"""Video frame composition: one template view (the scene's world) + overlays in safe zones.

Overlays on every frame: provenance label (top-left), step mini-map (top-right), title, the named
exaggerations / convention (under the view), on-screen key words (≤ 7–8 words, no formulas) and a
prediction badge during the pause. The view itself is drawn by the same template code as the course
illustrations, from the scene's params at state t.
"""
from __future__ import annotations

import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..visuals.base import DrawCtx  # noqa: E402
from ..visuals.illustrate import exaggeration_text, get_template  # noqa: E402
from ..visuals.style import provenance_badge, setup_rc, styleguide  # noqa: E402

LAYOUT = {
    # fractions of the frame (x0, y0, w, h); y from the bottom. Short keeps the bottom 12 % and top 5 % free
    # (platform UI safe zones); captions sit above the bottom safe zone.
    "short": {"size": (1080, 1920), "base_px": 38, "view": (0.13, 0.235, 0.845, 0.615), "caption_y": 0.13,
              "caption_w": 0.86, "caption_px": 60, "notes_y": 0.872, "top_y": 0.955, "title_y": 0.922,
              "chars": 26},
    "long": {"size": (1920, 1080), "base_px": 24, "view": (0.075, 0.29, 0.89, 0.56), "caption_y": 0.075,
             "caption_w": 0.80, "caption_px": 50, "notes_y": 0.19, "top_y": 0.965, "title_y": 0.905,
             "chars": 52},
}


class Composer:
    def __init__(self, scene: dict, fmt: str, domain: str = "geology"):
        self.scene = scene
        self.fmt = fmt
        self.L = LAYOUT[fmt]
        self.sg = styleguide(domain)
        self.domain = domain
        self.frames = {f["id"]: f for f in scene["frames"]}
        self.order = [f["id"] for f in scene["frames"]]

    def view_params(self, frame: dict) -> tuple:
        v = self.scene["views"][frame["view"]]
        tpl = get_template(v["template"])
        p = dict(v["params"])
        p.update(frame.get("params_override") or {})
        p["_domain"] = self.domain
        p = tpl.normalize(p)
        p["title"] = ""  # the frame title is drawn by the composer
        return tpl, p

    def render(self, out_path, frame_id: str, t: float, caption: str = "", overlay: str | None = None,
               step_index: int | None = None, dpi: int = 100) -> dict:
        L = self.L
        W, H = L["size"]
        setup_rc(self.sg, base_px=L["base_px"], dpi=dpi)
        fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi)
        fr = self.frames[frame_id]
        tpl, p = self.view_params(fr)
        ctx = DrawCtx(sg=self.sg, dpi=dpi, base_px=L["base_px"], mode="video", fig_px=(W, H))
        res = tpl.draw(fig, list(L["view"]), p, t, ctx) or {}
        # top bar: provenance + step mini-map
        prov = fr.get("provenance") or tpl.provenance_for(p)
        provenance_badge(fig, self.sg, prov, size_px=L["base_px"] * 1.15, dpi=dpi, xy=(0.035, L["top_y"]))
        self._minimap(fig, step_index if step_index is not None else self.order.index(frame_id), W, H, dpi)
        title = self.scene.get("title", "")
        if title:
            fig.text(0.5, L["title_y"], "\n".join(textwrap.wrap(title, L["chars"] + 8)), ha="center", va="top",
                     fontsize=L["base_px"] * 1.15 * 72 / dpi, fontweight="bold", color="#1A1A1A")
        # notes: exaggerations (computed + scene) and convention
        ex = list(res.get("exaggerations", []))
        if fr.get("true_scale"):
            ex = [e for e in ex if "вертикаль" not in e.get("what", "")]
        ex_txt = exaggeration_text(ex) if ex else ""
        if fr.get("true_scale") and not ex:
            ex_txt = "истинный масштаб — без преувеличения"
        notes = [n for n in res.get("notes", []) if n]
        y = L["notes_y"]
        if self.fmt == "short" and notes:
            ex_txt = " · ".join([x for x in [ex_txt] if x])
        if ex_txt:
            fig.text(0.5, y, ex_txt, ha="center", va="center", fontsize=L["base_px"] * 0.8 * 72 / dpi,
                     color="#B71C1C", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#B71C1C", lw=1.2))
        if notes:
            fig.text(0.5, y - (0.021 if self.fmt == "short" else 0.035), " · ".join(notes), ha="center",
                     va="center", fontsize=L["base_px"] * 0.66 * 72 / dpi, color="#616161")
        # on-screen key words
        if caption:
            lines = textwrap.wrap(caption, L["chars"])
            bg = "#E65100" if overlay == "predict" else "#1A237E"
            fig.text(0.5, L["caption_y"], "\n".join(lines), ha="center", va="center",
                     fontsize=L["caption_px"] * 72 / dpi, fontweight="bold", color="#FFFFFF", linespacing=1.15,
                     bbox=dict(boxstyle="round,pad=0.45,rounding_size=0.8", fc=bg, ec="none", alpha=0.95))
        if overlay == "predict":
            fig.text(0.5, L["caption_y"] - (0.062 if self.fmt == "short" else 0.06), "? пауза: подумайте",
                     ha="center", va="center", fontsize=L["base_px"] * 0.95 * 72 / dpi, color="#E65100",
                     fontweight="bold")
        fig.savefig(out_path, dpi=dpi)
        plt.close(fig)
        return {"exaggerations": ex, "provenance": prov, "class": fr.get("class"), "template": tpl.name}

    def _minimap(self, fig, k: int, W, H, dpi):
        n = len(self.order)
        L = self.L
        x1 = 0.965
        step = (0.032 if self.fmt == "short" else 0.018)
        x0 = x1 - step * (n - 1)
        y = L["top_y"] - 0.008
        for i in range(n):
            col = "#E65100" if i == k else ("#37474F" if i < k else "#BDBDBD")
            fig.patches.append(matplotlib.patches.Circle((x0 + i * step, y), 0.0085 if self.fmt == "short" else 0.006,
                                                         transform=fig.transFigure, fc=col, ec="none",
                                                         figure=fig))
        fig.text(x0 - 0.02, y, f"шаг {k + 1} из {n}", ha="right", va="center",
                 fontsize=L["base_px"] * 0.7 * 72 / dpi, color="#616161")


def frame_stats(img_path) -> dict:
    """Small helper for tests: fraction of non-white pixels."""
    from PIL import Image

    a = np.asarray(Image.open(img_path).convert("L"))
    return {"ink": float((a < 245).mean())}
