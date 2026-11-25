"""log_track: lithology column + borehole + synthetic log curves from ONE petrophysical model.

The tool depth drives both the tool position in the borehole and the current point of every
curve (curves are drawn only where the tool has already passed).
"""
from __future__ import annotations

import math

import numpy as np
from matplotlib.patches import Rectangle

from .. import models
from ..base import DrawCtx, Issue, Template, common_props, register
from ..style import fluid_color, lith

CURVE_IDS = ["GR", "SP", "CALI", "RD", "RS", "MNOR", "MINV", "NPHI", "NGK", "RHOB", "DT"]
LITH_KEYS = ["sand", "shaly_sand", "siltstone", "shale", "limestone", "dolomite", "marl", "anhydrite",
             "salt", "coal", "conglomerate", "basement", "generic"]


def _norm(v, rng, scale):
    a, b = rng
    if scale == "log":
        v = np.log10(np.maximum(v, 1e-4))
        a, b = math.log10(a), math.log10(b)
    return (v - a) / (b - a)


@register
class LogTrack(Template):
    name = "log_track"
    title_ru = "Каротажный планшет: литоколонка, скважина с прибором и кривые ГИС"
    description = (
        "Литологическая колонка (цвет и знак породы по стайлгайду, флюид в порах точками), ствол "
        "скважины с глинистой коркой и кавернами, прибор на кабеле, и синтетические кривые ГИС "
        "(ГК, ПС, кавернометрия, сопротивления двух глубинностей, микрозонды, НК/НГК, ГГК-П, АК), "
        "рассчитанные из ОДНОЙ модели пласта (Арчи, ПС по ρф/ρв, плотность/АК по пористости). "
        "Глубина вниз. Для вопросов «как по кривым выделить коллектор / глину / плотную породу / "
        "нефть и воду, ВНК, эффективная толщина», «что регистрирует прибор»."
    )
    use_for = ["И", "Пр", "Н", "Р", "data_practice", "прибор в скважине", "выделение коллекторов"]
    frame_class = "B"
    provenance = "симуляция"
    animatable = True
    animation = "t∈[0,1]: прибор идёт от забоя вверх (кабельный каротаж), кривые дописываются до глубины прибора"
    default_size = (1200, 1100)
    params_schema = {
        "type": "object",
        "required": ["layers"],
        "properties": {
            **common_props(),
            "layers": {
                "type": "array", "minItems": 1,
                "description": "Пласты сверху вниз; глубины в метрах",
                "items": {
                    "type": "object", "required": ["top", "base", "lith"],
                    "properties": {
                        "top": {"type": "number"}, "base": {"type": "number"},
                        "lith": {"enum": LITH_KEYS},
                        "fluid": {"enum": ["water", "oil", "gas", None], "default": None,
                                  "description": "флюид в порах (только для проницаемых пород)"},
                        "phi": {"type": "number", "minimum": 0, "maximum": 0.45, "description": "пористость, д.ед."},
                        "vsh": {"type": "number", "minimum": 0, "maximum": 1, "description": "глинистость, д.ед."},
                        "sw": {"type": "number", "minimum": 0, "maximum": 1, "description": "водонасыщенность"},
                        "permeable": {"type": "boolean", "description": "коллектор (проницаем) или нет"},
                        "rt": {"type": "number", "exclusiveMinimum": 0, "description": "задать сопротивление явно, Ом·м"},
                        "label": {"type": "string"},
                    },
                },
            },
            "curves": {"type": "array", "items": {"enum": CURVE_IDS}, "default": ["GR", "SP", "CALI", "RD", "RS"]},
            "rw": {"type": "number", "exclusiveMinimum": 0, "default": 0.05, "description": "ρв пластовой воды, Ом·м"},
            "rmf": {"type": "number", "exclusiveMinimum": 0, "default": 0.5, "description": "ρф фильтрата раствора, Ом·м (пресный раствор: ρф > ρв)"},
            "bit_mm": {"type": "number", "default": 216},
            "mudcake_mm": {"type": "number", "default": 10},
            "show_well": {"type": "boolean", "default": True},
            "show_invasion": {"type": "boolean", "default": True, "description": "показать зону проникновения фильтрата у стенки против коллекторов"},
            "tool_depth": {"type": ["number", "null"], "default": None, "description": "статичное положение прибора (м)"},
            "logging_direction": {"enum": ["up", "down"], "default": "up"},
            "annotations": {
                "type": "array", "default": [],
                "items": {"type": "object", "required": ["top", "base", "text"],
                          "properties": {"top": {"type": "number"}, "base": {"type": "number"},
                                         "text": {"type": "string"},
                                         "kind": {"enum": ["observation", "inference", "assumption"], "default": "inference"}}},
            },
            "noise": {"type": "number", "minimum": 0, "maximum": 0.2, "default": 0.02},
        },
    }
    example = {
        "title": "Песчаник с нефтью над водой между глинами",
        "layers": [
            {"top": 1000, "base": 1006, "lith": "shale"},
            {"top": 1006, "base": 1010, "lith": "sand", "fluid": "oil", "phi": 0.22},
            {"top": 1010, "base": 1014, "lith": "sand", "fluid": "water", "phi": 0.22},
            {"top": 1014, "base": 1018, "lith": "shale"},
            {"top": 1018, "base": 1021, "lith": "limestone", "phi": 0.03},
            {"top": 1021, "base": 1025, "lith": "shale"},
        ],
        "curves": ["GR", "SP", "CALI", "RD", "RS"],
        "annotations": [{"top": 1010, "base": 1010, "text": "ВНК", "kind": "inference"}],
    }

    # ------------------------------------------------------------------------------
    def check(self, params):
        iss = []
        L = sorted(params["layers"], key=lambda l: l["top"])
        for a in L:
            if a["base"] <= a["top"]:
                iss.append(Issue("error", "layer_thickness", f"пласт {a['top']}–{a['base']} м: подошва не ниже кровли"))
            if a["top"] < 0 or a["base"] > 9000:
                iss.append(Issue("error", "depth_range", f"глубина {a['top']}–{a['base']} м неправдоподобна"))
        for a, b in zip(L, L[1:]):
            if b["top"] < a["base"] - 1e-6:
                iss.append(Issue("error", "layer_overlap", f"пласты перекрываются на {b['top']} м"))
            elif b["top"] > a["base"] + 1e-6:
                iss.append(Issue("warning", "layer_gap", f"разрыв в колонке {a['base']}–{b['top']} м"))
        # fluids only in permeable rocks, density order inside one connected permeable body
        body = []
        bodies = []
        for a in L:
            perm = a.get("permeable")
            if perm is None:
                perm = a["lith"] in ("sand", "shaly_sand", "conglomerate") or (a.get("phi", 0) >= 0.08 and a["lith"] in ("limestone", "dolomite"))
            if a["lith"] == "shale":
                perm = False
            if a.get("fluid") in ("oil", "gas") and not perm:
                iss.append(Issue("error", "fluid_in_nonreservoir",
                                 f"{a['fluid']} в непроницаемой породе ({a['lith']}, {a['top']} м)"))
            if perm:
                if body and abs(body[-1]["base"] - a["top"]) > 1e-6:
                    bodies.append(body)
                    body = []
                body.append(a)
            else:
                if body:
                    bodies.append(body)
                body = []
        if body:
            bodies.append(body)
        rank = {"gas": 0, "oil": 1, "water": 2, None: 2}
        for bd in bodies:
            seq = [rank[x.get("fluid")] for x in bd]
            if any(s2 < s1 for s1, s2 in zip(seq, seq[1:])):
                iss.append(Issue("error", "fluid_order",
                                 f"в едином коллекторе {bd[0]['top']}–{bd[-1]['base']} м нарушен порядок газ→нефть→вода"))
        if params["rmf"] <= params["rw"] and "SP" in params["curves"]:
            iss.append(Issue("warning", "sp_sign",
                             "ρф ≤ ρв: аномалия ПС против коллекторов положительная (солёный раствор) — назвать в кадре"))
        if not (100 <= params["bit_mm"] <= 700):
            iss.append(Issue("error", "bit_size", f"диаметр долота {params['bit_mm']} мм неправдоподобен"))
        if params.get("tool_depth") is not None:
            if not (L[0]["top"] <= params["tool_depth"] <= L[-1]["base"]):
                iss.append(Issue("error", "tool_depth", "прибор вне интервала колонки"))
        return iss

    def state(self, params, t=None):
        sg = self.sg(params)
        L = sorted(params["layers"], key=lambda l: l["top"])
        res = models.synth_logs(L, sg["lithology"], sg["fluids"], rw=params["rw"], rmf=params["rmf"],
                                bit_mm=params["bit_mm"], mudcake_mm=params["mudcake_mm"], noise=params["noise"])
        top, base = L[0]["top"], L[-1]["base"]
        tool = params.get("tool_depth")
        if t is not None:
            tool = base - t * (base - top) if params["logging_direction"] == "up" else top + t * (base - top)
        res["tool_depth"] = tool
        res["top"], res["base"] = top, base
        return res

    def describe(self, params):
        L = sorted(params["layers"], key=lambda l: l["top"])
        sg = self.sg(params)
        parts = []
        for a in L:
            s = f"{lith(sg, a['lith'])['ru']} {a['top']:g}–{a['base']:g} м"
            if a.get("fluid"):
                s += f" ({sg['fluids'][a['fluid']]['ru']})"
            parts.append(s)
        names = ", ".join(sg["curves"][c]["ru"] for c in params["curves"] if c in sg["curves"])
        return f"Каротажный планшет: {'; '.join(parts)}. Кривые: {names}. Глубина растёт вниз."

    # ------------------------------------------------------------------------------
    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        st = self.state(params, t)
        z, C = st["depth"], st["curves"]
        top, base = st["top"], st["base"]
        tool = st["tool_depth"]
        x0, y0, w, h = rect
        head_h = 0.16 * h if ctx.mode == "video" else 0.15 * h
        body_h = h - head_h
        curves = [c for c in params["curves"] if c in sg["curves"]]
        tracks: list[str] = []
        for c in curves:
            tr = sg["curves"][c]["track"]
            if tr not in tracks:
                tracks.append(tr)
        widths = [0.30, 1.15 if params["show_well"] else 0.7] + [sg["tracks"].get(tr, {}).get("width", 1.0) for tr in tracks]
        tot = sum(widths)
        gap = 0.006
        xs = [x0]
        for wd in widths[:-1]:
            xs.append(xs[-1] + w * wd / tot)
        axes = []
        for i, wd in enumerate(widths):
            ax = fig.add_axes([xs[i] + gap / 2, y0, w * wd / tot - gap, body_h])
            ax.set_ylim(base, top)
            ax.set_xlim(0, 1)
            ax.tick_params(axis="x", bottom=False, labelbottom=False)
            if i > 0:
                ax.tick_params(axis="y", left=False, labelleft=False)
            axes.append(ax)
        # depth track
        dax = axes[0]
        dax.set_xticks([])
        span = base - top
        step = next(s for s in (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500) if span / s <= 12)
        ticks = np.arange(math.ceil(top / step) * step, base + 1e-6, step)
        dax.set_yticks([])
        for v in ticks:
            dax.text(0.92, v, f"{v:g}", ha="right", va="center", fontsize=ctx.pt(0.8), color="#212121")
            dax.plot([0.94, 1.0], [v, v], color="#212121", lw=0.8)
        # lithology + well column
        lax = axes[1]
        lax.set_xticks([])
        layers = st["layers"]
        rng = np.random.default_rng(3)
        well_x = 0.5
        for a in layers:
            lt = lith(sg, a["lith"])
            lax.add_patch(Rectangle((0, a["top"]), 1, a["base"] - a["top"], fc=lt["color"], ec="#555555",
                                    lw=0.5, hatch=lt.get("hatch") or None, zorder=1))
            if a.get("fluid") in ("oil", "gas", "water") and a.get("permeable"):
                col = fluid_color(sg, a["fluid"])
                npts = int(400 * (a["base"] - a["top"]) / max(span, 1e-6)) + 6
                px = rng.uniform(0.03, 0.97, npts)
                py = rng.uniform(a["top"], a["base"], npts)
                if params["show_well"]:
                    keep = np.abs(px - well_x) > 0.2
                    px, py = px[keep], py[keep]
                lax.scatter(px, py, s=(ctx.base_px * 0.33) ** 2, c=col, edgecolors="white", linewidths=0.4,
                            zorder=3)
                lax.add_patch(Rectangle((0.93, a["top"]), 0.07, a["base"] - a["top"], fc=col, ec="none", zorder=4))
        exag = []
        if params["show_well"]:
            bit = params["bit_mm"]
            half_w = 0.11  # axes fraction for nominal radius
            cal = C["CALI"]
            hw = half_w * cal / bit
            # invasion zone (filtrate) in permeable beds
            if params["show_invasion"]:
                perm = st["permeable"]
                inv = np.where(perm, half_w * 2.1, 0.0)
                lax.fill_betweenx(z, well_x - inv, well_x + inv, where=perm, color=sg["fluids"]["mud_filtrate"]["color"],
                                  alpha=0.45, lw=0, zorder=2)
            lax.fill_betweenx(z, well_x - hw, well_x + hw, color="#E9DFD6", lw=0, zorder=5)
            mcc = sg["fluids"]["mud_cake"]["color"]
            perm = st["permeable"]
            lax.fill_betweenx(z, well_x - half_w, well_x - hw, where=perm & (hw < half_w), color=mcc, lw=0, zorder=6)
            lax.fill_betweenx(z, well_x + hw, well_x + half_w, where=perm & (hw < half_w), color=mcc, lw=0, zorder=6)
            lax.plot(well_x - hw, z, color="#3E2723", lw=0.9, zorder=7)
            lax.plot(well_x + hw, z, color="#3E2723", lw=0.9, zorder=7)
            # exaggeration of the borehole width vs depth scale
            fig_w_px, fig_h_px = ctx.fig_px
            col_w_px = (w * widths[1] / tot - gap) * fig_w_px
            body_px = body_h * fig_h_px
            px_per_m_h = 2 * half_w * col_w_px / (bit / 1000.0)
            px_per_m_v = body_px / span
            f = px_per_m_h / px_per_m_v
            if f > 1.5:
                exag.append({"what": "диаметр скважины по горизонтали", "factor": round(f)})
            if tool is not None:
                tl = max(span * 0.05, 0.6)
                ty0 = tool - tl * 0.1
                lax.plot([well_x, well_x], [top, ty0], color="#212121", lw=1.2, zorder=8)
                lax.add_patch(Rectangle((well_x - half_w * 0.45, ty0), half_w * 0.9, tl, fc="#FFC107", ec="#212121",
                                        lw=1.0, zorder=9))
        # curve tracks
        hax = fig.add_axes([x0, y0 + body_h, w, head_h])
        hax.set_axis_off()
        hax.set_xlim(x0, x0 + w)
        hax.set_ylim(0, 1)
        if tool is not None:
            draw_mask = z >= tool if params["logging_direction"] == "up" else z <= tool
        else:
            draw_mask = np.ones_like(z, dtype=bool)
        for ti, tr in enumerate(tracks):
            ax = axes[2 + ti]
            ax.grid(axis="y", color=sg["palette"]["grid"], lw=0.5)
            ax.set_yticks(ticks)
            ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
            ax.grid(axis="x", color=sg["palette"]["grid"], lw=0.5)
            tr_curves = [c for c in curves if sg["curves"][c]["track"] == tr]
            if tr == "lith" and "CALI" in tr_curves:
                bitv = _norm(np.full_like(z, params["bit_mm"]), sg["curves"]["CALI"]["range"], "linear")
                ax.plot(bitv, z, color=sg["curves"]["BIT"]["color"], ls=":", lw=1.0)
            for ci, c in enumerate(tr_curves):
                cs = sg["curves"][c]
                v = _norm(C[c], cs["range"], cs["scale"])
                vv = np.where(draw_mask, v, np.nan)
                ax.plot(np.clip(vv, -0.02, 1.02), z, color=cs["color"], ls=cs.get("style", "-"),
                        lw=1.6 if ctx.mode == "video" else 1.3, zorder=5)
                if tool is not None:
                    k = int(np.argmin(np.abs(z - tool)))
                    ax.plot([np.clip(v[k], 0, 1)], [z[k]], "o", color=cs["color"], ms=ctx.base_px * 0.45, zorder=6,
                            mec="white", mew=0.8)
                # header line for the curve
                hx0 = xs[2 + ti] + gap / 2
                hw_ = w * widths[2 + ti] / tot - gap
                yy = 0.86 - ci * (0.8 / max(len(tr_curves), 3))
                hax.plot([hx0, hx0 + hw_], [yy - 0.08, yy - 0.08], color=cs["color"], ls=cs.get("style", "-"), lw=1.6)
                a_, b_ = cs["range"]
                hax.text(hx0 + hw_ / 2, yy, f"{cs['ru']}, {cs['unit']}", ha="center", va="bottom",
                         fontsize=ctx.pt(0.78), color=cs["color"], fontweight="bold")
                hax.text(hx0, yy - 0.1, f"{a_:g}", ha="left", va="top", fontsize=ctx.pt(0.68), color=cs["color"])
                hax.text(hx0 + hw_, yy - 0.1, f"{b_:g}", ha="right", va="top", fontsize=ctx.pt(0.68), color=cs["color"])
                if cs["scale"] == "log":
                    ax.set_xticks([])
                    for dec in range(int(math.floor(math.log10(a_))), int(math.ceil(math.log10(b_))) + 1):
                        xv = _norm(np.array(10.0 ** dec), cs["range"], "log")
                        if 0 <= xv <= 1:
                            ax.axvline(xv, color=sg["palette"]["grid"], lw=0.6)
            if tool is not None:
                ax.axhline(tool, color="#FFA000", lw=1.0, ls="--", zorder=4)
        # header for depth and lithology columns
        hax.text(xs[0] + w * widths[0] / tot / 2, 0.15, "м", ha="center", va="bottom", fontsize=ctx.pt(0.8))
        hax.text(xs[1] + w * widths[1] / tot / 2, 0.15, "порода и ствол" if params["show_well"] else "порода",
                 ha="center", va="bottom", fontsize=ctx.pt(0.8))
        # annotations (observation vs inference)
        for an in params.get("annotations", []):
            kind = an.get("kind", "inference")
            col = sg["process_chain"].get(kind, {}).get("color", "#AD1457")
            ztop, zb = an["top"], an["base"]
            for ax in axes[1:]:
                if zb > ztop:
                    ax.axhspan(ztop, zb, fc=col, alpha=0.07, zorder=0)
                else:
                    ax.axhline(ztop, color=col, lw=1.6, ls="-.", zorder=7)
            ax_last = axes[-1]
            ax_last.text(0.98, (ztop + zb) / 2, an["text"], ha="right", va="center", fontsize=ctx.pt(0.8),
                         color=col, fontweight="bold", zorder=10,
                         bbox=dict(fc="white", ec=col, lw=0.8, alpha=0.9, boxstyle="round,pad=0.2"))
        legend = self._legend_items(params, sg)
        return {"exaggerations": exag, "legend": legend,
                "notes": [sg.get("conventions", {}).get("log_display", {}).get("short_ru", "")],
                "axes": axes}

    def _legend_items(self, params, sg):
        items = []
        seen = set()
        for a in params["layers"]:
            if a["lith"] not in seen:
                seen.add(a["lith"])
                lt = lith(sg, a["lith"])
                items.append({"kind": "patch", "label": lt["ru"], "color": lt["color"], "hatch": lt.get("hatch")})
        for fl in ("gas", "oil", "water"):
            if any(a.get("fluid") == fl for a in params["layers"]):
                items.append({"kind": "dot", "label": sg["fluids"][fl]["ru"] + " в порах", "color": sg["fluids"][fl]["color"]})
        if params["show_well"]:
            items.append({"kind": "patch", "label": sg["fluids"]["mud_cake"]["ru"], "color": sg["fluids"]["mud_cake"]["color"]})
            if params["show_invasion"]:
                items.append({"kind": "patch", "label": "зона проникновения фильтрата",
                              "color": sg["fluids"]["mud_filtrate"]["color"]})
        return items

