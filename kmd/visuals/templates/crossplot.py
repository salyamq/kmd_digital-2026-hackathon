"""crossplot: x-y chart for data points, digitized book curves, formulas evaluated by code,
labelled regions (e.g. «коллектор / неколлектор»), threshold lines and a query point.

This is the template for «перерисовано по рис. N, стр. M»: the curves are given as digitized
points (read from the page image elsewhere) or as a formula from the chapter, and redrawn by code.
"""
from __future__ import annotations

import ast
import math

import numpy as np
from matplotlib.patches import Polygon
from scipy import special

from ..base import DrawCtx, Issue, Template, common_props, register

_FUNCS = {"log": np.log, "ln": np.log, "log10": np.log10, "exp": np.exp, "sqrt": np.sqrt, "abs": np.abs,
          "erf": special.erf, "erfc": special.erfc, "E1": special.exp1, "sin": np.sin, "cos": np.cos,
          "tanh": np.tanh, "minimum": np.minimum, "maximum": np.maximum}
_CONST = {"pi": math.pi, "e": math.e}
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant, ast.Add, ast.Sub,
            ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Mod)


def safe_eval(expr: str, x: np.ndarray, extra: dict | None = None) -> np.ndarray:
    """Evaluate a formula of x with a whitelist of numpy functions (no attribute access, no builtins)."""
    tree = ast.parse(expr.replace("^", "**"), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError(f"недопустимая конструкция в формуле: {type(node).__name__}")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _FUNCS):
            raise ValueError("недопустимая функция в формуле")
    env = {"x": x, **_FUNCS, **_CONST, **(extra or {})}
    with np.errstate(all="ignore"):
        return np.asarray(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env), dtype=float)


AXIS = {"type": "object", "required": ["label"],
        "properties": {"label": {"type": "string"}, "unit": {"type": "string", "default": ""},
                       "scale": {"enum": ["linear", "log"], "default": "linear"},
                       "range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                       "invert": {"type": "boolean", "default": False}}}


@register
class Crossplot(Template):
    name = "crossplot"
    title_ru = "График / кроссплот / палетка: точки, оцифрованные кривые, формулы, области"
    description = (
        "Двумерный график: точки данных, кривые (оцифрованные с рисунка книги или из таблицы), кривые по "
        "формуле из главы (вычисляются кодом: x, log, log10, exp, sqrt, erf, erfc, E1), подписанные области "
        "(например «коллектор/неколлектор», «нефть/вода»), пороговые линии и точка запроса («ваш образец»). "
        "Линейные и логарифмические оси. Для перерисовки рисунков книги (палетки, зависимости), "
        "решения на данных (признак → порог → вывод), сравнения зависимостей."
    )
    use_for = ["Ф", "Р", "Пр", "И", "data_practice", "палетка", "зависимость", "перерисовка рисунка"]
    frame_class = "A"
    provenance = "реальные данные"
    animatable = True
    animation = "t∈[0,1]: точка запроса движется по заданному пути / кривые прорисовываются слева направо"
    default_size = (1100, 800)
    params_schema = {
        "type": "object",
        "required": ["x", "y"],
        "properties": {
            **common_props(),
            "x": AXIS, "y": AXIS,
            "series": {"type": "array", "default": [],
                       "items": {"type": "object", "required": ["label", "points"],
                                 "properties": {"label": {"type": "string"},
                                                "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"},
                                                                                       "minItems": 2, "maxItems": 2}},
                                                "kind": {"enum": ["line", "points", "smooth"], "default": "line"},
                                                "color": {"type": "string"}, "dashed": {"type": "boolean", "default": False},
                                                "label_at_end": {"type": "boolean", "default": False,
                                                                 "description": "подписать кривую у её правого конца (шифр кривой), а не в легенде"}}}},
            "functions": {"type": "array", "default": [],
                          "items": {"type": "object", "required": ["label", "expr"],
                                    "properties": {"label": {"type": "string"}, "expr": {"type": "string"},
                                                   "x_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                                                   "color": {"type": "string"}, "dashed": {"type": "boolean", "default": False}}}},
            "regions": {"type": "array", "default": [],
                        "items": {"type": "object", "required": ["label", "polygon"],
                                  "properties": {"label": {"type": "string"},
                                                 "polygon": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                                                 "color": {"type": "string"}}}},
            "hlines": {"type": "array", "default": [], "items": {"type": "object", "required": ["value"],
                                                                  "properties": {"value": {"type": "number"}, "label": {"type": "string"}}}},
            "vlines": {"type": "array", "default": [], "items": {"type": "object", "required": ["value"],
                                                                  "properties": {"value": {"type": "number"}, "label": {"type": "string"}}}},
            "query": {"type": ["object", "null"], "default": None,
                      "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "label": {"type": "string"}}},
            "annotations": {"type": "array", "default": [],
                            "items": {"type": "object", "required": ["x", "y", "text"],
                                      "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "text": {"type": "string"}}}},
        },
    }
    example = {
        "title": "Сопротивление пласта по формуле Арчи при разной водонасыщенности",
        "x": {"label": "пористость", "unit": "д. ед.", "range": [0.05, 0.35]},
        "y": {"label": "сопротивление", "unit": "Ом·м", "scale": "log", "range": [0.1, 1000]},
        "functions": [{"label": "водоносный (Sв = 1)", "expr": "0.05 / x**2"},
                      {"label": "нефтеносный (Sв = 0,25)", "expr": "0.05 / (x**2 * 0.25**2)"}],
        "query": {"x": 0.2, "y": 20, "label": "пласт A"},
        "provenance": "симуляция",
    }

    def provenance_for(self, params):
        if params.get("provenance"):
            return params["provenance"]
        return "реальные данные" if params.get("series") else "симуляция"

    def check(self, params):
        iss = []
        for f in params.get("functions", []):
            try:
                xr = f.get("x_range") or params["x"].get("range") or [0.01, 1]
                y = safe_eval(f["expr"], np.linspace(xr[0], xr[1], 50))
                if not np.any(np.isfinite(y)):
                    iss.append(Issue("error", "expr_nan", f"формула «{f['expr']}» не даёт конечных значений"))
            except Exception as e:  # noqa: BLE001
                iss.append(Issue("error", "expr", f"формула «{f['expr']}»: {e}"))
        for axn in ("x", "y"):
            a = params[axn]
            if a.get("scale") == "log" and a.get("range") and min(a["range"]) <= 0:
                iss.append(Issue("error", "log_range", f"ось {axn}: логарифмическая шкала с неположительной границей"))
        if not params.get("series") and not params.get("functions"):
            iss.append(Issue("warning", "empty", "нет ни точек, ни формул"))
        return iss

    def describe(self, params):
        names = [s["label"] for s in params.get("series", [])] + [f["label"] for f in params.get("functions", [])]
        s = f"График: по горизонтали {params['x']['label']}, по вертикали {params['y']['label']}"
        if names:
            s += "; кривые: " + ", ".join(names)
        if params.get("regions"):
            s += "; области: " + ", ".join(r["label"] for r in params["regions"])
        return s + "."

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        p = params
        ax = fig.add_axes(rect)
        pal = sg["palette"]["series"]
        ci = 0
        frac = 1.0 if t is None else float(t)
        for a, setter in ((p["x"], "x"), (p["y"], "y")):
            if a.get("scale") == "log":
                (ax.set_xscale if setter == "x" else ax.set_yscale)("log")
            if a.get("range"):
                (ax.set_xlim if setter == "x" else ax.set_ylim)(*a["range"])
            lab = a["label"] + (f", {a['unit']}" if a.get("unit") else "")
            (ax.set_xlabel if setter == "x" else ax.set_ylabel)(lab)
            if a.get("invert"):
                (ax.invert_xaxis if setter == "x" else ax.invert_yaxis)()
        for r in p.get("regions", []):
            col = r.get("color") or pal[ci % len(pal)]
            ci += 1
            poly = np.array(r["polygon"], dtype=float)
            ax.add_patch(Polygon(poly, closed=True, fc=col, alpha=0.12, ec=col, lw=1.0))
            cx, cy = poly[:, 0].mean(), poly[:, 1].mean()
            if p["x"].get("scale") == "log":
                cx = float(np.exp(np.log(poly[:, 0]).mean()))
            if p["y"].get("scale") == "log":
                cy = float(np.exp(np.log(poly[:, 1]).mean()))
            ax.text(cx, cy, r["label"], ha="center", va="center", fontsize=ctx.pt(0.85), color=col, fontweight="bold")
        ci = 0
        for s in p.get("series", []):
            col = s.get("color") or pal[ci % len(pal)]
            ci += 1
            pts = np.array(s["points"], dtype=float)
            pts = pts[np.argsort(pts[:, 0])] if s.get("kind") != "points" else pts
            n = max(1, int(math.ceil(len(pts) * frac)))
            q = pts[:n]
            if s.get("kind") == "points":
                ax.scatter(q[:, 0], q[:, 1], s=(ctx.base_px * 0.5) ** 2, color=col, label=s["label"], zorder=4,
                           edgecolors="white", linewidths=0.5)
            else:
                xs, ys = q[:, 0], q[:, 1]
                if s.get("kind") == "smooth" and len(q) >= 4:
                    from scipy.interpolate import PchipInterpolator
                    xx = np.linspace(xs[0], xs[-1], 200)
                    ys = PchipInterpolator(xs, ys)(xx)
                    xs = xx
                lab_end = s.get("label_at_end")
                ax.plot(xs, ys, color=col, lw=2.2, ls="--" if s.get("dashed") else "-",
                        label=None if lab_end else s["label"], zorder=3)
                if lab_end and len(xs):
                    ax.annotate(s["label"], (xs[-1], ys[-1]), xytext=(4, 0), textcoords="offset points", va="center",
                                ha="left", fontsize=ctx.pt(0.72), color=col, annotation_clip=False)
        for f in p.get("functions", []):
            col = f.get("color") or pal[ci % len(pal)]
            ci += 1
            xr = f.get("x_range") or p["x"].get("range") or [0.01, 1]
            if p["x"].get("scale") == "log":
                xx = np.geomspace(xr[0], xr[1], 300)
            else:
                xx = np.linspace(xr[0], xr[1], 300)
            xx = xx[: max(2, int(len(xx) * frac))]
            ax.plot(xx, safe_eval(f["expr"], xx), color=col, lw=2.2, ls="--" if f.get("dashed") else "-",
                    label=f["label"], zorder=3)
        for hl in p.get("hlines", []):
            ax.axhline(hl["value"], color="#616161", lw=1.2, ls="--")
            if hl.get("label"):
                ax.text(ax.get_xlim()[1], hl["value"], hl["label"] + " ", ha="right", va="bottom",
                        fontsize=ctx.pt(0.78), color="#424242")
        for vl in p.get("vlines", []):
            ax.axvline(vl["value"], color="#616161", lw=1.2, ls="--")
            if vl.get("label"):
                ax.text(vl["value"], ax.get_ylim()[1], " " + vl["label"], ha="left", va="top", rotation=90,
                        fontsize=ctx.pt(0.78), color="#424242")
        q = p.get("query")
        if q:
            ax.plot([q["x"]], [q["y"]], marker="*", color="#FFA000", ms=ctx.base_px * 1.3, mec="#212121", zorder=6)
            if q.get("label"):
                ax.annotate(q["label"], (q["x"], q["y"]), xytext=(8, 8), textcoords="offset points",
                            fontsize=ctx.pt(0.85), fontweight="bold", color="#212121")
        for an in p.get("annotations", []):
            ax.annotate(an["text"], (an["x"], an["y"]), xytext=(6, -6), textcoords="offset points",
                        fontsize=ctx.pt(0.78), color="#212121", bbox=dict(fc="white", ec="#BDBDBD", alpha=0.9, pad=2))
        from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

        for a, axis in ((p["x"], ax.xaxis), (p["y"], ax.yaxis)):
            if a.get("scale") == "log":
                axis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0), numticks=12))
                axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
                axis.set_minor_formatter(NullFormatter())
            else:
                axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
        ax.grid(True, which="both", color=sg["palette"]["grid"], lw=0.5)
        if p.get("series") or p.get("functions"):
            ax.legend(fontsize=ctx.pt(0.78), loc="best")
        return {"exaggerations": [], "legend": [], "notes": [], "axes": [ax]}
