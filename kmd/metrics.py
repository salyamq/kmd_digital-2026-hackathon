"""Cost metrics required by the TZ: human-minutes and money per node and per video minute,
share of manual work. Reads the LLM cache, the edit journal and produced artifacts.

Costs use the provider charge when present and estimate the remaining cached answers from tokens.
Queue token counts are estimated from characters. Rejected responses are absent from the cache.

    python -m kmd.metrics            # all chapters -> runs/metrics.json + table on stdout
"""
from __future__ import annotations

import json
import os
import sys

from .config import EDITS, RUNS, load_env, read_json, write_json

CHARS_PER_TOKEN = 3.0  # Rough estimate for queue answers.
VIDEO_TASK_PREFIXES = ("vidpipe.", "video_script.")


def _llm_usage(ch_dir, price_in, price_out):
    calls = tin = tout = recorded_calls = 0
    reported = estimated = video = 0.0
    for f in ch_dir.glob("llm/*/*.json"):
        if f.parent.name == "pending":
            continue
        d = read_json(f)
        u = d.get("usage", {})
        calls += 1
        if "input_tokens" in u:
            incoming, outgoing = u["input_tokens"], u["output_tokens"]
        else:
            req = d["request"]
            incoming = int((len(req["system"]) + len(req["user"])) / CHARS_PER_TOKEN)
            outgoing = int(len(json.dumps(d["response"], ensure_ascii=False)) / CHARS_PER_TOKEN)
        tin += incoming
        tout += outgoing
        if isinstance(u.get("cost_usd"), (int, float)):
            cost = u["cost_usd"]
            reported += cost
            recorded_calls += 1
        else:
            cost = (incoming * price_in + outgoing * price_out) / 1e6
            estimated += cost
        if f.parent.name.startswith(VIDEO_TASK_PREFIXES):
            video += cost
    return calls, tin, tout, reported, estimated, recorded_calls, video


def _edits():
    out: dict = {}
    p = EDITS / "journal.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out.setdefault(r["chapter"], []).append(r)
    return out


def _video_minutes(ch_dir) -> float:
    durations = {}
    for p in sorted(ch_dir.glob("video/*/passport*.json"), key=lambda p: p.name != "passport.json"):
        d = read_json(p)
        durations[(p.parent, d.get("format", "short"))] = float(d.get("duration_s") or (d.get("video") or {}).get("duration_s") or 0)
    return sum(durations.values()) / 60


def compute() -> dict:
    load_env()
    price_in = float(os.environ.get("KMD_PRICE_IN", 15))
    price_out = float(os.environ.get("KMD_PRICE_OUT", 75))
    edits = _edits()
    res = {}
    for ch_dir in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        layer_p = ch_dir / "layer.json"
        if not layer_p.exists() or ch_dir.name.startswith(("fixture", "stub", "_")):
            continue
        nodes = len(read_json(layer_p)["nodes"])
        calls, tin, tout, reported, estimated, recorded_calls, video_usd = _llm_usage(ch_dir, price_in, price_out)
        usd = reported + estimated
        e = edits.get(ch_dir.name, [])
        human_min = sum(float(r["minutes"]) for r in e if r.get("kind") != "mentor")
        mentor_min = sum(float(r["minutes"]) for r in e if r.get("kind") == "mentor")
        video_human_min = sum(float(r["minutes"]) for r in e if r.get("kind") == "video")
        timing = ch_dir / "run_timing.json"
        elapsed_min = read_json(timing)["seconds"] / 60 if timing.exists() else None
        vmin = _video_minutes(ch_dir)
        res[ch_dir.name] = {
            "nodes": nodes,
            "llm_calls": calls,
            "tokens_in": tin,
            "tokens_out": tout,
            "usd_total": round(usd, 5),
            "usd_reported": round(reported, 5),
            "usd_estimated": round(estimated, 5),
            "calls_with_reported_cost": recorded_calls,
            "usd_per_node": round(usd / nodes, 3) if nodes else None,
            "manual_edits": sum(r.get("kind") != "mentor" for r in e),
            "human_minutes": human_min,
            "mentor_minutes": mentor_min,
            "run_minutes": round(elapsed_min, 2) if elapsed_min is not None else None,
            "manual_time_share": round(human_min / (human_min + elapsed_min), 3) if elapsed_min else None,
            "human_minutes_per_node": round(human_min / nodes, 2) if nodes else None,
            "video_minutes": round(vmin, 2),
            "llm_usd_per_video_minute": round(video_usd / vmin, 3) if vmin else None,
            "human_minutes_per_video_minute": round(video_human_min / vmin, 2) if vmin else None,
            "usd_per_video_minute_of_chapter": round(usd / vmin, 2) if vmin else None,
        }
    write_json(RUNS / "metrics.json", res)
    return res


if __name__ == "__main__":
    r = compute()
    json.dump(r, sys.stdout, ensure_ascii=False, indent=2)
    print()
