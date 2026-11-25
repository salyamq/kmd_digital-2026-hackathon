"""Self-test of the generic pipeline.

  python -m vidpipe selftest [out_dir] [--quick] [--tts rhvoice|none]

Parts (each reported in out_dir/selftest_report.md):
  templates    every scene template rendered from its own example, portrait + landscape (contact sheets)
  unit         unit tests (Yandex SpeechKit adapter with a mocked HTTP server, wrap rules, quote matching)
  unseen       two nodes the pipeline was never tuned on (tests/fixtures: gas slug catcher, drilling mud),
               built end-to-end with the RULE planner (no LLM, no hand plan); QA must pass
  mutation     a wrong number in the narration + a fake quote in the node -> QA must FAIL and DRAFT must appear
  robustness   missing earlier outputs -> --from fails fast with the stage to re-run; stages recreate folders
  determinism  rebuild the same video twice from its saved specs -> identical mp4 hash
--quick skips the parts that build videos (unseen, mutation, robustness, determinism) and runs the mutation
test at truth-gate level instead.
"""
import shutil
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

from .evaluator import run_model
from .inputs import DomainPack
from .overlays import OverlayRenderer, composite
from .render2d import Renderer
from .templates import REGISTRY
from .templates.base import Ctx
from .util import RES_DIR, ROOT_DIR, read_json, write_json

TEST_MODELS = {
    "depth_track": {"type": "formula", "grid": {"depth": {"from": 1000, "to": 1100, "n": 400, "unit": "m"}},
                    "expr": "60 + 50*sin(depth/7) + 20*sin(depth/2.3)", "output": {"name": "value"}},
    "field_evolution": {"type": "formula",
                        "params": {"D": {"value": 0.3, "unit": "m**2/s"}, "A": {"value": 1e5, "unit": "Pa"}},
                        "grid": {"r": {"from": 0.1, "to": 2000, "n": 160, "unit": "m", "scale": "log"},
                                 "t": {"from": 60, "to": 864000, "n": 50, "unit": "s", "scale": "log"}},
                        "expr": "A*E1(r**2/(4*D*t))", "output": {"name": "dp"}},
    "data_chart": {"type": "formula", "grid": {"x": {"from": 0, "to": 30, "n": 60}},
                   "expr": "200 + 40*(1-exp(-x/4))", "output": {"name": "y_P"}},
}


def run_templates(out_dir="selftest_out", frac=(0.35, 0.95)):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    i18n = read_json(RES_DIR / "i18n.json")
    dom = DomainPack(None)
    results = {}
    for theme_id in ("F",):
        theme = read_json(RES_DIR / "themes" / f"{theme_id}.json")
        for orient, (w, h) in (("portrait", (720, 1280)), ("landscape", (1920, 1080))):
            tiles = []
            for name, cls in REGISTRY.items():
                if name in ("photo", "ai_clip"):
                    continue
                try:
                    tpl = cls()
                    model = None
                    if name in TEST_MODELS:
                        model, _ = run_model(TEST_MODELS[name], out / f"m_{name}")
                        if name == "depth_track":
                            model = {"depth": model["axis_depth"], "value": model["value"]}
                        if name == "data_chart":
                            model = {"x": model["axis_x"], "y_P": model["y_P"]}
                    params = dict(tpl.example)
                    if name == "depth_track":
                        params.update({"window": [1000, 1100], "track": {"curve": "GR", "unit": "API", "range": [0, 150]},
                                       "layers": [{"top": 1000, "base": 1040, "lith": "clay", "label": "clay"},
                                                  {"top": 1040, "base": 1070, "lith": "sandstone", "label": "sand"},
                                                  {"top": 1070, "base": 1100, "lith": "clay"}]})
                    if name == "data_chart":
                        params = {"y": ["y_P"], "y_label": "p", "highlights": [{"x_from": 10, "x_to": 14, "label": "band"}]}
                    ctx = Ctx(w, h, 30, 6.0, theme, dom, "ru", i18n, cues={}, shot_dir=str(out),
                              orientation=orient, shot_id=f"{name}_{orient}")
                    miss = tpl.check_params(params, model)
                    L = tpl.plan(params, model, ctx)
                    R = Renderer(w, h, theme, str(out))
                    O = OverlayRenderer(w, h, theme)
                    for fr in frac:
                        f = int(ctx.n * fr) - 1
                        img = composite(R.render_frame(L["items"], f, f / 30), O.render(L["texts"], f, f / 30))
                        tiles.append((f"{name}@{fr}", Image.fromarray(img)))
                    bad = [c for c in L.get("checks", []) if c.get("type") == "assert" and not c.get("ok")]
                    results[f"{name}/{orient}"] = "ok" + (f" (checks failing: {[c['id'] for c in bad]})" if bad else "") \
                        + (f" missing: {miss}" if miss else "")
                except Exception as e:
                    results[f"{name}/{orient}"] = f"ERROR {e}"
                    traceback.print_exc()
            if tiles:
                tw, th_ = (240, 427) if orient == "portrait" else (480, 270)
                cols = 6 if orient == "portrait" else 4
                rows = (len(tiles) + cols - 1) // cols
                sheet = Image.new("RGB", (cols * tw, rows * th_), "white")
                for k, (lab, im) in enumerate(tiles):
                    sheet.paste(im.resize((tw, th_)), ((k % cols) * tw, (k // cols) * th_))
                sheet.save(out / f"sheet_{theme_id}_{orient}.png")
    for k, v in results.items():
        print(f"{k:40s} {v}")
    return results


# ============================================================================ end-to-end parts

FIXTURES = ROOT_DIR / "tests" / "fixtures"
UNSEEN = ["ru_slug_catcher", "ru_drilling_mud"]
DOMAIN = ROOT_DIR / "examples" / "domain_pack_demo"


def _qa(vd):
    return {c["id"]: c for c in (read_json(Path(vd) / "qa.json", []) or [])}


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _cli(args):
    from .cli import main
    main(args)


def _tts():
    from .tts import available_provider
    prov = available_provider("rhvoice")
    return prov if prov in ("rhvoice", "espeak", "silero") else "none"


def part_unit():
    import unittest
    suite = unittest.defaultTestLoader.discover(str(ROOT_DIR / "tests"), pattern="test_*.py", top_level_dir=str(ROOT_DIR))
    res = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w")).run(suite)
    ok = res.wasSuccessful()
    return ok, f"{res.testsRun} tests, {len(res.failures)} failures, {len(res.errors)} errors"


def part_unseen(out, tts):
    rows = []
    for name in UNSEEN:
        vid = f"unseen_{name}"
        vd = out / "videos" / vid
        if vd.exists():
            shutil.rmtree(vd)
        t0 = time.time()
        err = None
        try:
            _cli(["make", "--node", str(FIXTURES / name / "node.json"), "--pages", str(FIXTURES / name / "pages"),
                  "--domain", str(DOMAIN), "--format", "short", "--style", "F", "--planner", "rule",
                  "--tts", tts, "--out", str(out / "videos"), "--id", vid])
        except BaseException as e:                      # SystemExit included
            err = f"{type(e).__name__}: {e}"
        q = _qa(vd)
        mp4 = vd / "08_final" / f"{vid}.mp4"
        sl = read_json(vd / "02_shotlist.json", {}) or {}
        tl = read_json(vd / "timeline.json", {}) or {}
        fails = [k for k, c in q.items() if c["status"] == "fail"]
        need = ["claims_verified", "card_share", "mechanism_visuals", "ab_share"]
        ok = err is None and mp4.exists() and not fails and all(q.get(k, {}).get("status") == "pass" for k in need)
        rows.append({"node": name, "ok": ok, "error": err, "seconds": round(time.time() - t0),
                     "duration": tl.get("duration"),
                     "templates": [f"{s['template']}({s['class']})" for s in sl.get("shots", [])],
                     "qa": {k: q.get(k, {}).get("status") for k in need}, "qa_fails": fails,
                     "shares": q.get("ab_share", {}).get("details"),
                     "coverage_gaps": [g.get("status") for g in (read_json(vd / "coverage_report.json", {}) or {})
                                       .get("gaps", [])] if (vd / "coverage_report.json").exists() else []})
    return rows


def part_mutation(out, base_vd):
    """Copy a built video, inject a wrong spoken number and a fake quote, re-run overlays + QA."""
    from .cli import run_stages
    vd = out / "videos" / "mutation"
    if vd.exists():
        shutil.rmtree(vd)
    shutil.copytree(base_vd, vd)
    brief = read_json(vd / "00_brief.json")
    node = read_json(ROOT_DIR / brief["node"]) if not Path(brief["node"]).is_absolute() else read_json(brief["node"])
    script = read_json(vd / "01_script.json")
    # 1) fake quote: the first claim the script cites gets a sentence that is not in the chapter
    fake = "Пробкоуловитель полностью удаляет из газа все примеси за одну ступень очистки."
    target = None
    for ln in script["lines"]:
        for s_ in ln.get("sources", []):
            if s_.get("type", "claim") == "claim" and s_.get("claim_id"):
                target = s_["claim_id"]
                s_["quote"] = fake
                break
        if target:
            break
    for c in node["claims"]:
        if c["id"] == target:
            c["quote"] = fake
    # 2) wrong number: a factual line now states a number that no source contains
    ln = next(l for l in script["lines"] if l.get("asserts_fact") and l["role"] == "mechanism")
    ln["text"] = ln["text"].rstrip(".") + " — примерно в 13 раз быстрее."
    write_json(vd / "01_script.json", script)
    node_path = vd / "mutated_node.json"
    write_json(node_path, node)
    brief["node"] = str(node_path)
    write_json(vd / "00_brief.json", brief)
    run_stages(vd, only=["overlays", "qa"])
    q = _qa(vd)
    ov = read_json(vd / "07_overlays" / "overlays.json", {}) or {}
    res = {"claims_verified": q.get("claims_verified", {}).get("status"),
           "spoken_numbers": q.get("spoken_numbers", {}).get("status"),
           "draft_mark": ov.get("draft_mark"),
           "details": [q.get("claims_verified", {}).get("details"), q.get("spoken_numbers", {}).get("details")]}
    res["ok"] = res["claims_verified"] == "fail" and res["spoken_numbers"] == "fail" and bool(res["draft_mark"])
    return res


def part_mutation_quick():
    """Truth-gate-level mutation test (no video): same expectations as part_mutation."""
    from .inputs import load_node, Pages
    from .planner import rule_script
    from .truth import build_source_table, verify_sources, check_line_numbers
    name = UNSEEN[0]
    node = load_node(str(FIXTURES / name / "node.json"))
    pages = Pages(FIXTURES / name / "pages")
    script = rule_script(node, "short", "ru")
    st = verify_sources(build_source_table(script, [], node), pages)
    clean = all(r["status"] == "verified" for r in st if r["kind"] == "claim")
    ln = next(l for l in script["lines"] if l.get("asserts_fact") and l["role"] == "mechanism")
    ln["text"] += " Примерно в 13 раз быстрее."
    for l in script["lines"]:
        for s_ in l.get("sources", []):
            if s_.get("claim_id"):
                s_["quote"] = "Этой фразы нет в главе, она выдумана для проверки."
                break
    st = verify_sources(build_source_table(script, [], node), pages)
    fake_caught = any(r["status"] != "verified" for r in st if r["kind"] == "claim")
    num_caught = any(i["severity"] == "fail" for i in check_line_numbers(script, st, pages))
    return {"ok": clean and fake_caught and num_caught, "clean_verified": clean, "fake_quote_caught": fake_caught,
            "wrong_number_caught": num_caught}


def part_robustness(out, base_vd):
    from .cli import run_stages, MissingInputs
    vd = out / "videos" / "robustness"
    if vd.exists():
        shutil.rmtree(vd)
    shutil.copytree(base_vd, vd)
    shutil.rmtree(vd / "06_audio")
    shutil.rmtree(vd / "05_renders")
    msg = None
    try:
        run_stages(vd, start="layout")
    except MissingInputs as e:
        msg = str(e)
    fail_fast = bool(msg) and "06_audio/audio.json" in msg and "--from audio" in msg
    run_stages(vd, start="audio", end="layout")     # must recreate 06_audio/ and 05_renders/ itself
    recreated = (vd / "06_audio" / "audio.json").exists() and \
        all((vd / "05_renders" / f"{s['id']}.layout.json").exists() for s in read_json(vd / "02_shotlist.json")["shots"])
    return {"ok": fail_fast and recreated, "fail_fast": fail_fast, "folders_recreated": recreated,
            "message": (msg or "").splitlines()[:3]}


def part_determinism(base_vd):
    from .cli import run_stages
    vid = read_json(Path(base_vd) / "00_brief.json")["video_id"]
    mp4 = Path(base_vd) / "08_final" / f"{vid}.mp4"
    h0 = _sha(mp4)
    run_stages(base_vd, start="specs")
    h1 = _sha(mp4)
    run_stages(base_vd, start="specs")
    h2 = _sha(mp4)
    return {"ok": h1 == h2, "make": h0[:16], "rebuild_1": h1[:16], "rebuild_2": h2[:16], "make_equals_rebuild": h0 == h1}


def write_report(out, R):
    L = ["# vidpipe selftest", "", f"date: {time.strftime('%Y-%m-%d %H:%M')}", "",
         "| part | result | details |", "|---|---|---|"]
    t = R.get("templates", {})
    bad_t = {k: v for k, v in t.items() if not v.startswith("ok")}
    L.append(f"| templates | {'PASS' if not bad_t else 'FAIL'} | {len(t)} renders (template × orientation); "
             f"{'all ok' if not bad_t else bad_t} |")
    if "unit" in R:
        L.append(f"| unit tests | {'PASS' if R['unit'][0] else 'FAIL'} | {R['unit'][1]} |")
    for r in R.get("unseen", []):
        L.append(f"| unseen: {r['node']} | {'PASS' if r['ok'] else 'FAIL'} | {r['duration']} s video; "
                 f"{', '.join(r['templates'])}; QA {r['qa']}; shares {r['shares']}"
                 + (f"; QA fails {r['qa_fails']}" if r['qa_fails'] else "") + (f"; {r['error']}" if r['error'] else "")
                 + f"; built in {r['seconds']} s |")
    if "mutation" in R:
        m = R["mutation"]
        L.append(f"| mutation (wrong number + fake quote) | {'PASS' if m['ok'] else 'FAIL'} | "
                 + ("; ".join(f"{k}={v}" for k, v in m.items() if k not in ("ok", "details"))) + " |")
    if "robustness" in R:
        m = R["robustness"]
        L.append(f"| robustness (--from with missing outputs) | {'PASS' if m['ok'] else 'FAIL'} | "
                 f"fails fast: {m['fail_fast']}; folders recreated: {m['folders_recreated']} |")
    if "determinism" in R:
        m = R["determinism"]
        L.append(f"| determinism (rebuild twice) | {'PASS' if m['ok'] else 'FAIL'} | "
                 f"rebuild 1 {m['rebuild_1']} = rebuild 2 {m['rebuild_2']}; make {m['make']} "
                 f"({'same' if m['make_equals_rebuild'] else 'differs'}) |")
    (out / "selftest_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return "\n".join(L)


def run(out_dir="selftest_out", quick=False, tts=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    R = {"templates": run_templates(out_dir)}
    R["unit"] = part_unit()
    if quick:
        R["mutation"] = part_mutation_quick()
    else:
        tts = tts or _tts()
        R["unseen"] = part_unseen(out, tts)
        base = out / "videos" / f"unseen_{UNSEEN[0]}"
        det = out / "videos" / f"unseen_{UNSEEN[1]}"
        if (base / "qa.json").exists():
            R["mutation"] = part_mutation(out, base)
            R["robustness"] = part_robustness(out, base)
        if (det / "08_final").exists():
            R["determinism"] = part_determinism(det)
    write_json(out / "selftest.json", R)
    print(write_report(out, R))
    return R


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "selftest_out", quick="--quick" in sys.argv)
