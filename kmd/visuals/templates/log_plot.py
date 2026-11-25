"""log_plot: a log display drawn from DATA — digitized curves of a book figure or LAS samples.

Unlike log_track (synthetic curves from a petrophysical model), here every curve is a list of
(depth, value) points. Used for «перерисовано по рис. N, стр. M» of log charts and for real data
(class A). Depth grows downward; scales and units are written in the track headers.
"""
from __future__ import annotations

import math
import textwrap

import numpy as np
from matplotlib.patches import Rectangle

from ..base import DrawCtx, Issue, Template, common_props, register
from ..style import lith
from .log_track import LITH_KEYS

# Russian/English curve names -> style guide curve ids (colors, default scales)
NAME_MAP = {"пс": "SP", "сп": "SP", "sp": "SP", "гк": "GR", "gr": "GR", "дс": "CALI", "кавернограмма": "CALI",
            "cali": "CALI", "нгк": "NGK", "нгм": "NGK", "нк": "NPHI", "ннк": "NPHI", "nphi": "NPHI", "ггк": "RHOB",
            "ггм": "RHOB", "rhob": "RHOB", "ак": "DT", "dt": "DT", "мпз": "MNOR", "мгз": "MINV", "кс": "RD",
            "бк": "RD", "ик": "RD", "rt": "RD", "бкз": "RD", "бэз": "RD", "мбк": "RS"}


def _sid(name: str) -> str | None:
    k = name.lower().replace("ρ", "").strip()
    for key, v in NAME_MAP.items():
        if k.startswith(key):
            return v
    return None


CURVE = {"type": "object", "required": ["name", "points"],
         "properties": {"name": {"type": "string", "description": "как в книге: ПС, ГК, КС (А2М0,5N), НГК…"},
                        "unit": {"type": "string", "default": ""},
                        "points": {"type": "array", "minItems": 2,
                                   "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                                   "description": "[[глубина, значение], …] по глубине"},
                        "scale": {"enum": ["linear", "log"], "default": "linear"},
                        "range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                                  "description": "шкала трека слева→справа (может убывать)"},
                        "color": {"type": "string"}, "dashed": {"type": "boolean", "default": False}}}


@register
class LogPlot(Template):
    name = "log_plot"
    title_ru = "Каротажная диаграмма по данным (оцифровка рисунка книги или LAS)"
    description = (
        "Планшет ГИС, построенный по ТОЧКАМ кривых (оцифровка рисунка книги или реальные данные): треки с "
        "кривыми (глубина вниз, шкалы и единицы в шапке), необязательная литологическая колонка по "
        "интерпретации и выделенные интервалы с подписями (коллектор, ВНК, плотный прослой…). Для перерисовки "
        "рисунков-диаграмм, на которых держатся примеры и задачи главы, и для «решения на данных»."
    )
    use_for = ["И", "Р", "Пр", "Н", "data_practice", "перерисовка рисунка", "диаграммы ГИС"]
    frame_class = "A"
    provenance = "реальные данные"
    animatable = True
    animation = "t∈[0,1]: кривые прорисовываются снизу вверх (как при записи на подъёме)"
    default_size = (1000, 1200)
    params_schema = {
        "type": "object",
        "required": ["tracks"],
        "properties": {
            **common_props(),
            "tracks": {"type": "array", "minItems": 1, "maxItems": 6,
                       "items": {"type": "object", "required": ["curves"],
                                 "properties": {"title": {"type": "string"},
                                                "curves": {"type": "array", "minItems": 1, "maxItems": 4, "items": CURVE}}}},
            "depth_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "lith_column": {"type": "array", "default": [],
                            "items": {"type": "object", "required": ["top", "base", "lith"],
                                      "properties": {"top": {"type": "number"}, "base": {"type": "number"},
                                                     "lith": {"enum": LITH_KEYS}, "fluid": {"enum": ["water", "oil", "gas", None]},
                                                     "label": {"type": "string"}}}},
            "intervals": {"type": "array", "default": [],
                          "items": {"type": "object", "required": ["top", "base", "text"],
                                    "properties": {"top": {"type": "number"}, "base": {"type": "number"},
                                                   "text": {"type": "string"},
                                                   "kind": {"enum": ["observation", "inference", "assumption"], "default": "inference"}}}},
        },
    }
    example = {
        "title": "ПС и сопротивление по участку разреза (пример)",
        "tracks": [
            {"title": "ПС", "curves": [{"name": "ПС", "unit": "мВ", "range": [-60, 10],
                                        "points": [[1200, 0], [1204, 0], [1205, -40], [1210, -42], [1211, 0], [1220, 0]]}]},
            {"title": "КС", "curves": [{"name": "КС", "unit": "Ом·м", "scale": "log", "range": [1, 100],
                                        "points": [[1200, 3], [1204, 3], [1205, 25], [1208, 25], [1209, 4], [1211, 3], [1220, 3]]}]},
        ],
        "lith_column": [{"top": 1200, "base": 1204.5, "lith": "shale"}, {"top": 1204.5, "base": 1210.5, "lith": "sand"},
                        {"top": 1210.5, "base": 1220, "lith": "shale"}],
        "intervals": [{"top": 1204.5, "base": 1210.5, "text": "коллектор", "kind": "inference"}],
    }

    def check(self, params):
        iss = []
        for tr in params["tracks"]:
            for c in tr["curves"]:
                d = [p[0] for p in c["points"]]
                if any(b < a for a, b in zip(d, d[1:])):
                    iss.append(Issue("warning", "depth_order", f"{c['name']}: точки не по возрастанию глубины"))
                if c.get("scale") == "log" and (min(p[1] for p in c["points"]) <= 0 or
                                               (c.get("range") and min(c["range"]) <= 0)):
                    iss.append(Issue("error", "log_scale", f"{c['name']}: неположительные значения на логарифмической шкале"))
        L = sorted(params.get("lith_column", []), key=lambda l: l["top"])
        for a, b in zip(L, L[1:]):
            if b["top"] < a["base"] - 1e-6:
                iss.append(Issue("error", "layer_overlap", f"литоколонка: перекрытие на {b['top']} м"))
        for a in L:
            if a.get("fluid") in ("oil", "gas") and a["lith"] == "shale":
                iss.append(Issue("error", "fluid_in_nonreservoir", "нефть/газ в глине"))
        return iss

    def describe(self, params):
        names = [c["name"] for tr in params["tracks"] for c in tr["curves"]]
        s = "Каротажная диаграмма: " + ", ".join(names)
        if params.get("intervals"):
            s += "; выделены интервалы: " + ", ".join(f"{i['text']} {i['top']:g}–{i['base']:g} м" for i in params["intervals"])
        return s + ". Глубина растёт вниз."

    def _drange(self, p):
        if p.get("depth_range"):
            return tuple(p["depth_range"])
        ds = [pt[0] for tr in p["tracks"] for c in tr["curves"] for pt in c["points"]]
        ds += [x for l in p.get("lith_column", []) for x in (l["top"], l["base"])]
        return min(ds), max(ds)

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        top, base = self._drange(p)
        x0, y0, w, h = rect
        has_lith = bool(p.get("lith_column"))
        widths = [0.35] + ([0.5] if has_lith else []) + [1.0] * len(p["tracks"])
        tot = sum(widths)
        nmax = max(len(tr["curves"]) for tr in p["tracks"])
        block = 2.3 * ctx.base_px
        head_px = nmax * block + 0.8 * ctx.base_px
        head_h = head_px / ctx.fig_px[1]
        body_h = h - head_h
        xs = [x0]
        for wd in widths[:-1]:
            xs.append(xs[-1] + w * wd / tot)
        gap = 0.006
        axes = []
        for i, wd in enumerate(widths):
            ax = fig.add_axes([xs[i] + gap / 2, y0, w * wd / tot - gap, body_h])
            ax.set_ylim(base, top)
            ax.set_xlim(0, 1)
            ax.set_xticks([])
            if i > 0:
                ax.set_yticks([])
            axes.append(ax)
        span = base - top
        step = next(s for s in (0.5, 1, 2, 5, 10, 20, 50, 100, 200) if span / s <= 12)
        ticks = np.arange(math.ceil(top / step) * step, base + 1e-6, step)
        axes[0].set_yticks([])
        for v in ticks:
            axes[0].text(0.92, v, f"{v:g}", ha="right", va="center", fontsize=ctx.pt(0.78))
        hax = fig.add_axes([x0, y0 + body_h, w, head_h])
        hax.set_axis_off()
        hax.set_xlim(x0, x0 + w)
        hax.set_ylim(0, head_px)
        hax.text(xs[0] + w * widths[0] / tot / 2, 0.2 * ctx.base_px, "м", ha="center", va="bottom", fontsize=ctx.pt(0.8))
        k = 1
        if has_lith:
            lax = axes[1]
            for l in p["lith_column"]:
                lt = lith(sg, l["lith"])
                lax.add_patch(Rectangle((0, l["top"]), 1, l["base"] - l["top"], fc=lt["color"], hatch=lt.get("hatch") or None,
                                        ec="#555555", lw=0.5))
                if l.get("fluid"):
                    lax.add_patch(Rectangle((0.85, l["top"]), 0.15, l["base"] - l["top"],
                                            fc=sg["fluids"].get(l["fluid"], {}).get("color", "#999"), ec="none"))
            hax.text(xs[1] + w * widths[1] / tot / 2, 0.2 * ctx.base_px, "порода\n(интерпр.)", ha="center", va="bottom",
                     fontsize=ctx.pt(0.7))
            k = 2
        frac = 1.0 if t is None else float(t)
        dcut = base - frac * (base - top)
        pal = sg["palette"]["series"]
        for ti, tr in enumerate(p["tracks"]):
            ax = axes[k + ti]
            ax.grid(axis="y", color=sg["palette"]["grid"], lw=0.5)
            ax.set_yticks(ticks)
            ax.tick_params(axis="y", left=False, labelleft=False)
            hx0 = xs[k + ti] + gap / 2
            hw = w * widths[k + ti] / tot - gap
            nch = max(6, int(hw * ctx.fig_px[0] / (ctx.base_px * 0.78 * 0.6)))
            for ci, c in enumerate(tr["curves"]):
                sid = _sid(c["name"])
                cs = sg["curves"].get(sid, {}) if sid else {}
                col = c.get("color") or cs.get("color") or pal[(ti + ci) % len(pal)]
                pts = np.array(c["points"], dtype=float)
                pts = pts[np.argsort(pts[:, 0], kind="stable")]
                rng = c.get("range") or [float(pts[:, 1].min()), float(pts[:, 1].max())]
                a, b = rng
                if c.get("scale") == "log":
                    v = (np.log10(pts[:, 1]) - math.log10(a)) / (math.log10(b) - math.log10(a))
                else:
                    v = (pts[:, 1] - a) / ((b - a) or 1)
                m = pts[:, 0] >= dcut
                ax.plot(np.where(m, np.clip(v, -0.02, 1.02), np.nan), pts[:, 0], color=col, lw=1.6,
                        ls="--" if c.get("dashed") else "-")
                yy = head_px - ci * block - 0.1 * ctx.base_px
                nm = "\n".join(textwrap.wrap(c["name"], nch)[:2])
                hax.text(hx0 + hw / 2, yy, nm, ha="center", va="top", fontsize=ctx.pt(0.78), color=col, fontweight="bold",
                         linespacing=1.0)
                ly = yy - 1.45 * ctx.base_px
                hax.plot([hx0, hx0 + hw], [ly, ly], color=col, lw=1.6, ls="--" if c.get("dashed") else "-")
                hax.text(hx0, ly - 0.05 * ctx.base_px, f"{a:g}", ha="left", va="top", fontsize=ctx.pt(0.64), color=col)
                hax.text(hx0 + hw, ly - 0.05 * ctx.base_px, f"{b:g}", ha="right", va="top", fontsize=ctx.pt(0.64), color=col)
                if c.get("unit"):
                    hax.text(hx0 + hw / 2, ly - 0.05 * ctx.base_px, c["unit"], ha="center", va="top",
                             fontsize=ctx.pt(0.64), color=col)
        for it in p.get("intervals", []):
            col = sg["process_chain"].get(it.get("kind", "inference"), {}).get("color", "#AD1457")
            for ax in axes[1:]:
                if it["base"] > it["top"]:
                    ax.axhspan(it["top"], it["base"], fc=col, alpha=0.08)
                else:
                    ax.axhline(it["top"], color=col, lw=1.5, ls="-.")
            axes[-1].text(0.97, (it["top"] + it["base"]) / 2, it["text"], ha="right", va="center", fontsize=ctx.pt(0.75),
                          color=col, fontweight="bold", bbox=dict(fc="white", ec=col, lw=0.8, alpha=0.9, pad=1.5))
        legend = []
        seen = set()
        for l in p.get("lith_column", []):
            if l["lith"] not in seen:
                seen.add(l["lith"])
                lt = lith(sg, l["lith"])
                legend.append({"kind": "patch", "label": lt["ru"], "color": lt["color"], "hatch": lt.get("hatch")})
        for fl in ("gas", "oil", "water"):
            if any(l.get("fluid") == fl for l in p.get("lith_column", [])):
                legend.append({"kind": "patch", "label": sg["fluids"][fl]["ru"], "color": sg["fluids"][fl]["color"]})
        return {"exaggerations": [], "legend": legend, "notes": ["глубина растёт вниз"], "axes": axes}
