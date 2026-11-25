"""well_column: well construction + pressure vs depth from one hydrostatic model (drilling domain).

State model: mud column (density), casing strings, optional gas kick bubble that migrates up.
Closed well: bubble keeps its pressure (volume ~const) -> wellhead and bottom pressures rise.
Open well: bubble pressure = hydrostatic above it -> it expands (Boyle), most near the surface.
The bubble position drives both the picture and the pressure-depth curve.
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import Ellipse, Rectangle

from .. import models
from ..base import DrawCtx, Issue, Template, common_props, register


@register
class WellColumn(Template):
    name = "well_column"
    title_ru = "Скважина: конструкция, столб раствора и давление по глубине (в т.ч. газ в стволе)"
    description = (
        "Схема ствола скважины (обсадные колонны до башмаков, открытый ствол, бурильная колонна, раствор) "
        "рядом с графиком давления по глубине из той же модели: гидростатика ρgh, давление при циркуляции "
        "(ЭЦП), пластовое давление и давление гидроразрыва (если заданы), всплытие газовой пачки в закрытой "
        "(давление растёт по всему стволу) или открытой скважине (газ расширяется у устья). "
        "Для глав о бурении: гидростатика, ГНВП, глушение, конструкция скважины."
    )
    use_for = ["Ф", "П", "М", "бурение", "гидростатика", "газ в стволе", "конструкция скважины"]
    frame_class = "B"
    provenance = "симуляция"
    animatable = True
    animation = "t∈[0,1]: газовая пачка всплывает от забоя к устью; давления пересчитываются синхронно"
    default_size = (1200, 900)
    params_schema = {
        "type": "object",
        "properties": {
            **common_props(),
            "depth_m": {"type": "number", "exclusiveMinimum": 0, "default": 3000},
            "casings": {"type": "array", "default": [],
                        "items": {"type": "object", "required": ["shoe_m"],
                                  "properties": {"name": {"type": "string"}, "shoe_m": {"type": "number"},
                                                 "od_mm": {"type": "number"}}}},
            "hole_mm": {"type": "number", "default": 216},
            "mud_density_g_cc": {"type": "number", "default": 1.2},
            "ecd_g_cc": {"type": ["number", "null"], "default": None, "description": "эквивалентная циркуляционная плотность"},
            "pore_gradient_g_cc": {"type": ["number", "null"], "default": None, "description": "пластовое давление как эквивалентная плотность"},
            "frac_gradient_g_cc": {"type": ["number", "null"], "default": None, "description": "давление гидроразрыва как эквивалентная плотность"},
            "drill_string": {"type": "boolean", "default": True},
            "kick": {"type": ["object", "null"], "default": None,
                     "properties": {"mode": {"enum": ["closed", "open"]}, "volume_m3": {"type": "number", "default": 1.0},
                                    "start_depth_m": {"type": "number"}}},
            "bubble_depth_m": {"type": ["number", "null"], "default": None, "description": "статичное положение пачки"},
        },
    }
    example = {
        "title": "Газовая пачка в закрытой скважине: давление растёт по всему стволу",
        "depth_m": 3000, "casings": [{"name": "кондуктор", "shoe_m": 500, "od_mm": 324},
                                      {"name": "промежуточная колонна", "shoe_m": 1800, "od_mm": 245}],
        "mud_density_g_cc": 1.2, "frac_gradient_g_cc": 1.75, "kick": {"mode": "closed", "volume_m3": 1.5},
    }

    def check(self, params):
        iss = []
        D = params["depth_m"]
        if D > 12000:
            iss.append(Issue("error", "depth", "глубина неправдоподобна"))
        if not (0.8 <= params["mud_density_g_cc"] <= 2.5):
            iss.append(Issue("error", "mud_density", "плотность раствора вне 0,8–2,5 г/см³"))
        shoes = [c["shoe_m"] for c in params["casings"]]
        if any(s > D for s in shoes):
            iss.append(Issue("error", "shoe_depth", "башмак колонны глубже забоя"))
        if shoes != sorted(shoes):
            iss.append(Issue("warning", "casing_order", "колонны перечислены не по глубине"))
        ods = [c.get("od_mm") for c in params["casings"] if c.get("od_mm")]
        if ods and ods != sorted(ods, reverse=True):
            iss.append(Issue("error", "casing_od", "более глубокая колонна должна быть уже предыдущей"))
        if params.get("ecd_g_cc") is not None and params["ecd_g_cc"] < params["mud_density_g_cc"]:
            iss.append(Issue("error", "ecd", "при циркуляции давление на забой выше статического: ЭЦП ≥ плотности раствора"))
        if params.get("frac_gradient_g_cc") and params.get("pore_gradient_g_cc") and \
                params["frac_gradient_g_cc"] <= params["pore_gradient_g_cc"]:
            iss.append(Issue("error", "window", "градиент гидроразрыва должен быть выше пластового"))
        return iss

    def describe(self, params):
        s = (f"Скважина глубиной {params['depth_m']:g} м, раствор {params['mud_density_g_cc']:g} г/см³; "
             "справа график давления по глубине (глубина вниз)")
        k = params.get("kick")
        if k:
            s += ("; газовая пачка всплывает в закрытой скважине — давление растёт по всему стволу" if k["mode"] == "closed"
                  else "; газовая пачка всплывает в открытой скважине и расширяется у устья")
        return s + "."

    def state(self, params, t=None):
        D = params["depth_m"]
        rho = params["mud_density_g_cc"] * 1000
        z = np.linspace(0, D, 300)
        p_static = models.hydrostatic(z, rho)
        st = {"z": z, "p_static": p_static, "p": p_static.copy(), "bubble": None}
        k = params.get("kick")
        if k:
            z0 = k.get("start_depth_m") or D
            zb = params.get("bubble_depth_m")
            if t is not None:
                zb = z0 - t * (z0 - 0.04 * D)
            if zb is None:
                zb = z0
            pb0 = float(models.hydrostatic(z0, rho))
            g = models.gas_kick_migration(zb, well_depth=D, rho_mud=rho, p_bottom_initial=pb0,
                                          v_bubble0=k.get("volume_m3", 1.0), shut_in=k["mode"] == "closed")
            if k["mode"] == "closed":
                p = np.where(z <= zb, g["p_wellhead"] + rho * models.G * z, g["p_bubble"] + rho * models.G * (z - zb))
            else:
                p = 0.101e6 + rho * models.G * z
            st.update(p=p, bubble={"z": zb, **g})
        return st

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        st = self.state(p, t)
        D = p["depth_m"]
        x0, y0, w, h = rect
        wax = fig.add_axes([x0, y0, w * 0.36, h])
        pax = fig.add_axes([x0 + w * 0.47, y0, w * 0.53, h])
        for a in (wax, pax):
            a.set_ylim(D * 1.02, -0.03 * D)
        wax.set_xlim(-1, 1)
        wax.set_xticks([])
        wax.set_ylabel("глубина, м")
        mudc = sg["fluids"].get("mud", {}).get("color", "#8D6E63")
        hole = p["hole_mm"]
        maxd = max([c.get("od_mm") or hole * 1.5 for c in p["casings"]] + [hole])
        half = lambda d: 0.8 * d / maxd  # noqa: E731
        wax.add_patch(Rectangle((-1, 0), 2, D * 1.02, fc="#EFE6DA", ec="none", zorder=0))
        wax.add_patch(Rectangle((-half(hole), 0), 2 * half(hole), D, fc=mudc, alpha=0.35, ec="none", zorder=1))
        steel = sg["fluids"].get("steel", {}).get("color", "#455A64")
        for i, c in enumerate(sorted(p["casings"], key=lambda c: c["shoe_m"])):
            od = c.get("od_mm") or hole * (1.5 - 0.15 * i)
            hw = half(od)
            for sgn in (-1, 1):
                wax.plot([sgn * hw, sgn * hw], [0, c["shoe_m"]], color=steel, lw=2.6, zorder=3)
                wax.plot([sgn * hw, sgn * (hw + 0.06)], [c["shoe_m"], c["shoe_m"]], color=steel, lw=2.6, zorder=3)
            if c.get("name"):
                wax.text(hw + 0.08, c["shoe_m"], c["name"] + f"\n{c['shoe_m']:g} м", fontsize=ctx.pt(0.65),
                         va="center", ha="left", zorder=6)
        if p["drill_string"]:
            wax.add_patch(Rectangle((-0.06, 0), 0.12, D * 0.985, fc="#616161", ec="#212121", lw=0.6, zorder=4))
            wax.add_patch(Rectangle((-0.12, D * 0.97), 0.24, D * 0.03, fc="#FFC107", ec="#212121", lw=0.6, zorder=4))
        b = st["bubble"]
        fx = (2 * half(hole) / 2 * w * 0.36 * ctx.fig_px[0] / (hole / 1000)) / (h * ctx.fig_px[1] / (D * 1.05))
        exag = [{"what": "диаметр ствола по горизонтали", "factor": float(f"{fx:.2g}")}]
        if b:
            v = b["volume"]
            v0 = p["kick"].get("volume_m3", 1.0)
            ln = 0.035 * D * (v / v0)
            wax.add_patch(Ellipse((0, b["z"]), 2 * half(hole) * 0.9, ln, fc="#FFFFFF", ec=sg["fluids"]["gas"]["color"],
                                  lw=2, zorder=5, alpha=0.95))
            wax.text(0, b["z"], "газ", ha="center", va="center", fontsize=ctx.pt(0.7), color=sg["fluids"]["gas"]["color"],
                     fontweight="bold", zorder=6)
            exag.append({"what": "газовая пачка", "factor": "условно"})
        # pressure panel
        z = st["z"]
        pax.plot(st["p_static"] / 1e6, z, color="#616161", lw=1.4, ls="--", label="гидростатика раствора ρgh")
        if p.get("ecd_g_cc"):
            pax.plot(models.hydrostatic(z, p["ecd_g_cc"] * 1000) / 1e6, z, color="#6A1B9A", lw=1.4, ls="-.",
                     label="при циркуляции (ЭЦП)")
        if p.get("pore_gradient_g_cc"):
            pax.plot(models.hydrostatic(z, p["pore_gradient_g_cc"] * 1000) / 1e6, z, color=sg["fluids"]["water"]["color"],
                     lw=1.4, label="пластовое давление")
        if p.get("frac_gradient_g_cc"):
            pax.plot(models.hydrostatic(z, p["frac_gradient_g_cc"] * 1000) / 1e6, z, color="#C62828", lw=1.4,
                     label="давление гидроразрыва")
        if b:
            pax.plot(st["p"] / 1e6, z, color=sg["palette"]["accent"], lw=2.6, label="давление в стволе сейчас")
            pax.axhline(b["z"], color=sg["fluids"]["gas"]["color"], lw=1.0, ls=":")
            pax.text(st["p"][0] / 1e6, 0, f" на устье {b['p_wellhead'] / 1e6:.1f} МПа", fontsize=ctx.pt(0.78),
                     va="bottom", ha="left", color=sg["palette"]["accent"], fontweight="bold")
            pax.text(st["p"][-1] / 1e6, D, f" на забое {b['p_bottom'] / 1e6:.1f} МПа ", fontsize=ctx.pt(0.78),
                     va="bottom", ha="right", color=sg["palette"]["accent"], fontweight="bold")
        pax.set_xlabel("давление, МПа")
        pax.set_xlim(left=0)
        pax.grid(color=sg["palette"]["grid"], lw=0.5)
        pax.legend(loc="lower left", fontsize=ctx.pt(0.68))
        pax.tick_params(axis="y", labelleft=False)
        return {"exaggerations": exag, "legend": [], "notes": ["глубина растёт вниз"], "axes": [wax, pax]}
