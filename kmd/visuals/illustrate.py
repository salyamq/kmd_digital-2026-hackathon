"""Illustration rendering: spec (schemas/illustration.schema.json) -> SVG/PNG with labels.

Every image carries on the picture itself: the provenance badge («реальные данные» /
«симуляция» / «схема»), named exaggerations («не в масштабе: … ×N»), the redraw source
(«перерисовано по рис. N, стр. M») and the convention used.
"""
from __future__ import annotations

import re
from pathlib import Path

import jsonschema
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from ..config import SCHEMAS, read_json
from .base import REGISTRY, DrawCtx, InvariantError
from .style import badge, provenance_badge, setup_rc, styleguide

SIZES = {"wide": (1200, 750), "tall": (900, 1200), "square": (1000, 1000), "video_v": (1080, 1920),
         "video_h": (1920, 1080)}


# names used by the domain pack (difficulty_types.yaml scene_templates) -> catalog templates
ALIASES = {
    "invasion_profile": "radial_invasion", "tool_in_borehole": "log_track", "function_plot": "crossplot",
    "parameter_sweep": "crossplot", "decision_scale": "crossplot", "threshold_slider": "crossplot",
    "timeline": "timeline_growth", "sequence": "timeline_growth", "cross_section_evolution": "timeline_growth",
    "map_and_section": "plan_map", "decision_flow": "process_chain", "feature_compare": "comparison_bar",
    "block_3d": "cross_section",
}


def get_template(name: str):
    from . import templates  # noqa: F401  (registers)

    name = ALIASES.get(name, name)
    if name not in REGISTRY:
        raise KeyError(f"unknown template {name!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[name]


def exaggeration_text(ex: list[dict]) -> str:
    parts = []
    for e in ex:
        f = e.get("factor")
        if isinstance(f, (int, float)):
            parts.append(f"{e['what']} ×{f:g}")
        elif f:
            parts.append(f"{e['what']} {f}")
        else:
            parts.append(e["what"])
    return "не в масштабе: " + "; ".join(parts) if parts else ""


def redraw_text(rd: dict | None) -> str:
    if not rd:
        return ""
    fig_no = rd.get("figure")
    page = rd.get("page")
    s = "перерисовано по рис. " + str(fig_no) if fig_no else "перерисовано по книге"
    if page:
        s += f", стр. {page}"
    return s


def _draw_legend(fig, items, rect, ctx: DrawCtx):
    if not items:
        return
    x0, y0, w, h = rect
    ax = fig.add_axes(rect)
    ax.set_axis_off()
    ax.set_xlim(0, w * ctx.fig_px[0])
    ax.set_ylim(0, h * ctx.fig_px[1])
    W, H = w * ctx.fig_px[0], h * ctx.fig_px[1]
    sw = ctx.base_px * 1.3
    x, y = 4, H - sw - 2
    for it in items:
        label = it["label"]
        tw = len(label) * ctx.base_px * 0.56 + sw + 18
        if x + tw > W and x > 4:
            x = 4
            y -= sw + 8
        if y < 0:
            break
        if it.get("kind") == "line":
            ax.plot([x, x + sw], [y + sw / 2] * 2, color=it["color"], ls=it.get("ls", "-"), lw=2.2)
        elif it.get("kind") == "dot":
            ax.plot([x + sw / 2], [y + sw / 2], "o", color=it["color"], ms=ctx.base_px * 0.5, mec="white")
        else:
            ax.add_patch(Rectangle((x, y), sw, sw, fc=it["color"], ec="#555555", lw=0.6,
                                   hatch=it.get("hatch") or None))
        ax.text(x + sw + 5, y + sw / 2, label, va="center", ha="left", fontsize=ctx.pt(0.85), color="#212121")
        x += tw


def render(template: str, params: dict, out: str | Path, *, size=(1200, 750), t: float | None = None,
           provenance: str | None = None, title: str | None = None, redrawn_from: dict | None = None,
           exaggerations: list[dict] | None = None, base_px: float | None = None, formats=("svg",),
           check: bool = True, domain: str = "geology") -> dict:
    """Render one template to file(s). Returns {paths, exaggerations, issues, provenance, class}."""
    tpl = get_template(template)
    params = dict(params or {})
    params["_domain"] = domain
    p = tpl.normalize(params)
    issues = tpl.check(p)
    if check and any(i.level == "error" for i in issues):
        raise InvariantError(template, issues)
    sg = styleguide(domain)
    dpi = 100
    W, H = size
    bpx = base_px or max(13.0, min(W, H) / 52)
    setup_rc(sg, base_px=bpx, dpi=dpi)
    fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi)
    ctx = DrawCtx(sg=sg, dpi=dpi, base_px=bpx, mode="illustration", fig_px=(W, H))
    import textwrap

    ttl = title if title is not None else p.get("title", "")
    # title goes on its own line(s) under the provenance badge, wrapped to the image width
    ttl_lines = textwrap.wrap(ttl, max(20, int(W / (bpx * 1.1 * 0.62)))) if ttl else []
    top_h = (bpx * 2.3 + len(ttl_lines) * bpx * 1.45) / H
    foot_h = (bpx * 1.9) / H
    leg_h = (bpx * 2.0 * (2 if W < 1000 else 1.6)) / H
    axl_h = (bpx * 3.0) / H
    lm = max(0.075, bpx * 4.6 / W)
    rect = [lm, foot_h + leg_h + axl_h, 0.98 - lm, 1 - top_h - foot_h - leg_h - axl_h - 0.02]
    res = tpl.draw(fig, rect, p, t, ctx) or {}
    prov = provenance or tpl.provenance_for(p)
    provenance_badge(fig, sg, prov, size_px=bpx * 0.95, dpi=dpi, xy=(0.012, 1 - 0.3 * bpx / H))
    if ttl_lines:
        fig.text(0.5, 1 - 2.0 * bpx / H, "\n".join(ttl_lines), ha="center", va="top", fontsize=ctx.pt(1.1), fontweight="bold",
                 color=sg["palette"]["text"], wrap=True)
    ex = list(res.get("exaggerations", [])) + list(exaggerations or [])
    _draw_legend(fig, res.get("legend", []), [0.02, foot_h + 0.01, 0.96, leg_h], ctx)
    foot = [s for s in (exaggeration_text(ex), redraw_text(redrawn_from)) if s]
    notes = [n for n in res.get("notes", []) if n]
    if foot:
        badge(fig, " · ".join(foot), xy=(0.012, 0.008 + 0.2 * bpx / H), color="#B71C1C", bg="#FFFFFF",
              size_px=bpx * 0.8, dpi=dpi, va="bottom")
    if notes:
        fig.text(0.988, 0.008 + 0.25 * bpx / H, " · ".join(notes), ha="right", va="bottom",
                 fontsize=ctx.pt(0.72), color=sg["palette"]["muted"])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in formats:
        pth = out.parent / f"{out.name}.{fmt}" if not out.suffix.lower() in (".svg", ".png") else out.with_suffix("." + fmt)
        fig.savefig(pth, format=fmt, dpi=dpi, metadata={"Date": None} if fmt == "svg" else None)
        paths.append(pth)
    plt.close(fig)
    return {"paths": paths, "exaggerations": ex, "issues": [i.as_dict() for i in issues],
            "provenance": prov, "class": tpl.class_for(p), "alt": tpl.describe(p)}


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "fig"


def validate_spec(spec: dict) -> None:
    jsonschema.validate(spec, read_json(SCHEMAS / "illustration.schema.json"))


def render_illustration(spec: dict, out_dir: str | Path, fmt: str = "svg") -> dict:
    """Course-facing API. spec: see schemas/illustration.schema.json.

    Returns {path, alt, caption, class, provenance, redrawn_from, exaggerations, template, issues}.
    Raises InvariantError when the params violate a template invariant (physics checklist).
    """
    validate_spec(spec)
    tpl = get_template(spec["template"])
    size = spec.get("size") or ("tall" if tpl.default_size[1] > tpl.default_size[0] else "wide")
    wh = SIZES.get(size, SIZES["wide"]) if isinstance(size, str) else tuple(size)
    ident = _slug(spec.get("id") or spec["template"])
    r = render(spec["template"], spec.get("params", {}), Path(out_dir) / ident, size=wh, t=spec.get("t"),
               provenance=spec.get("provenance"), title=spec.get("title"), redrawn_from=spec.get("redrawn_from"),
               exaggerations=spec.get("exaggerations"), formats=(fmt,), domain=spec.get("domain", "geology"))
    alt = spec.get("alt") or r["alt"]
    caption = spec.get("caption") or ""
    rd = redraw_text(spec.get("redrawn_from"))
    if rd and rd not in caption:
        caption = (caption + " " if caption else "") + f"({rd})"
    return {
        "path": str(r["paths"][0]),
        "alt": alt,
        "caption": caption,
        "class": spec.get("class") or r["class"],
        "provenance": r["provenance"],
        "redrawn_from": spec.get("redrawn_from"),
        "exaggerations": r["exaggerations"],
        "template": spec["template"],
        "claim_ids": spec.get("claim_ids", []),
        "issues": r["issues"],
    }


def _np_default(o):
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError
