import json
import re
import shutil
from pathlib import Path

from kmd.course import stage
from kmd.site import build as site_build

FX = Path(__file__).parent / "fixtures" / "course"


def test_course_and_site_from_fixture(tmp_path, monkeypatch):
    shutil.copy(FX / "layer.json", tmp_path / "layer.json")
    shutil.copy(FX / "routing.json", tmp_path / "routing.json")
    answers = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (FX / "answers").glob("*.json")}

    def fake_complete_json(run_dir, task, prompt, variables, schema=None, **kw):
        assert prompt == "course_step", "fixture answers pass all checks, so no repair request is expected"
        nid = variables["node"]["id"]
        # the prompt must carry the node and the catalog
        assert variables["templates_text"] and variables["n_tasks"] >= 2
        stage.llm.validate(answers[nid], schema)
        return answers[nid]

    monkeypatch.setattr(stage.llm, "complete_json", fake_complete_json)
    monkeypatch.setattr(stage, "run_dir", lambda ch: tmp_path)
    monkeypatch.setattr(site_build, "run_dir", lambda ch: tmp_path)
    chapter = str(FX / "chapter.yaml")
    assert stage.run(chapter) == []
    rep = json.loads((tmp_path / "course_report.json").read_text(encoding="utf-8"))
    assert rep["steps_done"] == 3 and rep["tasks"] == 12
    assert len(rep["task_types"]) == 5
    assert rep["decision_steps"] == ["geo.fixture_latyshova.s20.03"]

    site = site_build.build(chapter)
    pages = {p.name for p in site.glob("*.html")}
    assert {"index.html", "step-01.html", "step-02.html", "step-03.html", "tasks.html", "cards.html", "summary.html", "map.html"} <= pages
    step = (site / "step-03.html").read_text(encoding="utf-8")
    # page refs on paragraphs, verbatim quotes, illustration with provenance, tasks with answer keys
    assert step.count('class="pg"') >= 5
    assert "«Поле зависимостей ρн = f (kн) разделяется здесь" in step
    assert 'class="prov"' in step
    assert "window.KMD_TASKS" in step
    # no external resources (works offline from file://)
    for page in pages:
        html = (site / page).read_text(encoding="utf-8")
        assert not re.search(r'(src|href)="(https?:)?//', html), page
    size = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    assert size < 30e6
