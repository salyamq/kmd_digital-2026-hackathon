"""pressure_diffusion: pressure perturbation around a well / gallery from analytical solutions.

ONE state model p(x, t) (exact solution of the piezoconductivity equation and/or the ПССС
approximation) feeds every view: profile p(r) at time t, history p(t) at a fixed point,
plan view of the depression around the well. The current time t drives all views at once.
"""
from __future__ import annotations

import math

import numpy as np
from matplotlib.patches import Circle

from .. import models
from ..base import DrawCtx, Issue, Template, common_props, register

MD = 9.869233e-16  # m2 per millidarcy
DAY = 86400.0


def _si(p: dict) -> dict:
    k = p["k_md"] * MD
    mu = p["mu_mpas"] * 1e-3
    beta = p["beta_star_1_per_mpa"] * 1e-6
    kappa = p.get("kappa_m2_s") or k / (mu * beta)
    return dict(k=k, mu=mu, h=p["h_m"], B=p["B_m"], kappa=kappa, p0=p["p0_mpa"] * 1e6, pw=p["pw_mpa"] * 1e6,
                q=p["q_m3_day"] / DAY, rw=p["rw_m"])


@register
class PressureDiffusion(Template):
    name = "pressure_diffusion"
    title_ru = "Волна давления в пласте: p(r) и p(t) из одного решения"
    description = (
        "Неустановившаяся фильтрация упругой жидкости: давление вокруг скважины (плоскорадиальный поток) "
        "или у галереи (прямолинейный поток) после пуска. Точное решение уравнения пьезопроводности "
        "(интеграл вероятности erf, интегральная показательная функция −Ei) и/или приближение ПССС "
        "(возмущённая область радиуса R(t), стационарный профиль внутри). Виды: профиль p(r) в момент t, "
        "история p(t) в точке наблюдения, план воронки депрессии. Все виды считаются из одной модели. "
        "Для тем: упругий режим, пьезопроводность, воронка депрессии, «давление расходится не с постоянной скоростью»."
    )
    use_for = ["Ф", "М", "В", "волна давления", "фильтрация", "приток к скважине"]
    frame_class = "B"
    provenance = "симуляция"
    animatable = True
    animation = "t∈[0,1]: время после пуска скважины от 0 до t_max_h (линейно); все виды синхронно"
    default_size = (1400, 750)
    params_schema = {
        "type": "object",
        "properties": {
            **common_props(),
            "geometry": {"enum": ["radial", "linear"], "default": "radial"},
            "bc": {"enum": ["const_rate", "const_pressure"], "default": "const_rate",
                   "description": "на скважине/галерее: постоянный дебит или постоянное забойное давление"},
            "method": {"enum": ["exact", "pssc", "both", "exact_log"], "default": "exact",
                       "description": "точное решение, ПССС, оба для сравнения, или точное + логарифмическое приближение у скважины (радиальный поток, постоянный дебит)"},
            "r_scale": {"enum": ["linear", "log"], "default": "linear", "description": "шкала расстояния на профиле p(r)"},
            "near_zone_factor": {"type": ["number", "null"], "default": None,
                                 "description": "отметить ближнюю зону r² ≤ factor·4κt (например 0.03 по книге)"},
            "k_md": {"type": "number", "exclusiveMinimum": 0, "default": 100, "description": "проницаемость, мД"},
            "mu_mpas": {"type": "number", "exclusiveMinimum": 0, "default": 1.0, "description": "вязкость, мПа·с"},
            "h_m": {"type": "number", "exclusiveMinimum": 0, "default": 10},
            "B_m": {"type": "number", "exclusiveMinimum": 0, "default": 100, "description": "ширина пласта (для галереи), м"},
            "beta_star_1_per_mpa": {"type": "number", "exclusiveMinimum": 0, "default": 1e-3,
                                    "description": "коэффициент упругоёмкости пласта β*, 1/МПа"},
            "kappa_m2_s": {"type": ["number", "null"], "default": None, "description": "задать пьезопроводность κ напрямую, м²/с"},
            "q_m3_day": {"type": "number", "default": 100, "description": "дебит, м³/сут (>0 — отбор)"},
            "p0_mpa": {"type": "number", "default": 20, "description": "начальное пластовое давление, МПа"},
            "pw_mpa": {"type": "number", "default": 15, "description": "забойное давление (для const_pressure), МПа"},
            "rw_m": {"type": "number", "default": 0.1},
            "t_max_h": {"type": "number", "exclusiveMinimum": 0, "default": 24},
            "snapshots_h": {"type": "array", "items": {"type": "number", "exclusiveMinimum": 0}, "default": []},
            "r_max_m": {"type": ["number", "null"], "default": None},
            "r_obs_m": {"type": ["number", "null"], "default": None, "description": "точка наблюдения для p(t), м"},
            "views": {"type": "array", "items": {"enum": ["profile", "history", "plan"]},
                      "default": ["profile", "history"]},
            "history_points": {"type": "array", "items": {"enum": ["obs", "well"]}, "default": ["obs"],
                               "description": "что показывать на p(t): точку наблюдения и/или забой"},
            "show_front": {"type": "boolean", "default": True, "description": "граница возмущённой области ПССС"},
            "show_flow": {"type": "boolean", "default": True},
        },
    }
    example = {
        "title": "Пуск скважины с постоянным дебитом: воронка депрессии растёт как √t",
        "geometry": "radial", "bc": "const_rate", "method": "both",
        "k_md": 100, "mu_mpas": 1, "h_m": 10, "beta_star_1_per_mpa": 1e-3, "q_m3_day": 100, "p0_mpa": 20,
        "t_max_h": 24, "snapshots_h": [1, 6, 24], "views": ["profile", "history"],
    }

    # ------------------------------------------------------------------ model
    def _fn(self, p, method):
        s = _si(p)
        geom, bc = p["geometry"], p["bc"]
        kw = dict(kappa=s["kappa"], p0=s["p0"], q=s["q"], pw=s["pw"], k=s["k"], mu=s["mu"], h=s["h"], B=s["B"],
                  rw=s["rw"])
        if method == "log":
            def flog(x, tt):
                x = np.asarray(x, dtype=float)
                u = x ** 2 / (4 * kw["kappa"] * max(tt, 1e-9))
                v = kw["p0"] - kw["q"] * kw["mu"] / (4 * math.pi * kw["k"] * kw["h"]) * (-0.5772 - np.log(u))
                return np.where(v <= kw["p0"], v, np.nan)
            return flog
        f = models.diffusion_exact if method == "exact" else models.diffusion_pssc
        return lambda x, tt: f(geom, bc, x, tt, **kw)

    def _rmax(self, p):
        s = _si(p)
        return p.get("r_max_m") or 1.6 * 2 * math.sqrt(s["kappa"] * p["t_max_h"] * 3600) + 5 * s["rw"]

    def state(self, params, t=None):
        p = params
        s = _si(p)
        T = p["t_max_h"] * 3600 * (1.0 if t is None else max(float(t), 1e-4))
        rmax = self._rmax(p)
        x0 = s["rw"] if p["geometry"] == "radial" else 0.0
        x = np.geomspace(max(x0, 1e-3), rmax, 400) if p["r_scale"] == "log" else np.linspace(x0, rmax, 400)
        methods = {"both": ["exact", "pssc"], "exact_log": ["exact", "log"]}.get(p["method"], [p["method"]])
        prof = {m: self._fn(p, m)(x, T) for m in methods}
        front = float(models.pssc_front(p["geometry"], p["bc"], T, kappa=s["kappa"], rw=s["rw"]))
        r_obs = p.get("r_obs_m") or rmax * 0.3
        th = np.linspace(1e-3, p["t_max_h"], 160) * 3600
        hist = {}
        for m in methods:
            f = self._fn(p, m)
            hist[m] = {}
            if "obs" in p["history_points"]:
                hist[m]["obs"] = np.array([float(f(np.array([r_obs]), tt)[0]) for tt in th])
            if p["bc"] == "const_rate" and "well" in p["history_points"]:
                hist[m]["well"] = np.array([float(f(np.array([x0]), tt)[0]) for tt in th])
        return {"x": x, "T": T, "profiles": prof, "front": front, "r_obs": r_obs, "th": th, "hist": hist,
                "kappa": s["kappa"], "rmax": rmax}

    def check(self, params):
        iss = []
        s = _si(params)
        if not (0.005 <= s["kappa"] <= 50):
            iss.append(Issue("warning", "kappa_range", f"κ={s['kappa']:.3g} м²/с вне типичного диапазона 0,005–50"))
        if not (0.05 <= params["rw_m"] <= 0.3):
            iss.append(Issue("error", "rw_range", "радиус скважины неправдоподобен (0,05–0,3 м)"))
        if not (0 < params["p0_mpa"] <= 150):
            iss.append(Issue("error", "p0_range", "пластовое давление вне 0–150 МПа"))
        if params["bc"] == "const_pressure" and params["pw_mpa"] >= params["p0_mpa"]:
            iss.append(Issue("warning", "injection", "забойное давление выше пластового — это нагнетание, а не отбор"))
        if params["bc"] == "const_rate" and params["q_m3_day"] <= 0:
            iss.append(Issue("warning", "injection", "дебит ≤ 0: нагнетание"))
        st = self.state(params, 1.0)
        pmin = min(float(np.nanmin(v)) for v in st["profiles"].values())
        if pmin <= 0:
            iss.append(Issue("error", "negative_pressure", "давление стало ≤ 0 — параметры неправдоподобны"))
        return iss

    def describe(self, params):
        g = "вокруг скважины" if params["geometry"] == "radial" else "у галереи"
        m = {"exact": "точное решение", "pssc": "метод ПССС", "both": "точное решение и ПССС",
             "exact_log": "точное решение и логарифмическое приближение у скважины"}[params["method"]]
        return (f"Распределение давления {g} в разные моменты после пуска ({m}); "
                f"давление у забоя ниже, вдали равно начальному {params['p0_mpa']:g} МПа; область возмущения "
                f"растёт пропорционально корню из времени.")

    # ------------------------------------------------------------------ draw
    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        st = self.state(p, t)
        views = p["views"]
        x0, y0, w, h = rect
        wide = w * ctx.fig_px[0] > 1.25 * h * ctx.fig_px[1]
        n = len(views)
        rects = []
        for i in range(n):
            if wide:
                gap = 0.07 * w
                ww = (w - gap * (n - 1)) / n
                rects.append([x0 + i * (ww + gap), y0, ww, h])
            else:
                gap = 0.09 * h
                hh = (h - gap * (n - 1)) / n
                rects.append([x0, y0 + (n - 1 - i) * (hh + gap), w, hh])
        res_axes = []
        pal = sg["pressure"]
        col = {"exact": pal["exact_color"], "pssc": pal["approx_color"], "log": pal["approx_color"]}
        lab = {"exact": "точное решение", "pssc": "ПССС (приближённо)", "log": "логарифмическая формула"}
        xl = "расстояние от скважины r, м" if p["geometry"] == "radial" else "расстояние от галереи x, м"
        T_h = st["T"] / 3600
        exag = []
        for v, r in zip(views, rects):
            ax = fig.add_axes(r)
            res_axes.append(ax)
            if v == "profile":
                ax.axhline(p["p0_mpa"], color=pal["initial_color"], lw=1.0, ls=":")
                ax.text(st["rmax"], p["p0_mpa"], "начальное p₀ ", ha="right", va="bottom", fontsize=ctx.pt(0.75),
                        color=pal["initial_color"])
                for sh in p["snapshots_h"]:
                    if t is not None and sh * 3600 > st["T"] + 1:
                        continue
                    for m in st["profiles"]:
                        yy = self._fn(p, m)(st["x"], sh * 3600) / 1e6
                        ax.plot(st["x"], yy, color=col[m], lw=1.0, alpha=0.45, ls="-" if m == "exact" else "--")
                        k = int(len(st["x"]) * 0.12)
                        if m == list(st["profiles"])[0]:
                            ax.text(st["x"][k], yy[k], f"{sh:g} ч", fontsize=ctx.pt(0.7), color=col[m], alpha=0.8,
                                    ha="left", va="top")
                for m, yy in st["profiles"].items():
                    ax.plot(st["x"], yy / 1e6, color=col[m], lw=2.4, ls="-" if m == "exact" else "--", label=lab[m])
                if p["show_front"] and (p["method"] in ("pssc", "both")):
                    ax.axvline(st["front"], color=pal["approx_color"], lw=1.0, ls="-.")
                    ax.text(st["front"], ax.get_ylim()[0], " R(t)" if p["geometry"] == "radial" else " l(t)",
                            color=pal["approx_color"], fontsize=ctx.pt(0.8), va="bottom", ha="left")
                if p["show_flow"]:
                    ya = p["p0_mpa"] - 0.12 * (p["p0_mpa"] - min(float(np.nanmin(v_)) for v_ in st["profiles"].values()) / 1e6)
                    ax.annotate("", xy=(st["rmax"] * 0.55, ya), xytext=(st["rmax"] * 0.8, ya),
                                arrowprops=dict(arrowstyle="-|>", color="#455A64", lw=1.6))
                    ax.text(st["rmax"] * 0.675, ya, "приток\n", ha="center", va="bottom", fontsize=ctx.pt(0.72),
                            color="#455A64")
                ax.set_xlabel(xl)
                ax.set_ylabel("давление p, МПа")
                if p["r_scale"] == "log":
                    ax.set_xscale("log")
                    ax.set_xlim(st["x"][0], st["rmax"])
                else:
                    ax.set_xlim(0, st["rmax"])
                if p.get("near_zone_factor"):
                    rz = math.sqrt(p["near_zone_factor"] * 4 * st["kappa"] * st["T"])
                    ax.axvspan(st["x"][0], rz, color=pal["exact_color"], alpha=0.08, lw=0)
                    ax.axvline(rz, color=pal["exact_color"], lw=1.0, ls=":")
                    ax.text(rz, ax.get_ylim()[1], " ближняя зона ", ha="right", va="top", fontsize=ctx.pt(0.72),
                            color=pal["exact_color"])
                ax.set_title(f"p(r) через {T_h:.3g} ч после пуска", fontsize=ctx.pt(0.95))
                if len(st["profiles"]) > 1:
                    ax.legend(loc="lower right", fontsize=ctx.pt(0.75), frameon=True)
                ax.grid(color=sg["palette"]["grid"], lw=0.5)
            elif v == "history":
                th = st["th"] / 3600
                for m, hd in st["hist"].items():
                    if "obs" in hd:
                        ax.plot(th, hd["obs"] / 1e6, color=col[m], lw=2.0, ls="-" if m == "exact" else "--",
                                label=f"r = {st['r_obs']:.0f} м, {lab[m]}")
                    if "well" in hd:
                        ax.plot(th, hd["well"] / 1e6, color=col[m], lw=2.0, ls="-" if m == "exact" else "--",
                                label=f"забой, {lab[m]}")
                ax.axvline(T_h, color="#FFA000", lw=1.4)
                for m, hd in st["hist"].items():
                    for key in ("obs", "well"):
                        if key in hd:
                            yv = float(np.interp(T_h, th, hd[key] / 1e6))
                            if np.isfinite(yv):
                                ax.plot([T_h], [yv], "o", color=col[m], ms=ctx.base_px * 0.45, mec="white")
                ax.set_xlabel("время после пуска t, ч")
                ax.set_ylabel("давление p, МПа")
                ax.set_xlim(0, p["t_max_h"])
                ax.set_title("p(t): давление во времени", fontsize=ctx.pt(0.95))
                ax.legend(loc="upper right", fontsize=ctx.pt(0.7))
                ax.grid(color=sg["palette"]["grid"], lw=0.5)
            elif v == "plan":
                m = "exact" if "exact" in st["profiles"] else "pssc"
                R = st["rmax"]
                g = np.linspace(-R, R, 240)
                X, Y = np.meshgrid(g, g)
                rr = np.hypot(X, Y) if p["geometry"] == "radial" else np.abs(X)
                rr = np.maximum(rr, st["x"][0])
                P = np.interp(rr, st["x"], st["profiles"][m]) / 1e6
                vmin = min(float(np.nanmin(v_)) for v_ in st["profiles"].values()) / 1e6
                from matplotlib.colors import PowerNorm
                dP = p["p0_mpa"] - P
                im = ax.imshow(dP, extent=[-R, R, -R, R], origin="lower", cmap=pal["cmap"] + "_r",
                               norm=PowerNorm(0.35, vmin=0, vmax=max(p["p0_mpa"] - vmin, 1e-6)))
                lv = [l_ for l_ in (0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5) if l_ < float(dP.max())]
                if lv:
                    cl = ax.contour(X, Y, dP, levels=lv, colors="white", linewidths=0.7)
                    ax.clabel(cl, fmt=lambda v_: f"{v_:g}", fontsize=ctx.pt(0.6))
                ax.set_aspect("equal")
                if p["geometry"] == "radial":
                    ax.add_patch(Circle((0, 0), R * 0.02, color=pal["well_color"], zorder=5))
                    box_px = r[2] * ctx.fig_px[0]
                    f = (R * 0.02 / p["rw_m"])
                    if f > 1.5:
                        exag.append({"what": "скважина на плане", "factor": round(f)})
                    if p["show_front"] and p["method"] in ("pssc", "both"):
                        ax.add_patch(Circle((0, 0), st["front"], fill=False, ec=pal["approx_color"], lw=1.4, ls="-."))
                    del box_px
                else:
                    ax.axvline(0, color=pal["well_color"], lw=3)
                ax.set_xlabel("м")
                ax.set_title("вид сверху: давление", fontsize=ctx.pt(0.95))
                cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
                cb.set_label("снижение давления p₀ − p, МПа", fontsize=ctx.pt(0.75))
        notes = [f"κ = {st['kappa']:.2g} м²/с"]
        return {"exaggerations": exag, "legend": [], "notes": notes, "axes": res_axes}
