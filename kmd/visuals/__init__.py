"""Deterministic visuals: parametric scene templates (class A/B), illustrations, style guide.

Public API (used by the course and video stages):
  catalog(compact=False)                 -> list of templates (name, description, params schema, example)
  catalog_text()                         -> compact Russian text of the catalog for LLM prompts
  render_illustration(spec, out_dir)     -> {path, alt, caption, class, provenance, redrawn_from, ...}
  render(template, params, out, ...)     -> low-level render to svg/png
  check(template, params)                -> list of invariant issues (dicts)
"""
from __future__ import annotations

import json

from .base import REGISTRY, InvariantError, Issue  # noqa: F401
from .illustrate import get_template, render, render_illustration  # noqa: F401


def catalog(compact: bool = False) -> list[dict]:
    from . import templates  # noqa: F401

    return [REGISTRY[k].catalog_entry(compact=compact) for k in sorted(REGISTRY)]


def catalog_text(with_schema: bool = True, names: list[str] | None = None) -> str:
    """Compact text for prompts: one block per template (name, what, when, params schema, example)."""
    out = []
    for e in catalog():
        if names and e["name"] not in names:
            continue
        out.append(f"### {e['name']} — {e['title']}\n{e['description']}\n"
                   f"Класс по умолчанию: {e['class']}, метка: «{e['provenance']}». "
                   f"Для типов: {', '.join(e['use_for'])}."
                   + (f" Анимация: {e['animation']}." if e['animatable'] else ""))
        if with_schema:
            sch = json.loads(json.dumps(e["params_schema"]))
            for k in ("title", "provenance", "frame_class"):
                sch.get("properties", {}).pop(k, None)
            out.append("params schema: " + json.dumps(sch, ensure_ascii=False))
            out.append("example params: " + json.dumps(e["example"], ensure_ascii=False))
    return "\n\n".join(out)


def check(template: str, params: dict) -> list[dict]:
    tpl = get_template(template)
    p = tpl.normalize(params)
    return [i.as_dict() for i in tpl.check(p)]
