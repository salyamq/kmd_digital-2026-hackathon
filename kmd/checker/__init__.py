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
FRAME_BATCH = 3
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
    for unit in units:
        if unit["kind"] in ("heading", "fragment") or unit.get("ocr_suspect"):
            continue
        text = unit["text"]
        markers = [(0, unit["page"])] + [(b["offset"], b["page"]) for b in unit.get("page_breaks", [])]
        ends = [offset for offset, _ in markers[1:]] + [len(text)]
        for (start, page), end in zip(markers, ends):
            excerpt = text[start:end].strip()
            tokens = _stem_tokens(excerpt)
            if not tokens:
                continue
            score = len(q & tokens) / (len(q) ** 0.5 * len(tokens) ** 0.3 + 1e-9)
            if item.get("page") == page:
                score *= 1.5
            scored.append((score, page, excerpt))
    scored.sort(key=lambda row: -row[0])
    out = []
    for _, page, txt in scored[:k]:
        if len(txt) > max_chars:  # keep the window with most overlap
            best, bi = -1, 0
            for i in range(0, len(txt) - max_chars + 1, 150):
                sc = len(q & _stem_tokens(txt[i:i + max_chars]))
                if sc > best:
                    best, bi = sc, i
            txt = ("…" if bi else "") + txt[bi:bi + max_chars] + "…"
        out.append({"page": page, "text": txt.replace("\n", " ")})
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


def analysis_brief(chapter: str, weak: int = 8, definitions: int = 15) -> dict | None:
    """Short context from the organizers' book analysis (not author text; hints only)."""
    from ..ingest import analysis

    a = analysis(chapter)
    if not a:
        return None
    w = [x for x in a.get("misleading_or_weak_sections") or [] if isinstance(x, dict)][:weak]
    d = [x for x in a.get("key_definitions") or [] if isinstance(x, dict) and x.get("term")][:definitions]
    return {"weak": w, "definitions": d} if (w or d) else None


def _review_batch(items: list[dict], root: Path, scenes: dict) -> tuple[list[dict], list[str], dict]:
    messages, images, context = [], [], {}
    for item in items:
        message = {k: item.get(k) for k in ("id", "type", "text", "quote", "page", "code_notes", "sources")}
        if image := item.get("image"):
            path = (root / image).resolve()
            if not path.is_relative_to(root) or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError(f"Недопустимый путь к кадру {item['id']}: {image}")
            if not path.is_file():
                raise FileNotFoundError(f"Кадр {item['id']} не найден: {image}")
            images.append(str(path))
            message["image_index"] = len(images)
        if (video_id := item.get("video_id")) in scenes:
            message["video_id"] = video_id
            context[video_id] = scenes[video_id]
        messages.append(message)
    return messages, images, context


def _confirm_findings(rd: Path, pkg_id: str, findings: list[dict], items: dict,
                      base: dict, root: Path, scenes: dict) -> tuple[set[str], list[Path]]:
    schema = {"type": "object", "required": ["checks"], "properties": {
        "checks": {"type": "array", "items": {"type": "object", "required": ["id", "supported"],
            "properties": {"id": {"type": "string"}, "supported": {"type": "boolean"}}}},
    }}
    calls = []
    for i in range(0, len(findings), FRAME_BATCH * 2):
        group = findings[i:i + FRAME_BATCH * 2]
        batch, images, context = _review_batch([items[f["target_id"]] for f in group], root, scenes)
        variables = {**base, "items": batch, "scenes": context, "candidates": group}
        calls.append(lambda variables=variables, images=images, i=i: llm.complete_json(
            rd, f"check_{pkg_id}_confirm_{i // (FRAME_BATCH * 2) + 1:02d}", "check_confirm",
            variables, schema, images=images))
    results, pending = llm.gather(calls)
    return {row["id"] for result in results if result for row in result["checks"] if row["supported"]}, pending


def _organizer_remarks(findings: list[dict]) -> list[dict]:
    categories = {
        "overgeneralization": "overgeneralization", "sign_flip": "sign_flip",
        "measured_vs_derived": "measured_vs_inferred", "lost_condition": "lost_condition",
        "missing_caveat": "missing_caveat", "wrong_scaling_law": "wrong_scaling",
        "wrong_mechanism": "wrong_mechanism", "outdated_as_current": "outdated_as_current",
        "it_analogy_without_limit": "analogy_without_limit", "frame_error": "frame_error",
    }
    severity = {1: "minor", 2: "significant", 3: "critical"}
    return [{
        "target": f["target_id"], "category": categories.get(f["error_type"], "other"),
        "severity": severity[f["severity"]], "problem": f["message"], "fix": f.get("fix") or "",
        "page_pdf": f.get("page"), "quote": f.get("evidence_quote"),
    } for f in findings]


def run_check(package: Path, chapter: str, out: str | None = None) -> list[Path]:
    package = Path(package)
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    clear_cache()
    pack = domain_pack(cfg.get("domain", "geology"))
    pkg = load_package(package)
    items = flatten(pkg)
    units = read_json(rd / "units.json")["units"]
    pages = {int(p): normalize(t) for p, t in read_json(rd / "source_pages.json").items()}
    code_findings = []
    for it in items:
        f, notes = code_checks(it, chapter)
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
        "analysis": analysis_brief(chapter, weak=8, definitions=15),
    }
    pkg_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", pkg.get("package_id", package.stem))
    root = (package if package.is_dir() else package.parent).resolve()
    scenes = {s["video_id"]: s["spec"] for s in pkg.get("scenes", []) if "video_id" in s and "spec" in s}
    text_items = [it for it in items if not it.get("image")]
    frame_items = [it for it in items if it.get("image")]
    batches = [group[i:i + size] for group, size in ((text_items, BATCH), (frame_items, FRAME_BATCH))
               for i in range(0, len(group), size)]
    calls = []
    for i, group in enumerate(batches, 1):
        batch, images, context = _review_batch(group, root, scenes)
        calls.append(lambda batch=batch, i=i, images=images, context=context: llm.complete_json(
            rd, f"check_{pkg_id}_{i:02d}", "check_review", {**base, "items": batch, "scenes": context},
            REVIEW_SCHEMA, images=images))
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
                quote = normalize(ev)
                exact_pages = {p for p, text in pages.items() if quote and quote in text}
                if exact_pages:
                    verified = True
                    page = page if page in exact_pages else min(exact_pages)
                else:
                    r = find_quote(ev, page, chapter, min_score=88)
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
    if "items" in pkg:
        candidates = [f for f in findings if f["source"] == "llm"]
        confirmed, pending = _confirm_findings(rd, pkg_id, candidates, by_id, base, root, scenes)
        if pending:
            return pending
        for finding in candidates:
            if finding["target_id"] not in confirmed:
                dropped.append({**finding, "reason": "independent review did not confirm the contradiction"})
        findings = [f for f in findings if f["source"] == "code" or f["target_id"] in confirmed]

    # one finding per target (keep the most severe; llm over code when equal)
    best: dict[str, dict] = {}
    for f in findings:
        cur = best.get(f["target_id"])
        if cur is None or (f["severity"], f["source"] == "llm") > (cur["severity"], cur["source"] == "llm"):
            best[f["target_id"]] = f
    final = sorted(best.values(), key=lambda f: (-f["severity"], f["target_id"]))
    res = {"package_id": pkg.get("package_id"), "chapter": cfg["id"], "items_checked": len(items),
           "findings": final, "dropped_for_precision": dropped}
    if "items" in pkg:
        res["package_id"] = pkg.get("package_id") or pkg_id
        res["remarks"] = _organizer_remarks(final)
        llm.validate(res, llm.load_schema("organizer/review_output"))
    outp = Path(out) if out else root / "findings.json"
    write_json(outp, res)
    print(f"[check] {pkg.get('package_id')}: {len(items)} items, {len(final)} findings "
          f"({sum(1 for f in final if f['source'] == 'code')} by code), dropped {len(dropped)} -> {outp}")
    return []


def run(chapter: str, **kw) -> list[Path]:  # stage-style entry is not used; see run_check
    return []
