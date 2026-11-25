"""State models shared by templates (and therefore by illustrations AND video frames).

Everything here is plain numerics: no drawing. Each function documents its physics and
its simplifications; the simplifications are echoed into scene specs as `assumptions`.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import special
from scipy.ndimage import gaussian_filter1d

# ----------------------------------------------------------------------------------------
# 1. Petrophysical forward model for a layered column (synthetic well logs)
# ----------------------------------------------------------------------------------------

PETRO_ASSUMPTIONS = [
    "Синтетические кривые рассчитаны из модели пласта (не реальная скважина).",
    "Сопротивление: формула Арчи (a=1, m=2, n=2) с параллельной проводимостью глинистой части.",
    "ПС: статическая амплитуда −K·lg(ρф/ρв), K≈70 мВ, ослаблена глинистостью; против непроницаемых пород аномалии нет.",
    "Кривые сглажены по вертикальному разрешению прибора; тонкие пласты читаются хуже.",
    "Кабельный каротаж записывается при подъёме прибора.",
]

# vertical resolution (Gaussian sigma, m) per curve id
RESOLUTION_M = {"GR": 0.30, "SP": 0.9, "CALI": 0.05, "BIT": 0.0, "RD": 0.8, "RS": 0.25,
                "MNOR": 0.05, "MINV": 0.05, "NPHI": 0.3, "NGK": 0.3, "RHOB": 0.2, "DT": 0.3}


def _layer_props(layer: dict, lith_table: dict, glob: dict) -> dict:
    lt = lith_table.get(layer.get("lith", "generic")) or lith_table.get("generic") or {}
    props = dict(lt.get("props", {}))
    phi = layer.get("phi", props.get("phi", 0.1))
    vsh = layer.get("vsh", props.get("vsh", 0.2))
    fluid = layer.get("fluid") or "water"
    perm_default = bool(props.get("reservoir", False)) and phi >= 0.06 and vsh < 0.5
    permeable = layer.get("permeable", perm_default)
    if layer.get("lith") in ("shale",):
        permeable = False
    sw = layer.get("sw")
    if sw is None:
        sw = {"water": 1.0, "oil": glob["sw_oil"], "gas": glob["sw_gas"]}.get(fluid, 1.0)
    if not permeable:
        sw = 1.0 if layer.get("sw") is None else sw
    sxo = 1.0 if sw >= 0.999 else 1.0 - glob["sor"]  # flushed zone keeps residual hydrocarbons
    return dict(phi=phi, vsh=vsh, fluid=fluid, permeable=permeable, sw=sw, sxo=sxo,
                rho_ma=props.get("rho_ma", 2.65), dt_ma=props.get("dt_ma", 180),
                rt_fixed=layer.get("rt", props.get("rt")), cave=props.get("cave", False),
                gr_clean=props.get("gr", 15.0), lith=layer.get("lith", "generic"))


def _archie_r(rw, phi, sw, a=1.0, m=2.0, n=2.0, vsh=0.0, rsh=3.0):
    phi = max(phi, 1e-3)
    c_clean = (phi ** m) * (max(sw, 1e-3) ** n) / (a * rw)
    c = (1 - vsh) * c_clean + vsh / rsh
    return 1.0 / max(c, 1e-6)


def synth_logs(layers: list[dict], lith_table: dict, fluids: dict, *, rw=0.05, rmf=0.5, rm=0.6,
               bit_mm=216.0, mudcake_mm=10.0, cave_mm=40.0, sw_oil=0.25, sw_gas=0.20, sor=0.2,
               gr_shale=120.0, ssp_k=70.0, dz=0.05, top=None, base=None, noise=0.0, seed=7) -> dict:
    """Synthetic logs on a regular depth grid.

    Returns {"depth": z, "curves": {id: array}, "props": per-sample dict arrays, "layers": normalized}.
    """
    glob = dict(sw_oil=sw_oil, sw_gas=sw_gas, sor=sor)
    layers = sorted(layers, key=lambda l: l["top"])
    z0 = layers[0]["top"] if top is None else top
    z1 = layers[-1]["base"] if base is None else base
    z = np.arange(z0, z1 + dz / 2, dz)
    n = len(z)
    rsh = (lith_table.get("shale", {}).get("props", {}) or {}).get("rt", 3.0)
    ssp = -ssp_k * math.log10(max(rmf, 1e-4) / max(rw, 1e-4))
    raw = {k: np.zeros(n) for k in ("GR", "SP", "CALI", "BIT", "RD", "RS", "MNOR", "MINV", "NPHI", "NGK", "RHOB", "DT")}
    perm = np.zeros(n, dtype=bool)
    lith_idx = np.full(n, -1)
    norm_layers = []
    for i, L in enumerate(layers):
        p = _layer_props(L, lith_table, glob)
        norm_layers.append({**L, **{k: p[k] for k in ("phi", "vsh", "fluid", "permeable", "sw")}})
        sel = (z >= L["top"]) & (z < L["base"] + (dz / 2 if i == len(layers) - 1 else 0))
        lith_idx[sel] = i
        perm[sel] = p["permeable"]
        hc = p["fluid"] if p["fluid"] in ("oil", "gas") and p["sw"] < 0.999 else None
        rho_hc = fluids.get(hc, {}).get("density_g_cc", 0.8) if hc else 1.0
        hi_hc = fluids.get(hc, {}).get("hydrogen_index", 1.0) if hc else 1.0
        phi, vsh = p["phi"], p["vsh"]
        raw["GR"][sel] = p["gr_clean"] + vsh * (gr_shale - p["gr_clean"])
        raw["SP"][sel] = ssp * (1 - vsh) if p["permeable"] else 0.0
        raw["BIT"][sel] = bit_mm
        if p["permeable"]:
            raw["CALI"][sel] = bit_mm - 2 * mudcake_mm
        elif p["cave"]:
            raw["CALI"][sel] = bit_mm + cave_mm
        else:
            raw["CALI"][sel] = bit_mm
        if p["rt_fixed"] is not None and not p["permeable"]:
            rt = float(p["rt_fixed"])
            rxo = rt
        else:
            rt = _archie_r(rw, phi, p["sw"], vsh=vsh, rsh=rsh)
            rxo = _archie_r(rmf, phi, p["sxo"], vsh=vsh, rsh=rsh) if p["permeable"] else rt
        raw["RD"][sel] = rt
        raw["RS"][sel] = rxo
        if p["permeable"]:
            rmc = 1.5 * rm
            raw["MINV"][sel] = rmc
            raw["MNOR"][sel] = 0.5 * rmc + 0.5 * min(rxo, 4 * rmc) + 0.6 * rmc
        else:
            v = min(rt, 30.0) if p["vsh"] < 0.5 else rt
            raw["MINV"][sel] = v
            raw["MNOR"][sel] = v * 0.97
        nphi_sh = 0.35
        nphi = phi * (p["sxo"] + (1 - p["sxo"]) * hi_hc) + vsh * nphi_sh
        raw["NPHI"][sel] = nphi
        raw["NGK"][sel] = 9.5 * np.exp(-4.2 * nphi) + 0.3
        rho_f = 1.0 * p["sxo"] + rho_hc * (1 - p["sxo"])
        raw["RHOB"][sel] = (1 - phi) * p["rho_ma"] + phi * rho_f
        raw["DT"][sel] = (1 - phi) * p["dt_ma"] + phi * 620.0
    out = {}
    rng = np.random.default_rng(seed)
    for k, arr in raw.items():
        sig = RESOLUTION_M.get(k, 0.2) / dz
        logk = k in ("RD", "RS", "MNOR", "MINV")
        a = np.log(np.maximum(arr, 1e-3)) if logk else arr.astype(float)
        if sig > 0:
            a = gaussian_filter1d(a, sig, mode="nearest")
        if noise and k not in ("BIT",):
            a = a + noise * (np.std(a) + (0.05 if logk else 1e-3)) * rng.standard_normal(n) * 0.3
        out[k] = np.exp(a) if logk else a
    return {"depth": z, "curves": out, "permeable": perm, "lith_idx": lith_idx, "layers": norm_layers,
            "ssp": ssp}


# ----------------------------------------------------------------------------------------
# 2. Pressure diffusion (elastic / piezoconductive flow), exact + ПССС approximations
# ----------------------------------------------------------------------------------------

def ei_neg(x):
    """-Ei(-x) = E1(x), x > 0 (the exponential integral used in the line-source solution)."""
    return special.exp1(np.maximum(x, 1e-300))


def diffusion_exact(geom: str, bc: str, x, t, *, kappa, p0, q=None, pw=None, k=None, mu=None,
                    h=None, B=None, rw=0.1):
    """Exact solutions of the piezoconductivity equation dp/dt = kappa * Laplacian(p), SI units.

    geom: "linear" (half-space, gallery at x=0) | "radial" (infinite reservoir, well at r=0)
    bc:   "const_pressure" (pw at the gallery/well) | "const_rate" (q, m3/s)
      linear+const_pressure: p = pw + (p0-pw) erf(x / 2sqrt(kt))
      linear+const_rate:     p = p0 - (q mu/(k B h)) [2 sqrt(kt/pi) e^{-x^2/4kt} - x erfc(x/2sqrt(kt))]
      radial+const_rate:     p = p0 - (q mu / 4 pi k h) E1(r^2/4kt)   (line source, main formula)
      radial+const_pressure: numerical (implicit finite differences on log-r grid).
    """
    x = np.asarray(x, dtype=float)
    t = max(float(t), 1e-9)
    s = 2 * math.sqrt(kappa * t)
    if geom == "linear" and bc == "const_pressure":
        return pw + (p0 - pw) * special.erf(x / s)
    if geom == "linear" and bc == "const_rate":
        c = q * mu / (k * B * h)
        return p0 - c * (s / math.sqrt(math.pi) * np.exp(-(x / s) ** 2) - x * special.erfc(x / s))
    if geom == "radial" and bc == "const_rate":
        return p0 - q * mu / (4 * math.pi * k * h) * ei_neg(x ** 2 / (4 * kappa * t))
    if geom == "radial" and bc == "const_pressure":
        return radial_const_pressure_fd(x, t, kappa=kappa, p0=p0, pw=pw, rw=rw)
    raise ValueError(f"unsupported {geom}/{bc}")


def radial_const_pressure_fd(r, t, *, kappa, p0, pw, rw, n=400):
    """Implicit FD on a log grid u=ln r for dp/dt = kappa/r^2 * d2p/du2 (radial diffusion)."""
    r = np.asarray(r, dtype=float)
    rmax = max(float(np.max(r)) * 3, rw + 20 * math.sqrt(kappa * t) + 10)
    u = np.linspace(math.log(rw), math.log(rmax), n)
    du = u[1] - u[0]
    rr = np.exp(u)
    p = np.full(n, float(p0))
    p[0] = pw
    nsteps = 200
    # geometric time steps resolve the early fast change
    times = np.geomspace(max(t * 1e-6, 1e-6), t, nsteps)
    tprev = 0.0
    from scipy.linalg import solve_banded
    for tn in times:
        dt = tn - tprev
        tprev = tn
        a = kappa * dt / (rr ** 2 * du ** 2)
        ab = np.zeros((3, n))
        ab[1, :] = 1 + 2 * a
        ab[0, 1:] = -a[:-1]
        ab[2, :-1] = -a[1:]
        rhs = p.copy()
        ab[1, 0], ab[0, 1], rhs[0] = 1, 0, pw
        ab[1, -1], ab[2, -2], rhs[-1] = 1, 0, p0
        p = solve_banded((1, 1), ab, rhs)
    return np.interp(r, rr, p, left=pw, right=p0)


def pssc_front(geom: str, bc: str, t, *, kappa, rw=0.1):
    """Radius/length of the perturbed zone by the method of successive steady states (ПССС).

    linear+const_rate: l = sqrt(2 kappa t);  linear+const_pressure: l = 2 sqrt(kappa t);
    radial+const_rate: R = sqrt(rw^2 + 4 kappa t);
    radial+const_pressure: from the material balance, solved numerically.
    """
    t = np.asarray(t, dtype=float)
    if geom == "linear" and bc == "const_rate":
        return np.sqrt(2 * kappa * t)
    if geom == "linear" and bc == "const_pressure":
        return 2 * np.sqrt(kappa * t)
    if geom == "radial" and bc == "const_rate":
        return np.sqrt(rw ** 2 + 4 * kappa * t)
    if geom == "radial" and bc == "const_pressure":
        # Q dt = beta* d[V dp_mean]; V=pi(R^2-rw^2)h, dp_mean = dpc/(2 ln(R/rw)), Q = 2 pi k h dpc/(mu ln(R/rw))
        # => 4 kappa dt = ln(R/rw) d[(R^2-rw^2)/ln(R/rw)]  -> integrate numerically in R.
        Rg = rw * np.geomspace(1.0001, 1e7, 4000)
        F = (Rg ** 2 - rw ** 2) / np.log(Rg / rw)
        dF = np.gradient(F, Rg)
        integrand = np.log(Rg / rw) * dF / (4 * kappa)
        tg = np.concatenate([[0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(Rg))])
        return np.interp(t, tg, Rg)
    raise ValueError(f"unsupported {geom}/{bc}")


def diffusion_pssc(geom: str, bc: str, x, t, *, kappa, p0, q=None, pw=None, k=None, mu=None, h=None,
                   B=None, rw=0.1):
    """Pressure profile by ПССС: steady-state profile inside the perturbed zone, p0 outside."""
    x = np.asarray(x, dtype=float)
    L = float(pssc_front(geom, bc, t, kappa=kappa, rw=rw))
    if geom == "linear":
        if bc == "const_rate":
            c = q * mu / (k * B * h)
            p = p0 - c * (L - x)
        else:
            p = pw + (p0 - pw) * x / max(L, 1e-9)
    else:
        if bc == "const_rate":
            p = p0 - q * mu / (2 * math.pi * k * h) * np.log(L / np.maximum(x, rw))
        else:
            p = pw + (p0 - pw) * np.log(np.maximum(x, rw) / rw) / max(math.log(L / rw), 1e-9)
    return np.where(x >= L, p0, p)


def well_rate_const_pressure(geom: str, t, *, kappa, p0, pw, k, mu, h, B=None, rw=0.1, method="exact"):
    """Rate for a constant-pressure gallery (exact eq. Q = k/mu (p0-pw) B h / sqrt(pi kappa t))."""
    t = np.maximum(np.asarray(t, dtype=float), 1e-9)
    if geom == "linear":
        if method == "exact":
            return k / mu * (p0 - pw) * B * h / np.sqrt(math.pi * kappa * t)
        return k / mu * (p0 - pw) * B * h / pssc_front("linear", "const_pressure", t, kappa=kappa)
    R = pssc_front("radial", "const_pressure", t, kappa=kappa, rw=rw)
    return 2 * math.pi * k * h * (p0 - pw) / (mu * np.log(R / rw))


# ----------------------------------------------------------------------------------------
# 3. Hydrostatics in a well (for the drilling domain): mud column, gas kick
# ----------------------------------------------------------------------------------------

G = 9.81


def hydrostatic(depth_m, rho_kg_m3, p_surface=0.0):
    return p_surface + rho_kg_m3 * G * np.asarray(depth_m, dtype=float)


def gas_kick_migration(depth_bubble, *, well_depth, rho_mud, p_bottom_initial, v_bubble0, shut_in: bool,
                       p_atm=0.101e6):
    """Gas bubble rising in a well (isothermal ideal gas, incompressible mud, no slip losses).

    shut_in=True (closed well): bubble volume ~ constant -> bubble keeps its bottom pressure,
      wellhead and bottom pressures rise as it migrates up.
    shut_in=False (open well): bubble pressure = hydrostatic above it -> expands (Boyle), most near surface.
    Returns dict(p_bubble, volume, p_wellhead, p_bottom).
    """
    if shut_in:
        pb = p_bottom_initial
        vol = v_bubble0
        p_wh = pb - rho_mud * G * depth_bubble
        p_bot = pb + rho_mud * G * (well_depth - depth_bubble)
        return dict(p_bubble=pb, volume=vol, p_wellhead=max(p_wh, 0.0), p_bottom=p_bot)
    pb = p_atm + rho_mud * G * depth_bubble
    vol = v_bubble0 * p_bottom_initial / pb
    return dict(p_bubble=pb, volume=vol, p_wellhead=0.0, p_bottom=p_atm + rho_mud * G * well_depth)
