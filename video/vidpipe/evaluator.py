"""Generic state-model evaluator.

A scene spec's "model" block says WHAT to compute; this module computes it, with no topic knowledge:

  formula        expression over a grid (any dims), params with units + sources, optional derived params
  pde_diffusion  1D linear/radial diffusion  du/dt = D * Laplacian(u)  (for chapters that give only the PDE)
  las            one curve from a LAS file over a depth window
  csv            columns from a CSV file (optional filter, x-window, date parsing)
  table          small inline table given in the spec (values quoted from the chapter)

Outputs go to 04_models/<shot>.npz (arrays) + <shot>.csv (flattened) + <shot>.json (meta).
"""
import ast
import math
import re
from pathlib import Path

import numpy as np

try:
    import pint
    UREG = pint.UnitRegistry()
    UREG.define("API = [] = GAPI = gAPI")
    UREG.define("fraction = [] = frac = v_v")
    UREG.define("darcy_ = 9.869233e-13 * m**2")
    UREG.define("millidarcy_ = 1e-3 * darcy_")
except Exception:  # pint missing: units must already be SI
    UREG = None

from scipy import special

from .util import write_json

# ------------------------------------------------------------------ safe expression evaluation

SAFE_FUNCS = {
    "exp": np.exp, "log": np.log, "ln": np.log, "log10": np.log10, "sqrt": np.sqrt,
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan, "arcsin": np.arcsin, "arccos": np.arccos,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh, "abs": np.abs,
    "erf": special.erf, "erfc": special.erfc,
    "E1": special.exp1, "exp1": special.exp1,               # exponential integral E1(x) = -Ei(-x)
    "Ei": special.expi, "expi": special.expi,
    "gamma": special.gamma, "besselj0": special.j0, "besselk0": special.k0, "besselk1": special.k1,
    "minimum": np.minimum, "maximum": np.maximum, "clip": np.clip, "where": np.where,
    "heaviside": lambda x: np.heaviside(x, 0.5),
    "smoothstep": lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1)),
    "sign": np.sign, "floor": np.floor, "ceil": np.ceil,
    "cumsum": np.cumsum, "mean": np.mean,
}
SAFE_CONSTS = {"pi": math.pi, "e": math.e, "g": 9.80665}

ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
                 ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Mod, ast.FloorDiv,
                 ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq, ast.IfExp, ast.keyword,
                 ast.BoolOp, ast.And, ast.Or, ast.Tuple, ast.List)


class ExprError(ValueError):
    pass


def normalize_expr(expr):
    """Accept common math spellings: '^' power, '·' and '×' multiply, unicode minus."""
    s = str(expr).strip()
    for a, b in (("^", "**"), ("·", "*"), ("×", "*"), ("−", "-"), ("–", "-"), ("÷", "/")):
        s = s.replace(a, b)
    if "=" in s and not any(op in s for op in ("==", "<=", ">=", "!=")):
        s = s.split("=", 1)[1]          # 'dp = Q*mu/...' -> right-hand side
    return s


def check_expr(expr, names):
    """Raise ExprError if the expression uses anything outside the whitelist."""
    tree = ast.parse(normalize_expr(expr), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise ExprError(f"forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCS:
                raise ExprError(f"unknown function: {ast.unparse(node.func)}")
        if isinstance(node, ast.Name) and node.id not in names and node.id not in SAFE_FUNCS \
                and node.id not in SAFE_CONSTS:
            raise ExprError(f"unknown symbol: {node.id}")
    return tree


def safe_eval(expr, env):
    names = set(env)
    tree = check_expr(expr, names)
    code = compile(tree, "<expr>", "eval")
    scope = {"__builtins__": {}}
    scope.update(SAFE_FUNCS)
    scope.update(SAFE_CONSTS)
    scope.update(env)
    with np.errstate(all="ignore"):
        return eval(code, scope)  # noqa: S307 - AST whitelisted above


def expr_symbols(expr):
    tree = ast.parse(normalize_expr(expr), mode="eval")
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(SAFE_FUNCS) - set(SAFE_CONSTS))


# ------------------------------------------------------------------ units

UNIT_NAMES = {
    "м": "m", "см": "cm", "мм": "mm", "км": "km", "мкм": "micrometer", "µm": "micrometer", "μm": "micrometer",
    "сут": "day", "d": "day", "ч": "hour", "h": "hour", "hr": "hour", "мин": "minute", "с": "s", "сек": "s",
    "Па": "Pa", "кПа": "kPa", "МПа": "MPa", "ГПа": "GPa", "атм": "atm", "ат": "at", "бар": "bar", "кгс": "kgf",
    "Д": "darcy_", "мД": "millidarcy_", "D": "darcy_", "mD": "millidarcy_", "md": "millidarcy_",
    "cP": "centipoise", "cp": "centipoise", "сП": "centipoise", "мПа": "mPa", "т": "tonne", "кг": "kg",
    "г": "g", "Н": "N", "кН": "kN", "МН": "MN", "л": "liter", "stb": "bbl", "STB": "bbl", "Sm": "m",
    "K": "kelvin", "градС": "degC", "°C": "degC",
}


def norm_unit(unit):
    u = str(unit).strip().replace("·", "*").replace("×", "*").replace("^", "**").replace("⋅", "*")
    u = u.replace("²", "2").replace("³", "3")

    def tok(m):
        name, exp = m.group(1), m.group(2)
        name = UNIT_NAMES.get(name, name)
        return name + (f"**{exp}" if exp else "")
    # a unit token optionally followed by an integer exponent (m3, м2, cm3) unless already '**'
    return re.sub(r"([A-Za-zА-Яа-яЁёµμ°_]+)(\d?)", tok, u)


def to_si(value, unit):
    """Convert value [unit] to SI base units. Returns (si_value, si_unit_str)."""
    if unit in (None, "", "-", "1", "dimensionless", "д.ед.", "доли", "fraction"):
        return float(value), ""
    if UREG is None:
        return float(value), unit
    q = UREG.Quantity(float(value), norm_unit(unit)).to_base_units()
    return float(q.magnitude), f"{q.units:~}"


def from_si(array, unit):
    """Convert an SI array to a display unit (e.g. Pa -> bar)."""
    if not unit or UREG is None:
        return array
    factor = to_si(1.0, unit)[0]
    return np.asarray(array) / factor


# ------------------------------------------------------------------ grids

def make_axis(g):
    lo, hi, n = float(g["from"]), float(g["to"]), int(g.get("n", 200))
    unit = g.get("unit")
    lo_si, _ = to_si(lo, unit)
    hi_si, _ = to_si(hi, unit)
    if g.get("scale", "lin") == "log":
        return np.geomspace(lo_si, hi_si, n)
    return np.linspace(lo_si, hi_si, n)


# ------------------------------------------------------------------ model types

def eval_formula(model):
    params_si, meta = {}, {}
    for name, p in (model.get("params") or {}).items():
        if isinstance(p, dict):
            v, u = to_si(p["value"], p.get("unit"))
        else:
            v, u = float(p), ""
        params_si[name] = v
        meta[name] = {"si_value": v, "si_unit": u}
    env = dict(params_si)
    for name, expr in (model.get("derived") or {}).items():
        env[name] = float(np.asarray(safe_eval(expr, env)))
        meta[name] = {"si_value": env[name], "derived_from": expr}
    grid = model.get("grid") or {}
    axes = {k: make_axis(g) for k, g in grid.items()}
    names = list(axes)
    mesh = np.meshgrid(*[axes[k] for k in names], indexing="ij") if names else []
    env.update({k: m for k, m in zip(names, mesh)})
    out = np.asarray(safe_eval(model["expr"], env), dtype=float)
    if names and out.shape != tuple(len(axes[k]) for k in names):
        out = np.broadcast_to(out, tuple(len(axes[k]) for k in names)).copy()
    oname = (model.get("output") or {}).get("name", "u")
    res = {oname: out}
    for name, expr in (model.get("exprs") or {}).items():     # extra outputs on the same grid (e.g. one per time)
        o = np.asarray(safe_eval(expr, env), dtype=float)
        res[name] = np.broadcast_to(o, out.shape).copy() if o.shape != out.shape else o
    res.update({f"axis_{k}": v for k, v in axes.items()})
    return res, {"params": meta, "axes": names, "output": oname, "exprs": list(model.get("exprs") or {})}


def eval_pde_diffusion(model):
    """Implicit finite differences for du/dt = D/x^a d/dx(x^a du/dx), a=0 linear, a=1 radial.

    inner_bc: {"type":"flux","value":expr}  -> -x^a * D * du/dx = value  at x0  (e.g. constant-rate well)
              {"type":"value","value":expr}
    outer_bc: {"type":"value","value":expr} (default 0 change) or {"type":"flux","value":0}
    """
    env = {}
    for name, p in (model.get("params") or {}).items():
        env[name] = to_si(p["value"], p.get("unit"))[0] if isinstance(p, dict) else float(p)
    for name, expr in (model.get("derived") or {}).items():
        env[name] = float(np.asarray(safe_eval(expr, env)))
    x = make_axis(model["grid"]["x"])
    t_out = make_axis(model["grid"]["t"])
    D = float(np.asarray(safe_eval(str(model["coef"]), env)))
    a = 1 if model.get("geometry", "linear") == "radial" else 0
    u0 = float(np.asarray(safe_eval(str(model.get("initial", 0)), env)))
    n = len(x)
    u = np.full(n, u0)
    xs = np.maximum(x, 1e-12)
    xf = 0.5 * (xs[1:] + xs[:-1])        # faces
    dx = np.diff(xs)
    vol = np.empty(n)
    vol[1:-1] = 0.5 * (xs[2:] - xs[:-2])
    vol[0], vol[-1] = 0.5 * dx[0], 0.5 * dx[-1]
    w = xs ** a
    wf = xf ** a
    ib = model.get("inner_bc", {"type": "flux", "value": 0})
    ob = model.get("outer_bc", {"type": "value", "value": u0})
    out = np.empty((n, len(t_out)))
    t_prev = 0.0
    # sub-steps between output times (log-spaced outputs need fine early steps)
    for j, t_next in enumerate(t_out):
        nsub = 20
        for dt in np.diff(np.linspace(t_prev, t_next, nsub + 1)):
            A = np.zeros((n, n))
            b = w * vol * u / dt
            for i in range(n):
                A[i, i] = w[i] * vol[i] / dt
            for i in range(n - 1):
                c = D * wf[i] / dx[i]
                A[i, i] += c; A[i, i + 1] -= c
                A[i + 1, i + 1] += c; A[i + 1, i] -= c
            if ib["type"] == "flux":
                b[0] += float(np.asarray(safe_eval(str(ib["value"]), env)))
            else:
                A[0, :] = 0; A[0, 0] = 1; b[0] = float(np.asarray(safe_eval(str(ib["value"]), env)))
            if ob["type"] == "value":
                A[-1, :] = 0; A[-1, -1] = 1; b[-1] = float(np.asarray(safe_eval(str(ob["value"]), env)))
            u = np.linalg.solve(A, b)
        out[:, j] = u
        t_prev = t_next
    oname = (model.get("output") or {}).get("name", "u")
    return {oname: out, "axis_x": x, "axis_t": t_out}, {"axes": ["x", "t"], "output": oname, "D": D}


def eval_las(model, base_dirs=()):
    import lasio
    import warnings
    warnings.filterwarnings("ignore")
    f = _resolve(model["file"], base_dirs)
    las = lasio.read(str(f))
    depth = np.asarray(las.index, dtype=float)
    val = np.asarray(las[model["curve"]], dtype=float)
    lo = float(model.get("depth_from", np.nanmin(depth)))
    hi = float(model.get("depth_to", np.nanmax(depth)))
    m = (depth >= lo) & (depth <= hi) & np.isfinite(val)
    meta = {"file": str(f), "curve": model["curve"], "unit": las.curves[model["curve"]].unit,
            "well": str(las.well.WELL.value) if "WELL" in las.well else "", "n": int(m.sum()),
            "depth_unit": las.index_unit}
    extra = {}
    for c in model.get("also", []):
        extra[c] = np.asarray(las[c], dtype=float)[m]
    return {"depth": depth[m], "value": val[m], **extra}, meta


def eval_csv(model, base_dirs=()):
    import pandas as pd
    f = _resolve(model["file"], base_dirs)
    df = pd.read_csv(f)
    for col, v in (model.get("filter") or {}).items():
        df = df[df[col] == v]
    x = model["x"]
    if model.get("parse_dates") or "date" in x.lower():
        df[x] = pd.to_datetime(df[x])
        if "x_from" in model:
            df = df[df[x] >= pd.to_datetime(model["x_from"])]
        if "x_to" in model:
            df = df[df[x] <= pd.to_datetime(model["x_to"])]
        df = df.sort_values(x)
        xv = (df[x] - df[x].iloc[0]).dt.total_seconds().to_numpy() / 86400.0   # days from start
        res = {"x": xv, "x_dates": np.array(df[x].dt.strftime("%Y-%m-%d").tolist(), dtype="U10")}
    else:
        if "x_from" in model:
            df = df[df[x] >= float(model["x_from"])]
        if "x_to" in model:
            df = df[df[x] <= float(model["x_to"])]
        df = df.sort_values(x)
        res = {"x": df[x].to_numpy(dtype=float)}
    for y in model["y"] if isinstance(model["y"], list) else [model["y"]]:
        res[f"y_{y}"] = pd.to_numeric(df[y], errors="coerce").to_numpy(dtype=float)
    for c in model.get("also", []):
        res[f"c_{c}"] = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
    return res, {"file": str(f), "rows": len(df), "x": x, "y": model["y"]}


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", ".").replace("\u2009", "").replace(" ", ""))


def eval_table(model):
    """Small table quoted from the chapter: {columns: [...], rows: [[...]], labels?: [...], source: {page, quote}}.
    Cells may be written as in the book ('0,7'); they are verified against the page text in QA."""
    cols = model["columns"]
    rows = model["rows"]
    res = {c: np.array([_num(r[i]) for r in rows], dtype=float) for i, c in enumerate(cols)}
    if model.get("labels"):
        res["labels"] = np.array([str(x) for x in model["labels"]], dtype="U80")
    return res, {"columns": cols, "n": len(rows)}


def _resolve(file, base_dirs):
    p = Path(file)
    if p.exists():
        return p
    for b in base_dirs:
        q = Path(b) / file
        if q.exists():
            return q
        hits = list(Path(b).rglob(Path(file).name))
        if hits:
            return hits[0]
    raise FileNotFoundError(f"dataset file not found: {file}")


def evaluate(model, base_dirs=()):
    t = model.get("type", "formula")
    if t == "formula":
        return eval_formula(model)
    if t == "pde_diffusion":
        return eval_pde_diffusion(model)
    if t == "las":
        return eval_las(model, base_dirs)
    if t == "csv":
        return eval_csv(model, base_dirs)
    if t == "table":
        return eval_table(model)
    raise ValueError(f"unknown model type: {t}")


def run_model(model, out_stem, base_dirs=()):
    arrays, meta = evaluate(model, base_dirs)
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(str(out_stem) + ".npz", **{k: v for k, v in arrays.items()
                                                  if getattr(v, "dtype", None) is not None and v.dtype != object})
    # flat CSV for humans / mentors
    try:
        import pandas as pd
        one_d = {k: v for k, v in arrays.items() if np.ndim(v) == 1}
        lens = {len(v) for v in one_d.values()}
        if len(lens) == 1:
            pd.DataFrame(one_d).to_csv(str(out_stem) + ".csv", index=False)
    except Exception:
        pass
    summary = {k: {"shape": list(np.shape(v)),
                   "min": float(np.nanmin(v)) if np.size(v) and np.issubdtype(np.asarray(v).dtype, np.number) else None,
                   "max": float(np.nanmax(v)) if np.size(v) and np.issubdtype(np.asarray(v).dtype, np.number) else None}
               for k, v in arrays.items()}
    write_json(str(out_stem) + ".json", {"model": model, "meta": meta, "arrays": summary})
    return arrays, meta


def load_model_output(out_stem):
    p = Path(str(out_stem) + ".npz")
    if not p.exists():
        return None
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}
