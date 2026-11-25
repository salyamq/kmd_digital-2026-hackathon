"""Redraw book figures by code: figure scan -> (vision LLM) template params -> SVG «перерисовано по рис. N, стр. M».

For every figure of the layer with role example/problem or redraw=true:
  1. crop the figure from the PDF page (embedded image bbox, 300 dpi) + the whole page image,
  2. LLM (`scene_redraw`, images attached) digitizes it into params of a catalog template,
  3. code checks: template invariants + control points from the chapter's worked examples
     (the redrawn chart must give the author's answer), one repair round with the errors,
  4. render runs/<ch>/illustrations/redraw_<fig>.svg + redraw_<fig>.json (result contract below).

Contract for the course stage (runs/<ch>/illustrations/redraws.json):
  [{figure, page, node_ids, path, file, alt, caption, class, provenance, redrawn_from:{figure,page},
    template, approximations, checks:[{source, ok, found, expected}], status: ok|errors|infeasible, errors}]
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import llm
from ..config import chapter_config, read_json, run_dir, write_json


def _fig_key(n) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-я.]+", "_", str(n)).strip("_")


def figure_uses(layer: dict) -> dict:
    """figure number -> {figure, uses:[node context]} for figures that need a redraw."""
    out: dict = {}
    for n in layer["nodes"]:
        for f in n.get("figures", []):
            if not (f.get("redraw") or f.get("role") in ("example", "problem")):
                continue
            num = str(f.get("number"))
            num_re = re.compile(r"рис\.?\s*" + re.escape(num) + r"(?!\d)", re.I)
            ent = out.setdefault(num, {"figure": f, "uses": []})
            exs = [e for e in n.get("worked_examples", []) if num_re.search(" ".join(
                [e.get("title", ""), e.get("condition", ""), " ".join(e.get("steps", [])), e.get("result", "")]))]
            if not exs:
                exs = n.get("worked_examples", []) if f.get("role") == "example" else []
            probs = [b for b in n.get("book_problems", []) if num_re.search(b.get("text", "")) or str(b.get("figure")) == num]
            cl = [c for c in n.get("claims", []) if num_re.search(c.get("text", "") + " " + c.get("quote", ""))]
            ent["uses"].append({"node_id": n["id"], "title": n.get("title_beginner", ""),
                                "examples": [{"title": e.get("title", ""), "page": e.get("page"), "condition": e.get("condition", ""),
                                              "result": e.get("result", "")} for e in exs],
                                "problems": [{"number": b.get("number"), "page": b.get("page"), "text": b.get("text", "")}
                                             for b in probs],
                                "claims": [{"text": c["text"], "page": c.get("page")} for c in cl][:6]})
    return out


def crop_figures(cfg: dict, page: int, out_dir: Path, dpi: int = 300) -> list[Path]:
    """Crops of the raster figures on a PDF page (largest first)."""
    import pymupdf

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = cfg["book"].get("pdf_path")
    if not pdf or not Path(pdf).exists():
        return []
    doc = pymupdf.open(pdf)
    if not (1 <= page <= len(doc)):
        return []
    pg = doc[page - 1]
    rects = [pymupdf.Rect(i["bbox"]) for i in pg.get_image_info()]
    rects = [r for r in rects if r.width > 60 and r.height > 60]
    rects.sort(key=lambda r: -r.width * r.height)
    paths = []
    for i, r in enumerate(rects[:3]):
        p = out_dir / f"p{page}_fig{i + 1}.png"
        if not p.exists():
            pg.get_pixmap(dpi=dpi, clip=r + (-4, -4, 4, 4)).save(p)
        paths.append(p)
    return paths


def _point_in_poly(x, y, poly, xlog=False, ylog=False) -> bool:
    import math

    def tx(v):
        return math.log10(v) if xlog else v

    def ty(v):
        return math.log10(v) if ylog else v

    px, py = tx(x), ty(y)
    pts = [(tx(a), ty(b)) for a, b in poly]
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def verify_checks(ans: dict) -> list[dict]:
    res = []
    if ans.get("template") != "crossplot":
        return [{"source": c.get("source"), "ok": None, "note": "проверка точек только для crossplot"} for c in ans.get("checks", [])]
    p = ans.get("params", {})
    xlog = (p.get("x") or {}).get("scale") == "log"
    ylog = (p.get("y") or {}).get("scale") == "log"
    for c in ans.get("checks", []):
        found = [r["label"] for r in p.get("regions", []) if len(r.get("polygon", [])) >= 3 and
                 _point_in_poly(c["x"], c["y"], r["polygon"], xlog, ylog)]
        exp = c["expected_region"].strip().lower()
        ok = any(exp in f.lower() or f.lower() in exp for f in found)
        res.append({"source": c["source"], "x": c["x"], "y": c["y"], "expected": c["expected_region"], "found": found, "ok": ok})
    return res


def redraw_one(rd: Path, cfg: dict, num: str, ent: dict, units: list[dict], lang: str = "русский") -> dict:
    from . import catalog_text, check, render_illustration

    f = ent["figure"]
    page = int(f.get("page") or 0)
    tmp = rd / "tmp" / "figs"
    imgs = crop_figures(cfg, page, tmp)
    pg_img = rd / "pages" / f"p{page}.png"
    if pg_img.exists():
        imgs.append(pg_img)
    ftxt = " ".join(u["text"] for u in units if str(u.get("figure_no")) == num and u.get("kind") == "figure")
    names = ["crossplot", "log_plot", "cross_section", "plan_map", "comparison_bar", "timeline_growth"]
    v = {"figure": {"number": num, "page": page, "caption": f.get("caption", "")}, "figure_text": ftxt,
         "uses": ent["uses"], "catalog": catalog_text(names=names), "course_language_name": lang}
    task = f"redraw.fig{_fig_key(num)}"
    ans = llm.complete_json(rd, task, "scene_redraw", v, schema="redraw", images=imgs)
    errors = _errors(ans, check)
    if errors:
        v2 = dict(v)
        v2["figure_text"] = (ftxt + "\n\nПРЕДЫДУЩАЯ ПОПЫТКА НЕ ПРОШЛА ПРОВЕРКУ КОДОМ:\n" + "\n".join(f"- {e}" for e in errors)
                             + "\nИсправь параметры (полигоны областей, шкалы, точки).")
        ans = llm.complete_json(rd, task + ".fix1", "scene_redraw", v2, schema="redraw", images=imgs)
        errors = _errors(ans, check)
    rec = {"figure": num, "page": page, "node_ids": [u["node_id"] for u in ent["uses"]],
           "redrawn_from": {"figure": num, "page": page}, "template": ans.get("template"),
           "approximations": ans.get("approximations", []), "checks": verify_checks(ans) if ans.get("feasible") else [],
           "errors": errors}
    if not ans.get("feasible"):
        rec.update(status="infeasible", reason=ans.get("reason"))
        return rec
    if any("invariant" in e or "schema" in e for e in errors):
        rec["status"] = "errors"
        return rec
    spec = {"id": f"redraw_{_fig_key(num)}", "template": ans["template"], "params": ans["params"],
            "title": ans.get("title", ""), "caption": ans["caption"], "alt": ans["alt"],
            "redrawn_from": {"figure": num, "page": page}, "size": "tall" if ans["template"] == "log_plot" else "wide"}
    try:
        r = render_illustration(spec, rd / "illustrations")
    except Exception as e:  # noqa: BLE001
        rec.update(status="errors", errors=errors + [f"render: {e}"])
        return rec
    rec.update({k: r[k] for k in ("path", "alt", "caption", "class", "provenance", "exaggerations")})
    rec["file"] = Path(r["path"]).name
    rec["status"] = "ok" if not errors else "errors"
    write_json(rd / "illustrations" / f"redraw_{_fig_key(num)}.json", rec)
    return rec


def _errors(ans: dict, check) -> list[str]:
    if not ans.get("feasible"):
        return []
    errs = []
    try:
        for i in check(ans["template"], ans["params"]):
            if i["level"] == "error":
                errs.append(f"invariant [{i['code']}]: {i['message']}")
    except Exception as e:  # noqa: BLE001
        errs.append(f"schema: {str(e).splitlines()[0][:300]}")
        return errs
    for c in verify_checks(ans):
        if c.get("ok") is False:
            errs.append(f"контрольная точка {c['source']} ({c['x']}, {c['y']}) попала в {c['found'] or 'никакую область'}, "
                        f"а у автора — «{c['expected']}»")
    return errs


def run(chapter: str, node: str | None = None, figures: list[str] | None = None, **kw) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    layer = read_json(rd / "layer.json")
    units = read_json(rd / "units.json")["units"] if (rd / "units.json").exists() else []
    figs = figure_uses(layer)
    if node:
        figs = {k: v for k, v in figs.items() if any(u["node_id"] == node for u in v["uses"])}
    if figures:
        figs = {k: v for k, v in figs.items() if k in figures}
    pending, index = [], []
    for num, ent in figs.items():
        try:
            rec = redraw_one(rd, cfg, num, ent, units)
        except llm.PendingLLM as p:
            pending.append(p.path)
            continue
        index.append(rec)
        print(f"[redraw] рис. {num}: {rec['status']} {rec.get('file', '')} {rec.get('errors') or ''}")
    if index:
        old = read_json(rd / "illustrations" / "redraws.json") if (rd / "illustrations" / "redraws.json").exists() else []
        keep = [o for o in old if o["figure"] not in {r["figure"] for r in index}]
        write_json(rd / "illustrations" / "redraws.json", keep + index)
    return pending
