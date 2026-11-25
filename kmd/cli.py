"""Command line: python -m kmd <command> ...

Stage modules live in kmd/<stage>/ and expose `run(chapter: str, **kwargs) -> list[Path]`
returning the list of pending LLM request files (empty when the stage completed).
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

from . import edits, llm
from .config import ROOT, RUNS, chapter_config, load_env, read_json, run_dir, write_json

STAGES = ["ingest", "layer", "verify", "route", "scenes", "course", "site"]
EXIT_PENDING = 3


def _stage(name: str):
    return importlib.import_module(f"kmd.{name}")


def _report_pending(pending: list[Path]) -> int:
    if not pending:
        return 0
    print(f"\n{len(pending)} LLM request(s) pending (provider=queue). Answer them with:")
    print("  python -m kmd llm pending        # list")
    print("  python -m kmd llm answer <pending.json> <response.json>")
    for p in pending[:20]:
        print("  ", Path(p).relative_to(ROOT) if Path(p).is_absolute() else p)
    return EXIT_PENDING


def cmd_stage(args) -> int:
    t0 = time.time()
    kwargs = {}
    if getattr(args, "node", None):
        kwargs["node"] = args.node
    pending = _stage(args.command).run(args.chapter, **kwargs) or []
    print(f"[{args.command}] {args.chapter}: done in {time.time()-t0:.1f}s, pending={len(pending)}")
    return _report_pending(pending)


def cmd_run(args) -> int:
    stages = STAGES
    if args.from_stage:
        stages = stages[stages.index(args.from_stage):]
    if args.to_stage:
        stages = stages[: stages.index(args.to_stage) + 1]
    scenes_requested = args.with_scenes or "scenes" in (args.from_stage, args.to_stage)
    video_jobs = getattr(args, "video_jobs", [])
    if getattr(args, "video_node", None):
        if "site" not in stages:
            raise ValueError("--video-node requires the run to include the site stage")
        video_jobs = [(args.video_node, args.video_format, args.video_engine)]
    started = time.monotonic()
    for s in stages:
        if s == "scenes" and not scenes_requested and llm.provider_name() == "queue":
            print(f"[scenes] {args.chapter}: using saved scenes and redraws (queue provider)")
            continue
        t0 = time.time()
        if s == "site":
            for node, fmt, engine in video_jobs:
                pending = _render_video(args, node, fmt, engine)
                if pending:
                    return _report_pending(pending)
        pending = _stage(s).run(args.chapter) or []
        print(f"[{s}] {args.chapter}: {time.time()-t0:.1f}s, pending={len(pending)}")
        if pending:
            return _report_pending(pending)
    output = RUNS / chapter_config(args.chapter)["id"]
    if stages == STAGES and output.is_dir():
        write_json(output / "run_timing.json", {"seconds": round(time.monotonic() - started, 3)})
    course_report = output / "course_report.json"
    if "course" in stages and course_report.exists():
        chapter_errors = read_json(course_report).get("chapter_errors", [])
        if chapter_errors:
            for error in chapter_errors:
                print(f"[course] ERROR {error}", file=sys.stderr)
            return 1
    if "site" in stages:
        print(f"OK: open {output / 'site' / 'index.html'}")
    return 0


def cmd_rebuild(args) -> int:
    """After an override: re-merge the layer and rebuild everything downstream."""
    args.from_stage = "layer"
    args.to_stage = None
    args.video_jobs = []
    if args.video:
        passports = sorted((run_dir(args.chapter) / "video").glob("*/passport*.json"))
        for p in passports:
            pas = read_json(p)
            # Re-render each video with the engine that made it: a rebuild must not silently swap a
            # checked video for one made by another engine.
            job = (pas["node_id"], pas.get("format", "short"), pas.get("engine") or "legacy")
            if job not in args.video_jobs:
                args.video_jobs.append(job)
    return cmd_run(args)


def cmd_llm(args) -> int:
    if args.llm_cmd == "pending":
        files = sorted(RUNS.glob(f"{args.chapter or '*'}/llm/pending/*.json"))
        for f in files:
            r = read_json(f)
            print(f"{f.relative_to(ROOT)}\t{r['task']}\t{len(r['user'])} chars")
        print(f"{len(files)} pending")
        return 0
    if args.llm_cmd == "show":
        r = read_json(args.file)
        print("=== SYSTEM ===\n" + r["system"] + "\n=== USER ===\n" + r["user"])
        if r.get("images"):
            print("=== IMAGES (look at each before answering) ===\n" + "\n".join(r["images"]))
        return 0
    if args.llm_cmd == "answer":
        out = llm.answer_pending(Path(args.file), Path(args.response))
        print(f"cached: {out.relative_to(ROOT)}")
        return 0
    if args.llm_cmd == "stats":
        tot: dict = {}
        for f in RUNS.glob("*/llm/*/*.json"):
            if f.parent.name == "pending":
                continue
            ch = f.parts[-4]
            d = read_json(f)
            s = tot.setdefault(ch, {"calls": 0, "in_chars": 0, "out_chars": 0})
            s["calls"] += 1
            s["in_chars"] += len(d["request"]["system"]) + len(d["request"]["user"])
            s["out_chars"] += len(json.dumps(d["response"], ensure_ascii=False))
        print(json.dumps(tot, ensure_ascii=False, indent=2))
        return 0
    return 1


def cmd_edit(args) -> int:
    rec = edits.log_edit(args.chapter, args.target, args.minutes, args.what, who=args.who, kind=args.kind)
    print(json.dumps(rec, ensure_ascii=False))
    return 0


def _render_video(args, node, fmt, engine=None):
    if (engine or args.video_engine) == "legacy":
        return _stage("video").run(args.chapter, node=node, fmt=fmt) or []
    from .video import vidpipe

    return vidpipe.run(args.chapter, node, fmt, planner=args.planner, tts=args.tts) or []


def cmd_video(args) -> int:
    pending = _render_video(args, args.node, args.format, args.video_engine)
    rd = run_dir(args.chapter)
    if not pending and any((rd / "steps").glob("*.json")):
        _stage("site").run(args.chapter)
    elif not pending:
        cmd_library(args)
    return _report_pending(pending)


def video_options(parser):
    # vidpipe (default) = video/vidpipe: Cairo renderer, real Volve data, its LLM planner runs through kmd.llm
    # (API provider or the file queue, cached). --planner rule works without any LLM but gives generic frames.
    # legacy = kmd/video: matplotlib state-model frames from a kmd scene spec (made the first delivered videos).
    parser.add_argument("--video-engine", choices=["vidpipe", "legacy"], default="vidpipe")
    parser.add_argument("--planner", choices=["llm", "rule"], default="llm")
    parser.add_argument("--tts", choices=["microsoft", "piper", "rhvoice", "espeak", "none"], default="microsoft")


def cmd_check(args) -> int:
    pending = _stage("checker").run_check(Path(args.package), args.chapter, out=args.out) or []
    return _report_pending(pending)


def cmd_library(args) -> int:
    from .site.build import build_library

    print(f"OK: open {build_library()}")
    return 0


def cmd_serve(args) -> int:
    from .site.serve import serve

    cmd_library(args)
    return serve(args.port)


def cmd_export(args) -> int:
    target = _stage("submission").export(args.chapter, args.out)
    print(f"[export] {target}")
    return 0


def cmd_domain(args) -> int:
    pending = _stage("domain").new_domain(args.domain, args.from_chapter) or []
    return _report_pending(pending)


def main(argv=None) -> int:
    load_env()
    ap = argparse.ArgumentParser(prog="kmd", description="Глава → курс pipeline")
    sub = ap.add_subparsers(dest="command", required=True)
    for s in STAGES:
        p = sub.add_parser(s)
        p.add_argument("chapter")
        p.add_argument("--node")
        p.set_defaults(func=cmd_stage)
    p = sub.add_parser("run", help="all stages for a chapter")
    p.add_argument("chapter")
    p.add_argument("--from", dest="from_stage", choices=STAGES)
    p.add_argument("--to", dest="to_stage", choices=STAGES)
    p.add_argument("--with-scenes", action="store_true", help="generate missing scenes and redraws in queue mode")
    p.add_argument("--video-node", help="render one learning-layer node before building the site")
    p.add_argument("--video-format", choices=["short", "long"], default="short")
    video_options(p)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("rebuild", help="re-merge overrides and rebuild downstream")
    p.add_argument("chapter")
    p.add_argument("--with-scenes", action="store_true", help="generate missing scenes and redraws in queue mode")
    p.add_argument("--video", action="store_true", help="also re-render existing videos")
    video_options(p)
    p.set_defaults(func=cmd_rebuild)
    p = sub.add_parser("video")
    p.add_argument("chapter")
    p.add_argument("node")
    p.add_argument("--format", choices=["short", "long"], default="short")
    video_options(p)
    p.set_defaults(func=cmd_video)
    p = sub.add_parser("library", help="build a shared offline home for available courses and videos")
    p.set_defaults(func=cmd_library)
    p = sub.add_parser("serve", help="open the local course library with video seeking")
    p.add_argument("--port", type=int, default=8766)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("check", help="review an external package (bookmarks)")
    p.add_argument("package")
    p.add_argument("--chapter", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("export", help="export course JSON in the organizers’ schemas")
    p.add_argument("chapter")
    p.add_argument("--out")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("domain", help="draft a domain pack for a new domain")
    p.add_argument("domain")
    p.add_argument("--from-chapter", required=True)
    p.set_defaults(func=cmd_domain)
    p = sub.add_parser("llm")
    p.add_argument("llm_cmd", choices=["pending", "show", "answer", "stats"])
    p.add_argument("file", nargs="?")
    p.add_argument("response", nargs="?")
    p.add_argument("--chapter")
    p.set_defaults(func=cmd_llm)
    p = sub.add_parser("edit", help="log a manual edit (minutes)")
    p.add_argument("chapter")
    p.add_argument("--target", required=True)
    p.add_argument("--minutes", type=float, required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--who", default="team")
    p.add_argument("--kind", default="fix")
    p.set_defaults(func=cmd_edit)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
