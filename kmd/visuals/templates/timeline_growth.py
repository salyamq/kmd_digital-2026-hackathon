"""timeline_growth: geological history as a sequence of events computed on one surface model.

State model: a list of strata (bottom(x), top(x)) and the current depositional surface s(x).
Events: deposit (sheet / wedge / lens / mound), erode (cut to a level -> unconformity), sea_level,
subside (burial). Younger strata always lie on the current surface, so «молодые над старыми» holds by
construction; an unconformity appears only as an explicit erosion event.
"""
from __future__ import annotations

import math

import numpy as np

from ..base import DrawCtx, Issue, Template, common_props, register
from ..style import lith
from .log_track import LITH_KEYS


def _shape(xf, ev):
    c = ev.get("center_frac", 0.5)
    w = max(ev.get("width_frac", 1.0), 1e-3)
    shp = ev.get("shape", "sheet")
    if shp == "sheet":
        return np.ones_like(xf)
    if shp == "wedge":
        return xf if ev.get("thicken", "right") == "right" else 1 - xf
    u = (xf - c) / (w / 2)
    inside = np.abs(u) < 1
    if shp == "lens":
        return np.where(inside, np.sqrt(np.clip(1 - u ** 2, 0, 1)), 0.0)
    if shp == "mound":
        return np.where(inside, np.clip(np.cos(u * math.pi / 2), 0, 1) ** 0.6, 0.0)
    if shp == "prograde":
        # clinoform wedge: full thickness landward of the front, tapering to zero over w/2 basinward
        front = c
        return np.clip((front - xf) / (w / 2) + 1, 0, 1)
    return np.ones_like(xf)


@register
class TimelineGrowth(Template):
    name = "timeline_growth"
    title_ru = "Геологическая история: накопление, рост рифа, проградация, размыв, погружение"
    description = (
        "Разрез, который строится во времени по событиям: накопление слоя (пласт, клин, линза, постройка-риф, "
        "проградирующий клин дельты), колебания уровня моря, размыв (несогласие как событие: размыв → перерыв → "
        "новое накопление), погружение. Молодые слои всегда ложатся на текущую поверхность. Внизу — шкала времени "
        "с текущим событием. Для тем: рост рифа, проградация дельты, формирование ловушки и покрышки, «как "
        "пласт оказался на глубине»."
    )
    use_for = ["В", "П", "М", "геологическое время", "рост рифа", "несогласие"]
    frame_class = "B"
    provenance = "схема"
    animatable = True
    animation = "t∈[0,1]: события по порядку; текущее событие выполняется частично"
    default_size = (1200, 750)
    params_schema = {
        "type": "object",
        "required": ["events"],
        "properties": {
            **common_props(),
            "width_m": {"type": "number", "exclusiveMinimum": 0, "default": 3000},
            "base_lith": {"enum": LITH_KEYS, "default": "basement"},
            "base_thickness_m": {"type": "number", "exclusiveMinimum": 0, "default": 30},
            "sea_level_m": {"type": ["number", "null"], "default": None, "description": "уровень моря над исходной поверхностью, м"},
            "events": {"type": "array", "minItems": 1, "maxItems": 12,
                       "items": {"type": "object", "required": ["kind"],
                                 "properties": {
                                     "kind": {"enum": ["deposit", "erode", "sea_level", "subside"]},
                                     "label": {"type": "string"}, "time_label": {"type": "string"},
                                     "lith": {"enum": LITH_KEYS},
                                     "shape": {"enum": ["sheet", "wedge", "lens", "mound", "prograde", "fill"], "default": "sheet",
                                               "description": "fill — заполнить рельеф до отметки level_m (облекание/захоронение)"},
                                     "thickness_m": {"type": "number", "minimum": 0},
                                     "center_frac": {"type": "number"}, "width_frac": {"type": "number"},
                                     "thicken": {"enum": ["left", "right"]},
                                     "up_to_sea_level": {"type": "boolean", "default": False,
                                                         "description": "рост не выше уровня моря (риф)"},
                                     "level_m": {"type": "number", "description": "erode: срезать до отметки; sea_level: новый уровень"},
                                     "amount_m": {"type": "number", "description": "subside: на сколько погрузить"}}}},
        },
    }
    example = {
        "title": "Рост рифа и его захоронение",
        "width_m": 3000, "sea_level_m": 40, "base_lith": "limestone",
        "events": [
            {"kind": "deposit", "lith": "limestone", "shape": "mound", "thickness_m": 35, "center_frac": 0.5,
             "width_frac": 0.4, "up_to_sea_level": True, "label": "риф растёт к свету", "time_label": "этап 1"},
            {"kind": "sea_level", "level_m": 80, "label": "море углубляется", "time_label": "этап 2"},
            {"kind": "deposit", "lith": "limestone", "shape": "mound", "thickness_m": 35, "center_frac": 0.5,
             "width_frac": 0.3, "up_to_sea_level": True, "label": "риф догоняет уровень моря", "time_label": "этап 3"},
            {"kind": "deposit", "lith": "shale", "shape": "fill", "level_m": 78, "label": "глины перекрывают риф",
             "time_label": "этап 4"},
        ],
    }

    def check(self, params):
        iss = []
        for i, ev in enumerate(params["events"]):
            k = ev["kind"]
            if k == "deposit" and ev.get("shape") == "fill":
                if not ev.get("lith") or ev.get("level_m") is None:
                    iss.append(Issue("error", "deposit_params", f"событие {i + 1}: для заполнения нужны lith и level_m"))
            elif k == "deposit" and (not ev.get("lith") or not ev.get("thickness_m")):
                iss.append(Issue("error", "deposit_params", f"событие {i + 1}: для накопления нужны lith и thickness_m"))
            if k in ("erode", "sea_level") and ev.get("level_m") is None:
                iss.append(Issue("error", "level", f"событие {i + 1}: нужен level_m"))
            if k == "subside" and not ev.get("amount_m"):
                iss.append(Issue("error", "amount", f"событие {i + 1}: нужен amount_m"))
            if ev.get("up_to_sea_level") and params.get("sea_level_m") is None and not any(
                    e["kind"] == "sea_level" for e in params["events"][:i]):
                iss.append(Issue("error", "sea_level", "рост до уровня моря без заданного уровня моря"))
        if not any(i.level == "error" for i in iss):
            st = self.state(params, None)
            sea_hist = [params.get("sea_level_m")] + [e.get("level_m") for e in params["events"] if e["kind"] == "sea_level"]
            sea_max = max([v for v in sea_hist if v is not None], default=None)
            if sea_max is not None and any(e["kind"] == "subside" for e in params["events"]) is False:
                top_max = max(float(s_["top"].max()) for s_ in st["strata"][1:]) if len(st["strata"]) > 1 else 0
                if top_max > sea_max + 1e-6:
                    iss.append(Issue("warning", "above_sea", "осадки поднялись выше уровня моря — проверить (наземное накопление?)"))
        return iss

    def describe(self, params):
        return "Схема геологической истории по этапам: " + "; ".join(
            (e.get("time_label") + ": " if e.get("time_label") else "") + (e.get("label") or e["kind"])
            for e in params["events"]) + "."

    def state(self, params, t=None, nx=400):
        W = params["width_m"]
        xf = np.linspace(0, 1, nx)
        surf = np.zeros(nx)
        strata = [{"lith": params["base_lith"], "bot": -params["base_thickness_m"] * np.ones(nx), "top": surf.copy(),
                   "label": ""}]
        sea = params.get("sea_level_m")
        unconf = []
        evs = params["events"]
        N = len(evs)
        tt = 1.0 if t is None else float(t)
        cur = min(int(tt * N), N - 1) if tt < 1 else N - 1
        frac = 1.0 if tt >= 1 else tt * N - cur
        if t is None:
            cur, frac = N - 1, 1.0
        for i, ev in enumerate(evs[: cur + 1]):
            f = 1.0 if i < cur else frac
            k = ev["kind"]
            if k == "deposit" and ev.get("shape") == "fill":
                lvl = ev.get("level_m", float(surf.max()))
                tgt = np.maximum(surf, lvl)
                new_top = surf + (tgt - surf) * f
                strata.append({"lith": ev["lith"], "bot": surf.copy(), "top": new_top.copy(), "label": ev.get("label", "")})
                surf = np.maximum(surf, new_top)
            elif k == "deposit":
                th = ev["thickness_m"] * _shape(xf, ev) * f
                new_top = surf + th
                if ev.get("up_to_sea_level") and sea is not None:
                    new_top = np.where(th > 0, np.minimum(new_top, np.maximum(sea, surf)), new_top)
                strata.append({"lith": ev["lith"], "bot": surf.copy(), "top": new_top.copy(), "label": ev.get("label", "")})
                surf = np.maximum(surf, new_top)
            elif k == "sea_level":
                base = sea if sea is not None else float(surf.max())
                sea = base + f * (ev["level_m"] - base)
            elif k == "erode":
                lvl = float(surf.max()) + f * (ev["level_m"] - float(surf.max()))
                cut = surf > lvl
                for s in strata:
                    s["top"] = np.minimum(s["top"], lvl)
                    s["bot"] = np.minimum(s["bot"], lvl)
                surf = np.minimum(surf, lvl)
                if f >= 0.999 and cut.any():
                    unconf.append({"x": xf[cut] * W, "z": surf[cut].copy(), "label": ev.get("label", "размыв")})
            elif k == "subside":
                d = ev["amount_m"] * f
                for s in strata:
                    s["top"] = s["top"] - d
                    s["bot"] = s["bot"] - d
                for u in unconf:
                    u["z"] = u["z"] - d
                surf = surf - d
        return {"x": xf * W, "strata": strata, "surface": surf, "sea": sea, "unconf": unconf, "cur": cur, "frac": frac}

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        st = self.state(params, t)
        full = self.state(params, None)
        x0, y0, w, h = rect
        tl_h = 0.14 * h
        ax = fig.add_axes([x0, y0 + tl_h + 0.04 * h, w, h - tl_h - 0.04 * h])
        x = st["x"]
        zmin = min(float(s["bot"].min()) for s in full["strata"])
        zmax = max(float(full["surface"].max()), full["sea"] or -1e9, float(st["surface"].max()), st["sea"] or -1e9)
        zmin = min(zmin, min(float(s["bot"].min()) for s in st["strata"]))
        pad = 0.12 * (zmax - zmin)
        ax.set_xlim(0, params["width_m"])
        ax.set_ylim(zmin - 0.02 * (zmax - zmin), zmax + pad)
        if st["sea"] is not None:
            ax.fill_between(x, st["surface"], st["sea"], where=st["sea"] > st["surface"], color="#BBDEFB", lw=0,
                            zorder=0)
            ax.axhline(st["sea"], color="#1E66C9", lw=1.2, ls="-", zorder=1)
            ax.text(params["width_m"] * 0.99, st["sea"], "уровень моря", ha="right", va="bottom", color="#1E66C9",
                    fontsize=ctx.pt(0.75))
        for s in st["strata"]:
            lt = lith(sg, s["lith"])
            m = s["top"] > s["bot"] + 1e-6
            ax.fill_between(x, s["bot"], s["top"], where=m, color=lt["color"], hatch=lt.get("hatch") or None,
                            edgecolor="#555555", lw=0.3, zorder=2)
            ax.plot(x[m], s["top"][m], color="#333333", lw=0.6, zorder=3)
            if s["label"] and m.any():
                th = np.where(m, s["top"] - s["bot"], 0)
                big = np.where(th >= 0.8 * th.max())[0]
                j = int(big[len(big) // 2])
                if th[j] > 0.06 * (zmax - zmin):
                    ax.text(x[j], (s["top"][j] + s["bot"][j]) / 2, s["label"], ha="center", va="center",
                            fontsize=ctx.pt(0.75), zorder=6, bbox=dict(fc="white", ec="none", alpha=0.75, pad=1))
        for u in st["unconf"]:
            ax.plot(u["x"], u["z"], color="#C62828", lw=2.2, ls=(0, (6, 3)), zorder=5)
            ax.text(u["x"][len(u["x"]) // 2], u["z"][len(u["z"]) // 2], " несогласие (размыв)", color="#C62828",
                    fontsize=ctx.pt(0.75), va="bottom", zorder=6)
        ax.set_xlabel("расстояние, м")
        ax.set_ylabel("отметка, м")
        # timeline bar
        tax = fig.add_axes([x0, y0, w, tl_h])
        tax.set_axis_off()
        evs = params["events"]
        N = len(evs)
        tax.set_xlim(0, N)
        tax.set_ylim(0, 1)
        tax.annotate("", xy=(N, 0.62), xytext=(0, 0.62), arrowprops=dict(arrowstyle="-|>", color="#616161", lw=1.4))
        for i, ev in enumerate(evs):
            done = i < st["cur"] or (i == st["cur"] and st["frac"] >= 0.999)
            active = i == st["cur"]
            col = "#E65100" if active else ("#37474F" if done else "#BDBDBD")
            tax.plot([i + 0.5], [0.62], "o", color=col, ms=ctx.base_px * (0.8 if active else 0.55))
            txt = ev.get("time_label") or f"{i + 1}"
            tax.text(i + 0.5, 0.95, txt, ha="center", va="top", fontsize=ctx.pt(0.72), color=col)
            if ev.get("label"):
                tax.text(i + 0.5, 0.35, ev["label"], ha="center", va="top", fontsize=ctx.pt(0.62), color=col, wrap=True)
        tax.text(N, 0.62, " время", va="center", ha="left", fontsize=ctx.pt(0.72), color="#616161")
        Wpx = w * ctx.fig_px[0]
        Hpx = (h - tl_h) * ctx.fig_px[1]
        ve = (Hpx / (zmax + pad - zmin)) / (Wpx / params["width_m"])
        exag = [{"what": "вертикальный масштаб", "factor": round(ve)}] if ve > 1.3 else []
        legend = []
        for s in full["strata"]:
            lt = lith(sg, s["lith"])
            if lt["ru"] not in [i["label"] for i in legend]:
                legend.append({"kind": "patch", "label": lt["ru"], "color": lt["color"], "hatch": lt.get("hatch")})
        return {"exaggerations": exag, "legend": legend, "notes": [], "axes": [ax, tax]}
