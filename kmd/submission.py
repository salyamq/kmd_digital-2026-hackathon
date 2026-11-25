"""Export generated course artifacts in the organizers' interchange schemas."""
from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path

from . import llm
from .config import read_json, run_dir, write_json

FORMATS = dict(short="шортс", long="длинное видео", interactive="интерактив",
               data_practice="практикум на данных", cards="карточки", text="текст")
CRITERIA = dict(time="time_change", invisible="invisible_visible", scale="scale_jump",
                counterintuitive="counterintuitive", cause_effect="cause_effect")
SOURCE_KINDS = dict(formula="formula", table="table", problem="task", figure="figure_caption")
FRAME_ORIGINS = {"реальные данные": "code_from_data", "симуляция": "code_from_model",
                 "схема": "code_from_model", "иллюстрация ИИ": "ai_generated"}


def _claim_id(value):
    return re.sub(r"\.c(\d+)$", r"#c\1", value) if value else None


def _field(value, default_by="author"):
    if isinstance(value, dict):
        return {"text": value.get("text") or "", "by_model": value.get("by", default_by) == "model"}
    return {"text": str(value or ""), "by_model": default_by == "model"}


def _node(node, order, units):
    layers = node.get("layers", {})
    data = node.get("data_meaning") or {}
    analogy = node.get("it_analogy") or {}
    misconception = node.get("misconception")
    lens = node.get("inefficiency_lens")
    claims = []
    needs_scan = []
    for claim in node["claims"]:
        source_unit = next((units[uid] for uid in claim.get("unit_ids", []) if uid in units), {})
        claims.append(dict(claim, id=_claim_id(claim["id"]), page_pdf=claim["page"],
                           source_kind=SOURCE_KINDS.get(source_unit.get("kind"), "text"),
                           by_model=claim.get("by") == "model"))
    for uid in node.get("unit_ids", []):
        if units.get(uid, {}).get("ocr_suspect"):
            needs_scan.append({"page": units[uid]["page"], "what": units[uid]["kind"]})
    difficulty = {k: node["difficulty"][k] for k in ("primary", "secondary") if node["difficulty"].get(k)}
    main_data = [data.get(key) for key in ("text", "inputs", "outputs") if data.get(key)]
    return dict(
        node, order=order, title=node["title_beginner"], threshold=bool(node["difficulty"].get("threshold")),
        why_here=_field(node.get("order_rationale"), "model"), difficulty=difficulty,
        layers={
            "topic": _field(node.get("title_book")), "main": _field(node["claims"][0]),
            **{key: _field(layers.get(key)) for key in ("mechanism", "practice", "nuances")},
            "deeper": [dict(_field(part), title=part.get("title", "")) for part in layers.get("deeper", [])],
        },
        claims=claims, pages=sorted({claim["page_pdf"] for claim in claims}),
        links=[dict(link, target=link["to"], type={"example": "example_of"}.get(link["type"], link["type"]))
               for link in node.get("links", [])],
        data_meaning={
            "from_chapter": _field(" ".join(main_data), data.get("by", "model")),
            "breaks": _field(data.get("breaks_where"), data.get("by", "model")),
            "hypotheses": [dict(_field(part, "model"), hypothesis=True) for part in data.get("hypotheses", [])],
        },
        it_analogy={**_field(analogy, "model"), "breaks_where": analogy.get("breaks_where") or ""},
        terms_introduced=[t["term"] for t in node.get("terms", [])], needs_scan=needs_scan,
        misconception={**misconception, **_field(misconception), "ref": misconception.get("ref")} if misconception else None,
        now_practice=_field(node["current_practice"], "model") if node.get("current_practice") else None,
        inefficiency_lens={**lens, "by_model": lens.get("by") == "model"} if lens else None,
        worked_examples=[dict(item, page_pdf=item["page"]) for item in node.get("worked_examples", [])],
        book_tasks=[dict(item, number=str(item.get("number") or ""), page_pdf=item["page"])
                    for item in node.get("book_problems", [])],
    )


def _coverage(chapter, rows, nodes, units):
    node_ids = defaultdict(list)
    for node in nodes:
        for uid in node.get("unit_ids", []):
            node_ids[uid].append(node["id"])
    kinds = dict(example="worked_example", problem="task", list="paragraph", fragment="paragraph")
    return {"chapter": chapter, "rows": [{
        "unit_id": row["unit_id"], "kind": kinds.get(row["kind"], row["kind"]), "page_pdf": row["page"],
        "excerpt": units[row["unit_id"]]["text"][:180],
        "node_ids": node_ids.get(row["unit_id"]) or ([row["node_id"]] if row.get("node_id") else []),
        "reason": row.get("reason"),
    } for row in rows]}


def _task(task):
    kind = task["type"]
    prompt = task["question"]
    opts = task.get("items", []) if kind == "order" else task.get("options", [])
    options = [{"id": f"o{i + 1}", "text": value} for i, value in enumerate(opts)]
    if kind in ("single", "multiple"):
        good = [options[i]["id"] for i in task["correct"]]
        answer = good[0] if kind == "single" else good
    elif kind == "order":
        answer = [o["id"] for o in options]
    elif kind == "cloze":
        slots = iter(range(1, len(task["blanks"]) + 1))
        prompt = re.sub(r"___", lambda _: "{{" + str(next(slots)) + "}}", task["text"])
        answer = [blank["answers"][0] for blank in task["blanks"]]
    else:
        answer = task["answer"]
    return dict(task, type={"cloze": "gap", "numeric": "calc"}.get(kind, kind), step_id=task["node_id"],
                claim_ids=[_claim_id(task["claim_id"])], prompt=prompt, options=options, answer=answer)


def _illustrations(chapter, steps):
    illustrations = []
    for step in steps:
        for art in step["illustrations"]:
            redrawn = art.get("redrawn_from")
            label = art["provenance"]
            if label not in FRAME_ORIGINS and redrawn:
                label = "реальные данные"
            illustrations.append(dict(
                art, id=f"{step['node_id']}.{art['id']}", step_id=step["node_id"], node_id=step["node_id"],
                file=Path("illustrations", Path(art["file"]).name).as_posix(),
                origin="redrawn_from_book" if redrawn else FRAME_ORIGINS[label],
                frame_class=art["class"], label=label, claim_ids=[_claim_id(c) for c in art.get("claim_ids", [])],
            ))
    return {"chapter": chapter, "illustrations": illustrations}


def _text(value):
    return str(value.get("text") or value.get("question") or "") if isinstance(value, dict) else str(value or "")


def _video(passport, rd, prefix):
    script = []
    source_entries = {}
    for line in passport["script"]:
        ids = list(line.get("claim_ids", []))
        for source in line.get("sources", []):
            if claim := source.get("claim_id"):
                ids.append(claim)
                source_entries[claim] = source
        script.append({
            **line, "t_start": line.get("start", line.get("t0")), "t_end": line.get("end", line.get("t1")),
            "claim_id": _claim_id(ids[0]) if ids else None, "claim_ids": [_claim_id(c) for c in ids],
            "on_screen": line.get("caption") or "",
        })
    source_entries.update({s["claim_id"]: s for s in passport.get("sources", []) if s.get("claim_id")})
    sources = [{"claim_id": _claim_id(claim), "page_or_dataset": str(s.get("page") or s.get("dataset") or ""),
                "quote": s.get("quote") or ""} for claim, s in source_entries.items()]
    frames = [
        {**frame, "t": frame.get("start", frame.get("t0")),
         "label": frame.get("label") or frame.get("provenance_label") or frame.get("provenance")}
        for frame in passport["frames"]
    ]
    checklist = [
        {"item": row["item"], "answer": "да" if row["ok"] else "нет", "note": row.get("note") or ""}
        for row in passport.get("physics_checklist", []) if "ok" in row
    ]
    if passport.get("speech_check"):
        audio = {**passport.get("metrics", {}), **passport["speech_check"], "voice": passport.get("tools", {}).get("tts")}
    else:
        audio = {**passport.get("metrics", {}), "voice": passport.get("voice")}
    specs_name = f"{prefix}.scenes.json"
    bridge = passport.get("data_it_bridge")
    if isinstance(bridge, dict):
        bridge = " ".join([bridge.get("where_in_data", ""), bridge.get("manual_work", ""), *bridge.get("hypotheses", [])])
    specs = passport.get("scene_spec")
    if not specs:
        work = (rd / passport.get("build_directory", "")).resolve()
        specs = []
        for scene in passport.get("scene_specs", []):
            path = (work / scene["file"]).resolve()
            if path.is_relative_to(rd.resolve()) and path.suffix == ".json" and path.is_file():
                scene = read_json(path)
            specs.append(scene)
        if not checklist:
            checklist = [{"item": item, "answer": "н/п"}
                         for item in dict.fromkeys(rule for scene in specs for rule in scene.get("invariants", []))]
    result = {
        "video_id": passport.get("video_id") or f"{passport['node_id']}.{passport.get('format', 'short')}",
        "node_id": passport["node_id"], "node_card": passport["node_card"], "script": script, "sources": sources,
        "scene_spec": specs_name, "frames": frames, "physics_checklist": checklist, "audio_check": audio,
        "exaggerations": [x.get("what", "") if isinstance(x, dict) else str(x) for x in passport.get("exaggerations", [])],
        "prediction_question": _text(passport.get("prediction_question") or passport.get("prediction")),
        "transfer_question": _text(passport.get("transfer_question")), "data_it_bridge": bridge or "",
    }
    return result, specs_name, specs


def export(chapter: str, out: str | None = None) -> Path:
    rd = run_dir(chapter)
    target = Path(out) if out else rd / "submission"
    layer = read_json(rd / "layer.json")
    units = {u["id"]: u for u in read_json(rd / "units.json")["units"]}
    by_id = {node["id"]: node for node in layer["nodes"]}
    ordered = list(dict.fromkeys([*layer.get("order", []), *by_id]))
    nodes = [_node(by_id[nid], i, units) for i, nid in enumerate(ordered, 1)]
    cid = layer["chapter"]
    routes = read_json(rd / "routing.json")
    files = {
        "layer.json": ("node", {"chapter": cid, "source": f"{layer['author']}, «{layer['book']}»",
                                "pdf_pages": [str(page) for page in layer["pages"]], "nodes": nodes}),
        "coverage.json": ("coverage", _coverage(cid, read_json(rd / "coverage.json"), nodes, units)),
        "routing.json": ("routing", {"chapter": cid, "routes": [
            dict(r, format=FORMATS[r["format"]], why=r["rationale"], template=r.get("scene_template"),
                 hook_short=r.get("hook_only", False),
                 video_scores={k: int(v in r["video_criteria"]) for k, v in CRITERIA.items()})
            for r in routes
        ]}),
    }
    artifacts = []
    tasks_path = rd / "tasks.json"
    if tasks_path.is_file():
        files["tasks.json"] = ("task", {"chapter": cid, "tasks": [_task(t) for t in read_json(tasks_path)["tasks"]]})
        steps = [read_json(f) for f in sorted((rd / "steps").glob("*.json")) if not f.name.endswith(".tasks.json")]
        files["illustrations.json"] = ("illustration", _illustrations(cid, steps))
        artifacts = [rd / art["file"] for step in steps for art in step["illustrations"]]
    for f in sorted(rd.glob("video/*/passport*.json")):
        video, spec_name, spec = _video(read_json(f), rd, f.stem)
        folder = Path("video", f.parent.name)
        files[folder / f.name] = ("passport", video)
        files[folder / spec_name] = (None, spec)
    for schema, result in files.values():
        if schema:
            llm.validate(result, llm.load_schema(f"organizer/{schema}"))
    for name, (_, result) in files.items():
        write_json(target / name, result)
    for path in artifacts:
        dest = target / "illustrations" / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() != dest.resolve():
            shutil.copy2(path, dest)
    return target
