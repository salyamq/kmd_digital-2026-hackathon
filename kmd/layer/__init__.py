"""Stage 1: learning layer.

units.json --(layer_extract per chunk, LLM)--> draft nodes + skipped units
           --(layer_graph per chapter, LLM)--> order, parts, links, order_rationale, merges
           --(code)--> layer.json (schemas/layer.schema.json), coverage.json; overrides applied last.

Code (not the LLM) fills everything that can be copied from the source: problem texts, table cells,
figure captions, pages of examples, ids. The LLM only writes what needs understanding.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import edits, llm
from ..config import chapter_config, domain_pack, read_json, run_dir, write_json
from .terms import node_text, uses_term

SCHEMA_VERSION = "1.1"
CHUNK_CHARS = 9000          # source characters per extraction request
AUTO_KINDS = {"heading", "fragment"}  # covered by code, not by the LLM


# ------------------------------------------------------------------ chunking

def _unit_len(u: dict) -> int:
    return len(u["text"]) + min(len(u.get("description") or ""), 700)


def make_chunks(units: list[dict], budget: int = CHUNK_CHARS) -> list[list[dict]]:
    """Group units into chunks: whole small sections together, big sections split at headings/paragraphs."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    by_sec: list[list[dict]] = []
    for u in units:
        if by_sec and by_sec[-1][0]["section_code"] == u["section_code"]:
            by_sec[-1].append(u)
        else:
            by_sec.append([u])
    for sec in by_sec:
        ssize = sum(_unit_len(u) for u in sec)
        if cur and size + ssize <= budget:
            cur.extend(sec)
            size += ssize
            continue
        if cur:
            chunks.append(cur)
            cur, size = [], 0
        if ssize <= budget:
            cur, size = list(sec), ssize
            continue
        # split a big section
        n_parts = max(2, round(ssize / budget + 0.49))
        target = ssize / n_parts
        part: list[dict] = []
        psize = 0
        for i, u in enumerate(sec):
            ul = _unit_len(u)
            if part and ((psize >= target and _good_cut(sec, i)) or psize + ul > budget * 1.3):
                chunks.append(part)
                part, psize = [], 0
            part.append(u)
            psize += ul
        if part:
            cur, size = part, psize
    if cur:
        chunks.append(cur)
    return chunks


def _good_cut(sec: list[dict], i: int) -> bool:
    """Cut before unit i if it starts a new topic (heading, or a paragraph after a non-example)."""
    u, prev = sec[i], sec[i - 1]
    if u["kind"] == "heading":
        return True
    if prev["kind"] == "heading":
        return False
    if u["kind"] in ("example", "problem", "formula", "figure", "table", "list"):
        return False
    return u["kind"] == "paragraph" and prev["kind"] in ("paragraph", "problem", "figure", "table")


# ------------------------------------------------------------------ prompt variables

def _pages_str(u: dict) -> str:
    return f"{u['page']}–{u['page_end']}" if u.get("page_end") else str(u["page"])


def _display_text(u: dict) -> str:
    t = u["text"]
    for b in sorted(u.get("page_breaks", []), key=lambda x: -x["offset"]):
        t = t[: b["offset"]] + f"⟦стр. {b['page']}⟧ " + t[b["offset"]:]
    return t


def _extra(u: dict) -> str:
    ex = []
    if u.get("figure_no"):
        ex.append(f"рис. {u['figure_no']}")
    if u.get("table_no"):
        ex.append(f"табл. {u['table_no']}")
    if u.get("example_no"):
        ex.append(f"пример {u['example_no']}")
    if u.get("problem_no"):
        ex.append(f"задача {u['problem_no']}")
    if u.get("ocr_suspect"):
        ex.append("ТЕКСТ ПОВРЕЖДЁН РАСПОЗНАВАНИЕМ — не цитировать, восстановить смысл по контексту нельзя")
    return ", ".join(ex)


def _pack_vars(pack: dict) -> dict:
    meta = pack.get("pack", {})
    mis = pack.get("misconceptions", {})
    mis = mis.get("items", mis) if isinstance(mis, dict) else mis
    itb = pack.get("it_bridges", {})
    itb = itb.get("items", itb) if isinstance(itb, dict) else itb
    dt = pack.get("difficulty_types", {}).get("types", {})
    return {
        "domain_name": meta.get("name", meta.get("id", "")),
        "audience": meta.get("audience", "новички"),
        "difficulty_types": dt,
        "misconceptions": mis,
        "it_bridges": itb,
        "personas": pack.get("personas", ""),
    }


def _book_str(cfg: dict) -> str:
    b = cfg.get("book", {})
    return f"{b.get('author', '')}, «{b.get('title', '')}» ({b.get('year', '')})".strip(", ")


def _pages_range(cfg: dict) -> str:
    return ", ".join(f"{a}–{b}" for a, b in (s["pages"] for s in cfg.get("segments", [])))


# ------------------------------------------------------------------ stage

def extract_requests(chapter: str):
    """Yield (chunk_index, chunk_units, variables) for every extraction request of the chapter."""
    cfg = chapter_config(chapter)
    U = read_json(run_dir(chapter) / "units.json")
    pack = domain_pack(cfg.get("domain", "geology"))
    pv = _pack_vars(pack)
    chunks = make_chunks(U["units"])
    sec_titles = {s["code"]: s["title"] for s in U["sections"]}
    seen_parts: dict[str, int] = {}
    for i, ch in enumerate(chunks):
        codes = list(dict.fromkeys(u["section_code"] for u in ch))
        first = codes[0]
        seen_parts[first] = seen_parts.get(first, 0) + 1
        must = [u["id"] for u in ch if u["kind"] not in AUTO_KINDS]
        units_v = [
            {"id": u["id"], "pages": _pages_str(u), "kind": u["kind"], "extra": _extra(u),
             "text": _display_text(u) if not u.get("ocr_suspect") else u["text"][:300] + " …",
             "description": (u.get("description") or "")[:700] + ("…" if len(u.get("description") or "") > 700 else "")}
            for u in ch
        ]
        variables = {
            **pv,
            "chapter_types": cfg.get("difficulty_types", []),
            "book": _book_str(cfg),
            "chapter_title": cfg.get("title", U.get("title", "")),
            "pages": _pages_range(cfg),
            "sections": U["sections"],
            "chunk_no": i + 1,
            "chunk_total": len(chunks),
            "section_code": ", ".join(codes),
            "section_title": " / ".join(sec_titles.get(c, c) for c in codes),
            "part_of_section": seen_parts[first] if seen_parts[first] > 1 else 0,
            "units": units_v,
            "must_cover": must,
        }
        yield i, ch, variables


def run(chapter: str, **kw) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    U = read_json(rd / "units.json")
    pack = domain_pack(cfg.get("domain", "geology"))
    prefix = pack.get("pack", {}).get("id_prefix", cfg.get("domain", "x")[:3])

    reqs = list(extract_requests(chapter))
    calls = [
        (lambda v=v, i=i: llm.complete_json(rd, f"layer_extract_{i + 1:02d}", "layer_extract", v, "layer_extract"))
        for i, _, v in reqs
    ]
    results, pending = llm.gather(calls)
    if pending:
        return pending

    drafts, skipped = _collect_drafts(reqs, results)
    graph_vars = _graph_vars(cfg, U, drafts, pack)
    try:
        graph = llm.complete_json(rd, "layer_graph", "layer_graph", graph_vars, "layer_graph")
    except llm.PendingLLM as p:
        return [p.path]

    layer, coverage = assemble(cfg, U, drafts, skipped, graph, prefix)
    layer, applied = edits.apply_overrides(cfg["id"], layer)
    if applied:
        layer["overrides_applied"] = applied
    write_json(rd / "layer.json", layer)
    write_json(rd / "coverage.json", coverage)
    try:
        llm.validate(layer, llm.load_schema("layer"))
    except Exception as e:  # reported by verify as a hard error too
        print(f"[layer] WARNING: layer.json does not match schema: {str(e)[:300]}")
    n_cov = sum(1 for c in coverage if c["node_id"] or c["reason"])
    print(f"[layer] {cfg['id']}: {len(layer['nodes'])} nodes, {sum(len(n['claims']) for n in layer['nodes'])} claims, "
          f"coverage {n_cov}/{len(coverage)}")
    return []


# ------------------------------------------------------------------ assembly

def _collect_drafts(reqs, results):
    drafts, skipped = [], {}
    for (i, ch, _v), res in zip(reqs, results):
        chunk_ids = {u["id"] for u in ch}
        for n in res["nodes"]:
            n = dict(n)
            n["key"] = f"c{i + 1}.{n['key']}"
            n["unit_ids"] = [x for x in n["unit_ids"] if x in chunk_ids]
            n["_chunk"] = i
            drafts.append(n)
        for s in res.get("skipped", []):
            if s["unit_id"] in chunk_ids:
                skipped[s["unit_id"]] = s["reason"]
    return drafts, skipped


def _graph_vars(cfg, U, drafts, pack) -> dict:
    defined = {}
    for n in drafts:
        for t in n.get("terms", []):
            defined.setdefault(t["term"], n["key"])
    nodes_v = []
    for n in drafts:
        txt = node_text(n)
        uses = sorted({t for t, k in defined.items() if k != n["key"] and uses_term(txt, t)})
        gist = " ".join(c["text"] for c in n["claims"][:4])
        extras = []
        if n.get("worked_examples"):
            extras.append(f"примеров: {len(n['worked_examples'])}")
        if n.get("book_problems"):
            extras.append(f"задач: {len(n['book_problems'])}")
        if n.get("misconception"):
            extras.append(f"заблуждение: {n['misconception']['text']}")
        nodes_v.append({
            "key": n["key"], "section_code": n["section_code"],
            "difficulty": n["difficulty"]["primary"] + ("/" + n["difficulty"]["secondary"] if n["difficulty"].get("secondary") else ""),
            "title_book": n["title_book"], "title_beginner": n["title_beginner"],
            "terms": [t["term"] for t in n.get("terms", [])], "uses": uses[:12],
            "gist": gist[:600], "extras": "; ".join(extras),
        })
    return {
        "audience": pack.get("pack", {}).get("audience", "новички"),
        "chapter_title": cfg.get("title", ""),
        "book": _book_str(cfg),
        "pages": _pages_range(cfg),
        "nodes": nodes_v,
    }


def parse_md_table(text: str) -> tuple[list[str], list[list[str]], str]:
    """Markdown table (possibly with caption lines before it) -> (columns, rows, caption)."""
    cap, rows = [], []
    for line in text.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            if not rows:
                cap.append(s)
            continue
        if re.fullmatch(r"\|[\s\-:|]+\|?", s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return [], [], " ".join(cap).strip()
    cols = rows[0]
    width = max(len(r) for r in rows)
    cols = cols + [""] * (width - len(cols))
    body = [r + [""] * (width - len(r)) for r in rows[1:]]
    return cols, body, " ".join(c.strip("* ") for c in cap if c).strip()


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _merge_nodes(a: dict, b: dict) -> dict:
    out = dict(a)
    for k in ("unit_ids", "claims", "worked_examples", "book_problems", "terms", "formulas", "tables", "figures", "procedure"):
        out[k] = list(a.get(k) or []) + list(b.get(k) or [])
    for k in ("mechanism", "practice", "nuances"):
        ta, tb = a["layers"][k]["text"], b["layers"][k]["text"]
        out["layers"] = dict(out["layers"])
        out["layers"][k] = {"text": (ta + " " + tb).strip(), "by": "author" if "author" in (a["layers"][k]["by"], b["layers"][k]["by"]) else "model"}
    out["layers"]["deeper"] = list(a["layers"].get("deeper", [])) + list(b["layers"].get("deeper", []))
    if not out.get("misconception") and b.get("misconception"):
        mc = dict(b["misconception"])
        off = len(a["claims"])
        mc["claim_ids"] = [str(int(x) + off) for x in mc.get("claim_ids", []) if str(x).isdigit()]
        out["misconception"] = mc
    return out


def assemble(cfg, U, drafts, skipped, graph, prefix):
    units = {u["id"]: u for u in U["units"]}
    by_key = {n["key"]: n for n in drafts}
    # merges
    for m in graph.get("merge", []) or []:
        a, b = by_key.get(m["into"]), by_key.get(m["from"])
        if a and b and a is not b:
            by_key[m["into"]] = _merge_nodes(a, b)
            by_key[m["from"]] = None  # type: ignore
    alive = [k for k, v in by_key.items() if v is not None]
    merged_from = {m["from"]: m["into"] for m in graph.get("merge", []) or [] if m.get("from") in by_key}
    # order: graph order first, then any forgotten keys in book order
    order_keys = []
    for k in graph.get("order", []):
        k = merged_from.get(k, k)
        if k in alive and k not in order_keys:
            order_keys.append(k)
    for k in alive:
        if k not in order_keys:
            order_keys.append(k)
    # ids: <prefix>.<chapter>.<section_code>.<nn>, nn counted per section in book order (stable)
    key2id: dict[str, str] = {}
    per_sec: dict[str, int] = {}
    known = {s["code"] for s in U["sections"]}
    for k in alive:  # book order
        n = by_key[k]
        # section code comes from the node's first unit (the LLM's section_code is only a fallback)
        first_u = next((units[u] for u in n["unit_ids"] if u in units), None)
        sc = first_u["section_code"] if first_u else n.get("section_code", "")
        if sc not in known:
            alt = "s" + re.sub(r"[^0-9]+", "_", sc).strip("_")
            sc = alt if alt in known else sc
        sc = re.sub(r"[^a-z0-9_]", "", sc.lower()) or "s0"
        n["section_code"] = sc
        per_sec[sc] = per_sec.get(sc, 0) + 1
        key2id[k] = f"{prefix}.{cfg['id']}.{sc}.{per_sec[sc]:02d}"
    for f, t in merged_from.items():
        key2id[f] = key2id.get(t, "")
    gnodes = {g["key"]: g for g in graph.get("nodes", [])}

    nodes = []
    for k in order_keys:
        d = by_key[k]
        nid = key2id[k]
        g = gnodes.get(k, {})
        nodes.append(_final_node(nid, d, g, units, key2id))
    order = [n["id"] for n in nodes]
    parts = []
    used = set()
    for i, p in enumerate(graph.get("parts", [])):
        ids = []
        for k in p["node_keys"]:
            nid = key2id.get(merged_from.get(k, k))
            if nid and nid not in used and nid in order:
                ids.append(nid)
                used.add(nid)
        if ids:
            parts.append({"id": f"part{i + 1}", "title": p["title"], "node_ids": sorted(ids, key=order.index)})
    rest = [x for x in order if x not in used]
    if rest:
        if parts:
            parts[-1]["node_ids"] += rest
        else:
            parts.append({"id": "part1", "title": cfg.get("title", ""), "node_ids": rest})

    # coverage: every unit -> node or reason
    unit2node = {}
    for n in nodes:
        for uid in n["unit_ids"]:
            unit2node.setdefault(uid, n["id"])
    coverage = []
    ulist = U["units"]
    for idx, u in enumerate(ulist):
        nid = unit2node.get(u["id"])
        reason = None
        if not nid:
            if u["kind"] == "heading":
                # a heading belongs to the node of the next covered unit
                for v in ulist[idx + 1:]:
                    if unit2node.get(v["id"]):
                        nid = unit2node[v["id"]]
                        break
                reason = None if nid else "заголовок без содержания в главе"
            elif u["kind"] == "fragment":
                reason = "фрагмент подписи/надписи рисунка или служебная строка без самостоятельного смысла"
            elif u["id"] in skipped:
                reason = skipped[u["id"]]
            elif u.get("ocr_suspect"):
                reason = "текст повреждён распознаванием (см. скан страницы); смысл не восстанавливается из текста"
        coverage.append({"unit_id": u["id"], "page": u["page"], "kind": u["kind"], "node_id": nid, "reason": reason})

    layer = {
        "chapter": cfg["id"],
        "domain": cfg.get("domain", "geology"),
        "schema_version": SCHEMA_VERSION,
        "title": cfg.get("title", ""),
        "book": cfg.get("book", {}).get("title", ""),
        "author": cfg.get("book", {}).get("author", ""),
        "pages": [p for s in cfg.get("segments", []) for p in range(s["pages"][0], s["pages"][1] + 1)],
        "parts": parts,
        "nodes": nodes,
        "order": order,
        "graph_notes": graph.get("notes", ""),
    }
    return layer, coverage


def _final_node(nid: str, d: dict, g: dict, units: dict, key2id: dict) -> dict:
    claims = []
    for i, c in enumerate(d["claims"]):
        claims.append({
            "id": f"{nid}.c{i + 1:02d}", "kind": c["kind"], "text": c["text"], "quote": c["quote"],
            "page": int(c["page"]), "unit_ids": [u for u in c.get("unit_ids", []) if u in units] or d["unit_ids"][:1],
            "by": "author",
        })
    examples = []
    for i, e in enumerate(d.get("worked_examples", [])):
        uids = [u for u in e.get("unit_ids", []) if u in units]
        page = units[uids[0]]["page"] if uids else (units[d["unit_ids"][0]]["page"] if d["unit_ids"] else 0)
        nums = sorted(
            set(_NUM_RE.findall(" ".join([e["condition"], e["result"], *e["steps"]]))),
            key=lambda x: (float(x.replace(",", ".")), -len(x), x),
        )
        ex_no = next((units[u].get("example_no") for u in uids if units[u].get("example_no")), None)
        examples.append({
            "id": f"{nid}.e{i + 1:02d}", "page": page, "title": e["title"], "condition": e["condition"],
            "steps": e["steps"], "result": e["result"], "numbers": nums, "unit_ids": uids,
            "example_no": ex_no, "by": "author",
        })
    problems = []
    for p in d.get("book_problems", []):
        u = units.get(p["unit_id"])
        if not u:
            continue
        txt = re.sub(r"^\s*\d{1,3}[.)]\s*", "", u["text"]).strip()
        problems.append({
            "number": u.get("problem_no") or "", "text": txt, "figure": p.get("figure"), "page": u["page"],
            "unit_id": u["id"], "ocr_suspect": bool(u.get("ocr_suspect")),
        })
    tables = []
    for i, t in enumerate(d.get("tables", [])):
        u = units.get(t["unit_id"])
        if not u:
            continue
        cols, rows, cap = parse_md_table(u["text"])
        tables.append({
            "id": f"{nid}.t{i + 1:02d}", "number": u.get("table_no"), "caption": u.get("caption") or cap or "",
            "page": u["page"], "page_end": u.get("page_end", u["page"]), "columns": cols, "rows": rows,
            "ocr_fixes": t.get("ocr_fixes", []), "unit_id": u["id"],
        })
    figures = []
    for f in d.get("figures", []):
        u = units.get(f["unit_id"])
        if not u or u["kind"] != "figure":
            continue
        figures.append({
            "number": u.get("figure_no") or "", "page": u["page"], "caption": u["text"], "role": f["role"],
            "redraw": bool(f.get("redraw")), "unit_id": u["id"],
            "scan": f"pages/p{u['page']}.png",
        })
    formulas = []
    for i, f in enumerate(d.get("formulas", [])):
        formulas.append({
            "id": f"{nid}.f{i + 1:02d}", "latex": f["latex"], "meaning": f["meaning"],
            "vars": f.get("vars", []), "page": int(f["page"]), "unit_id": f.get("unit_id"),
        })
    mc = d.get("misconception")
    if mc:
        ids = []
        for x in mc.get("claim_ids", []):
            m = re.search(r"\d+", str(x))
            if m and 1 <= int(m.group()) <= len(claims):
                ids.append(claims[int(m.group()) - 1]["id"])
        mc = {**mc, "claim_ids": ids}
    links = []
    for l in g.get("links", []):
        to = key2id.get(l["to"])
        if to and to != nid and {"to": to, "type": l["type"]} not in links:
            links.append({"to": to, "type": l["type"]})
    dm = d["data_meaning"]
    return {
        "id": nid,
        "section": d["section_code"],
        "title_book": d["title_book"],
        "title_beginner": d["title_beginner"],
        "difficulty": d["difficulty"],
        "order_rationale": {"text": g.get("order_rationale", ""), "by": "model"},
        "layers": d["layers"],
        "procedure": d.get("procedure", []),
        "claims": claims,
        "worked_examples": examples,
        "book_problems": problems,
        "terms": d.get("terms", []),
        "formulas": formulas,
        "tables": tables,
        "figures": figures,
        "misconception": mc,
        "data_meaning": dm,
        "it_analogy": {**d["it_analogy"], "by": "model"},
        "current_practice": {**d["current_practice"], "by": "model"},
        "inefficiency_lens": d["inefficiency_lens"],
        "links": links,
        "unit_ids": d["unit_ids"],
        "pages": sorted({units[u]["page"] for u in d["unit_ids"] if u in units}),
    }
