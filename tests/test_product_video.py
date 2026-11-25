from pathlib import Path

import pytest

from kmd import cli
from kmd.config import read_json, write_json
from kmd.video import vidpipe
from video.vidpipe import cli as renderer
from video.vidpipe.pipeline import Project
from video.vidpipe import tts


def test_run_renders_selected_video_before_site(monkeypatch):
    calls = []

    def stage(name):
        def run(chapter):
            calls.append((name, chapter))
            return []

        return type("Stage", (), {"run": run})

    monkeypatch.setattr(cli, "_stage", stage)
    monkeypatch.setattr(cli, "chapter_config", lambda chapter: {"id": chapter})
    monkeypatch.setattr(cli, "_render_video",
                        lambda args, node, fmt, engine=None: calls.append((node, fmt)) or [])

    assert cli.main(["run", "chapter", "--from", "course",
                     "--video-node", "node", "--video-format", "long"]) == 0
    assert calls == [("course", "chapter"), ("node", "long"), ("site", "chapter")]


@pytest.mark.parametrize("voice", ["none", "microsoft"])
def test_vidpipe_receives_original_claim_and_page(tmp_path, monkeypatch, voice):
    claim = {"id": "node.c01", "text": "A layer stores fluid in pores.", "page": 12,
             "quote": "The fluid occupies pore space.", "kind": "observation"}
    write_json(tmp_path / "source_pages.json", {"12": claim["quote"]})
    write_json(tmp_path / "layer.json", {"domain": "geology", "language": "ru", "nodes": [{
        "id": "node", "title_beginner": "Fluid in the rock", "claims": [claim],
    }]})
    monkeypatch.setattr(vidpipe, "run_dir", lambda _: tmp_path)
    monkeypatch.setattr(vidpipe, "chapter_config", lambda _: {"book": {"title": "Source"}})
    monkeypatch.setattr(vidpipe.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(tts, "available_provider", lambda provider: provider)
    attempts = []

    def render(directory, start=None):
        project = Project(directory)
        provider = project.brief["tts"]["provider"]
        attempts.append((provider, start))
        if provider == "microsoft":
            raise tts.MicrosoftSpeechError("service error")
        assert project.brief["format"] == "explainer"
        assert project.node["id"] == "node"
        assert project.node["claims"][0]["id"] == claim["id"]
        assert project.pages.find_quote(claim["quote"], 12)["status"] == "verified"
        output = Path(directory) / "08_final" / "long.mp4"
        output.parent.mkdir()
        output.write_bytes(b"video")
        write_json(directory / "passport.json", {
            "format": {"duration_s": 120}, "qa_failures": [],
            "tools": {"tts": {"provider": "none"}},
        })

    monkeypatch.setattr(renderer, "run_stages", render)
    vidpipe.run("chapter", "node", "long", planner="rule", tts=voice)
    expected = [("none", None)] if voice == "none" else [("microsoft", None), ("piper", "audio")]
    assert attempts == expected
    out = tmp_path / "video" / "node"
    assert (out / "long.mp4").read_bytes() == b"video"
    passport = read_json(out / "passport.long.json")
    assert (passport["engine"], passport["format"], passport["duration_s"]) == ("vidpipe", "long", 120)
