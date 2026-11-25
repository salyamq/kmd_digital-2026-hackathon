"""Truth gate: every fact traced to a chapter page + verbatim quote or to a dataset/model,
every number on screen or in the voice-over present in the source table, physics anti-examples absent.
"""
import re

from .inputs import norm_text

NUM_RE = re.compile(r"(?<![\w.,])[-−]?\d+(?:[.,]\d+)?(?:\s?[·x×]\s?10\^?[-−]?\d+)?")
NEG_RU = re.compile(r"\b(не|нет|ни|никак\w*|вовсе не|отнюдь)\b", re.I)
NEG_EN = re.compile(r"\b(not|no|never|doesn't|does not|don't|isn't|aren't|nor|without)\b", re.I)


def numbers_in(text):
    """Numbers as written (strip markup). Returns list of normalized strings ('3.5')."""
    t = re.sub(r"[*_]", "", text or "")
    out = []
    for m in NUM_RE.finditer(t):
        s = m.group().replace("−", "-").replace(",", ".")
        out.append(s)
    return out


def _num_equal(a, b):
    try:
        fa, fb = float(a.split("x")[0]), float(b.split("x")[0])
        return abs(fa - fb) <= 1e-9 * max(1, abs(fa))
    except ValueError:
        return a == b


def build_source_table(script, specs, node, catalog_files=()):
    """Collect every source the video relies on: claims (page+quote), datasets, model params, assumptions."""
    rows, seen = [], set()
    claims = {c["id"]: c for c in node.get("claims", [])}

    index = {}

    def add(row):
        key = (row["kind"], row.get("ref"), row.get("quote"), row.get("file"), row.get("curve"), row.get("param"))
        if key in index:                     # merge: keep the richer description, union of users
            old = index[key]
            for k, v in row.items():
                if k == "used_by":
                    old["used_by"] = sorted(set(old.get("used_by", [])) | set(v))
                elif v not in (None, "", []) and old.get(k) in (None, "", []):
                    old[k] = v
            return
        row["id"] = f"src{len(rows) + 1}"
        index[key] = row
        rows.append(row)
    src = node.get("source") or {}
    if src.get("book"):                       # bibliographic reference (its year may appear in captions)
        add({"kind": "reference", "ref": src["book"], "chapter": src.get("chapter"), "used_by": []})
    for ln in script.get("lines", []):
        for s in ln.get("sources", []):
            if s.get("type", "claim") == "claim":
                c = claims.get(str(s.get("claim_id")), {})
                add({"kind": "claim", "ref": s.get("claim_id"), "page": s.get("page", c.get("page")),
                     "quote": s.get("quote") or c.get("quote"), "claim_text": c.get("text"), "used_by": [ln["id"]]})
            elif s.get("type") == "dataset":
                add({"kind": "dataset", "ref": s.get("dataset"), "file": s.get("file"), "curve": s.get("curve"),
                     "used_by": [ln["id"]]})
    for sp in specs:
        m = sp.get("model") or {}
        if m.get("type") in ("las", "csv"):
            cv = m.get("curve") or m.get("y")
            add({"kind": "dataset", "ref": m.get("dataset", "open dataset"), "file": m.get("file"),
                 "curve": ", ".join(cv) if isinstance(cv, list) else cv, "used_by": [sp["shot_id"]],
                 "selection": "; ".join(f"{k}={v}" for k, v in (m.get("filter") or {}).items()) or None,
                 "window": [m.get("depth_from", m.get("x_from")), m.get("depth_to", m.get("x_to"))]})
        if m.get("type") in ("formula", "pde_diffusion"):
            src = m.get("source") or {}
            c = claims.get(str(src.get("claim_id")), {}) if src.get("claim_id") else {}
            add({"kind": "formula", "ref": m.get("expr") or m.get("coef"), "claim_id": src.get("claim_id"),
                 "page": src.get("page") or c.get("page"), "quote": src.get("quote") or c.get("quote"),
                 "claim_text": c.get("text"), "used_by": [sp["shot_id"]], "assumption": bool(src.get("assumption"))})
            for name, prm in (m.get("params") or {}).items():
                if isinstance(prm, dict):
                    ps = prm.get("source") or {}
                    is_ass = ps == "assumption" or (isinstance(ps, dict) and ps.get("assumption")) or not ps
                    add({"kind": "assumption" if is_ass else "param", "param": name, "value": prm.get("value"),
                         "unit": prm.get("unit"), "page": ps.get("page") if isinstance(ps, dict) else None,
                         "quote": ps.get("quote") if isinstance(ps, dict) else None,
                         "note": ps.get("note") if isinstance(ps, dict) else None, "used_by": [sp["shot_id"]]})
        if m.get("type") == "table":
            src = m.get("source") or {}
            cells = [str(c) for r in m.get("rows", []) for c in r]
            add({"kind": "table", "ref": src.get("title") or "table", "page": src.get("page"), "quote": src.get("quote"),
                 "cells": cells, "labels": m.get("labels"), "used_by": [sp["shot_id"]]})
        for a in sp.get("assumptions", []):
            add({"kind": "assumption", "ref": a if isinstance(a, str) else a.get("text"), "used_by": [sp["shot_id"]]})
    return rows


def verify_sources(source_table, pages):
    """Mark each claim/formula/param row: verified | near | not_found | no_pages | no_quote."""
    for r in source_table:
        if r["kind"] == "table":
            res = pages.find_quote(r.get("quote") or "", r.get("page"))
            missing = [c for c in r.get("cells", []) if not pages.number_on_page(c, r.get("page"))]
            r["missing_cells"] = missing
            r["status"] = res["status"] if not missing else ("not_found" if pages.available else "no_pages")
            r["match"] = res
            continue
        if r["kind"] in ("claim", "formula", "param"):
            if not r.get("quote"):
                r["status"] = "no_quote" if r["kind"] != "formula" or not r.get("assumption") else "assumption"
                continue
            res = pages.find_quote(r["quote"], r.get("page"))
            r["status"] = res["status"]
            r["match"] = res
        elif r["kind"] == "dataset":
            r["status"] = "dataset"
        elif r["kind"] == "reference":
            r["status"] = "reference"
        else:
            r["status"] = "assumption"
    return source_table


def allowed_numbers(source_table, specs=None):
    """Numbers that the source table backs (quotes, claim texts, param values, model params)."""
    nums = set()
    for r in source_table:
        if r["kind"] == "reference":              # only the publication year of the book, nothing else
            nums |= set(re.findall(r"\b(1[89]\d\d|20\d\d)\b", str(r.get("ref") or "")))
            continue
        for k in ("quote", "claim_text", "ref", "file", "curve", "selection"):
            for n in numbers_in(str(r.get(k) or "")):
                nums.add(n)
        for c in r.get("cells") or []:
            for n in numbers_in(str(c)):
                nums.add(n)
        if r.get("value") is not None:
            for n in numbers_in(str(r["value"])):
                nums.add(n)
        if r.get("page") is not None:              # page citations on screen ("с. 65") are references, not facts
            nums.add(str(r["page"]))
    return nums


def check_line_numbers(script, source_table, pages):
    """Spoken numbers: must be in the line's own sources, the source table, or the chapter text."""
    allowed = allowed_numbers(source_table)
    issues = []
    for ln in script.get("lines", []):
        for n in numbers_in(ln.get("text", "")):
            own = set()
            for s in ln.get("sources", []):
                own |= set(numbers_in(str(s.get("quote") or "")))
            if any(_num_equal(n, a) for a in own | allowed):
                continue
            if pages.available and pages.contains_number(n):
                issues.append({"line": ln["id"], "number": n, "status": "in_chapter_not_cited",
                               "severity": "warn"})
                continue
            if ln.get("number_sources", {}).get(n):          # e.g. dataset-derived value
                continue
            issues.append({"line": ln["id"], "number": n, "status": "unsourced", "severity": "fail"})
    return issues


def check_screen_numbers(overlay_items, source_table):
    """On-screen numbers: axis ticks/data readouts/model readouts must carry a source_ref of the right kind;
    any other number must be in the source table."""
    allowed = allowed_numbers(source_table)
    issues = []
    for it in overlay_items:
        texts = [it.get("text", "")] + (it.get("text_track") or [])[:1]
        kind = it.get("kind_num")
        for txt in texts:
            for n in numbers_in(txt):
                if kind == "enumeration" or it.get("kind") in ("header", "subtitle"):
                    continue
                ref = str(it.get("source_ref") or "")
                if kind in ("axis",) and ref.startswith(("axis:", "model:")):
                    continue
                if kind in ("data",) and ref.startswith("dataset:"):
                    continue
                if kind in ("model",) and ref.startswith("model:"):
                    continue
                if any(_num_equal(n, a) for a in allowed):
                    continue
                issues.append({"shot": it.get("shot"), "text": txt[:60], "number": n, "severity": "fail",
                               "status": "unsourced_on_screen"})
    return issues


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?…])\s+|\n", text or "") if s.strip()]


def physics_check(texts, rules, lang):
    """texts: list of (where, text, is_myth). Rules with applies_if/forbid regexes (data from domain pack)."""
    results = []
    joined = " ".join(t for _, t, _ in texts)
    for r in rules:
        if r.get("lang") and r["lang"] != lang:
            continue
        if r.get("applies_if") and not any(re.search(p, joined, re.I) for p in r["applies_if"]):
            results.append({"id": r["id"], "status": "n/a", "text": r.get("text")})
            continue
        hits = []
        for where, txt, is_myth in texts:
            if is_myth:
                continue
            for sent in _sentences(txt):
                for pat in r.get("forbid", []):
                    m = re.search(pat, sent, re.I)
                    if not m:
                        continue
                    neg = NEG_RU if lang == "ru" else NEG_EN
                    if r.get("allow_if_negated") and neg.search(sent[:m.end() + 5]):
                        continue
                    hits.append({"where": where, "sentence": sent[:140], "pattern": pat})
        results.append({"id": r["id"], "status": "fail" if hits else "pass", "text": r.get("text"), "hits": hits})
    return results


def spec_rules_check(specs, rules):
    from .evaluator import safe_eval  # noqa: F401  (expressions here are plain Python over params dict)
    out = []
    for r in rules:
        for sp in specs:
            tpl = r.get("applies_to_template", "*")
            if tpl != "*" and sp.get("template") != tpl:
                continue
            try:
                ok = bool(eval(r["require"], {"__builtins__": {}}, {"params": sp.get("params", {}),
                                                                     "spec": sp}))  # noqa: S307 (domain-pack data)
            except Exception as e:
                ok, r = False, {**r, "error": str(e)}
            out.append({"id": r["id"], "shot": sp["shot_id"], "status": "pass" if ok else "fail", "text": r.get("text")})
    return out


def quote_in_claims(quote, node):
    q = norm_text(quote or "")
    for c in node.get("claims", []):
        if q and (q in norm_text(c.get("quote") or "") or q in norm_text(c.get("text") or "")):
            return c["id"]
    return None
