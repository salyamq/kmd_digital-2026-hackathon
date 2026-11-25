"""Paths and config loading. Nothing domain- or chapter-specific lives here."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
SCHEMAS = ROOT / "schemas"
DOMAINS = ROOT / "domains"
CHAPTERS = ROOT / "chapters"
RUNS = ROOT / "runs"
OVERRIDES = ROOT / "overrides"
EDITS = ROOT / "edits"


def data_dir() -> Path:
    return Path(os.environ.get("KMD_DATA", Path.home() / "kmd_data")).expanduser()


def load_env() -> None:
    """Load ROOT/.env (KEY=VALUE lines) into os.environ without overriding existing vars."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def chapter_config(chapter: str) -> dict:
    p = Path(chapter)
    if not p.suffix:
        p = CHAPTERS / f"{chapter}.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    cfg.setdefault("id", p.stem)
    cfg["_path"] = str(p)
    for key in ("md", "pdf"):
        if cfg.get("book", {}).get(key):
            cfg["book"][f"{key}_path"] = str((data_dir() / cfg["book"][key]).expanduser())
    return cfg


def run_dir(chapter: str) -> Path:
    cid = chapter_config(chapter)["id"]
    d = RUNS / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def domain_dir(domain: str) -> Path:
    return DOMAINS / domain


def domain_pack(domain: str) -> dict:
    """Load all files of a domain pack into one dict (yaml/json by extension, md as text)."""
    d = domain_dir(domain)
    pack: dict = {}
    if not d.exists():
        raise FileNotFoundError(f"domain pack not found: {d}")
    for f in sorted(d.iterdir()):
        if f.suffix in (".yaml", ".yml"):
            pack[f.stem] = yaml.safe_load(f.read_text(encoding="utf-8"))
        elif f.suffix == ".json":
            pack[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        elif f.suffix == ".md":
            pack[f.stem] = f.read_text(encoding="utf-8")
    return pack


def read_json(p: Path | str):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path | str, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
