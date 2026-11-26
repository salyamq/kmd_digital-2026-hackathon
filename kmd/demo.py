"""One-command «change a number in the layer and rebuild» for the defense.

    python -m kmd demo-edit latyshova --claim geo.latyshova.s20.04.c02 --replace 1856 1857
    python -m kmd demo-edit latyshova --claim geo.latyshova.s20.04.c02 --text "новый текст утверждения"

Writes the patch to overrides/<chapter>/<node>.json (merged with an existing override), logs the
edit in edits/journal.jsonl, rebuilds the chapter (only the changed step asks the model) and prints
the step page with the new text.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import edits
from .config import ROOT, chapter_config, load_env, read_json, run_dir, write_json

DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash-1017"


def find_claim(layer: dict, claim_id: str) -> tuple[dict, dict]:
    for node in layer["nodes"]:
        for claim in node.get("claims", []):
            if claim["id"] == claim_id:
                return node, claim
    raise SystemExit(f"утверждение {claim_id} не найдено в слое")


def write_override(chapter_id: str, node_id: str, claim_id: str, text: str) -> Path:
    path = edits.OVERRIDES / chapter_id / f"{node_id}.json"
    patch = read_json(path) if path.exists() else {}
    patch.setdefault("claims_patch", {}).setdefault(claim_id, {})["text"] = text
    write_json(path, patch)
    return path


def use_api_model(model: str | None) -> str:
    """Point the pipeline at an OpenRouter model if a key is configured; return the provider label."""
    load_env()
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
        os.environ.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    if os.environ.get("KMD_LLM_PROVIDER") in (None, "", "openai") and os.environ.get("OPENAI_API_KEY"):
        os.environ["KMD_LLM_PROVIDER"] = "openai"
        if model or "openrouter.ai" in os.environ.get("OPENAI_BASE_URL", ""):
            os.environ["KMD_LLM_MODEL"] = model or os.environ.get("KMD_DEMO_MODEL") or DEFAULT_MODEL
        return f"openai:{os.environ.get('KMD_LLM_MODEL')}"
    return os.environ.get("KMD_LLM_PROVIDER") or "queue"


def step_page(site: Path, claim_id: str) -> Path | None:
    marker = f'id="src-{claim_id}"'
    for page in sorted(site.glob("step-*.html")):
        if marker in page.read_text(encoding="utf-8"):
            return page
    return None


def run(args) -> int:
    from .cli import main as kmd_main

    cfg = chapter_config(args.chapter)
    rd = run_dir(args.chapter)
    node, claim = find_claim(read_json(rd / "layer.json"), args.claim)
    old = claim["text"]
    if args.text:
        new = args.text
    else:
        before, after = args.replace
        if before not in old:
            raise SystemExit(f"в утверждении нет «{before}»: {old}")
        new = old.replace(before, after)
    if new == old:
        raise SystemExit("текст не изменился")
    path = write_override(cfg["id"], node["id"], claim["id"], new)
    edits.log_edit(cfg["id"], claim["id"], args.minutes, f"демо-правка: «{old}» → «{new}»", who=args.who)
    print(f"[demo] {path.relative_to(ROOT)}\n  было:  {old}\n  стало: {new}")
    print(f"[demo] модель для изменённого шага: {use_api_model(args.model)}")
    code = kmd_main(["rebuild", args.chapter] + (["--video"] if args.video else []))
    if code:
        return code
    page = step_page(rd / "site", claim["id"])
    if not page:
        print("[demo] блок утверждения на страницах шагов не найден")
        return 1
    html = page.read_text(encoding="utf-8")
    shown = re.sub(r"\s+", " ", new) in re.sub(r"\s+", " ", html)
    print(f"[demo] новый текст на странице: {'да' if shown else 'НЕТ'}")
    print(f"[demo] открыть: file://{page}#src-{claim['id']}")
    return 0 if shown else 1


def add_parser(sub) -> None:
    p = sub.add_parser("demo-edit", help="change one claim of the layer, log it and rebuild (defense demo)")
    p.add_argument("chapter")
    p.add_argument("--claim", required=True, help="claim id, e.g. geo.latyshova.s20.04.c02 (anchor #src-<id> on the step page)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--replace", nargs=2, metavar=("OLD", "NEW"), help="replace a fragment of the claim text, e.g. 1856 1857")
    g.add_argument("--text", help="new full claim text")
    p.add_argument("--minutes", type=float, default=1.0)
    p.add_argument("--who", default="team")
    p.add_argument("--model", help=f"OpenRouter model for the changed step (default KMD_DEMO_MODEL or {DEFAULT_MODEL})")
    p.add_argument("--video", action="store_true", help="also re-render the chapter's existing videos")
    p.set_defaults(func=run)
