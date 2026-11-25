"""Stage 4b: static offline course site (runs/<ch>/site/index.html). See kmd/site/build.py."""
from __future__ import annotations

from pathlib import Path


def run(chapter: str, **kw) -> list[Path]:
    from .build import build

    build(chapter)
    return []
