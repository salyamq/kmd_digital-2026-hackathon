"""Code-level checks of course content (no LLM): text limits, evidence substrings, numbers vs source."""
from __future__ import annotations

import re

MAX_SENTENCE_WORDS = 20

_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_QUOTES = "«»„“”\"'’‘`"


def norm(s: str) -> str:
    """Normalize for substring matching: case, ё, dashes, quotes, markup, whitespace."""
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"\*\*|__|\$", "", s)
    for d in _DASHES:
        s = s.replace(d, "-")
    for q in _QUOTES:
        s = s.replace(q, "")
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def strip_markup(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(s or ""))


_ABBR = r"(?:стр|рис|табл|т\.\s?е|т\.\s?к|им|гл|ед|усл|прим|напр|e\.g|i\.e|fig|eq|vs|Dr|Mr|St)"


def sentences(text: str) -> list[str]:
    t = strip_markup(text)
    t = re.sub(r"\$[^$]*\$", "F", t)  # inline math counts as one word
    # protect abbreviations and decimals
    t = re.sub(rf"\b({_ABBR})\.", lambda m: m.group(1).replace(".", "§") + "§", t, flags=re.I)
    parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«\"(])", t)
    return [p.replace("§", ".").strip() for p in parts if p.strip()]


def words(sentence: str) -> int:
    return len([w for w in re.split(r"\s+", sentence) if re.search(r"\w", w)])


def long_sentences(text: str, limit: int = MAX_SENTENCE_WORDS) -> list[str]:
    return [s for s in sentences(text) if words(s) > limit]


_NUM = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)")


def numbers(text: str) -> list[str]:
    """Numbers in text, normalized (decimal comma -> dot, no leading zeros)."""
    t = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}\b)", "", str(text or ""))  # 10 000 -> 10000
    out = []
    for m in _NUM.finditer(t):
        out.append(norm_number(m.group(1)))
    return out


def norm_number(s: str) -> str:
    s = s.replace(",", ".")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    s = s.lstrip("0") or "0"
    if s.startswith("."):
        s = "0" + s
    return s


def number_set(text: str) -> set[str]:
    return set(numbers(text))


# Small integers appear everywhere (list markers, «2–3 фразы», «один из двух») and are not facts.
TRIVIAL_NUMBERS = {str(i) for i in range(0, 11)}


def unknown_numbers(text: str, source_numbers: set[str]) -> list[str]:
    return sorted({n for n in numbers(text) if n not in source_numbers and n not in TRIVIAL_NUMBERS})


def find_evidence(evidence: str, chunks: list[tuple[str, str]]) -> str | None:
    """Return the id of the first chunk (id, text) that contains the evidence (normalized), else None."""
    ev = norm(strip_markup(evidence))
    if len(ev) < 6:
        return None
    for cid, text in chunks:
        if ev in norm(strip_markup(text)):
            return cid
    return None


def stem_in(answer: str, text: str) -> bool:
    """Loose containment for answers of cloze tasks: every word (cut to a 5-char stem) is in text."""
    t = norm(text)
    for w in re.findall(r"[\wа-яё]+", norm(answer)):
        st = w[:5] if len(w) > 5 else w
        if st not in t:
            return False
    return True
