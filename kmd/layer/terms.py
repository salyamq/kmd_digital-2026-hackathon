"""Term matching helpers (language-level, no domain knowledge): used by layer (graph hints) and verify."""
from __future__ import annotations

import re
from functools import lru_cache

_WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")


def _stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    if len(w) <= 4 or not re.search(r"[а-я]", w):
        return re.escape(w)
    # crude Russian stemming: drop up to 3 trailing letters (inflection) for long words
    cut = 2 if len(w) <= 6 else 3
    return re.escape(w[:-cut]) + r"[а-яё]{0,5}"


@lru_cache(maxsize=4096)
def term_regex(term: str) -> re.Pattern | None:
    """Regex that matches inflected forms of a (multi-word) term. Abbreviations match case-sensitively."""
    t = re.sub(r"\(.*?\)", "", term).strip()
    words = _WORD.findall(t)
    if not words:
        return None
    if len(words) == 1 and words[0].isupper() and len(words[0]) <= 6:
        return re.compile(r"(?<![A-Za-zА-Яа-яЁё])" + re.escape(words[0]) + r"(?![A-Za-zА-Яа-яЁё])")
    pat = r"[\s\-]+(?:[а-яё]+\s+)?".join(_stem(w) for w in words)
    return re.compile(r"(?<![a-zа-яё])" + pat, re.I)


def uses_term(text: str, term: str) -> bool:
    rx = term_regex(term)
    return bool(rx and rx.search(text.replace("ё", "е").replace("Ё", "Е")))


def node_text(node: dict) -> str:
    """All learner-visible prose of a node (for term/number checks)."""
    parts = [node.get("title_beginner", "")]
    lay = node.get("layers", {})
    for k in ("mechanism", "practice", "nuances"):
        v = lay.get(k)
        if isinstance(v, dict):
            parts.append(v.get("text", ""))
    for c in node.get("claims", []):
        parts.append(c.get("text", ""))
    for p in node.get("procedure", []) or []:
        parts.append(p if isinstance(p, str) else p.get("text", ""))
    return "\n".join(parts)
