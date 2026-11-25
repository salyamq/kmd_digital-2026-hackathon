"""Template base class and layout helpers shared by all scene templates.

A template turns (scene spec params + state-model output + timing) into a layout:
  items   graphics draw-list for render2d (no text)
  texts   text items for the overlay/compositing step (labels, ticks, callouts)
  probes  exact-colour markers QA looks for in rendered frames
  checks  invariants QA verifies (model-level and frame-level)
  state   per-frame arrays derived from the model (saved to 04_models/<shot>_state.npz)
"""
import math
import re

import numpy as np


class Ctx:
    """Everything a template may use besides its params and model output."""

    def __init__(self, w, h, fps, duration, theme, domain, lang, i18n, cues=None, shot_dir=None,
                 orientation="portrait", shot_id="S", class_="B"):
        self.w, self.h, self.fps = w, h, fps
        self.duration = max(0.5, float(duration))
        self.n = int(round(self.duration * fps))
        self.theme = theme
        self.domain = domain
        self.lang = lang
        self.T = i18n.get(lang, i18n["en"])
        self.cues = cues or {}          # line_id -> [t_start, t_end] relative to shot start
        self.shot_dir = shot_dir
        self.orientation = orientation
        self.portrait = orientation == "portrait"
        self.shot_id = shot_id
        self.class_ = class_
        # safe content box (header at top, subtitles at bottom are composited later)
        if self.portrait:
            self.box = (40, 262, w - 80, 700)          # x, y, w, h
            self.font_scale = 1.0
        else:
            self.box = (110, 215, w - 220, 640)
            self.font_scale = 1.42
        self.times = np.arange(self.n) / fps

    # -- timing
    def at(self, spec, default=0.0):
        """Resolve a time reference: number (s), 'L3' (start of line L3), 'L3.end', 'L3+0.5', '50%'."""
        if spec is None:
            return default
        if isinstance(spec, (int, float)):
            return float(max(0.0, min(self.duration, spec)))
        s = str(spec).strip()
        if s.endswith("%"):
            return self.duration * float(s[:-1]) / 100.0
        m = re.match(r"^([A-Za-z]\w*?)(\.end|\.start)?([+-][\d.]+)?$", s)
        if m and m.group(1) in self.cues:
            a, b = self.cues[m.group(1)]
            base = b if m.group(2) == ".end" else a
            return float(max(0.0, min(self.duration, base + float(m.group(3) or 0))))
        try:
            return float(s)
        except ValueError:
            return default

    def s(self, px):
        """Scale a portrait-tuned pixel size for the current format."""
        return px * self.font_scale

    # -- theme / legend shortcuts
    @property
    def ink(self):
        return self.theme["ink"]

    def lith(self, name):
        return self.domain.lith(name)

    def label(self, key):
        return self.T["provenance"].get(key, key)


def measure(theme, text, font_key, size, max_w, line_h=1.18):
    """Rendered (w, h, n_lines) of a text item, using the same fonts/wrapping as the overlay layer."""
    from ..overlays import font, wrap_runs, line_width, SS
    f = font(theme["fonts"].get(font_key, font_key), int(size) * SS)
    lines = wrap_runs(str(text), f, (max_w or 0) * SS)
    asc, desc = f.getmetrics()
    lh = (asc + desc) * line_h
    h = (lh * (len(lines) - 1) + asc + desc) / SS + 4
    w = max(line_width(ln, f) for ln in lines) / SS + 4
    return w, h, len(lines)


def fit_size(theme, text, font_key, size, max_w, max_h, min_frac=0.55, line_h=1.18):
    """Largest font size <= size so that the wrapped text fits in max_h."""
    s = int(size)
    lo = int(size * min_frac)
    while s > lo and measure(theme, text, font_key, s, max_w, line_h)[1] > max_h:
        s -= 1
    return s


def text_box_size(theme, text, size, max_w, font_key="label", pad=(14, 8)):
    """(w, h) of a label/callout box as the overlay layer draws it (text + padding)."""
    w, h, _ = measure(theme, text, font_key, size, max_w)
    return w + 2 * pad[0], h + 2 * pad[1]


def place_callouts(ctx, labels, obstacles, bounds, curve=None, n_samples=16, step=None):
    """Time-aware placement of callout boxes. Generic: templates describe what must stay visible.

    labels    [{text, size, target: (x, y), t0, t1?, max_w?: [w1, w2...], prefer_x?: x}]
    obstacles [{box: (x0, y0, x1, y1)} or {boxes: (n_frames, 4) array}, t0?, t1?, w: weight]
              e.g. the moving instrument, a live readout, layer labels, the track header
    bounds    (x0, y0, x1, y1) where boxes may go
    curve     (pts (m, 2), reveal_n (n_frames,)) — revealed data points a box should not hide
    Placed boxes become obstacles for later labels. Returns [{x, y, max_w, box, cost}] (x, y = top-left).
    Cost per candidate = overlap with obstacles over the frames the label is visible + hidden curve points
    + distance to its target; the cheapest candidate wins.
    """
    th = ctx.theme
    step = step or ctx.s(14)
    bx0, by0, bx1, by1 = bounds
    fr_all = np.arange(ctx.n)
    placed, out = [], []
    if curve is not None:
        cpts = np.asarray(curve[0], float)
        sub = max(1, len(cpts) // 240)
        cidx = np.arange(0, len(cpts), sub)
        cpts = cpts[cidx]
        creveal = np.asarray(curve[1], float)
    order = sorted(range(len(labels)), key=lambda i: labels[i].get("t0", 0.0))
    res = [None] * len(labels)
    for i in order:
        L = labels[i]
        t0 = float(L.get("t0", 0.0))
        t1 = float(L["t1"]) if L.get("t1") is not None else ctx.duration
        frames = np.unique(np.clip((np.linspace(t0, max(t0, t1 - 1e-3), n_samples) * ctx.fps).astype(int),
                                   0, ctx.n - 1))
        tx, ty = L["target"]
        best = None
        for mw in L.get("max_w") or [ctx.w * 0.42]:
            bw, bh = text_box_size(th, L["text"], L["size"], mw)
            if bw > bx1 - bx0 or bh > by1 - by0:
                continue
            xs = np.arange(bx0, bx1 - bw + 1e-6, step)
            ys = np.arange(by0, by1 - bh + 1e-6, step)
            X0, Y0 = [a.ravel() for a in np.meshgrid(xs, ys)]
            X1, Y1 = X0 + bw, Y0 + bh
            area = bw * bh
            cost = np.zeros_like(X0)
            for ob in list(obstacles) + placed:
                ot0, ot1 = ob.get("t0", 0.0), ob.get("t1", ctx.duration)
                fs = frames[(frames / ctx.fps >= ot0) & (frames / ctx.fps < ot1)]
                if not len(fs):
                    continue
                if "boxes" in ob:
                    B = np.asarray(ob["boxes"], float)[fs]
                else:
                    B = np.repeat(np.asarray(ob["box"], float)[None, :], len(fs), 0)
                acc = np.zeros_like(X0)
                for b in B:
                    ox = np.clip(np.minimum(X1, b[2]) - np.maximum(X0, b[0]), 0, None)
                    oy = np.clip(np.minimum(Y1, b[3]) - np.maximum(Y0, b[1]), 0, None)
                    acc += ox * oy / area
                cost += ob.get("w", 5.0) * acc / len(frames)
            if curve is not None:
                hid = np.zeros_like(X0)
                for f in frames:
                    nrev = np.searchsorted(cidx, creveal[f])
                    if nrev <= 0:
                        continue
                    P = cpts[:nrev]
                    inside = ((P[None, :, 0] >= X0[:, None]) & (P[None, :, 0] <= X1[:, None]) &
                              (P[None, :, 1] >= Y0[:, None]) & (P[None, :, 1] <= Y1[:, None]))
                    hid += inside.sum(1)
                cost += 4.0 * np.minimum(hid / len(frames) / 12.0, 3.0)
            # target: the box must not cover the point it explains; short leaders preferred
            ex = np.clip(tx, X0, X1)
            ey = np.clip(ty, Y0, Y1)
            dist = np.hypot(ex - tx, ey - ty)
            cost += np.where(dist < 4, 6.0, 0.0) + dist / ctx.s(260)
            if L.get("prefer_x") is not None:
                cost += np.abs((X0 + X1) / 2 - L["prefer_x"]) / ctx.s(900)
            k = int(np.argmin(cost))
            cand = (float(cost[k]), float(X0[k]), float(Y0[k]), bw, bh, mw)
            if best is None or cand[0] < best[0] - 1e-9:
                best = cand
        if best is None:                                   # nothing fits: keep at target
            res[i] = {"x": tx, "y": ty, "max_w": ctx.w * 0.42, "box": None, "cost": None}
            continue
        c, x, y, bw, bh, mw = best
        box = (x, y, x + bw, y + bh)
        placed.append({"box": box, "t0": t0, "t1": t1, "w": 10.0})
        res[i] = {"x": x, "y": y, "max_w": mw, "box": box, "cost": round(c, 3)}
    return res


def nice_ticks(lo, hi, n=5):
    """Round axis ticks ('nice numbers')."""
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if span / step <= n:
            break
    start = math.ceil(lo / step - 1e-9) * step
    ticks = []
    v = start
    while v <= hi + 1e-9 * span:
        ticks.append(round(v, 10))
        v += step
    return ticks


def log_ticks(lo, hi):
    out = []
    e = math.floor(math.log10(max(lo, 1e-30)))
    while 10 ** e <= hi * 1.0001:
        if 10 ** e >= lo * 0.9999:
            out.append(10 ** e)
        e += 1
    return out


def fmt_num(v, lang="ru", max_dec=2):
    """Format a number for screen; decimals follow the language (comma in Russian)."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    av = abs(v)
    if av >= 100 or float(v).is_integer():
        s = f"{v:.0f}"
    elif av >= 10:
        s = f"{v:.1f}".rstrip("0").rstrip(".")
    elif av >= 0.01:
        s = f"{v:.{max_dec}f}".rstrip("0").rstrip(".")
    else:
        s = f"{v:.1e}"
    if lang == "ru":
        s = s.replace(".", ",")
    return s


class Scale:
    """Linear or log mapping from data to pixels."""

    def __init__(self, d0, d1, p0, p1, log=False):
        self.log = log
        self.d0, self.d1, self.p0, self.p1 = d0, d1, p0, p1
        if log:
            self.l0, self.l1 = math.log10(max(d0, 1e-30)), math.log10(max(d1, 1e-30))

    def __call__(self, v):
        v = np.asarray(v, dtype=float)
        if self.log:
            u = (np.log10(np.maximum(v, 1e-30)) - self.l0) / (self.l1 - self.l0)
        else:
            u = (v - self.d0) / (self.d1 - self.d0)
        return self.p0 + u * (self.p1 - self.p0)

    def inv(self, p):
        u = (np.asarray(p, dtype=float) - self.p0) / (self.p1 - self.p0)
        if self.log:
            return 10 ** (self.l0 + u * (self.l1 - self.l0))
        return self.d0 + u * (self.d1 - self.d0)


class Template:
    name = "base"
    purpose = ""
    classes = ("B",)
    required = {}       # field -> description (in params)
    optional = {}
    needs_model = False  # True if spec.model must be present
    example = {}

    def check_params(self, params, model_out=None):
        """Return list of missing/invalid field messages (empty = ok)."""
        missing = [f"missing params.{k}" for k in self.required if k not in params]
        if self.needs_model and model_out is None:
            missing.append("missing state model output (spec.model)")
        return missing

    def plan(self, params, model_out, ctx):
        raise NotImplementedError

    @classmethod
    def settled_params(cls, params):
        """Params that show this visual in its FINISHED state from the first frame (used when a scene is
        re-used as a still base under a card, e.g. a bridge line). Templates with animation override this."""
        return dict(params)

    @classmethod
    def describe(cls):
        return {"name": cls.name, "purpose": cls.purpose, "classes": list(cls.classes),
                "required": cls.required, "optional": cls.optional, "needs_model": cls.needs_model,
                "example": cls.example}


# ------------------------------------------------------------------ small builders

def T(text, x, y, size=28, font="label", color=None, anchor="lm", t0=0.0, t1=None, bg=None, **kw):
    """Shorthand for a text overlay item."""
    d = {"kind": "label", "text": str(text), "x": float(x), "y": float(y), "size": size, "font": font,
         "anchor": anchor, "t0": t0}
    if color:
        d["color"] = color
    if t1 is not None:
        d["t1"] = t1
    if bg:
        d["bg"] = bg
    d.update(kw)
    return d


def callout(text, target, pos, t0=0.0, t1=None, size=26, **kw):
    d = {"kind": "callout", "text": str(text), "target": [float(target[0]), float(target[1])],
         "pos": [float(pos[0]), float(pos[1])], "size": size, "t0": t0}
    if t1 is not None:
        d["t1"] = t1
    d.update(kw)
    return d


def panel(x, y, w, h, theme, r=26, t0=0.0, **kw):
    d = {"type": "rect", "x": x, "y": y, "w": w, "h": h, "r": r, "fill": theme["panel"],
         "stroke": theme["panel_stroke"], "lw": theme.get("outline_w", 3) * 0.8, "t0": t0, "shadow": True}
    d.update(kw)
    return d
