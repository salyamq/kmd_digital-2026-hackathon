"""Tolerant loader for external packages (our schema, loose JSON, or plain text lines)."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _read_any(p: Path):
    if p.suffix == ".json":
        return json.loads(p.read_text(encoding="utf-8"))
    if p.suffix in (".jsonl",):
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    # text/markdown: one claim per non-empty line; "стр. N" / "p. N" picked up as page
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        s = line.strip(" -*\t")
        if len(s) < 15:
            continue
        m = re.search(r"(?:стр\.|с\.|p\.|page)\s*(\d+)", s, re.I)
        out.append({"id": f"{p.stem}.{i + 1}", "text": s, "page": int(m.group(1)) if m else None})
    return out


def load_package(path: Path) -> dict:
    if path.is_file():
        data = _read_any(path)
        return data if isinstance(data, dict) else {"package_id": path.stem, "claims": data}
    main = path / "package.json"
    if main.exists():
        return json.loads(main.read_text(encoding="utf-8"))
    pkg: dict = {"package_id": path.name, "claims": [], "scripts": [], "scenes": [], "frames": []}
    for p in sorted(path.iterdir()):
        if p.name == "findings.json" or p.suffix not in (".json", ".jsonl", ".md", ".txt"):
            continue
        data = _read_any(p)
        if isinstance(data, dict):
            for k in ("claims", "scripts", "scenes", "frames"):
                pkg[k] += data.get(k, [])
        elif isinstance(data, list):
            key = next((k for k in ("scripts", "scenes", "frames") if k[:-1] in p.stem.lower()), "claims")
            pkg[key] += data
    return pkg


def flatten(pkg: dict) -> list[dict]:
    """All checkable elements as {id, type, text, quote, page, ...}."""
    items = []
    for c in pkg.get("claims", []):
        items.append({"id": str(c["id"]), "type": "claim", "text": c.get("text", ""), "quote": c.get("quote"),
                      "page": c.get("page")})
    claims = {str(c["id"]): c for c in pkg.get("claims", [])}
    for s in pkg.get("scripts", []):
        for ln in s.get("lines", []):
            page = next((claims[x].get("page") for x in ln.get("claim_ids", []) if x in claims), None)
            text = ln.get("text", "") + (f" [на экране: {ln['on_screen']}]" if ln.get("on_screen") else "")
            items.append({"id": str(ln["id"]), "type": "script_line", "text": text, "quote": None, "page": page})
    for sc in pkg.get("scenes", []):
        parts = []
        for k in ("template", "objects", "params", "invariants", "assumptions", "exaggerations"):
            if sc.get(k):
                parts.append(f"{k}: {json.dumps(sc[k], ensure_ascii=False)}")
        items.append({"id": str(sc["id"]), "type": "scene", "text": "; ".join(parts), "quote": None, "page": None})
    for f in pkg.get("frames", []):
        text = f"кадр класса {f.get('class')}, метка «{f.get('provenance')}»: {f.get('description', '')}"
        if f.get("labels"):
            text += f" Подписи: {', '.join(f['labels'])}"
        items.append({"id": str(f["id"]), "type": "frame", "text": text, "quote": None, "page": None,
                      "class": f.get("class"), "provenance": f.get("provenance")})
    return items
