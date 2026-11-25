import json
from types import SimpleNamespace

from kmd import cli
from kmd.site import build


def _stages(monkeypatch):
    monkeypatch.setattr(cli, "_stage", lambda name: SimpleNamespace(run=lambda chapter, **kw: []))
    monkeypatch.setattr(cli, "chapter_config", lambda chapter: {"id": chapter})
    monkeypatch.setenv("KMD_LLM_PROVIDER", "queue")


def test_default_video_engine_is_legacy(monkeypatch):
    _stages(monkeypatch)
    used = []
    monkeypatch.setattr(cli, "_render_video", lambda args, node, fmt, engine=None: used.append((node, fmt, engine)) or [])
    assert cli.main(["run", "ch", "--video-node", "n1"]) == 0
    assert used == [("n1", "short", "legacy")]


def test_rebuild_keeps_each_video_engine(monkeypatch, tmp_path):
    _stages(monkeypatch)
    (tmp_path / "video" / "a").mkdir(parents=True)
    (tmp_path / "video" / "b").mkdir(parents=True)
    (tmp_path / "video" / "a" / "passport.json").write_text(json.dumps({"node_id": "a", "format": "short"}))
    (tmp_path / "video" / "b" / "passport.long.json").write_text(
        json.dumps({"node_id": "b", "format": "long", "engine": "vidpipe"}))
    monkeypatch.setattr(cli, "run_dir", lambda chapter: tmp_path)
    used = []
    monkeypatch.setattr(cli, "_render_video", lambda args, node, fmt, engine=None: used.append((node, fmt, engine)) or [])
    assert cli.main(["rebuild", "ch", "--video"]) == 0
    assert sorted(used) == [("a", "short", "legacy"), ("b", "long", "vidpipe")]


def test_site_does_not_embed_local_paths():
    cfg = {"book": {"title": "T", "md": "md/x.md", "md_path": "C:\\Users\\x\\x.md", "pdf_path": "/home/x/x.pdf"}}
    assert build._public_book(cfg) == {"title": "T", "md": "md/x.md"}


def test_svg_ids_are_deterministic(tmp_path):
    from kmd import visuals  # noqa: F401  (sets matplotlib style + svg.hashsalt)
    import matplotlib.pyplot as plt

    outs = []
    for i in range(2):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        p = tmp_path / f"{i}.svg"
        fig.savefig(p, format="svg", metadata={"Date": None})
        plt.close(fig)
        outs.append(p.read_text())
    assert outs[0] == outs[1]
