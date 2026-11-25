"""Geometry-led templates: cross_section, pore_scale, inset_callouts, process_steps."""
import math

import numpy as np

from .base import Template, Ctx, T, callout, panel


# ------------------------------------------------------------------ polygon helpers

def clip_halfplane(poly, a, b, c):
    """Keep the part of a convex polygon where a*x + b*y + c >= 0 (Sutherland-Hodgman, one edge)."""
    out = []
    n = len(poly)
    for i in range(n):
        P, Q = poly[i], poly[(i + 1) % n]
        fp, fq = a * P[0] + b * P[1] + c, a * Q[0] + b * Q[1] + c
        if fp >= 0:
            out.append(P)
        if (fp >= 0) != (fq >= 0):
            tt = fp / (fp - fq)
            out.append((P[0] + (Q[0] - P[0]) * tt, P[1] + (Q[1] - P[1]) * tt))
    return out


class CrossSection(Template):
    name = "cross_section"
    purpose = "Layered geological cross-section: any list of units (lithology, thickness), dip, faults, a well, fluids in pores."
    classes = ("B",)
    required = {"units": "[{name, lith, thickness}] from top to bottom (relative thickness ok)"}
    optional = {
        "dip_deg": "apparent dip of layers", "faults": "[{x: 0..1, throw: 0..1 of section height, dip_deg}]",
        "well": "{x: 0..1, to_unit: name, label}", "reveal": "bottom_up|top_down|all",
        "labels": "bool: callout each unit name", "highlight": "[{unit, at: time-ref, text?}]",
        "fluids": "[{unit, fluid: oil|water|gas, below?: {fluid, at_frac}}] shown as pore-scale dots, not blobs",
        "surface": "bool: draw a ground line with sky above", "times": "time-refs per unit reveal",
    }
    example = {"units": [{"name": "глина", "lith": "clay", "thickness": 1}, {"name": "песчаник", "lith": "sandstone",
                                                                             "thickness": 1.2},
                         {"name": "глина", "lith": "clay", "thickness": 1}], "reveal": "bottom_up", "labels": True}

    @classmethod
    def settled_params(cls, params):
        p = dict(params)
        p["reveal"] = "all"
        p.pop("times", None)
        return p

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        surface = p.get("surface", False)
        lab_w = ctx.s(0) if not p.get("labels", True) else (ctx.s(0) if ctx.portrait else bw * 0.18)
        X0, X1 = bx, bx + bw - lab_w
        Y0 = by + (bh * 0.12 if surface else (ctx.s(80) if p.get("well") else ctx.s(10)))
        Y1 = by + bh - ctx.s(10)
        units = p["units"]
        tot = sum(float(u.get("thickness", 1)) for u in units)
        dip = math.tan(math.radians(float(p.get("dip_deg", 0))))
        xm = (X0 + X1) / 2
        # boundaries as lines y = yb + dip*(x - xm)
        ys = [Y0]
        for u in units:
            ys.append(ys[-1] + (Y1 - Y0) * float(u.get("thickness", 1)) / tot)
        faults = sorted(p.get("faults", []), key=lambda f: f["x"])
        # blocks between faults: each block has a vertical shift
        cuts = []
        shift = 0.0
        for fl in faults:
            fx = X0 + (X1 - X0) * float(fl["x"])
            fd = math.radians(float(fl.get("dip_deg", 70)))
            shift += float(fl.get("throw", 0.1)) * (Y1 - Y0)
            cuts.append((fx, fd, shift))
        items, texts = [], []
        n = len(units)
        reveal = p.get("reveal", "bottom_up")
        ts_given = [ctx.at(x) for x in p.get("times", [])]
        span = max(0.6, ctx.duration * 0.45)
        order = list(range(n))[::-1] if reveal == "bottom_up" else list(range(n))
        t_unit = {}
        for rank, i in enumerate(order):
            t_unit[i] = ts_given[i] if i < len(ts_given) else (0.2 + span * rank / max(1, n) if reveal != "all" else 0.2)
        # polygon per unit per block
        big = 4 * (Y1 - Y0)

        def unit_poly(i, s):
            yt, yb = ys[i] + s, ys[i + 1] + s
            return [(X0, yt + dip * (X0 - xm)), (X1, yt + dip * (X1 - xm)), (X1, yb + dip * (X1 - xm)),
                    (X0, yb + dip * (X0 - xm))]

        blocks = [(None, 0.0)] + [(c, c[2]) for c in cuts]
        for bi, (cut, s) in enumerate(blocks):
            for i, u in enumerate(units):
                poly = unit_poly(i, s)
                # keep right of this fault, left of next fault
                if cut:
                    fx, fd, _ = cut
                    # fault line through (fx, Y0) with direction (cos, sin) of dip, measured from horizontal
                    ax, ay = math.cos(fd), math.sin(fd)
                    poly = clip_halfplane(poly, ay, -ax, -(ay * fx - ax * Y0))
                if bi + 1 < len(blocks):
                    fx, fd, _ = blocks[bi + 1][0]
                    ax, ay = math.cos(fd), math.sin(fd)
                    poly = clip_halfplane(poly, -ay, ax, (ay * fx - ax * Y0))
                poly = clip_halfplane(poly, 0, 1, -Y0)          # y >= Y0
                poly = clip_halfplane(poly, 0, -1, Y1)          # y <= Y1
                if len(poly) < 3:
                    continue
                key, sty = ctx.lith(u.get("lith"))
                pat = {"kind": sty.get("pattern", "none"), "spacing": ctx.s(16), "size": 2.1, "seed": i + 3}
                fl = next((f for f in p.get("fluids", []) if f.get("unit") in (u.get("name"), i)), None)
                if fl:
                    pat = {"kind": "dots", "spacing": ctx.s(11), "size": 2.6,
                           "color": ctx.domain.fluid_color(fl["fluid"]), "opacity": 0.95, "seed": i + 3}
                items.append({"type": "polygon", "pts": [list(map(float, q)) for q in poly], "fill": sty["fill"],
                              "pattern": pat, "stroke": th["ink"], "lw": 2.2, "t0": t_unit[i], "fade_in": 0.45})
                if fl and fl.get("below"):
                    yc = ys[i] + s + (ys[i + 1] - ys[i]) * float(fl["below"].get("at_frac", 0.6))
                    lower = clip_halfplane(poly, 0, 1, -yc)
                    if len(lower) >= 3:
                        items.append({"type": "polygon", "pts": [list(map(float, q)) for q in lower], "fill": sty["fill"],
                                      "pattern": {"kind": "dots", "spacing": ctx.s(11), "size": 2.6,
                                                  "color": ctx.domain.fluid_color(fl["below"]["fluid"]),
                                                  "opacity": 0.95, "seed": i + 9},
                                      "stroke": th["ink"], "lw": 1.5, "t0": t_unit[i] + 0.3, "fade_in": 0.45})
        for cut in cuts:
            fx, fd, _ = cut
            dx = (Y1 - Y0) / math.tan(fd)
            items.append({"type": "line", "x1": fx, "y1": Y0, "x2": fx + dx, "y2": Y1, "stroke": th["accent"],
                          "lw": ctx.s(5), "t0": max(t_unit.values()) + 0.3, "appear": "draw", "fade_in": 0.6})
        items.append({"type": "rect", "x": X0, "y": Y0, "w": X1 - X0, "h": Y1 - Y0, "stroke": th["ink"],
                      "lw": th.get("outline_w", 3), "t0": 0.0})
        if surface:
            items.insert(0, {"type": "rect", "x": X0, "y": by, "w": X1 - X0, "h": Y0 - by, "fill": th["accent2"],
                             "fill_opacity": 0.18, "t0": 0.0})
        w = p.get("well")
        if w:
            wx = X0 + (X1 - X0) * float(w.get("x", 0.5))
            tgt = next((i for i, u in enumerate(units) if u.get("name") == w.get("to_unit")), n - 1)
            wy = ys[tgt] + (ys[tgt + 1] - ys[tgt]) * 0.6
            tw = ctx.at(w.get("at"), max(t_unit.values()) + 0.5)
            items.append({"type": "line", "x1": wx, "y1": Y0 - ctx.s(40), "x2": wx, "y2": wy, "stroke": th["ink"],
                          "lw": ctx.s(7), "t0": tw, "appear": "draw", "fade_in": 0.8})
            items.append({"type": "polygon", "pts": [[wx - ctx.s(26), Y0 - ctx.s(8)], [wx + ctx.s(26), Y0 - ctx.s(8)],
                                                      [wx, Y0 - ctx.s(70)]],
                          "fill": th["equipment"]["body"], "stroke": th["ink"], "lw": 3, "t0": tw})
            if w.get("label"):
                texts.append(callout(w["label"], [wx + ctx.s(10), Y0 - ctx.s(40)], [wx + ctx.s(130), Y0 - ctx.s(40)],
                                     t0=tw + 0.3, size=ctx.s(22), anchor="lm"))
        if p.get("labels", True):
            for i, u in enumerate(units):
                if not u.get("name"):
                    continue
                yc = (ys[i] + ys[i + 1]) / 2 + dip * (X1 - xm) * 0.7
                if ctx.portrait:
                    texts.append(T(u["name"], X1 - ctx.s(16), yc, size=ctx.s(26), font="label", color=th["ink"],
                                   anchor="rm", t0=t_unit[i] + 0.3,
                                   bg={"fill": th["panel"], "opacity": 0.88, "radius": 10, "pad": [12, 6]},
                                   source_ref=u.get("source_ref")))
                else:
                    texts.append(callout(u["name"], [X1 - ctx.s(30), yc], [X1 + lab_w * 0.5, yc], t0=t_unit[i] + 0.3,
                                         size=ctx.s(24), source_ref=u.get("source_ref")))
        for hl in p.get("highlight", []):
            i = next((k for k, u in enumerate(units) if u.get("name") == hl.get("unit") or k == hl.get("unit")), None)
            if i is None:
                continue
            th_ = ctx.at(hl.get("at"), ctx.duration * 0.6)
            items.append({"type": "rect", "x": X0 - 6, "y": ys[i] - 6 + min(0, dip * (X0 - xm)), "w": X1 - X0 + 12,
                          "h": ys[i + 1] - ys[i] + 12 + abs(dip) * (X1 - X0), "stroke": th["accent"], "lw": ctx.s(6),
                          "r": 8, "t0": th_, "appear": "draw", "fade_in": 0.5, "dash": [14, 8]})
            if hl.get("text"):
                texts.append(callout(hl["text"], [xm, (ys[i] + ys[i + 1]) / 2], [xm, Y0 + ctx.s(30)], t0=th_ + 0.3,
                                     size=ctx.s(24), source_ref=hl.get("source_ref")))
        checks = [{"id": "order", "type": "assert", "ok": all(ys[i] < ys[i + 1] for i in range(n)),
                   "text": "units stacked top to bottom in the given order"}]
        return {"items": items, "texts": texts, "probes": [], "checks": checks,
                "state": {"boundaries_px": np.array(ys)}}


class PoreScale(Template):
    name = "pore_scale"
    purpose = ("Pore-scale view of a granular rock: grains always touch (grain-supported framework), pore space "
               "filled with fluids at a given saturation; optional flow arrows through pore throats.")
    classes = ("B",)
    required = {}
    optional = {
        "grains": "{n: count, size_cv: 0..0.5, touching: true (always enforced)}",
        "fluids": "{wetting: water|oil, sw: 0..1 water saturation, nonwetting: oil|gas}",
        "flow": "{direction_deg, label, at}", "legend": "bool", "seed": "int",
    }
    example = {"grains": {"n": 60}, "fluids": {"wetting": "water", "nonwetting": "oil", "sw": 0.3}, "legend": True}

    def plan(self, p, model, ctx):
        from PIL import Image, ImageDraw
        from scipy import ndimage
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        S = min(bw, bh)
        X0, Y0 = bx + (bw - S) / 2, by + (bh - S) / 2
        g = p.get("grains", {})
        n = int(g.get("n", 55))
        rng = np.random.default_rng(int(p.get("seed", 5)))
        # Poisson-disk-ish centres
        dmin = S / math.sqrt(n) * 0.9
        pts = []
        tries = 0
        while len(pts) < n and tries < 20000:
            c = rng.uniform(-0.05 * S, 1.05 * S, 2)
            if all(np.hypot(*(c - q)) >= dmin for q in pts):
                pts.append(c)
            tries += 1
        P = np.array(pts)
        D = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])
        np.fill_diagonal(D, np.inf)
        nn = D.min(axis=1)
        cv = float(g.get("size_cv", 0.12))
        k = 1.02
        # enlarge until the contact graph is connected (grain-supported framework)
        for _ in range(30):
            r = 0.5 * nn * k * (1 + rng.normal(0, cv * 0.3, len(P)).clip(-0.2, 0.2))
            contact = D <= (r[:, None] + r[None, :]) * 1.0
            # union-find
            parent = list(range(len(P)))

            def find(a):
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a
            for i, j in zip(*np.where(contact)):
                parent[find(i)] = find(j)
            comps = len({find(i) for i in range(len(P))})
            if comps == 1:
                break
            k *= 1.02
        # raster pores, then fluids by distance to grain surface (wetting film)
        res = 2
        N = int(S * res)
        img = Image.new("L", (N, N), 0)
        dr = ImageDraw.Draw(img)
        for (x, y), rr in zip(P * res, r * res):
            dr.ellipse([x - rr, y - rr, x + rr, y + rr], fill=255)
        grain = np.asarray(img) > 0
        pore = ~grain
        dist = ndimage.distance_transform_edt(pore)
        fl = p.get("fluids", {"wetting": "water", "nonwetting": "oil", "sw": 0.3})
        sw = float(fl.get("sw", 0.3))
        # pick film thickness so that wetting fraction of pore pixels == sw
        pv = dist[pore]
        thr = np.quantile(pv, min(0.999, max(0.0, sw))) if pv.size else 0
        wet = pore & (dist <= thr)
        nonwet = pore & (dist > thr)
        c_w = np.array([int(255 * c) for c in _rgb(ctx.domain.fluid_color(fl.get("wetting", "water")))])
        c_n = np.array([int(255 * c) for c in _rgb(ctx.domain.fluid_color(fl.get("nonwetting", "oil")))])
        rgba = np.zeros((N, N, 4), np.uint8)
        rgba[wet, :3], rgba[wet, 3] = c_w, 255
        rgba[nonwet, :3], rgba[nonwet, 3] = c_n, 255
        path = f"{ctx.shot_dir}/{ctx.shot_id}_pores.png"
        Image.fromarray(rgba).save(path)
        items = [{"type": "rect", "x": X0, "y": Y0, "w": S, "h": S, "fill": th["panel"], "t0": 0.0},
                 {"type": "image", "src": f"{ctx.shot_id}_pores.png", "x": X0, "y": Y0, "w": S, "h": S, "t0": 0.6,
                  "fade_in": 0.8}]
        sand = ctx.lith("sandstone")[1]["fill"]
        grains = []
        for i, ((x, y), rr) in enumerate(zip(P, r)):
            grains.append({"type": "circle", "cx": float(X0 + x), "cy": float(Y0 + y), "r": float(rr),
                           "fill": sand, "stroke": th["ink"], "lw": 1.6, "t0": 0.05 + 0.4 * (i / len(P)),
                           "appear": "grow", "fade_in": 0.3})
        items.append({"type": "group", "items": grains, "clip": {"type": "rect", "x": X0, "y": Y0, "w": S, "h": S},
                      "t0": 0.0, "fade_in": 0.01})
        items.append({"type": "rect", "x": X0, "y": Y0, "w": S, "h": S, "stroke": th["ink"], "lw": 3, "t0": 0.0})
        texts = []
        flw = p.get("flow")
        if flw:
            ang = math.radians(float(flw.get("direction_deg", 0)))
            tf = ctx.at(flw.get("at"), 1.2)
            for j in range(3):
                yy = Y0 + S * (0.25 + 0.25 * j)
                x1, x2 = X0 + S * 0.15, X0 + S * 0.85
                items.append({"type": "arrow", "x1": x1, "y1": yy, "x2": x1 + (x2 - x1) * math.cos(ang),
                              "y2": yy + (x2 - x1) * math.sin(ang), "stroke": th["accent"], "lw": ctx.s(5),
                              "dash": [16, 12], "tracks": {"dash_offset": (-ctx.times * 60).round(1).tolist()},
                              "t0": tf + 0.15 * j, "appear": "draw", "fade_in": 0.5})
            if flw.get("label"):
                texts.append(T(flw["label"], X0 + S / 2, Y0 - ctx.s(20), size=ctx.s(24), font="label",
                               color=th["accent"], anchor="cb", t0=tf))
        if p.get("legend", True):
            texts.append({"kind": "legend", "x": X0, "y": Y0 + S + ctx.s(30), "size": ctx.s(22), "t0": 0.8,
                          "items": [{"color": sand, "text": p.get("grain_label", "зерно" if ctx.lang == "ru" else "grain")},
                                    {"color": ctx.domain.fluid_color(fl.get("wetting", "water")),
                                     "text": fl.get("wetting_label", fl.get("wetting", "water"))},
                                    {"color": ctx.domain.fluid_color(fl.get("nonwetting", "oil")),
                                     "text": fl.get("nonwetting_label", fl.get("nonwetting", "oil"))}][:2 if sw >= 0.999 else 3]})
        sw_actual = float(wet.sum() / max(1, pore.sum()))
        checks = [{"id": "grains_touch", "type": "assert", "ok": comps == 1,
                   "text": f"grain-supported framework: contact graph connected ({comps} component)"},
                  {"id": "saturation", "type": "assert", "ok": abs(sw_actual - sw) < 0.03,
                   "text": f"drawn wetting-phase saturation {sw_actual:.2f} vs spec {sw:.2f}"},
                  {"id": "no_lake", "type": "assert", "ok": bool(nonwet.sum() < 0.8 * N * N),
                   "text": "fluid only in pore space (no free 'lake')"}]
        return {"items": items, "texts": texts, "probes": [], "checks": checks,
                "state": {"porosity_drawn": float(pore.mean()), "sw_drawn": sw_actual}}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


class InsetCallouts(Template):
    name = "inset_callouts"
    purpose = "A base scene with a circular magnified inset (any other template inside) and callout labels."
    classes = ("B", "C")
    required = {"base": "{template: name, params: {...}} or {image: path}",
                "inset": "{template: name, params: {...}, focus: [x,y] 0..1 of base, pos: [x,y] 0..1, radius: 0..0.5}"}
    optional = {"callouts": "[{text, target: [x,y] 0..1 of base, at: time-ref}]", "inset_at": "time-ref"}
    example = {"base": {"template": "cross_section", "params": {"units": [{"name": "песчаник", "lith": "sandstone",
                                                                             "thickness": 1}]}},
               "inset": {"template": "pore_scale", "params": {"grains": {"n": 40}}, "focus": [0.5, 0.5],
                         "pos": [0.7, 0.35], "radius": 0.28}}

    def plan(self, p, model, ctx):
        from . import REGISTRY
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        items, texts, checks, probes = [], [], [], []
        base = p["base"]
        if base.get("template"):
            sub = REGISTRY[base["template"]]().plan(base.get("params", {}), model, ctx)
            items += sub["items"]
            texts += sub["texts"]
            checks += sub.get("checks", [])
        elif base.get("image"):
            items.append({"type": "image", "src": base["image"], "x": bx, "y": by, "w": bw, "h": bh, "t0": 0.0,
                          "tracks": {"zoom": {"kf": [[0, 1.0], [ctx.duration, 1.06]], "ease": "linear"}}})
        ins = p["inset"]
        t_in = ctx.at(p.get("inset_at"), ctx.duration * 0.35)
        R = float(ins.get("radius", 0.26)) * min(bw, bh) * (1.25 if ctx.portrait else 1.0)
        fx, fy = bx + bw * ins.get("focus", [0.5, 0.5])[0], by + bh * ins.get("focus", [0.5, 0.5])[1]
        cx, cy = bx + bw * ins.get("pos", [0.7, 0.3])[0], by + bh * ins.get("pos", [0.7, 0.3])[1]
        r_focus = R / float(ins.get("zoom", 4))
        items.append({"type": "circle", "cx": fx, "cy": fy, "r": r_focus, "stroke": th["accent"], "lw": 3.5,
                      "t0": t_in, "appear": "draw", "fade_in": 0.4})
        # tangent-ish connector lines
        for sgn in (-1, 1):
            ang = math.atan2(cy - fy, cx - fx) + sgn * math.pi / 2
            items.append({"type": "line", "x1": fx + r_focus * math.cos(ang), "y1": fy + r_focus * math.sin(ang),
                          "x2": cx + R * math.cos(ang), "y2": cy + R * math.sin(ang), "stroke": th["accent"],
                          "lw": 2.2, "t0": t_in + 0.2, "appear": "draw", "fade_in": 0.3})
        # inset: sub-template planned into the circle's bounding square, delayed to t_in
        sub_ctx = Ctx(ctx.w, ctx.h, ctx.fps, ctx.duration - t_in, th, ctx.domain, ctx.lang,
                      {ctx.lang: ctx.T, "en": ctx.T}, cues={}, shot_dir=ctx.shot_dir, orientation=ctx.orientation,
                      shot_id=ctx.shot_id + "_inset")
        sub_ctx.box = (cx - R, cy - R, 2 * R, 2 * R)
        sub_ctx.font_scale = ctx.font_scale * 0.8
        ip = REGISTRY[ins["template"]]().plan(ins.get("params", {}), model, sub_ctx)
        shift = lambda it: _delay(it, t_in, ctx.fps)
        inner = [{"type": "circle", "cx": cx, "cy": cy, "r": R, "fill": th["panel"], "t0": 0.0}] + \
                [shift(i) for i in ip["items"]]
        items.append({"type": "group", "items": inner, "t0": t_in, "fade_in": 0.35, "appear": "grow",
                      "grow_origin": [cx, cy], "clip": {"type": "circle", "cx": cx, "cy": cy, "r": R}})
        items.append({"type": "circle", "cx": cx, "cy": cy, "r": R, "stroke": th["ink"], "lw": 5, "t0": t_in,
                      "appear": "grow", "grow_origin": [cx, cy], "fade_in": 0.35})
        texts += [_delay_text(tx, t_in, ctx.fps) for tx in ip["texts"]]
        checks += ip.get("checks", [])
        for co in p.get("callouts", []):
            tx = bx + bw * co["target"][0]
            ty = by + bh * co["target"][1]
            texts.append(callout(co["text"], [tx, ty], [tx + ctx.s(co.get("dx", 0)), ty + ctx.s(co.get("dy", -90))],
                                 t0=ctx.at(co.get("at"), t_in + 0.6), size=ctx.s(24), source_ref=co.get("source_ref")))
        return {"items": items, "texts": texts, "probes": probes, "checks": checks, "state": {}}


def _delay(it, dt, fps):
    it = dict(it)
    it["t0"] = it.get("t0", 0.0) + dt
    if "t1" in it:
        it["t1"] = it["t1"] + dt
    shift = int(round(dt * fps))
    if "tracks" in it:
        tr = {}
        for k, v in it["tracks"].items():
            if isinstance(v, list):
                tr[k] = [v[0]] * shift + v
            elif isinstance(v, dict) and "kf" in v:
                tr[k] = {**v, "kf": [[a + dt, b] for a, b in v["kf"]]}
            else:
                tr[k] = v
        it["tracks"] = tr
    if it.get("type") == "group":
        it["items"] = [_delay(s, 0, fps) for s in it["items"]]
    return it


def _delay_text(tx, dt, fps):
    tx = dict(tx)
    tx["t0"] = tx.get("t0", 0.0) + dt
    if "t1" in tx:
        tx["t1"] += dt
    return tx


class ProcessSteps(Template):
    name = "process_steps"
    purpose = "Step-by-step process / chain of causes: numbered nodes connected by flowing arrows, highlighted in turn."
    classes = ("T",)
    required = {"steps": "[{title, text?}] in order (2-6 steps)"}
    optional = {"layout": "vertical|horizontal|cycle", "times": "time-refs when each step activates",
                "icons": "list of icon kinds per step"}
    example = {"steps": [{"title": "Пласт под давлением"}, {"title": "Скважина открыта"},
                         {"title": "Давление падает у ствола"}], "layout": "vertical"}

    def plan(self, p, model, ctx):
        from .base import measure
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        steps = p["steps"]
        n = len(steps)
        lay = p.get("layout", "vertical" if ctx.portrait else "horizontal")
        given = [ctx.at(x) for x in p.get("times", [])]
        span = max(0.5, ctx.duration - 1.2)
        ts = [given[i] if i < len(given) else 0.3 + span * i / max(1, n) for i in range(n)]
        items, texts = [], []
        # ---- size boxes from the real text (same fonts as the overlay layer)
        scale = 1.0
        for _ in range(8):
            t_sz, x_sz = ctx.s(30) * scale, ctx.s(23) * scale
            if lay == "vertical":
                gap = ctx.s(30)
                inner_w = bw - ctx.s(20) - ctx.s(110)
            else:
                gap = ctx.s(60)
                inner_w = (bw - gap * (n - 1)) / n - ctx.s(48)
            heights = []
            for st in steps:
                h = measure(th, st["title"], "title", t_sz, inner_w, 1.08)[1]
                if st.get("text"):
                    h += ctx.s(10) + measure(th, st["text"], "body_regular", x_sz, inner_w, 1.15)[1]
                heights.append(h + (ctx.s(44) if lay == "vertical" else ctx.s(84) + ctx.s(30)))
            need = (sum(heights) + gap * (n - 1)) if lay == "vertical" else max(heights)
            if need <= bh or scale < 0.62:
                break
            scale *= 0.92
        boxes = []
        if lay == "cycle":
            R = min(bw, bh) * 0.34
            cx, cy = bx + bw / 2, by + bh / 2
            for i in range(n):
                a = -math.pi / 2 + 2 * math.pi * i / n
                w_, h_ = ctx.s(230), ctx.s(120)
                boxes.append((cx + R * math.cos(a) - w_ / 2, cy + R * math.sin(a) - h_ / 2, w_, h_))
        elif lay == "vertical":
            heights = [max(ctx.s(86), h) for h in heights]
            extra = max(0.0, bh - sum(heights) - gap * (n - 1))
            y = by + min(extra / 2, ctx.s(20))
            for h_ in heights:
                boxes.append((bx + ctx.s(10), y, bw - ctx.s(20), h_))
                y += h_ + gap
        else:
            w_ = (bw - gap * (n - 1)) / n
            h_ = min(bh, max(heights))
            for i in range(n):
                boxes.append((bx + i * (w_ + gap), by + (bh - h_) / 2, w_, h_))
        for i, (st, (x, y, w_, h_)) in enumerate(zip(steps, boxes)):
            t_i = ts[i]
            t_next = ts[i + 1] if i + 1 < n else ctx.duration + 1
            items.append(panel(x, y, w_, h_, th, r=20, t0=t_i, appear="grow", fade_in=0.35,
                               tracks={"lw": {"kf": [[t_i, 5.0], [t_next, 2.0]]}}, stroke=th["accent"]))
            ccx, ccy = x + ctx.s(40), y + ctx.s(42)
            items.append({"type": "circle", "cx": ccx, "cy": ccy, "r": ctx.s(24), "fill": th["accent"], "t0": t_i,
                          "appear": "grow"})
            texts.append(T(str(i + 1), ccx, ccy, size=ctx.s(26), font="mono", color="#FFFFFF", anchor="cm",
                           t0=t_i + 0.1, kind_num="enumeration"))
            if lay == "vertical":
                tx0, ty0, mw = x + ctx.s(84), y + ctx.s(22), w_ - ctx.s(110)
            else:
                tx0, ty0, mw = x + ctx.s(24), y + ctx.s(84), w_ - ctx.s(48)
            texts.append(T(st["title"], tx0, ty0, size=round(ctx.s(30) * scale), font="title", color=th["ink"],
                           anchor="lt", t0=t_i + 0.15, max_w=mw, line_h=1.08, source_ref=st.get("source_ref"),
                           max_h=(y + h_) - ty0 - ctx.s(14)))
            if st.get("text"):
                th_ = measure(th, st["title"], "title", round(ctx.s(30) * scale), mw, 1.08)[1]
                texts.append(T(st["text"], tx0, ty0 + th_ + ctx.s(10), size=round(ctx.s(23) * scale),
                               font="body_regular", color=th["ink_soft"], anchor="lt", t0=t_i + 0.3, max_w=mw,
                               line_h=1.15, source_ref=st.get("source_ref")))
            if i + 1 < n:
                x2, y2, w2, h2 = boxes[i + 1]
                if lay == "vertical":
                    a = (ccx, y + h_ + 3, ccx, y2 - 3)
                elif lay == "horizontal":
                    a = (x + w_ + 6, y + h_ / 2, x2 - 6, y2 + h2 / 2)
                else:
                    a = (x + w_ / 2, y + h_ / 2, x2 + w2 / 2, y2 + h2 / 2)
                items.append({"type": "arrow", "x1": a[0], "y1": a[1], "x2": a[2], "y2": a[3], "stroke": th["ink"],
                              "lw": ctx.s(4), "head": ctx.s(12), "t0": ts[i + 1] - 0.25, "appear": "draw",
                              "fade_in": 0.35})
        return {"items": items, "texts": texts, "probes": [], "checks": [
            {"id": "fits", "type": "assert", "ok": bool(lay != "vertical" or boxes[-1][1] + boxes[-1][3] <= by + bh + 2),
             "text": "all steps fit in the content area"}], "state": {"font_scale": scale}}
