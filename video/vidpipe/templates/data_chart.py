"""data_chart: line / step / scatter / crossplot from a CSV, LAS or model output, drawn progressively.
Highlight bands can be given explicitly or DERIVED FROM DATA (e.g. rows where a status column == 0),
so labels like 'well shut in' are backed by the dataset itself.
"""
import numpy as np

from .base import Template, Scale, T, callout, nice_ticks, log_ticks, fmt_num, panel


def _bands_from_mask(x, mask):
    bands, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        if (not m or i == len(mask) - 1) and start is not None:
            end = i if m else i - 1
            bands.append((float(x[start]), float(x[end])))
            start = None
    return bands


class DataChart(Template):
    name = "data_chart"
    purpose = "Real-data chart (time series, depth plot, crossplot) drawn progressively, with data-derived highlights."
    classes = ("A", "B")
    needs_model = True
    required = {"y": "list of model array names to plot (e.g. ['y_PRESSURE'])"}
    optional = {
        "x": "model array for x (default 'x')", "kind": "line|step|scatter|range_bars",
        "lo": "range_bars: model array with lower bounds", "hi": "range_bars: model array with upper bounds",
        "labels": "range_bars: model array with category names (lithology names get legend colours)",
        "highlight": "range_bars: list of category names to emphasise",
        "x_label": "str", "y_label": "str", "x_range": "[a,b]", "y_range": "[a,b]",
        "x_scale": "lin|log", "y_scale": "lin|log", "invert_y": "bool (depth plots)",
        "draw": "{start: time-ref, end: time-ref}",
        "series_draw": "[{start, end}] per series (draw series one after another)",
        "highlights": "[{x_from, x_to, label}] in x units",
        "highlight_where": "{array: model array, op: '==|<|>', value: number, label: str}",
        "annotations": "[{x, text, at?: time-ref}]",
        "ref_lines": "[{y, label}]", "series_labels": "{array: label}", "dates": "bool: x_dates array labels ticks",
        "caption": "source caption shown under the chart (dataset, well, curve)",
        "x_display_unit": "convert x from SI for display (model outputs)", "y_display_unit": "convert y from SI",
    }
    example = {"x": "x", "y": ["y_AVG_DOWNHOLE_PRESSURE"], "dates": True, "y_label": "p, бар",
               "highlight_where": {"array": "c_ON_STREAM_HRS", "op": "==", "value": 0, "label": "скважина остановлена"}}

    def check_params(self, params, model_out=None):
        """'y' is required for line/step/scatter; range_bars needs lo/hi/labels instead."""
        if params.get("kind") == "range_bars":
            errs = [f"missing params.{k} (range_bars)" for k in ("lo", "hi", "labels") if k not in params]
            if self.needs_model and model_out is None:
                errs.append("missing state model output (spec.model)")
            return errs
        return super().check_params(params, model_out)

    @classmethod
    def settled_params(cls, params):
        p = dict(params)
        p["draw"] = {"start": 0.0, "end": 0.6}
        p.pop("series_draw", None)
        p.pop("annotations", None)
        return p

    def plan(self, p, model, ctx):
        if p.get("kind") == "range_bars":
            return self._range_bars(p, model, ctx)
        th, dom = ctx.theme, ctx.domain
        probe = dom.legend.get("probe_colors", {"b": "#C81E3C"})
        from ..evaluator import from_si
        x = np.asarray(model[p.get("x", "x")], float)
        if p.get("x_display_unit"):
            x = from_si(x, p["x_display_unit"])
        series = p["y"] if isinstance(p["y"], list) else [p["y"]]
        Ys_data = [np.asarray(model[s], float) for s in series]
        if p.get("y_display_unit"):
            Ys_data = [from_si(y, p["y_display_unit"]) for y in Ys_data]
        ok = np.isfinite(x)
        for y in Ys_data:
            ok &= np.isfinite(y)
        x = x[ok]
        Ys_data = [y[ok] for y in Ys_data]
        dates = model.get("x_dates")
        if dates is not None:
            dates = np.asarray(dates)[ok] if len(dates) == len(ok) else None
        bx, by, bw, bh = ctx.box
        L = bx + ctx.s(84)
        R = bx + bw - ctx.s(20)
        Tp = by + ctx.s(40)
        B = by + bh - ctx.s(110)
        xr = p.get("x_range") or [float(x.min()), float(x.max())]
        allv = np.concatenate(Ys_data)
        pad = 0.06 * (allv.max() - allv.min() + 1e-9)
        yr = p.get("y_range") or [float(allv.min() - pad), float(allv.max() + pad)]
        X = Scale(xr[0], xr[1], L, R, log=p.get("x_scale") == "log")
        if p.get("invert_y"):
            Y = Scale(yr[0], yr[1], Tp, B, log=p.get("y_scale") == "log")
        else:
            Y = Scale(yr[0], yr[1], B, Tp, log=p.get("y_scale") == "log")
        items, texts = [], []
        items.append(panel(bx, by, bw, bh - ctx.s(40), th, r=18, fill=th["chart"]["bg"], shadow=True, lw=2, t0=0.0))

        # highlight bands (explicit or derived from data)
        bands = [(h["x_from"], h["x_to"], h.get("label"), h.get("source_ref")) for h in p.get("highlights", [])]
        hw = p.get("highlight_where")
        if hw and hw.get("array") in model:
            arr = np.asarray(model[hw["array"]], float)[ok]
            v = float(hw["value"])
            mask = {"==": arr == v, "<": arr < v, ">": arr > v, "<=": arr <= v, ">=": arr >= v}[hw.get("op", "==")]
            for a, b in _bands_from_mask(x, mask):
                bands.append((a, b, hw.get("label"), f"dataset:{hw['array']}"))
        # draw window
        dr = p.get("draw", {})
        t_s, t_e = ctx.at(dr.get("start"), 0.5), ctx.at(dr.get("end"), ctx.duration * 0.75)
        t_e = max(t_s + 0.4, t_e)
        for i, (a, b, lbl, ref) in enumerate(bands):
            xa, xb = float(X(a)), float(X(b))
            if xb - xa < 3:
                xa, xb = xa - 4, xb + 4
            # band appears when the drawn curve reaches it
            frac = (a - xr[0]) / max(1e-9, xr[1] - xr[0])
            t_b = t_s + (t_e - t_s) * frac
            items.append({"type": "rect", "x": xa, "y": Tp, "w": xb - xa, "h": B - Tp, "fill": th["accent3"],
                          "fill_opacity": 0.28, "t0": t_b, "fade_in": 0.4})
            if lbl and i == 0:
                texts.append(callout(lbl, [xa + (xb - xa) / 2, Tp + ctx.s(10)],
                                     [min(R - ctx.s(80), xa + ctx.s(150)), Tp + ctx.s(60)], t0=t_b + 0.2,
                                     size=ctx.s(22), source_ref=ref))
        # grid + ticks
        if dates is not None and p.get("dates", True):
            nt = 4 if ctx.portrait else 6
            idx = np.linspace(0, len(x) - 1, nt).round().astype(int)
            for i in idx:
                xx = float(X(x[i]))
                items.append({"type": "line", "x1": xx, "y1": Tp, "x2": xx, "y2": B, "stroke": th["chart"]["grid"],
                              "lw": 1.2, "t0": 0.2})
                d = str(dates[i])
                lab = f"{d[8:10]}.{d[5:7]}.{d[2:4]}" if ctx.lang == "ru" else d
                texts.append(T(lab, xx, B + ctx.s(14), size=ctx.s(17), font="mono", color=th["chart"]["tick_text"],
                               anchor="ct", t0=0.2, kind_num="axis", source_ref="axis:x"))
        else:
            xt = log_ticks(*xr) if p.get("x_scale") == "log" else nice_ticks(xr[0], xr[1], 4 if ctx.portrait else 6)
            for v in xt:
                xx = float(X(v))
                items.append({"type": "line", "x1": xx, "y1": Tp, "x2": xx, "y2": B, "stroke": th["chart"]["grid"],
                              "lw": 1.2, "t0": 0.2})
                texts.append(T(fmt_num(v, ctx.lang), xx, B + ctx.s(14), size=ctx.s(17), font="mono",
                               color=th["chart"]["tick_text"], anchor="ct", t0=0.2, kind_num="axis",
                               source_ref="axis:x"))
        for v in nice_ticks(yr[0], yr[1], 4 if ctx.portrait else 5):
            yy = float(Y(v))
            items.append({"type": "line", "x1": L, "y1": yy, "x2": R, "y2": yy, "stroke": th["chart"]["grid"],
                          "lw": 1.2, "t0": 0.2})
            texts.append(T(fmt_num(v, ctx.lang), L - ctx.s(10), yy, size=ctx.s(17), font="mono",
                           color=th["chart"]["tick_text"], anchor="rm", t0=0.2, kind_num="axis", source_ref="axis:y"))
        items.append({"type": "line", "x1": L, "y1": B, "x2": R, "y2": B, "stroke": th["chart"]["axis"], "lw": 2.5})
        items.append({"type": "line", "x1": L, "y1": Tp, "x2": L, "y2": B, "stroke": th["chart"]["axis"], "lw": 2.5})
        if p.get("y_label"):
            texts.append(T(p["y_label"], L, Tp - ctx.s(18), size=ctx.s(19), font="body", color=th["chart"]["tick_text"],
                           anchor="lb", t0=0.2))
        if p.get("x_label"):
            texts.append(T(p["x_label"], R, B + ctx.s(44), size=ctx.s(19), font="body", color=th["chart"]["tick_text"],
                           anchor="rt", t0=0.2))
        # series
        colors = [th["accent2"], th["accent"], th["accent3"], th["good"]]
        kind = p.get("kind", "line")
        state = {}
        probes = []
        for si, (sname, yv) in enumerate(zip(series, Ys_data)):
            col = (p.get("colors") or {}).get(sname)
            if not col:
                mn = sname.replace("y_", "").upper()
                col = dom.curve_color(mn) if mn in dom.legend.get("curves", {}) else colors[si % len(colors)]
            if kind == "step":
                xs2 = np.repeat(x, 2)[1:]
                ys2 = np.repeat(yv, 2)[:-1]
                pts = np.column_stack([X(xs2), Y(ys2)])
            else:
                pts = np.column_stack([X(x), Y(yv)])
            n = len(pts)
            sd = (p.get("series_draw") or [None] * (si + 1))[si] if si < len(p.get("series_draw") or []) else None
            if sd:                                  # this series has its own draw window
                s0, s1 = ctx.at(sd.get("start"), t_s), ctx.at(sd.get("end"), t_e)
                uu = np.clip((ctx.times - s0) / max(0.4, s1 - s0), 0, 1)
            else:
                uu = np.clip((ctx.times - t_s) / (t_e - t_s), 0, 1)
            reveal = 1 + (n - 1) * uu
            if kind == "scatter":
                P = np.zeros((ctx.n, n, 3), np.float32)
                for f in range(ctx.n):
                    m = int(reveal[f])
                    P[f, :m, 0], P[f, :m, 1], P[f, :m, 2] = pts[:m, 0], pts[:m, 1], 0.85
                np.savez_compressed(f"{ctx.shot_dir}/{ctx.shot_id}_sc{si}.npz", P=P)
                items.append({"type": "points", "npz": f"{ctx.shot_id}_sc{si}.npz", "key": "P", "r": ctx.s(4.5),
                              "fill": col, "t0": 0.0})
            else:
                head = {"r": ctx.s(7.5), "fill": probe["b"] if si == 0 else col, "stroke": th["panel"], "lw": 2}
                items.append({"type": "polyline", "pts": pts.round(2).tolist(), "stroke": col, "lw": ctx.s(3.6),
                              "tracks": {"reveal_n": reveal.round(3).tolist()}, "t0": 0.0, "fade_in": 0.01,
                              "head": head})
                if si == 0:
                    k = np.minimum(n - 1, np.floor(reveal - 1).astype(int))
                    fr = (reveal - 1) - k
                    k1 = np.minimum(n - 1, k + 1)
                    hx = pts[k, 0] + (pts[k1, 0] - pts[k, 0]) * fr
                    hy = pts[k, 1] + (pts[k1, 1] - pts[k, 1]) * fr
                    state.update({"head_x": hx, "head_y": hy})
                    probes.append({"name": "chart_head", "color": probe["b"], "region": [L - 10, Tp - 10, R + 10, B + 10],
                                   "expect_x": hx.round(2).tolist(), "expect_y": hy.round(2).tolist()})
            sl = (p.get("series_labels") or {}).get(sname)
            if sl:
                texts.append({"kind": "legend", "x": L + ctx.s(10) + si * ctx.s(220), "y": by + bh - ctx.s(20),
                              "items": [{"color": col, "text": sl, "shape": "square"}], "size": ctx.s(20), "t0": 0.3})
        for an in p.get("annotations", []):
            xv = float(an["x"])
            yv = float(np.interp(xv, x, Ys_data[0]))
            frac = (xv - xr[0]) / max(1e-9, xr[1] - xr[0])
            t_a = ctx.at(an.get("at"), t_s + (t_e - t_s) * frac + 0.2)
            texts.append(callout(an["text"], [float(X(xv)), float(Y(yv))],
                                 [float(X(xv)) + ctx.s(an.get("dx", -120)), float(Y(yv)) + ctx.s(an.get("dy", -90))],
                                 t0=t_a, size=ctx.s(21), source_ref=an.get("source_ref")))
        for rl in p.get("ref_lines", []):
            yy = float(Y(rl["y"]))
            items.append({"type": "line", "x1": L, "y1": yy, "x2": R, "y2": yy, "stroke": th["accent2"], "lw": 2.5,
                          "dash": [10, 8], "t0": ctx.at(rl.get("at"), 0.4), "appear": "draw"})
            if rl.get("label"):
                texts.append(T(rl["label"], R - 6, yy - ctx.s(14), size=ctx.s(19), font="label", color=th["accent2"],
                               anchor="rb", t0=ctx.at(rl.get("at"), 0.4), source_ref=rl.get("source_ref")))
        if p.get("caption"):
            texts.append(T(p["caption"], bx + ctx.s(8), by + bh - ctx.s(8), size=ctx.s(17), font="body_regular",
                           color=th["ink_soft"], anchor="lb", t0=0.3, max_w=bw - 20))
        checks = [{"id": "n_points", "type": "assert", "ok": bool(len(x) >= 3), "text": f"{len(x)} data points"},
                  {"id": "frame_head", "type": "frame_expect", "probes": ["chart_head"], "tol_px": 5,
                   "text": "drawn curve head is at the data point for that time"}] if probes else \
                 [{"id": "n_points", "type": "assert", "ok": bool(len(x) >= 3), "text": f"{len(x)} data points"}]
        return {"items": items, "texts": texts, "probes": probes, "checks": checks, "state": state}


    # ------------------------------------------------------------------ range bars (min-max per category)
    def _range_bars(self, p, model, ctx):
        from .base import measure
        th, dom = ctx.theme, ctx.domain
        labels = [str(x) for x in model[p.get("labels", "labels")]]
        lo = np.asarray(model[p.get("lo", "min")], float)
        hi = np.asarray(model[p.get("hi", "max")], float)
        bx, by, bw, bh = ctx.box
        items, texts = [], []
        items.append(panel(bx, by, bw, bh - ctx.s(30), th, r=18, fill=th["chart"]["bg"], shadow=True, lw=2, t0=0.0))
        name_w = min(bw * 0.42, max(measure(th, l, "label", ctx.s(22), 0)[0] for l in labels) + ctx.s(30))
        L, R = bx + name_w, bx + bw - ctx.s(110)
        Tp, B = by + ctx.s(70), by + bh - ctx.s(100)
        logx = p.get("x_scale", "log") == "log"
        xr = p.get("x_range") or [float(np.min(lo)) * (0.6 if logx else 0.9), float(np.max(hi)) * (1.6 if logx else 1.1)]
        X = Scale(xr[0], xr[1], L, R, log=logx)
        n = len(labels)
        row = (B - Tp) / max(1, n)
        ticks = log_ticks(*xr) if logx else nice_ticks(xr[0], xr[1], 4)
        for v in ticks:
            xx = float(X(v))
            items.append({"type": "line", "x1": xx, "y1": Tp - ctx.s(10), "x2": xx, "y2": B, "stroke": th["chart"]["grid"],
                          "lw": 1.3, "t0": 0.1})
            texts.append(T(fmt_num(v, ctx.lang), xx, B + ctx.s(12), size=ctx.s(17), font="mono",
                           color=th["chart"]["tick_text"], anchor="ct", t0=0.1, kind_num="axis", source_ref="axis:x"))
        dr = p.get("draw", {})
        t_s, t_e = ctx.at(dr.get("start"), 0.4), ctx.at(dr.get("end"), max(0.8, ctx.duration * 0.6))
        hl = {h.lower() for h in p.get("highlight", [])}
        for i, (lab, a, b) in enumerate(zip(labels, lo, hi)):
            t_i = t_s + (t_e - t_s) * i / max(1, n)
            yc = Tp + row * (i + 0.5)
            _, sty = ctx.lith(lab)
            xa, xb = float(X(a)), float(X(max(b, a * 1.04)))
            emph = lab.lower() in hl
            items.append({"type": "rect", "x": xa, "y": yc - row * 0.3, "w": max(6.0, xb - xa), "h": row * 0.6,
                          "r": 6, "fill": sty["fill"], "stroke": th["accent"] if emph else th["ink"],
                          "lw": 4 if emph else 1.8, "pattern": {"kind": sty.get("pattern", "none"), "spacing": ctx.s(10),
                                                               "size": 1.6, "seed": i},
                          "t0": t_i, "appear": "draw", "grow_dir": "right", "fade_in": 0.5})
            texts.append(T(lab, L - ctx.s(14), yc, size=ctx.s(22), font="label", color=th["ink"], anchor="rm", t0=t_i,
                           max_w=name_w - ctx.s(20), line_h=1.0, hl_color=th["accent"]))
            rng = fmt_num(a, ctx.lang) if a == b else f"{fmt_num(a, ctx.lang)}–{fmt_num(b, ctx.lang)}"
            texts.append(T(rng, xb + ctx.s(10), yc, size=ctx.s(19), font="mono", color=th["ink_soft"], anchor="lm",
                           t0=t_i + 0.3, kind_num="data", source_ref=f"dataset:{p.get('table_ref', 'table')}"))
        if p.get("x_label"):
            texts.append(T(p["x_label"], R, B + ctx.s(46), size=ctx.s(18), font="body", color=th["chart"]["tick_text"],
                           anchor="rt", t0=0.2))
        if p.get("title"):
            texts.append(T(p["title"], bx + ctx.s(20), by + ctx.s(24), size=ctx.s(24), font="title", color=th["ink"],
                           anchor="lt", t0=0.1, max_w=bw - ctx.s(40)))
        if p.get("caption"):
            texts.append(T(p["caption"], bx + ctx.s(8), by + bh - ctx.s(4), size=ctx.s(16), font="body_regular",
                           color=th["ink_soft"], anchor="lb", t0=0.3, max_w=bw - 20))
        checks = [{"id": "ranges_valid", "type": "assert", "ok": bool(np.all(hi >= lo)), "text": "every max >= min"}]
        return {"items": items, "texts": texts, "probes": [], "checks": checks, "state": {}}
