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
from .config import ROOT, RUNS, chapter_config, load_env, read_json, run_dir

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
    for s in stages:
        t0 = time.time()
        pending = _stage(s).run(args.chapter) or []
        print(f"[{s}] {args.chapter}: {time.time()-t0:.1f}s, pending={len(pending)}")
        if pending:
            return _report_pending(pending)
    print(f"OK: open {RUNS / chapter_config(args.chapter)['id'] / 'site' / 'index.html'}")
    return 0


def cmd_rebuild(args) -> int:
    """After an override: re-merge the layer and rebuild everything downstream."""
    args.from_stage = "layer"
    args.to_stage = None
    rc = cmd_run(args)
    if rc == 0 and args.video:
        vid = _stage("video")
        for p in sorted((run_dir(args.chapter) / "video").glob("*/passport.json")):
            pas = read_json(p)
            vid.run(args.chapter, node=pas["node_id"], fmt=pas.get("format", "short"))
    return rc


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


def cmd_video(args) -> int:
    pending = _stage("video").run(args.chapter, node=args.node, fmt=args.format) or []
    return _report_pending(pending)


def cmd_check(args) -> int:
    pending = _stage("checker").run_check(Path(args.package), args.chapter, out=args.out) or []
    return _report_pending(pending)


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
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("rebuild", help="re-merge overrides and rebuild downstream")
    p.add_argument("chapter")
    p.add_argument("--video", action="store_true", help="also re-render existing videos")
    p.set_defaults(func=cmd_rebuild)
    p = sub.add_parser("video")
    p.add_argument("chapter")
    p.add_argument("node")
    p.add_argument("--format", choices=["short", "long"], default="short")
    p.set_defaults(func=cmd_video)
    p = sub.add_parser("check", help="review an external package (bookmarks)")
    p.add_argument("package")
    p.add_argument("--chapter", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_check)
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
