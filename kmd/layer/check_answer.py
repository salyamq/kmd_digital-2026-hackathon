"""Dev/QA tool: check an answer to a queued layer_extract request before submitting it.

    python -m kmd.layer.check_answer <pending.json> <answer.json>

Prints: schema errors, quotes not found on their page, numbers absent from the chapter,
units of the chunk that are neither covered nor skipped. Exit 1 if anything is wrong.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .. import llm
from ..config import read_json
from ..verify import check_text_numbers, clear_cache, find_quote


def check(pending: Path, answer: Path) -> int:
    req = read_json(pending)
    m = re.match(r"runs/([^/]+)/", req["cache_path"])
    chapter = m.group(1)
    clear_cache()
    obj = llm._extract_json(Path(answer).read_text(encoding="utf-8"))
    bad = 0
    try:
        llm.validate(obj, req.get("schema"))
    except Exception as e:
        print("SCHEMA:", str(e).split("\n")[0][:300])
        bad += 1
    if req["prompt"] != "layer_extract":
        return 1 if bad else 0
    must = re.search(r"Покрыть: (.*)\.\n", req["user"]).group(1).split(", ")
    covered = set()
    for n in obj.get("nodes", []):
        covered.update(n.get("unit_ids", []))
        for i, c in enumerate(n.get("claims", [])):
            r = find_quote(c["quote"], c["page"], chapter)
            if not r["found"]:
                bad += 1
                print(f"QUOTE {n['key']}#{i + 1} p.{c['page']} -> {r['where']} {r['score']:.0f}: {c['quote'][:90]}")
        texts = []
        for k in ("mechanism", "practice", "nuances"):
            texts.append(n["layers"][k]["text"])
        texts += [d["text"] for d in n["layers"]["deeper"]] + n.get("procedure", [])
        texts += [c["text"] for c in n["claims"]]
        for e in n.get("worked_examples", []):
            texts += [e["condition"], e["result"], *e["steps"]]
        texts += [t["definition"] for t in n.get("terms", [])]
        dm = n["data_meaning"]
        texts += [dm["text"], dm["inputs"], dm["outputs"], dm["breaks_where"], *dm["hypotheses"]]
        texts += [n["it_analogy"]["text"], n["it_analogy"]["breaks_where"], n["current_practice"]["text"]]
        texts += [str(v) for k, v in n["inefficiency_lens"].items() if k != "by"]
        if n.get("misconception"):
            texts += [n["misconception"]["text"], n["misconception"]["correction"]]
        nums = check_text_numbers("\n".join(texts), chapter)
        if nums:
            bad += 1
            print(f"NUMBERS {n['key']}: {nums}")
    skipped = {s["unit_id"] for s in obj.get("skipped", [])}
    miss = [u for u in must if u not in covered and u not in skipped]
    if miss:
        bad += 1
        print("UNCOVERED:", miss)
    extra = [u for n in obj.get("nodes", []) for u in n.get("unit_ids", []) if u not in must and not re.match(r"u\d", u)]
    if extra:
        print("UNKNOWN UNITS:", extra)
    print(f"nodes={len(obj.get('nodes', []))} claims={sum(len(n['claims']) for n in obj.get('nodes', []))} problems={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(check(Path(sys.argv[1]), Path(sys.argv[2])))
