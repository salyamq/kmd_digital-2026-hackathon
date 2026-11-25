import copy
import json
from pathlib import Path

import pytest

from kmd.course import checks as C
from kmd.course import stage

FX = Path(__file__).parent / "fixtures" / "course"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_sentences_and_limits():
    t = "В хороших условиях она не больше 1 см, при плохом растворе достигает 3–4 см. При бурении на воде нет. См. рис. 69."
    ss = C.sentences(t)
    assert len(ss) == 3
    assert not C.long_sentences(t)
    long = " ".join(["слово"] * 21) + "."
    assert C.long_sentences(long)


def test_numbers_and_unknown():
    assert C.numbers("при 4–8 см³/ч, kп* = 17%, ρ = 0,25 Ом·м") == ["4", "8", "17", "0.25"]
    assert C.unknown_numbers("порог 17% и 42 м", {"17"}) == ["42"]
    assert C.unknown_numbers("шаг 2 из 3", set()) == []  # trivial small integers are not facts


def test_find_evidence_normalizes():
    chunks = [("how-1", "Граница проходит при **kп*** = 17%. «Ёлка» — тест")]
    assert C.find_evidence("граница проходит при kп* = 17%", chunks) == "how-1"
    assert C.find_evidence("елка - тест", chunks) == "how-1"
    assert C.find_evidence("нет такого текста", chunks) is None


def _ctx(layer, tmp_path):
    return {
        "source_numbers": stage.source_number_set(tmp_path, layer),
        "catalog": [{"template": t, "source": "builtin"} for t in ("chain", "contrast", "ranges", "decision", "regions2d")],
        "ill_dir": tmp_path / "illustrations",
        "run_dir": tmp_path,
        "need_decision": False,
    }


@pytest.mark.parametrize("nid", ["geo.fixture_latyshova.s17.01", "geo.fixture_latyshova.s20.01", "geo.fixture_latyshova.s20.03"])
def test_fixture_answers_pass_all_checks(nid, tmp_path):
    layer = load("layer.json")
    node = next(n for n in layer["nodes"] if n["id"] == nid)
    ans = load(f"answers/{nid}.json")
    stage.validate_answer(ans)
    res = stage.assemble(node, ans, _ctx(layer, tmp_path))
    assert res["errors"] == [], res["errors"]
    assert res["illustrations"], "at least one illustration per step"
    assert all(not t.get("_bad") for t in res["tasks"])
    assert all(t["anchor"] for t in res["tasks"]), "every task points to the place of its answer"


def test_checks_catch_bad_answer(tmp_path):
    layer = load("layer.json")
    node = next(n for n in layer["nodes"] if n["id"] == "geo.fixture_latyshova.s17.01")
    ans = copy.deepcopy(load("answers/geo.fixture_latyshova.s17.01.json"))
    ans["how_it_works"] = ans["how_it_works"][:-1]  # drop the paragraph covering c06
    ans["essence"][0] = " ".join(["очень"] * 22) + "."
    ans["how_it_works"][0]["text"] += " Водоотдача бывает 37 см³/ч."
    ans["tasks"][0]["evidence"] = "этого текста нет в шаге"
    ans["tasks"][1]["claim_id"] = "c99"
    ans["illustrations"][0]["template"] = "no_such_template"
    res = stage.assemble(node, ans, _ctx(layer, tmp_path))
    errs = "\n".join(res["errors"])
    assert "c06" in errs  # uncovered claim
    assert "длиннее 20 слов" in errs
    assert "37" in errs  # number not in source
    assert "evidence не найден" in errs
    assert "c99" in errs
    assert "неизвестный шаблон" in errs


def test_task_type_checks():
    claims = {"c1": {"id": "c1", "page": 1}}
    chunks = [("how-1", "Порог равен 17%. Корка тоньше 1 см.")]
    ok = {"type": "numeric", "question": "Порог?", "answer": 17, "tolerance": 0, "explanation": "x", "evidence": "Порог равен 17%", "claim_id": "c1"}
    assert stage.check_task(ok, claims, chunks, {"17"}) == []
    bad = dict(ok, answer=18)
    assert any("не встречается" in e for e in stage.check_task(bad, claims, chunks, {"17"}))
    single2 = {"type": "single", "question": "Вопрос?", "options": ["a", "b", "c"], "correct": [0, 1], "explanation": "x", "evidence": "Порог равен 17%", "claim_id": "c1"}
    assert any("ровно один" in e for e in stage.check_task(single2, claims, chunks, {"17"}))
    cloze = {"type": "cloze", "question": "Вставьте", "text": "Корка ___ 1 см.", "blanks": [{"answers": ["тоньше"], "options": ["толще", "тоньше"]}], "explanation": "x", "evidence": "Корка тоньше 1 см", "claim_id": "c1"}
    assert stage.check_task(cloze, claims, chunks, {"17"}) == []


def test_plan_gives_enough_tasks_and_a_decision_step():
    layer = load("layer.json")
    routing = {r["node_id"]: r for r in load("routing.json")}
    pl = stage.plan(layer, routing)
    assert sum(p["need_decision"] for p in pl.values()) >= 1
    assert pl["geo.fixture_latyshova.s20.03"]["need_decision"]  # routed data_practice
    types = {t for p in pl.values() for t in p["preferred_types"]}
    assert len(types) >= 4


def test_decision_with_unsupported_numbers_is_not_published(tmp_path):
    layer = load("layer.json")
    node = next(n for n in layer["nodes"] if n["id"] == "geo.fixture_latyshova.s17.01")
    ans = load("answers/geo.fixture_latyshova.s17.01.json")
    ans["decision"] = {
        "title": "Проверка условий",
        "signs": ["Число 38953"],
        "rule": "Сначала сверить условия.",
        "conclusion": "Условия определяют вывод.",
        "claim_ids": [node["claims"][0]["id"]],
    }
    res = stage.assemble(node, ans, _ctx(layer, tmp_path))
    assert any(error.startswith("decision: числа") for error in res["errors"])
    assert not any(block["kind"] == "decision" for block in res["blocks"])
