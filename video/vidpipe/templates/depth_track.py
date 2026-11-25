"""depth_track: an object (logging tool, bit, sensor...) moves along depth in a cutaway, while a log
track draws the measured curve. ONE state array depth(t) drives both the object and the curve head.

Works with any curve from any LAS (model type 'las'), any lithology list, any direction of particles.
"""
import numpy as np

from .base import (Template, Scale, T, callout, nice_ticks, log_ticks, fmt_num, panel, place_callouts,
                   text_box_size)
from ..render2d import shade


class DepthTrack(Template):
    name = "depth_track"
    purpose = ("Object moving along depth (tool on cable, bit, sensor) in a geological cutaway + a log track "
               "that draws a real curve; the curve point is always at the object's current depth.")
    classes = ("A", "B")
    needs_model = True
    required = {
        "track": "{curve: mnemonic, unit, range?: [min,max], log?: bool, title?: str}",
    }
    optional = {
        "window": "[top, base] depth window (default: model depth range)",
        "layers": "[{top, base, lith, label?}] lithology bands for the cutaway (depth units of the model)",
        "object": "{kind: tool|bit|sensor, label?: str}",
        "motion": "{start?, end?: time-ref, profile?: smooth|linear, direction?: down|up (up = logging while "
                  "pulling out), show_full?: bool (whole curve already logged), margin?: 0..0.2}",
        "particles": "{direction: to_object|from_object, rate: curve|number, label?: str, start?: time-ref}",
        "markers": "[{depth, label}] horizontal marker lines (e.g. formation tops)",
        "annotations": "[{depth, text}] labels that appear when the object passes that depth",
        "readout": "bool: live value readout at the curve head",
        "shade": "{cutoff, below_color?, above_color?} fill between curve and cutoff",
        "callouts": "[{text, at: time-ref, target: object|curve}]",
        "caption": "small source caption under the track (dataset · well · curve)",
    }
    example = {
        "track": {"curve": "GR", "unit": "API", "range": [0, 150]},
        "window": [4285, 4360],
        "layers": [{"top": 4285, "base": 4317, "lith": "shale"}, {"top": 4317, "base": 4340, "lith": "sandstone"},
                   {"top": 4340, "base": 4360, "lith": "shale"}],
        "object": {"kind": "tool", "label": "tool"},
        "particles": {"direction": "to_object", "rate": "curve"},
        "readout": True,
    }

    @classmethod
    def settled_params(cls, params):
        p = dict(params)
        p["motion"] = dict(p.get("motion") or {}, show_full=True, start="100%")
        p.pop("annotations", None)
        p.pop("callouts", None)
        p["readout"] = False
        if isinstance(p.get("particles"), dict):
            p.pop("particles")
        return p

    def plan(self, p, model, ctx):
        th, dom = ctx.theme, ctx.domain
        probe = dom.legend.get("probe_colors", {"a": "#1E5AA8", "b": "#C81E3C"})
        depth = np.asarray(model["depth"], float)
        val = np.asarray(model["value"], float)
        win = p.get("window") or [float(depth.min()), float(depth.max())]
        top, base = float(win[0]), float(win[1])
        m = (depth >= top) & (depth <= base) & np.isfinite(val)
        depth, val = depth[m], val[m]
        tr = p["track"]
        vr = tr.get("range") or [float(np.nanpercentile(val, 1)), float(np.nanpercentile(val, 99))]
        logx = bool(tr.get("log", False))

        bx, by, bw, bh = ctx.box
        if ctx.portrait:
            cut = (bx, bx + bw * 0.52)
            lab = (bx + bw * 0.54, bx + bw * 0.66)
            trk = (bx + bw * 0.67, bx + bw)
        else:
            cut = (bx + bw * 0.10, bx + bw * 0.48)
            lab = (bx + bw * 0.50, bx + bw * 0.57)
            trk = (bx + bw * 0.58, bx + bw * 0.84)
        y_head = by + ctx.s(56)                       # room for the track header
        y0, y1 = y_head + 8, by + bh - 6
        D = Scale(top, base, y0, y1)                  # depth increases downward: y1 > y0
        X = Scale(vr[0], vr[1], trk[0] + 6, trk[1] - 6, log=logx)

        # ------------------------------------------------ the ONE state model of motion: depth(t)
        mo = p.get("motion", {})
        ts = ctx.at(mo.get("start"), 0.5)
        te = ctx.at(mo.get("end"), ctx.duration - 0.6)
        te = max(ts + 0.5, te)
        u = np.clip((ctx.times - ts) / (te - ts), 0, 1)
        if mo.get("profile", "smooth") == "smooth":
            u = u * u * (3 - 2 * u)
        mg = (base - top) * float(mo.get("margin", 0.05))
        going_up = mo.get("direction", "down") == "up"     # 'up' = recording while the tool is pulled upward
        if going_up:
            d_obj = (base - mg) - (base - top - 2 * mg) * u
        else:
            d_obj = (top + mg) + (base - top - 2 * mg) * u     # depth of the measuring point at every frame
        y_obj = D(d_obj)

        items, texts, state = [], [], {"t": ctx.times, "depth": d_obj, "y_sensor": y_obj}
        ink = th["ink"]
        ow = th.get("outline_w", 3)

        # ------------------------------------------------ cutaway: layers
        layers = p.get("layers") or [{"top": top, "base": base, "lith": "unknown"}]
        cw = cut[1] - cut[0]
        layer_boxes = []
        for i, L in enumerate(layers):
            lt, lb = max(top, float(L["top"])), min(base, float(L["base"]))
            if lb <= lt:
                continue
            key, sty = ctx.lith(L.get("lith"))
            items.append({"type": "rect", "x": cut[0], "y": float(D(lt)), "w": cw, "h": float(D(lb) - D(lt)),
                          "fill": sty["fill"], "pattern": {"kind": sty.get("pattern", "none"), "spacing": ctx.s(15),
                                                           "size": 2.0, "seed": i + 1},
                          "t0": 0.0, "fade_in": 0.5, "appear": "draw", "grow_dir": "down"})
            if L.get("label"):
                lx = cut[0] + ctx.s(14)
                lw_, lh_ = text_box_size(th, L["label"], ctx.s(24), None, pad=(10, 5))
                ly = float((D(lt) + D(lb)) / 2)
                layer_boxes.append((lx - 10, ly - lh_ / 2, lx - 10 + lw_, ly + lh_ / 2))
                texts.append(T(L["label"], lx, ly, size=ctx.s(24), font="label",
                               color=ink, anchor="lm", t0=0.3,
                               bg={"fill": th["panel"], "opacity": 0.82, "radius": 10, "pad": [10, 5]},
                               source_ref=L.get("source_ref")))
        for L in layers[1:]:
            yb = float(D(max(top, min(base, float(L["top"])))))
            items.append({"type": "line", "x1": cut[0], "y1": yb, "x2": cut[1], "y2": yb, "stroke": ink,
                          "lw": 2, "t0": 0.2})
        items.append({"type": "rect", "x": cut[0], "y": y0, "w": cw, "h": y1 - y0, "stroke": ink, "lw": ow,
                      "t0": 0.0})

        # ------------------------------------------------ borehole, cable, tool
        hole_w = ctx.s(62)
        hx = cut[0] + cw * 0.62
        mud = dom.fluid_color("mud")
        items.append({"type": "rect", "x": hx - hole_w / 2, "y": y0, "w": hole_w, "h": y1 - y0,
                      "fill": mud, "fill_opacity": 0.92, "t0": 0.1})
        for sx in (hx - hole_w / 2, hx + hole_w / 2):
            items.append({"type": "line", "x1": sx, "y1": y0, "x2": sx, "y2": y1, "stroke": ink, "lw": ow, "t0": 0.1})
        tool_h, tool_w = ctx.s(118), ctx.s(30)
        sensor_off = tool_h * 0.66                       # sensor position inside the tool body
        tool_top = (y_obj - sensor_off).tolist()
        inner = []                                       # everything that must stay inside the cutaway
        part = p.get("particles")
        if part:
            P = self._particles(part, d_obj, y_obj, hx, hole_w, cut, D, depth, val, vr, ctx, seed=11)
            np.savez_compressed(f"{ctx.shot_dir}/{ctx.shot_id}_particles.npz", P=P)
            inner.append({"type": "points", "npz": f"{ctx.shot_id}_particles.npz", "key": "P", "r": ctx.s(3.4),
                          "fill": th["accent3"], "glow": th["accent3"], "t0": ctx.at(part.get("start"), 0.0),
                          "fade_in": 0.6})
        inner.append({"type": "line", "x1": hx, "y1": 0, "x2": hx, "y2": 0,
                      "stroke": th["equipment"]["cable"], "lw": 3, "tracks": {"y2": tool_top}, "t0": 0.0})
        inner.append({"type": "rect", "x": hx - tool_w / 2, "y": 0, "w": tool_w, "h": tool_h, "r": tool_w / 2,
                      "fill": th["equipment"]["body"], "stroke": ink, "lw": ow, "tracks": {"y": tool_top}, "t0": 0.0,
                      "fade_in": 0.2})
        # sensor band = probe A (exact colour, QA looks for it)
        band_h = ctx.s(16)
        inner.append({"type": "rect", "x": hx - tool_w / 2 + 2, "y": 0, "w": tool_w - 4, "h": band_h,
                      "fill": probe["a"], "tracks": {"y": (y_obj - band_h / 2).tolist()}, "t0": 0.0, "fade_in": 0.2})
        inner.append({"type": "circle", "cx": hx, "cy": 0, "r": tool_w * 0.18, "fill": ink,
                      "tracks": {"cy": (np.array(tool_top) + tool_h - 6).tolist()}, "t0": 0.0})
        items.append({"type": "group", "items": inner, "t0": 0.0, "fade_in": 0.01,
                      "clip": {"type": "rect", "x": cut[0] + 2, "y": y0 + 2, "w": cw - 4, "h": y1 - y0 - 4}})
        # cable above the window (comes from the surface, outside the zoomed cutaway)
        items.append({"type": "line", "x1": hx, "y1": by - ctx.s(10), "x2": hx, "y2": y0,
                      "stroke": th["equipment"]["cable"], "lw": 3, "t0": 0.0})
        to_place = []          # callouts positioned at the end by place_callouts (time-aware, no overlaps)
        static_boxes = []      # boxes of fixed labels the callouts must not cover
        if part and part.get("label"):
            t_p = ctx.at(part.get("at"), ts + 1.0)
            k = min(ctx.n - 1, int(t_p * ctx.fps))
            side = cut[0] + (hx - hole_w / 2 - cut[0]) * 0.5
            to_place.append({"text": part["label"], "size": ctx.s(24), "target": (side, float(y_obj[k])),
                             "t0": t_p, "source_ref": part.get("source_ref")})

        # ------------------------------------------------ track panel, grid, ticks
        items.append(panel(trk[0], y_head - ctx.s(50), trk[1] - trk[0], y1 - y_head + ctx.s(50) + 6, th, r=14,
                           fill=th["chart"]["bg"], shadow=False, lw=2))
        dt = nice_ticks(top, base, 6 if ctx.portrait else 7)
        for d in dt:
            yy = float(D(d))
            items.append({"type": "line", "x1": trk[0], "y1": yy, "x2": trk[1], "y2": yy,
                          "stroke": th["chart"]["grid"], "lw": 1.5, "t0": 0.1})
            texts.append(T(fmt_num(d, ctx.lang), lab[1] - 4, yy, size=ctx.s(21), font="mono",
                           color=th["chart"]["tick_text"], anchor="rm", t0=0.2, kind_num="axis",
                           source_ref="axis:depth"))
        xt = log_ticks(vr[0], vr[1]) if logx else nice_ticks(vr[0], vr[1], 3)
        for v in xt:
            xx = float(X(v))
            items.append({"type": "line", "x1": xx, "y1": y0, "x2": xx, "y2": y1,
                          "stroke": th["chart"]["grid"], "lw": 1.5, "t0": 0.1})
        title = tr.get("title") or f"{tr['curve']}, {tr.get('unit', '')}".strip(", ")
        texts.append(T(title, (trk[0] + trk[1]) / 2, y_head - ctx.s(30), size=ctx.s(24), font="label",
                       color=dom.curve_color(tr["curve"]), anchor="cm", t0=0.2))
        texts.append(T(fmt_num(vr[0], ctx.lang), trk[0] + 8, y_head - ctx.s(6), size=ctx.s(18), font="mono",
                       color=th["chart"]["tick_text"], anchor="lm", t0=0.2, kind_num="axis",
                       source_ref="axis:track"))
        texts.append(T(fmt_num(vr[1], ctx.lang), trk[1] - 8, y_head - ctx.s(6), size=ctx.s(18), font="mono",
                       color=th["chart"]["tick_text"], anchor="rm", t0=0.2, kind_num="axis",
                       source_ref="axis:track"))
        texts.append(T(ctx.T["depth_m"], lab[1] - 4, y_head - ctx.s(30), size=ctx.s(16), font="body",
                       color=th["chart"]["tick_text"], anchor="rm", t0=0.2, max_w=lab[1] - lab[0] + 30,
                       align="right"))

        # ------------------------------------------------ the curve, revealed down to the object's depth
        step = max(1, len(depth) // 900)
        dd, vv = depth[::step], val[::step]
        if going_up:                                   # the curve grows from the bottom
            dd_r, vv_r = dd[::-1], vv[::-1]
            pts = np.column_stack([X(np.clip(vv_r, vr[0], vr[1])), D(dd_r)])
            reveal_n = np.interp(-d_obj, -dd_r, np.arange(len(dd_r)) + 1.0, left=1.0, right=float(len(dd_r)))
        else:
            pts = np.column_stack([X(np.clip(vv, vr[0], vr[1])), D(dd)])
            reveal_n = np.interp(d_obj, dd, np.arange(len(dd)) + 1.0, left=1.0, right=float(len(dd)))
        if mo.get("show_full"):                        # static scene with the whole curve already logged
            reveal_n = np.full(ctx.n, float(len(dd)))
        col = dom.curve_color(tr["curve"])
        sh = p.get("shade")
        show_full = bool(mo.get("show_full"))
        curve_item = {"type": "polyline", "pts": pts.round(2).tolist(), "stroke": col, "lw": ctx.s(3.2),
                      "tracks": {"reveal_n": reveal_n.round(3).tolist()}, "t0": 0.0, "fade_in": 0.01}
        if not show_full:      # the head marks "measured at the tool depth"; a finished log has no live point
            curve_item["head"] = {"r": ctx.s(8), "fill": probe["b"], "stroke": th["panel"], "lw": 2}
        if sh:
            curve_item["fill_to"] = {"x": float(X(sh["cutoff"])), "color": sh.get("color", col), "opacity": 0.18}
        items.append(curve_item)
        v_obj = np.interp(d_obj, dd, vv)
        state.update({"value_at_sensor": v_obj, "x_head": X(np.clip(v_obj, vr[0], vr[1])), "y_head": y_obj})

        if p.get("readout", False):
            unit = tr.get("unit", "")
            txt_track = [f"{fmt_num(v, ctx.lang)} {unit}".strip() for v in v_obj]
            texts.append({"kind": "label", "text": txt_track[0], "text_track": txt_track[::3], "text_track_every": 3,
                          "x": float(trk[0]), "y": 0, "size": ctx.s(22), "font": "mono", "color": th["panel"],
                          "anchor": "rm", "t0": ts, "bg": {"fill": col, "radius": 10, "pad": [9, 5]},
                          "tracks": {"x": (state["x_head"] - ctx.s(16)).round(1).tolist(), "y": y_obj.round(1).tolist()},
                          "kind_num": "data", "source_ref": f"dataset:{tr['curve']}"})

        # ------------------------------------------------ markers and annotations
        for mk in p.get("markers", []):
            yy = float(D(mk["depth"]))
            if not (y0 <= yy <= y1):
                continue
            items.append({"type": "line", "x1": cut[0], "y1": yy, "x2": trk[1], "y2": yy,
                          "stroke": mk.get("color") or th["accent"], "lw": 2.5, "dash": [8, 6],
                          "t0": ctx.at(mk.get("at"), 0.3), "appear": "draw", "fade_in": 0.5})
            if mk.get("label"):
                mw_, mh_ = text_box_size(th, mk["label"], ctx.s(19), None, pad=(8, 4))
                static_boxes.append((cut[1] - 8 - mw_, yy - ctx.s(14) - mh_ / 2, cut[1], yy - ctx.s(14) + mh_ / 2))
                texts.append(T(mk["label"], cut[1] - 8, yy - ctx.s(14), size=ctx.s(19), font="label",
                               color=mk.get("color") or th["accent"], anchor="rm", t0=ctx.at(mk.get("at"), 0.3),
                               source_ref=mk.get("source_ref"), kind_num=mk.get("kind_num"),
                               bg={"fill": th["panel"], "opacity": 0.9, "radius": 8, "pad": [8, 4]}))
        for an in p.get("annotations", []):
            d_a = float(an["depth"])
            passed = np.where((d_obj <= d_a) if going_up else (d_obj >= d_a))[0]
            t_a = float(ctx.times[passed[0]]) if len(passed) else ctx.duration - 1.0
            t_a = ctx.at(an.get("at"), t_a)
            yy = float(D(d_a))
            tx = float(X(np.clip(np.interp(d_a, dd, vv), vr[0], vr[1])))
            to_place.append({"text": an["text"], "size": ctx.s(23), "target": (tx, yy), "t0": t_a,
                             "t1": ctx.at(an.get("until"), None) if an.get("until") else None,
                             "source_ref": an.get("source_ref")})
        for co in p.get("callouts", []):
            t_c = ctx.at(co.get("at"), ts + 1.0)
            k = min(ctx.n - 1, int(t_c * ctx.fps))
            on_obj = co.get("target", "object") == "object"
            tgt = (hx + tool_w / 2, float(y_obj[k])) if on_obj else (float(state["x_head"][k]), float(y_obj[k]))
            to_place.append({"text": co["text"], "size": ctx.s(23), "target": tgt, "t0": t_c,
                             "t1": ctx.at(co.get("until"), None) if co.get("until") else None,
                             "follow": on_obj and co.get("follow", True), "source_ref": co.get("source_ref")})
        if to_place:
            obst = [{"boxes": np.column_stack([np.full(ctx.n, hx - tool_w / 2 - 8), np.array(tool_top) - 8,
                                               np.full(ctx.n, hx + tool_w / 2 + 8),
                                               np.array(tool_top) + tool_h + 8]), "w": 14.0},
                    {"box": (trk[0], y_head - ctx.s(54), trk[1], y_head + 4), "w": 10.0},
                    {"box": (lab[0], y0, lab[1], y1), "w": 1.5}]
            if not show_full:
                hr = ctx.s(16)
                obst.append({"boxes": np.column_stack([state["x_head"] - hr, y_obj - hr, state["x_head"] + hr,
                                                       y_obj + hr]), "w": 10.0})
            if part:
                obst.append({"boxes": np.column_stack([np.full(ctx.n, cut[0]), y_obj - ctx.s(110),
                                                       np.full(ctx.n, cut[1]), y_obj + ctx.s(110)]),
                             "t0": ctx.at(part.get("start"), 0.0), "w": 0.8})
            if p.get("readout", False):
                rw, rh = text_box_size(th, f"000,0 {tr.get('unit', '')}", ctx.s(22), None, font_key="mono",
                                       pad=(9, 5))
                rx1 = state["x_head"] - ctx.s(16)
                obst.append({"boxes": np.column_stack([rx1 - rw - 6, y_obj - rh / 2 - 6, rx1 + 6, y_obj + rh / 2 + 6]),
                             "t0": ts, "w": 14.0})
            obst += [{"box": b, "w": 8.0} for b in layer_boxes + static_boxes]
            narrow = [ctx.w * 0.42, ctx.w * 0.30, ctx.w * 0.22]
            spots = place_callouts(ctx, [dict(L, max_w=narrow) for L in to_place], obst,
                                   (bx, by, bx + bw, y1), curve=(pts, reveal_n))
            for L, sp in zip(to_place, spots):
                extra = {"follow_y": False, "max_w": sp["max_w"], "anchor": "lt"}
                if L.get("follow"):
                    extra["track_target_y"] = y_obj.round(1).tolist()
                texts.append(callout(L["text"], L["target"], (sp["x"], sp["y"]), t0=L["t0"], t1=L.get("t1"),
                                     size=L["size"], source_ref=L.get("source_ref"), **extra))

        # ------------------------------------------------ probes and invariants
        probes = [{"name": "sensor", "color": probe["a"], "region": [cut[0], y0 - 20, cut[1], y1 + 20],
                   "expect_y": y_obj.round(2).tolist()},
                  {"name": "curve_head", "color": probe["b"], "region": [trk[0], y0 - 20, trk[1], y1 + 20],
                   "expect_y": y_obj.round(2).tolist()}]
        if show_full:
            probes = [pr for pr in probes if pr["name"] != "curve_head"]
        checks = [
            {"id": "depth_down", "type": "assert", "ok": bool(D(base) > D(top)),
             "text": "depth axis increases downward"},
            {"id": "same_state", "type": "assert",
             "ok": bool(np.max(np.abs(state["y_head"] - state["y_sensor"])) < 1e-6),
             "text": "curve head depth == object depth (same array)"},
        ] + ([] if show_full else [
            {"id": "frame_same_y", "type": "frame_same_y", "a": "sensor", "b": "curve_head", "tol_px": 4,
             "text": "in rendered frames the curve point is at the tool's depth"}]) + [
            {"id": "data_points", "type": "assert", "ok": bool(len(depth) >= 20),
             "text": f"enough data points in window ({len(depth)})"},
        ]
        if p.get("caption"):
            texts.append(T(p["caption"], trk[1], y1 + ctx.s(14), size=ctx.s(16), font="body_regular",
                           color=th["ink_soft"], anchor="rt", t0=0.4, max_w=bw))
        regions = [{"key": "schematic", "x": cut[0], "y": y1 + ctx.s(12), "anchor": "lt"},
                   {"key": "data" if getattr(ctx, "model_kind", "las") in ("las", "csv") else "simulation",
                    "x": trk[1], "y": by + ctx.s(40) - ctx.s(36) - 6, "anchor": "rb"}]
        return {"items": items, "texts": texts, "probes": probes, "checks": checks, "state": state,
                "regions": regions}

    # --------------------------------------------------------------------------------------------
    def _particles(self, part, d_obj, y_obj, hx, hole_w, cut, D, depth, val, vr, ctx, seed=11, nmax=90):
        """Point cloud per frame. Rate at the sensor depth is proportional to the curve value there
        (the same data the track draws), so 'more particles' always means 'higher reading'."""
        rng = np.random.default_rng(seed)
        fps = ctx.fps
        life = int(0.75 * fps)
        P = np.zeros((ctx.n, nmax, 3), np.float32)
        alive = []                                    # [x0, y0, birth_frame, slot]
        free = list(range(nmax))
        rate_mode = part.get("rate", "curve")
        direction = part.get("direction", "to_object")
        span = max(1e-9, vr[1] - vr[0])
        for f in range(ctx.n):
            if rate_mode == "curve":
                v = np.interp(d_obj[f], depth, val)
                lam = 0.25 + 3.0 * np.clip((v - vr[0]) / span, 0, 1.5) ** 1.3   # births per frame
            else:
                lam = float(rate_mode)
            for _ in range(rng.poisson(lam)):
                if not free:
                    break
                side = rng.choice([-1, 1])
                x0 = hx + side * rng.uniform(hole_w * 0.75, max(hole_w * 0.8, (cut[1] - cut[0]) * 0.42))
                x0 = float(np.clip(x0, cut[0] + 6, cut[1] - 6))
                y0 = float(y_obj[f] + rng.uniform(-1, 1) * ctx.s(110))
                alive.append([x0, y0, f, free.pop()])
            still = []
            for x0, y0, b, slot in alive:
                age = (f - b) / life
                if age >= 1:
                    free.append(slot)
                    continue
                sx, sy = hx, float(y_obj[f])
                if direction == "to_object":
                    x, y = x0 + (sx - x0) * age, y0 + (sy - y0) * age
                else:
                    x, y = sx + (x0 - sx) * age, sy + (y0 - sy) * age
                al = min(1.0, age * 5) * (1 - max(0, age - 0.75) * 4)
                P[f, slot] = (x, y, al)
                still.append([x0, y0, b, slot])
            alive = still
        return P
