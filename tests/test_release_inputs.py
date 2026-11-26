import time
from pathlib import Path
import json
from types import SimpleNamespace

from PIL import Image
import pytest
import yaml

from kmd import ingest, llm


def test_markdown_with_numbered_images_and_no_pdf(monkeypatch, tmp_path):
    data = tmp_path / "data"
    images = data / "scans"
    images.mkdir(parents=True)
    (data / "chapter.md").write_text(
        "<!-- page 7 -->\n\n## Пористые среды\n\nПоры могут соединяться друг с другом.\n",
        encoding="utf-8",
    )
    Image.new("RGB", (13, 19), "white").save(images / "page-007.jpg")
    config = tmp_path / "chapter.yaml"
    config.write_text(yaml.safe_dump({
        "id": "images_example", "language": "ru",
        "book": {"md": "chapter.md", "page_images": "scans"},
        "segments": [{"pages": [7, 7]}],
    }), encoding="utf-8")
    monkeypatch.setenv("KMD_DATA", str(data))
    monkeypatch.delenv("KMD_FORCE_PDF", raising=False)
    monkeypatch.setattr("kmd.config.RUNS", tmp_path / "runs")

    assert ingest.run(config.as_posix()) == []
    run = tmp_path / "runs" / "images_example"
    assert not (run / "pdf2md_report.json").exists()
    assert ingest.load_units(config.as_posix())["pages"] == [7]
    with Image.open(run / "pages/p7.png") as page:
        assert page.format == "PNG"
        assert page.size == (13, 19)


def test_numbered_images_require_each_source_page(tmp_path):
    with pytest.raises(ValueError, match="страниц: 12"):
        ingest._import_page_images(tmp_path, [12], tmp_path / "out")


@pytest.mark.parametrize(("endpoint", "model", "override", "disabled"), [
    ("https://openrouter.ai/api/v1", "deepseek/deepseek-v4.1-flash-1017", None, True),
    ("https://openrouter.ai/api/v1", "deepseek/deepseek-v4.1-flash-1017", "default", False),
    ("https://openrouter.ai/api/v1", "openai/gpt-6-luna", None, False),
    ("https://provider.example/v1", "deepseek/deepseek-v4.1-flash-1017", "off", False),
])
def test_reasoning_option_for_openrouter(monkeypatch, endpoint, model, override, disabled):
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    monkeypatch.setenv("KMD_LLM_MODEL", model)
    if override is None:
        monkeypatch.delenv("KMD_OPENROUTER_REASONING", raising=False)
    else:
        monkeypatch.setenv("KMD_OPENROUTER_REASONING", override)
    options = {}
    result = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2, model_extra={"cost": 0.001}),
    )

    def create(**kwargs):
        options.update(kwargs)
        return result

    completions = SimpleNamespace(create=create)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr("openai.OpenAI", lambda **_: client)

    text, usage, returned = llm._call_openai("system", "task", 32000)
    assert (text, returned) == ("{}", model)
    assert usage["cost_usd"] == 0.001
    assert usage["finish_reason"] == "stop"
    if disabled:
        assert options["extra_body"] == {
            "reasoning": {"enabled": False}, "provider": {"require_parameters": True},
        }
    else:
        assert "extra_body" not in options



def test_organizer_review_flattens_items_and_attaches_package_frames(tmp_path):
    from kmd.checker import _organizer_remarks, _review_batch
    from kmd.checker.load import flatten

    (tmp_path / "frames").mkdir()
    image = tmp_path / "frames" / "scene.png"
    Image.new("RGB", (4, 4)).save(image)
    entries = [
        {"id": "C1", "type": "claim", "text": "Текст", "page_pdf": 7},
        {"id": "A1", "type": "analogy", "text": "Аналогия", "breaks_where": "граница"},
        {"id": "S1", "type": "scene_fact", "text": "Параметр", "video_id": "v"},
        {"id": "L1", "type": "script_line", "text": "Фраза", "on_screen": "Плашка", "claim_ref": "C1"},
    ]
    items = flatten({"items": entries, "frames": [
        {"id": "F1", "file": "frames/scene.png", "frame_class": "B", "label": "схема", "video_id": "v"},
    ]})
    assert items[3]["page"] == 7
    assert "граница" in items[1]["text"]
    assert "Плашка" in items[3]["text"]
    messages, attachments, context = _review_batch(items, tmp_path, {"v": {"invariants": []}})
    assert messages[-1]["image_index"] == 1
    assert attachments == [str(image)]
    assert context == {"v": {"invariants": []}}
    with pytest.raises(ValueError, match="Недопустимый путь"):
        _review_batch([dict(items[-1], image="../outside.png")], tmp_path, {})
    assert _organizer_remarks([{
        "target_id": "C1", "error_type": "measured_vs_derived", "severity": 3,
        "message": "Проблема", "fix": "Правка", "page": 7,
    }]) == [{
        "target": "C1", "category": "measured_vs_inferred", "severity": "critical",
        "problem": "Проблема", "fix": "Правка", "page_pdf": 7, "quote": None,
    }]


def test_checker_retrieves_passage_from_its_actual_page():
    from kmd.checker import retrieve

    first = "Глинистый раствор"
    unit = {"kind": "paragraph", "page": 7, "text": first + " Тепловой поток",
            "page_breaks": [{"offset": len(first), "page": 8}]}
    assert retrieve({"text": "Тепловой поток"}, [unit], k=1) == [{"page": 8, "text": "Тепловой поток"}]


def test_transport_errors_are_retried_but_client_errors_are_not(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    seq = [json.JSONDecodeError("Expecting value", "\n", 0), "", "{}"]

    def flaky(system, user, max_tokens, images):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"finish_reason": "stop"}, "m"

    assert llm._call_with_retry(flaky, "s", "u", 10, (), tries=3)[0] == "{}"

    class BadRequest(Exception):
        status_code = 400

    calls = []

    def bad(*_a):
        calls.append(1)
        raise BadRequest("no")

    with pytest.raises(BadRequest):
        llm._call_with_retry(bad, "s", "u", 10, (), tries=3)
    assert len(calls) == 1
    with pytest.raises(llm.LLMError):
        llm._call_with_retry(lambda *_a: ("", {"finish_reason": "stop"}, "m"), "s", "u", 10, (), tries=2)


def test_pmap_keeps_order_and_collects_pending(monkeypatch):
    monkeypatch.setattr(llm, "parallelism", lambda: 4)

    def f(x):
        if x == 2:
            raise llm.PendingLLM(Path(f"p{x}"))
        time.sleep(0.01 * (5 - x))
        return x * 10

    assert llm.pmap(f, range(5)) == [("ok", 0), ("ok", 10), ("pending", Path("p2")), ("ok", 30), ("ok", 40)]
