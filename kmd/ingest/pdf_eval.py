"""Compare PDF->markdown pages with the provided book markdown (dev check, no LLM unless asked).

    python -m kmd.ingest.pdf_eval CHAPTER [PAGE ...] [--mode text|auto|ocr] [--ocr tesseract|llm|off]

Prints per page: chosen source, text-layer quality, and word-level similarity to the provided md
(math, markup and figure descriptions removed on both sides).
"""
from __future__ import annotations

import difflib
import re
import sys
import tempfile
from pathlib import Path

from ..config import chapter_config
from .parse import split_pages, strip_description_blocks
from .pdf2md import chapter_pages, convert


def norm_words(md: str) -> list[str]:
    t = strip_description_blocks(md)
    t = re.sub(r"\$\$.*?\$\$|\$[^$\n]*\$", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>|[#*_`|>]", " ", t)
    t = t.lower().replace("ё", "е").replace("\u00ad", "")
    return re.findall(r"[а-яa-z0-9]+", t)


def similarity(a: str, b: str) -> float:
    wa, wb = norm_words(a), norm_words(b)
    if not wa and not wb:
        return 1.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def main(argv: list[str]) -> None:
    ch = argv[0]
    opts = {k: v for k, v in zip(argv, argv[1:]) if k.startswith("--")}
    pages = [int(x) for x in argv[1:] if x.isdigit()]
    cfg = chapter_config(ch)
    pages = pages or chapter_pages(cfg)
    ref = split_pages(Path(cfg["book"]["md_path"]).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        md, rep, pending = convert(cfg["book"]["pdf_path"], pages, Path(td), cfg.get("language", "ru"),
                                   mode=opts.get("--mode"), ocr=opts.get("--ocr"))
    got = split_pages(md)
    sims = []
    for p in pages:
        if str(p) not in rep:
            continue
        s = similarity(got.get(p, ""), ref.get(p, ""))
        sims.append(s)
        r = rep[str(p)]
        print(f"p{p}: {r['source']:<10} sim={s:.3f} chars={r['chars']} letters={r['letter_ratio']} weird={r['weird_ratio']} debris={r['debris_ratio']} good={r['good']}")
    if sims:
        print(f"mean sim={sum(sims) / len(sims):.3f} over {len(sims)} pages; pending={len(pending)}")


if __name__ == "__main__":
    main(sys.argv[1:])
