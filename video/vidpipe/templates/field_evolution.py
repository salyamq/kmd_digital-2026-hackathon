"""field_evolution: a scalar field u(x, t) from the state model, shown as a map (plan view around a
source, or a 1D strip) plus a synced profile chart u(x) at the current time. Both read the SAME array
at the SAME time index k(frame), and the 'front' (where u crosses a threshold) is marked in both.
"""
import math

import numpy as np

from .base import Template, Scale, T, callout, nice_ticks, log_ticks, fmt_num, panel
from ..evaluator import from_si


def _time_label(t_s, lang):
    units = [(86400, "сут" if lang == "ru" else "d"), (3600, "ч" if lang == "ru" else "h"),
             (60, "мин" if lang == "ru" else "min"), (1, "с" if lang == "ru" else "s")]
    for k, u in units:
        if t_s >= k:
            return f"t = {fmt_num(t_s / k, lang, 1)} {u}"
    return f"t = {fmt_num(t_s, lang, 2)} " + units[-1][1]


class FieldEvolution(Template):
    name = "field_evolution"
    purpose = ("A field computed by the state model spreading in time (pressure, temperature, concentration...): "
               "map view + synced profile chart from the same array, with the disturbance front marked in both.")
    classes = ("B",)
    needs_model = True
    required = {
        "field": "{output: name of the model array, x_axis: 'r'|'x' axis name, t_axis: 't'}",
    }
    optional = {
        "view": "plan_radial (source at centre, default) | strip (1D bar)",
        "display_unit": "unit to show values in (e.g. bar); model output is SI",
        "x_display_unit": "unit for distance axis (default m)",
        "x_max": "max distance shown (model x units, SI)",
        "x_scale": "log|lin for the chart",
        "time": "{start: time-ref, end: time-ref} video interval over which model time advances",
        "front": "{threshold: value in display_unit, label?: str}",
        "ghosts": "number of earlier profiles kept faint on the chart (default 3)",
        "labels": "{x: 'r, м', y: 'Δp, бар', source: 'скважина', colorbar: 'Δp, бар'}",
        "invert_values": "bool: plot -u (e.g. pressure drop shown as depression)",
    }
    example = {"field": {"output": "dp", "x_axis": "r", "t_axis": "t"}, "display_unit": "bar",
               "x_max": 1000, "front": {"threshold": 0.1}, "labels": {"x": "r, м", "y": "Δp, бар"}}

    @classmethod
    def settled_params(cls, params):
        p = dict(params)
        p["time"] = {"start": 0.0, "end": 0.6}
        if isinstance(p.get("front"), dict):
            p["front"] = {k: v for k, v in p["front"].items() if k != "label"}
        return p

    def plan(self, p, model, ctx):
        th, dom = ctx.theme, ctx.domain
        probe = dom.legend.get("probe_colors", {"a": "#1E5AA8", "b": "#C81E3C", "c": "#0B8F6A"})
        fs = p["field"]
        U = np.asarray(model[fs["output"]], float)                     # [nx, nt] SI
        xs = np.asarray(model["axis_" + fs.get("x_axis", "r")], float)
        tt = np.asarray(model["axis_" + fs.get("t_axis", "t")], float)
        du = p.get("display_unit")
        Ud = from_si(U, du) if du else U
        if p.get("invert_values"):
            Ud = -Ud
        xdu = p.get("x_display_unit", "m")
        xsd = from_si(xs, xdu)
        x_max = float(p.get("x_max", xsd.max()))
        lab = {"x": "r, м" if ctx.lang == "ru" else "r, m", "y": "", "source": "", "colorbar": ""}
        lab.update(p.get("labels", {}))

        # ------------------------------------------------ the ONE state model of time: k(frame)
        tm = p.get("time", {})
        ts, te = ctx.at(tm.get("start"), 0.6), ctx.at(tm.get("end"), ctx.duration - 0.8)
        te = max(ts + 0.5, te)
        u = np.clip((ctx.times - ts) / (te - ts), 0, 1)
        k = u * (len(tt) - 1)                                          # float index into model time axis
        t_now = np.interp(k, np.arange(len(tt)), tt)

        # front radius per model time (where u crosses threshold), then per frame
        thr = (p.get("front") or {}).get("threshold")
        r_front_t = np.full(len(tt), np.nan)
        if thr is not None:
            for j in range(len(tt)):
                col = Ud[:, j]
                above = np.where(col >= thr)[0]
                if len(above):
                    i = above.max()
                    if i + 1 < len(col) and col[i] != col[i + 1]:
                        f = (col[i] - thr) / (col[i] - col[i + 1])
                        r_front_t[j] = xsd[i] + f * (xsd[i + 1] - xsd[i])
                    else:
                        r_front_t[j] = xsd[i]
        r_front = np.interp(k, np.arange(len(tt)), np.nan_to_num(r_front_t, nan=0.0))
        has_front = thr is not None and np.nanmax(r_front_t) > 0

        bx, by, bw, bh = ctx.box
        if ctx.portrait:
            S = min(bw * 0.78, bh * 0.50)
            plan_box = (bx + (bw - S) / 2 - ctx.s(30), by + 6, S, S)
            chart = (bx + ctx.s(70), by + S + ctx.s(60), bw - ctx.s(90), bh - S - ctx.s(110))
        else:
            # map | colorbar | chart, computed from the box so it also fits a narrowed box (overlay_card base)
            cb_space = ctx.s(26 + 18 + 64)              # gap + bar + value labels
            gap = ctx.s(60 + 26)                        # chart panel margin (y tick labels) + air
            S = min(bh * 0.92, bw * 0.42)
            cw_min = bw * 0.40
            if bw * 0.02 + S + cb_space + gap + cw_min > bw:
                S = max(bw * 0.25, bw * 0.98 - cb_space - gap - cw_min)
            plan_box = (bx + bw * 0.02, by + (bh - S) / 2, S, S)
            cx0 = plan_box[0] + S + cb_space + gap
            chart = (cx0, by + bh * 0.10, bx + bw - ctx.s(20) - cx0, bh * 0.70)
        items, texts = [], []
        vmax = float(p.get("vmax", np.nanpercentile(Ud, 99.5)))
        vmin = float(p.get("vmin", 0.0))
        cmap = p.get("cmap") or th["field_cmap"]

        # ------------------------------------------------ map image stack [ny, nx, nt]
        view = p.get("view", "plan_radial")
        N = 220
        if view == "plan_radial":
            g = np.linspace(-x_max, x_max, N)
            XX, YY = np.meshgrid(g, g)
            R = np.sqrt(XX ** 2 + YY ** 2)
            stack = np.empty((N, N, len(tt)), np.float32)
            for j in range(len(tt)):
                stack[:, :, j] = np.interp(np.maximum(R, xsd[0]), xsd, Ud[:, j])
            mask = (R <= x_max).astype(np.float32)
            np.savez_compressed(f"{ctx.shot_dir}/{ctx.shot_id}_field.npz", F=stack, M=mask)
            px, py, pw, ph = plan_box
            items.append({"type": "circle", "cx": px + pw / 2, "cy": py + ph / 2, "r": pw / 2 + 6,
                          "fill": th["panel"], "stroke": th["ink"], "lw": th.get("outline_w", 3), "t0": 0.0})
            items.append({"type": "field", "npz": f"{ctx.shot_id}_field.npz", "key": "F", "mask_key": "M",
                          "x": px, "y": py, "w": pw, "h": ph, "cmap": cmap, "vmin": vmin, "vmax": vmax,
                          "gamma": p.get("gamma", 0.6), "tracks": {"k": k.round(4).tolist()}, "t0": 0.0,
                          "fade_in": 0.4})
            cxp, cyp = px + pw / 2, py + ph / 2
            rpx = (pw / 2) / x_max
            # distance ring scale
            for rr in nice_ticks(0, x_max, 3)[1:]:
                if rr < x_max:
                    items.append({"type": "circle", "cx": cxp, "cy": cyp, "r": rr * rpx, "stroke": th["muted"],
                                  "lw": 1.2, "dash": [4, 7], "t0": 0.3})
            if has_front:
                items.append({"type": "circle", "cx": cxp, "cy": cyp, "r": 1.0, "stroke": th["accent"], "lw": 3.5,
                              "dash": [10, 7], "tracks": {"r": np.maximum(1.0, r_front * rpx).round(2).tolist()},
                              "t0": ts})
                # probe A: front marker on the horizontal radius
                items.append({"type": "line", "x1": cxp, "y1": cyp, "x2": cxp + pw / 2, "y2": cyp,
                              "stroke": th["ink"], "lw": 1.5, "t0": 0.3})
            items.append({"type": "circle", "cx": cxp, "cy": cyp, "r": ctx.s(11), "fill": th["equipment"]["body"],
                          "stroke": th["ink"], "lw": 3, "t0": 0.1})
            if has_front:      # drawn above the well symbol so it is never hidden (QA probe)
                items.append({"type": "circle", "cx": cxp, "cy": cyp, "r": ctx.s(7), "fill": probe["a"],
                              "tracks": {"cx": (cxp + np.minimum(r_front, x_max) * rpx).round(2).tolist()}, "t0": ts})
            if lab.get("source"):
                texts.append(callout(lab["source"], [cxp, cyp], [px + pw * 0.2, py + ph * 0.14], t0=0.4,
                                     size=ctx.s(21)))
            texts.append(T(f"{fmt_num(x_max, ctx.lang)} {xdu if xdu != 'm' else ('м' if ctx.lang == 'ru' else 'm')}",
                           cxp + pw / 2 - 4, cyp + ctx.s(16), size=ctx.s(18), font="mono", color=th["ink_soft"],
                           anchor="rt", t0=0.4, kind_num="axis", source_ref="axis:x"))
        else:  # strip: 1D bar along x
            px, py, pw, ph = plan_box[0], plan_box[1] + plan_box[3] * 0.35, plan_box[2], plan_box[3] * 0.3
            stack = np.empty((8, N, len(tt)), np.float32)
            gx = np.linspace(xsd[0], x_max, N)
            for j in range(len(tt)):
                stack[:, :, j] = np.interp(gx, xsd, Ud[:, j])[None, :]
            np.savez_compressed(f"{ctx.shot_dir}/{ctx.shot_id}_field.npz", F=stack)
            items.append({"type": "field", "npz": f"{ctx.shot_id}_field.npz", "key": "F", "x": px, "y": py, "w": pw,
                          "h": ph, "cmap": cmap, "vmin": vmin, "vmax": vmax, "tracks": {"k": k.round(4).tolist()}})
            items.append({"type": "rect", "x": px, "y": py, "w": pw, "h": ph, "stroke": th["ink"], "lw": 3})
            cxp, cyp, rpx = px, py + ph / 2, pw / (x_max - xsd[0])
            if has_front:
                items.append({"type": "circle", "cx": px, "cy": py + ph + ctx.s(14), "r": ctx.s(7), "fill": probe["a"],
                              "tracks": {"cx": (px + (np.minimum(r_front, x_max) - xsd[0]) * rpx).round(2).tolist()},
                              "t0": ts})

        # ------------------------------------------------ colorbar
        if view == "plan_radial":
            cbx = plan_box[0] + plan_box[2] + ctx.s(26)
            cby, cbh = plan_box[1] + plan_box[3] * 0.15, plan_box[3] * 0.7
            grad = np.linspace(vmax, vmin, 64)[:, None] * np.ones((1, 4))
            np.savez_compressed(f"{ctx.shot_dir}/{ctx.shot_id}_cbar.npz", G=grad.astype(np.float32))
            items.append({"type": "field", "npz": f"{ctx.shot_id}_cbar.npz", "key": "G", "x": cbx, "y": cby,
                          "w": ctx.s(18), "h": cbh, "cmap": cmap, "vmin": vmin, "vmax": vmax,
                          "gamma": p.get("gamma", 0.6), "t0": 0.2})
            items.append({"type": "rect", "x": cbx, "y": cby, "w": ctx.s(18), "h": cbh, "stroke": th["ink"],
                          "lw": 1.5, "t0": 0.2})
            texts.append(T(fmt_num(vmax, ctx.lang), cbx + ctx.s(24), cby, size=ctx.s(17), font="mono",
                           color=th["ink_soft"], anchor="lm", t0=0.3, kind_num="axis", source_ref="model:range"))
            texts.append(T(fmt_num(vmin, ctx.lang), cbx + ctx.s(24), cby + cbh, size=ctx.s(17), font="mono",
                           color=th["ink_soft"], anchor="lm", t0=0.3, kind_num="axis", source_ref="model:range"))
            if lab.get("colorbar"):
                texts.append(T(lab["colorbar"], cbx - ctx.s(4), cby - ctx.s(22), size=ctx.s(17), font="body",
                               color=th["ink_soft"], anchor="lm", t0=0.3))

        # ------------------------------------------------ chart u(x) at the current time
        cx0, cy0, cw, chh = chart
        items.append(panel(cx0 - ctx.s(60), cy0 - ctx.s(20), cw + ctx.s(70), chh + ctx.s(70), th, r=16,
                           fill=th["chart"]["bg"], shadow=False, lw=2, t0=0.2))
        xlog = p.get("x_scale", "log") == "log"
        x_lo = float(max(xsd[0], x_max / 1e4)) if xlog else 0.0
        Xs = Scale(x_lo, x_max, cx0, cx0 + cw, log=xlog)
        Ys = Scale(vmin, vmax * 1.05, cy0 + chh, cy0)
        xt = log_ticks(x_lo, x_max) if xlog else nice_ticks(x_lo, x_max, 4)
        for v in xt:
            items.append({"type": "line", "x1": float(Xs(v)), "y1": cy0, "x2": float(Xs(v)), "y2": cy0 + chh,
                          "stroke": th["chart"]["grid"], "lw": 1.3, "t0": 0.3})
            texts.append(T(fmt_num(v, ctx.lang), float(Xs(v)), cy0 + chh + ctx.s(16), size=ctx.s(17), font="mono",
                           color=th["chart"]["tick_text"], anchor="ct", t0=0.3, kind_num="axis", source_ref="axis:x"))
        for v in nice_ticks(vmin, vmax, 4):
            items.append({"type": "line", "x1": cx0, "y1": float(Ys(v)), "x2": cx0 + cw, "y2": float(Ys(v)),
                          "stroke": th["chart"]["grid"], "lw": 1.3, "t0": 0.3})
            texts.append(T(fmt_num(v, ctx.lang), cx0 - ctx.s(10), float(Ys(v)), size=ctx.s(17), font="mono",
                           color=th["chart"]["tick_text"], anchor="rm", t0=0.3, kind_num="axis", source_ref="axis:y"))
        items.append({"type": "line", "x1": cx0, "y1": cy0 + chh, "x2": cx0 + cw, "y2": cy0 + chh,
                      "stroke": th["chart"]["axis"], "lw": 2.5, "t0": 0.25})
        items.append({"type": "line", "x1": cx0, "y1": cy0, "x2": cx0, "y2": cy0 + chh, "stroke": th["chart"]["axis"],
                      "lw": 2.5, "t0": 0.25})
        texts.append(T(lab["x"], cx0 + cw, cy0 + chh + ctx.s(44), size=ctx.s(18), font="body",
                       color=th["chart"]["tick_text"], anchor="rt", t0=0.3))
        if lab.get("y"):
            texts.append(T(lab["y"], cx0 - ctx.s(4), cy0 - ctx.s(4), size=ctx.s(18), font="body",
                           color=th["chart"]["tick_text"], anchor="lb", t0=0.3))
        # profile per frame: sample on a fixed x grid
        gx = np.geomspace(x_lo, x_max, 160) if xlog else np.linspace(x_lo, x_max, 160)
        prof_t = np.stack([np.interp(gx, xsd, Ud[:, j]) for j in range(len(tt))], axis=1)    # [160, nt]
        frames_pts = []
        for f in range(ctx.n):
            kk = k[f]
            j0 = int(math.floor(kk)); j1 = min(len(tt) - 1, j0 + 1); w = kk - j0
            prof = prof_t[:, j0] * (1 - w) + prof_t[:, j1] * w
            frames_pts.append(np.column_stack([Xs(gx), Ys(np.clip(prof, vmin, vmax * 1.05))]).round(1).tolist())
        # ghosts: frozen earlier profiles
        n_g = int(p.get("ghosts", 3))
        if n_g > 0:
            for gi in range(1, n_g + 1):
                fr = int((ts + (te - ts) * gi / (n_g + 1)) * ctx.fps)
                if fr < ctx.n:
                    items.append({"type": "polyline", "pts": frames_pts[fr], "stroke": th["muted"], "lw": 2,
                                  "dash": [6, 6], "t0": fr / ctx.fps, "fade_in": 0.3})
                    texts.append(T(_time_label(float(t_now[fr]), ctx.lang), float(Xs(gx[8])),
                                   float(frames_pts[fr][8][1]) - ctx.s(12), size=ctx.s(15), font="mono",
                                   color=th["muted"], anchor="lb", t0=fr / ctx.fps + 0.2, kind_num="model",
                                   source_ref=f"model:{ctx.shot_id}"))
        items.append({"type": "polyline", "pts": frames_pts[0], "stroke": th["accent2"], "lw": ctx.s(4),
                      "tracks": {"pts": frames_pts}, "t0": ts - 0.2,
                      "fill_to": {"y": cy0 + chh, "color": th["accent2"], "opacity": 0.14}})
        if has_front:
            yb = float(Ys(thr))
            items.append({"type": "line", "x1": cx0, "y1": yb, "x2": cx0 + cw, "y2": yb, "stroke": th["accent"],
                          "lw": 1.5, "dash": [5, 6], "t0": ts})
            items.append({"type": "circle", "cx": 0, "cy": yb, "r": ctx.s(7), "fill": probe["b"],
                          "tracks": {"cx": Xs(np.clip(r_front, x_lo, x_max)).round(2).tolist()}, "t0": ts})
            fl = (p.get("front") or {}).get("label")
            if fl:
                texts.append(callout(fl, [float(Xs(np.clip(r_front[-1], x_lo, x_max))), yb],
                                     [cx0 + cw * 0.72, cy0 + chh * 0.25], t0=ctx.at((p.get("front") or {}).get("at"), te - 1.5),
                                     size=ctx.s(21), track_target_x=Xs(np.clip(r_front, x_lo, x_max)).round(1).tolist(),
                                     source_ref=(p.get("front") or {}).get("source_ref")))
        # time readout (model output -> number on screen, sourced to the model)
        tl = [_time_label(float(v), ctx.lang) for v in t_now]
        tx_, ty_ = (plan_box[0], plan_box[1] + plan_box[3] + ctx.s(14)) if not ctx.portrait else \
            (plan_box[0] + plan_box[2] + ctx.s(10), plan_box[1] + ctx.s(10))
        texts.append({"kind": "label", "text": tl[0], "text_track": tl[::2], "text_track_every": 2,
                      "x": tx_, "y": ty_, "size": ctx.s(26), "font": "mono", "color": th["panel"],
                      "anchor": "lt" if not ctx.portrait else "lt", "t0": ts - 0.3,
                      "bg": {"fill": th["ink"], "radius": 12, "pad": [12, 6]}, "kind_num": "model",
                      "source_ref": f"model:{ctx.shot_id}"})

        state = {"t_model": t_now, "k": k, "r_front": r_front}
        probes, checks = [], []
        if has_front:
            if view == "plan_radial":
                probes.append({"name": "front_map", "color": probe["a"],
                               "region": [plan_box[0] - 10, plan_box[1] - 10, plan_box[0] + plan_box[2] + 10,
                                          plan_box[1] + plan_box[3] + 10],
                               "expect_x": (cxp + np.minimum(r_front, x_max) * rpx).round(2).tolist()})
            probes.append({"name": "front_chart", "color": probe["b"], "region": [cx0 - 10, cy0 - 10, cx0 + cw + 10,
                                                                                 cy0 + chh + 10],
                           "expect_x": Xs(np.clip(r_front, x_lo, x_max)).round(2).tolist()})
            checks.append({"id": "front_monotone", "type": "assert",
                           "ok": bool(np.all(np.diff(np.nan_to_num(r_front_t)) >= -1e-9)),
                           "text": "disturbance front never moves backwards (model)"})
            checks.append({"id": "frame_front", "type": "frame_expect", "probes": [p_["name"] for p_ in probes],
                           "tol_px": 5, "text": "front marker in map and chart at the model's front radius"})
        checks.append({"id": "finite", "type": "assert", "ok": bool(np.isfinite(Ud).mean() > 0.99),
                       "text": "model output finite"})
        checks.append({"id": "spreads_gradually", "type": "assert",
                       "ok": bool(not has_front or (np.nanmin(r_front_t) < 0.5 * np.nanmax(r_front_t))),
                       "text": "front radius grows over the shown time (not instantaneous)"})
        return {"items": items, "texts": texts, "probes": probes, "checks": checks, "state": state}
