"""Render a learning-layer node with the video branch's renderer."""
from __future__ import annotations

import os
import shutil

from ..config import ROOT, chapter_config, domain_dir, read_json, run_dir, write_json


def run(chapter: str, node: str, fmt: str, *, planner: str, tts: str) -> None:
    from video.vidpipe.cli import run_stages
    from video.vidpipe.pipeline import stage_brief
    from video.vidpipe.tts import available_provider

    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    layer = read_json(rd / "layer.json")
    nd = next((item for item in layer["nodes"] if item["id"] == node), None)
    if nd is None:
        raise ValueError(f"Unknown node {node!r} in {chapter}")
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg must be installed and available on PATH")
    if available_provider(tts) != tts:
        raise ValueError(f"TTS engine {tts!r} is unavailable; install it or select another with --tts")

    out = rd / "video" / node
    build = rd / "tmp" / "vidpipe" / node / fmt
    inputs = build / "inputs"
    pages = inputs / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    source_pages = read_json(rd / "source_pages.json")
    for old in pages.glob("p*.txt"):
        if str(int(old.stem[1:])) not in source_pages:
            old.unlink()
    for number, content in source_pages.items():
        (pages / f"p{int(number):03d}.txt").write_text(content, encoding="utf-8")

    book = cfg.get("book", {})
    difficulty = nd.get("difficulty") or {}
    misconception = nd.get("misconception") or {}
    data = nd.get("data_meaning") or {}
    analogy = nd.get("it_analogy") or {}
    node_file = inputs / "node.json"
    write_json(node_file, {
        **nd,
        "title": nd.get("title_beginner") or nd.get("title_book") or node,
        "lang": cfg.get("course_language") or layer.get("language") or cfg.get("language", "ru"),
        "source": {"title": layer.get("title") or cfg.get("title"), "book": book.get("title"),
                   "chapter": chapter, "pages": sorted({c["page"] for c in nd["claims"] if c.get("page")})},
        "difficulty_types": [difficulty[key] for key in ("primary", "secondary") if difficulty.get(key)],
        "misconception": {**misconception, "claim_id": next(iter(misconception.get("claim_ids") or []), None)},
        "what_it_means_for_data": data if data.get("claim_ids") else {},
        "data_meaning": {},
        "it_analogy": " ".join(filter(None, (analogy.get("text"), analogy.get("breaks_where")))),
        "formulas": [f for f in nd.get("formulas", []) if f.get("expr") and f.get("grid")],
    })

    product_settings = {
        "mode": planner, "model": os.environ.get("VIDPIPE_LLM_MODEL") or os.environ.get("KMD_LLM_MODEL"),
        "base_url": os.environ.get("VIDPIPE_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
    }
    stage_brief(build, node_file, pages, domain_dir(cfg.get("domain") or layer["domain"]),
                {"short": "short", "long": "explainer"}[fmt], "F", [ROOT / "video" / "data"],
                product_settings, {"provider": tts, "voice": os.environ.get("KMD_TTS_VOICE") if tts == "microsoft" else None},
                {"provider": "none"})
    run_stages(build)

    passport = read_json(build / "passport.json")
    narration = passport["tools"]["tts"]["provider"]
    speech_check = {"status": "skipped", "reason": "no Russian narration"}
    if narration != "none" and passport["node_card"]["lang"] == "ru":
        from .asr import check

        phrases = [{"id": line["id"], "text": line["text"], "start": line["t0"], "end": line["t1"]}
                   for line in passport["script"]]
        script_text = " ".join(p["text"] for p in phrases).casefold()
        terms = [term["term"] for term in nd.get("terms", []) if term["term"].casefold() in script_text]
        try:
            speech_check = check(build / "06_audio" / "narration.wav", phrases, terms)
        except Exception as exc:
            speech_check = {"status": "unavailable", "reason": str(exc)}
            print(f"[video] local speech verification unavailable: {exc}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "08_final" / f"{fmt}.mp4", out / f"{fmt}.mp4")
    # Vidpipe composites its own subtitles, so an old external track would be out of sync.
    (out / f"{fmt}.srt").unlink(missing_ok=True)
    write_json(out / f"passport.{fmt}.json", {
        **passport, "engine": "vidpipe", "node_id": node, "format": fmt,
        "vidpipe_format": passport["format"], "duration_s": passport["format"]["duration_s"],
        "output": f"{fmt}.mp4", "data_bridge": passport.get("data_it_bridge"),
        "speech_check": speech_check,
        "rebuild_from_scratch_command": f"python -m kmd video {chapter} {node} --format {fmt} --planner {planner} --tts {tts}",
        "build_directory": build.relative_to(rd).as_posix(),
    })
    if passport["qa_failures"]:
        print(f"[video] {node}: {len(passport['qa_failures'])} QA failures; see {build / 'qa_report.md'}")
    print(f"[video] {node}: {out / (fmt + '.mp4')}")
