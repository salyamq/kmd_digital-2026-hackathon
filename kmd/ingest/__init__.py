"""Stage 0: ingest. Chapter yaml + book markdown (+ pdf) -> units.json, source_pages.json, pages/p<N>.png.

The markdown is expected to carry `<!-- page N -->` markers (N = PDF page number, 1-based).
Figure descriptions produced by a vision model are blocks delimited by `----` lines that contain a
`━━━ FORMAT ...` header; they are NOT author text: they are attached to the nearest figure unit as
`description` and removed from source_pages.json (so no quote/number can be "verified" against them).

Nothing here is chapter- or domain-specific; only language-level patterns (ru/en) are used.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ..config import chapter_config, read_json, run_dir, write_json
from .parse import (
    PAGE_RE,
    build_units,
    cut_segment,
    detect_running_lines,
    split_pages,
)

__all__ = ["run", "load_units", "load_pages"]


def load_units(chapter: str) -> dict:
    return read_json(run_dir(chapter) / "units.json")


def load_pages(chapter: str) -> dict[int, str]:
    return {int(k): v for k, v in read_json(run_dir(chapter) / "source_pages.json").items()}


def _render_pages(pdf_path: str, pages: list[int], out: Path, dpi: int = 150) -> int:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # older versions
        import fitz as pymupdf  # type: ignore
    if not Path(pdf_path).exists():
        return 0
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    doc = pymupdf.open(pdf_path)
    for p in pages:
        f = out / f"p{p}.png"
        if f.exists() or p < 1 or p > doc.page_count:
            continue
        pix = doc[p - 1].get_pixmap(dpi=dpi)
        pix.save(str(f))
        n += 1
    return n


def run(chapter: str, **kw) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    md = Path(cfg["book"]["md_path"]).read_text(encoding="utf-8")
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    pages = split_pages(md)
    running = detect_running_lines(pages)

    all_units: list[dict] = []
    sections: list[dict] = []
    source_pages: dict[str, str] = {}
    chapter_pages: list[int] = []
    for si, seg in enumerate(cfg.get("segments", [])):
        a, b = seg["pages"]
        seg_pages = cut_segment(pages, a, b, seg.get("start"), seg.get("end"))
        x_off = sum(1 for s in sections if s["code"].startswith("x"))
        units, secs = build_units(seg_pages, running, segment=si, language=cfg.get("language", "ru"), x_offset=x_off)
        used = {x["code"] for x in sections}
        for s in secs:
            if s["code"] in used:  # same number in another segment (e.g. § 1 of the next chapter)
                old, s["code"] = s["code"], f"{s['code']}_{si + 1}"
                for u in units:
                    if u["section_code"] == old:
                        u["section_code"] = s["code"]
            sections.append(s)
        all_units.extend(units)
        for p in range(a, b + 1):
            chapter_pages.append(p)
            # full page text (author text only: figure descriptions removed)
            source_pages[str(p)] = _clean_page(pages.get(p, ""), running)
        # neighbour pages help quotes that run over the segment border
        for p in (a - 1, b + 1):
            if p in pages and str(p) not in source_pages:
                source_pages[str(p)] = _clean_page(pages[p], running)

    # stable ids: u<page>_<nn>
    per_page: Counter = Counter()
    for u in all_units:
        per_page[u["page"]] += 1
        u["id"] = f"u{u['page']:03d}_{per_page[u['page']]:02d}"
    # move id to front for readability
    all_units = [{"id": u.pop("id"), **u} for u in all_units]

    kinds = Counter(u["kind"] for u in all_units)
    figs = sorted({u["figure_no"] for u in all_units if u.get("figure_no")}, key=_natkey)
    write_json(
        rd / "units.json",
        {
            "chapter": cfg["id"],
            "title": cfg.get("title", ""),
            "language": cfg.get("language", "ru"),
            "pages": chapter_pages,
            "sections": sections,
            "stats": {"units": len(all_units), "kinds": dict(kinds), "figures": figs},
            "units": all_units,
        },
    )
    write_json(rd / "source_pages.json", dict(sorted(source_pages.items(), key=lambda kv: int(kv[0]))))
    if not kw.get("no_images"):
        _render_pages(cfg["book"].get("pdf_path", ""), chapter_pages, rd / "pages", dpi=kw.get("dpi", 150))
    print(f"[ingest] {cfg['id']}: {len(all_units)} units on {len(chapter_pages)} pages, "
          f"{len(sections)} sections, kinds={dict(kinds)}")
    return []


def _natkey(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _clean_page(text: str, running: set) -> str:
    """Author text of a page: no vision descriptions, no running headers/footers or bare page numbers
    at the page edges (so that quotes crossing a page break can be matched)."""
    from .parse import _is_noise

    lines = _strip_descriptions(text).split("\n")
    nz = [i for i, l in enumerate(lines) if l.strip()]
    edge = set(nz[:4] + nz[-4:])
    return "\n".join(l for i, l in enumerate(lines) if not (i in edge and _is_noise(l, running))).strip() + "\n"


def _strip_descriptions(text: str) -> str:
    from .parse import strip_description_blocks

    return strip_description_blocks(text)
