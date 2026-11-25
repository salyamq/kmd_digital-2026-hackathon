"""overlay_card: any visual template + a strip of cards (question / myth / fact / equation / text) beside it.
The visual keeps running; cards replace each other at narration cues. The shot's class is the base visual's
class (A/B/C) — the cards are a minority of the frame, unlike full-screen text cards (class T)."""
import copy

from .base import Template, T, panel, fit_size, measure


KIND_STYLE = {   # icon, theme colour key, label key in i18n
    "question": ("question", "accent", "question"),
    "myth": ("cross", "bad", "myth"),
    "fact": ("check", "good", "fact"),
    "equation": (None, "accent2", None),
    "text": ("arrow", "accent2", None),
}


class OverlayCard(Template):
    name = "overlay_card"
    purpose = ("A visual template (base) with question / myth / fact / equation cards beside it, switching at "
               "narration cues. Use it instead of full-screen text cards so every line keeps a visual.")
    classes = ("A", "B", "C")
    required = {"base": "{template: visual template name, params: {...}} (its model is the shot's model)",
                "cards": "[{kind: question|myth|fact|equation|text, text, options?: [..], at: time-ref, "
                         "label?: str, source_ref?: claim id}]"}
    optional = {"position": "auto (below on 9:16, right on 16:9) | below | right", "card_share": "0.2..0.45"}
    example = {"base": {"template": "cross_section", "params": {"units": [
        {"name": "глина", "lith": "clay", "thickness": 1}, {"name": "песчаник", "lith": "sandstone", "thickness": 1}]}},
        "cards": [{"kind": "question", "text": "Где выше радиоактивность?", "options": ["глина", "песчаник"], "at": 0.3},
                  {"kind": "fact", "text": "Наиболее радиоактивны *глины*", "at": "60%"}]}

    def check_params(self, params, model_out=None):
        from . import REGISTRY
        miss = super().check_params(params, model_out)
        base = params.get("base") or {}
        tpl = REGISTRY.get(base.get("template"))
        if tpl is None:
            miss.append(f"unknown base template {base.get('template')}")
        else:
            if tpl.name in ("overlay_card",):
                miss.append("base cannot be overlay_card")
            miss += [f"base.{m}" for m in tpl().check_params(base.get("params") or {}, model_out)]
        for c in params.get("cards", []):
            if c.get("kind", "text") not in KIND_STYLE:
                miss.append(f"unknown card kind {c.get('kind')}")
        return miss

    def plan(self, p, model, ctx):
        from . import REGISTRY
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        pos = p.get("position", "auto")
        if pos == "auto":
            pos = "below" if ctx.portrait else "right"
        share = float(p.get("card_share", 0.30 if pos == "below" else 0.34))
        gap = ctx.s(18)
        if pos == "below":
            ch = bh * share
            base_box = (bx, by, bw, bh - ch - gap)
            card = (bx, by + bh - ch, bw, ch)
        else:
            cw = bw * share
            base_box = (bx, by, bw - cw - gap, bh)
            card = (bx + bw - cw, by + bh * 0.08, cw, bh * 0.84)
        sub = copy.copy(ctx)
        sub.box = base_box
        base = p["base"]
        L = REGISTRY[base["template"]]().plan(base.get("params", {}), model, sub)
        items, texts = list(L["items"]), list(L["texts"])
        b0 = (base_box[0], base_box[1], base_box[0] + base_box[2], base_box[1] + base_box[3])
        for it in texts:                    # the base's callouts must stay beside the cards, never on them
            if it.get("kind") == "callout":
                it.setdefault("bounds", b0)
        cards = sorted(p.get("cards", []), key=lambda c: ctx.at(c.get("at"), 0.0))
        times = [ctx.at(c.get("at"), 0.0) for c in cards]
        cx, cy, cw, chh = card
        for i, c in enumerate(cards):
            t0 = times[i]
            t1 = ctx.at(c.get("until")) if c.get("until") else (times[i + 1] if i + 1 < len(cards) else None)
            kind = c.get("kind", "text")
            icon, col_key, lab_key = KIND_STYLE[kind]
            col = th.get(col_key, th["accent"])
            fo = {"t0": t0, "fade_in": 0.3}
            if t1 is not None:
                fo.update({"t1": t1, "fade_out": 0.25})
            items.append(panel(cx, cy, cw, chh, th, r=20, stroke=col, lw=4, **fo))
            pad = ctx.s(22)
            tx = cx + pad
            top = cy + pad
            if icon:
                items.append({"type": "icon", "kind": icon, "cx": cx + pad + ctx.s(22), "cy": cy + pad + ctx.s(22),
                              "size": ctx.s(30), "stroke": "#FFFFFF", "fill": col, "lw": ctx.s(5), **fo})
                label = c.get("label") or (ctx.T.get(lab_key) if lab_key else None)
                if label:
                    texts.append(T(str(label).upper(), cx + pad + ctx.s(56), cy + pad + ctx.s(22), size=ctx.s(21),
                                   font="mono", color=col, anchor="lm", **fo))
                top = cy + pad + ctx.s(56)
            opts = c.get("options") or []
            opt_h = ctx.s(52) if opts else 0
            room_h = cy + chh - pad - top - (opt_h * (len(opts) if pos == "right" else 1) + (ctx.s(10) if opts else 0))
            font = "display" if kind == "equation" else "title"
            size = fit_size(th, c["text"], font, ctx.s(44 if kind == "equation" else 34), cw - 2 * pad, room_h,
                            line_h=1.1)
            texts.append(T(c["text"], tx, top, size=size, font=font, color=th["ink"], anchor="lt", max_w=cw - 2 * pad,
                           line_h=1.1, hl_color=th["accent"], max_h=room_h, myth=(kind == "myth" or c.get("myth", False)),
                           source_ref=c.get("source_ref"), **fo))
            if opts:
                oy = cy + chh - pad - (opt_h * (len(opts) if pos == "right" else 1))
                x = tx
                for j, o in enumerate(opts):
                    t_o = t0 + 0.6 + 0.5 * j
                    lab = f"*{chr(65 + j)}* · {o}"
                    if pos == "right":
                        ox, oyy = tx, oy + j * opt_h
                    else:
                        w = measure(th, lab, "body", ctx.s(24), 0)[0] + 40
                        if x + w > cx + cw - pad:
                            x = tx
                        ox, oyy = x, oy
                        x += w + ctx.s(14)
                    texts.append(T(lab, ox, oyy, size=ctx.s(24), font="body", color=th["ink"], anchor="lt", t0=t_o,
                                   t1=t1, fade_out=0.25 if t1 else 0.25,
                                   bg={"fill": th["panel"], "stroke": th["ink"], "stroke_w": 2, "radius": 22,
                                       "pad": [16, 7]}))
        L.update({"items": items, "texts": texts})
        L.setdefault("checks", []).append({"id": "cards_timed", "type": "assert",
                                           "ok": all(a <= b for a, b in zip(times, times[1:])),
                                           "text": "overlay cards appear in narration order"})
        return L
