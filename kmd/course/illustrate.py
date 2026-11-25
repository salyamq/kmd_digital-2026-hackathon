"""Illustration hook: use the visuals agent's renderer (`kmd.visuals`) when it knows a template,
otherwise the built-in domain-free templates in `kmd.course.figures`.

Expected visuals API (any of these names is accepted, all optional):
  kmd.visuals.catalog() -> list[{template|name, class, provenance, params|doc|description}]
  kmd.visuals.render_illustration(spec: dict, out_dir: Path) -> {file|path, class, provenance, ...}
"""
from __future__ import annotations

import importlib
from pathlib import Path

from . import figures


def _visuals():
    try:
        return importlib.import_module("kmd.visuals")
    except Exception:
        return None


def catalog(domain: str | None = None) -> list[dict]:
    out, seen = [], set()
    v = _visuals()
    fn = getattr(v, "catalog", None) if v else None
    if callable(fn):
        try:
            try:
                items = fn(domain) if domain else fn()
            except TypeError:
                items = fn()
            for it in items or []:
                name = it.get("template") or it.get("name") or it.get("id")
                if not name or name in seen:
                    continue
                if it.get("course") is False:  # template not meant for still illustrations
                    continue
                seen.add(name)
                doc = it.get("params_doc") or it.get("params") or it.get("doc") or it.get("description") or ""
                if not isinstance(doc, str):
                    import json

                    doc = json.dumps(doc, ensure_ascii=False)
                out.append({"template": name, "class": it.get("class", "B"), "provenance": it.get("provenance", "схема"), "params": doc, "source": "visuals"})
        except Exception as e:  # never let a visuals bug kill the course stage
            print(f"[course] visuals.catalog failed: {e}")
    for it in figures.catalog():
        if it["template"] not in seen:
            out.append(it)
    return out


def render(spec: dict, out_dir: Path, stem: str) -> dict:
    """Render one illustration spec. Returns {file, class, provenance, template, renderer} or raises."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = spec.get("template")
    v = _visuals()
    fn = getattr(v, "render_illustration", None) if v else None
    if tpl not in figures.TEMPLATES and callable(fn):
        res = fn(dict(spec, id=stem), out_dir) or {}
        f = res.get("file") or res.get("path") or res.get("svg") or res.get("png")
        if not f:
            raise ValueError(f"visuals returned no file for {tpl}")
        return {
            "file": str(f),
            "class": res.get("class", spec.get("class", "B")),
            "provenance": res.get("provenance", "схема"),
            "template": tpl,
            "renderer": "visuals",
            "alt": res.get("alt"),
        }
    if tpl not in figures.TEMPLATES:
        raise KeyError(f"unknown illustration template: {tpl}")
    r = figures.render(tpl, spec.get("params") or {})
    path = out_dir / f"{stem}.svg"
    path.write_text(r["svg"], encoding="utf-8")
    return {"file": str(path), "class": r["class"], "provenance": r["provenance"], "template": tpl, "renderer": "builtin"}
