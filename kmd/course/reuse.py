"""Dev helper for the queue provider: re-answer pending course_step requests with the previous
cached answer for the same node when the node itself did not change (only the prompt wording or the
template catalog did). The answer still goes through all code checks; if they fail, the stage issues
a repair request as usual.

    python -m kmd.course.reuse <chapter>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from .. import llm
from ..config import read_json, run_dir


def _node_block(user: str) -> str:
    i = user.find("# Узел учебного слоя")
    if i < 0:
        return ""
    j = user.find("\n# ", i + 5)
    return user[i:j if j > 0 else None]


def reuse(chapter: str) -> int:
    rd = run_dir(chapter)
    n = 0
    for pend in sorted((rd / "llm" / "pending").glob("course_step.*.json")):
        req = read_json(pend)
        if req["task"].endswith(".fix"):
            continue
        cache_dir = rd / "llm" / req["task"]
        best = None
        for f in sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            old = read_json(f)
            if _node_block(old["request"]["user"]) == _node_block(req["user"]):
                best = old
                break
        if not best:
            continue
        # if a repair answer exists for the old request, prefer it (it passed or improved the checks)
        fix_dir = rd / "llm" / (req["task"] + ".fix")
        resp = best["response"]
        for f in sorted(fix_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if fix_dir.exists() else []:
            fx = read_json(f)
            if _node_block(fx["request"]["user"]) == _node_block(req["user"]):
                resp = fx["response"]
                break
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as t:
            json.dump(resp, t, ensure_ascii=False)
        try:
            llm.answer_pending(pend, Path(t.name), model="claude-opus-5.5 (agent queue, reused: node unchanged)")
            n += 1
            print(f"reused: {req['task']}")
        except Exception as e:
            print(f"cannot reuse {req['task']}: {e}")
    return n


if __name__ == "__main__":
    print(f"{reuse(sys.argv[1])} reused")
