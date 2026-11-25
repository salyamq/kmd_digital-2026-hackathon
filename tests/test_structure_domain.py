from pathlib import Path

import kmd.domain as dom
from kmd.config import chapter_config, domain_pack


def test_write_pack(tmp_path, monkeypatch):
    real = Path(dom.DOMAINS)
    tmp = tmp_path / "domains"
    (tmp / "geology").mkdir(parents=True)
    for f in real.joinpath("geology").iterdir():
        (tmp / "geology" / f.name).write_bytes(f.read_bytes())
    monkeypatch.setattr(dom, "DOMAINS", tmp)
    base = {"pack": {"audience": "x", "voice": None}, "difficulty_types": {"types": {"М": {"name": "механизм"}}}}
    res = {"glossary": [{"term": "долото", "en": "bit", "definition": "инструмент"}],
           "misconceptions": [{"text": "a", "correction": "b"}], "physics_checklist": "## Процессы\n- [ ] x",
           "it_bridges": [{"concept": "c", "analogy": "a", "breaks_where": "b"}],
           "stress_dict": [{"term": "долото", "kind": "stem", "say": "долото́", "expansion": None}],
           "pack": {"name": "Бурение", "id_prefix": "drl", "audience": "", "data_context": {}},
           "difficulty_hints": {"М": "циркуляция раствора"}}
    dom.write_pack("drilling", res, base, chapter_config("latyshova"))
    files = {p.name for p in (tmp / "drilling").iterdir()}
    assert {"pack.yaml", "glossary.json", "misconceptions.json", "physics_checklist.md", "it_bridges.json",
            "stress_dict.json", "difficulty_types.yaml"} <= files


def test_digest_budget():
    import json
    u = json.load(open(Path(__file__).resolve().parent.parent / "runs/latyshova/units.json"))["units"]
    d = dom.chapter_digest(u, budget=8000)
    assert len(d) < 16000 and "§ 20" in d
