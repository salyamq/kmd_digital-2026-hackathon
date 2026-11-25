"""make_video CLI.

  python -m vidpipe make --node node.json --pages chapter/ --domain domain_pack/ --format short --style F
  python -m vidpipe rebuild videos/<id>              # re-render from saved specs (no planner/LLM call)
  python -m vidpipe rebuild videos/<id> --only render
  python -m vidpipe check --node node.json --pages chapter/ --domain domain_pack/
  python -m vidpipe templates
  python -m vidpipe selftest
"""
import argparse
import json
import shlex
import sys
import tempfile
import time
from pathlib import Path

from . import config as C
from .util import ROOT_DIR, StageTimer, log, slug, read_json


def _stage_fn(name):
    from . import pipeline as pl
    from . import qa, passport
    return {
        "script": pl.stage_script, "audio": pl.stage_audio, "shotlist": pl.stage_shotlist, "specs": pl.stage_specs,
        "models": pl.stage_models, "layout": pl.stage_layout, "render": pl.stage_render,
        "overlays": pl.stage_overlays, "compose": pl.stage_compose,
        "qa": lambda P: (qa.write_reports(P, qa.run_qa(P)), qa.mentor_pack(P)),
        "passport": passport.build_passport,
    }[name]


class MissingInputs(SystemExit):
    pass


def _expand(pattern, vd):
    """Concrete paths for a STAGE_REQUIRES pattern, given what is on disk now."""
    if "{shot}" in pattern or "{model_shot}" in pattern:
        sl = read_json(vd / "02_shotlist.json", None)
        if not sl:
            return [pattern.replace("{shot}", "S*").replace("{model_shot}", "S*")]
        ids = [s["id"] for s in sl.get("shots", [])]
        if "{model_shot}" in pattern:
            ids = [i for i in ids if (read_json(vd / "03_scene_specs" / f"{i}.json", {}) or {}).get("model")]
        key = "{shot}" if "{shot}" in pattern else "{model_shot}"
        return [pattern.replace(key, i) for i in ids]
    if "{video_id}" in pattern:
        b = read_json(vd / "00_brief.json", {}) or {}
        return [pattern.replace("{video_id}", b.get("video_id", vd.name))]
    return [pattern]


def check_inputs(video_dir, todo):
    """Before running stages `todo`, every file they read that no stage in `todo` (run earlier) will write
    must already exist. Fails fast with the stage to re-run, instead of crashing midway (or after paid TTS)."""
    vd = Path(video_dir)
    missing = []
    for i, s in enumerate(todo):
        earlier = set(todo[:i])
        for pat in C.STAGE_REQUIRES.get(s, []):
            producer = C.STAGE_PRODUCES.get(pat)
            if producer in earlier:
                continue
            for f in _expand(pat, vd):
                if not (vd / f).exists():
                    missing.append((s, f, producer))
    if missing:
        first = min((C.STAGES.index(p) for _, _, p in missing if p), default=1)
        lines = [f"  stage '{s}' needs {f}  (written by stage '{p}')" for s, f, p in missing[:12]]
        msg = ("cannot run " + ", ".join(todo) + " — earlier outputs are missing:\n" + "\n".join(lines) +
               f"\n  fix: python -m vidpipe rebuild {vd} --from {C.STAGES[max(1, first)]}")
        raise MissingInputs(msg)


def run_stages(video_dir, start=None, end=None, only=None):
    from .pipeline import Project
    stages = [s for s in C.STAGES if s != "brief"]
    if only:
        todo = [s for s in stages if s in only]
    else:
        i0 = stages.index(start) if start else 0
        i1 = stages.index(end) + 1 if end else len(stages)
        todo = stages[i0:i1]
    check_inputs(video_dir, todo)
    t0 = time.time()
    for s in todo:
        for d in C.STAGE_DIRS.get(s, []):  # every stage creates the folders it writes into
            (Path(video_dir) / d).mkdir(parents=True, exist_ok=True)
        P = Project(video_dir)            # fresh: every stage reads from disk
        log(f"stage {s}", "stage")
        with StageTimer(video_dir, s):
            _stage_fn(s)(P)
    log(f"done in {time.time() - t0:.0f} s → {Path(video_dir) / '08_final'}", "ok")


def cmd_make(a):
    from .pipeline import stage_brief
    from .inputs import load_node
    node = load_node(a.node)
    vid = a.id or f"{slug(node['id'])}_{a.format}_{a.style}"
    vd = Path(a.out) / vid
    data_dirs = a.data or [str(ROOT_DIR / "data")]
    planner = {"mode": a.planner, "provider": a.llm_provider, "model": a.llm_model, "base_url": a.llm_base_url,
               "cache": str(Path(a.llm_cache).resolve()) if a.llm_cache else None}
    tts = {"provider": a.tts, "voice": a.voice, "rate": a.rate, "role": a.role, "speed": a.speed,
           "numbers": a.tts_numbers, "emphasis": a.tts_emphasis}
    if not (a.start and a.start != "script") and not a.only:
        from .pipeline import _rel
        planner["cache"] = _rel(planner["cache"])
        stage_brief(vd, a.node, a.pages, a.domain, a.format, a.style, data_dirs, planner, tts,
                    {"provider": a.ai_video}, lang=a.lang, cmdline="python -m vidpipe " + " ".join(map(shlex.quote, sys.argv[1:])))
    run_stages(vd, a.start, a.end, a.only)
    return vd


def apply_tts_overrides(vd, a):
    """rebuild --tts/--voice/... : store the new voice settings in the brief (so the passport records them)."""
    from .util import write_json
    keys = {"provider": a.tts, "voice": a.voice, "role": a.role, "speed": a.speed, "rate": a.rate,
            "numbers": a.tts_numbers, "emphasis": a.tts_emphasis}
    keys = {k: v for k, v in keys.items() if v is not None}
    if not keys:
        return
    b = read_json(vd / "00_brief.json")
    t = dict(b.get("tts") or {})
    if "provider" in keys and keys["provider"] != t.get("provider"):
        for k in ("voice", "role", "speed", "rate"):      # engine change: old engine's voice names don't apply
            if k not in keys:
                t.pop(k, None)
    t.update(keys)
    b["tts"] = t
    write_json(vd / "00_brief.json", b)
    log(f"tts settings: {t}", "ok")


def cmd_rebuild(a):
    vd = Path(a.video_dir)
    if not (vd / "00_brief.json").exists():
        sys.exit(f"not a video dir: {vd}")
    apply_tts_overrides(vd, a)
    run_stages(vd, a.start or ("specs" if not a.only else None), a.end, a.only)


def cmd_tts(a):
    """One-off synthesis (smoke test): python -m vidpipe tts --provider yandex --text "..." --out test.wav"""
    from .inputs import DomainPack, detect_lang
    from .tts import available_provider, prepare, synth, numbers_mode
    lang = a.lang or detect_lang(a.text)
    prov = available_provider(a.provider)
    if a.provider and prov != a.provider:
        sys.exit(f"provider '{a.provider}' not available (got '{prov}')")
    dom = DomainPack(a.domain)
    nm = numbers_mode(prov, a.numbers)
    text = prepare(a.text, lang, dom.expansions, dom.stress, numbers=nm, emphasis=a.emphasis and prov == "yandex")
    calls = []
    dur = synth(text, a.out, lang, prov, a.voice, a.rate, role=a.role, speed=a.speed, log=calls.append)
    print(f"provider : {prov}   voice: {a.voice or 'default'}   role: {a.role or '-'}   speed: {a.speed or '-'}")
    print(f"numbers  : {nm}")
    print(f"sent     : {text}")
    print(f"audio    : {dur:.2f} s -> {a.out}")
    if calls:
        chars = sum(c["chars"] for c in calls)
        cost = [c["cost"] for c in calls]
        cur = calls[0].get("currency") or ""
        est = "unknown (fill vidpipe/resources/tts_prices.json)" if any(c is None for c in cost) \
            else f"{sum(cost):.6f} {cur}"
        print(f"requests : {len(calls)}   chars billed: {chars}   est. cost: {est}")


def cmd_check(a):
    from .inputs import load_node, Pages, DomainPack, scan_datasets, match_curves
    from .planner import node_terms
    node = load_node(a.node)
    pages = Pages(a.pages, cache_dir=Path(tempfile.gettempdir()) / "vidpipe_ocr")
    dom = DomainPack(a.domain)
    cat = scan_datasets(a.data or [str(ROOT_DIR / "data")])
    terms = node_terms(node)
    rep = {"node": {"id": node["id"], "lang": node["lang"], "claims": len(node["claims"]),
                    "claims_with_quote": sum(1 for c in node["claims"] if c.get("quote")),
                    "claims_with_page": sum(1 for c in node["claims"] if c.get("page")),
                    "missing_fields": node["_missing"], "difficulty": node["difficulty"]},
           "pages": {"files": len(pages.files), "pages_with_text": sum(1 for v in pages.pages.values() if v.strip()),
                     "quotes_found": [pages.find_quote(c["quote"], c.get("page"))["status"]
                                      for c in node["claims"] if c.get("quote")]},
           "domain_pack": dom.summary(), "datasets": len(cat), "curve_terms": terms,
           "matching_curves": [f"{h['well']}:{h['curve']}" for h in match_curves(cat, terms)][:10]}
    print(json.dumps(rep, ensure_ascii=False, indent=2))


def cmd_templates(a):
    from .templates import catalog
    for t in catalog():
        print(f"{t['name']:20s} [{','.join(t['classes'])}] {t['purpose']}")
        for k, v in t["required"].items():
            print(f"    required {k}: {v}")


TTS_PROVIDERS = ["yandex", "rhvoice", "silero", "espeak", "none"]


def add_tts_args(p):
    p.add_argument("--tts", choices=TTS_PROVIDERS, help="TTS engine (yandex needs YANDEX_API_KEY; rhvoice = offline)")
    p.add_argument("--voice", help="voice name (yandex: alexander, dasha, ... see README; rhvoice: aleksandr-hq, ...)")
    p.add_argument("--role", help="yandex voice role, e.g. neutral | good | friendly | strict (if the voice has it)")
    p.add_argument("--speed", type=float, help="yandex speech speed, 1.0 = normal")
    p.add_argument("--rate", type=int, help="rhvoice speech rate in percent")
    p.add_argument("--tts-numbers", choices=["auto", "raw", "words"],
                   help="raw: send digits (engine normalizes); words: expand with num2words; auto: raw for yandex")
    p.add_argument("--tts-emphasis", action="store_true", default=None,
                   help="yandex: speak on-screen *accent* words with **emphasis** markup")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="make_video", description="Chapter node -> verified explainer video")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="build a video from a node")
    m.add_argument("--node", required=True)
    m.add_argument("--pages", help="chapter pages dir (markdown/txt and/or scans)")
    m.add_argument("--domain", help="domain pack dir")
    m.add_argument("--data", action="append", help="open data dir(s) (default: ./data)")
    m.add_argument("--format", choices=list(C.FORMATS), default="short")
    m.add_argument("--style", choices=["F", "N", "M"], default="F")
    m.add_argument("--out", default=str(ROOT_DIR / "videos"))
    m.add_argument("--id")
    m.add_argument("--lang")
    m.add_argument("--planner", choices=["auto", "rule", "llm", "replay"], default="auto")
    m.add_argument("--llm-provider", choices=["anthropic", "openai"])
    m.add_argument("--llm-model")
    m.add_argument("--llm-base-url")
    m.add_argument("--llm-cache", help="dir with script.json/shots.json for --planner replay")
    add_tts_args(m)
    m.add_argument("--ai-video", choices=["none", "fal", "wan_local"], default="none")
    for p in (m,):
        p.add_argument("--from", dest="start", choices=C.STAGES[1:])
        p.add_argument("--to", dest="end", choices=C.STAGES[1:])
        p.add_argument("--only", nargs="+", choices=C.STAGES[1:])
    r = sub.add_parser("rebuild", help="re-run stages of an existing video from its saved specs")
    r.add_argument("video_dir")
    r.add_argument("--from", dest="start", choices=C.STAGES[1:])
    r.add_argument("--to", dest="end", choices=C.STAGES[1:])
    r.add_argument("--only", nargs="+", choices=C.STAGES[1:])
    add_tts_args(r)
    tt = sub.add_parser("tts", help="synthesize one text (smoke test of a TTS provider)")
    tt.add_argument("--provider", choices=TTS_PROVIDERS, required=True)
    tt.add_argument("--text", required=True)
    tt.add_argument("--out", default="test.wav")
    tt.add_argument("--lang")
    tt.add_argument("--domain", help="domain pack dir (stress dictionary, expansions)")
    tt.add_argument("--voice")
    tt.add_argument("--role")
    tt.add_argument("--speed", type=float)
    tt.add_argument("--rate", type=int)
    tt.add_argument("--numbers", choices=["auto", "raw", "words"], default="auto")
    tt.add_argument("--emphasis", action="store_true")
    c = sub.add_parser("check", help="preflight: what the pipeline can see in the inputs")
    c.add_argument("--node", required=True)
    c.add_argument("--pages")
    c.add_argument("--domain")
    c.add_argument("--data", action="append")
    pv = sub.add_parser("preview", help="contact sheet from layouts (no video encoding)")
    pv.add_argument("video_dir")
    pv.add_argument("--per-shot", type=int, default=2)
    pv.add_argument("--out")
    sub.add_parser("templates", help="list scene templates")
    st = sub.add_parser("selftest", help="templates, unit tests, 2 unseen nodes, mutation, robustness, determinism")
    st.add_argument("out", nargs="?", default="selftest_out")
    st.add_argument("--quick", action="store_true", help="no video builds (templates, unit tests, truth-level mutation)")
    st.add_argument("--tts", choices=TTS_PROVIDERS, help="voice for the test videos (default: rhvoice if installed)")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        cmd_make(a)
    elif a.cmd == "rebuild":
        cmd_rebuild(a)
    elif a.cmd == "check":
        cmd_check(a)
    elif a.cmd == "templates":
        cmd_templates(a)
    elif a.cmd == "tts":
        cmd_tts(a)
    elif a.cmd == "preview":
        from .pipeline import Project, preview
        print(preview(Project(a.video_dir), a.per_shot, a.out))
    elif a.cmd == "selftest":
        from .selftest import run
        R = run(a.out, quick=a.quick, tts=a.tts)
        bad = [k for k, v in R.items() if (isinstance(v, dict) and v.get("ok") is False) or
               (isinstance(v, tuple) and not v[0]) or (isinstance(v, list) and any(not r.get("ok") for r in v))]
        if bad:
            sys.exit(f"selftest: FAILED parts {bad}")


if __name__ == "__main__":
    main()
