"""Markdown -> pages -> blocks -> units. Pure functions (unit-tested in tests/test_structure_ingest.py)."""
from __future__ import annotations

import re
from collections import defaultdict

PAGE_RE = re.compile(r"^<!--\s*page\s+(\d+)\s*-->\s*$", re.M)

# language-level patterns (ru + en); no domain knowledge here
FIG_RE = re.compile(r"^\**\s*(?:Рис\.?|Рисунок|Fig\.?|Figure)\s*(\d+(?:[.\-]\d+)*[а-яa-z]?)\b\.?", re.I)
TAB_RE = re.compile(r"^\**\s*(?:Таблица|Табл\.|Table)\s*(\d+(?:[.\-]\d+)*)\b\.?", re.I)
EXAMPLE_RE = re.compile(r"^\**\s*(?:Пример|Example)\s*(\d+(?:\.\d+)*)?\s*[.:]", re.I)
SOLUTION_RE = re.compile(r"^\**\s*(?:Решение|Ответ|Solution|Answer)\s*[.:]", re.I)
PROBLEMS_HDR_RE = re.compile(
    r"^(?:#+\s*)?\**\s*(?:Задач[аи]|Упражнени[яе]|Вопросы(?: и задачи)?|Контрольные вопросы|"
    r"Problems?|Exercises?|Questions?)\s*\.?\**\s*$",
    re.I,
)
LIST_RE = re.compile(r"^\s*(?:[-*–]\s+|•\s*|\d{1,3}[.)]\s+|[а-яa-z][)]\s+)")
NUM_ITEM_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+")
CHAPTER_RE = re.compile(r"(?:^|\s)(?:Глава|ГЛАВА|Chapter|CHAPTER)\s+([IVXLC]+|\d+)\b")
PARAGRAPH_RE = re.compile(r"§\s*(\d+)")
NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?(?:\s|$)")
TERMINAL = ".!?:;…»\")"


def split_pages(md: str) -> dict[int, str]:
    """{page_number: text after its marker up to the next marker}."""
    pages: dict[int, str] = {}
    marks = list(PAGE_RE.finditer(md))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        p = int(m.group(1))
        pages[p] = pages.get(p, "") + md[m.end():end].strip("\n") + "\n"
    return pages


def _norm_marker(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[#*_`\s]+", "", s)
    return s


def _roman(s: str) -> int:
    if s.isdigit():
        return int(s)
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    tot, prev = 0, 0
    for ch in reversed(s.upper()):
        v = vals.get(ch, 0)
        tot = tot - v if v < prev else tot + v
        prev = max(prev, v)
    return tot


def _find_marker(pages: dict[int, str], plist: list[int], marker: str, after: tuple[int, int] | None = None):
    """Return (page, line_index) of the first line starting with marker (normalized)."""
    nm = _norm_marker(marker)
    if not nm:
        return None
    heading_only = marker.lstrip().startswith("#")
    for strict in ((True, False) if heading_only else (False,)):
        for p in plist:
            lines = pages.get(p, "").split("\n")
            for i, line in enumerate(lines):
                if after and (p, i) <= after:
                    continue
                if strict and not line.lstrip().startswith("#"):
                    continue
                if _norm_marker(line).startswith(nm):
                    return p, i
    return _find_marker_fuzzy(pages, plist, nm, after)


def _find_marker_fuzzy(pages: dict[int, str], plist: list[int], nm: str, after=None, threshold: float = 0.8):
    """OCR / text-layer markdown: headings lose '#', get split over lines or misread letters.
    Compare the marker with the start of each line (joined with the next two lines)."""
    import difflib

    best, best_r = None, threshold
    for p in plist:
        lines = pages.get(p, "").split("\n")
        for i in range(len(lines)):
            if after and (p, i) <= after:
                continue
            cand = _norm_marker(" ".join(lines[i:i + 3]))[: len(nm)]
            if not cand or not cand[:1].isalnum() and cand[:1] != nm[:1]:
                continue
            r = difflib.SequenceMatcher(None, nm, cand, autojunk=False).ratio()
            if r > best_r:
                best, best_r = (p, i), r
    return best


def cut_segment(pages: dict[int, str], a: int, b: int, start: str | None, end: str | None) -> list[tuple[int, str]]:
    """Pages a..b, cut at start/end marker lines (markers may be mid-page)."""
    plist = list(range(a, b + 1))
    texts = {p: pages.get(p, "") for p in plist}
    s_pos = _find_marker(pages, plist, start) if start else None
    if start and not s_pos:
        print(f"[ingest] WARNING: start marker not found on pages {a}-{b}: {start!r}")
    if s_pos:
        sp, si = s_pos
        plist = [p for p in plist if p >= sp]
        texts[sp] = "\n".join(pages[sp].split("\n")[si:])
    if end:
        search = plist + ([b + 1] if (b + 1) in pages else [])
        e_pos = _find_marker(pages, search, end, after=s_pos)
        if e_pos:
            ep, ei = e_pos
            if ep > b:
                pass  # end marker on the next page: chapter runs to the end of page b
            else:
                plist = [p for p in plist if p <= ep]
                base = texts[ep] if ep in texts else pages[ep]
                if s_pos and ep == s_pos[0]:
                    # both markers on one page: index relative to the cut text
                    ei = ei - s_pos[1]
                texts[ep] = "\n".join(base.split("\n")[:ei])
        else:
            print(f"[ingest] WARNING: end marker not found on pages {a}-{b + 1}: {end!r}")
    return [(p, texts[p]) for p in plist]


def _norm_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower().replace("ё", "е"))


def _edge_lines(text: str, k: int = 4) -> list[str]:
    lines = [l for l in text.split("\n") if l.strip()]
    return lines[:k] + lines[-k:]


def detect_running_lines(pages: dict[int, str], min_pages: int = 3) -> set[str]:
    """Running headers/footers: non-heading lines repeated at page edges on >= min_pages pages."""
    cnt: dict[str, set] = defaultdict(set)
    for p, t in pages.items():
        for l in _edge_lines(t):
            s = l.strip()
            if s.startswith(("#", "|", "$", "<!--", "-", "━")) or len(s) > 120:
                continue
            n = _norm_line(s)
            if len(re.sub(r"[^a-zа-я]", "", n)) < 6 and "©" not in n:
                continue
            cnt[n].add(p)
    return {n for n, ps in cnt.items() if len(ps) >= min_pages}


def _is_noise(line: str, running: set[str]) -> bool:
    s = line.strip()
    if re.fullmatch(r"\d{1,4}", s):
        return True  # bare page number
    return _norm_line(s) in running


def _desc_span(lines: list[str], i: int):
    """If a vision description block starts at line i, return (next_index, body_lines); else None.

    Block: optional `----`, then one or more `━━━ FORMAT ...` sections; it ends after a `KEYWORDS:` line
    or at a closing `----` that is not followed by another `━━━` section (closing line may be missing).
    """
    s = lines[i].strip()
    nxt = _next_nonempty(lines, i + 1)
    if s == "----" and nxt is not None and lines[nxt].strip().startswith("━━━"):
        j = nxt
    elif s.startswith("━━━"):
        j = i
    else:
        return None
    body = []
    while j < len(lines):
        lj = lines[j].strip()
        if lj == "----":
            k = _next_nonempty(lines, j + 1)
            if k is not None and lines[k].strip().startswith("━━━"):
                j = k
                continue
            return j + 1, body
        body.append(lines[j].rstrip())
        j += 1
        if lj.startswith("KEYWORDS"):
            k = _next_nonempty(lines, j)
            if k is not None and lines[k].strip() == "----":
                k2 = _next_nonempty(lines, k + 1)
                if k2 is not None and lines[k2].strip().startswith("━━━"):
                    j = k2
                    continue
                return k + 1, body
            if k is not None and lines[k].strip().startswith("━━━"):
                j = k
                continue
            return j, body
    return j, body


def strip_description_blocks(text: str) -> str:
    """Remove vision-model figure description blocks (they are not author text)."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        span = _desc_span(lines, i)
        if span:
            i = span[0]
            continue
        out.append(lines[i])
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def _next_nonempty(lines: list[str], i: int):
    while i < len(lines):
        if lines[i].strip():
            return i
        i += 1
    return None


# ---------------------------------------------------------------- blocks

def _blocks(seg_pages: list[tuple[int, str]], running: set[str]) -> list[dict]:
    """Split the segment into raw blocks: heading, table, formula, desc, item, para (with page)."""
    blocks: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur and any(x.strip() for x in cur["lines"]):
            blocks.append(cur)
        cur = None

    for page, text in seg_pages:
        flush()
        blocks.append({"type": "pagebreak", "page": page, "lines": []})
        lines = text.split("\n")
        edge = set()
        nz = [i for i, l in enumerate(lines) if l.strip()]
        edge.update(nz[:4] + nz[-4:])
        i = 0
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if i in edge and _is_noise(raw, running):
                i += 1
                continue
            # vision description block
            span = _desc_span(lines, i)
            if span:
                flush()
                blocks.append({"type": "desc", "page": page, "lines": [l for l in span[1] if l.strip()]})
                i = span[0]
                continue
            if s == "----" or s == "---":
                flush()
                i += 1
                continue
            if not s:
                flush()
                i += 1
                continue
            if s.startswith("#"):
                flush()
                blocks.append({"type": "heading", "page": page, "lines": [s]})
                i += 1
                continue
            if s.startswith("|"):
                if not cur or cur["type"] != "table":
                    flush()
                    cur = {"type": "table", "page": page, "lines": []}
                cur["lines"].append(s)
                i += 1
                continue
            if s.startswith("$$") or s.startswith("\\["):
                flush()
                body = [s]
                closer = "$$" if s.startswith("$$") else "\\]"
                done = (s.count("$$") >= 2) if closer == "$$" else s.rstrip().endswith("\\]")
                j = i + 1
                while not done and j < len(lines):
                    body.append(lines[j].rstrip())
                    if closer in lines[j]:
                        done = True
                    j += 1
                blocks.append({"type": "formula", "page": page, "lines": body})
                i = j
                continue
            if LIST_RE.match(s) and not FIG_RE.match(s) and not TAB_RE.match(s):
                flush()
                cur = {"type": "item", "page": page, "lines": [s]}
                i += 1
                continue
            if cur and cur["type"] == "table":
                flush()
            if not cur:
                cur = {"type": "para", "page": page, "lines": []}
            cur["lines"].append(s)
            i += 1
    flush()
    return blocks


# ---------------------------------------------------------------- units

def _ends_open(text: str) -> bool:
    t = text.rstrip()
    return bool(t) and t[-1] not in TERMINAL and not t.endswith("$$")


def _starts_lower(text: str) -> bool:
    t = text.lstrip(" *_«\"(")
    return bool(t) and t[0].isalpha() and t[0].islower()


def _join(a: str, b: str) -> str:
    a = a.rstrip()
    if re.search(r"[а-яёa-z]-$", a, re.I) and _starts_lower(b):
        return a[:-1] + b.lstrip()
    return a + " " + b.lstrip()


def _is_formula_line(s: str) -> bool:
    if len(s) > 140 or "=" not in s:
        return False
    words = re.findall(r"[А-Яа-яЁё]{3,}", re.sub(r"\\text\{[^}]*\}|\\mathrm\{[^}]*\}", "", s))
    return len(words) <= 1


def _ocr_suspect(text: str) -> bool:
    """Cyrillic text OCR-ed as Latin look-alikes ("Ha pe3yIbTaTax"): many Latin words outside math."""
    plain = re.sub(r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]", " ", text, flags=re.S)
    lat = re.findall(r"\b[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]{2,}\b", plain)
    cyr = re.findall(r"\b[А-Яа-яЁё]{3,}\b", plain)
    return len(lat) >= 5 and len(lat) > 2 * len(cyr)


def _section_of(heading: str, state: dict) -> dict | None:
    """Return a new section dict if this heading opens a numbered section/chapter."""
    h = heading.lstrip("#").strip().strip("*").strip()
    m = CHAPTER_RE.search(" " + h)
    if m and len(h) < 80:
        n = _roman(m.group(1))
        state["chapter"] = n
        return {"code": f"ch{n}", "title": h}
    m = PARAGRAPH_RE.search(h)
    if m and h.find("§") < 4:
        return {"code": f"s{m.group(1)}", "title": h}
    m = NUMBERED_RE.match(h)
    if m:
        return {"code": "s" + m.group(1).replace(".", "_"), "title": h}
    return None


def build_units(seg_pages: list[tuple[int, str]], running: set[str], segment: int = 0, language: str = "ru",
                x_offset: int = 0):
    blocks = _blocks(seg_pages, running)
    # chapters without numbered sections: top-level headings open sections
    hlevels = []
    has_numbered = False
    for b in blocks:
        if b["type"] == "heading":
            h = b["lines"][0]
            plain = h.lstrip("#").strip()
            if PROBLEMS_HDR_RE.match(plain) or FIG_RE.match(plain) or CHAPTER_RE.search(" " + plain):
                continue
            if _section_of(h, {"chapter": None}):
                has_numbered = True
            hlevels.append(len(h) - len(h.lstrip("#")))
    top_level = min(hlevels) if (hlevels and not has_numbered) else None
    units: list[dict] = []
    sections: list[dict] = []
    used_codes: dict[str, str] = {}
    state = {"chapter": None, "section": None, "code": None, "sub": None, "problems": False, "x": x_offset}
    page = seg_pages[0][0] if seg_pages else 0
    crossed_break = False
    pending_desc: list[dict] = []

    def new_section(sec: dict, pg: int):
        code = sec["code"]
        if code in used_codes and used_codes[code] != sec["title"]:
            code = f"ch{state['chapter']}{code}" if state["chapter"] and not code.startswith("ch") else f"{code}b"
        used_codes[code] = sec["title"]
        state["section"], state["code"], state["sub"] = sec["title"], code, None
        sections.append({"code": code, "title": sec["title"], "page": pg, "segment": segment})

    def ensure_section(pg: int):
        if state["code"] is None:
            state["x"] += 1
            new_section({"code": f"x{state['x']}", "title": "(начало фрагмента)"}, pg)

    def last_text_unit():
        for u in reversed(units):
            if u["kind"] in ("fragment", "figure") and not u.get("_open"):
                continue
            return u
        return None

    def add(kind: str, text: str, pg: int, **extra) -> dict:
        ensure_section(pg)
        u = {
            "kind": kind,
            "page": pg,
            "page_end": pg,
            "section": state["section"],
            "section_code": state["code"],
            "subsection": state["sub"],
            "text": text,
            "figure_no": None,
        }
        u.update(extra)
        units.append(u)
        return u

    for bi, b in enumerate(blocks):
        t = b["type"]
        if t == "pagebreak":
            page = b["page"]
            crossed_break = True
            continue
        text = "\n".join(b["lines"]).strip()
        if t == "desc":
            pending_desc.append({"page": page, "text": text, "idx": len(units)})
            continue
        if t == "heading" and FIG_RE.match(text.lstrip("#").strip()):
            t, text = "para", text.lstrip("#").strip()  # figure caption typeset as a heading
        if t == "heading":
            plain = text.lstrip("#").strip()
            if PROBLEMS_HDR_RE.match(plain):
                add("heading", text, page, level=text.count("#", 0, len(text) - len(text.lstrip("#"))))
                state["problems"] = True
                continue
            sec = _section_of(text, state)
            level = len(text) - len(text.lstrip("#"))
            if sec:
                new_section(sec, page)
            else:
                if (state["code"] is None and level <= 2) or (top_level is not None and level <= top_level):
                    state["x"] += 1
                    new_section({"code": f"x{state['x']}", "title": plain}, page)
                else:
                    state["sub"] = plain
            state["problems"] = False
            add("heading", text, page, level=level)
            crossed_break = False
            continue
        if t == "table":
            prev = units[-1] if units else None
            if prev and prev["kind"] == "table" and crossed_break and not prev.get("_closed"):
                # table continued on the next page
                rows = [l for l in b["lines"] if not re.fullmatch(r"\|[\s\-:|]+\|?", l)]
                prev.setdefault("page_breaks", []).append({"offset": len(prev["text"]) + 1, "page": page})
                prev["text"] += "\n" + "\n".join(rows)
                prev["page_end"] = page
            elif prev and prev.get("_table_caption"):
                prev["kind"] = "table"
                prev.pop("_table_caption")
                prev["caption"] = prev["text"]
                prev["text"] = prev["text"] + "\n" + text
                prev["page_end"] = page
            else:
                add("table", text, page, table_no=None, caption=None)
            crossed_break = False
            continue
        if t == "formula":
            add("formula", text, page)
            crossed_break = False
            continue
        # para / item
        if t == "para" and PROBLEMS_HDR_RE.match(text):
            add("heading", text, page, level=9)
            state["problems"] = True
            crossed_break = False
            continue
        prev = last_text_unit()
        hyphen = prev is not None and bool(re.search(r"[а-яёa-z]-$", prev["text"].rstrip(), re.I))
        if (
            prev is not None
            and t == "para"
            and prev["kind"] in ("paragraph", "list", "problem", "example")
            and _starts_lower(text)
            and (hyphen or _ends_open(prev["text"]))
            and not FIG_RE.match(text)
        ):
            joined = _join(prev["text"], text)
            if page != prev["page_end"]:
                # offset in the joined text where the new page starts
                prev.setdefault("page_breaks", []).append({"offset": len(joined) - len(text.lstrip()), "page": page})
            prev["text"] = joined
            prev["page_end"] = max(prev["page_end"], page)
            crossed_break = False
            continue
        crossed_break = False
        m_fig = FIG_RE.match(text)
        if m_fig:
            add("figure", text, page, figure_no=m_fig.group(1).rstrip("."), description=None)
            continue
        m_tab = TAB_RE.match(text)
        if m_tab and len(text) < 300:
            add("paragraph", text, page, table_no=m_tab.group(1).rstrip("."), _table_caption=True)
            continue
        prevu = units[-1] if units else None
        if prevu is not None and prevu.get("_table_caption") and len(text) < 300 and t == "para":
            prevu["text"] += "\n" + text  # second caption line (title / "data for example N")
            continue
        if prevu is not None and prevu["kind"] == "figure" and (
            re.match(r"^[^.]{0,40}:\s*\(?[1-9IVа-я]\)?\s*[–—-]", text) or re.match(r"^\(?[1-9IVа-я]\)?\s*[–—]\s", text)
        ):
            prevu["text"] += "\n" + text  # figure legend ("Фации: 1 – ...")
            continue
        m_ex = EXAMPLE_RE.match(text)
        if m_ex:
            add("example", text, page, example_no=m_ex.group(1))
            state["problems"] = False
            continue
        if SOLUTION_RE.match(text) and units and units[-1]["kind"] == "example":
            add("example", text, page, example_no=units[-1].get("example_no"))
            continue
        if t == "item":
            m_num = NUM_ITEM_RE.match(text)
            num = int(m_num.group(1)) if m_num else 0
            last_pno = max((int(u["problem_no"]) for u in units if u.get("problem_no", "").isdigit()), default=None)
            if m_num and (state["problems"] or (num >= 10 and last_pno is not None and last_pno < num <= last_pno + 20)):
                add("problem", text, page, problem_no=m_num.group(1))
            else:
                add("list", text, page)
            continue
        if _is_formula_line(text):
            add("formula", text, page)
            continue
        words = text.split()
        nxt_t = next((x["type"] for x in blocks[bi + 1:] if x["type"] != "pagebreak"), None)
        near_formula = nxt_t == "formula" or (units and units[-1]["kind"] == "formula")
        if len(text) < 60 and len(words) <= 6 and text.rstrip()[-1:] not in ".!?:" and not near_formula:
            add("fragment", text, page)
            continue
        if state["problems"] and not m_ex:
            state["problems"] = False
        add("paragraph", text, page)

    # attach vision descriptions to figures: prefer the next figure caption on the same/next page,
    # else the previous figure caption on the same page, else a caption-less figure unit.
    for d in pending_desc:
        target, best = None, None
        for free_only in (True, False):
            for pos in range(max(0, d["idx"] - 5), min(len(units), d["idx"] + 6)):
                u = units[pos]
                if u["kind"] != "figure" or not u.get("figure_no") or abs(u["page"] - d["page"]) > 1:
                    continue
                if free_only and u.get("description"):
                    continue
                dist = (d["idx"] - pos) if pos < d["idx"] else (pos - d["idx"] + 1)
                dist += 0.5 if pos < d["idx"] else 0  # tie -> the caption that follows
                if best is None or dist < best:
                    target, best = u, dist
            if target is not None:
                break
        if target is not None:
            target["description"] = (target.get("description") + "\n\n" if target.get("description") else "") + d["text"]
        else:
            # figure without a caption in the text: keep the description (marked as vision output)
            u = {
                "kind": "figure", "page": d["page"], "page_end": d["page"],
                "section": None, "section_code": None, "subsection": None,
                "text": "", "figure_no": None, "description": d["text"],
            }
            # inherit section from the neighbour unit
            ref = units[min(d["idx"], len(units) - 1)] if units else None
            if ref:
                u["section"], u["section_code"], u["subsection"] = ref["section"], ref["section_code"], ref["subsection"]
            units.insert(d["idx"], u)
            for d2 in pending_desc:
                if d2["idx"] > d["idx"] or (d2 is not d and d2["idx"] == d["idx"] and d2["page"] > d["page"]):
                    d2["idx"] += 1

    for u in units:
        if language == "ru" and _ocr_suspect(u["text"]):
            u["ocr_suspect"] = True
        if u.pop("_table_caption", None):
            u["kind"] = "paragraph"  # table caption without a table
        u.pop("_open", None)
        u.pop("_closed", None)
        if u["kind"] == "figure":
            u["description_by"] = "vision" if u.get("description") else None
        if u.get("page_end") == u["page"]:
            u.pop("page_end")
    for s in sections:
        s["units"] = sum(1 for u in units if u["section_code"] == s["code"])
    return units, sections
