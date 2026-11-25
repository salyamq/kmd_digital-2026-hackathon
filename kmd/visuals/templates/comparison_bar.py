"""comparison_bar: compare numbers from the chapter (bars with values written on them)."""
from __future__ import annotations

import numpy as np

from ..base import DrawCtx, Issue, Template, common_props, register


@register
class ComparisonBar(Template):
    name = "comparison_bar"
    title_ru = "Сравнение чисел из главы (столбики с подписями)"
    description = (
        "Горизонтальные столбики для сравнения величин, взятых из главы (диапазоны — отрезками min–max). "
        "Каждое число подписано на столбике. Для тем: сравнение пород/методов/параметров по числу, "
        "пороги и диапазоны применимости. Только числа из источника."
    )
    use_for = ["М", "Р", "И", "сравнение", "диапазоны", "пороги"]
    frame_class = "A"
    provenance = "реальные данные"
    animatable = True
    animation = "t∈[0,1]: столбики растут до значений"
    default_size = (1100, 650)
    params_schema = {
        "type": "object",
        "required": ["items"],
        "properties": {
            **common_props(),
            "items": {"type": "array", "minItems": 1, "maxItems": 14,
                      "items": {"type": "object", "required": ["label"],
                                "properties": {"label": {"type": "string"}, "value": {"type": "number"},
                                               "min": {"type": "number"}, "max": {"type": "number"},
                                               "note": {"type": "string"}, "color": {"type": "string"}}}},
            "value_label": {"type": "string", "default": ""},
            "unit": {"type": "string", "default": ""},
            "scale": {"enum": ["linear", "log"], "default": "linear"},
            "highlight": {"type": ["string", "null"], "default": None},
            "threshold": {"type": ["object", "null"], "default": None,
                          "properties": {"value": {"type": "number"}, "label": {"type": "string"}}},
        },
    }
    example = {
        "title": "Пористость пород (пример)",
        "items": [{"label": "песчаник", "min": 15, "max": 30}, {"label": "известняк", "min": 1, "max": 10},
                  {"label": "глина", "value": 30, "note": "поры есть, но они не проницаемы"}],
        "value_label": "пористость", "unit": "%",
        "threshold": {"value": 9, "label": "граничное значение"},
    }

    def check(self, params):
        iss = []
        for it in params["items"]:
            if it.get("value") is None and (it.get("min") is None or it.get("max") is None):
                iss.append(Issue("error", "no_value", f"«{it['label']}»: нужно value или min+max"))
            if it.get("min") is not None and it.get("max") is not None and it["min"] > it["max"]:
                iss.append(Issue("error", "range", f"«{it['label']}»: min > max"))
            if params["scale"] == "log" and any((it.get(k) or 1) <= 0 for k in ("value", "min", "max")):
                iss.append(Issue("error", "log", "логарифмическая шкала и неположительное значение"))
        return iss

    def describe(self, params):
        u = params.get("unit", "")
        parts = []
        for it in params["items"]:
            if it.get("value") is not None:
                parts.append(f"{it['label']} — {it['value']:g} {u}".strip())
            else:
                parts.append(f"{it['label']} — {it['min']:g}–{it['max']:g} {u}".strip())
        return f"Сравнение ({params.get('value_label', '')}): " + "; ".join(parts) + "."

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        ax = fig.add_axes([rect[0] + rect[2] * 0.22, rect[1], rect[2] * 0.76, rect[3]])
        items = p["items"]
        n = len(items)
        f = 1.0 if t is None else float(t)
        pal = sg["palette"]["series"]
        y = np.arange(n)[::-1]
        if p["scale"] == "log":
            ax.set_xscale("log")
        vmax = max(max(it.get("value") or 0, it.get("max") or 0) for it in items)
        for i, it in enumerate(items):
            col = it.get("color") or (sg["palette"]["accent"] if p.get("highlight") == it["label"] else pal[0])
            if it.get("value") is not None:
                v = it["value"] * f
                ax.barh(y[i], v, color=col, height=0.6, alpha=0.9)
                txt = f"{it['value']:g} {p['unit']}".strip()
                ax.text(v, y[i], " " + txt, va="center", ha="left", fontsize=ctx.pt(0.85), fontweight="bold")
            else:
                a, b = it["min"], it["min"] + (it["max"] - it["min"]) * f
                ax.barh(y[i], b - a, left=a, color=col, height=0.6, alpha=0.9)
                ax.text(b, y[i], f" {it['min']:g}–{it['max']:g} {p['unit']}".rstrip(), va="center", ha="left",
                        fontsize=ctx.pt(0.85), fontweight="bold")
            if it.get("note"):
                ax.text(ax.get_xlim()[0] if p["scale"] == "log" else 0, y[i] - 0.42, " " + it["note"], va="center",
                        ha="left", fontsize=ctx.pt(0.68), color="#616161")
        ax.set_yticks(y)
        ax.set_yticklabels([it["label"] for it in items], fontsize=ctx.pt(0.9))
        ax.set_xlim(right=vmax * (1.35 if p["scale"] == "linear" else 3))
        if p["scale"] == "linear":
            ax.set_xlim(left=0)
        if p.get("threshold"):
            ax.axvline(p["threshold"]["value"], color="#C62828", lw=1.6, ls="--")
            ax.text(p["threshold"]["value"], n - 0.4, " " + p["threshold"].get("label", ""), color="#C62828",
                    fontsize=ctx.pt(0.78), va="bottom")
        ax.set_xlabel((p.get("value_label") or "") + (f", {p['unit']}" if p.get("unit") else ""))
        ax.grid(axis="x", color=sg["palette"]["grid"], lw=0.5)
        ax.spines[["top", "right"]].set_visible(False)
        return {"exaggerations": [], "legend": [], "notes": [], "axes": [ax]}
