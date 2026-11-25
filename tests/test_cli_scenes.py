from types import SimpleNamespace

import pytest

from kmd import cli


@pytest.mark.parametrize(
    ("provider", "args", "scenes_requested"),
    [
        ("queue", ["run", "chapter"], False),
        ("queue", ["rebuild", "chapter"], False),
        ("queue", ["run", "chapter", "--with-scenes"], True),
        ("queue", ["run", "chapter", "--to", "scenes"], True),
        ("openai", ["run", "chapter"], True),
    ],
)
def test_pipeline_scene_queue_policy(monkeypatch, provider, args, scenes_requested):
    stages = []

    def stage(name):
        def run(chapter):
            stages.append(name)
            return ["scene-request.json"] if name == "scenes" else []

        return SimpleNamespace(run=run)

    monkeypatch.setattr(cli, "_stage", stage)
    monkeypatch.setattr(cli, "chapter_config", lambda chapter: {"id": chapter})
    monkeypatch.setenv("KMD_LLM_PROVIDER", provider)

    assert cli.main(args) == (cli.EXIT_PENDING if scenes_requested else 0)
    assert ("scenes" in stages) == scenes_requested
    if not scenes_requested:
        assert stages[-2:] == ["course", "site"]


def test_pipeline_still_reports_pending_course(monkeypatch):
    def stage(name):
        assert name != "site"
        return SimpleNamespace(run=lambda chapter: ["step-request.json"] if name == "course" else [])

    monkeypatch.setenv("KMD_LLM_PROVIDER", "queue")
    monkeypatch.setattr(cli, "_stage", stage)
    assert cli.main(["run", "chapter"]) == cli.EXIT_PENDING
