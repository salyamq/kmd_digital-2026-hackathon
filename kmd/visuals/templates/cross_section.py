"""cross_section: layered section with structure, a fault, fluids in a trap and wells.

State model: a layer-index field on an (x, z) grid computed from layer thicknesses, a structure
function and a (possibly inclined) fault plane. The fault throw is applied to all horizons at
once, so the offset is the same on every layer and in every frame. Fluids fill the pores of the
reservoir layer by depth relative to horizontal contacts: gas above GOC, oil above OWC, water below.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from ..base import DrawCtx, Issue, Template, common_props, register
from ..style import fluid_color, lith
from .log_track import LITH_KEYS


def _structure(xf: np.ndarray, st: dict) -> np.ndarray:
    """Depth offset (m, +down) of all horizons along the normalized x in [0,1]."""
    typ = st.get("type", "flat")
    A = st.get("amplitude_m", 0.0)
    c = st.get("center_frac", 0.5)
    wd = max(st.get("width_frac", 0.5), 1e-3)
    if typ == "anticline":
        return -A * np.exp(-((xf - c) / (wd / 2)) ** 2)
    if typ == "syncline":
        return A * np.exp(-((xf - c) / (wd / 2)) ** 2)
    if typ == "monocline":
        return np.tan(math.radians(st.get("dip_deg", 2.0))) * (xf - 0.5) * st.get("_width_m", 5000.0)
    return np.zeros_like(xf)


@register
class CrossSection(Template):
    name = "cross_section"
    title_ru = "Геологический разрез: слои, структура, разлом, флюиды в ловушке, скважины"
    description = (
        "Вертикальный разрез: слои сверху вниз (молодые над старыми), форма структуры (горизонтально, "
        "антиклиналь, синклиналь, моноклиналь), разлом с одинаковым смещением всех слоёв, флюиды в ПОРАХ "
        "пласта-коллектора по горизонтальным контактам (газ над нефтью над водой), покрышка, скважины. "
        "Вертикальное преувеличение вычисляется и подписывается числом; vertical_exaggeration=1 даёт истинный "
        "масштаб («пласт как лист бумаги»). Для ловушек, контактов ВНК/ГНК, корреляции разрезов скважин, "
        "«почему нефть не озеро», масштабов."
    )
    use_for = ["П", "М", "В", "Н", "ловушка", "контакты флюидов", "разлом", "масштаб"]
    frame_class = "B"
    provenance = "схема"
    animatable = True
    animation = "t∈[0,1]: заполнение ловушки — контакты опускаются от кровли до заданных глубин (накопление УВ)"
    default_size = (1200, 750)
    params_schema = {
        "type": "object",
        "required": ["layers"],
        "properties": {
            **common_props(),
            "layers": {"type": "array", "minItems": 2, "description": "Слои сверху вниз (от молодых к древним)",
                       "items": {"type": "object", "required": ["lith", "thickness_m"],
                                 "properties": {"lith": {"enum": LITH_KEYS}, "thickness_m": {"type": "number", "exclusiveMinimum": 0},
                                                "name": {"type": "string"}}}},
            "top_depth_m": {"type": "number", "default": 1000, "description": "глубина кровли верхнего слоя на краях"},
            "width_m": {"type": "number", "exclusiveMinimum": 0, "default": 5000},
            "structure": {"type": "object", "default": {"type": "flat"},
                          "properties": {"type": {"enum": ["flat", "anticline", "syncline", "monocline"]},
                                         "amplitude_m": {"type": "number", "minimum": 0},
                                         "center_frac": {"type": "number", "minimum": 0, "maximum": 1},
                                         "width_frac": {"type": "number", "exclusiveMinimum": 0, "maximum": 2},
                                         "dip_deg": {"type": "number", "minimum": -30, "maximum": 30}}},
            "fault": {"type": ["object", "null"], "default": None,
                      "properties": {"x_frac": {"type": "number", "minimum": 0, "maximum": 1},
                                     "throw_m": {"type": "number", "description": "+: правый блок опущен"},
                                     "dip_deg": {"type": "number", "minimum": 30, "maximum": 90, "default": 70},
                                     "sealing": {"type": "boolean", "default": True}}},
            "traps": {"type": "array", "default": [],
                      "items": {"type": "object", "required": ["layer"],
                                "properties": {"layer": {"type": "integer", "minimum": 0, "description": "индекс слоя-коллектора"},
                                               "goc_m": {"type": ["number", "null"], "description": "глубина ГНК"},
                                               "owc_m": {"type": ["number", "null"], "description": "глубина ВНК"},
                                               "transition_m": {"type": "number", "minimum": 0, "default": 0,
                                                                "description": "переходная зона над ВНК (показывается градиентом)"}}}},
            "wells": {"type": "array", "default": [],
                      "items": {"type": "object", "required": ["x_frac"],
                                "properties": {"x_frac": {"type": "number", "minimum": 0, "maximum": 1},
                                               "name": {"type": "string"}, "depth_m": {"type": "number"}}}},
            "vertical_exaggeration": {"type": ["number", "null"], "default": None,
                                      "description": "null — подобрать; 1 — истинный масштаб; иначе ×N"},
            "show_labels": {"type": "boolean", "default": True},
        },
    }
    example = {
        "title": "Антиклинальная ловушка: газ, нефть и вода в порах песчаника",
        "layers": [
            {"lith": "shale", "thickness_m": 60, "name": "покрышка"},
            {"lith": "sand", "thickness_m": 40, "name": "пласт-коллектор"},
            {"lith": "shale", "thickness_m": 50},
            {"lith": "limestone", "thickness_m": 40},
        ],
        "top_depth_m": 1500, "width_m": 6000,
        "structure": {"type": "anticline", "amplitude_m": 70, "center_frac": 0.5, "width_frac": 0.6},
        "traps": [{"layer": 1, "goc_m": 1525, "owc_m": 1555}],
        "wells": [{"x_frac": 0.5, "name": "Скв. 1"}, {"x_frac": 0.82, "name": "Скв. 2"}],
    }

    # ---------------------------------------------------------------- model
    def state(self, params, t=None, nx=500, nz=500):
        W = params["width_m"]
        L = params["layers"]
        st = dict(params.get("structure") or {"type": "flat"})
        st["_width_m"] = W
        xf = np.linspace(0, 1, nx)
        off = _structure(xf, st)
        cum = np.concatenate([[0], np.cumsum([l["thickness_m"] for l in L])])
        z_top = params["top_depth_m"]
        hor = z_top + cum[:, None] + off[None, :]  # horizons (nl+1, nx), unfaulted
        fault = params.get("fault")
        throw = fault.get("throw_m", 0.0) if fault else 0.0
        zmin = float(hor.min()) - 0.15 * (cum[-1])
        zmax = float(hor.max()) + max(throw, 0) + 0.1 * cum[-1]
        if fault and throw < 0:
            zmin += throw
        zz = np.linspace(zmin, zmax, nz)
        X, Z = np.meshgrid(xf, zz)
        Zu = Z.copy()
        right = np.zeros_like(X, dtype=bool)
        fx = None
        if fault:
            dip = math.radians(fault.get("dip_deg", 70))
            zref = (zmin + zmax) / 2
            # fault plane dips to the right: x_f(z) = x0 + (z - zref)/tan(dip) / W
            fx = lambda z: fault["x_frac"] + (z - zref) / math.tan(dip) / W  # noqa: E731
            right = X > fx(Z)
            Zu = np.where(right, Z - throw, Z)
        # layer index from unshifted depth
        idx = np.full(X.shape, -1)
        for i in range(len(L)):
            topi = np.interp(xf, xf, hor[i])[None, :]
            basei = np.interp(xf, xf, hor[i + 1])[None, :]
            idx = np.where((Zu >= topi) & (Zu < basei), i, idx)
        idx = np.where(Zu >= hor[-1][None, :], len(L), idx)  # below the deepest layer
        # fluids (fill fraction f in [0,1] animates contacts descending from the crest)
        f = 1.0 if t is None else float(t)
        fluid = np.zeros(X.shape, dtype=int)  # 0 none/water-saturated non-reservoir, 1 water, 2 oil, 3 gas
        contacts = []
        for tr in params.get("traps", []):
            li = tr["layer"]
            in_res = idx == li
            # trap crest = shallowest point of the reservoir top
            crest = float(np.min(np.where(in_res, Z, np.inf)))
            owc, goc = tr.get("owc_m"), tr.get("goc_m")
            owc_t = None if owc is None else crest + f * (owc - crest)
            goc_t = None if goc is None else crest + f * (goc - crest)
            fl = np.where(in_res, 1, 0)
            if owc_t is not None:
                fl = np.where(in_res & (Z < owc_t), 2, fl)
            if goc_t is not None:
                fl = np.where(in_res & (Z < goc_t), 3, fl)
            # hydrocarbons only in the connected part of the reservoir that contains the crest
            hc = fl >= 2
            if hc.any():
                lab, _ = ndimage.label(hc)
                ci, cj = np.unravel_index(np.argmin(np.where(in_res, Z, np.inf)), Z.shape)
                keep = lab == lab[ci, cj] if lab[ci, cj] > 0 else np.zeros_like(hc)
                fl = np.where(hc & ~keep, 1, fl)
            fluid = np.where(in_res, fl, fluid)
            contacts.append({"layer": li, "goc": goc_t, "owc": owc_t, "crest": crest,
                             "transition": tr.get("transition_m", 0.0)})
        return {"x": xf * W, "xf": xf, "z": zz, "idx": idx, "fluid": fluid, "horizons": hor, "fault_x": fx,
                "contacts": contacts, "zmin": zmin, "zmax": zmax, "right": right}

    # ---------------------------------------------------------------- checks
    def check(self, params):
        iss = []
        L = params["layers"]
        sg = self.sg(params)
        for tr in params.get("traps", []):
            li = tr["layer"]
            if li >= len(L):
                iss.append(Issue("error", "trap_layer", f"нет слоя {li}"))
                continue
            props = lith(sg, L[li]["lith"]).get("props", {})
            if not props.get("reservoir") and L[li]["lith"] not in ("limestone", "dolomite"):
                iss.append(Issue("error", "fluid_in_nonreservoir", f"флюиды в непроницаемом слое ({L[li]['lith']})"))
            if li == 0:
                iss.append(Issue("error", "no_seal", "у коллектора нет покрышки сверху"))
            elif lith(sg, L[li - 1]["lith"]).get("props", {}).get("reservoir"):
                iss.append(Issue("error", "no_seal", "слой над коллектором проницаем — нет покрышки"))
            goc, owc = tr.get("goc_m"), tr.get("owc_m")
            if goc is not None and owc is not None and goc >= owc:
                iss.append(Issue("error", "fluid_order", "ГНК должен быть выше ВНК (газ над нефтью)"))
            if goc is not None and owc is None:
                iss.append(Issue("warning", "gas_only", "задан только ГНК: газовая шапка без нефти — проверить по источнику"))
            st = self.state(params)
            c = [k for k in st["contacts"] if k["layer"] == li][0]
            deepest = owc if owc is not None else goc
            if deepest is not None:
                if deepest <= c["crest"]:
                    iss.append(Issue("error", "contact_above_crest", "контакт выше кровли ловушки — залежи нет"))
                # closure: hydrocarbon zone must not reach the section edge (spill)
                hc = st["fluid"] >= 2
                edge = hc[:, :3].any() or hc[:, -3:].any()
                if edge and not params.get("fault"):
                    iss.append(Issue("warning", "open_trap",
                                     "залежь доходит до края разреза: проверить замыкание ловушки (иначе УВ уходят вверх по пласту)"))
        ve = params.get("vertical_exaggeration")
        if ve is not None and ve < 1:
            iss.append(Issue("error", "ve", "вертикальное преувеличение < 1"))
        if params["top_depth_m"] < 0 or params["top_depth_m"] > 8000:
            iss.append(Issue("error", "depth_range", "глубина неправдоподобна"))
        return iss

    def describe(self, params):
        sg = self.sg(params)
        L = params["layers"]
        s = "Разрез: " + ", ".join(f"{lith(sg, l['lith'])['ru']} {l['thickness_m']:g} м" for l in L)
        st = (params.get("structure") or {}).get("type", "flat")
        s += {"anticline": "; слои изогнуты в антиклиналь", "syncline": "; синклиналь",
              "monocline": "; моноклиналь"}.get(st, "")
        if params.get("fault"):
            s += f"; разлом со смещением {abs(params['fault'].get('throw_m', 0)):g} м"
        for tr in params.get("traps", []):
            if tr.get("goc_m") is not None:
                s += f"; ГНК на {tr['goc_m']:g} м"
            if tr.get("owc_m") is not None:
                s += f"; ВНК на {tr['owc_m']:g} м"
        return s + ". Глубина растёт вниз."

    # ---------------------------------------------------------------- draw
    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        L = params["layers"]
        W = params["width_m"]
        x0, y0, w, h = rect
        box_w_px, box_h_px = w * ctx.fig_px[0], h * ctx.fig_px[1]
        st = self.state(params, t)
        zmin, zmax = st["zmin"], st["zmax"]
        ve_req = params.get("vertical_exaggeration")
        if ve_req:
            # depth window that gives exactly the requested VE
            zspan = W * (box_h_px / box_w_px) / ve_req
            zc = (zmin + zmax) / 2
            zmin, zmax = zc - zspan / 2, zc + zspan / 2
            params = dict(params)
        ax = fig.add_axes(rect)
        ax.set_xlim(0, W)
        ax.set_ylim(zmax, zmin)
        Xg, Zg = np.meshgrid(st["x"], st["z"])
        cols = [lith(sg, l["lith"])["color"] for l in L] + [lith(sg, L[-1]["lith"])["color"]]
        hat = [lith(sg, l["lith"]).get("hatch") or None for l in L] + [lith(sg, L[-1]["lith"]).get("hatch") or None]
        idx = st["idx"].astype(float)
        above = idx < 0
        # overburden above the top layer: neutral
        idx = np.where(above, np.nan, idx)
        levels = np.arange(-0.5, len(L) + 1.0, 1.0)
        ax.contourf(Xg, Zg, idx, levels=levels, colors=cols, zorder=1).set_rasterized(True)
        cs = ax.contourf(Xg, Zg, idx, levels=levels, colors="none", hatches=hat, zorder=2)
        cs.set_rasterized(True)
        for coll in getattr(cs, "collections", [cs]):
            try:
                coll.set_edgecolor("#555555")
                coll.set_linewidth(0)
            except Exception:
                pass
        if np.any(above):
            ax.contourf(Xg, Zg, np.where(above, 1.0, np.nan), levels=[0.5, 1.5], colors=["#EEEEEE"], zorder=1)
        # fluids in pores of the reservoir: color overlay with the rock hatch still visible
        fl = st["fluid"].astype(float)
        fcol = {1: fluid_color(sg, "water"), 2: fluid_color(sg, "oil"), 3: fluid_color(sg, "gas")}
        for code, col in fcol.items():
            m = np.where(fl == code, 1.0, np.nan)
            if np.all(np.isnan(m)):
                continue
            ax.contourf(Xg, Zg, m, levels=[0.5, 1.5], colors=[col], alpha=0.55, zorder=3).set_rasterized(True)
        # layer boundaries
        ax.contour(Xg, Zg, st["idx"].astype(float), levels=np.arange(-0.5, len(L) + 0.5, 1.0), colors="#333333",
                   linewidths=0.7, zorder=4)
        # fault plane
        if st["fault_x"] is not None:
            zz = np.array([zmin, zmax])
            ax.plot(st["fault_x"](zz) * W, zz, color="#B71C1C", lw=2.2, zorder=6)
            thr = params["fault"].get("throw_m", 0)
            zm = zmin + 0.12 * (zmax - zmin)
            xm = st["fault_x"](zm) * W
            ax.annotate("", xy=(xm + 0.03 * W, zm + 0.08 * (zmax - zmin) * np.sign(thr)), xytext=(xm + 0.03 * W, zm),
                        arrowprops=dict(arrowstyle="->", color="#B71C1C", lw=1.5), zorder=7)
            ax.annotate("", xy=(xm - 0.03 * W, zm - 0.08 * (zmax - zmin) * np.sign(thr)), xytext=(xm - 0.03 * W, zm),
                        arrowprops=dict(arrowstyle="->", color="#B71C1C", lw=1.5), zorder=7)
            ax.text(xm, zmin + 0.02 * (zmax - zmin), f"разлом, смещение {abs(thr):g} м", color="#B71C1C",
                    ha="center", va="top", fontsize=ctx.pt(0.8), fontweight="bold", zorder=8,
                    bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))
        # contacts: horizontal dashed lines across the reservoir extent
        for c in st["contacts"]:
            for key, lab, col in (("goc", "ГНК", fluid_color(sg, "gas")), ("owc", "ВНК", fluid_color(sg, "water"))):
                zc = c[key]
                if zc is None:
                    continue
                row = np.argmin(np.abs(st["z"] - zc))
                cols_in = np.where(st["idx"][row] == c["layer"])[0]
                if len(cols_in) == 0:
                    continue
                xa, xb = st["x"][cols_in.min()], st["x"][cols_in.max()]
                ax.plot([xa, xb], [zc, zc], color=col, lw=1.6, ls="--", zorder=8)
                ax.text(xb, zc, f" {lab} {zc:.0f} м", color=col, va="center", ha="left", fontsize=ctx.pt(0.8),
                        fontweight="bold", zorder=9, bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.5))
        # wells
        for wl in params.get("wells", []):
            xw = wl["x_frac"] * W
            zd = wl.get("depth_m") or zmax
            ax.plot([xw, xw], [zmin, zd], color="#111111", lw=2.0, zorder=10)
            ax.plot([xw], [zmin], marker="v", color="#111111", ms=ctx.base_px * 0.7, zorder=10, clip_on=False)
            if wl.get("name"):
                ax.text(xw, zmin, wl["name"] + "\n", ha="center", va="bottom", fontsize=ctx.pt(0.8), zorder=10)
        # layer names on the left
        if params["show_labels"]:
            hor = st["horizons"]
            for i, l in enumerate(L):
                if l.get("name"):
                    zc = (hor[i][5] + hor[i + 1][5]) / 2
                    if zmin < zc < zmax:
                        ax.text(0.01 * W, zc, l["name"], va="center", ha="left", fontsize=ctx.pt(0.78),
                                zorder=9, bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.8))
        ax.set_xlabel("расстояние, м")
        ax.set_ylabel("глубина, м")
        # VE from the real axes geometry
        ve = (box_h_px / (zmax - zmin)) / (box_w_px / W)
        exag = []
        notes = []
        if ve > 1.3:
            exag.append({"what": "вертикальный масштаб", "factor": round(ve, 0 if ve > 5 else 1)})
        else:
            notes.append("истинный масштаб: без вертикального преувеличения")
        legend = []
        for l in L:
            lt = lith(sg, l["lith"])
            if lt["ru"] not in [i["label"] for i in legend]:
                legend.append({"kind": "patch", "label": lt["ru"], "color": lt["color"], "hatch": lt.get("hatch")})
        present = set(np.unique(st["fluid"]).tolist())
        for code, fk in ((3, "gas"), (2, "oil"), (1, "water")):
            if code in present:
                legend.append({"kind": "patch", "label": sg["fluids"][fk]["ru"] + " в порах", "color": fluid_color(sg, fk)})
        return {"exaggerations": exag, "legend": legend, "notes": notes, "axes": [ax], "ve": ve}
