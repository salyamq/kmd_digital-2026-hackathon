"""Re-key cached layer_extract answers after a display-only change of the prompt input.

    python -m kmd.layer.migrate CH

When ingest gains display-only information (e.g. page-break markers ⟦стр. N⟧ inside units) the rendered
layer_extract prompts change and the LLM cache misses although the chunk (same unit ids and unit text) and
its answer are still valid. This tool copies each cached answer to the key of the current prompt if the
chunk's unit ids are identical, and records `migrated_from` in the cache file. Quotes and pages of the
migrated answers are re-checked by `kmd verify` as usual.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from .. import llm
from ..config import ROOT, read_json, run_dir, write_json
from . import extract_requests


def request_key(prompt: str, variables: dict, schema) -> tuple[str, dict]:
    schema_d = llm.load_schema(schema)
    system, user, src = llm.render(prompt, variables)
    user_full = user + llm._schema_instruction(schema_d)
    key = hashlib.sha256(json.dumps([prompt, src, system, user_full], ensure_ascii=False).encode("utf-8")).hexdigest()[:20]
    return key, {"system": system, "user": user_full, "schema": schema_d}


def _unit_ids(user: str) -> list[str]:
    return re.findall(r"^\[(u\d{3}_\d{2}) \|", user, flags=re.M)


def migrate(chapter: str) -> int:
    rd = run_dir(chapter)
    n = 0
    for i, ch, v in extract_requests(chapter):
        task = f"layer_extract_{i + 1:02d}"
        key, req = request_key("layer_extract", v, "layer_extract")
        new = rd / "llm" / task / f"{key}.json"
        if new.exists():
            continue
        ids = [u["id"] for u in ch]
        for old in sorted((rd / "llm" / task).glob("*.json")):
            d = read_json(old)
            if _unit_ids(d["request"]["user"]) == ids:
                d["request"].update({"key": key, "system": req["system"], "user": req["user"],
                                     "cache_path": str(new.relative_to(ROOT))})
                d["migrated_from"] = old.name
                write_json(new, d)
                n += 1
                print(f"[migrate] {chapter} {task}: {old.name} -> {new.name}")
                break
    # stale pending requests of the old prompt are obsolete
    for p in (rd / "llm" / "pending").glob("layer_extract_*.json"):
        r = read_json(p)
        if (ROOT / r["cache_path"]).exists():
            continue
        task = r["task"]
        if any((rd / "llm" / task).glob("*.json")):
            p.unlink()
    return n


if __name__ == "__main__":
    print(migrate(sys.argv[1]), "migrated")
