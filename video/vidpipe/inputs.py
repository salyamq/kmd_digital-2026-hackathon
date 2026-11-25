"""Load and normalize the four inputs: node JSON, chapter pages, domain pack, datasets.

Everything here is tolerant: the organizers' exact schema is unknown, so we accept
common key variants and record what we could not find (node['_missing']).
"""
import csv
import difflib
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from .util import RES_DIR, ROOT_DIR, read_json, write_json, log

# ----------------------------------------------------------------------------- text utils

CYR = re.compile(r"[А-Яа-яЁё]")


def detect_lang(text):
    if not text:
        return "ru"
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return "ru"
    cyr = sum(1 for c in letters if CYR.match(c))
    return "ru" if cyr / len(letters) > 0.3 else "en"


def _not_a_page(p):
    """README / notes / hidden files in a --pages dir are documentation, not chapter text."""
    n = p.name.lower()
    return n.startswith((".", "_", "readme", "license", "notes")) or p.parent.name.startswith(".")


def norm_text(s):
    """Normalization used for quote matching: case, ё/е, hyphenation, quotes, dashes, spaces."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("́", "")                      # combining acute (stress) marks
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)       # hyphenation across lines
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»“”„\"'`’]", "", s)
    s = re.sub(r"[‐‑‒–—―−]", "-", s)
    s = re.sub(r"[*_#>|]", " ", s)                    # markdown noise
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ----------------------------------------------------------------------------- node

def _first(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, "", []):
            return d[k]
    return default


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _norm_page(p):
    if p is None:
        return None
    if isinstance(p, (int, float)):
        return int(p)
    m = re.search(r"\d+", str(p))
    return int(m.group()) if m else None


def _norm_claim(c, i):
    if isinstance(c, str):
        return {"id": f"c{i+1}", "text": c, "page": None, "quote": None}
    cid = str(_first(c, ["id", "claim_id", "key", "uid"], f"c{i+1}"))
    text = _first(c, ["text", "statement", "claim", "summary", "content", "fact"], "")
    quote = _first(c, ["quote", "verbatim", "citation", "source_quote", "evidence", "quote_ru", "quote_en"])
    src = c.get("source") if isinstance(c.get("source"), dict) else {}
    page = _norm_page(_first(c, ["page", "page_ref", "pages", "page_number", "p"]) or _first(src, ["page", "pages"]))
    if quote is None:
        quote = _first(src, ["quote", "verbatim", "text"])
    if isinstance(quote, list):
        quote = " ".join(map(str, quote))
    return {"id": cid, "text": text or (quote or ""), "page": page, "quote": quote,
            "kind": _first(c, ["kind", "type", "role"]), "raw": c}


def load_node(path):
    raw = read_json(path)
    if raw is None:
        raise FileNotFoundError(f"node file not found: {path}")
    if isinstance(raw, list):              # some exporters wrap a single node in a list
        raw = raw[0]
    if "node" in raw and isinstance(raw["node"], dict):
        raw = {**raw, **raw["node"]}
    missing = []

    node = {"raw": raw}
    node["id"] = str(_first(raw, ["id", "node_id", "slug", "key"], Path(path).stem))
    node["title"] = _first(raw, ["title", "name", "heading", "topic"], node["id"])

    claims = _first(raw, ["claims", "statements", "facts", "key_points", "assertions"], [])
    node["claims"] = [_norm_claim(c, i) for i, c in enumerate(_as_list(claims))]
    if not node["claims"]:
        missing.append("claims")

    diff = _first(raw, ["difficulty_types", "difficulty_type", "difficulty", "difficulties", "types"], [])
    node["difficulty"] = [str(d).strip().lower() for d in _as_list(diff)]

    mis = _first(raw, ["misconception", "misconceptions", "myth", "common_misconception", "fixes_misconception"])
    if isinstance(mis, list):
        mis = mis[0] if mis else None
    if isinstance(mis, str):
        mis = {"wrong": mis}
    if isinstance(mis, dict):
        node["misconception"] = {
            "wrong": _first(mis, ["wrong", "myth", "text", "statement", "misconception", "belief"], ""),
            "right": _first(mis, ["right", "correct", "correction", "fix", "truth", "reality", "explanation"], ""),
            "claim_id": _first(mis, ["claim_id", "source_claim", "refutes_with"]),
            "page": _norm_page(_first(mis, ["page", "page_ref"])),
            "quote": _first(mis, ["quote", "verbatim"]),
        }
    else:
        node["misconception"] = None
        missing.append("misconception")

    data = _first(raw, ["what_it_means_for_data", "data_meaning", "in_data", "for_data", "data_view",
                        "what_it_means_in_data", "data"])
    if isinstance(data, dict):
        node["data_meaning"] = {"text": _first(data, ["text", "summary", "description"], ""),
                                "curves": _as_list(_first(data, ["curves", "mnemonics", "logs"])),
                                "datasets": _as_list(_first(data, ["datasets", "files"])),
                                "claim_ids": _as_list(_first(data, ["claim_ids", "claims"]))}
    else:
        node["data_meaning"] = {"text": data or "", "curves": [], "datasets": [], "claim_ids": []}
    if not node["data_meaning"]["text"]:
        missing.append("what_it_means_for_data")

    it = _first(raw, ["it_analogy", "analogy", "it_bridge", "it", "it_parallel"])
    if isinstance(it, dict):
        it = _first(it, ["text", "analogy", "summary"], "")
    node["it_analogy"] = it or ""
    if not node["it_analogy"]:
        missing.append("it_analogy")

    node["formulas"] = _as_list(_first(raw, ["formulas", "equations", "formula"]))
    node["datasets"] = _as_list(_first(raw, ["datasets", "data_refs", "data_sources"]))
    node["prediction_question"] = _first(raw, ["prediction_question", "predict_question", "question_before"])
    node["transfer_question"] = _first(raw, ["transfer_question", "question_after", "check_question"])
    node["source"] = _first(raw, ["source", "chapter", "book", "reference"], {})
    node["visual_hints"] = _first(raw, ["visual_hints", "visuals", "scene_hints"], {})

    all_text = " ".join([node["title"]] + [c["text"] or "" for c in node["claims"]] +
                        [node["misconception"]["wrong"] if node["misconception"] else ""])
    node["lang"] = str(_first(raw, ["lang", "language", "locale"], detect_lang(all_text)))[:2].lower()
    node["_missing"] = missing
    return node


# ----------------------------------------------------------------------------- pages

PAGE_MARK = re.compile(
    r"^\s*(?:<!--\s*)?(?:#+\s*)?(?:\[?\s*)?(?:page|стр\.?|страница|с\.)\s*[:#№]?\s*(\d{1,4})\s*(?:\]|-->)?\s*$",
    re.IGNORECASE | re.MULTILINE)
TEXT_EXT = {".md", ".txt", ".markdown"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def _split_by_markers(text):
    """Split markdown text by page markers. Returns {page:int|None: text}."""
    marks = list(PAGE_MARK.finditer(text))
    if not marks:
        return {None: text}
    out = {}
    if marks[0].start() > 0 and text[:marks[0].start()].strip():
        out[None] = text[:marks[0].start()]
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[int(m.group(1))] = out.get(int(m.group(1)), "") + text[m.end():end]
    return out


def _ocr(img_path, cache_dir, lang="rus+eng"):
    cache = Path(cache_dir) / (Path(img_path).stem + ".ocr.txt")
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    if not shutil.which("tesseract"):
        return ""
    try:
        out = subprocess.run(["tesseract", str(img_path), "stdout", "-l", lang],
                             capture_output=True, text=True, timeout=180).stdout
    except Exception:
        out = ""
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(out, encoding="utf-8")
    return out


class Pages:
    """Chapter text indexed by page. Used to verify quotes, formulas and numbers."""

    def __init__(self, pages_dir, cache_dir=None, ocr=True):
        self.pages = {}            # page -> text  (None key = unknown page)
        self.images = {}           # page -> image path
        self.files = []
        self.dir = Path(pages_dir) if pages_dir else None
        if not self.dir or not self.dir.exists():
            return
        files = sorted(p for p in self.dir.rglob("*") if p.is_file() and not _not_a_page(p))
        self.files = [str(p) for p in files]
        self.ocr_pages = set()     # pages whose text came from OCR (fuzzy quote match allowed there)
        texts = [p for p in files if p.suffix.lower() in TEXT_EXT]
        imgs = [p for p in files if p.suffix.lower() in IMG_EXT]
        for p in texts:
            t = p.read_text(encoding="utf-8", errors="ignore")
            num = re.findall(r"\d+", p.stem)
            parts = _split_by_markers(t)
            if list(parts.keys()) == [None] and num:
                parts = {int(num[-1]): t}
            for k, v in parts.items():
                self.pages[k] = self.pages.get(k, "") + "\n" + v
        for p in imgs:
            num = re.findall(r"\d+", p.stem)
            page = int(num[-1]) if num else None
            self.images[page] = str(p)
            if ocr and (page not in self.pages or not self.pages[page].strip()):
                txt = _ocr(p, cache_dir or (self.dir / ".ocr_cache"))
                if txt.strip():
                    self.pages[page] = self.pages.get(page, "") + "\n" + txt
                    self.ocr_pages.add(page)
        self._norm = {k: norm_text(v) for k, v in self.pages.items()}
        self.full_norm = " ".join(self._norm.values())

    @property
    def available(self):
        return bool(self.pages) and any(v.strip() for v in self.pages.values())

    def find_quote(self, quote, page=None):
        """Claim -> page + quote check.
        status: verified   exact (normalized) text on the cited page (±1: quotes may cross a page break)
                wrong_page exact text exists, but on another page than cited
                near       similar text only (OCR noise or a mis-copied quote) — not accepted as verified
                not_found / no_pages / too_short
        On OCR'd scans a fuzzy match >= 0.92 on the cited page counts as verified (recognition noise)."""
        if not self.available:
            return {"status": "no_pages", "page_found": None, "ratio": 0.0}
        q = norm_text(quote or "")
        if len(q) < 6:
            return {"status": "too_short", "page_found": None, "ratio": 0.0}

        def on_cited(k):
            return page is None or k is None or abs(k - page) <= 1

        hits = [k for k, v in self._norm.items() if q in v]
        if hits:
            good = [k for k in hits if on_cited(k)]
            k = good[0] if good else hits[0]
            return {"status": "verified" if good else "wrong_page", "page_found": k, "ratio": 1.0,
                    "page_match": bool(good), "exact": True}
        # quote crossing a page break: try cited page + next page joined
        if page is not None and page in self._norm and (page + 1) in self._norm:
            if q in self._norm[page] + " " + self._norm[page + 1]:
                return {"status": "verified", "page_found": page, "ratio": 1.0, "page_match": True, "exact": True}
        # fuzzy: best window by character similarity
        best = (0.0, None, "")
        qt = q.split()
        n = len(qt)
        for k, v in self._norm.items():
            vt = v.split()
            if len(vt) < 3:
                continue
            step = max(1, n // 4)
            for i in range(0, max(1, len(vt) - n + 1), step):
                win = " ".join(vt[i:i + n])
                r = difflib.SequenceMatcher(None, q, win).ratio()
                if r > best[0]:
                    best = (r, k, win)
        r, k, win = best
        ocr_ok = k in self.ocr_pages and on_cited(k) and r >= 0.92
        status = "verified" if ocr_ok else ("near" if r >= 0.75 else "not_found")
        return {"status": status, "page_found": k, "ratio": round(r, 3), "page_match": on_cited(k),
                "exact": False, "closest_text": win[:160] if r >= 0.5 else None}

    def contains_number(self, num_str):
        """Does this number (as written, decimal comma or point) occur anywhere in the chapter?"""
        if not self.available:
            return False
        variants = {num_str, num_str.replace(".", ","), num_str.replace(",", ".")}
        for v in variants:
            if re.search(rf"(?<![\d.,]){re.escape(v)}(?![\d])", self.full_norm):
                return True
        return False

    def number_on_page(self, num_str, page=None):
        """Is this number (as written in the book, '0,7' or '0.7') on the given page (±1) — or anywhere if page is None?"""
        if not self.available:
            return False
        keys = [k for k in self._norm if page is None or k is None or (k is not None and abs(k - int(page)) <= 1)]
        s = str(num_str).strip()
        variants = {s, s.replace(".", ","), s.replace(",", ".")}
        for k in keys:
            for v in variants:
                if re.search(rf"(?<![\d.,]){re.escape(v.lower())}(?![\d])", self._norm[k]):
                    return True
        return False

    def excerpt(self, max_chars=12000):
        out, n = [], 0
        for k in sorted(self.pages, key=lambda x: (x is None, x or 0)):
            t = re.sub(r"\s+\n", "\n", self.pages[k]).strip()
            chunk = f"\n[page {k}]\n{t}\n"
            if n + len(chunk) > max_chars:
                out.append(chunk[: max(0, max_chars - n)])
                break
            out.append(chunk)
            n += len(chunk)
        return "".join(out)


# ----------------------------------------------------------------------------- domain pack

def _deep_merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_table(path):
    """json / csv / tsv / 'a — b' text lines -> list of rows (dicts or 2-tuples)."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return read_json(p)
    text = p.read_text(encoding="utf-8", errors="ignore")
    if p.suffix.lower() in (".csv", ".tsv"):
        lines_ = [l for l in text.splitlines() if l.strip()]
        if not lines_:
            return []
        delim = "\t" if p.suffix.lower() == ".tsv" or "\t" in lines_[0] else ","
        first = [c.strip().lower() for c in lines_[0].split(delim)]
        known = {"word", "term", "слово", "термин", "text", "stressed", "stress", "ударение", "abbr", "spoken",
                 "definition", "en", "ru", "tts", "pronunciation", "with_stress"}
        if any(c in known for c in first):
            return list(csv.DictReader(lines_, delimiter=delim))
        return [tuple(c.strip() for c in l.split(delim)[:2]) for l in lines_ if delim in l]
    rows = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        m = re.split(r"\s+(?:—|–|-|=>|->|:|=)\s+|\t", line, maxsplit=1)
        if len(m) == 2 and m[0] and m[1]:
            rows.append((m[0].strip(), m[1].strip()))
    return rows


def _acute_to_plus(w):
    """'гли́на' (combining acute after vowel) -> 'гл+ина' (Silero/RHVoice convention)."""
    if "́" not in w:
        return w
    out = []
    for ch in w:
        if ch == "́" and out:
            v = out.pop()
            out.append("+" + v)
        else:
            out.append(ch)
    return "".join(out)


def _find(dirp, patterns):
    if not dirp:
        return []
    out = []
    for pat in patterns:
        out += sorted(Path(dirp).rglob(pat))
    seen, res = set(), []
    for p in out:
        if p not in seen and p.is_file():
            seen.add(p)
            res.append(p)
    return res


class DomainPack:
    def __init__(self, domain_dir):
        self.dir = Path(domain_dir) if domain_dir else None
        base = RES_DIR / "default_domain"
        self.legend = read_json(base / "legend.json")
        phys = read_json(base / "physics_checklist.json")
        self.physics_rules = list(phys["rules"])
        self.spec_rules = list(phys.get("spec_rules", []))
        self.physics_manual = list(phys.get("manual", []))
        self.stress = {}           # lowercase word -> stressed form with '+'
        self.glossary = []         # list of dicts {term, en?, ru?, definition?}
        self.misconceptions = []
        self.expansions = {}       # abbreviation -> spoken form (TTS)
        self.style_notes = []      # free-text style guide items for manual QA
        self.photos = []           # [{path, source, license, caption}]
        self.visuals = []          # [{match: [keywords], template, params, model?, class?}] — visual hints (data)
        self.found = {}
        if not self.dir or not self.dir.exists():
            return
        d = self.dir
        for p in _find(d, ["*legend*.json", "*style*.json", "*palette*.json"]):
            j = read_json(p) or {}
            self.legend = _deep_merge(self.legend, j.get("legend", j))
            self.found.setdefault("legend", []).append(str(p))
        for p in _find(d, ["*style*.md", "*legend*.md", "*style*.txt"]):
            self.style_notes += [l.strip("-*• ").strip() for l in p.read_text(encoding="utf-8").splitlines()
                                 if l.strip().startswith(("-", "*", "•"))]
            self.found.setdefault("style_notes", []).append(str(p))
        for p in _find(d, ["*stress*", "*ударен*", "*accent*"]):
            if p.suffix.lower() not in (".json", ".csv", ".tsv", ".txt", ".md", ""):
                continue
            rows = _read_table(p)
            if isinstance(rows, dict):
                rows = list(rows.items())
            for r in rows or []:
                if isinstance(r, dict):
                    k = _first(r, ["word", "term", "слово", "термин", "text"])
                    v = _first(r, ["stressed", "stress", "ударение", "tts", "pronunciation", "with_stress"])
                else:
                    k, v = r[0], r[1]
                if k and v:
                    v = _acute_to_plus(str(v))
                    self.stress[str(k).replace("+", "").replace("́", "").lower()] = v
            self.found.setdefault("stress", []).append(str(p))
        for p in _find(d, ["*glossar*", "*глоссар*", "*terms*"]):
            rows = _read_table(p)
            if isinstance(rows, dict):
                rows = [{"term": k, "definition": v} for k, v in rows.items()]
            for r in rows or []:
                if isinstance(r, dict):
                    self.glossary.append(r)
                    abbr = _first(r, ["abbr", "abbreviation", "аббревиатура"])
                    spoken = _first(r, ["spoken", "tts", "произношение", "read_as"])
                    if abbr and spoken:
                        self.expansions[abbr] = spoken
                else:
                    self.glossary.append({"term": r[0], "definition": r[1]})
            self.found.setdefault("glossary", []).append(str(p))
        for p in _find(d, ["*expansion*", "*abbrev*", "*сокращ*"]):
            rows = _read_table(p)
            if isinstance(rows, dict):
                self.expansions.update(rows)
            else:
                for r in rows or []:
                    if isinstance(r, (list, tuple)):
                        self.expansions[r[0]] = r[1]
        for p in _find(d, ["*physics*", "*физик*", "*checklist*"]):
            if p.suffix.lower() == ".json":
                j = read_json(p) or {}
                self.physics_rules += j.get("rules", []) if isinstance(j, dict) else []
                self.spec_rules += j.get("spec_rules", []) if isinstance(j, dict) else []
                self.physics_manual += j.get("manual", []) if isinstance(j, dict) else []
            else:
                self.physics_manual += [l.strip("-*•[] xX").strip() for l in
                                        p.read_text(encoding="utf-8").splitlines()
                                        if l.strip().startswith(("-", "*", "•", "["))]
            self.found.setdefault("physics", []).append(str(p))
        for p in _find(d, ["*misconcep*", "*заблужд*"]):
            j = read_json(p) if p.suffix == ".json" else None
            self.misconceptions += j if isinstance(j, list) else []
            self.found.setdefault("misconceptions", []).append(str(p))
        for p in _find(d, ["*visual*.json"]):
            j = read_json(p) or []
            self.visuals += j if isinstance(j, list) else j.get("visuals", [])
            self.found.setdefault("visuals", []).append(str(p))
        photo_meta = {}
        for p in _find(d, ["photos.json", "*photo*.json"]):
            for item in read_json(p) or []:
                photo_meta[Path(item.get("file", item.get("path", ""))).name] = item
        for p in _find(d, ["*.jpg", "*.jpeg", "*.png", "*.webp"]):
            meta = photo_meta.get(p.name, {})
            self.photos.append({"path": str(p), "source": meta.get("source"), "license": meta.get("license"),
                                "caption": meta.get("caption", p.stem), "tags": meta.get("tags", [])})

    # helpers ---------------------------------------------------------------
    def lith(self, name):
        """Resolve a lithology name in any language to its legend style."""
        key = str(name or "unknown").strip().lower()
        key = self.legend.get("lithology_aliases", {}).get(key, key)
        lit = self.legend["lithology"]
        if key not in lit:
            for k in lit:                       # 'глинистый песчаник' -> contains 'песчаник'
                if k in key:
                    key = k
                    break
            for alias, k in self.legend.get("lithology_aliases", {}).items():
                if alias in key:
                    key = k
                    break
        return key if key in lit else "unknown", lit.get(key, lit["unknown"])

    def fluid_color(self, name):
        key = str(name or "").strip().lower()
        key = self.legend.get("fluid_aliases", {}).get(key, key)
        return self.legend["fluids"].get(key, "#888888")

    def curve_color(self, mnemonic):
        c = self.legend.get("curves", {})
        return c.get(str(mnemonic).upper(), c.get("default", "#222222"))

    def summary(self):
        def rel(x):           # repo-relative paths in reports (no machine-specific absolute paths)
            try:
                return str(Path(x).resolve().relative_to(ROOT_DIR))
            except ValueError:
                return str(x)
        return {"dir": rel(self.dir) if self.dir else None,
                "found": {k: [rel(v) for v in vs] for k, vs in self.found.items()},
                "stress_entries": len(self.stress), "glossary_entries": len(self.glossary),
                "physics_rules": len(self.physics_rules), "physics_manual": len(self.physics_manual),
                "photos": len(self.photos)}


# ----------------------------------------------------------------------------- datasets

def scan_datasets(data_dirs):
    """Build a catalog of available open datasets: LAS curves, CSV columns, SEG-Y files.

    A hand-written catalog.json in a data dir adds licence/source/description and aliases.
    """
    catalog = []
    for dd in data_dirs:
        dd = Path(dd)
        if not dd.exists():
            continue
        manual = {}
        for cat in dd.rglob("catalog.json"):
            for e in read_json(cat) or []:
                manual[str((cat.parent / e["file"]).resolve())] = e
        for p in sorted(dd.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            entry = None
            if ext == ".las":
                entry = _scan_las(p)
            elif ext == ".csv":
                entry = _scan_csv(p)
            elif ext in (".sgy", ".segy"):
                entry = {"type": "segy", "file": str(p)}
            if entry:
                entry.update(manual.get(str(p.resolve()), {}))
                entry["file"] = str(p.resolve())
                catalog.append(entry)
    return catalog


def _scan_las(p):
    try:
        import lasio
        import warnings
        warnings.filterwarnings("ignore")
        las = lasio.read(str(p), ignore_data=False)
        curves = []
        for c in las.curves[1:]:
            v = las[c.mnemonic]
            import numpy as np
            ok = np.isfinite(v)
            if ok.sum() < 10:
                continue
            d = las.index[ok]
            curves.append({"mnemonic": c.mnemonic, "unit": c.unit, "descr": c.descr,
                           "depth_min": float(d.min()), "depth_max": float(d.max())})
        well = str(las.well.WELL.value) if "WELL" in las.well else p.stem
        return {"type": "las", "well": well, "index_unit": las.index_unit, "curves": curves}
    except Exception as e:
        return {"type": "las", "error": str(e)}


def _scan_csv(p):
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            header = f.readline().strip()
        cols = [c.strip().strip('"').lstrip("﻿") for c in header.split(",")]
        return {"type": "csv", "columns": cols}
    except Exception as e:
        return {"type": "csv", "error": str(e)}


def match_curves(catalog, wanted_terms):
    """Find LAS curves matching any of the wanted terms via mnemonics.json aliases."""
    aliases = read_json(RES_DIR / "mnemonics.json", {})
    wanted = {str(t).lower() for t in wanted_terms if t}
    hits = []
    for e in catalog:
        if e.get("type") != "las":
            continue
        for c in e.get("curves", []):
            mn = c["mnemonic"].upper()
            names = {mn.lower()} | {a.lower() for a in aliases.get(mn, [])}
            if any(w == n or (len(w) > 3 and w in n) or (len(n) > 3 and n in w) for w in wanted for n in names):
                hits.append({"file": e["file"], "well": e.get("well"), "curve": c["mnemonic"],
                             "unit": c["unit"], "depth_min": c["depth_min"], "depth_max": c["depth_max"],
                             "dataset": e.get("dataset", "open dataset"), "license": e.get("license")})
    return hits
