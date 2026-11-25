"""Illustration hook: use the visuals stage's renderer (`kmd.visuals`) for its templates and the
built-in domain-free templates in `kmd.course.figures` for the rest.

visuals API used (all optional; the course works without kmd.visuals):
  kmd.visuals.catalog() -> [{name, title, description, class, provenance, params_schema, example, ...}]
  kmd.visuals.catalog_text() -> compact text of the catalog for prompts
  kmd.visuals.render_illustration(spec, out_dir) -> {path, alt, caption, class, provenance, issues, ...}
"""
from __future__ import annotations

import importlib
from pathlib import Path

from . import figures


def _visuals():
    try:
        return importlib.import_module("kmd.visuals")
    except Exception as e:  # pragma: no cover - visuals missing or broken
        print(f"[course] kmd.visuals unavailable: {e}")
        return None


def catalog(domain: str | None = None) -> list[dict]:
    """[{template, class, provenance, source}] — the names the LLM may use."""
    out, seen = [], set()
    v = _visuals()
    if v and callable(getattr(v, "catalog", None)):
        try:
            for it in v.catalog() or []:
                name = it.get("name") or it.get("template")
                if not name or name in seen or it.get("course") is False:
                    continue
                seen.add(name)
                out.append({"template": name, "class": it.get("class", "B"), "provenance": it.get("provenance", "схема"),
                            "title": it.get("title", ""), "source": "visuals"})
        except Exception as e:
            print(f"[course] visuals.catalog failed: {e}")
    for it in figures.catalog():
        if it["template"] not in seen:
            out.append(it)
    return out


def catalog_text(domain: str | None = None) -> str:
    """Catalog description for the course_step prompt."""
    parts = []
    v = _visuals()
    names = {c["template"] for c in catalog(domain) if c["source"] == "visuals"}
    if v and names and callable(getattr(v, "catalog_text", None)):
        try:
            parts.append(v.catalog_text())
        except Exception as e:
            print(f"[course] visuals.catalog_text failed: {e}")
    for it in figures.catalog():
        if it["template"] not in names:
            parts.append(f"### {it['template']}\nКласс {it['class']}, метка «{it['provenance']}». {it['params']}")
    return "\n\n".join(parts)


_SPEC_KEYS = ("template", "params", "caption", "alt", "title", "redrawn_from", "exaggerations", "claim_ids", "class", "provenance", "t", "size")


def render(spec: dict, out_dir: Path, stem: str) -> dict:
    """Render one illustration spec. Returns {file, class, provenance, template, renderer, alt?, caption?, issues}
    or raises (unknown template, invariant violation, bad params)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = spec.get("template")
    if tpl in figures.TEMPLATES:
        r = figures.render(tpl, spec.get("params") or {})
        path = out_dir / f"{stem}.svg"
        path.write_text(r["svg"], encoding="utf-8")
        return {"file": str(path), "class": r["class"], "provenance": r["provenance"], "template": tpl, "renderer": "builtin", "issues": []}
    v = _visuals()
    fn = getattr(v, "render_illustration", None) if v else None
    if not callable(fn):
        raise KeyError(f"unknown illustration template: {tpl}")
    s = {k: spec[k] for k in _SPEC_KEYS if spec.get(k) is not None}
    s["id"] = stem.replace(".", "_")  # visuals derives the file name from id (a dot would be taken as a suffix)
    try:
        res = fn(s, out_dir) or {}
    except Exception as e:
        if "Additional properties" in str(e):  # older/newer spec schema: retry with the core keys
            res = fn({k: s[k] for k in ("id", "template", "params", "caption", "alt") if k in s}, out_dir) or {}
        else:
            raise
    f = res.get("path") or res.get("file")
    if not f:
        raise ValueError(f"visuals returned no file for {tpl}")
    issues = [i for i in (res.get("issues") or []) if (i.get("level") if isinstance(i, dict) else None) in ("error", "critical")]
    return {
        "file": str(f), "class": res.get("class", "B"), "provenance": res.get("provenance", "схема"), "template": tpl,
        "renderer": "visuals", "alt": res.get("alt"), "caption": res.get("caption"), "issues": issues,
        "redrawn_from": res.get("redrawn_from"), "exaggerations": res.get("exaggerations"),
    }
