"""Stage 1b: verify the learning layer with code (not the LLM).

Reusable functions (also used by the course agent on step pages):
    normalize(text) -> str
    find_quote(quote, page, chapter) -> dict(found, page, score, exact)
    extract_numbers(text) -> list[str]
    check_text_numbers(text, chapter) -> list[str]     # numbers absent from the chapter source
run(chapter) writes runs/<ch>/verify_report.json; hard errors make `kmd verify` exit non-zero.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

from ..config import chapter_config, read_json, run_dir, write_json

__all__ = ["normalize", "find_quote", "extract_numbers", "check_text_numbers", "source_numbers", "run", "verify_layer"]

FUZZY_MIN = 90.0

_LATEX_CMD = re.compile(r"\\(?:mathrm|text|mathit|operatorname|mathbf|boldsymbol|textit|textbf)\s*")


def normalize(text: str) -> str:
    """Normalize for quote matching: case, ё/е, dashes, quotes, markdown/LaTeX wrappers, hyphenation, spaces."""
    t = text or ""
    t = t.replace("⟦", " ").replace("⟧", " ")
    t = re.sub(r"⟦?стр\.\s*\d+⟧?", " ", t)
    t = t.lower().replace("ё", "е")
    t = re.sub(r"\\\(|\\\)|\\\[|\\\]|\$\$?", " ", t)       # math delimiters
    t = _LATEX_CMD.sub("", t)
    t = re.sub(r"\\tag\s*\{[^}]*\}", " ", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"[*_`#>|]", " ", t)                          # markdown
    t = re.sub(r"[‐‑‒–—―−]", "-", t)                         # dashes
    t = re.sub(r"[«»“”„\"']", "", t)                         # quotes
    t = t.replace("\u00ad", "")                              # soft hyphen
    t = re.sub(r"(?<=[a-zа-я])-\s+(?=[a-zа-я])", "", t)      # hyphenation across a line/page break
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*([.,;:!?()])\s*", r"\1", t)              # spaces around punctuation do not matter
    return t.strip()


@lru_cache(maxsize=32)
def _pages(chapter: str) -> dict[int, str]:
    rd = run_dir(chapter)
    return {int(k): v for k, v in read_json(rd / "source_pages.json").items()}


@lru_cache(maxsize=32)
def _norm_pages(chapter: str) -> dict[int, str]:
    return {p: normalize(t) for p, t in _pages(chapter).items()}


def clear_cache() -> None:
    _pages.cache_clear()
    _norm_pages.cache_clear()
    source_numbers.cache_clear()


def _fuzzy(q: str, hay: str) -> float:
    try:
        from rapidfuzz import fuzz

        return float(fuzz.partial_ratio(q, hay))
    except ImportError:  # pragma: no cover
        import difflib

        sm = difflib.SequenceMatcher(None, q, hay)
        m = sm.find_longest_match(0, len(q), 0, len(hay))
        return 100.0 * m.size / max(1, len(q))


def find_quote(quote: str, page: int | None, chapter: str, min_score: float = FUZZY_MIN) -> dict:
    """Is the quote on `page` (or spanning page/page+1, or page-1/page)? Returns
    {found, page, score, exact, where}. `where` = "page" | "adjacent" | "other:<p>" | None."""
    q = normalize(quote)
    pages = _norm_pages(chapter)
    if not q:
        return {"found": False, "page": page, "score": 0.0, "exact": False, "where": None}
    cands = []
    if page in pages:
        cands.append(("page", page, pages[page]))
        if page + 1 in pages:
            cands.append(("adjacent", page, pages[page] + " " + pages[page + 1]))
        if page - 1 in pages:
            cands.append(("adjacent", page, pages[page - 1] + " " + pages[page]))
    for where, p, hay in cands:
        if q in hay:
            return {"found": True, "page": p, "score": 100.0, "exact": True, "where": where}
    best = (0.0, None, None)
    for where, p, hay in cands:
        s = _fuzzy(q, hay)
        if s > best[0]:
            best = (s, p, where)
    if best[0] >= min_score:
        return {"found": True, "page": best[1], "score": best[0], "exact": False, "where": best[2]}
    # elsewhere in the chapter? (wrong page)
    for p, hay in pages.items():
        if q in hay or _fuzzy(q, hay) >= min_score:
            return {"found": False, "page": p, "score": 100.0 if q in hay else _fuzzy(q, hay), "exact": q in hay,
                    "where": f"other:{p}"}
    return {"found": False, "page": page, "score": best[0], "exact": False, "where": None}


# ------------------------------------------------------------------ numbers

_NUM = re.compile(r"(?<![\w.,])[-−]?\d+(?:[.,]\d+)?(?:\s?\d{3})*")
_SUPER = str.maketrans({c: " " for c in "⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉⁻₋"})  # exponents/indices are not values


def _canon(n: str) -> str:
    n = n.replace("−", "-").replace(" ", "").replace("\u00a0", "").replace(",", ".")
    n = n.lstrip("-")
    if "." in n:
        n = n.rstrip("0").rstrip(".") or "0"
    n = n.lstrip("0") or "0"
    if n.startswith("."):
        n = "0" + n
    return n


def extract_numbers(text: str) -> list[str]:
    """Numbers as written (with decimal comma/point), excluding single digits inside identifiers/subscripts."""
    t = (text or "").translate(_SUPER)
    t = re.sub(r"\\(?:tag|label)\s*\{[^}]*\}", " ", t)
    t = re.sub(r"[_^]\s*\{[^}]*\}|[_^]\s*\w", " ", t)  # LaTeX sub/superscripts are not numbers
    t = re.sub(r"(?<=[A-Za-zА-Яа-яЁё])\d+", " ", t)      # letter-glued digits (БК-3? no: hyphen) like A0, k2
    out = []
    for m in _NUM.finditer(t):
        s = m.group().strip()
        if s:
            out.append(s)
    return out


@lru_cache(maxsize=32)
def source_numbers(chapter: str) -> frozenset:
    """All numbers that occur in the author text of the chapter (units + full source pages)."""
    rd = run_dir(chapter)
    nums = set()
    texts = list(_pages(chapter).values())
    try:
        texts += [u["text"] for u in read_json(rd / "units.json")["units"]]
    except FileNotFoundError:
        pass
    for t in texts:
        for n in extract_numbers(t):
            nums.add(_canon(n))
        # also raw digit groups (e.g. "10³" -> 10 and 3; "2190–2250")
        for d in re.findall(r"\d+(?:[.,]\d+)?", t.translate(_SUPER)):
            nums.add(_canon(d))
    return frozenset(nums)


TRIVIAL = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "100"}


def check_text_numbers(text: str, chapter: str, allow_trivial: bool = True) -> list[str]:
    """Numbers in `text` that do not occur anywhere in the chapter source (each listed once)."""
    src = source_numbers(chapter)
    bad = []
    for n in extract_numbers(text):
        c = _canon(n)
        if allow_trivial and c in TRIVIAL:
            continue
        if c not in src and n not in bad:
            bad.append(n)
    return bad


# ------------------------------------------------------------------ layer checks

def _node_fields(node: dict):
    """(field_path, text, by) for every learner-visible text field of a node."""
    yield "title_beginner", node.get("title_beginner", ""), "model"
    lay = node.get("layers", {})
    for k in ("mechanism", "practice", "nuances"):
        v = lay.get(k) or {}
        yield f"layers.{k}", v.get("text", ""), v.get("by", "model")
    for i, d in enumerate(lay.get("deeper", []) or []):
        yield f"layers.deeper[{i}]", d.get("title", "") + " " + d.get("text", ""), d.get("by", "model")
    for i, p in enumerate(node.get("procedure", []) or []):
        yield f"procedure[{i}]", p if isinstance(p, str) else p.get("text", ""), "author"
    for c in node.get("claims", []):
        yield f"claims.{c['id']}.text", c.get("text", ""), "author"
    for e in node.get("worked_examples", []):
        yield f"worked_examples.{e['id']}", " ".join([e.get("title", ""), e.get("condition", ""), *e.get("steps", []), e.get("result", "")]), "author"
    for i, t in enumerate(node.get("terms", [])):
        yield f"terms[{i}]", t.get("definition", ""), t.get("by", "model")
    mc = node.get("misconception")
    if mc:
        yield "misconception", mc.get("text", "") + " " + mc.get("correction", ""), mc.get("by", "model")
    dm = node.get("data_meaning") or {}
    yield "data_meaning", " ".join(str(dm.get(k, "")) for k in ("text", "inputs", "outputs", "breaks_where")) + " " + " ".join(dm.get("hypotheses", [])), dm.get("by", "model")
    it = node.get("it_analogy") or {}
    yield "it_analogy", it.get("text", "") + " " + it.get("breaks_where", ""), "model"
    cp = node.get("current_practice") or {}
    yield "current_practice", cp.get("text", ""), "model"
    il = node.get("inefficiency_lens") or {}
    yield "inefficiency_lens", " ".join(str(il.get(k, "")) for k in ("inputs", "manual_steps", "judgment_points", "time", "typical_errors")), il.get("by", "model")
    yield "order_rationale", (node.get("order_rationale") or {}).get("text", ""), "model"


def verify_layer(chapter: str, layer: dict, units: dict, coverage: list | None) -> dict:
    from ..layer.terms import node_text, uses_term

    errors, warnings = [], []
    stats = {"nodes": len(layer.get("nodes", [])), "claims": 0, "quotes_exact": 0, "quotes_fuzzy": 0,
             "quotes_missing": 0, "numbers_bad": 0}

    def err(kind, target, msg, **kw):
        errors.append({"type": kind, "target": target, "message": msg, **kw})

    def warn(kind, target, msg, **kw):
        warnings.append({"type": kind, "target": target, "message": msg, **kw})

    # schema
    try:
        from .. import llm

        llm.validate(layer, llm.load_schema("layer"))
    except Exception as e:
        err("schema", "layer", str(e).split("\n")[0][:400])

    nodes = layer.get("nodes", [])
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        err("ids", "layer", f"duplicate node ids: {dup}")
    idset = set(ids)
    if layer.get("order") and set(layer["order"]) != idset:
        err("order", "layer", "order does not list exactly the node ids")
    in_parts = [i for p in layer.get("parts", []) for i in p["node_ids"]]
    if sorted(in_parts) != sorted(ids):
        warn("parts", "layer", "parts do not partition the nodes")
    pat = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+\.[0-9]{2}$")
    for n in nodes:
        if not pat.match(n["id"]):
            err("ids", n["id"], "id does not match <prefix>.<chapter>.<section>.<nn>")

    unit_ids = set(units)
    claim_ids = set()
    for n in nodes:
        nid = n["id"]
        for l in n.get("links", []):
            if l["to"] not in idset:
                err("links", nid, f"link to unknown node {l['to']}")
        for u in n.get("unit_ids", []):
            if u not in unit_ids:
                err("units", nid, f"unknown unit {u}")
        for c in n.get("claims", []):
            stats["claims"] += 1
            if c["id"] in claim_ids:
                err("ids", c["id"], "duplicate claim id")
            claim_ids.add(c["id"])
            r = find_quote(c["quote"], c["page"], chapter)
            if r["found"]:
                stats["quotes_exact" if r["exact"] else "quotes_fuzzy"] += 1
                if not r["exact"]:
                    warn("quote_fuzzy", c["id"], f"quote matched fuzzily ({r['score']:.0f}%)")
            else:
                stats["quotes_missing"] += 1
                if r["where"] and r["where"].startswith("other:"):
                    err("quote_page", c["id"], f"quote is on page {r['page']}, not {c['page']}", fix_page=r["page"],
                        quote=c["quote"][:120])
                else:
                    err("quote_missing", c["id"], f"quote not found on p.{c['page']} (best {r['score']:.0f}%)",
                        quote=c["quote"][:160])
        # numbers in every learner-visible field
        for path, text, by in _node_fields(n):
            bad = check_text_numbers(text, chapter)
            if bad:
                stats["numbers_bad"] += len(bad)
                err("number_not_in_source", f"{nid}.{path}", f"numbers not in chapter: {bad}", by=by)
        for e in n.get("worked_examples", []):
            if not e.get("unit_ids"):
                warn("example_units", e["id"], "worked example without unit ids")
        mc = n.get("misconception")
        if mc:
            for cid in mc.get("claim_ids", []):
                if cid not in {c["id"] for c in n["claims"]}:
                    warn("misconception", nid, f"misconception refers to unknown claim {cid}")

    # coverage
    covered = {}
    if coverage is None:
        err("coverage", "layer", "coverage.json missing")
    else:
        for c in coverage:
            covered[c["unit_id"]] = c
            if not c.get("node_id") and not c.get("reason"):
                err("coverage", c["unit_id"], f"unit ({c['kind']}, p.{c['page']}) has neither node nor reason")
            if c.get("node_id") and c["node_id"] not in idset:
                err("coverage", c["unit_id"], f"coverage points to unknown node {c['node_id']}")
        for uid in units:
            if uid not in covered:
                err("coverage", uid, "unit missing in coverage.json")
    # every example/problem unit should be represented as such
    ex_units = {u for n in nodes for e in n.get("worked_examples", []) for u in e.get("unit_ids", [])}
    pr_units = {p["unit_id"] for n in nodes for p in n.get("book_problems", [])}
    for uid, u in units.items():
        if u["kind"] == "problem" and uid not in pr_units:
            warn("problem_missing", uid, f"book problem {u.get('problem_no')} (p.{u['page']}) not in any node.book_problems")
        if u["kind"] == "example" and uid not in ex_units:
            warn("example_missing", uid, f"example {u.get('example_no')} (p.{u['page']}) not in any worked_examples")

    # term used before the node that defines it
    first_def = {}
    for i, n in enumerate(nodes):
        for t in n.get("terms", []):
            first_def.setdefault(t["term"].lower().replace("ё", "е"), i)
    for i, n in enumerate(nodes):
        txt = node_text(n)
        own = {t["term"].lower().replace("ё", "е") for t in n.get("terms", [])}
        for term, j in first_def.items():
            if j > i and term not in own and uses_term(txt, term):
                warn("term_before_definition", n["id"], f"uses «{term}» defined later in {nodes[j]['id']}")

    stats["errors"] = len(errors)
    stats["warnings"] = len(warnings)
    return {"chapter": chapter, "ok": not errors, "stats": stats, "errors": errors, "warnings": warnings}


def run(chapter: str, **kw) -> list[Path]:
    clear_cache()
    rd = run_dir(chapter)
    layer = read_json(rd / "layer.json")
    units = {u["id"]: u for u in read_json(rd / "units.json")["units"]}
    cov_p = rd / "coverage.json"
    coverage = read_json(cov_p) if cov_p.exists() else None
    rep = verify_layer(chapter_config(chapter)["id"], layer, units, coverage)
    write_json(rd / "verify_report.json", rep)
    s = rep["stats"]
    print(f"[verify] {chapter}: nodes={s['nodes']} claims={s['claims']} quotes exact/fuzzy/missing="
          f"{s['quotes_exact']}/{s['quotes_fuzzy']}/{s['quotes_missing']} bad_numbers={s['numbers_bad']} "
          f"errors={s['errors']} warnings={s['warnings']}")
    for e in rep["errors"][:25]:
        print("  ERROR", e["type"], e["target"], e["message"])
    if rep["errors"] and not kw.get("no_fail"):
        sys.exit(2)
    return []
