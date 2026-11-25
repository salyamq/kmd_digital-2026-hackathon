"""plan_map: map view (structure contours, contact outline, wells, section line).

State model: a depth surface z(x, y) of the reservoir top, either parametric (dome / anticline /
monocline) or interpolated from data points. The hydrocarbon area is where z < OWC (and gas where
z < GOC), i.e. the same horizontal contacts as on the section template.
"""
from __future__ import annotations

import math

import numpy as np

from ..base import DrawCtx, Issue, Template, common_props, register
from ..style import fluid_color


@register
class PlanMap(Template):
    name = "plan_map"
    title_ru = "Карта (вид сверху): структурные изолинии кровли, контур залежи, скважины"
    description = (
        "Вид сверху: изогипсы кровли пласта (купол, антиклиналь, моноклиналь или по точкам скважин), "
        "внешний контур нефтеносности по ВНК и газоносности по ГНК (контакт горизонтален, поэтому контур = "
        "изогипса), скважины с результатом, линия разреза А–А′, масштабная линейка и север. Для тем: "
        "строение залежи, размещение скважин, связь карты и разреза."
    )
    use_for = ["П", "М", "Р", "карта", "залежь", "размещение скважин"]
    frame_class = "B"
    provenance = "схема"
    animatable = True
    animation = "t∈[0,1]: скважины появляются по порядку"
    default_size = (1000, 900)
    params_schema = {
        "type": "object",
        "properties": {
            **common_props(),
            "width_m": {"type": "number", "exclusiveMinimum": 0, "default": 6000},
            "height_m": {"type": "number", "exclusiveMinimum": 0, "default": 5000},
            "structure": {"type": "object", "default": {"type": "dome"},
                          "properties": {"type": {"enum": ["dome", "anticline", "monocline", "points"]},
                                         "center": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                                                    "description": "доли ширины/высоты"},
                                         "crest_depth_m": {"type": "number"}, "amplitude_m": {"type": "number"},
                                         "radius_frac": {"type": "number"}, "elongation": {"type": "number"},
                                         "azimuth_deg": {"type": "number"}, "dip_deg": {"type": "number"}}},
            "points": {"type": "array", "default": [],
                       "items": {"type": "object", "required": ["x", "y", "z"],
                                 "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}}},
            "contour_interval_m": {"type": ["number", "null"], "default": None},
            "owc_m": {"type": ["number", "null"], "default": None},
            "goc_m": {"type": ["number", "null"], "default": None},
            "wells": {"type": "array", "default": [],
                      "items": {"type": "object", "required": ["x", "y"],
                                "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "name": {"type": "string"},
                                               "result": {"enum": ["oil", "gas", "water", "dry", None]}}}},
            "section_line": {"type": ["array", "null"], "default": None,
                             "items": {"type": "array", "items": {"type": "number"}}},
        },
    }
    example = {
        "title": "Купол: изогипсы кровли и контур залежи по ВНК",
        "structure": {"type": "dome", "center": [0.5, 0.5], "crest_depth_m": 1500, "amplitude_m": 80,
                      "radius_frac": 0.35, "elongation": 1.6, "azimuth_deg": 30},
        "owc_m": 1545, "goc_m": 1515,
        "wells": [{"x": 3000, "y": 2500, "name": "1", "result": "gas"}, {"x": 4300, "y": 3300, "name": "2", "result": "oil"},
                  {"x": 5200, "y": 1200, "name": "3", "result": "water"}],
        "section_line": [[600, 1000], [5400, 4000]],
    }

    def surface(self, p, nx=200, ny=180):
        W, H = p["width_m"], p["height_m"]
        X, Y = np.meshgrid(np.linspace(0, W, nx), np.linspace(0, H, ny))
        s = p.get("structure") or {"type": "dome"}
        typ = s.get("type", "dome")
        if typ == "points" or (p.get("points") and typ == "points"):
            from scipy.interpolate import griddata
            pts = np.array([[q["x"], q["y"]] for q in p["points"]])
            zz = np.array([q["z"] for q in p["points"]])
            Z = griddata(pts, zz, (X, Y), method="cubic" if len(pts) >= 6 else "linear")
            Zn = griddata(pts, zz, (X, Y), method="nearest")
            Z = np.where(np.isnan(Z), Zn, Z)
            return X, Y, Z
        cx, cy = s.get("center", [0.5, 0.5])
        cx, cy = cx * W, cy * H
        crest = s.get("crest_depth_m", 1500)
        if typ == "monocline":
            az = math.radians(s.get("azimuth_deg", 90))
            dip = math.tan(math.radians(s.get("dip_deg", 3)))
            d = (X - cx) * math.sin(az) + (Y - cy) * math.cos(az)
            return X, Y, crest + dip * d
        A = s.get("amplitude_m", 80)
        R = s.get("radius_frac", 0.35) * min(W, H)
        el = s.get("elongation", 1.0 if typ == "dome" else 2.5)
        az = math.radians(s.get("azimuth_deg", 0))
        u = (X - cx) * math.cos(az) - (Y - cy) * math.sin(az)
        v = (X - cx) * math.sin(az) + (Y - cy) * math.cos(az)
        r2 = (v / (R * el)) ** 2 + (u / R) ** 2
        return X, Y, crest + A * (1 - np.exp(-r2))

    def check(self, params):
        iss = []
        _, _, Z = self.surface(params, 60, 50)
        if params.get("goc_m") is not None and params.get("owc_m") is not None and params["goc_m"] >= params["owc_m"]:
            iss.append(Issue("error", "fluid_order", "ГНК должен быть выше ВНК"))
        for k in ("owc_m", "goc_m"):
            v = params.get(k)
            if v is not None and v <= float(np.nanmin(Z)):
                iss.append(Issue("error", "contact_above_crest", f"{k}: контакт выше свода — залежи нет"))
        if params.get("owc_m") is not None:
            inside = Z < params["owc_m"]
            if inside[0].any() or inside[-1].any() or inside[:, 0].any() or inside[:, -1].any():
                iss.append(Issue("warning", "open_contour", "контур залежи выходит за край карты (ловушка не замкнута на карте)"))
        return iss

    def describe(self, params):
        s = "Карта кровли пласта (изогипсы, глубина в метрах)"
        if params.get("owc_m") is not None:
            s += f"; контур залежи по ВНК {params['owc_m']:g} м"
        if params.get("wells"):
            s += "; скважины: " + ", ".join(w.get("name", "?") for w in params["wells"])
        return s + "."

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        X, Y, Z = self.surface(p)
        ax = fig.add_axes(rect)
        ax.set_aspect("equal")
        zr = float(np.nanmax(Z) - np.nanmin(Z))
        ci = p.get("contour_interval_m") or next(c for c in (1, 2, 5, 10, 20, 25, 50, 100, 200) if zr / c <= 12)
        lv = np.arange(math.floor(np.nanmin(Z) / ci) * ci, np.nanmax(Z) + ci, ci)
        ax.contourf(X, Y, Z, levels=[-1e9, 1e9], colors=["#F5F5F5"])
        if p.get("owc_m") is not None:
            ax.contourf(X, Y, Z, levels=[-1e9, p["owc_m"]], colors=[fluid_color(sg, "oil")], alpha=0.35)
            c1 = ax.contour(X, Y, Z, levels=[p["owc_m"]], colors=[fluid_color(sg, "water")], linewidths=2.4)
            ax.clabel(c1, fmt=lambda v: f"ВНК {v:g}", fontsize=ctx.pt(0.75))
        if p.get("goc_m") is not None:
            ax.contourf(X, Y, Z, levels=[-1e9, p["goc_m"]], colors=[fluid_color(sg, "gas")], alpha=0.35)
            c2 = ax.contour(X, Y, Z, levels=[p["goc_m"]], colors=[fluid_color(sg, "gas")], linewidths=2.0)
            ax.clabel(c2, fmt=lambda v: f"ГНК {v:g}", fontsize=ctx.pt(0.75))
        cs = ax.contour(X, Y, Z, levels=lv, colors="#424242", linewidths=0.8)
        ax.clabel(cs, fmt=lambda v: f"{v:g}", fontsize=ctx.pt(0.65))
        wells = p.get("wells", [])
        nvis = len(wells) if t is None else math.ceil(t * len(wells))
        rescol = {"oil": fluid_color(sg, "oil"), "gas": fluid_color(sg, "gas"), "water": fluid_color(sg, "water"),
                  "dry": "#FFFFFF", None: "#FFFFFF"}
        for wl in wells[:nvis]:
            ax.plot([wl["x"]], [wl["y"]], "o", ms=ctx.base_px * 0.75, mfc=rescol.get(wl.get("result")), mec="#111111",
                    mew=1.5, zorder=6)
            if wl.get("name"):
                ax.annotate(wl["name"], (wl["x"], wl["y"]), xytext=(6, 6), textcoords="offset points",
                            fontsize=ctx.pt(0.85), fontweight="bold", zorder=7)
        sl = p.get("section_line")
        if sl and len(sl) >= 2:
            (xa, ya), (xb, yb) = sl[0], sl[-1]
            ax.plot([xa, xb], [ya, yb], color="#AD1457", lw=1.8, ls="--", zorder=5)
            ax.text(xa, ya, "А ", ha="right", va="center", color="#AD1457", fontsize=ctx.pt(0.9), fontweight="bold")
            ax.text(xb, yb, " А′", ha="left", va="center", color="#AD1457", fontsize=ctx.pt(0.9), fontweight="bold")
        W, H = p["width_m"], p["height_m"]
        sb = next(s for s in (100, 200, 500, 1000, 2000, 5000, 10000) if s >= W / 6)
        ax.plot([W * 0.05, W * 0.05 + sb], [H * 0.05, H * 0.05], color="#111111", lw=3)
        ax.text(W * 0.05 + sb / 2, H * 0.065, f"{sb:g} м" if sb < 1000 else f"{sb / 1000:g} км", ha="center",
                va="bottom", fontsize=ctx.pt(0.8))
        ax.annotate("С", xy=(W * 0.95, H * 0.95), xytext=(W * 0.95, H * 0.83), ha="center", va="top",
                    fontsize=ctx.pt(0.9), fontweight="bold", arrowprops=dict(arrowstyle="-|>", color="#111111", lw=1.5))
        ax.set_xlim(0, W)
        ax.set_ylim(0, H)
        ax.set_xticks([])
        ax.set_yticks([])
        legend = [{"kind": "line", "label": f"изогипсы кровли (глубина, м), через {ci:g} м", "color": "#424242"}]
        if p.get("goc_m") is not None:
            legend.append({"kind": "patch", "label": "газовая часть", "color": fluid_color(sg, "gas")})
        if p.get("owc_m") is not None:
            legend.append({"kind": "patch", "label": "нефтяная часть", "color": fluid_color(sg, "oil")})
        if wells:
            legend.append({"kind": "dot", "label": "скважина (цвет — результат)", "color": "#9E9E9E"})
        return {"exaggerations": [], "legend": legend, "notes": [], "axes": [ax]}
