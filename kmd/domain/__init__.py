"""`kmd domain new <id> --from-chapter CH`: draft a domain pack for a new domain with the LLM (timed).

Engine-wide parts (8 difficulty types, formats, video criteria) are copied from the base pack
(`domains/geology/difficulty_types.yaml`) and enriched with per-domain hints; domain knowledge (glossary,
misconceptions, physics checklist, IT bridges, stress dictionary) is drafted from the chapter text.
Timing and provenance go to domains/<id>/BUILD.json (the TZ asks for the time to build the pack).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import yaml

from .. import llm
from ..config import DOMAINS, chapter_config, domain_pack, read_json, run_dir, write_json

BASE = "geology"
TEXT_BUDGET = 24000

S = {"type": "string"}
SCHEMA = {
    "type": "object",
    "required": ["glossary", "misconceptions", "physics_checklist", "it_bridges", "stress_dict", "pack", "difficulty_hints"],
    "properties": {
        "glossary": {"type": "array", "items": {"type": "object", "required": ["term", "en", "definition"],
                     "properties": {"term": S, "en": {"type": ["string", "null"]}, "definition": S,
                                    "aliases": {"type": "array", "items": S}, "source": S}}},
        "misconceptions": {"type": "array", "items": {"type": "object", "required": ["text", "correction"],
                           "properties": {"text": S, "correction": S, "keywords": {"type": "array", "items": S}}}},
        "physics_checklist": S,
        "it_bridges": {"type": "array", "items": {"type": "object", "required": ["concept", "analogy", "breaks_where"],
                       "properties": {"concept": S, "analogy": S, "breaks_where": S, "difficulty": {"type": "array", "items": S}}}},
        "stress_dict": {"type": "array", "items": {"type": "object", "required": ["term", "kind", "say", "expansion"],
                        "properties": {"term": S, "kind": {"enum": ["abbr", "symbol", "stem"]}, "say": S,
                                       "expansion": {"type": ["string", "null"]}, "check_by_ear": {"type": "boolean"}}}},
        "pack": {"type": "object", "required": ["name", "id_prefix", "audience", "data_context"],
                 "properties": {"name": S, "id_prefix": {"type": "string", "pattern": "^[a-z]{2,5}$"}, "audience": S,
                                "data_context": {"type": "object"}}},
        "difficulty_hints": {"type": "object"},
    },
}


def chapter_digest(units: list[dict], budget: int = TEXT_BUDGET) -> str:
    """Headings in full, paragraphs truncated so that the whole chapter fits the budget."""
    texts = [u for u in units if u["kind"] not in ("fragment",) and not u.get("ocr_suspect")]
    total = sum(len(u["text"]) for u in texts) or 1
    ratio = min(1.0, budget / total)
    out = []
    for u in texts:
        t = u["text"].replace("\n", " ")
        if u["kind"] == "heading":
            out.append(t)
            continue
        lim = max(min(160, budget // max(1, len(texts))), int(len(t) * ratio))
        out.append(f"[стр. {u['page']}] " + (t if len(t) <= lim else t[:lim] + "…"))
    return "\n".join(out)


def new_domain(domain: str, from_chapter: str) -> list[Path]:
    t0 = time.time()
    cfg = chapter_config(from_chapter)
    rd = run_dir(from_chapter)
    units_p = rd / "units.json"
    if not units_p.exists():
        from .. import ingest

        ingest.run(from_chapter)
    units = read_json(units_p)["units"]
    base = domain_pack(BASE)
    dt = base.get("difficulty_types", {})
    b = cfg.get("book", {})
    variables = {
        "difficulty_types": dt.get("types", {}),
        "domain": domain,
        "chapter_title": cfg.get("title", ""),
        "book": f"{b.get('author', '')}, «{b.get('title', '')}»",
        "text": chapter_digest(units),
    }
    try:
        res = llm.complete_json(rd, f"domain_new_{domain}", "domain_new", variables, SCHEMA)
    except llm.PendingLLM as p:
        return [p.path]
    write_pack(domain, res, base, cfg)
    elapsed = time.time() - t0
    build = {
        "domain": domain, "from_chapter": cfg["id"], "base_pack": BASE,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "wall_seconds_last_run": round(elapsed, 1),
        "llm_requests": 1, "llm_provider": llm.provider_name(),
        "note": "LLM answer time is not included when the queue provider is used; see the cache file timestamps.",
    }
    bp = DOMAINS / domain / "BUILD.json"
    if bp.exists():
        old = read_json(bp)
        build["first_built_at"] = old.get("first_built_at", old.get("built_at"))
    else:
        build["first_built_at"] = build["built_at"]
    write_json(bp, build)
    print(f"[domain] {domain}: pack written to {DOMAINS / domain} in {elapsed:.1f}s "
          f"({len(res['glossary'])} terms, {len(res['misconceptions'])} misconceptions)")
    return []


def write_pack(domain: str, res: dict, base: dict, cfg: dict) -> None:
    d = DOMAINS / domain
    d.mkdir(parents=True, exist_ok=True)
    p = res["pack"]
    base_meta = base.get("pack", {})
    pack = {
        "id": domain, "name": p["name"], "id_prefix": p["id_prefix"], "language": cfg.get("language", "ru"),
        "source_languages": ["ru", "en"], "audience": p.get("audience") or base_meta.get("audience"),
        "voice": base_meta.get("voice"), "data_context": p.get("data_context", {}),
        "drafted_by": "kmd domain new (LLM draft; review marked items)", "drafted_from_chapter": cfg["id"],
    }
    (d / "pack.yaml").write_text(yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8")
    dt = json.loads(json.dumps(base.get("difficulty_types", {})))
    for code, hint in (res.get("difficulty_hints") or {}).items():
        if code in dt.get("types", {}) and hint:
            dt["types"][code]["domain_examples"] = hint
    (d / "difficulty_types.yaml").write_text(yaml.safe_dump(dt, allow_unicode=True, sort_keys=False), encoding="utf-8")
    write_json(d / "glossary.json", {"about": f"Глоссарий RU/EN домена {domain} (черновик LLM по главе {cfg['id']}).",
                                     "items": res["glossary"]})
    mis = [{"id": f"mc{i + 1:02d}", "source": "model", **m} for i, m in enumerate(res["misconceptions"])]
    write_json(d / "misconceptions.json", {"about": "Черновик заблуждений (LLM).", "items": mis})
    general = (DOMAINS / BASE / "physics_checklist.md").read_text(encoding="utf-8") if (DOMAINS / BASE / "physics_checklist.md").exists() else ""
    gen_part = general.split("## Флюиды и пласт")[0] if general else ""
    (d / "physics_checklist.md").write_text(
        f"# Чек-лист корректности: {p['name']}\n\n(Черновик LLM по главе {cfg['id']}; общие пункты — из базового пакета.)\n\n"
        + res["physics_checklist"].strip() + "\n\n## Общие пункты (из базового пакета)\n" + gen_part.split("\n", 2)[-1],
        encoding="utf-8")
    write_json(d / "it_bridges.json", {"about": "ИТ-мосты (черновик LLM).",
                                       "items": [{"id": f"it{i + 1:02d}", **b} for i, b in enumerate(res["it_bridges"])]})
    base_sd = DOMAINS / BASE / "stress_dict.json"
    about = read_json(base_sd).get("about", "") if base_sd.exists() else ""
    entries = [{**e, "check_by_ear": e.get("check_by_ear", True)} for e in res["stress_dict"]]
    write_json(d / "stress_dict.json", {"version": "1.0", "about": f"Черновик LLM (домен {domain}). " + about,
                                        "entries": entries})
    for f in ("personas.md", "styleguide.json"):
        src = DOMAINS / BASE / f
        if src.exists() and not (d / f).exists():
            shutil.copy(src, d / f)  # inherited; adjust if the domain needs its own
