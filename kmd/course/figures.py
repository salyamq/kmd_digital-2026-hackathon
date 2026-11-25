"""Built-in, domain-free illustration templates (class A/B, deterministic SVG).

They are the fallback when `kmd.visuals` (the visuals agent's renderer) is missing or does not
know a template. Every template draws only the text/numbers passed in `params` (which the
course stage checks against the source), so a figure cannot claim more than the step text.

SVGs use CSS classes (`ill-*`) so the course site can theme them (light/dark); an embedded
<style> gives sane colors when the SVG is opened standalone.
"""
from __future__ import annotations

import html
import math

W = 360  # viewBox width: phone-first (1 unit ~ 1 CSS px on a 390px screen); the site caps the width on desktop

_STYLE = """<style>
.ill-bg{fill:var(--ill-bg,#fff)} .ill-box{fill:var(--ill-box,#f3f5f8);stroke:var(--ill-line,#5b6573);stroke-width:1.5}
.ill-good{fill:var(--ill-good,#d9efe1);stroke:var(--ill-good-line,#2f7d4f)} .ill-bad{fill:var(--ill-bad,#f8dcd8);stroke:var(--ill-bad-line,#b5473a)}
.ill-neutral{fill:var(--ill-neutral,#e6e9ef);stroke:var(--ill-line,#5b6573)} .ill-accent{fill:var(--ill-accent,#dce8f8);stroke:var(--ill-accent-line,#2f5f9e)}
.ill-line{stroke:var(--ill-line,#5b6573);stroke-width:1.5;fill:none} .ill-arrow{fill:var(--ill-line,#5b6573)}
.ill-text{fill:var(--ill-text,#1d2330);font:15px system-ui,sans-serif} .ill-small{fill:var(--ill-muted,#5b6573);font:13px system-ui,sans-serif}
.ill-title{fill:var(--ill-text,#1d2330);font:600 16px system-ui,sans-serif} .ill-label{fill:var(--ill-muted,#5b6573);font:italic 12px system-ui,sans-serif}
.ill-point{fill:var(--ill-accent-line,#2f5f9e)}
</style>"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def wrap(text: str, max_chars: int) -> list[str]:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def _text_block(x, y, text, max_chars, cls="ill-text", lh=19, anchor="middle") -> tuple[str, int]:
    lines = wrap(text, max_chars)
    out = [f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">']
    for i, ln in enumerate(lines):
        out.append(f'<tspan x="{x}" dy="{0 if i == 0 else lh}">{esc(ln)}</tspan>')
    out.append("</text>")
    return "".join(out), len(lines) * lh


def _svg(h: int, body: str, label: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" role="img" aria-label="{esc(title)}" class="ill-svg">'
        f"<title>{esc(title)}</title>{_STYLE}"
        f'<rect class="ill-bg" x="0" y="0" width="{W}" height="{h}" rx="8"/>'
        f"{body}"
        f'<text class="ill-label" x="{W-10}" y="16" text-anchor="end">{esc(label)}</text>'
        "</svg>"
    )


def _arrow(x1, y1, x2, y2) -> str:
    ang = math.atan2(y2 - y1, x2 - x1)
    a1 = (x2 - 9 * math.cos(ang - 0.45), y2 - 9 * math.sin(ang - 0.45))
    a2 = (x2 - 9 * math.cos(ang + 0.45), y2 - 9 * math.sin(ang + 0.45))
    return (
        f'<line class="ill-line" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
        f'<polygon class="ill-arrow" points="{x2:.1f},{y2:.1f} {a1[0]:.1f},{a1[1]:.1f} {a2[0]:.1f},{a2[1]:.1f}"/>'
    )


def tpl_chain(p: dict, label: str) -> str:
    """Cause -> effect chain (vertical boxes with arrows)."""
    items = [str(i) for i in p.get("items", [])][:7]
    title = p.get("title", "")
    y, body = 30, []
    if title:
        t, h = _text_block(W / 2, y + 8, title, 34, "ill-title")
        body.append(t)
        y += h + 14
    bw = W - 24
    for i, it in enumerate(items):
        lines = wrap(it, 36)
        bh = 18 + 19 * len(lines)
        tone = p.get("tones", [None] * len(items))[i] if i < len(p.get("tones", [])) else None
        cls = f"ill-box ill-{tone}" if tone in ("good", "bad", "neutral", "accent") else "ill-box"
        body.append(f'<rect class="{cls}" x="{(W-bw)/2}" y="{y}" width="{bw}" height="{bh}" rx="10"/>')
        t, _ = _text_block(W / 2, y + 24, it, 36)
        body.append(t)
        y += bh
        if i < len(items) - 1:
            body.append(_arrow(W / 2, y + 2, W / 2, y + 26))
            y += 30
    return _svg(y + 16, "".join(body), label, title or " → ".join(items))


def tpl_contrast(p: dict, label: str) -> str:
    """Two cases one above the other (e.g. «хороший раствор» vs «плохой раствор»)."""
    left, right = p.get("left", {}), p.get("right", {})
    title = p.get("title", "")
    y, body = 30, []
    if title:
        t, h = _text_block(W / 2, y + 8, title, 34, "ill-title")
        body.append(t)
        y += h + 14
    for k, side in enumerate((left, right)):
        tone = side.get("tone") or ("good" if k == 0 else "bad")
        cls = f"ill-box ill-{tone}" if tone in ("good", "bad", "neutral", "accent") else "ill-box"
        inner, yy = [], y + 24
        t, h = _text_block(W / 2, yy, side.get("title", ""), 34, "ill-title")
        inner.append(t)
        yy += h + 6
        for pt in side.get("points", [])[:6]:
            t, h = _text_block(26, yy, "• " + str(pt), 38, "ill-text", anchor="start")
            inner.append(t)
            yy += h + 4
        bh = yy - y + 4
        body.append(f'<rect class="{cls}" x="12" y="{y}" width="{W-24}" height="{bh}" rx="10"/>')
        body.extend(inner)
        y += bh + 10
    if p.get("verdict"):
        t, h = _text_block(W / 2, y + 12, p["verdict"], 40, "ill-small")
        body.append(t)
        y += h + 10
    return _svg(y + 8, "".join(body), label, title or f"{left.get('title','')} / {right.get('title','')}")


def _scale(v, lo, hi, a, b, log=False):
    if log:
        lo, hi, v = math.log10(lo), math.log10(hi), math.log10(max(v, 1e-12))
    return a + (v - lo) / (hi - lo) * (b - a) if hi != lo else a


def tpl_ranges(p: dict, label: str) -> str:
    """Numeric axis with book ranges/thresholds (e.g. «оптимально 4–8», «плохо ≥ 20»)."""
    ax = p.get("axis", {})
    lo, hi, log = float(ax.get("min", 0)), float(ax.get("max", 1)), bool(ax.get("log", False))
    unit = ax.get("unit") or ""
    title = p.get("title", "")
    x0, x1 = 22, W - 22
    y, body = 30, []
    if title:
        t, h = _text_block(W / 2, y + 8, title, 34, "ill-title")
        body.append(t)
        y += h + 16
    bar_y = y + 26
    rows = p.get("ranges", [])
    for i, r in enumerate(rows):
        a = _scale(float(r["from"]), lo, hi, x0, x1, log)
        b = _scale(float(r["to"]), lo, hi, x0, x1, log)
        tone = r.get("tone", "neutral")
        ry = bar_y + i * 48
        body.append(f'<rect class="ill-box ill-{tone}" x="{a:.1f}" y="{ry}" width="{max(b-a,4):.1f}" height="16" rx="4"/>')
        lab = str(r.get("label", ""))
        half = min(len(lab) * 4.2, (x1 - x0) / 2)
        tx = min(max((a + b) / 2, x0 + half), x1 - half)
        body.append(f'<text class="ill-text" x="{tx:.1f}" y="{ry-6}" text-anchor="middle">{esc(lab)}</text>')
    axis_y = bar_y + max(len(rows), 1) * 48 - 14
    body.append(f'<line class="ill-line" x1="{x0}" y1="{axis_y}" x2="{x1}" y2="{axis_y}"/>')
    ticks = ax.get("ticks") or sorted({float(r["from"]) for r in rows} | {float(r["to"]) for r in rows} | {lo, hi})
    for tv in ticks:
        tx = _scale(float(tv), lo, hi, x0, x1, log)
        body.append(f'<line class="ill-line" x1="{tx:.1f}" y1="{axis_y-5}" x2="{tx:.1f}" y2="{axis_y+5}"/>')
        body.append(f'<text class="ill-small" x="{tx:.1f}" y="{axis_y+22}" text-anchor="middle">{esc(_fmt(tv))}</text>')
    for m in p.get("marks", []):
        tx = _scale(float(m["value"]), lo, hi, x0, x1, log)
        body.append(f'<line class="ill-line" stroke-dasharray="4 3" x1="{tx:.1f}" y1="{bar_y-6}" x2="{tx:.1f}" y2="{axis_y}"/>')
        body.append(f'<text class="ill-small" x="{tx:.1f}" y="{bar_y-10}" text-anchor="middle">{esc(m.get("label",""))}</text>')
    body.append(f'<text class="ill-small" x="{W/2}" y="{axis_y+44}" text-anchor="middle">{esc(ax.get("label",""))}{", " + esc(unit) if unit else ""}{" (лог. шкала)" if log else ""}</text>')
    return _svg(axis_y + 58, "".join(body), label, title or ax.get("label", ""))


def tpl_decision(p: dict, label: str) -> str:
    """Signs -> rule -> outcomes (decision on data), stacked for narrow screens."""
    title = p.get("title", "")
    y, body = 30, []
    if title:
        t, h = _text_block(W / 2, y + 8, title, 34, "ill-title")
        body.append(t)
        y += h + 14

    def box(y, text, tone, cls="ill-text"):
        lines = wrap(text, 38)
        bh = 14 + 19 * len(lines)
        body.append(f'<rect class="ill-box ill-{tone}" x="12" y="{y}" width="{W-24}" height="{bh}" rx="8"/>')
        t, _ = _text_block(24, y + 21, text, 38, cls, anchor="start")
        body.append(t)
        return y + bh

    def head(y, text):
        body.append(f'<text class="ill-small" x="14" y="{y+4}">{esc(text)}</text>')
        return y + 12

    y = head(y, "Признаки")
    for s_ in p.get("signs", [])[:5]:
        y = box(y, s_, "accent") + 6
    body.append(_arrow(W / 2, y + 2, W / 2, y + 22))
    y = head(y + 30, "Правило")
    y = box(y, p.get("rule", ""), "neutral") + 4
    outs = p.get("outcomes", [])[:5]
    if outs:
        body.append(_arrow(W / 2, y + 2, W / 2, y + 22))
        y = head(y + 30, "Вывод")
        for o in outs:
            y = box(y, f"{o.get('if', '')} → {o.get('then', '')}", o.get("tone", "neutral")) + 6
    return _svg(y + 12, "".join(body), label, title or p.get("rule", ""))


def tpl_regions2d(p: dict, label: str) -> str:
    """Plane split by constant thresholds into labelled regions, with points (cases)."""
    xa, ya = p.get("x", {}), p.get("y", {})
    xlo, xhi, xlog = float(xa.get("min", 0)), float(xa.get("max", 1)), bool(xa.get("log"))
    ylo, yhi, ylog = float(ya.get("min", 0)), float(ya.get("max", 1)), bool(ya.get("log"))
    title = p.get("title", "")
    top = 30
    body = []
    if title:
        t, h = _text_block(W / 2, top + 8, title, 34, "ill-title")
        body.append(t)
        top += h + 14
    L, R, T, B = 52, W - 12, top, top + 260
    for r in p.get("regions", []):
        rx = [float(v) for v in r.get("x", [xlo, xhi])]
        ry = [float(v) for v in r.get("y", [ylo, yhi])]
        a, b = _scale(rx[0], xlo, xhi, L, R, xlog), _scale(rx[1], xlo, xhi, L, R, xlog)
        c, d = _scale(ry[1], ylo, yhi, B, T, ylog), _scale(ry[0], ylo, yhi, B, T, ylog)
        body.append(f'<rect class="ill-box ill-{r.get("tone","neutral")}" x="{a:.1f}" y="{c:.1f}" width="{b-a:.1f}" height="{d-c:.1f}"/>')
        t, _ = _text_block((a + b) / 2, (c + d) / 2, r.get("label", ""), max(8, int((b - a) / 8.5)), "ill-small")
        body.append(t)
    body.append(f'<line class="ill-line" x1="{L}" y1="{B}" x2="{R}" y2="{B}"/><line class="ill-line" x1="{L}" y1="{T}" x2="{L}" y2="{B}"/>')
    for v in p.get("vlines", []):
        x = _scale(float(v["value"]), xlo, xhi, L, R, xlog)
        body.append(f'<line class="ill-line" stroke-dasharray="5 4" x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{B}"/>')
        body.append(f'<text class="ill-small" x="{x+4:.1f}" y="{T+14}">{esc(v.get("label",""))}</text>')
    for v in p.get("hlines", []):
        yv = _scale(float(v["value"]), ylo, yhi, B, T, ylog)
        body.append(f'<line class="ill-line" stroke-dasharray="5 4" x1="{L}" y1="{yv:.1f}" x2="{R}" y2="{yv:.1f}"/>')
        body.append(f'<text class="ill-small" x="{R-4}" y="{yv-4:.1f}" text-anchor="end">{esc(v.get("label",""))}</text>')
    for tv in xa.get("ticks", [xlo, xhi]):
        x = _scale(float(tv), xlo, xhi, L, R, xlog)
        body.append(f'<text class="ill-small" x="{x:.1f}" y="{B+18}" text-anchor="middle">{esc(_fmt(tv))}</text>')
    for tv in ya.get("ticks", [ylo, yhi]):
        yv = _scale(float(tv), ylo, yhi, B, T, ylog)
        body.append(f'<text class="ill-small" x="{L-6}" y="{yv+4:.1f}" text-anchor="end">{esc(_fmt(tv))}</text>')
    for pt in p.get("points", []):
        x = _scale(float(pt["x"]), xlo, xhi, L, R, xlog)
        yv = _scale(float(pt["y"]), ylo, yhi, B, T, ylog)
        body.append(f'<circle class="ill-point" cx="{x:.1f}" cy="{yv:.1f}" r="6"/>')
        body.append(f'<text class="ill-text" x="{x+9:.1f}" y="{yv-8:.1f}">{esc(pt.get("label",""))}</text>')
    xl = f'{xa.get("label","")}{", " + xa["unit"] if xa.get("unit") else ""}'
    yl = f'{ya.get("label","")}{", " + ya["unit"] if ya.get("unit") else ""}'
    body.append(f'<text class="ill-small" x="{(L+R)/2}" y="{B+40}" text-anchor="middle">{esc(xl)}{" (лог.)" if xlog else ""}</text>')
    body.append(f'<text class="ill-small" x="16" y="{(T+B)/2}" text-anchor="middle" transform="rotate(-90 16 {(T+B)/2})">{esc(yl)}{" (лог.)" if ylog else ""}</text>')
    return _svg(B + 56, "".join(body), label, title or f"{yl} — {xl}")


def _fmt(v) -> str:
    v = float(v)
    s = f"{v:g}"
    return s.replace(".", ",")


TEMPLATES = {
    "chain": {
        "fn": tpl_chain, "class": "B", "provenance": "схема",
        "doc": "Цепочка «причина → следствие» или стадии процесса сверху вниз. params: {title?, items:[2–7 коротких фраз из текста шага], tones?:[good|bad|neutral|accent]}",
    },
    "contrast": {
        "fn": tpl_contrast, "class": "B", "provenance": "схема",
        "doc": "Два случая рядом (условие А против условия Б). params: {title?, left:{title, points:[...], tone?}, right:{title, points:[...], tone?}, verdict?}",
    },
    "ranges": {
        "fn": tpl_ranges, "class": "A", "provenance": "схема",
        "doc": "Числовая ось с диапазонами и порогами ИЗ КНИГИ. params: {title?, axis:{label, unit, min, max, log?, ticks?}, ranges:[{from, to, label, tone:good|bad|neutral|accent}], marks?:[{value, label}]}",
    },
    "decision": {
        "fn": tpl_decision, "class": "B", "provenance": "схема",
        "doc": "Решение на данных: признаки → правило → вывод. params: {title?, signs:[...], rule, outcomes:[{if, then, tone?}]}",
    },
    "regions2d": {
        "fn": tpl_regions2d, "class": "A", "provenance": "схема",
        "doc": "Плоскость двух признаков, разбитая ПОСТОЯННЫМИ порогами на области, с точками-примерами. Только если в книге границы — постоянные пороги (не кривые!). params: {title?, x:{label, unit, min, max, log?, ticks?}, y:{...}, regions:[{label, x:[a,b], y:[c,d], tone}], vlines?:[{value,label}], hlines?:[{value,label}], points?:[{x, y, label}]}",
    },
}


def catalog() -> list[dict]:
    return [{"template": k, "class": v["class"], "provenance": v["provenance"], "params": v["doc"], "source": "builtin"} for k, v in TEMPLATES.items()]


def render(template: str, params: dict) -> dict:
    t = TEMPLATES[template]
    svg = t["fn"](params or {}, t["provenance"])
    return {"svg": svg, "class": t["class"], "provenance": t["provenance"], "template": template}
