"""`kmd course CH`: layer.json (+ routing, scenes, domain pack) -> steps/*.json, tasks.json, cards.json.

One LLM request per node (prompt `course_step`), then code-level checks:
  * every claim of the node is retold in «Как это работает» (claim_ids coverage);
  * sentences <= 20 words in model-written blocks; beginner title 3-7 words;
  * every number in model-written text exists in the source (source_pages.json) or in author fields;
  * every task: claim_id exists, `evidence` is a substring of the step text, answer consistent;
  * illustration templates exist and render.
If hard errors remain, one repair request (prompt `course_step_fix`) with the error list; whatever still
fails after that is dropped (tasks, illustrations) or reported in steps/<id>.json `checks` and
course_report.json. Blocks taken verbatim from the layer (examples, formulas, tables, terms,
misconception, data meaning, analogy, practice, book problems) are assembled by code, not by the LLM.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .. import llm
from ..config import SCHEMAS, chapter_config, domain_pack, read_json, run_dir, write_json
from . import checks as C
from . import illustrate

TYPES = ["single", "multiple", "order", "cloze", "numeric"]
LANG_NAMES = {"ru": "русский", "en": "английский", "kk": "казахский"}
MIN_TASKS_CHAPTER = 15
FORMAT_LABELS = {
    "short": "короткое видео (шортс)",
    "long": "видео-разбор",
    "interactive": "интерактив",
    "data_practice": "практикум на данных",
    "cards": "карточки",
    "text": "текст",
}


# ---------------------------------------------------------------- inputs

def load_layer(rd: Path) -> dict:
    p = rd / "layer.json"
    if not p.exists():
        raise FileNotFoundError(f"{p} not found: run `kmd layer` first")
    return read_json(p)


def load_routing(rd: Path) -> dict:
    p = rd / "routing.json"
    if not p.exists():
        return {}
    r = read_json(p)
    if isinstance(r, dict):
        r = r.get("routing") or r.get("nodes") or list(r.values())
    return {x["node_id"]: x for x in r if isinstance(x, dict) and "node_id" in x}


def load_scenes(rd: Path) -> dict:
    d = rd / "scenes"
    out = {}
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                s = read_json(f)
            except Exception:
                continue
            out[s.get("node_id", f.stem)] = s
    return out


def scene_summary(scene: dict | None) -> dict | None:
    if not scene:
        return None
    keep = {k: scene.get(k) for k in ("template", "params", "invariants", "assumptions", "exaggerations") if scene.get(k)}
    keep["frames"] = [{"id": f.get("id"), "class": f.get("class"), "description": f.get("description")} for f in scene.get("frames", [])][:12]
    return keep


def node_order(layer: dict) -> list[str]:
    ids = [n["id"] for n in layer["nodes"]]
    order = [i for i in layer.get("order", []) if i in ids]
    return order + [i for i in ids if i not in order]


def part_of(layer: dict) -> dict:
    out = {}
    for p in layer.get("parts", []):
        for nid in p.get("node_ids", []):
            out.setdefault(nid, {"id": p["id"], "title": p["title"]})
    return out


def domain_misconceptions(pack: dict) -> list[dict]:
    m = pack.get("misconceptions") or []
    if isinstance(m, dict):
        m = m.get("items") or m.get("misconceptions") or []
    out = []
    for x in m:
        if isinstance(x, str):
            out.append({"text": x, "keywords": []})
        elif isinstance(x, dict):
            t = x.get("text") or x.get("misconception") or x.get("wrong") or x.get("myth")
            if t:
                out.append({"text": t, "correction": x.get("correction", ""), "keywords": x.get("keywords", [])})
    return out


def relevant_misconceptions(items: list[dict], node: dict, limit: int = 8) -> list[str]:
    """Misconceptions whose keywords occur in the node (domain packs give keywords); else none."""
    txt = C.norm(json.dumps(node, ensure_ascii=False))
    out = []
    for m in items:
        kws = [C.norm(k) for k in m.get("keywords", []) if k]
        if kws and any(k in txt for k in kws):
            out.append(m["text"] + (f" (на деле: {m['correction']})" if m.get("correction") else ""))
    return out[:limit]


def source_number_set(rd: Path, layer: dict) -> set[str]:
    """Numbers allowed in course text: those of the source pages, plus author-side layer fields
    (worked examples, tables, formulas, quotes) which may carry OCR fixes."""
    nums: set[str] = set()
    sp = rd / "source_pages.json"
    if sp.exists():
        for t in read_json(sp).values():
            nums |= C.number_set(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False))
    for n in layer["nodes"]:
        for c in n.get("claims", []):
            nums |= C.number_set(c.get("quote", ""))
        for k in ("worked_examples", "tables", "formulas", "book_problems"):
            nums |= C.number_set(json.dumps(n.get(k, []), ensure_ascii=False))
        if not sp.exists():
            nums |= C.number_set(json.dumps(n, ensure_ascii=False))
    return nums


def node_has_numbers(node: dict) -> bool:
    txt = json.dumps([node.get("claims"), node.get("worked_examples"), node.get("tables")], ensure_ascii=False)
    return any(n not in C.TRIVIAL_NUMBERS for n in C.numbers(re.sub(r'"(id|unit_ids|page)":\s*("[^"]*"|\d+|\[[^\]]*\])', "", txt)))


def prompt_node(node: dict) -> dict:
    """The node as shown to the LLM: drop bookkeeping fields."""
    n = {k: v for k, v in node.items() if not k.startswith("_") and k != "unit_ids"}
    n["claims"] = [{k: v for k, v in c.items() if k != "unit_ids"} for c in node.get("claims", [])]
    n["worked_examples"] = [{k: v for k, v in e.items() if k != "unit_ids"} for e in node.get("worked_examples", [])]
    n["book_problems"] = [{k: v for k, v in e.items() if k != "unit_id"} for e in node.get("book_problems", [])]
    return n


def step_llm_schema() -> dict:
    s = read_json(SCHEMAS / "course_step_llm.schema.json")
    t = read_json(SCHEMAS / "task.schema.json")
    t.pop("$schema", None)
    for k in ("id", "node_id", "page", "anchor"):
        t["properties"].pop(k, None)
    s["$defs"]["task"] = t
    return s


# ---------------------------------------------------------------- planning

def plan(layer: dict, routing: dict) -> dict:
    order = node_order(layer)
    nodes = {n["id"]: n for n in layer["nodes"]}
    n = max(1, len(order))
    base = min(5, max(2, math.ceil((MIN_TASKS_CHAPTER + 3) / n)))
    decision = [nid for nid in order if routing.get(nid, {}).get("format") == "data_practice"]
    if not decision:
        def score(nid):
            nd = nodes[nid]
            prim = (nd.get("difficulty") or {}).get("primary")
            return len(nd.get("worked_examples", [])) * 2 + (2 if prim in ("И", "Н", "Р") else 0) + (1 if nd.get("data_meaning") else 0)
        best = max(order, key=score)
        decision = [best]
    out = {}
    for i, nid in enumerate(order):
        nd = nodes[nid]
        k = base + (1 if len(nd.get("claims", [])) > 8 and base < 5 else 0)
        has_num = node_has_numbers(nd)
        pref = [TYPES[(2 * i) % 5], TYPES[(2 * i + 1) % 5]]
        if not has_num:
            pref = [t if t != "numeric" else "single" for t in pref]
            if pref[0] == pref[1]:
                pref[1] = "cloze"
        elif nd.get("worked_examples") and "numeric" not in pref:
            pref.append("numeric")
        out[nid] = {"index": i + 1, "n_tasks": k, "preferred_types": pref, "has_numbers": has_num, "need_decision": nid in decision}
    return out


# ---------------------------------------------------------------- assembly + checks

def _pages(ids, claims) -> list[int]:
    return sorted({claims[i]["page"] for i in ids if i in claims and claims[i].get("page") is not None})


def _ids(ids, claims, errors, where):
    good = []
    for i in ids or []:
        if i in claims:
            good.append(i)
        else:
            errors.append(f"{where}: неизвестный claim_id «{i}» (есть: {', '.join(claims)})")
    return good


def assemble(node: dict, ans: dict, ctx: dict) -> dict:
    """Build the step page + tasks + cards from the layer node and the LLM answer; run checks."""
    claims = {c["id"]: c for c in node.get("claims", [])}
    errors: list[str] = []
    warnings: list[str] = []
    src_nums: set[str] = ctx["source_numbers"]

    def num_check(text, where, hard=True):
        bad = C.unknown_numbers(text, src_nums)
        if bad:
            (errors if hard else warnings).append(f"{where}: числа не найдены в источнике: {', '.join(bad)}")

    def len_check(text, where, hard=True):
        for s in C.long_sentences(text):
            (errors if hard else warnings).append(f"{where}: фраза длиннее 20 слов ({C.words(s)}): «{s[:90]}…»")

    title = ans["title_beginner"].strip().rstrip(".")
    tw = C.words(title)
    if not 3 <= tw <= 7:
        errors.append(f"title_beginner: {tw} слов, нужно 3–7")
    essence = [e.strip() for e in ans["essence"]]
    for k, e in enumerate(essence):
        len_check(e, f"essence[{k}]")
        num_check(e, f"essence[{k}]")

    blocks: list[dict] = []
    chunks: list[tuple[str, str]] = [("essence", " ".join(essence))]
    quoted: set[str] = set()

    # --- Как это работает
    items, covered = [], set()
    for k, p in enumerate(ans["how_it_works"]):
        where = f"how_it_works[{k}]"
        ids = _ids(p.get("claim_ids"), claims, errors, where)
        by = p.get("by") or ("author" if ids else "model")
        if by == "author" and not ids:
            errors.append(f"{where}: абзац by=author без claim_ids")
        if by == "model" and ids:
            by = "author"
        covered |= set(ids)
        len_check(p["text"], where)
        num_check(p["text"], where)
        quotes = []
        for i in ids:
            if i not in quoted:
                quoted.add(i)
                c = claims[i]
                quotes.append({"claim_id": i, "quote": c["quote"], "page": c.get("page"), "kind": c.get("kind")})
        bid = f"how-{k+1}"
        items.append({"id": bid, "section": p.get("section") or "", "text": p["text"], "claim_ids": ids, "pages": _pages(ids, claims), "by": by, "quotes": quotes})
        chunks.append((bid, p["text"]))
    missing = [i for i in claims if i not in covered]
    if missing:
        errors.append(f"how_it_works: не пересказаны утверждения {', '.join(missing)} — каждое claim id должно быть в claim_ids какого-то абзаца")
    model_pars = sum(1 for it in items if it["by"] == "model")
    if model_pars > 2:
        warnings.append(f"how_it_works: {model_pars} абзацев без опоры на книгу")
    blocks.append({"id": "how", "kind": "how", "title": "Как это работает", "by": "mixed", "pages": sorted({p for it in items for p in it["pages"]}), "items": items})

    # --- По шагам
    proc = ans.get("procedure")
    if proc and proc.get("steps"):
        steps = []
        for k, s in enumerate(proc["steps"]):
            ids = _ids(s.get("claim_ids"), claims, errors, f"procedure.steps[{k}]")
            len_check(s["text"], f"procedure.steps[{k}]")
            num_check(s["text"], f"procedure.steps[{k}]")
            steps.append({"text": s["text"], "claim_ids": ids, "pages": _pages(ids, claims)})
        blocks.append({"id": "procedure", "kind": "procedure", "title": "По шагам", "by": "mixed", "subtitle": proc.get("title", ""), "pages": sorted({p for s in steps for p in s["pages"]}), "items": steps})
        chunks.append(("procedure", " ".join(s["text"] for s in steps)))

    # --- Разбор примеров (author, from the layer)
    exs = node.get("worked_examples") or []
    if exs:
        ex_items = []
        for e in exs:
            eid = "ex-" + re.sub(r"[^A-Za-z0-9_-]+", "_", str(e.get("id", len(ex_items) + 1)))
            ex_items.append({"id": eid, "title": e.get("title", ""), "page": e.get("page"), "condition": e.get("condition", ""), "steps": e.get("steps", []), "result": e.get("result", ""), "numbers": e.get("numbers", [])})
            chunks.append((eid, " ".join([e.get("condition", ""), " ".join(e.get("steps", [])), e.get("result", "")])))
        blocks.append({"id": "examples", "kind": "examples", "title": "Разбор примеров из книги", "by": "author", "pages": sorted({e["page"] for e in ex_items if e["page"]}), "items": ex_items})

    # --- Решение на данных
    dec = ans.get("decision")
    if dec:
        ids = _ids(dec.get("claim_ids"), claims, errors, "decision")
        txt = " ".join([dec.get("title", ""), " ".join(dec.get("signs", [])), dec.get("rule", ""), dec.get("conclusion", "")] + [c.get("given", "") + " " + c.get("why", "") + " " + " ".join(c.get("options", [])) for c in dec.get("cases", [])])
        num_check(txt, "decision")
        for f in ("rule", "conclusion"):
            len_check(dec.get(f, ""), f"decision.{f}")
        for k, cs in enumerate(dec.get("cases", [])):
            if not 0 <= cs.get("answer", -1) < len(cs.get("options", [])):
                errors.append(f"decision.cases[{k}]: answer вне диапазона options")
        blocks.append({"id": "decision", "kind": "decision", "title": "Решение на данных", "by": "mixed", "pages": _pages(ids, claims), "data": dict(dec, claim_ids=ids)})
        chunks.append(("decision", txt))
    elif ctx.get("need_decision"):
        errors.append("decision: для этого шага нужен блок «решение на данных» (признаки → правило → вывод)")

    # --- Цифры и условия
    if ans.get("numbers"):
        nitems = []
        for k, s in enumerate(ans["numbers"]):
            ids = _ids(s.get("claim_ids"), claims, errors, f"numbers[{k}]")
            num_check(s["text"], f"numbers[{k}]")
            len_check(s["text"], f"numbers[{k}]")
            nitems.append({"text": s["text"], "claim_ids": ids, "pages": _pages(ids, claims)})
        blocks.append({"id": "numbers", "kind": "numbers", "title": "Цифры и условия", "by": "mixed", "pages": sorted({p for s in nitems for p in s["pages"]}), "items": nitems})
        chunks.append(("numbers", " ".join(s["text"] for s in nitems)))

    # --- Формулы, таблицы (author, from the layer)
    if node.get("formulas"):
        blocks.append({"id": "formulas", "kind": "formulas", "title": "Формулы", "by": "author", "pages": sorted({f["page"] for f in node["formulas"] if f.get("page")}), "items": node["formulas"]})
        chunks.append(("formulas", " ".join(f.get("meaning", "") + " " + " ".join(v.get("meaning", "") for v in f.get("vars", [])) for f in node["formulas"])))
    if node.get("tables"):
        blocks.append({"id": "tables", "kind": "tables", "title": "Таблицы книги", "by": "author", "pages": sorted({t["page"] for t in node["tables"] if t.get("page")}), "items": node["tables"]})
        chunks.append(("tables", " ".join(t.get("caption", "") + " " + " ".join(t.get("columns", [])) + " " + " ".join(" ".join(r) for r in t.get("rows", [])) for t in node["tables"])))

    # --- Частая ошибка
    mis = node.get("misconception")
    if mis and mis.get("text"):
        ids = [i for i in mis.get("claim_ids", []) if i in claims]
        blocks.append({"id": "mistake", "kind": "mistake", "title": "Частая ошибка", "by": mis.get("by", "model"), "pages": _pages(ids, claims), "data": dict(mis, claim_ids=ids)})
        chunks.append(("mistake", mis["text"] + " " + mis.get("correction", "")))

    # --- Что это значит для данных
    dm = node.get("data_meaning")
    if dm and dm.get("text"):
        data = dict(dm)
        lens = node.get("inefficiency_lens")
        if lens:
            data["lens"] = lens
        blocks.append({"id": "data", "kind": "data", "title": "Что это значит для данных", "by": dm.get("by", "model"), "pages": [], "data": data})
        chunks.append(("data", " ".join(str(dm.get(k, "")) for k in ("text", "inputs", "outputs", "breaks_where")) + " " + " ".join(dm.get("hypotheses", []))))

    # --- Аналогия
    an = node.get("it_analogy")
    if an and an.get("text"):
        blocks.append({"id": "analogy", "kind": "analogy", "title": "Аналогия", "by": an.get("by", "model"), "pages": [], "data": an})
        chunks.append(("analogy", an["text"] + " " + an.get("breaks_where", "")))

    # --- Как это делается сейчас; глубже
    cp = node.get("current_practice")
    if cp and cp.get("text"):
        blocks.append({"id": "now", "kind": "now", "title": "Как это делается сейчас", "by": cp.get("by", "model"), "pages": [], "data": cp})
        chunks.append(("now", cp["text"]))
    deeper = (node.get("layers") or {}).get("deeper") or []
    if deeper:
        blocks.append({"id": "deeper", "kind": "deeper", "title": "Глубже", "by": "mixed", "pages": [], "items": deeper})
        chunks.append(("deeper", " ".join(d.get("title", "") + " " + d.get("text", "") for d in deeper)))

    # --- Задачи из книги, рисунки книги
    if node.get("book_problems"):
        blocks.append({"id": "problems", "kind": "problems", "title": "Задачи из книги", "by": "author", "pages": sorted({b["page"] for b in node["book_problems"] if b.get("page")}), "items": node["book_problems"]})
        chunks.append(("problems", " ".join(b.get("text", "") for b in node["book_problems"])))
    if node.get("figures"):
        blocks.append({"id": "book_figures", "kind": "book_figures", "title": "Рисунки книги к этому шагу", "by": "author", "pages": sorted({f["page"] for f in node["figures"] if f.get("page")}), "items": node["figures"]})

    # --- Новые понятия
    if node.get("terms"):
        blocks.append({"id": "glossary", "kind": "glossary", "title": "Новые понятия", "by": "mixed", "pages": sorted({t["page"] for t in node["terms"] if t.get("page")}), "items": node["terms"]})
        chunks.append(("glossary", " ".join(t["term"] + " — " + t.get("definition", "") for t in node["terms"])))
        alltext = norm_all = C.norm(" ".join(t for _, t in chunks))
        for t in node["terms"]:
            if C.norm(t["term"]).split(" ")[0][:5] not in alltext:
                warnings.append(f"термин «{t['term']}» не встречается в тексте шага")
        del norm_all

    # --- Tasks
    tasks = []
    for k, t in enumerate(ans.get("tasks", [])):
        errs = check_task(t, claims, chunks, src_nums)
        t = dict(t)
        t["page"] = claims[t["claim_id"]].get("page") if t.get("claim_id") in claims else None
        t["anchor"] = C.find_evidence(t.get("evidence", ""), chunks)
        if errs:
            errors.extend(f"tasks[{k}] ({t.get('type')}): {e}" for e in errs)
            t["_bad"] = errs
        tasks.append(t)
    if len({t["type"] for t in tasks if not t.get("_bad")}) < 2 and len(tasks) >= 2:
        warnings.append("tasks: меньше двух типов заданий в шаге")

    # --- Cards
    cards = []
    for k, c in enumerate(ans.get("cards", [])):
        ids = [i for i in c.get("claim_ids", []) if i in claims]
        num_check(c["front"] + " " + c["back"], f"cards[{k}]")
        if C.words(c["back"]) > 40:
            warnings.append(f"cards[{k}]: ответ длиннее 40 слов")
        cards.append({"front": c["front"], "back": c["back"], "claim_ids": ids, "kind": c.get("kind", "idea"), "page": (_pages(ids, claims) or [None])[0]})

    # --- Illustrations: render now, so a failing spec goes into the repair request
    known = {t["template"] for t in ctx["catalog"]}
    ills = []
    for k, s in enumerate(ans.get("illustrations", [])):
        where = f"illustrations[{k}] ({s.get('template')})"
        if s.get("template") not in known:
            errors.append(f"{where}: неизвестный шаблон (есть: {', '.join(sorted(known))})")
            continue
        ids = _ids(s.get("claim_ids"), claims, errors, where)
        txt = json.dumps({"p": s.get("params", {}), "c": s.get("caption", ""), "a": s.get("alt", "")}, ensure_ascii=False)
        bad = C.unknown_numbers(re.sub(r'"(tone|log|min|max|ticks|[a-z_]*frac|[a-z_]*_m|width|height|t|seed|vertical_exaggeration)":\s*(\[[^\]]*\]|[^,}\]]+)', "", txt), src_nums)
        if bad:
            warnings.append(f"{where}: числа не найдены в источнике (проверьте, что это параметры модели, а не факты): {', '.join(bad)}")
        stem = f"{node['id']}__{k+1}"
        try:
            r = illustrate.render(s, ctx["ill_dir"], stem)
        except Exception as e:
            errors.append(f"{where}: рисунок не построен: {str(e)[:400]}")
            continue
        if r.get("issues"):
            errors.append(f"{where}: нарушены инварианты шаблона: {'; '.join(i.get('message', '') for i in r['issues'])[:400]}")
            continue
        best, overlap = "how", 0
        for it in items:
            o = len(set(ids) & set(it["claim_ids"]))
            if o > overlap:
                best, overlap = it["id"], o
        f = Path(r["file"])
        rd = ctx["run_dir"]
        ills.append({
            "id": f"ill-{k+1}", "template": s["template"], "class": r["class"], "provenance": r["provenance"],
            "caption": r.get("caption") or s["caption"], "alt": s.get("alt") or r.get("alt") or "",
            "file": str(f.resolve().relative_to(rd.resolve())) if rd.resolve() in f.resolve().parents else str(f),
            "renderer": r["renderer"], "claim_ids": ids, "pages": _pages(ids, claims), "after_block": best,
            "redrawn_from": r.get("redrawn_from") or s.get("redrawn_from"), "exaggerations": r.get("exaggerations") or s.get("exaggerations"),
        })
    if not ills:
        errors.append("illustrations: нет ни одной корректной иллюстрации")

    return {"title": title, "essence": essence, "blocks": blocks, "tasks": tasks, "cards": cards, "illustrations": ills, "chunks": chunks, "errors": errors, "warnings": warnings}


def check_task(t: dict, claims: dict, chunks, src_nums) -> list[str]:
    e = []
    typ = t.get("type")
    if t.get("claim_id") not in claims:
        e.append(f"claim_id «{t.get('claim_id')}» нет в узле")
    ev = t.get("evidence", "")
    if not C.find_evidence(ev, chunks):
        e.append(f"evidence не найден дословно в тексте шага: «{ev[:80]}»")
    alltext = " ".join([t.get("question", ""), t.get("text", ""), " ".join(t.get("options", []) or []), " ".join(t.get("items", []) or []), t.get("explanation", "")])
    bad = C.unknown_numbers(alltext, src_nums | C.number_set(ev))
    if bad:
        e.append(f"числа не из источника: {', '.join(bad)}")
    if typ in ("single", "multiple"):
        opts, cor = t.get("options") or [], t.get("correct") or []
        if any(not 0 <= i < len(opts) for i in cor):
            e.append("correct: индекс вне options")
        if typ == "single" and len(cor) != 1:
            e.append("single: должен быть ровно один верный ответ")
        if typ == "multiple" and len(cor) < 2:
            e.append("multiple: нужно хотя бы два верных ответа (иначе используй single)")
        if len(set(C.norm(o) for o in opts)) != len(opts):
            e.append("options: повторяющиеся варианты")
    elif typ == "order":
        its = t.get("items") or []
        if len(its) < 3 or len(set(C.norm(i) for i in its)) != len(its):
            e.append("order: нужно 3+ разных пункта")
    elif typ == "cloze":
        n = (t.get("text") or "").count("___")
        bl = t.get("blanks") or []
        if n != len(bl) or n == 0:
            e.append(f"cloze: пропусков ___ в тексте {n}, а blanks {len(bl)}")
        for k, b in enumerate(bl):
            a0 = (b.get("answers") or [""])[0]
            if b.get("options") and C.norm(a0) not in [C.norm(o) for o in b["options"]]:
                e.append(f"cloze blank {k}: options не содержат ответ «{a0}»")
            if not C.stem_in(a0, ev):
                e.append(f"cloze blank {k}: ответ «{a0}» не виден в evidence")
    elif typ == "numeric":
        a = t.get("answer")
        if a is None:
            e.append("numeric: нет answer")
        elif C.norm_number(f"{a:g}") not in C.number_set(ev):
            e.append(f"numeric: ответ {a:g} не встречается в evidence")
    return e


def minutes_for(step_text_words: int, n_tasks: int, n_cases: int, has_media: bool) -> int:
    m = step_text_words / 120 + n_tasks * 0.75 + n_cases * 0.5 + (1.5 if has_media else 0)
    return max(2, int(math.ceil(m)))


# ---------------------------------------------------------------- LLM calls

def llm_vars(cfg: dict, layer: dict, node: dict, pl: dict, ctx: dict) -> dict:
    lang = cfg.get("course_language", "ru")
    route = ctx["routing"].get(node["id"], {})
    return {
        "course_language_name": LANG_NAMES.get(lang, lang),
        "book": cfg.get("book", {}),
        "chapter_title": layer.get("title") or cfg.get("title", ""),
        "index": pl["index"],
        "total": ctx["total"],
        "part_title": ctx["parts"].get(node["id"], {}).get("title", ""),
        "prev_terms": ctx["prev_terms"][node["id"]],
        "next_title": ctx["next_title"].get(node["id"]),
        "route_format": FORMAT_LABELS.get(route.get("format", "text"), route.get("format", "text")),
        "route_rationale": (route.get("rationale") or "").strip().rstrip("."),
        "node": prompt_node(node),
        "scene": scene_summary(ctx["scenes"].get(node["id"])),
        "misconceptions": relevant_misconceptions(ctx["misconceptions"], node),
        "templates_text": ctx["catalog_text"],
        "n_tasks": pl["n_tasks"],
        "preferred_types": pl["preferred_types"],
        "has_numbers": pl["has_numbers"],
        "need_decision": pl["need_decision"],
    }


def build_node(rd: Path, cfg: dict, layer: dict, node: dict, pl: dict, ctx: dict):
    """Return (assembled, attempts) or raise PendingLLM."""
    schema = step_llm_schema()
    v = llm_vars(cfg, layer, node, pl, ctx)
    task = f"course_step.{node['id']}"
    ans = llm.complete_json(rd, task, "course_step", v, schema=schema)
    actx = dict(ctx, need_decision=pl["need_decision"])
    res = assemble(node, ans, actx)
    if not res["errors"]:
        return res, 1
    v2 = dict(v, previous=ans, errors=res["errors"])
    ans2 = llm.complete_json(rd, task + ".fix", "course_step_fix", v2, schema=schema)
    res2 = assemble(node, ans2, actx)
    res2["fixed_errors"] = res["errors"]
    return res2, 2


# ---------------------------------------------------------------- output

def write_step(rd: Path, cfg: dict, layer: dict, node: dict, pl: dict, ctx: dict, res: dict) -> tuple[dict, list, list]:
    nid = node["id"]
    claims = {c["id"]: c for c in node.get("claims", [])}
    errors, warnings = list(res["errors"]), list(res["warnings"])
    ills = list(res["illustrations"])
    # extra illustrations announced by the visuals stage (book figure redraws, scene stills)
    man = rd / "illustrations" / "manifest.json"
    if man.exists():
        for k, m in enumerate([m for m in read_json(man) if m.get("node_id") == nid]):
            ills.append({
                "id": f"ill-v{k+1}", "template": m.get("template", "visuals"), "class": m.get("class", "B"),
                "provenance": m.get("provenance", "схема"), "caption": m.get("caption", ""), "alt": m.get("alt", m.get("caption", "")),
                "file": m["file"], "renderer": "visuals", "claim_ids": m.get("claim_ids", []),
                "pages": _pages(m.get("claim_ids", []), claims) or ([m["page"]] if m.get("page") else []), "after_block": m.get("after_block") or "how",
            })
    if not ills:
        errors.append("на шаге нет ни одной иллюстрации")

    good_tasks = [t for t in res["tasks"] if not t.get("_bad")]
    dropped = [t for t in res["tasks"] if t.get("_bad")]
    tasks = []
    for k, t in enumerate(good_tasks):
        t = {k2: v for k2, v in t.items() if not k2.startswith("_")}
        t["id"] = f"{nid}.t{k+1:02d}"
        t["node_id"] = nid
        tasks.append(t)
    cards = [dict(c, id=f"{nid}.k{k+1:02d}", node_id=nid) for k, c in enumerate(res["cards"])]

    pages = set()
    for b in res["blocks"]:
        pages |= set(b.get("pages") or [])
    pages |= {c["page"] for c in claims.values() if c.get("page")}
    text_words = sum(len(t.split()) for _, t in res["chunks"])
    dec = next((b for b in res["blocks"] if b["kind"] == "decision"), None)
    route = ctx["routing"].get(nid, {})
    step = {
        "node_id": nid,
        "chapter": layer["chapter"],
        "index": pl["index"],
        "part": ctx["parts"].get(nid, {"id": "p0", "title": ""}),
        "title_beginner": res["title"],
        "title_book": node.get("title_book", ""),
        "section": node.get("section"),
        "pages": sorted(pages),
        "minutes": minutes_for(text_words, len(tasks), len(dec["data"].get("cases", [])) if dec else 0, route.get("format") in ("short", "long", "interactive")),
        "difficulty": node.get("difficulty", {}),
        "threshold": (node.get("difficulty") or {}).get("threshold"),
        "format": route.get("format", "text"),
        "format_rationale": route.get("rationale", ""),
        "order_rationale": (node.get("order_rationale") or {}).get("text"),
        "essence": res["essence"],
        "blocks": res["blocks"],
        "illustrations": ills,
        "media": None,
        "sources": [{"claim_id": c["id"], "kind": c.get("kind"), "text": c.get("text"), "quote": c["quote"], "page": c.get("page"), "by": c.get("by", "author")} for c in node.get("claims", [])],
        "task_ids": [t["id"] for t in tasks],
        "card_ids": [c["id"] for c in cards],
        "links": node.get("links", []),
        "overridden": bool(node.get("_overridden")),
        "checks": {"errors": errors, "warnings": warnings, "fixed": res.get("fixed_errors", []), "dropped_tasks": [{"question": t.get("question"), "errors": t["_bad"]} for t in dropped]},
    }
    write_json(rd / "steps" / f"{nid}.json", step)
    write_json(rd / "steps" / f"{nid}.tasks.json", {"tasks": tasks, "cards": cards})
    return step, tasks, cards


def run(chapter: str, node: str | None = None, **kw) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    layer = load_layer(rd)
    try:
        from ..edits import apply_overrides

        layer, _ = apply_overrides(cfg["id"], layer) if not layer.get("_overrides_applied") else (layer, [])
    except Exception as e:  # overrides of other chapters/ids must not break the course
        print(f"[course] overrides not applied: {e}")
    routing = load_routing(rd)
    try:
        pack = domain_pack(cfg.get("domain") or layer.get("domain", ""))
    except FileNotFoundError:
        pack = {}
    order = node_order(layer)
    nodes = {n["id"]: n for n in layer["nodes"]}
    pl = plan(layer, routing)
    prev_terms, seen, next_title = {}, [], {}
    for i, nid in enumerate(order):
        prev_terms[nid] = list(seen)
        seen += [t["term"] for t in nodes[nid].get("terms", []) if t["term"] not in seen]
        next_title[nid] = nodes[order[i + 1]].get("title_beginner") if i + 1 < len(order) else None
    ctx = {
        "routing": routing,
        "scenes": load_scenes(rd),
        "parts": part_of(layer),
        "total": len(order),
        "prev_terms": prev_terms,
        "next_title": next_title,
        "misconceptions": domain_misconceptions(pack),
        "catalog": illustrate.catalog(cfg.get("domain")),
        "catalog_text": illustrate.catalog_text(cfg.get("domain")),
        "run_dir": rd,
        "ill_dir": rd / "illustrations",
        "source_numbers": source_number_set(rd, layer),
    }
    targets = [node] if node else order
    pending: list[Path] = []
    done: dict[str, tuple] = {}
    for nid in targets:
        if nid not in nodes:
            raise KeyError(f"unknown node {nid}")
        try:
            res, attempts = build_node(rd, cfg, layer, nodes[nid], pl[nid], ctx)
        except llm.PendingLLM as p:
            pending.append(p.path)
            continue
        done[nid] = write_step(rd, cfg, layer, nodes[nid], pl[nid], ctx, res) + (attempts,)

    # chapter-level files are rebuilt from all step files on disk (so --node runs keep the rest)
    collect(rd, layer, order, pending)
    return pending


def collect(rd: Path, layer: dict, order: list[str], pending: list[Path]) -> dict:
    """Merge per-step outputs into tasks.json / cards.json / course_report.json."""
    all_tasks, all_cards, report_nodes = [], [], []
    # per-step tasks/cards are stored next to the step so partial runs can be merged
    for nid in order:
        sp = rd / "steps" / f"{nid}.json"
        if not sp.exists():
            report_nodes.append({"node_id": nid, "status": "pending"})
            continue
        st = read_json(sp)
        tp = rd / "steps" / f"{nid}.tasks.json"
        if tp.exists():
            d = read_json(tp)
            all_tasks += d["tasks"]
            all_cards += d["cards"]
        report_nodes.append({"node_id": nid, "status": "ok" if not st["checks"]["errors"] else "errors", "title": st["title_beginner"], "tasks": len(st["task_ids"]), "illustrations": len(st["illustrations"]), "errors": st["checks"]["errors"], "warnings": st["checks"]["warnings"], "dropped_tasks": len(st["checks"].get("dropped_tasks", []))})
    types = sorted({t["type"] for t in all_tasks})
    chapter_errors = []
    if len(all_tasks) < MIN_TASKS_CHAPTER:
        chapter_errors.append(f"заданий {len(all_tasks)} < {MIN_TASKS_CHAPTER}")
    if len(types) < 4:
        chapter_errors.append(f"типов заданий {len(types)} < 4: {types}")
    dec_steps = []
    for nid in order:
        sp = rd / "steps" / f"{nid}.json"
        if sp.exists() and any(b["kind"] == "decision" for b in read_json(sp)["blocks"]):
            dec_steps.append(nid)
    if not dec_steps:
        chapter_errors.append("нет ни одного шага «решение на данных»")
    write_json(rd / "tasks.json", {"chapter": layer["chapter"], "tasks": all_tasks})
    write_json(rd / "cards.json", {"chapter": layer["chapter"], "cards": all_cards})
    report = {
        "chapter": layer["chapter"],
        "nodes": len(order),
        "steps_done": sum(1 for r in report_nodes if r["status"] != "pending"),
        "pending": [str(p) for p in pending],
        "tasks": len(all_tasks),
        "task_types": {t: sum(1 for x in all_tasks if x["type"] == t) for t in types},
        "cards": len(all_cards),
        "decision_steps": dec_steps,
        "chapter_errors": chapter_errors,
        "steps": report_nodes,
    }
    write_json(rd / "course_report.json", report)
    return report
