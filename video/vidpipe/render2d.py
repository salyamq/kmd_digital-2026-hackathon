"""Deterministic 2D renderer: draws a JSON draw-list per frame with Cairo, pipes frames to ffmpeg.

Templates never draw; they emit a draw-list ("layout") in pixel coordinates (origin top-left, y down).
All motion comes from per-frame tracks computed from the state model, so the same numbers drive
picture, chart and (in overlays.py) the text labels.

Item keys (all optional except type + geometry):
  t0, t1               visible interval in shot seconds
  fade_in, fade_out    seconds; appear: fade | draw | grow | none
  opacity, fill, stroke, lw, dash, pattern{kind,color,spacing,size}
  tracks{key: [per-frame values] | {"kf": [[t, v], ...], "ease": "linear"|"smooth"}}
Types: background, rect, circle, ellipse, polygon, polyline, line, arrow, image, field, points, group, icon
"""
import math
import subprocess
from functools import lru_cache
from pathlib import Path

import cairo
import numpy as np

from .util import log


# ------------------------------------------------------------------ colors & tracks

@lru_cache(maxsize=512)
def rgb(hexstr):
    h = str(hexstr).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def shade(hexstr, k):
    """k<1 darker, k>1 lighter."""
    r, g, b = rgb(hexstr)
    if k < 1:
        r, g, b = r * k, g * k, b * k
    else:
        r, g, b = r + (1 - r) * (k - 1), g + (1 - g) * (k - 1), b + (1 - b) * (k - 1)
    return "#%02x%02x%02x" % tuple(int(max(0, min(1, c)) * 255) for c in (r, g, b))


def ease_smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def track_value(spec, f, t):
    if isinstance(spec, list):
        if not spec:
            return None
        return spec[max(0, min(len(spec) - 1, f))]
    if isinstance(spec, dict) and "kf" in spec:
        kf = spec["kf"]
        if t <= kf[0][0]:
            return kf[0][1]
        for (ta, va), (tb, vb) in zip(kf, kf[1:]):
            if ta <= t <= tb:
                u = (t - ta) / max(1e-9, tb - ta)
                if spec.get("ease", "smooth") == "smooth":
                    u = ease_smooth(u)
                if isinstance(va, (list, tuple)):
                    return [a + (b - a) * u for a, b in zip(va, vb)]
                return va + (vb - va) * u
        return kf[-1][1]
    return spec


def get(item, key, f, t, default=None):
    tr = item.get("tracks", {})
    if key in tr:
        v = track_value(tr[key], f, t)
        return default if v is None else v
    return item.get(key, default)


def visibility(item, t):
    """Returns (alpha_factor, progress) where progress in [0,1] for draw/grow appear modes."""
    t0 = item.get("t0", 0.0)
    t1 = item.get("t1", 1e9)
    if t < t0 or t > t1:
        return 0.0, 0.0
    fi = item.get("fade_in", 0.3)
    fo = item.get("fade_out", 0.25)
    appear = item.get("appear", "fade")
    a = 1.0
    prog = 1.0
    if fi > 0 and t < t0 + fi:
        u = ease_smooth((t - t0) / fi)
        if appear == "fade":
            a = u
        elif appear in ("draw", "grow"):
            prog = u
            a = min(1.0, u * 3)
        elif appear == "none":
            pass
    if fo > 0 and t1 < 1e8 and t > t1 - fo:
        a *= ease_smooth((t1 - t) / fo)
    return a, prog


# ------------------------------------------------------------------ background

_BG_CACHE = {}


def background_array(w, h, theme, seed=7):
    key = (w, h, theme["id"])
    if key in _BG_CACHE:
        return _BG_CACHE[key]
    rng = np.random.default_rng(seed)
    base = np.array(rgb(theme["bg"]))
    vig = np.array(rgb(theme.get("bg_vignette", theme["bg"])))
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
    k = np.clip(d ** 1.6, 0, 1)[..., None]
    img = base * (1 - k) + vig * k
    amp = theme.get("paper_noise", 0.0)
    if amp:
        # paper grain: fine noise + soft blotches (deterministic)
        fine = rng.normal(0, 1, (h, w))
        coarse = rng.normal(0, 1, (h // 24 + 2, w // 24 + 2))
        from scipy.ndimage import zoom, gaussian_filter
        coarse = zoom(coarse, (h / coarse.shape[0], w / coarse.shape[1]), order=1)[:h, :w]
        coarse = gaussian_filter(coarse, 6)
        n = (0.7 * fine + 0.55 * coarse) * amp * 0.3
        img = img + n[..., None]
    arr = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    _BG_CACHE[key] = arr
    return arr


# ------------------------------------------------------------------ the renderer

class Renderer:
    def __init__(self, w, h, theme, base_dir="."):
        self.w, self.h = w, h
        self.theme = theme
        self.base = Path(base_dir)
        self._img_cache = {}
        self._npz_cache = {}
        bg = background_array(w, h, theme)
        bgra = np.zeros((h, w, 4), np.uint8)
        bgra[..., 0], bgra[..., 1], bgra[..., 2], bgra[..., 3] = bg[..., 2], bg[..., 1], bg[..., 0], 255
        self._bg_surface = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32, w, h)

    # -- resources
    def _npz(self, path):
        p = str(self.base / path) if not Path(path).is_absolute() else path
        if p not in self._npz_cache:
            with np.load(p) as z:
                self._npz_cache[p] = {k: z[k] for k in z.files}
        return self._npz_cache[p]

    def _image_surface(self, path, w, h):
        key = (path, int(w), int(h))
        if key in self._img_cache:
            return self._img_cache[key]
        from PIL import Image
        p = str(self.base / path) if not Path(path).is_absolute() else path
        im = Image.open(p).convert("RGBA").resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
        a = np.asarray(im).astype(np.float32)
        alpha = a[..., 3:4] / 255.0
        pre = (a[..., :3] * alpha).astype(np.uint8)          # cairo wants premultiplied BGRA
        bgra = np.dstack([pre[..., 2], pre[..., 1], pre[..., 0], a[..., 3].astype(np.uint8)])
        surf = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32,
                                                  bgra.shape[1], bgra.shape[0])
        self._img_cache[key] = surf
        return surf

    # -- frame
    def render_frame(self, items, f, t):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.w, self.h)
        ctx = cairo.Context(surf)
        ctx.set_source_surface(self._bg_surface, 0, 0)
        ctx.paint()
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        for it in items:
            self.draw(ctx, it, f, t, 1.0)
        surf.flush()
        buf = np.ndarray((self.h, self.w, 4), np.uint8, buffer=surf.get_data())
        return buf[..., [2, 1, 0]].copy()

    def draw(self, ctx, it, f, t, parent_alpha):
        a, prog = visibility(it, t)
        a *= parent_alpha * float(get(it, "opacity", f, t, 1.0))
        if a <= 0.003:
            return
        fn = getattr(self, "_d_" + it["type"], None)
        if fn is None:
            return
        ctx.save()
        if it.get("appear") == "grow" and prog < 1.0:
            ox, oy = it.get("grow_origin", self._center(it, f, t))
            ctx.translate(ox, oy)
            s = max(0.001, prog)
            ctx.scale(s, s)
            ctx.translate(-ox, -oy)
        fn(ctx, it, f, t, a, prog)
        ctx.restore()

    def _center(self, it, f, t):
        if "x" in it and "w" in it:
            return get(it, "x", f, t) + get(it, "w", f, t) / 2, get(it, "y", f, t) + get(it, "h", f, t) / 2
        if "cx" in it:
            return get(it, "cx", f, t), get(it, "cy", f, t)
        if "pts" in it and it["pts"]:
            p = np.asarray(it["pts"])
            return float(p[:, 0].mean()), float(p[:, 1].mean())
        return self.w / 2, self.h / 2

    # -- paint helpers
    def _fill_stroke(self, ctx, it, f, t, a, path_fn):
        fill = get(it, "fill", f, t)
        stroke = get(it, "stroke", f, t)
        if fill:
            path_fn()
            ctx.set_source_rgba(*rgb(fill), a * it.get("fill_opacity", 1.0))
            if it.get("pattern") and it["pattern"].get("kind", "none") != "none":
                ctx.fill_preserve()
                ctx.save()
                ctx.clip()
                self._pattern(ctx, it, a)
                ctx.restore()
                ctx.new_path()
            else:
                ctx.fill()
        if stroke:
            path_fn()
            ctx.set_source_rgba(*rgb(stroke), a)
            ctx.set_line_width(get(it, "lw", f, t, 2.0))
            if it.get("dash"):
                off = float(get(it, "dash_offset", f, t, 0.0))
                ctx.set_dash(it["dash"], off)
            ctx.stroke()
            ctx.set_dash([])

    def _pattern(self, ctx, it, a):
        p = it["pattern"]
        kind = p.get("kind", "dots")
        col = p.get("color") or shade(it.get("fill", "#888888"), 0.62)
        sp = float(p.get("spacing", 16))
        sz = float(p.get("size", 2.2))
        x1, y1, x2, y2 = ctx.clip_extents()
        ctx.set_source_rgba(*rgb(col), a * p.get("opacity", 0.75))
        ctx.set_line_width(max(1.0, sz * 0.8))
        rng = np.random.default_rng(p.get("seed", 3))
        row = 0
        y = y1 - sp
        while y < y2 + sp:
            off = (sp / 2) if row % 2 else 0
            x = x1 - sp + off
            while x < x2 + sp:
                jx, jy = rng.uniform(-0.18, 0.18, 2) * sp
                if kind == "dots":
                    ctx.arc(x + jx, y + jy, sz, 0, 2 * math.pi); ctx.fill()
                elif kind == "circles":
                    ctx.arc(x + jx, y + jy, sz * 2.2, 0, 2 * math.pi); ctx.stroke()
                elif kind == "dashes":
                    ctx.move_to(x - sp * 0.28, y); ctx.line_to(x + sp * 0.28, y); ctx.stroke()
                elif kind == "dots_dashes":
                    if (row + int(x / sp)) % 2:
                        ctx.arc(x, y, sz, 0, 2 * math.pi); ctx.fill()
                    else:
                        ctx.move_to(x - sp * 0.25, y); ctx.line_to(x + sp * 0.25, y); ctx.stroke()
                elif kind == "cross":
                    s = sp * 0.18
                    ctx.move_to(x - s, y - s); ctx.line_to(x + s, y + s)
                    ctx.move_to(x - s, y + s); ctx.line_to(x + s, y - s); ctx.stroke()
                elif kind == "hatch":
                    ctx.move_to(x - sp / 2, y + sp / 2); ctx.line_to(x + sp / 2, y - sp / 2); ctx.stroke()
                x += sp
            if kind == "bricks":
                ctx.move_to(x1, y + sp / 2); ctx.line_to(x2, y + sp / 2); ctx.stroke()
                xx = x1 - sp + ((sp) if row % 2 else 0)
                while xx < x2 + sp:
                    ctx.move_to(xx, y - sp / 2); ctx.line_to(xx, y + sp / 2); ctx.stroke()
                    xx += sp * 2
            y += sp
            row += 1

    # -- primitives
    def _d_background(self, ctx, it, f, t, a, prog):
        ctx.set_source_surface(self._bg_surface, 0, 0)
        ctx.paint_with_alpha(a)

    def _rounded(self, ctx, x, y, w, h, r):
        r = max(0.0, min(r, w / 2, h / 2))
        if r <= 0:
            ctx.rectangle(x, y, w, h)
            return
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.close_path()

    def _d_rect(self, ctx, it, f, t, a, prog):
        x, y = get(it, "x", f, t), get(it, "y", f, t)
        w, h = get(it, "w", f, t), get(it, "h", f, t)
        r = get(it, "r", f, t, 0)
        if it.get("appear") == "draw" and prog < 1:
            # reveal by growing along the item's "grow_dir" (default: downwards)
            d = it.get("grow_dir", "down")
            if d == "down":
                h = h * prog
            elif d == "up":
                y, h = y + h * (1 - prog), h * prog
            elif d == "right":
                w = w * prog
            elif d == "left":
                x, w = x + w * (1 - prog), w * prog
        if it.get("shadow"):
            ctx.save()
            self._rounded(ctx, x + 5, y + 7, w, h, r)
            ctx.set_source_rgba(0, 0, 0, 0.13 * a)
            ctx.fill()
            ctx.restore()
        self._fill_stroke(ctx, it, f, t, a, lambda: self._rounded(ctx, x, y, w, h, r))

    def _d_circle(self, ctx, it, f, t, a, prog):
        cx, cy, r = get(it, "cx", f, t), get(it, "cy", f, t), get(it, "r", f, t)
        if r <= 0:
            return
        def path():
            ctx.new_sub_path()
            ctx.arc(cx, cy, r, 0, 2 * math.pi)
        if it.get("appear") == "draw" and prog < 1:
            ctx.new_path()
            ctx.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * prog)
            ctx.set_source_rgba(*rgb(it.get("stroke") or it.get("fill") or "#000"), a)
            ctx.set_line_width(it.get("lw", 2))
            ctx.stroke()
            return
        self._fill_stroke(ctx, it, f, t, a, path)

    def _d_ellipse(self, ctx, it, f, t, a, prog):
        cx, cy = get(it, "cx", f, t), get(it, "cy", f, t)
        rx, ry = get(it, "rx", f, t), get(it, "ry", f, t)
        def path():
            ctx.save(); ctx.translate(cx, cy); ctx.scale(max(rx, 1e-3), max(ry, 1e-3))
            ctx.new_sub_path(); ctx.arc(0, 0, 1, 0, 2 * math.pi); ctx.restore()
        self._fill_stroke(ctx, it, f, t, a, path)

    def _d_polygon(self, ctx, it, f, t, a, prog):
        pts = get(it, "pts", f, t)
        if not pts or len(pts) < 3:
            return
        def path():
            ctx.move_to(*pts[0])
            for p in pts[1:]:
                ctx.line_to(*p)
            ctx.close_path()
        self._fill_stroke(ctx, it, f, t, a, path)

    def _d_polyline(self, ctx, it, f, t, a, prog):
        pts = get(it, "pts", f, t)
        if pts is None:
            pts = self._npz(it["npz"])[it["key"]]
        pts = np.asarray(pts, dtype=float)
        if len(pts) < 2:
            return
        n = float(get(it, "reveal_n", f, t, len(pts)))
        if it.get("appear") == "draw" and prog < 1:
            n = min(n, 1 + (len(pts) - 1) * prog)
        n = max(1.0, min(len(pts), n))
        k = int(math.floor(n))
        seg = pts[:k]
        if k < len(pts) and n > k:
            frac = n - k
            last = pts[k - 1] + (pts[k] - pts[k - 1]) * frac
            seg = np.vstack([seg, last])
        if len(seg) < 2:
            return
        if it.get("fill_to"):           # area fill to a baseline (x=const or y=const)
            ft = it["fill_to"]
            ctx.move_to(*seg[0])
            for p in seg[1:]:
                ctx.line_to(*p)
            if "x" in ft:
                ctx.line_to(ft["x"], seg[-1][1]); ctx.line_to(ft["x"], seg[0][1])
            else:
                ctx.line_to(seg[-1][0], ft["y"]); ctx.line_to(seg[0][0], ft["y"])
            ctx.close_path()
            ctx.set_source_rgba(*rgb(ft.get("color", it.get("stroke", "#000"))), a * ft.get("opacity", 0.25))
            ctx.fill()
        ctx.move_to(*seg[0])
        for p in seg[1:]:
            ctx.line_to(*p)
        ctx.set_source_rgba(*rgb(it.get("stroke", "#000")), a)
        ctx.set_line_width(get(it, "lw", f, t, 3.0))
        if it.get("dash"):
            ctx.set_dash(it["dash"], float(get(it, "dash_offset", f, t, 0)))
        ctx.stroke()
        ctx.set_dash([])
        head = it.get("head")
        if head:
            hx, hy = seg[-1]
            ctx.arc(hx, hy, head.get("r", 7), 0, 2 * math.pi)
            ctx.set_source_rgba(*rgb(head.get("fill", it.get("stroke", "#000"))), a)
            ctx.fill_preserve()
            if head.get("stroke"):
                ctx.set_source_rgba(*rgb(head["stroke"]), a)
                ctx.set_line_width(head.get("lw", 2))
                ctx.stroke()
            ctx.new_path()

    def _d_line(self, ctx, it, f, t, a, prog):
        x1, y1 = get(it, "x1", f, t), get(it, "y1", f, t)
        x2, y2 = get(it, "x2", f, t), get(it, "y2", f, t)
        if it.get("appear") == "draw":
            x2, y2 = x1 + (x2 - x1) * prog, y1 + (y2 - y1) * prog
        ctx.move_to(x1, y1)
        ctx.line_to(x2, y2)
        ctx.set_source_rgba(*rgb(get(it, "stroke", f, t, "#000")), a)
        ctx.set_line_width(get(it, "lw", f, t, 2.0))
        if it.get("dash"):
            ctx.set_dash(it["dash"], float(get(it, "dash_offset", f, t, 0)))
        ctx.stroke()
        ctx.set_dash([])

    def _d_arrow(self, ctx, it, f, t, a, prog):
        x1, y1 = get(it, "x1", f, t), get(it, "y1", f, t)
        x2, y2 = get(it, "x2", f, t), get(it, "y2", f, t)
        if it.get("appear") == "draw":
            x2, y2 = x1 + (x2 - x1) * prog, y1 + (y2 - y1) * prog
        col = get(it, "stroke", f, t, "#000")
        lw = get(it, "lw", f, t, 4.0)
        hs = it.get("head", lw * 3.2)
        ang = math.atan2(y2 - y1, x2 - x1)
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1:
            return
        bx, by = x2 - hs * 0.8 * math.cos(ang), y2 - hs * 0.8 * math.sin(ang)
        ctx.move_to(x1, y1)
        ctx.line_to(bx, by)
        ctx.set_source_rgba(*rgb(col), a)
        ctx.set_line_width(lw)
        if it.get("dash"):
            ctx.set_dash(it["dash"], float(get(it, "dash_offset", f, t, 0)))
        ctx.stroke()
        ctx.set_dash([])
        ctx.move_to(x2, y2)
        ctx.line_to(x2 - hs * math.cos(ang - 0.45), y2 - hs * math.sin(ang - 0.45))
        ctx.line_to(x2 - hs * math.cos(ang + 0.45), y2 - hs * math.sin(ang + 0.45))
        ctx.close_path()
        ctx.fill()

    def _d_image(self, ctx, it, f, t, a, prog):
        x, y, w, h = (get(it, k, f, t) for k in ("x", "y", "w", "h"))
        zoom = float(get(it, "zoom", f, t, 1.0))
        surf = self._image_surface(it["src"], w * zoom, h * zoom)
        ctx.rectangle(x, y, w, h)
        ctx.clip()
        px = float(get(it, "pan_x", f, t, 0.5))
        py = float(get(it, "pan_y", f, t, 0.5))
        ctx.set_source_surface(surf, x - (w * zoom - w) * px, y - (h * zoom - h) * py)
        ctx.paint_with_alpha(a)

    def _d_field(self, ctx, it, f, t, a, prog):
        """Scalar field image from an npz array [ny, nx, nt] (or [ny,nx]) colorized with a colormap.
        frame index into the last axis comes from the 'k' track (float -> linear blend)."""
        arr = self._npz(it["npz"])[it["key"]]
        k = float(get(it, "k", f, t, 0))
        if arr.ndim == 3:
            k0 = int(max(0, min(arr.shape[2] - 1, math.floor(k))))
            k1 = min(arr.shape[2] - 1, k0 + 1)
            u = k - k0
            fld = arr[:, :, k0] * (1 - u) + arr[:, :, k1] * u
        else:
            fld = arr
        vmin, vmax = it.get("vmin", float(np.nanmin(arr))), it.get("vmax", float(np.nanmax(arr)))
        z = np.clip((fld - vmin) / max(1e-12, vmax - vmin), 0, 1)
        if it.get("gamma"):
            z = z ** it["gamma"]
        lut = _lut(tuple(it.get("cmap", ["#ffffff", "#000000"])))
        rgbimg = lut[(z * 255).astype(np.int32)]
        alpha_mask = it.get("mask_key")
        al = np.full(fld.shape, 255, np.uint8)
        if alpha_mask:
            al = (self._npz(it["npz"])[alpha_mask] * 255).astype(np.uint8)
        a16 = al.astype(np.uint16)
        rgb16 = rgbimg.astype(np.uint16)
        bgra = np.dstack([(rgb16[..., 2] * a16 // 255).astype(np.uint8), (rgb16[..., 1] * a16 // 255).astype(np.uint8),
                          (rgb16[..., 0] * a16 // 255).astype(np.uint8), al])
        bgra = np.ascontiguousarray(bgra)
        surf = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32,
                                                  bgra.shape[1], bgra.shape[0])
        x, y, w, h = (get(it, kk, f, t) for kk in ("x", "y", "w", "h"))
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(w / bgra.shape[1], h / bgra.shape[0])
        pat = cairo.SurfacePattern(surf)
        pat.set_filter(cairo.FILTER_GOOD)
        ctx.set_source(pat)
        ctx.paint_with_alpha(a)
        ctx.restore()

    def _d_points(self, ctx, it, f, t, a, prog):
        """Per-frame point cloud from npz: P[frame] -> (N, 3) rows x, y, alpha."""
        P = self._npz(it["npz"])[it["key"]]
        fr = P[max(0, min(P.shape[0] - 1, f))]
        col = rgb(it.get("fill", "#000"))
        r = it.get("r", 3.0)
        glow = it.get("glow")
        for x, y, al in fr:
            if al <= 0.01:
                continue
            if glow:
                ctx.arc(x, y, r * 2.4, 0, 2 * math.pi)
                ctx.set_source_rgba(*rgb(glow), a * al * 0.25)
                ctx.fill()
            ctx.arc(x, y, r, 0, 2 * math.pi)
            ctx.set_source_rgba(*col, a * al)
            ctx.fill()

    def _d_group(self, ctx, it, f, t, a, prog):
        clip = it.get("clip")
        if clip:
            if clip.get("type") == "circle":
                ctx.arc(get(clip, "cx", f, t), get(clip, "cy", f, t), get(clip, "r", f, t), 0, 2 * math.pi)
            else:
                self._rounded(ctx, clip["x"], clip["y"], clip["w"], clip["h"], clip.get("r", 0))
            ctx.clip()
        tx, ty = float(get(it, "tx", f, t, 0)), float(get(it, "ty", f, t, 0))
        s = float(get(it, "scale", f, t, 1.0))
        ox, oy = get(it, "origin", f, t, [0, 0])
        ctx.translate(tx + ox, ty + oy)
        ctx.scale(s, s)
        ctx.translate(-ox, -oy)
        for sub in it.get("items", []):
            self.draw(ctx, sub, f, t, a)

    def _d_icon(self, ctx, it, f, t, a, prog):
        """Simple vector icons (no text): check, cross, question, arrow, clock, db, gear, eye, warning."""
        cx, cy, s = get(it, "cx", f, t), get(it, "cy", f, t), get(it, "size", f, t, 40)
        col = rgb(get(it, "stroke", f, t, "#000"))
        kind = it.get("kind", "check")
        lw = it.get("lw", max(3.0, s * 0.12))
        ctx.set_line_width(lw)
        ctx.set_source_rgba(*col, a)
        h = s / 2
        if it.get("fill"):
            ctx.arc(cx, cy, h * 1.25, 0, 2 * math.pi)
            ctx.set_source_rgba(*rgb(it["fill"]), a)
            ctx.fill()
            ctx.set_source_rgba(*col, a)
        if kind == "check":
            ctx.move_to(cx - h * 0.6, cy + h * 0.02)
            ctx.line_to(cx - h * 0.15, cy + h * 0.5)
            ctx.line_to(cx + h * 0.65, cy - h * 0.45)
            ctx.stroke()
        elif kind == "cross":
            ctx.move_to(cx - h * 0.5, cy - h * 0.5); ctx.line_to(cx + h * 0.5, cy + h * 0.5)
            ctx.move_to(cx - h * 0.5, cy + h * 0.5); ctx.line_to(cx + h * 0.5, cy - h * 0.5)
            ctx.stroke()
        elif kind == "question":
            ctx.arc(cx, cy - h * 0.25, h * 0.38, math.pi * 1.05, math.pi * 2.3)
            ctx.line_to(cx, cy + h * 0.2)
            ctx.stroke()
            ctx.arc(cx, cy + h * 0.55, lw * 0.6, 0, 2 * math.pi); ctx.fill()
        elif kind == "arrow":
            ctx.move_to(cx - h * 0.6, cy); ctx.line_to(cx + h * 0.5, cy); ctx.stroke()
            ctx.move_to(cx + h * 0.15, cy - h * 0.4); ctx.line_to(cx + h * 0.6, cy); ctx.line_to(cx + h * 0.15, cy + h * 0.4)
            ctx.stroke()
        elif kind == "clock":
            ctx.arc(cx, cy, h * 0.75, 0, 2 * math.pi); ctx.stroke()
            ctx.move_to(cx, cy); ctx.line_to(cx, cy - h * 0.45); ctx.move_to(cx, cy); ctx.line_to(cx + h * 0.35, cy)
            ctx.stroke()
        elif kind == "db":
            for k in range(3):
                yy = cy - h * 0.5 + k * h * 0.5
                ctx.save(); ctx.translate(cx, yy); ctx.scale(h * 0.7, h * 0.22)
                ctx.arc(0, 0, 1, 0, 2 * math.pi); ctx.restore(); ctx.stroke()
            ctx.move_to(cx - h * 0.7, cy - h * 0.5); ctx.line_to(cx - h * 0.7, cy + h * 0.5)
            ctx.move_to(cx + h * 0.7, cy - h * 0.5); ctx.line_to(cx + h * 0.7, cy + h * 0.5); ctx.stroke()
        elif kind == "gear":
            ctx.arc(cx, cy, h * 0.42, 0, 2 * math.pi); ctx.stroke()
            for k in range(8):
                an = k * math.pi / 4
                ctx.move_to(cx + h * 0.55 * math.cos(an), cy + h * 0.55 * math.sin(an))
                ctx.line_to(cx + h * 0.82 * math.cos(an), cy + h * 0.82 * math.sin(an))
            ctx.stroke()
        elif kind == "eye":
            ctx.save(); ctx.translate(cx, cy); ctx.scale(h * 0.85, h * 0.45)
            ctx.arc(0, 0, 1, 0, 2 * math.pi); ctx.restore(); ctx.stroke()
            ctx.arc(cx, cy, h * 0.2, 0, 2 * math.pi); ctx.fill()
        elif kind == "warning":
            ctx.move_to(cx, cy - h * 0.7); ctx.line_to(cx + h * 0.75, cy + h * 0.6); ctx.line_to(cx - h * 0.75, cy + h * 0.6)
            ctx.close_path(); ctx.stroke()
            ctx.move_to(cx, cy - h * 0.2); ctx.line_to(cx, cy + h * 0.15); ctx.stroke()
            ctx.arc(cx, cy + h * 0.38, lw * 0.5, 0, 2 * math.pi); ctx.fill()
        elif kind == "dot":
            ctx.arc(cx, cy, h * 0.35, 0, 2 * math.pi); ctx.fill()


@lru_cache(maxsize=32)
def _lut(cmap):
    stops = np.array([rgb(c) for c in cmap])
    xs = np.linspace(0, 1, len(stops))
    g = np.linspace(0, 1, 256)
    lut = np.stack([np.interp(g, xs, stops[:, i]) for i in range(3)], axis=1)
    return (lut * 255).astype(np.uint8)


# ------------------------------------------------------------------ video writer

def render_layout(layout, out_mp4, theme, base_dir, qa_frames=(), qa_dir=None):
    """Render a template layout to an mp4 (no audio, no text). Returns list of saved QA frame paths."""
    w, h, fps, n = layout["w"], layout["h"], layout["fps"], layout["n_frames"]
    r = Renderer(w, h, theme, base_dir)
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "14",
           "-pix_fmt", "yuv420p", str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    saved = []
    qa_set = set(int(q) for q in qa_frames)
    items = layout["items"]
    for fidx in range(n):
        t = fidx / fps
        frame = r.render_frame(items, fidx, t)
        proc.stdin.write(frame.tobytes())
        if fidx in qa_set and qa_dir:
            from PIL import Image
            p = Path(qa_dir) / f"{out_mp4.stem}_f{fidx:05d}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(frame).save(p)
            saved.append(str(p))
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {out_mp4}")
    return saved
