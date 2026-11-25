"""radial_invasion: zones around the borehole in a permeable bed + resistivity profile R(r).

State model: borehole radius, mud cake, flushed zone r_xo, invasion front r_i(t) growing ~ sqrt(t),
resistivities Rm, Rmc, Rxo, Rt. The same radii drive the picture (top) and the profile (bottom);
tool depths of investigation are drawn as markers on the same r axis.
"""
from __future__ import annotations

import math

import numpy as np
from matplotlib.patches import Rectangle

from ..base import DrawCtx, Issue, Template, common_props, register
from ..style import fluid_color, lith


@register
class RadialInvasion(Template):
    name = "radial_invasion"
    title_ru = "Зона проникновения фильтрата вокруг скважины и профиль сопротивления"
    description = (
        "Горизонтальный срез пласта от оси скважины наружу: раствор, глинистая корка, промытая зона, зона "
        "проникновения, неизменённая часть пласта; ниже — радиальный профиль удельного сопротивления из тех же "
        "радиусов (повышающее проникновение ρзп > ρп для водоносного пласта при пресном растворе, понижающее — "
        "для продуктивного). Отметки глубинности зондов. Для тем: условия вскрытия, проникновение, почему "
        "зонды разной глубинности показывают разное."
    )
    use_for = ["Н", "И", "М", "проникновение", "глубинность", "условия вскрытия"]
    frame_class = "B"
    provenance = "схема"
    animatable = True
    animation = "t∈[0,1]: фронт проникновения продвигается от стенки (∝√t)"
    default_size = (1200, 800)
    params_schema = {
        "type": "object",
        "properties": {
            **common_props(),
            "lith": {"type": "string", "default": "sand"},
            "fluid": {"enum": ["water", "oil", "gas"], "default": "water"},
            "rw_m": {"type": "number", "default": 0.108},
            "mudcake_mm": {"type": "number", "default": 10},
            "rxo_m": {"type": "number", "default": 0.3, "description": "радиус промытой зоны"},
            "ri_m": {"type": "number", "default": 0.6, "description": "радиус зоны проникновения (D/2)"},
            "r_max_m": {"type": "number", "default": 1.6},
            "Rm": {"type": "number", "default": 0.6}, "Rmc": {"type": "number", "default": 0.9},
            "Rxo": {"type": "number", "default": 12.0}, "Rt": {"type": "number", "default": 2.0},
            "tools": {"type": "array", "default": [],
                      "items": {"type": "object", "required": ["name", "radius_m"],
                                "properties": {"name": {"type": "string"}, "radius_m": {"type": "number"}}}},
        },
    }
    example = {
        "title": "Повышающее проникновение: водоносный пласт, пресный раствор",
        "fluid": "water", "Rxo": 12.0, "Rt": 2.0,
        "tools": [{"name": "микрозонд", "radius_m": 0.15}, {"name": "малый зонд", "radius_m": 0.45},
                  {"name": "большой зонд", "radius_m": 1.3}],
    }

    def check(self, params):
        iss = []
        rc = params["rw_m"] - params["mudcake_mm"] / 1000
        if not (0.04 <= params["rw_m"] <= 0.35):
            iss.append(Issue("error", "rw", "радиус скважины неправдоподобен"))
        if not (rc < params["rw_m"] <= params["rxo_m"] <= params["ri_m"] <= params["r_max_m"]):
            iss.append(Issue("error", "radii_order", "радиусы должны идти: скважина ≤ промытая зона ≤ зона проникновения ≤ край"))
        if params["fluid"] == "water" and params["Rxo"] < params["Rt"]:
            iss.append(Issue("warning", "invasion_type", "водоносный пласт с понижающим проникновением — возможно при солёном растворе; назвать условие"))
        return iss

    def describe(self, params):
        kind = "повышающее" if params["Rxo"] > params["Rt"] else "понижающее"
        return (f"Срез от оси скважины: раствор, глинистая корка, промытая зона до {params['rxo_m']:g} м, зона проникновения "
                f"до {params['ri_m']:g} м, дальше неизменённый пласт. Профиль сопротивления: {kind} проникновение "
                f"(ρзп = {params['Rxo']:g}, ρп = {params['Rt']:g} Ом·м).")

    def state(self, params, t=None):
        rw = params["rw_m"]
        f = 1.0 if t is None else max(float(t), 0.0)
        g = math.sqrt(f)
        rxo = rw + (params["rxo_m"] - rw) * g
        ri = rw + (params["ri_m"] - rw) * g
        r = np.linspace(0, params["r_max_m"], 600)
        rc = rw - params["mudcake_mm"] / 1000 * min(1.0, 4 * f if t is not None else 1.0)
        R = np.where(r < rc, params["Rm"], params["Rmc"])
        R = np.where(r >= rw, params["Rt"], R)
        R = np.where((r >= rw) & (r < ri), params["Rxo"] + (params["Rt"] - params["Rxo"]) *
                     np.clip((r - rxo) / max(ri - rxo, 1e-6), 0, 1), R)
        return {"r": r, "R": R, "rxo": rxo, "ri": ri, "rc": rc}

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        st = self.state(p, t)
        x0, y0, w, h = rect
        top = fig.add_axes([x0, y0 + 0.55 * h, w, 0.42 * h])
        bot = fig.add_axes([x0, y0, w, 0.45 * h], sharex=top)
        R = p["r_max_m"]
        top.set_xlim(0, R)
        top.set_ylim(0, 1)
        top.set_yticks([])
        lt = lith(sg, p["lith"])
        top.add_patch(Rectangle((0, 0), R, 1, fc=lt["color"], hatch=lt.get("hatch") or None, ec="#555555", lw=0))
        fcol = fluid_color(sg, p["fluid"])
        top.add_patch(Rectangle((st["ri"], 0), R - st["ri"], 1, fc=fcol, alpha=0.35, lw=0))
        filt = sg["fluids"]["mud_filtrate"]["color"]
        top.add_patch(Rectangle((p["rw_m"], 0), st["ri"] - p["rw_m"], 1, fc=filt, alpha=0.55, lw=0))
        top.add_patch(Rectangle((p["rw_m"], 0), st["rxo"] - p["rw_m"], 1, fc=filt, alpha=0.35, lw=0))
        top.add_patch(Rectangle((0, 0), st["rc"], 1, fc=sg["fluids"]["mud"]["color"], alpha=0.6, lw=0))
        top.add_patch(Rectangle((st["rc"], 0), p["rw_m"] - st["rc"], 1, fc=sg["fluids"]["mud_cake"]["color"], lw=0))
        labels = [(st["rc"] / 2, "раствор"), ((st["rxo"] + p["rw_m"]) / 2, "промытая\nзона"),
                  ((st["rxo"] + st["ri"]) / 2, "зона\nпроникновения"), ((st["ri"] + R) / 2, "неизменённая часть пласта")]
        for xv, txt in labels:
            top.text(xv, 0.5, txt, ha="center", va="center", fontsize=ctx.pt(0.72), zorder=5,
                     bbox=dict(fc="white", ec="none", alpha=0.75, pad=1))
        top.set_title("срез от оси скважины в пласт", fontsize=ctx.pt(0.9))
        for tool in p["tools"]:
            for a in (top, bot):
                a.axvline(tool["radius_m"], color="#AD1457", lw=1.2, ls=":")
            top.text(tool["radius_m"], 1.0, tool["name"], rotation=0, ha="center", va="bottom", fontsize=ctx.pt(0.68),
                     color="#AD1457")
        bot.plot(st["r"], st["R"], color=sg["curves"].get("RD", {}).get("color", "#B71C1C"), lw=2.4)
        bot.set_yscale("log")
        bot.set_xlabel("расстояние от оси скважины, м")
        bot.set_ylabel("сопротивление, Ом·м")
        bot.grid(True, which="both", color=sg["palette"]["grid"], lw=0.5)
        bot.text(R, p["Rt"], f" ρп = {p['Rt']:g}", ha="right", va="bottom", fontsize=ctx.pt(0.75))
        bot.text(p["rw_m"], p["Rxo"], f" ρзп = {p['Rxo']:g}", ha="left", va="bottom", fontsize=ctx.pt(0.75))
        legend = [{"kind": "patch", "label": "фильтрат раствора в порах", "color": filt},
                  {"kind": "patch", "label": f"{sg['fluids'][p['fluid']]['ru']} в порах", "color": fcol},
                  {"kind": "patch", "label": sg["fluids"]["mud_cake"]["ru"], "color": sg["fluids"]["mud_cake"]["color"]}]
        return {"exaggerations": [], "legend": legend, "notes": [], "axes": [top, bot]}
