"""Stage 2: format routing. layer.json + domain difficulty types -> routing.json.

One LLM request per chapter (prompts/route_format.md) proposes a format per node; code enforces the
TZ constraints (>=1 data_practice node, video share, hooks <= 20 % of videos, no tables/formulas in shorts).
"""
from __future__ import annotations

from pathlib import Path

from .. import llm
from ..config import chapter_config, domain_pack, read_json, run_dir, write_json

FORMATS = ["short", "long", "interactive", "data_practice", "cards", "text"]
VIDEO = {"short", "long"}


def node_features(n: dict) -> list[str]:
    f = []
    if n.get("worked_examples"):
        f.append(f"примеры автора: {len(n['worked_examples'])}")
    if n.get("procedure"):
        f.append(f"процедура: {len(n['procedure'])} шагов")
    if n.get("formulas"):
        f.append(f"формулы: {len(n['formulas'])}")
    if n.get("tables"):
        f.append(f"таблицы: {len(n['tables'])}")
    if n.get("figures"):
        f.append("рисунки: " + ", ".join(fi.get("number", "") for fi in n["figures"]))
    if n.get("book_problems"):
        f.append(f"задачи книги: {len(n['book_problems'])}")
    if n.get("misconception"):
        f.append("исправляет заблуждение: " + n["misconception"]["text"])
    if (n.get("difficulty") or {}).get("threshold"):
        f.append("пороговая идея")
    f.append(f"утверждений: {len(n.get('claims', []))}")
    return f


def _vars(cfg, layer, pack) -> dict:
    dt = pack.get("difficulty_types", {})
    nodes = []
    for n in layer["nodes"]:
        d = n["difficulty"]
        nodes.append({
            "id": n["id"],
            "difficulty": d["primary"] + ("/" + d["secondary"] if d.get("secondary") else ""),
            "title": f"{n['title_beginner']} ({n['title_book']})",
            "features": "; ".join(node_features(n)),
            "gist": (n["layers"]["mechanism"]["text"])[:400],
        })
    return {
        "audience": pack.get("pack", {}).get("audience", ""),
        "formats": dt.get("formats", {}),
        "video_criteria": dt.get("video_criteria", {}),
        "difficulty_types": dt.get("types", {}),
        "chapter_title": cfg.get("title", ""),
        "nodes": nodes,
    }


SCHEMA = {
    "type": "object", "required": ["routes"],
    "properties": {"routes": {"type": "array", "items": {
        "type": "object",
        "required": ["node_id", "format", "video_criteria", "scene_template", "hook_only", "rationale"],
        "properties": {
            "node_id": {"type": "string"},
            "format": {"enum": FORMATS},
            "video_criteria": {"type": "array", "items": {"enum": ["time_change", "invisible_visible", "scale_jump", "counterintuitive", "cause_effect"]}},
            "scene_template": {"type": ["string", "null"]},
            "hook_only": {"type": "boolean"},
            "rationale": {"type": "string"},
        }}}},
}


def enforce(routes: list[dict], layer: dict) -> tuple[list[dict], list[str]]:
    """Apply TZ constraints in code. Returns (routes, notes about changes)."""
    notes = []
    by_id = {n["id"]: n for n in layer["nodes"]}
    for r in routes:
        n = by_id[r["node_id"]]
        if r["format"] in VIDEO and not r["video_criteria"]:
            notes.append(f"{r['node_id']}: video without video criteria -> interactive")
            r["format"] = "interactive"
        if r["format"] == "short" and (n.get("tables") or len(n.get("formulas", [])) >= 2):
            notes.append(f"{r['node_id']}: short with tables/formulas -> interactive")
            r["format"] = "interactive"
        if r["format"] not in VIDEO:
            r["hook_only"] = False
    if not any(r["format"] == "data_practice" for r in routes):
        # the node with most worked examples (then procedure) becomes the data-decision step
        cand = sorted(routes, key=lambda r: (-len(by_id[r["node_id"]].get("worked_examples", [])),
                                              -len(by_id[r["node_id"]].get("procedure", []))))
        if cand:
            notes.append(f"{cand[0]['node_id']}: no data_practice in chapter -> data_practice")
            cand[0]["format"] = "data_practice"
            cand[0]["hook_only"] = False
    vids = [r for r in routes if r["format"] in VIDEO]
    hooks = [r for r in vids if r["hook_only"]]
    max_hooks = int(0.2 * len(vids))
    for r in hooks[max_hooks:]:
        r["hook_only"] = False
        notes.append(f"{r['node_id']}: hook share > 20 % -> hook_only=false")
    return routes, notes


def run(chapter: str, **kw) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    layer = read_json(rd / "layer.json")
    pack = domain_pack(cfg.get("domain", "geology"))
    try:
        res = llm.complete_json(rd, "route_format", "route_format", _vars(cfg, layer, pack), SCHEMA)
    except llm.PendingLLM as p:
        return [p.path]
    got = {r["node_id"]: r for r in res["routes"]}
    routes = []
    for n in layer["nodes"]:
        r = dict(got.get(n["id"]) or {"format": "text", "video_criteria": [], "scene_template": None,
                                       "hook_only": False, "rationale": "формат не предложен моделью — текст по умолчанию"})
        r["node_id"] = n["id"]
        r["difficulty"] = n["difficulty"]
        routes.append(r)
    routes, notes = enforce(routes, layer)
    out = [{k: r[k] for k in ("node_id", "format", "difficulty", "video_criteria", "scene_template", "hook_only", "rationale")}
           for r in routes]
    write_json(rd / "routing.json", out)
    from collections import Counter

    c = Counter(r["format"] for r in out)
    if notes:
        write_json(rd / "routing_notes.json", notes)
    print(f"[route] {cfg['id']}: {dict(c)}; code adjustments: {len(notes)}")
    return []
