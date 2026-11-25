"""Text layer. ALL text, numbers, labels, callouts, subtitles and provenance chips are drawn here,
from JSON, at compositing time — never by a generative model and never inside the graphics render.

Glyphs: PIL (supersampled sprites, cached). Shapes (pills, leader lines): Cairo.
Inline markup in text: *word* -> accent/keyword colour.
"""
import math
import re
from functools import lru_cache
from pathlib import Path

import cairo
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .render2d import rgb, ease_smooth, track_value
from .util import FONT_DIR

SS = 2  # supersampling for glyph sprites


@lru_cache(maxsize=64)
def font(file, size):
    p = Path(file)
    if not p.is_absolute():
        p = FONT_DIR / file
    return ImageFont.truetype(str(p), int(size))


def parse_runs(text):
    """'a *b* c' -> [('a ', False), ('b', True), (' c', False)]"""
    parts = re.split(r"(\*[^*]+\*)", text)
    out = []
    for p in parts:
        if not p:
            continue
        if p.startswith("*") and p.endswith("*") and len(p) > 2:
            out.append((p[1:-1], True))
        else:
            out.append((p, False))
    return out


STICKY_SYMBOL = re.compile(r"^[=+×→←↔≈≠<>≤≥—–-]{1,2}$")


def wrap_runs(text, fnt, max_w):
    """Greedy word wrap that keeps *markup* runs. Returns lines of (word, hl, glue); glue=True means the word
    continues the previous one without a space (e.g. '*больше*?' -> 'больше' + '?')."""
    words = []
    prev_ended_with_space = True
    for chunk, hl in parse_runs(text):
        parts = re.split(r"(\s+)", chunk)
        first = True
        for w in parts:
            if not w:
                continue
            if w.isspace():
                prev_ended_with_space = True
                first = False
                continue
            glue = bool(words) and first and not prev_ended_with_space
            words.append((w, hl, glue))
            prev_ended_with_space = False
            first = False
    lines, cur, cur_w = [], [], 0.0
    space = fnt.getlength(" ")
    for w, hl, glue in words:
        ww = fnt.getlength(w)
        add = ww + (0 if (glue or not cur) else space)
        if cur and max_w and cur_w + add > max_w and not glue:
            if STICKY_SYMBOL.match(w):           # '=', '—', '→' never start a line: keep with the previous word
                if len(cur) > 1:
                    last = cur.pop()
                    lines.append(cur)
                    cur = [(last[0], last[1], False)]
                    cur_w = fnt.getlength(last[0])
                    add = ww + space
                else:                            # single long word: allow a small overflow
                    cur.append((w, hl, glue))
                    cur_w += add
                    continue
            else:
                lines.append(cur)
                cur, cur_w = [], 0.0
                add = ww
                glue = False
        cur.append((w, hl, glue))
        cur_w += add
    if cur:
        lines.append(cur)
    return lines or [[("", False, False)]]


def line_width(ln, fnt):
    space = fnt.getlength(" ")
    return sum(fnt.getlength(w) + (0 if (g or i == 0) else space) for i, (w, _, g) in enumerate(ln))


class Sprite:
    def __init__(self, surface, w, h):
        self.surface, self.w, self.h = surface, w, h


class OverlayRenderer:
    def __init__(self, w, h, theme, lang="ru"):
        self.w, self.h, self.theme, self.lang = w, h, theme, lang
        self.cache = {}

    # ------------------------------------------------------------------ text sprites
    def text_sprite(self, text, font_key, size, color, hl_color=None, max_w=None, align="left", line_h=1.18,
                    upper=False):
        key = (text, font_key, size, color, hl_color, max_w, align, line_h, upper)
        if key in self.cache:
            return self.cache[key]
        if upper:
            text = text.upper()
        fpath = self.theme["fonts"].get(font_key, font_key)
        fnt = font(fpath, size * SS)
        lines = wrap_runs(text, fnt, (max_w or 0) * SS)
        asc, desc = fnt.getmetrics()
        lh = int((asc + desc) * line_h)
        space = fnt.getlength(" ")
        widths = [line_width(ln, fnt) for ln in lines]
        W = int(max(widths) + 4 * SS)
        H = int(lh * (len(lines) - 1) + asc + desc + 4 * SS)
        img = Image.new("RGBA", (max(1, W), max(1, H)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c_main = tuple(int(v * 255) for v in rgb(color))
        c_hl = tuple(int(v * 255) for v in rgb(hl_color or self.theme.get("accent", color)))
        for i, ln in enumerate(lines):
            x = 2 * SS
            if align == "center":
                x = (W - widths[i]) / 2
            elif align == "right":
                x = W - widths[i] - 2 * SS
            y = i * lh + 2 * SS
            for j, (w, hl, glue) in enumerate(ln):
                if j and not glue:
                    x += space
                d.text((x, y), w, font=fnt, fill=c_hl if hl else c_main)
                x += fnt.getlength(w)
        img = img.resize((max(1, W // SS), max(1, H // SS)), Image.LANCZOS)
        a = np.asarray(img).astype(np.float32)
        al = a[..., 3:4] / 255.0
        pre = (a[..., :3] * al).astype(np.uint8)
        bgra = np.ascontiguousarray(np.dstack([pre[..., 2], pre[..., 1], pre[..., 0], a[..., 3].astype(np.uint8)]))
        surf = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32,
                                                  bgra.shape[1], bgra.shape[0])
        sp = Sprite(surf, bgra.shape[1], bgra.shape[0])
        self.cache[key] = sp
        return sp

    # ------------------------------------------------------------------ geometry helpers
    @staticmethod
    def anchor_xy(x, y, w, h, anchor):
        ax = {"l": 0, "c": 0.5, "r": 1}[anchor[0]]
        ay = {"t": 0, "m": 0.5, "b": 1}[anchor[1]]
        return x - w * ax, y - h * ay

    @staticmethod
    def rounded(ctx, x, y, w, h, r):
        r = max(0, min(r, w / 2, h / 2))
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.close_path()

    def _alpha(self, it, t):
        t0, t1 = it.get("t0", 0.0), it.get("t1", 1e9)
        if t < t0 or t > t1:
            return 0.0
        fi, fo = it.get("fade_in", 0.25), it.get("fade_out", 0.2)
        a = 1.0
        if fi > 0 and t < t0 + fi:
            a = ease_smooth((t - t0) / fi)
        if fo > 0 and t1 < 1e8 and t > t1 - fo:
            a *= ease_smooth((t1 - t) / fo)
        return a

    def _get(self, it, key, f, t, default=None):
        tr = it.get("tracks", {})
        if key in tr:
            v = track_value(tr[key], f, t)
            return default if v is None else v
        return it.get(key, default)

    # ------------------------------------------------------------------ draw one text item
    def draw_label(self, ctx, it, f, t, a):
        th = self.theme
        text = it["text"]
        if it.get("text_track"):
            every = it.get("text_track_every", 1)
            text = it["text_track"][max(0, min(len(it["text_track"]) - 1, f // every))]
        size = round(it.get("size", 28))
        sp = self.text_sprite(text, it.get("font", "label"), size, it.get("color", th["ink"]), it.get("hl_color"),
                              it.get("max_w"), it.get("align", "left"), it.get("line_h", 1.18), it.get("upper", False))
        if it.get("max_h"):
            while sp.h > it["max_h"] and size > it.get("size", 28) * 0.5:
                size -= 1
                sp = self.text_sprite(text, it.get("font", "label"), size, it.get("color", th["ink"]),
                                      it.get("hl_color"), it.get("max_w"), it.get("align", "left"),
                                      it.get("line_h", 1.18), it.get("upper", False))
        x, y = float(self._get(it, "x", f, t)), float(self._get(it, "y", f, t))
        bg = it.get("bg")
        pad = bg.get("pad", [12, 6]) if bg else [0, 0]
        bw, bh = sp.w + 2 * pad[0], sp.h + 2 * pad[1]
        bx, by = self.anchor_xy(x, y, bw, bh, it.get("anchor", "lm"))
        # keep inside frame
        x0, y0, x1, y1 = it.get("bounds") or (0, 0, self.w, self.h)
        bx = min(max(x0 + 4, bx), x1 - bw - 4)
        by = min(max(y0 + 4, by), y1 - bh - 4)
        if bg:
            self.rounded(ctx, bx, by, bw, bh, bg.get("radius", 12))
            ctx.set_source_rgba(*rgb(bg.get("fill", th["panel"])), a * bg.get("opacity", 1.0))
            ctx.fill_preserve()
            if bg.get("stroke"):
                ctx.set_source_rgba(*rgb(bg["stroke"]), a)
                ctx.set_line_width(bg.get("stroke_w", 2))
                ctx.stroke()
            ctx.new_path()
        ctx.set_source_surface(sp.surface, bx + pad[0], by + pad[1])
        ctx.paint_with_alpha(a)
        return (bx, by, bw, bh)

    def draw_callout(self, ctx, it, f, t, a):
        th = self.theme
        cs = th["callout"]
        tx, ty = it["target"]
        if it.get("track_target_y"):
            ty = float(track_value(it["track_target_y"], f, t))
        if it.get("track_target_x"):
            tx = float(track_value(it["track_target_x"], f, t))
        px, py = it["pos"]
        if it.get("follow_y", bool(it.get("track_target_y"))):
            py = py + (ty - it["target"][1])
        lab = dict(it, kind="label", x=px, y=py, font=it.get("font", "label"), color=cs["text"],
                   anchor=it.get("anchor", "cm"), max_w=it.get("max_w", self.w * 0.42),
                   bg={"fill": cs["fill"], "stroke": cs["stroke"], "stroke_w": 2, "radius": 14, "pad": [14, 8]})
        # measure first to find the nearest edge for the leader
        sp = self.text_sprite(lab["text"], lab["font"], round(lab.get("size", 26)), cs["text"], None,
                              lab["max_w"], "left", 1.18, False)
        bw, bh = sp.w + 28, sp.h + 16
        bx, by = self.anchor_xy(px, py, bw, bh, lab["anchor"])
        x0, y0, x1, y1 = it.get("bounds") or (0, 0, self.w, self.h)
        bx = min(max(x0 + 4, bx), x1 - bw - 4)
        by = min(max(y0 + 4, by), y1 - bh - 4)
        ex = min(max(tx, bx), bx + bw)
        ey = min(max(ty, by), by + bh)
        # leader line draws itself in
        prog = min(1.0, (t - it.get("t0", 0)) / 0.35) if t >= it.get("t0", 0) else 0
        ctx.set_source_rgba(*rgb(cs["leader"]), a)
        ctx.set_line_width(2.2)
        ctx.move_to(ex, ey)
        ctx.line_to(ex + (tx - ex) * prog, ey + (ty - ey) * prog)
        ctx.stroke()
        ctx.arc(tx, ty, 5.5, 0, 2 * math.pi)
        ctx.set_source_rgba(*rgb(cs["leader"]), a * prog)
        ctx.fill()
        lab["x"], lab["y"], lab["anchor"] = bx, by, "lt"
        self.draw_label(ctx, lab, f, t, a)

    def draw_legend(self, ctx, it, f, t, a):
        th = self.theme
        x, y = it["x"], it["y"]
        size = it.get("size", 22)
        gap = it.get("gap", 26)
        horizontal = it.get("horizontal", True)
        cx, cy = x, y
        for e in it["items"]:
            ctx.set_source_rgba(*rgb(e["color"]), a)
            if e.get("shape", "dot") == "dot":
                ctx.arc(cx + size * 0.4, cy, size * 0.38, 0, 2 * math.pi)
            else:
                self.rounded(ctx, cx, cy - size * 0.38, size * 0.8, size * 0.76, 4)
            ctx.fill_preserve()
            ctx.set_source_rgba(*rgb(th["ink"]), a * 0.6)
            ctx.set_line_width(1.5)
            ctx.stroke()
            sp = self.text_sprite(e["text"], "label", size, it.get("color", th["ink"]))
            ctx.set_source_surface(sp.surface, cx + size * 1.05, cy - sp.h / 2)
            ctx.paint_with_alpha(a)
            if horizontal:
                cx += size * 1.05 + sp.w + gap
            else:
                cy += size * 1.6

    def draw_header(self, ctx, it, f, t, a):
        """Kicker (mono, small caps) + number badge + display title with *accent* words."""
        th = self.theme
        hs = th["header"]
        x, y = it["x"], it["y"]
        max_w = it.get("max_w", self.w - 2 * x)
        ksz, tsz = it.get("kicker_size", 22), it.get("title_size", 50)
        cy = y
        if it.get("badge") or it.get("kicker"):
            bx = x
            if it.get("badge"):
                bsp = self.text_sprite(str(it["badge"]), "mono", ksz + 4, hs["badge_text"])
                bw, bh = bsp.w + 18, bsp.h + 8
                self.rounded(ctx, bx, cy, bw, bh, 8)
                ctx.set_source_rgba(*rgb(hs["badge_fill"]), a)
                ctx.fill()
                ctx.set_source_surface(bsp.surface, bx + 9, cy + 4)
                ctx.paint_with_alpha(a)
                bx += bw + 14
            else:
                bh = ksz * 1.4
            if it.get("kicker"):
                ksp = self.text_sprite(it["kicker"].upper(), "mono", ksz, hs.get("kicker_color", th["ink_soft"]))
                ctx.set_source_surface(ksp.surface, bx, cy + (bh - ksp.h) / 2)
                ctx.paint_with_alpha(a)
            cy += bh + 12
        if it.get("title"):
            title = it["title"]
            upper = hs.get("title_case") == "upper"
            max_lines = it.get("max_lines", 2)
            while True:
                tsp = self.text_sprite(title, "display", tsz, hs["title_color"], hs["accent_word_color"], max_w,
                                       "left", 1.06, upper)
                f_ = font(self.theme["fonts"]["display"], tsz * SS)
                n_lines = len(wrap_runs(title.upper() if upper else title, f_, max_w * SS))
                if n_lines <= max_lines or tsz <= it.get("title_size", 50) * 0.6:
                    break
                tsz -= 2
            ctx.set_source_surface(tsp.surface, x - 2, cy)
            ctx.paint_with_alpha(a)
            cy += tsp.h
        if it.get("spec_line"):
            ssp = self.text_sprite(it["spec_line"], "body_regular", ksz, th["ink_soft"], max_w=max_w)
            ctx.set_source_surface(ssp.surface, x, cy + 6)
            ctx.paint_with_alpha(a)

    def draw_subtitle(self, ctx, it, f, t, a):
        ss = self.theme["subtitle"]
        size = it.get("size", 34)
        max_w = it.get("max_w", self.w * 0.84)
        sp = self.text_sprite(it["text"], "body", size, ss["text"], ss.get("keyword_color"), max_w, "center", 1.16)
        padx, pady = size * 0.6, size * 0.34
        bw, bh = sp.w + 2 * padx, sp.h + 2 * pady
        bx, by = it["x"] - bw / 2, it["y"] - bh / 2
        self.rounded(ctx, bx, by, bw, bh, ss.get("radius", 20))
        ctx.set_source_rgba(*rgb(ss["fill"]), a * ss.get("opacity", 1.0))
        ctx.fill_preserve()
        if ss.get("stroke"):
            ctx.set_source_rgba(*rgb(ss["stroke"]), a)
            ctx.set_line_width(ss.get("stroke_w", 2))
            ctx.stroke()
        ctx.new_path()
        ctx.set_source_surface(sp.surface, bx + padx, by + pady)
        ctx.paint_with_alpha(a)
        return bw, bh

    def draw_provenance(self, ctx, it, f, t, a):
        pv = self.theme["provenance"]
        size = it.get("size", 20)
        sp = self.text_sprite(it["text"], "mono", size, pv["text"])
        dot = size * 0.32
        bw, bh = sp.w + 26 + dot * 2 + 8, sp.h + 10
        bx, by = self.anchor_xy(it["x"], it["y"], bw, bh, it.get("anchor", "rt"))
        self.rounded(ctx, bx, by, bw, bh, bh / 2)
        ctx.set_source_rgba(*rgb(pv["fill"]), a * 0.92)
        ctx.fill()
        ctx.arc(bx + 13 + dot, by + bh / 2, dot, 0, 2 * math.pi)
        ctx.set_source_rgba(*rgb(it.get("dot", self.theme["accent"])), a)
        ctx.fill()
        ctx.set_source_surface(sp.surface, bx + 13 + dot * 2 + 8, by + 5)
        ctx.paint_with_alpha(a)

    # ------------------------------------------------------------------ frame
    def render(self, items, f, t):
        """Returns premultiplied RGBA uint8 array (H, W, 4) or None if nothing visible."""
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.w, self.h)
        ctx = cairo.Context(surf)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        drawn = False
        for it in items:
            a = self._alpha(it, t) * it.get("opacity", 1.0)
            if a <= 0.003:
                continue
            drawn = True
            ctx.save()
            k = it.get("kind", "label")
            lf = it.get("_lf", f)            # tracks are indexed by the frame inside the item's own shot
            if k == "label":
                self.draw_label(ctx, it, lf, t, a)
            elif k == "callout":
                self.draw_callout(ctx, it, lf, t, a)
            elif k == "legend":
                self.draw_legend(ctx, it, lf, t, a)
            elif k == "header":
                self.draw_header(ctx, it, lf, t, a)
            elif k == "subtitle":
                self.draw_subtitle(ctx, it, lf, t, a)
            elif k == "provenance":
                self.draw_provenance(ctx, it, lf, t, a)
            ctx.restore()
        if not drawn:
            return None
        surf.flush()
        buf = np.ndarray((self.h, self.w, 4), np.uint8, buffer=surf.get_data())
        return buf[..., [2, 1, 0, 3]].copy()      # premultiplied RGBA


def composite(base_rgb, over_rgba_premul):
    """out = over + base * (1 - alpha) on uint8 arrays."""
    if over_rgba_premul is None:
        return base_rgb
    a = over_rgba_premul[..., 3:4].astype(np.uint16)
    out = over_rgba_premul[..., :3].astype(np.uint16) + (base_rgb.astype(np.uint16) * (255 - a) + 127) // 255
    return np.clip(out, 0, 255).astype(np.uint8)
