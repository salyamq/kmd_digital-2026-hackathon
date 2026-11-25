"""Video passport (brief section 7)."""
from pathlib import Path

from .util import read_json, write_json, read_calls, file_hash, log


def build_passport(P):
    script = read_json(P.p("01_script.json"))
    shotlist = read_json(P.p("02_shotlist.json"))
    tl = read_json(P.p("timeline.json"))
    st = read_json(P.p("source_table.json"), []) or []
    qa = read_json(P.p("qa.json"), []) or []
    cov = read_json(P.p("coverage_report.json"), {}) or {}
    metrics = read_json(P.p("metrics.json"), {}) or {}
    audio = read_json(P.p("06_audio", "audio.json"), {}) or {}
    manual = read_json(P.p("manual_log.json"), {}) or {}
    calls = read_calls(P.dir)
    specs = P.specs()
    node = P.node
    shots_t = {s["id"]: s for s in tl["shots"]}
    frames = []
    exaggerations = []
    for sh, sp in zip(shotlist["shots"], specs):
        ai = read_json(P.p("05_renders", f"{sh['id']}.ai.json"))
        t = shots_t[sh["id"]]
        frames.append({"shot": sh["id"], "t0": t["start"], "t1": t["end"], "class": sh["class"],
                       "template": sh["template"], "method": "ai_clip" if ai else "render2d (Cairo draw-list)",
                       "provenance_label": P.T()["provenance"].get(sp.get("provenance"), sp.get("provenance")),
                       "state_model": (sp.get("model") or {}).get("type"),
                       "ai": ({k: ai.get(k) for k in ("provider", "model", "seed", "seconds", "cost_usd", "prompt",
                                                      "first_frame", "last_frame")} if ai else None)})
        for e in (sh.get("exaggerations") or []) + (sp.get("exaggerations") or []):
            exaggerations.append({"shot": sh["id"], "what": e})
        if sh["template"] == "depth_track" and (sp.get("params") or {}).get("particles"):
            exaggerations.append({"shot": sh["id"], "what": "Particles are a symbolic depiction of radiation "
                                  "quanta; their density follows the measured curve value, not a physical count."})
        if sh["template"] == "depth_track":
            exaggerations.append({"shot": sh["id"], "what": "Cutaway is zoomed and not to scale horizontally; "
                                  "borehole and tool widths exaggerated for visibility."})
        if sh["template"] == "field_evolution":
            exaggerations.append({"shot": sh["id"], "what": "Model time is mapped to video time (log scale if the "
                                  "grid is log-spaced): seconds of video ≠ seconds of reservoir time."})
        if sh["template"] in ("pore_scale", "inset_callouts"):
            exaggerations.append({"shot": sh["id"], "what": "2D slice of a 3D grain pack; grains drawn as discs."})
    secs = metrics.get("machine_seconds", {})
    money = sum((c.get("cost_usd") or 0) for c in calls)
    by_cur = {}
    for c in calls:
        if c.get("cost_usd") is not None:
            by_cur["USD"] = by_cur.get("USD", 0) + c["cost_usd"]
        elif c.get("cost") is not None:
            by_cur[c.get("currency") or "?"] = by_cur.get(c.get("currency") or "?", 0) + c["cost"]
    unknown_cost = any(c.get("cost_usd") is None and c.get("cost") is None for c in calls)
    dur_min = tl["duration"] / 60
    person = float(manual.get("person_minutes", 0))
    mentor = float(manual.get("mentor_minutes", 0))
    machine_min = sum(secs.values()) / 60
    passport = {
        "video_id": P.brief["video_id"],
        "rebuild_command": f"python -m vidpipe rebuild {P.dir}",
        "rebuild_from_scratch_command": P.brief.get("cmdline"),
        "output": str(P.p("08_final", f"{P.brief['video_id']}.mp4")),
        "format": {"name": P.brief["format"], "size": P.brief["size"], "fps": P.fmt["fps"],
                   "duration_s": tl["duration"], "style": P.brief.get("style")},
        "node_card": {"node_id": node["id"], "title": node["title"], "difficulty_types": node["difficulty"],
                      "misconception_fixed": node.get("misconception"), "lang": P.lang,
                      "source": node.get("source"), "node_file_sha1": file_hash(P.brief["node"])},
        "script": [{"id": l["id"], "role": l["role"], "text": l["text"], "t0": tl["lines"][l["id"]][0],
                    "t1": tl["lines"][l["id"]][1], "sources": l.get("sources", []),
                    "asserts_fact": l.get("asserts_fact")} for l in script["lines"]],
        "source_table": st,
        "scene_specs": [{"shot_id": sp["shot_id"], "file": f"03_scene_specs/{sp['shot_id']}.json",
                         "template": sp["template"], "class": sp["class"], "model": sp.get("model"),
                         "invariants": sp.get("invariants", []), "assumptions": sp.get("assumptions", [])}
                        for sp in specs],
        "frames": frames,
        "exaggerations": exaggerations,
        "prediction_question": script.get("prediction_question"),
        "transfer_question": script.get("transfer_question"),
        "data_it_bridge": script.get("data_it_bridge"),
        "metrics": {"person_minutes": person, "machine_minutes": round(machine_min, 2),
                    "machine_seconds_by_stage": secs, "money_usd": round(money, 4),
                    "money_by_currency": {k: round(v, 4) for k, v in by_cur.items()},
                    "tts_chars": sum(c.get("chars", 0) for c in calls if c.get("kind") == "tts"),
                    "tts_audio_s": round(sum(c.get("audio_s", 0) for c in calls if c.get("kind") == "tts"), 1),
                    "money_note": "some external calls have unknown cost" if unknown_cost else
                    ("no paid external calls" if not calls else "sum of logged calls"),
                    "cost_per_minute_usd": round(money / dur_min, 4) if dur_min else None,
                    "manual_share": round(person / (person + machine_min), 3) if (person + machine_min) else 0.0,
                    "mentor_minutes": mentor, "external_calls": calls},
        "tools": {"planner": script.get("planner"), "tts": {k: audio.get(k) for k in ("provider", "voice", "role", "speed", "rate", "numbers")},
                  "renderer": "vidpipe.render2d (Cairo) — deterministic, from scene specs",
                  "text_layer": "vidpipe.overlays (PIL glyphs + Cairo) composited at compose time",
                  "encoder": "ffmpeg libx264 / AAC", "ai_video": P.brief.get("ai_video")},
        "qa_summary": {k: sum(1 for r in qa if r["status"] == k) for k in ("pass", "fail", "warn", "manual", "info")},
        "qa_failures": [f"{r['id']}: {r['text']} — {r.get('details', '')}" for r in qa if r["status"] == "fail"],
        "coverage_gaps": cov.get("gaps", []),
        "open_questions": [r.get("ref") or r.get("param") for r in st if r["kind"] == "assumption"],
        "datasets": sorted({f"{r.get('ref')} · {r.get('file')}" for r in st if r["kind"] == "dataset"}),
    }
    write_json(P.p("passport.json"), passport)
    log("passport written", "ok")
    return passport
