"""Video tooling checks that need no network: pronunciation dictionary, script rules, timeline,
scene checks, subtitles, ASR text normalization."""
import json
from pathlib import Path

from kmd.scenes import check_scene
from kmd.video import render, tts
from kmd.video.asr import normalize, wer
from kmd.video.script_checks import check_script

FIX = Path(__file__).parent / "fixtures"

NODE = {"id": "geo.stub.s20.01", "claims": [{"id": "c01", "text": "a"}, {"id": "c02", "text": "b"}, {"id": "c03", "text": "c"}]}


def _scene():
    return json.loads((FIX / "scene_stub_short.json").read_text(encoding="utf-8"))


def _script():
    ph = [
        {"id": "p1", "role": "hook", "kind": "question", "text": "Прибор не видит нефть. Как он находит пласт?", "caption": "Как найти пласт?", "frame_id": "f1", "claim_ids": []},
        {"id": "p2", "role": "problem", "kind": "observation", "text": "Против глин кривая ПС — потенциалы самопроизвольной поляризации — стоит ровно.", "caption": "Линия глин", "frame_id": "f1", "claim_ids": ["c01"]},
        {"id": "p3", "role": "prediction", "kind": "question", "text": "Что будет против песчаника?", "caption": "Что в песчанике?", "frame_id": "f2", "claim_ids": []},
        {"id": "p4", "role": "answer", "kind": "observation", "text": "Кривая отклоняется от линии глин.", "caption": "Отклонение ПС", "frame_id": "f2", "claim_ids": ["c01"]},
        {"id": "p5", "role": "honesty", "kind": "observation", "text": "Вот пласт в истинном масштабе.", "caption": "Истинный масштаб", "frame_id": "f3", "claim_ids": ["c01"]},
        {"id": "p6", "role": "transfer", "kind": "question", "text": "Как научить программу находить такие пласты?", "caption": "Как автоматизировать?", "frame_id": "f4", "claim_ids": []},
    ]
    return {"node_id": NODE["id"], "format": "short", "phrases": ph,
            "prediction": {"question_phrase_id": "p3", "answer_phrase_id": "p4"}, "transfer_question": "x",
            "data_it_bridge": "y", "terms_introduced": []}


def test_stub_scene_passes_checks():
    e, w, sc = check_scene(_scene(), NODE, "short")
    assert e == []
    assert any(f.get("true_scale") for f in sc["frames"])


def test_scene_check_catches_bad_physics_and_refs():
    sc = _scene()
    sc["views"]["log"]["params"]["layers"][1]["fluid"] = "water"
    sc["views"]["log"]["params"]["layers"][2]["fluid"] = "oil"   # oil below water in one sand body
    sc["frames"][0]["claim_ids"] = ["c99"]
    e, _, _ = check_scene(sc, NODE, "short")
    assert any("fluid_order" in x for x in e)
    assert any("c99" in x for x in e)


def test_script_rules():
    entries = tts.load_dict("geology")
    e, w = check_script(_script(), _scene(), NODE, "short", entries)
    assert not [x for x in e if "слов —" not in x]  # only the length rule may fire on this tiny stub
    bad = _script()
    bad["phrases"][1]["text"] = "Пористость 20 процентов и ρ равно пяти омметрам."
    bad["phrases"][0]["role"] = "problem"
    e, _ = check_script(bad, _scene(), NODE, "short", entries)
    assert any("словами" in x for x in e)
    assert any("крючком" in x for x in e)


def test_stress_dict_applies():
    entries = tts.load_dict("geology")
    say, ear = tts.apply_dict("Кривая ПС против коллектора, дебит скважины.", entries)
    assert "пэ эс" in say
    assert "колле\u0301ктора" in say
    assert "де\u0301бит" in say
    assert "дебит" in ear


def test_timeline_pause_and_min_caption():
    ph = _script()["phrases"]
    a = {p["id"]: {"duration": 0.8 if p["id"] == "p4" else 2.5} for p in ph}
    tl = render.build_timeline(ph, a, "p3")
    rows = {r["id"]: r for r in tl["phrases"]}
    assert rows["p1"]["start"] < 3.0                      # hook inside the first 3 s
    gap = rows["p4"]["start"] - rows["p3"]["end"]
    assert 1.0 <= gap - render.GAP <= 1.6                  # prediction pause 1–1.5 s
    assert rows["p5"]["start"] - rows["p4"]["start"] >= 1.5  # caption at least 1.5 s
    blocks = render.frame_blocks(tl["phrases"])
    frames = {f["id"]: f for f in _scene()["frames"]}
    st = render.state_at(rows["p3"]["end"] + 0.5, tl, frames, blocks)
    assert st["overlay"] == "predict"
    st2 = render.state_at(rows["p3"]["end"] + 1.0, tl, frames, blocks)
    assert st2["t"] == st["t"]                              # model frozen during the pause


def test_srt(tmp_path):
    ph = _script()["phrases"]
    tl = render.build_timeline(ph, {p["id"]: {"duration": 2.0} for p in ph}, "p3")
    render.write_srt(tl, tmp_path / "a.srt")
    txt = (tmp_path / "a.srt").read_text(encoding="utf-8")
    assert "-->" in txt and "Прибор не видит нефть" in txt


def test_asr_normalization():
    assert normalize("Пористость 20%.") == ["пористость", "двадцать", "процентов"]
    assert wer(["а", "б", "в"], ["а", "б", "в"]) == 0
    assert abs(wer(["а", "б", "в", "г"], ["а", "х", "в", "г"]) - 0.25) < 1e-9


def test_crossplot_constant_matches_every_x():
    import numpy as np
    from kmd.visuals.templates.crossplot import safe_eval

    x = np.array([1.0, 2.0, 3.0])
    assert safe_eval("0.5", x).tolist() == [0.5, 0.5, 0.5]


def test_scene_flags_unsourced_real_data_bars():
    scene = _scene()
    scene["views"]["log"] = {"template": "comparison_bar",
                              "params": {"items": [{"label": "Замер", "value": 573.8}]}}
    errors, _, _ = check_scene(scene, NODE, "short")
    assert any("573.8" in error for error in errors)
