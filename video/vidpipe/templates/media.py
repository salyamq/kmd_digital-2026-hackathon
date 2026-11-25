"""Class C (real photo) and class D (atmosphere / AI clip) templates."""
from .base import Template, T


class Photo(Template):
    name = "photo"
    purpose = "Real photo/footage frame (class C) with a slow zoom/pan (2.5D feel). Needs a licensed real image."
    classes = ("C",)
    required = {"src": "path to a real photo (domain pack photos/ or refs/)"}
    optional = {"caption": "str", "credit": "source/licence line (required for publishing)",
                "zoom": "[from, to]", "pan": "[[x0,y0],[x1,y1]] 0..1", "callouts": "[{text, target:[x,y] 0..1, at}]"}
    example = {"src": "refs/rig.jpg", "credit": "Photo: … (CC BY 4.0)", "zoom": [1.0, 1.12]}

    def plan(self, p, model, ctx):
        from .base import callout
        bx, by, bw, bh = (0, 0, ctx.w, ctx.h) if p.get("full_bleed", True) else ctx.box
        z = p.get("zoom", [1.0, 1.1])
        pan = p.get("pan", [[0.5, 0.5], [0.5, 0.5]])
        items = [{"type": "image", "src": p["src"], "x": bx, "y": by, "w": bw, "h": bh, "t0": 0.0, "fade_in": 0.3,
                  "tracks": {"zoom": {"kf": [[0, z[0]], [ctx.duration, z[1]]], "ease": "linear"},
                             "pan_x": {"kf": [[0, pan[0][0]], [ctx.duration, pan[1][0]]], "ease": "smooth"},
                             "pan_y": {"kf": [[0, pan[0][1]], [ctx.duration, pan[1][1]]], "ease": "smooth"}}}]
        texts = []
        if p.get("credit"):
            texts.append(T(p["credit"], ctx.w - 16, ctx.h - 16, size=ctx.s(15), font="body_regular",
                           color="#FFFFFF", anchor="rb", bg={"fill": "#000000", "opacity": 0.45, "radius": 6,
                                                            "pad": [8, 4]}))
        for co in p.get("callouts", []):
            tx, ty = bx + bw * co["target"][0], by + bh * co["target"][1]
            texts.append(callout(co["text"], [tx, ty], [tx + ctx.s(co.get("dx", 60)), ty + ctx.s(co.get("dy", -80))],
                                 t0=ctx.at(co.get("at"), 0.8), size=ctx.s(24), source_ref=co.get("source_ref")))
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}


class AIClip(Template):
    name = "ai_clip"
    purpose = ("Atmosphere / transition only (class D): an AI video clip between two VERIFIED frames "
               "(real photo or our render). No facts, text, numbers or diagrams in the prompt. "
               "Without a video model configured, a deterministic cross-zoom between the two frames is used.")
    classes = ("D",)
    required = {"first_frame": "path | 'shot:<id>:first' | 'shot:<id>:last'",
                "last_frame": "path | 'shot:<id>:first' | 'shot:<id>:last'",
                "prompt": "motion/mood description only"}
    optional = {"seconds": "3-6"}
    example = {"first_frame": "refs/rig_dusk.jpg", "last_frame": "shot:S2:first",
               "prompt": "slow camera descent from the rig into the ground, dusk light", "seconds": 3}

    def plan(self, p, model, ctx):
        # Fallback layout (used when no AI provider is configured or the clip failed verification).
        a, b = p.get("_first_path"), p.get("_last_path")
        items = []
        if a:
            items.append({"type": "image", "src": a, "x": 0, "y": 0, "w": ctx.w, "h": ctx.h, "t0": 0.0,
                          "tracks": {"zoom": {"kf": [[0, 1.0], [ctx.duration, 1.35]], "ease": "smooth"},
                                     "opacity": {"kf": [[ctx.duration * 0.45, 1.0], [ctx.duration * 0.9, 0.0]]}}})
        if b:
            items.append({"type": "image", "src": b, "x": 0, "y": 0, "w": ctx.w, "h": ctx.h, "t0": 0.0,
                          "tracks": {"zoom": {"kf": [[0, 0.82], [ctx.duration, 1.0]], "ease": "smooth"},
                                     "opacity": {"kf": [[ctx.duration * 0.45, 0.0], [ctx.duration * 0.9, 1.0]]}}})
        return {"items": items, "texts": [], "probes": [], "checks": [
            {"id": "no_text_in_prompt", "type": "assert", "ok": _prompt_ok(p.get("prompt", "")),
             "text": "AI prompt has no digits/text/diagram requests"}], "state": {}}


FORBIDDEN_PROMPT = ["text", "label", "number", "digit", "chart", "graph", "diagram", "arrow", "axis", "caption",
                    "title", "letters", "logo", "надпис", "текст", "цифр", "числ", "график", "диаграм", "стрелк",
                    "подпис", "схем", "формул", "formula"]


def _prompt_ok(prompt):
    import re
    s = prompt.lower()
    return not re.search(r"\d", s) and not any(w in s for w in FORBIDDEN_PROMPT)
