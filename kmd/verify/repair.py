"""Remove unsupported decimal approximations while retaining their symbolic expressions."""
from __future__ import annotations

import re
from copy import deepcopy

from . import check_text_numbers, extract_numbers

_VALUE = r"[+\-−]?\d+(?:[.,]\d+)?"
_RADICAL = r"(?:√\s*(?:\([^()\n]+\)|[\w]+)|\\sqrt\{[^{}\n]+\})"
_EXPRESSION = rf"(?:{_RADICAL}(?:\s*/\s*\d+)?|\d+\s*/\s*\d+)"
_APPROXIMATION = re.compile(
    rf"(?<![\w.,]){_EXPRESSION}(?P<tail>\s*(?:≈|≃|\\approx\b)\s*"
    rf"(?P<value>{_VALUE})(?:\s*%)?)(?=\s*(?:[,.;!?)$]|\\\)|$))"
)
_PERCENT_GLOSS = re.compile(
    rf",\s*то есть\b[^.,!?;%]*?(?<![\w.,])(?P<value>{_VALUE})\s*%\s*(?=[.!?;]|$)",
    re.IGNORECASE,
)


def _strip_unsupported_approximations(text: str, chapter: str) -> str:
    spans = []
    for match in _APPROXIMATION.finditer(text):
        drop_value = bool(check_text_numbers(match["value"], chapter))
        end = match.end()
        gloss = _PERCENT_GLOSS.match(text, end)
        if (gloss and extract_numbers(gloss[0]) == [gloss["value"]]
                and check_text_numbers(gloss["value"], chapter)):
            start = match.start("tail") if drop_value else gloss.start()
            spans.append((start, gloss.end()))
        elif drop_value:
            spans.append((match.start("tail"), end))

    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text


def strip_generated_approximations(chapter: str, layer: dict, findings: list[dict]) -> tuple[dict, list[str]]:
    """Propose edits to generated explanations flagged by the number check."""
    invalid_fields = {finding["target"] for finding in findings if finding["type"] == "number_not_in_source"}
    if not invalid_fields or "_layer" in layer.get("overrides_applied", []):
        return layer, []

    candidate = deepcopy(layer)
    changed = []
    for node in candidate["nodes"]:
        if node.get("_overridden"):
            continue
        explanations = node.get("layers", {})
        fields = [(role, explanations.get(role) or {}, ("text",)) for role in ("mechanism", "practice", "nuances")]
        fields.extend((f"deeper[{i}]", item, ("title", "text")) for i, item in enumerate(explanations.get("deeper") or []))
        for field, item, keys in fields:
            target = f"{node['id']}.layers.{field}"
            if target not in invalid_fields:
                continue
            for key in keys:
                original = item.get(key, "")
                updated = _strip_unsupported_approximations(original, chapter)
                if updated != original:
                    item[key] = updated
                    changed.append(f"{target}.{key}")
    return candidate, changed
