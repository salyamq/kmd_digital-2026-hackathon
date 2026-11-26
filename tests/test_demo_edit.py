from kmd import demo, edits


def test_override_merges_with_existing_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(edits, "OVERRIDES", tmp_path)
    (tmp_path / "ch").mkdir()
    (tmp_path / "ch" / "n1.json").write_text('{"layers": {"deeper": []}, "claims_patch": {"c0": {"page": 3}}}', encoding="utf-8")
    path = demo.write_override("ch", "n1", "c1", "в 1857 г.")
    patch = edits.read_json(path)
    assert patch["layers"] == {"deeper": []}
    assert patch["claims_patch"] == {"c0": {"page": 3}, "c1": {"text": "в 1857 г."}}


def test_find_claim_and_overridden_numbers_apply():
    layer = {"nodes": [{"id": "n1", "claims": [{"id": "c1", "text": "в 1856 г."}]}]}
    node, claim = demo.find_claim(layer, "c1")
    assert node["id"] == "n1" and claim["text"] == "в 1856 г."
