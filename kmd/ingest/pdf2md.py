"""PDF -> markdown with `<!-- page N -->` markers, for chapters that come without a prepared .md.

Per page (N = 1-based PDF page number):
  * text layer (pymupdf) if it looks good: enough characters, mostly letters, few garbled tokens,
    few formula fragments. Cleanup: soft hyphens, line-end hyphenation, letter-spaced words
    («П л о с к о п а р а л л е л ь н о е»), small raised digits -> superscripts, headings from
    font size / bold numbered lines.
  * otherwise OCR of the page image: the vision LLM (prompt `ingest_ocr`, one request per page,
    cached like every LLM call; in queue mode the request waits for a worker), or tesseract
    (rus+eng) when KMD_PDF_OCR=tesseract or no LLM is wanted (KMD_PDF_OCR=off -> text layer anyway).

Env knobs: KMD_PDF_MODE=auto|text|ocr (default auto), KMD_PDF_OCR=llm|tesseract|off (default llm).
Nothing here is chapter- or domain-specific.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from ..config import write_json

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore

SUPERSCRIPT = str.maketrans("0123456789+-−", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻")
_LETTER = r"А-Яа-яЁёA-Za-z"
_SPACED = re.compile(rf"(?<![{_LETTER}])((?:[{_LETTER}] ){{3,}}[{_LETTER}])(?![{_LETTER}])")
_CYR_WORD = re.compile(r"[А-Яа-яЁё]{2,}")
_MIXED = re.compile(r"\b(?=\w*[А-Яа-яЁё])(?=\w*[A-Za-z])\w{3,}\b")
_HEAD_NUM = re.compile(r"^(?:§\s*\d+|(?:Глава|ГЛАВА|Chapter|CHAPTER)\b|\d+(?:\.\d+)*\.?\s+\S|[IVXLC]+\.\s+\S)")


# ---------------------------------------------------------------- text layer

def _span_bold(s: dict) -> bool:
    return bool(s["flags"] & 16) or "bold" in s["font"].lower()


def _line_text(line: dict, body: float) -> str:
    spans = line["spans"]
    base = max((s["bbox"][3] for s in spans if s["size"] >= 0.8 * body), default=None)
    out = []
    for s in spans:
        t = s["text"]
        small = s["size"] < 0.75 * body
        if small and base is not None and s["bbox"][3] < base - 0.25 * body and re.fullmatch(r"[\d+\-−]+", t.strip()):
            t = t.strip().translate(SUPERSCRIPT)  # м2/с -> м²/с
        out.append(t)
    return "".join(out)


def _join_spaced(t: str) -> str:
    parts = re.split(r"( {2,})", t)
    return "".join(_SPACED.sub(lambda m: m.group(1).replace(" ", ""), p) if not p.isspace() else " " for p in parts)


def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        ln = ln[:-1].replace("\u00ad", "") + "-" if ln.endswith("\u00ad") else ln.replace("\u00ad", "")
        if not ln:
            continue
        if out and re.search(rf"[{_LETTER}]-$", out) and re.match(r"[а-яёa-z]", ln):
            out = out[:-1] + ln  # line-end hyphenation
        elif out:
            out += " " + ln
        else:
            out = ln
    return re.sub(r"\s+", " ", out).strip()


def _is_debris(lines: list[str], text: str) -> bool:
    """Formula fragments of a broken text layer: many tiny lines / few real words."""
    if not text:
        return False
    short = sum(1 for ln in lines if len(ln.strip()) <= 3)
    words = len(_CYR_WORD.findall(text))
    toks = len(text.split())
    return (len(lines) >= 3 and short / len(lines) >= 0.5) or (toks >= 4 and words / toks < 0.25 and len(text) < 300)


def text_layer_page(page) -> tuple[str, dict]:
    d = page.get_text("dict")
    sizes: Counter = Counter()
    for b in d["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                if s["text"].strip():
                    sizes[round(s["size"], 1)] += len(s["text"].strip())
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    out: list[str] = []
    debris_chars = 0
    total_chars = 0
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        raw = [_join_spaced(_line_text(ln, body)) for ln in b.get("lines", [])]
        raw = [r for r in raw if r.strip()]
        if not raw:
            continue
        text = _join_lines(raw)
        total_chars += len(text)
        if _is_debris(raw, text):
            debris_chars += len(text)
            out.append(f"$$ {text} $$")
            continue
        spans = [s for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
        nchar = sum(len(s["text"].strip()) for s in spans) or 1
        avg = sum(s["size"] * len(s["text"].strip()) for s in spans) / nchar
        bold = sum(len(s["text"].strip()) for s in spans if _span_bold(s)) / nchar
        first_bold = bool(spans) and _span_bold(spans[0])
        heading = (
            len(text) <= 220 and len(raw) <= 4 and not text.endswith((",", ";"))
            and (avg >= 1.1 * body or bold >= 0.6 or (first_bold and _HEAD_NUM.match(text)))
            and not re.fullmatch(r"[\d\s.]+", text)
        )
        if heading:
            level = 1 if (avg >= 1.25 * body or re.match(r"(?:Глава|ГЛАВА|Chapter|CHAPTER)\b", text)) else (2 if (avg >= 1.1 * body or text.startswith("§")) else 3)
            out.append("#" * level + " " + text)
        else:
            out.append(text)
    md = "\n\n".join(out)
    return md, {"chars": total_chars, "debris_ratio": round(debris_chars / total_chars, 3) if total_chars else 0.0}


def quality(md: str, debris_ratio: float = 0.0) -> dict:
    plain = re.sub(r"\$\$.*?\$\$", " ", md, flags=re.S)
    chars = len(plain.strip())
    letters = sum(c.isalpha() for c in plain)
    nonspace = sum(not c.isspace() for c in plain) or 1
    toks = plain.split()
    weird = sum(1 for t in toks if _MIXED.search(t) or re.search(r"[%{}\\^~|<>@�]", t) or re.search(r"[А-Яа-яЁё]\d|\d[А-Яа-яЁё]{2,}", t))
    q = {
        "chars": chars,
        "letter_ratio": round(letters / nonspace, 3),
        "weird_ratio": round(weird / len(toks), 3) if toks else 0.0,
        "debris_ratio": debris_ratio,
    }
    q["good"] = chars >= 150 and q["letter_ratio"] >= 0.6 and q["weird_ratio"] <= 0.04 and debris_ratio <= 0.2
    return q


# ---------------------------------------------------------------- OCR

def render_page(doc, pno: int, out_dir: Path, dpi: int = 200) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"p{pno}.png"
    if not f.exists():
        doc[pno - 1].get_pixmap(dpi=dpi).save(str(f))
    return f


def ocr_tesseract(img: Path, lang: str = "rus+eng") -> str:
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract is not installed (apt install tesseract-ocr tesseract-ocr-rus)")
    r = subprocess.run(["tesseract", str(img), "-", "-l", lang, "--psm", "3"], capture_output=True, text=True, timeout=300)
    paras = [_join_lines(p.split("\n")) for p in re.split(r"\n\s*\n", r.stdout)]
    return "\n\n".join(p for p in paras if p)


OCR_SCHEMA = {
    "type": "object",
    "required": ["markdown"],
    "properties": {
        "markdown": {"type": "string", "description": "page text as markdown"},
        "unreadable": {"type": "array", "items": {"type": "string"}, "description": "places that could not be read"},
    },
}


def ocr_llm(rd: Path, img: Path, pno: int, hint: str, language: str) -> str:
    from .. import llm

    v = {"page": pno, "language": language, "text_layer": hint[:6000]}
    res = llm.complete_json(rd, f"ocr_page.p{pno}", "ingest_ocr", v, schema=OCR_SCHEMA, images=[str(img)], max_tokens=8000)
    return res["markdown"].strip()


# ---------------------------------------------------------------- chapter

def chapter_pages(cfg: dict) -> list[int]:
    ps: set[int] = set()
    for seg in cfg.get("segments", []):
        a, b = seg["pages"]
        ps |= set(range(max(1, a - 1), b + 2))
    return sorted(ps)


def convert(pdf_path: str, pages: list[int], rd: Path, language: str = "ru", mode: str | None = None, ocr: str | None = None):
    """Return (markdown, report, pending). `pending` lists queue requests still to be answered."""
    from .. import llm

    mode = mode or os.environ.get("KMD_PDF_MODE", "auto")
    ocr = ocr or os.environ.get("KMD_PDF_OCR", "llm")
    doc = pymupdf.open(pdf_path)
    parts, report, pending = [], {}, []
    for p in pages:
        if p < 1 or p > doc.page_count:
            continue
        md, m = text_layer_page(doc[p - 1])
        q = quality(md, m["debris_ratio"])
        use_text = mode == "text" or (mode == "auto" and q["good"]) or ocr == "off"
        src = "text_layer"
        if not use_text:
            img = render_page(doc, p, rd / "pages_ocr")
            try:
                if ocr == "tesseract":
                    md, src = ocr_tesseract(img), "tesseract"
                else:
                    md, src = ocr_llm(rd, img, p, md if q["chars"] else "", language), "vision_llm"
            except llm.PendingLLM as e:
                pending.append(e.path)
                src = "pending"
        report[str(p)] = dict(q, source=src)
        parts.append(f"<!-- page {p} -->\n\n{md}\n")
    return "\n".join(parts), report, pending


def chapter_markdown(cfg: dict, rd: Path) -> tuple[str | None, list]:
    """Build runs/<ch>/source.md from the chapter's PDF pages. Returns (markdown or None if pending, pending)."""
    pdf = cfg.get("book", {}).get("pdf_path")
    if not pdf or not Path(pdf).exists():
        raise FileNotFoundError(f"no markdown and no PDF for chapter {cfg.get('id')}: {pdf}")
    md, report, pending = convert(pdf, chapter_pages(cfg), rd, cfg.get("language", "ru"))
    write_json(rd / "pdf2md_report.json", report)
    if pending:
        print(f"[ingest] pdf2md: {len(pending)} page OCR requests pending (answer them, then re-run)")
        return None, pending
    (rd / "source.md").write_text(md, encoding="utf-8")
    srcs = Counter(r["source"] for r in report.values())
    print(f"[ingest] pdf2md: {len(report)} pages -> {rd / 'source.md'} ({dict(srcs)})")
    return md, []
