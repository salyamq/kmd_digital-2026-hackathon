"""Code-level checks of verify/checker/route (no LLM). Need runs/latyshova and runs/baraboshkin units/source pages."""
import json
from pathlib import Path

import pytest

from kmd.verify import _canon, check_text_numbers, extract_numbers, find_quote, normalize

ROOT = Path(__file__).resolve().parent.parent
need = pytest.mark.skipif(not (ROOT / "runs/latyshova/source_pages.json").exists(), reason="ingest not run")


def test_normalize_and_numbers():
    assert normalize("Ёлка — «тест»  про-\nверка") == normalize("елка - тест проверка")
    assert _canon("0,050") == _canon("0.05")
    nums = extract_numbers("kп = 17%, 0,05 Ом·м, 10³ мкм², A0,025")
    assert "17" in nums and "0,05" in nums and "103" not in nums


@need
def test_find_quote_page_logic():
    q = "Водоотдача - основной показатель качества глинистого раствора"
    assert find_quote(q, 90, "latyshova")["found"]
    r = find_quote(q, 97, "latyshova")
    assert not r["found"] and r["where"] == "other:90"
    assert not find_quote("этой фразы точно нет в главе про геофизику", 90, "latyshova")["found"]


@need
def test_numbers_against_source():
    assert check_text_numbers("оптимальная водоотдача 4—8 см³/ч", "latyshova") == []
    assert check_text_numbers("водоотдача 4321 см³/ч", "latyshova") == ["4321"]


@need
def test_checker_code_checks():
    from kmd.checker import code_checks

    f, _ = code_checks({"id": "x", "type": "frame", "text": "кадр: пролёт над рекой, без надписей и цифр",
                        "class": "D", "provenance": "иллюстрация ИИ"}, "baraboshkin")
    assert f == []
    f, _ = code_checks({"id": "y", "type": "frame", "text": "сгенерированный разрез с подписями фаций",
                        "class": "C", "provenance": "иллюстрация ИИ"}, "baraboshkin")
    assert f and f[0]["error_type"] == "frame_error"


def test_route_enforce():
    from kmd.route import enforce

    layer = {"nodes": [{"id": "a", "tables": [{}], "formulas": [], "worked_examples": [{}]},
                       {"id": "b", "tables": [], "formulas": [], "worked_examples": []}]}
    routes = [{"node_id": "a", "format": "short", "video_criteria": ["cause_effect"], "hook_only": True},
              {"node_id": "b", "format": "long", "video_criteria": [], "hook_only": False}]
    out, notes = enforce(routes, layer)
    assert out[0]["format"] in ("interactive", "data_practice") and out[1]["format"] == "interactive"
    assert any(r["format"] == "data_practice" for r in out)
