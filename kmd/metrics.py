"""Cost metrics required by the TZ: human-minutes and money per node and per video minute,
share of manual work. Reads the LLM cache, the edit journal and produced artifacts.

LLM usage counts every cached answer, including answers that were later superseded (re-asks after a
prompt change), so it is the real development cost, an upper bound for a clean run. Queue answers have no
token counts: tokens are estimated from characters (CHARS_PER_TOKEN).

    python -m kmd.metrics            # all chapters -> runs/metrics.json + table on stdout
"""
from __future__ import annotations

import json
import os
import sys

from .config import EDITS, RUNS, read_json, write_json

# Price per 1M tokens (USD) used to convert usage into money; override with env KMD_PRICE_IN / KMD_PRICE_OUT.
PRICE_IN = float(os.environ.get("KMD_PRICE_IN", 15.0))
PRICE_OUT = float(os.environ.get("KMD_PRICE_OUT", 75.0))
CHARS_PER_TOKEN = 3.0  # Russian text, rough; used only when the provider gave no token counts


def _llm_usage(ch_dir):
    calls = tin = tout = 0
    for f in ch_dir.glob("llm/*/*.json"):
        if f.parent.name == "pending":
            continue
        d = read_json(f)
        u = d.get("usage", {})
        calls += 1
        if "input_tokens" in u:
            tin += u["input_tokens"]
            tout += u["output_tokens"]
        else:
            req = d["request"]
            tin += int((len(req["system"]) + len(req["user"])) / CHARS_PER_TOKEN)
            tout += int(len(json.dumps(d["response"], ensure_ascii=False)) / CHARS_PER_TOKEN)
    return calls, tin, tout


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
    edits = _edits()
    res = {}
    for ch_dir in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        layer_p = ch_dir / "layer.json"
        if not layer_p.exists() or ch_dir.name.startswith(("fixture", "stub", "_")):
            continue
        nodes = len(read_json(layer_p)["nodes"])
        calls, tin, tout = _llm_usage(ch_dir)
        usd = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
        e = edits.get(ch_dir.name, [])
        human_min = sum(float(r["minutes"]) for r in e)
        vmin = _video_minutes(ch_dir)
        res[ch_dir.name] = {
            "nodes": nodes,
            "llm_calls": calls,
            "tokens_in": tin,
            "tokens_out": tout,
            "usd_total": round(usd, 2),
            "usd_per_node": round(usd / nodes, 3) if nodes else None,
            "manual_edits": len(e),
            "human_minutes": human_min,
            "human_minutes_per_node": round(human_min / nodes, 2) if nodes else None,
            "video_minutes": round(vmin, 2),
            "usd_per_video_minute_of_chapter": round(usd / vmin, 2) if vmin else None,
        }
    write_json(RUNS / "metrics.json", res)
    return res


if __name__ == "__main__":
    r = compute()
    json.dump(r, sys.stdout, ensure_ascii=False, indent=2)
    print()
