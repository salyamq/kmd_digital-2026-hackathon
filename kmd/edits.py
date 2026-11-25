"""Manual edits: overrides (JSON merge-patch over generated artifacts) + the edit journal.

A human never edits generated files. To fix a fact:
  1. write/patch overrides/<chapter>/<node_id>.json  (RFC 7386 merge-patch over the node;
     lists are replaced whole; for claims use {"claims_patch": {"<claim_id>": {...}}})
  2. `kmd edit log CH --target <node_id> --minutes 4 --what "..."`  (appends edits/journal.jsonl)
  3. `kmd rebuild CH`  -> layer is re-merged, step page / tasks / site / video rebuilt.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

from .config import EDITS, OVERRIDES, ROOT, read_json


def merge_patch(target, patch):
    if not isinstance(patch, dict):
        return patch
    if not isinstance(target, dict):
        target = {}
    out = dict(target)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge_patch(out.get(k), v)
    return out


def apply_overrides(chapter_id: str, layer: dict) -> tuple[dict, list[str]]:
    """Apply overrides/<chapter>/*.json to layer nodes. Returns (layer, applied_node_ids)."""
    d = OVERRIDES / chapter_id
    applied = []
    if not d.exists():
        return layer, applied
    by_id = {n["id"]: n for n in layer["nodes"]}
    for f in sorted(d.glob("*.json")):
        patch = read_json(f)
        nid = patch.pop("id", f.stem)
        if nid == "_layer":
            claims_free = {k: v for k, v in patch.items()}
            layer = merge_patch(layer, claims_free)
            applied.append(nid)
            continue
        if nid not in by_id:
            raise KeyError(f"override {f} targets unknown node {nid}")
        node = by_id[nid]
        cp = patch.pop("claims_patch", None)
        node = merge_patch(node, patch)
        if cp:
            claims = []
            for c in node.get("claims", []):
                if c["id"] in cp:
                    c = merge_patch(c, cp[c["id"]])
                    if c is None or c.get("_delete"):
                        continue
                claims.append(c)
            node["claims"] = claims
        node["_overridden"] = True
        by_id[nid] = node
        applied.append(nid)
    layer["nodes"] = [by_id[n["id"]] for n in layer["nodes"]]
    return layer, applied


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return ""


def log_edit(chapter: str, target: str, minutes: float, what: str, who: str = "team", kind: str = "fix") -> dict:
    EDITS.mkdir(parents=True, exist_ok=True)
    rec = {
        "time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "chapter": chapter,
        "target": target,
        "kind": kind,
        "minutes": minutes,
        "what": what,
        "who": who,
        "commit": _git_head(),
    }
    with open(EDITS / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def summary() -> dict:
    p = EDITS / "journal.jsonl"
    out: dict = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        s = out.setdefault(r["chapter"], {"edits": 0, "minutes": 0.0})
        s["edits"] += 1
        s["minutes"] += float(r["minutes"])
    return out
