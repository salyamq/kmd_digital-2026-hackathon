"""Checker module: review another team's draft package (bookmarks) against the chapter source.

    kmd check PACKAGE_DIR_OR_JSON --chapter CH [--out findings.json]

Pipeline: load package (tolerant) -> flatten to items -> code checks (quotes/pages, numbers, frame class
rules) -> retrieve source passages per item -> LLM review in batches (prompts/check_review.md) ->
post-filter for precision (evidence quote must be found in the chapter) -> findings.json.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import llm
from ..config import chapter_config, domain_pack, read_json, run_dir, write_json
from ..verify import check_text_numbers, clear_cache, find_quote, normalize
from .load import load_package, flatten

BATCH = 10
ERROR_TYPES = ["overgeneralization", "sign_flip", "measured_vs_derived", "lost_condition", "missing_caveat",
               "wrong_scaling_law", "wrong_mechanism", "wrong_number", "outdated_as_current",
               "it_analogy_without_limit", "frame_error", "misconception", "unsupported"]
REVIEW_SCHEMA = {
    "type": "object", "required": ["reviews"],
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "required": ["id", "verdict", "error_type", "severity", "explanation", "fix", "page", "evidence_quote"],
        "properties": {
            "id": {"type": "string"}, "verdict": {"enum": ["ok", "error", "unsure"]},
            "error_type": {"anyOf": [{"enum": ERROR_TYPES}, {"type": "null"}]},
            "severity": {"enum": [1, 2, 3, None]}, "explanation": {"type": "string"},
            "fix": {"type": ["string", "null"]}, "page": {"type": ["integer", "null"]},
            "evidence_quote": {"type": ["string", "null"]},
        }}}},
}

# frames: generated classes must not assert facts (TZ "Правила генерации", class C/D)
_FACT_WORDS = re.compile(r"керн|шлиф|разрез|схем|кривая|каротаж|график|диаграмм|цифр|числ|надпис|подпис|шкал|ось|логотип", re.I)


def _stem_tokens(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[а-яёa-z]{4,}", normalize(text))}


def retrieve(item: dict, units: list[dict], k: int = 3, max_chars: int = 900) -> list[dict]:
    """Top-k source units by stem overlap (+ bonus for the page the item refers to)."""
    q = _stem_tokens(item["text"] + " " + (item.get("quote") or ""))
    scored = []
    for u in units:
        if u["kind"] in ("heading", "fragment") or u.get("ocr_suspect"):
            continue
        t = _stem_tokens(u["text"])
        if not t:
            continue
        s = len(q & t) / (len(q) ** 0.5 * len(t) ** 0.3 + 1e-9)
        if item.get("page") and item["page"] in (u["page"], u.get("page_end", u["page"])):
            s *= 1.5
        scored.append((s, u))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, u in scored[:k]:
        txt = u["text"]
        if len(txt) > max_chars:  # keep the window with most overlap
            best, bi = -1, 0
            for i in range(0, len(txt) - max_chars + 1, 150):
                sc = len(q & _stem_tokens(txt[i:i + max_chars]))
                if sc > best:
                    best, bi = sc, i
            txt = ("…" if bi else "") + txt[bi:bi + max_chars] + "…"
        out.append({"page": u["page"], "text": txt.replace("\n", " ")})
    return out


def code_checks(item: dict, chapter: str) -> tuple[list[dict], list[str]]:
    """Deterministic findings + notes passed to the LLM as hints."""
    findings, notes = [], []
    q = item.get("quote")
    if q:
        r = find_quote(q, item.get("page"), chapter)
        if not r["found"] and r["where"] and r["where"].startswith("other:"):
            findings.append({"target_id": item["id"], "error_type": "wrong_page", "severity": 1,
                             "message": f"цитата находится на стр. {r['page']}, а не на стр. {item.get('page')}",
                             "fix": f"стр. {r['page']}", "page": r["page"], "evidence_quote": q[:200],
                             "source": "code", "subtype": "wrong_page"})
            notes.append(f"цитата найдена на стр. {r['page']}, а не {item.get('page')}")
        elif not r["found"]:
            notes.append(f"цитата не найдена в главе дословно (лучшее совпадение {r['score']:.0f}%) — возможно, искажена")
    bad = check_text_numbers(item["text"], chapter)
    if bad:
        notes.append(f"числа, которых нет в тексте главы: {', '.join(bad)}")
    if item["type"] == "frame":
        cls, prov, desc = item.get("class"), (item.get("provenance") or "").lower(), item["text"]
        asserted = re.sub(r"\bбез\s+[^.;]*", "", desc, flags=re.I)  # "без надписей и цифр" is not a fact
        if cls in ("C", "D") and "ии" in prov and _FACT_WORDS.search(asserted):
            findings.append({"target_id": item["id"], "error_type": "frame_error", "severity": 3,
                             "message": "сгенерированный кадр (класс C/D) содержит фактическое содержание (разрез/кривая/керн/надписи)",
                             "fix": "сделать кадр классом A/B детерминированной графикой или убрать факты из генерации",
                             "page": None, "evidence_quote": None, "source": "code"})
        if cls == "A" and prov and "реальн" not in prov and "данн" not in prov:
            notes.append("кадр класса A (данные) помечен не как «реальные данные»")
        if cls == "B" and "реальн" in prov:
            notes.append("кадр класса B (процесс, расчёт) помечен как «реальные данные»")
    return findings, notes


def run_check(package: Path, chapter: str, out: str | None = None) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    clear_cache()
    pack = domain_pack(cfg.get("domain", "geology"))
    pkg = load_package(Path(package))
    items = flatten(pkg)
    units = read_json(rd / "units.json")["units"]
    code_findings = []
    for it in items:
        f, notes = code_checks(it, cfg["id"])
        code_findings += f
        it["code_notes"] = "; ".join(notes)
        it["sources"] = retrieve(it, units)
    mis = pack.get("misconceptions", {})
    mis = mis.get("items", mis) if isinstance(mis, dict) else mis
    b = cfg.get("book", {})
    base = {
        "domain_name": pack.get("pack", {}).get("name", ""),
        "misconceptions": mis,
        "physics_checklist": pack.get("physics_checklist", ""),
        "chapter_title": cfg.get("title", ""),
        "book": f"{b.get('author', '')}, «{b.get('title', '')}»",
    }
    pkg_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", pkg.get("package_id", Path(package).stem))
    calls = []
    for i in range(0, len(items), BATCH):
        batch = [{k: it.get(k) for k in ("id", "type", "text", "quote", "page", "code_notes", "sources")} for it in items[i:i + BATCH]]
        calls.append(lambda batch=batch, i=i: llm.complete_json(
            rd, f"check_{pkg_id}_{i // BATCH + 1:02d}", "check_review", {**base, "items": batch}, REVIEW_SCHEMA))
    results, pending = llm.gather(calls)
    if pending:
        return pending
    by_id = {it["id"]: it for it in items}
    findings = list(code_findings)
    dropped = []
    for res in results:
        for rv in res["reviews"]:
            if rv["verdict"] != "error" or rv["id"] not in by_id:
                continue
            ev = rv.get("evidence_quote")
            verified, page = False, rv.get("page")
            if ev:
                r = find_quote(ev, page, cfg["id"], min_score=88)
                if r["found"] or (r["where"] or "").startswith("other:"):
                    verified, page = True, r["page"]
            source_based = rv["error_type"] not in ("frame_error", "it_analogy_without_limit", "misconception",
                                                    "outdated_as_current", "missing_caveat")
            if source_based and not verified:
                # precision guard: a claimed contradiction with the source must be backed by a real quote
                dropped.append({**rv, "reason": "evidence quote not found in chapter"})
                continue
            findings.append({
                "target_id": rv["id"], "error_type": rv["error_type"], "severity": rv["severity"] or 2,
                "message": rv["explanation"], "fix": rv.get("fix"), "page": page,
                "evidence_quote": ev, "evidence_verified": verified, "source": "llm",
            })
    # one finding per target (keep the most severe; llm over code when equal)
    best: dict[str, dict] = {}
    for f in findings:
        cur = best.get(f["target_id"])
        if cur is None or (f["severity"], f["source"] == "llm") > (cur["severity"], cur["source"] == "llm"):
            best[f["target_id"]] = f
    final = sorted(best.values(), key=lambda f: (-f["severity"], f["target_id"]))
    res = {"package_id": pkg.get("package_id"), "chapter": cfg["id"], "items_checked": len(items),
           "findings": final, "dropped_for_precision": dropped}
    outp = Path(out) if out else Path(package if Path(package).is_dir() else Path(package).parent) / "findings.json"
    write_json(outp, res)
    print(f"[check] {pkg.get('package_id')}: {len(items)} items, {len(final)} findings "
          f"({sum(1 for f in final if f['source'] == 'code')} by code), dropped {len(dropped)} -> {outp}")
    return []


def run(chapter: str, **kw) -> list[Path]:  # stage-style entry is not used; see run_check
    return []
