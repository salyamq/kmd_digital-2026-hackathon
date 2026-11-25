"""Style guide access + drawing helpers shared by all templates (badges, legends, fonts).

The colors/hatches/curve conventions are NOT defined here: they come from
`domains/<domain>/styleguide.json`. Only generic fallbacks live in this module.
"""
from __future__ import annotations

import functools
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from ..config import DOMAINS  # noqa: E402

DEFAULT_DOMAIN = "geology"

_FALLBACK = {
    "lithology": {"generic": {"ru": "порода", "color": "#CFCFCF", "hatch": "", "props": {}}},
    "fluids": {},
    "curves": {},
    "tracks": {},
    "conventions": {},
    "pressure": {"cmap": "cividis", "initial_color": "#37474F", "approx_color": "#E65100",
                 "exact_color": "#1565C0", "well_color": "#212121"},
    "provenance": {
        "реальные данные": {"color": "#1B5E20", "bg": "#E8F5E9"},
        "симуляция": {"color": "#E65100", "bg": "#FFF3E0"},
        "схема": {"color": "#37474F", "bg": "#ECEFF1"},
        "иллюстрация ИИ": {"color": "#6A1B9A", "bg": "#F3E5F5"},
    },
    "process_chain": {},
    "palette": {"text": "#1A1A1A", "muted": "#616161", "grid": "#DDDDDD", "bg": "#FFFFFF",
                "accent": "#E65100", "accent2": "#1565C0",
                "series": ["#1565C0", "#E65100", "#2E7D32", "#AD1457", "#6A1B9A", "#00838F"]},
    "font": {"family": "DejaVu Sans"},
}


@functools.lru_cache(maxsize=8)
def styleguide(domain: str = DEFAULT_DOMAIN) -> dict:
    """Load the domain style guide merged over generic fallbacks."""
    sg = json.loads(json.dumps(_FALLBACK))
    p = DOMAINS / domain / "styleguide.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        for k, v in d.items():
            if isinstance(v, dict) and isinstance(sg.get(k), dict):
                sg[k].update(v)
            else:
                sg[k] = v
    return sg


def lith(sg: dict, key: str) -> dict:
    return sg["lithology"].get(key) or sg["lithology"].get("generic") or _FALLBACK["lithology"]["generic"]


def fluid_color(sg: dict, key: str | None, default: str = "#BBBBBB") -> str:
    if not key:
        return default
    return sg["fluids"].get(key, {}).get("color", default)


def setup_rc(sg: dict, base_px: float = 14, dpi: float = 100) -> None:
    """Set matplotlib defaults. base_px = font size in output pixels."""
    pt = base_px * 72.0 / dpi
    plt.rcParams.update({
        "font.family": sg.get("font", {}).get("family", "DejaVu Sans"),
        "font.size": pt,
        "axes.titlesize": pt * 1.1,
        "axes.labelsize": pt,
        "xtick.labelsize": pt * 0.9,
        "ytick.labelsize": pt * 0.9,
        "legend.fontsize": pt * 0.9,
        "axes.edgecolor": "#333333",
        "axes.linewidth": 0.8,
        "hatch.linewidth": 0.6,
        "svg.fonttype": "none",
        "axes.unicode_minus": True,
        "figure.facecolor": sg["palette"].get("bg", "#FFFFFF"),
    })


def badge(fig, text: str, xy=(0.012, 0.985), color="#37474F", bg="#ECEFF1", size_px=14, dpi=100,
          ha="left", va="top", zorder=50):
    """Rounded label in figure coordinates (provenance, scale notes, redraw source)."""
    pt = size_px * 72.0 / dpi
    return fig.text(xy[0], xy[1], text, ha=ha, va=va, fontsize=pt, color=color, zorder=zorder,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.6", fc=bg, ec=color, lw=1.0))


def provenance_badge(fig, sg: dict, provenance: str, size_px=14, dpi=100, xy=(0.012, 0.985), ha="left"):
    st = sg["provenance"].get(provenance, {"color": "#37474F", "bg": "#ECEFF1"})
    return badge(fig, provenance, xy=xy, color=st["color"], bg=st["bg"], size_px=size_px, dpi=dpi, ha=ha)


def note(fig, text: str, xy, size_px=12, dpi=100, color="#424242", ha="left", va="bottom", **kw):
    pt = size_px * 72.0 / dpi
    return fig.text(xy[0], xy[1], text, ha=ha, va=va, fontsize=pt, color=color, **kw)


def round_box(ax, x, y, w, h, fc, ec, lw=1.2, r=0.02, zorder=2, transform=None):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw,
                       zorder=zorder, transform=transform or ax.transAxes)
    ax.add_patch(p)
    return p


def px_to_pt(px: float, dpi: float = 100) -> float:
    return px * 72.0 / dpi


def ru_number(v: float, nd: int = 3) -> str:
    """Number with a decimal comma (Russian convention), trimmed."""
    return f"{v:.{nd}g}".replace(".", ",")


def comma_axes(ax) -> None:
    """Decimal comma on the linear axes of ax."""
    from matplotlib.ticker import FuncFormatter

    for axis, sc in ((ax.xaxis, ax.get_xscale()), (ax.yaxis, ax.get_yscale())):
        if sc == "linear":
            axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
        elif sc == "log":
            axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))


def ru_hours(h: float) -> str:
    """Readable rounded time: '≈ 44 мин', '≈ 2,5 ч', '≈ 21 ч'."""
    if h < 1:
        return f"≈ {max(1, round(h * 60))} мин"
    if h < 10:
        return "≈ " + f"{round(h * 2) / 2:g}".replace(".", ",") + " ч"
    return f"≈ {round(h)} ч"
