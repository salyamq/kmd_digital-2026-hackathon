"""Pipeline stages. Each stage reads only files written by earlier stages and writes its own files,
so any stage can be re-run alone:  python -m vidpipe rebuild videos/<id> --only render
"""
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config as C
from .evaluator import run_model, load_model_output
from .inputs import load_node, Pages, DomainPack, scan_datasets
from .templates import REGISTRY
from .templates.base import Ctx
from .util import (RES_DIR, ROOT_DIR, read_json, write_json, log, StageTimer, slug, file_hash, log_external_call)


def _rel(p):
    """Store paths relative to the repo root when possible, so a video dir can be rebuilt on another machine."""
    if not p:
        return None
    p = Path(p).resolve()
    try:
        return str(p.relative_to(ROOT_DIR))
    except ValueError:
        return str(p)


def _abs(p):
    if not p:
        return None
    q = Path(p)
    return str(q if q.is_absolute() else (ROOT_DIR / q))


class Project:
    def __init__(self, video_dir):
        self.dir = Path(video_dir)
        self.brief = read_json(self.dir / "00_brief.json") or {}
        for k in ("node", "pages", "domain"):
            if self.brief.get(k):
                self.brief[k] = _abs(self.brief[k])
        self.brief["data_dirs"] = [_abs(d) for d in self.brief.get("data_dirs", [])]
        self._node = self._pages = self._domain = self._catalog = None

    # paths
    def p(self, *parts):
        return self.dir.joinpath(*parts)

    @property
    def fmt(self):
        return C.FORMATS[self.brief["format"]]

    @property
    def node(self):
        if self._node is None:
            self._node = load_node(self.brief["node"])
        return self._node

    @property
    def pages(self):
        if self._pages is None:
            self._pages = Pages(self.brief.get("pages"), cache_dir=self.p("pages_cache"))
        return self._pages

    @property
    def domain(self):
        if self._domain is None:
            self._domain = DomainPack(self.brief.get("domain"))
        return self._domain

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = scan_datasets(self.data_dirs)
        return self._catalog

    @property
    def data_dirs(self):
        dirs = list(self.brief.get("data_dirs") or [])
        for k in ("domain", "pages"):
            if self.brief.get(k):
                dirs.append(self.brief[k])
        if self.brief.get("node"):
            dirs.append(str(Path(self.brief["node"]).parent))
        return dirs

    @property
    def lang(self):
        return self.brief.get("lang") or self.node["lang"]

    @property
    def theme(self):
        return read_json(RES_DIR / "themes" / f"{self.brief.get('style', 'F')}.json")

    @property
    def i18n(self):
        return read_json(RES_DIR / "i18n.json")

    def T(self):
        i = self.i18n
        return i.get(self.lang, i["en"])

    def specs(self):
        return [read_json(f) for f in sorted(self.p("03_scene_specs").glob("S*.json"),
                                             key=lambda f: int(f.stem[1:]) if f.stem[1:].isdigit() else 0)]


# ============================================================================ 00 brief

def stage_brief(video_dir, node, pages, domain, fmt, style, data_dirs, planner, tts, ai_video, lang=None,
                allow_unverified=False, cmdline=None):
    vd = Path(video_dir)
    vd.mkdir(parents=True, exist_ok=True)
    nd = load_node(node)
    brief = {"video_id": vd.name, "node_id": nd["id"], "node": _rel(node), "pages": _rel(pages),
             "domain": _rel(domain), "data_dirs": [_rel(d) for d in data_dirs],
             "format": fmt, "style": style, "lang": lang or nd["lang"],
             "target_s": C.FORMATS[fmt]["target_s"], "size": [C.FORMATS[fmt]["w"], C.FORMATS[fmt]["h"]],
             "planner": planner, "tts": tts, "ai_video": ai_video, "allow_unverified": allow_unverified,
             "created": time.strftime("%Y-%m-%d %H:%M:%S"), "cmdline": cmdline,
             "node_missing_fields": nd["_missing"]}
    write_json(vd / "00_brief.json", brief)
    return brief


# ============================================================================ 01 script

def stage_script(P):
    from .planner import rule_script, validate_script
    pl = P.brief.get("planner", {})
    mode = pl.get("mode", "auto")
    script, notes = None, []
    if mode in ("llm", "replay", "auto"):
        from .llm import LLM, detect_provider, llm_script
        prov = "replay" if mode == "replay" else (pl.get("provider") or detect_provider())
        if prov:
            try:
                llm = LLM(prov, pl.get("model"), pl.get("base_url"), _abs(pl.get("cache")), P.dir)
                script, errs = llm_script(llm, P.node, P.pages, P.brief["format"], P.lang, P.domain)
                if errs:
                    notes.append(f"LLM script had unresolved problems: {errs[:5]}")
                    if any("without a source" in e or "number" in e or "quote" in e for e in errs):
                        notes.append("falling back to the rule planner (facts must be sourced)")
                        script = None
            except Exception as e:
                if type(e).__name__ == "PendingLLM":
                    raise  # queued request: stop here, the caller reports it
                notes.append(f"LLM script failed: {e}")
                script = None
        elif mode == "llm":
            notes.append("no LLM provider configured (set ANTHROPIC_API_KEY or OPENAI_API_KEY/VIDPIPE_LLM_BASE_URL)")
    if script is None:
        script = rule_script(P.node, P.brief["format"], P.lang)
    script.update({"video_id": P.brief["video_id"], "node_id": P.node["id"], "lang": P.lang,
                   "format": P.brief["format"], "style": P.brief.get("style", "F")})
    for i, l in enumerate(script["lines"]):
        l.setdefault("id", f"L{i + 1}")
        l.setdefault("sources", [])
        l.setdefault("asserts_fact", bool(l["sources"]))
    errs, warns = validate_script(script, P.node, P.pages, P.brief["format"])
    script["validation"] = {"errors": errs, "warnings": warns, "notes": notes}
    write_json(P.p("01_script.json"), script)
    for n in notes:
        log(n, "warn")
    log(f"script: {len(script['lines'])} lines, planner={script.get('planner')}, "
        f"{len(errs)} errors, {len(warns)} warnings", "ok" if not errs else "warn")
    return script


# ============================================================================ 06 audio (runs right after script: voice drives the edit)

def stage_audio(P):
    from .tts import available_provider, prepare, synth, word_timings, numbers_mode
    from .util import log_external_call
    script = read_json(P.p("01_script.json"))
    t = P.brief.get("tts", {}) or {}
    prov = available_provider(t.get("provider"))
    nmode = numbers_mode(prov, t.get("numbers"))
    rate = t.get("rate") or ((124 if P.brief["format"] == "short" else 116) if prov == "rhvoice" else None)
    from .tts import DEFAULT_VOICES
    out = {"provider": prov, "voice": t.get("voice") or DEFAULT_VOICES.get(prov, {}).get(P.lang),
           "role": t.get("role"), "speed": t.get("speed"),
           "rate": rate, "numbers": nmode, "emphasis": bool(t.get("emphasis")), "lines": {}}
    adir = P.p("06_audio")
    adir.mkdir(parents=True, exist_ok=True)
    totals = {"chars": 0, "requests": 0}

    def log_call(rec):
        rec = dict(rec, stage="audio", line=cur_line[0])
        totals["chars"] += rec.get("chars", 0)
        totals["requests"] += 1
        log_external_call(P.dir, **rec)

    cur_line = [None]
    for l in script["lines"]:
        cur_line[0] = l["id"]
        say = prepare(l.get("say") or l["text"], P.lang, P.domain.expansions, P.domain.stress,
                      numbers=nmode, emphasis=bool(t.get("emphasis")) and prov == "yandex")
        wav = adir / f"{l['id']}.wav"
        t0 = time.time()
        dur = synth(say, wav, P.lang, prov, t.get("voice"), rate, role=t.get("role"), speed=t.get("speed"),
                    log=log_call)
        words, pauses = word_timings(l["text"], wav) if prov != "none" else ([], [])
        if not words:
            toks = l["text"].split()
            words = [{"w": w, "t0": dur * i / len(toks), "t1": dur * (i + 1) / len(toks)} for i, w in enumerate(toks)]
        out["lines"][l["id"]] = {"wav": wav.name, "dur": round(dur, 3), "tts_text": say, "words": words,
                                 "pauses": pauses, "synth_s": round(time.time() - t0, 2)}
    out["external"] = totals
    # glossary terms without stress entries (QA warning)
    if P.lang == "ru":
        import re
        terms = {str(g.get("term", g.get("ru", ""))).lower() for g in P.domain.glossary}
        text = " ".join(l["text"].lower() for l in script["lines"])
        def covered(t_):        # the phrase itself, or each of its content words, has a stress entry
            return t_ in P.domain.stress or all(w in P.domain.stress for w in re.findall(r"\w{4,}", t_))
        out["terms_without_stress"] = sorted(t_ for t_ in terms if t_ and t_ in text and not covered(t_))
    write_json(adir / "audio.json", out)
    tot = sum(v["dur"] for v in out["lines"].values())
    extra = f", {totals['requests']} API calls, {totals['chars']} chars" if totals["requests"] else ""
    log(f"audio: {prov} ({out['voice'] or 'default voice'}, numbers={nmode}), {len(out['lines'])} lines, "
        f"{tot:.1f} s of speech{extra}", "ok")
    return out


# ============================================================================ 02 shot list + 03 specs

def stage_shotlist(P):
    from .planner import rule_shots_specs
    script = read_json(P.p("01_script.json"))
    pl = P.brief.get("planner", {})
    mode = pl.get("mode", "auto")
    shotlist = specs = None
    coverage, notes = [], []
    if mode in ("llm", "replay", "auto") and str(script.get("planner", "")).startswith("llm"):
        from .llm import LLM, detect_provider, llm_shots
        prov = "replay" if mode == "replay" else (pl.get("provider") or detect_provider())
        try:
            llm = LLM(prov, pl.get("model"), pl.get("base_url"), _abs(pl.get("cache")), P.dir)
            shotlist, specs, errs = llm_shots(llm, script, P.node, P.pages, P.catalog, P.brief["format"],
                                              P.brief.get("style", "F"), P.lang, P.domain, P.data_dirs)
            if errs:
                notes.append(f"LLM shot list problems: {errs[:6]}")
        except Exception as e:
            if type(e).__name__ == "PendingLLM":
                raise
            notes.append(f"LLM shot list failed: {e}")
    if shotlist is None:
        shotlist, specs, coverage = rule_shots_specs(script, P.node, P.catalog, P.brief["format"],
                                                     P.brief.get("style", "F"), P.lang, P.domain.visuals)
        shotlist["planner"] = "rule"
    else:
        shotlist["planner"] = script.get("planner")
    shotlist["notes"] = notes
    write_json(P.p("02_shotlist.json"), shotlist)
    sd = P.p("03_scene_specs")
    if sd.exists():
        shutil.rmtree(sd)
    sd.mkdir(parents=True)
    for sp in specs:
        write_json(sd / f"{sp['shot_id']}.json", sp)
    write_json(P.p("coverage_seed.json"), coverage)
    # the rule planner may have added dataset sources to lines: keep script in sync
    write_json(P.p("01_script.json"), script)
    log(f"shot list: {len(shotlist['shots'])} shots ({shotlist['planner']})", "ok")
    return shotlist


def stage_specs(P):
    """Validate specs, replace broken shots by safe fallbacks, write the coverage report."""
    from .planner import validate_shots
    script = read_json(P.p("01_script.json"))
    shotlist = read_json(P.p("02_shotlist.json"))
    specs = P.specs()
    bad, gaps = validate_shots(shotlist, specs, script, None, P.data_dirs)
    lines = {l["id"]: l for l in script["lines"]}
    fixed = []
    for i, (sh, sp) in enumerate(zip(shotlist["shots"], specs)):
        if sh["id"] in bad:
            errs = bad[sh["id"]]
            lt = [lines[x] for x in sh["line_ids"] if x in lines]
            if len(lt) > 1:
                new = {"template": "process_steps", "params": {"steps": [{"title": l["text"][:60]} for l in lt],
                                                               "times": [l["id"] for l in lt]}}
            else:
                new = {"template": "text_panel", "params": {"text": lt[0]["text"] if lt else "", "icon": "arrow"}}
            gaps.append({"shot": sh["id"], "wanted_template": sp.get("template"), "status": "replaced_by_fallback",
                         "reason": "; ".join(errs)[:400]})
            sp.update(new)
            sp["model"] = None
            sp["class"] = sh["class"] = "T"
            sp["provenance"] = sh["provenance"] = "schematic"
            sh["template"] = sp["template"]
            fixed.append(sh["id"])
        sp.setdefault("provenance", sh.get("provenance") or C.CLASS_LABEL[sh["class"]])
        write_json(P.p("03_scene_specs", f"{sp['shot_id']}.json"), sp)
    write_json(P.p("02_shotlist.json"), shotlist)
    cov = (read_json(P.p("coverage_seed.json"), []) or []) + gaps
    write_coverage(P, shotlist, specs, cov)
    if bad.get("_lines"):
        log(f"specs: {bad['_lines']}", "warn")
    for e in bad.get("_plan", []):
        log(f"specs: {e}", "warn")
    log(f"specs: {len(specs)} validated, {len(fixed)} replaced by fallback {fixed}", "ok" if not fixed else "warn")


def write_coverage(P, shotlist, specs, gaps):
    from .templates import catalog
    used = {}
    for sp in specs:
        used[sp["template"]] = used.get(sp["template"], 0) + 1
    rep = {"node": P.node["id"], "node_missing_fields": P.node["_missing"],
           "templates_used": used, "library": [t["name"] for t in catalog()],
           "gaps": gaps,
           "inputs": {"pages": P.pages.available, "pages_files": len(P.pages.files),
                      "domain_pack": P.domain.summary(), "datasets": len(P.catalog),
                      "photos": len(P.domain.photos)}}
    write_json(P.p("coverage_report.json"), rep)
    md = [f"# Coverage report — {P.node['id']}", "",
          f"Templates used: {', '.join(f'{k}×{v}' for k, v in used.items())}", ""]
    if P.node["_missing"]:
        md.append(f"**Node fields missing:** {', '.join(P.node['_missing'])}")
    md.append("")
    if gaps:
        md += ["| shot | wanted | status | reason |", "|---|---|---|---|"]
        for g in gaps:
            md.append(f"| {g.get('shot')} | {g.get('wanted_template')} | **{g.get('status')}** | "
                      f"{str(g.get('reason', '')).replace('|', '/')} |")
    else:
        md.append("All requested visuals are covered by existing templates.")
    P.p("coverage_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")


# ============================================================================ 04 models

def stage_models(P):
    md = P.p("04_models")
    md.mkdir(parents=True, exist_ok=True)
    n = 0
    for sp in P.specs():
        m = sp.get("model")
        if not m:
            continue
        run_model(m, md / sp["shot_id"], P.data_dirs)
        n += 1
        # inset sub-templates may carry their own model: not supported yet (coverage)
    log(f"models: {n} state models evaluated", "ok")


def _model_for(P, sp):
    m = sp.get("model")
    if not m:
        return None
    out = load_model_output(P.p("04_models", sp["shot_id"]))
    if out is None:
        out, _ = run_model(m, P.p("04_models", sp["shot_id"]), P.data_dirs)
    return out


# ============================================================================ layout (timeline + template plans)

def build_timeline(P):
    script = read_json(P.p("01_script.json"))
    audio = read_json(P.p("06_audio", "audio.json"))
    shotlist = read_json(P.p("02_shotlist.json"))
    specs = {s["shot_id"]: s for s in P.specs()}
    fps = P.fmt["fps"]
    lines = {l["id"]: l for l in script["lines"]}
    t = 0.0
    shots, line_times, subs = [], {}, []
    max_chars = 30 if P.fmt["orientation"] == "portrait" else 50
    from .tts import chunk_words
    for sh in shotlist["shots"]:
        sp = specs[sh["id"]]
        start = t
        cur = start + C.SHOT_PAD_HEAD
        cues = {}
        for k, lid in enumerate(sh["line_ids"]):
            a = audio["lines"][lid]
            if k:
                cur += C.LINE_GAP
            line_times[lid] = [round(cur, 3), round(cur + a["dur"], 3)]
            cues[lid] = [round(cur - start, 3), round(cur - start + a["dur"], 3)]
            for ch in chunk_words(a["words"], max_chars):
                subs.append({"text": ch["text"], "t0": round(cur + ch["t0"], 3), "t1": round(cur + ch["t1"], 3),
                             "line": lid})
            cur += a["dur"]
        dur = cur - start + C.SHOT_PAD_TAIL
        if not sh["line_ids"]:
            dur = float(sp.get("params", {}).get("seconds", 3.0))
        dur = max(C.MIN_SHOT_S, dur)
        dur = math.ceil(dur * fps) / fps
        shots.append({"id": sh["id"], "start": round(start, 3), "end": round(start + dur, 3), "dur": round(dur, 3),
                      "cues": cues, "line_ids": sh["line_ids"], "f0": int(round(start * fps)),
                      "n_frames": int(round(dur * fps))})
        t = start + dur
    # merge subtitle chunks that would flash too briefly
    for s in subs:
        if s["t1"] - s["t0"] < 0.6:
            s["t1"] = s["t0"] + 0.6
    tl = {"fps": fps, "duration": round(t, 3), "n_frames": int(round(t * fps)), "shots": shots,
          "lines": line_times, "subtitles": subs}
    write_json(P.p("timeline.json"), tl)
    return tl


def stage_layout(P):
    tl = build_timeline(P)
    shotlist = read_json(P.p("02_shotlist.json"))
    rd = P.p("05_renders")
    rd.mkdir(parents=True, exist_ok=True)
    theme, i18n = P.theme, P.i18n
    for sh, ts in zip(shotlist["shots"], tl["shots"]):
        sp = read_json(P.p("03_scene_specs", f"{sh['id']}.json"))
        tpl = REGISTRY[sp["template"]]()
        model = _model_for(P, sp) if tpl.needs_model or sp.get("model") else None
        ctx = Ctx(P.fmt["w"], P.fmt["h"], P.fmt["fps"], ts["dur"], theme, P.domain, P.lang, i18n,
                  cues=ts["cues"], shot_dir=str(rd), orientation=P.fmt["orientation"], shot_id=sh["id"],
                  class_=sh["class"])
        ctx.model_kind = (sp.get("model") or {}).get("type")
        params = dict(sp.get("params") or {})
        if sp["template"] == "ai_clip":
            params["_first_path"], params["_last_path"] = _resolve_frame(P, params.get("first_frame")), \
                _resolve_frame(P, params.get("last_frame"))
        L = tpl.plan(params, model, ctx)
        assert ctx.n == ts["n_frames"], (ctx.n, ts["n_frames"])
        state = L.pop("state", {})
        if state:
            np.savez_compressed(P.p("04_models", f"{sh['id']}_state.npz"),
                                **{k: np.asarray(v) for k, v in state.items()})
        L.update({"w": ctx.w, "h": ctx.h, "fps": ctx.fps, "n_frames": ctx.n, "shot_id": sh["id"],
                  "template": sp["template"]})
        write_json(rd / f"{sh['id']}.layout.json", L)
    log(f"layout: {len(tl['shots'])} shots, {tl['duration']:.1f} s total", "ok")
    return tl


def _resolve_frame(P, ref):
    if not ref:
        return None
    if str(ref).startswith("shot:"):
        _, sid, which = str(ref).split(":")
        return str(P.p("05_renders", "frames", f"{sid}_{which}.png"))
    p = Path(ref)
    for base in [Path("."), *map(Path, P.data_dirs)]:
        if (base / p).exists():
            return str((base / p).resolve())
    return None


# ============================================================================ 05 render

def stage_render(P, only=None):
    from .render2d import render_layout
    from PIL import Image
    shotlist = read_json(P.p("02_shotlist.json"))
    rd = P.p("05_renders")
    (rd / "frames").mkdir(parents=True, exist_ok=True)
    # render data/process shots first so AI clips can use their frames as first/last frames
    order = sorted(shotlist["shots"], key=lambda s: s["template"] == "ai_clip")
    for sh in order:
        if only and sh["id"] not in only:
            continue
        L = read_json(rd / f"{sh['id']}.layout.json")
        for old in (rd / "qa").glob(f"{sh['id']}_f*.png"):      # stale QA frames from an earlier layout
            old.unlink()
        n = L["n_frames"]
        qa = sorted({max(0, min(n - 1, int(n * f))) for f in (0.3, 0.55, 0.8, 0.97)} | {0, n - 1})
        t0 = time.time()
        if sh["template"] == "ai_clip" and _ai_clip(P, sh, L):
            pass
        else:
            saved = render_layout(L, rd / f"{sh['id']}.mp4", P.theme, str(rd), qa_frames=qa, qa_dir=rd / "qa")
            for f, which in ((0, "first"), (n - 1, "last")):
                src = rd / "qa" / f"{sh['id']}_f{f:05d}.png"
                if src.exists():
                    shutil.copy(src, rd / "frames" / f"{sh['id']}_{which}.png")
        log(f"render {sh['id']} ({sh['template']}, {n} frames) {time.time() - t0:.1f}s", "ok")


def _ai_clip(P, sh, L):
    """Call the swappable video adapter. Returns True if a verified clip was produced."""
    from .adapters.video_ai import generate_clip, provider_from_brief
    sp = read_json(P.p("03_scene_specs", f"{sh['id']}.json"))
    prov = provider_from_brief(P.brief)
    if prov == "none":
        return False
    prm = sp["params"]
    first, last = _resolve_frame(P, prm.get("first_frame")), _resolve_frame(P, prm.get("last_frame"))
    if not (first and last and Path(first).exists() and Path(last).exists()):
        log(f"{sh['id']}: AI clip needs verified first/last frames — using deterministic fallback", "warn")
        return False
    res = generate_clip(first, last, prm["prompt"], prm.get("seconds", 4), P.fmt["orientation"], prov,
                        out=P.p("05_renders", f"{sh['id']}_ai_raw.mp4"), video_dir=P.dir)
    if not res:
        return False
    # conform to size/fps/duration
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", res["path"], "-vf",
                    f"scale={L['w']}:{L['h']}:force_original_aspect_ratio=increase,crop={L['w']}:{L['h']},fps={L['fps']}",
                    "-t", str(L["n_frames"] / L["fps"]), "-an", "-c:v", "libx264", "-crf", "16",
                    str(P.p("05_renders", f"{sh['id']}.mp4"))], check=True)
    write_json(P.p("05_renders", f"{sh['id']}.ai.json"), res)
    return True


# ============================================================================ 07 overlays

def stage_overlays(P):
    from .truth import build_source_table, verify_sources
    script = read_json(P.p("01_script.json"))
    shotlist = read_json(P.p("02_shotlist.json"))
    tl = read_json(P.p("timeline.json"))
    T = P.T()
    W, H = P.fmt["w"], P.fmt["h"]
    portrait = P.fmt["orientation"] == "portrait"
    lines = {l["id"]: l for l in script["lines"]}
    roles_order = []
    for sh_ in shotlist["shots"]:
        r_ = lines[sh_["line_ids"][0]]["role"] if sh_["line_ids"] else "outro"
        if r_ not in roles_order:
            roles_order.append(r_)
    items = []
    # truth status decides the draft mark
    st = verify_sources(build_source_table(script, P.specs(), P.node), P.pages)
    unverified = [r for r in st if r["kind"] in ("claim", "formula", "param", "table") and r.get("status") != "verified"]
    draft = bool(unverified) and not P.brief.get("allow_unverified_no_mark")
    margin = 40 if portrait else 110
    for sh, ts in zip(shotlist["shots"], tl["shots"]):
        L = read_json(P.p("05_renders", f"{sh['id']}.layout.json"))
        sp = read_json(P.p("03_scene_specs", f"{sh['id']}.json"))
        a, b = ts["start"], ts["end"]
        role = lines[sh["line_ids"][0]]["role"] if sh["line_ids"] else "outro"
        # header (kicker = section, badge = section number, title = video title)
        if sh["template"] not in ("title_card", "ai_clip", "photo"):
            items.append({"kind": "header", "shot": sh["id"], "t0": a, "t1": b, "fade_in": 0.2 if ts["start"] == 0 else 0,
                          "fade_out": 0, "x": margin, "y": 62 if portrait else 46,
                          "kicker": T["roles"].get(role, role.upper()),
                          "badge": f"{roles_order.index(role) + 1:02d}" if role in roles_order else None,
                          "title": script.get("title") or P.node["title"],
                          "title_size": 42 if portrait else 52, "kicker_size": 20 if portrait else 24,
                          "max_lines": 2 if portrait else 1,
                          "max_w": W - 2 * margin - (0 if portrait else 300)})
        # provenance: region chips from the template, else one chip per shot
        regions = L.get("regions") or []
        if regions:
            for rg in regions:
                items.append({"kind": "provenance", "shot": sh["id"], "t0": a + 0.2, "t1": b, "fade_out": 0,
                              "text": T["provenance"].get(rg["key"], rg["key"]), "x": rg["x"], "y": rg["y"],
                              "anchor": rg.get("anchor", "lb"), "size": 17 if portrait else 22})
        else:
            items.append({"kind": "provenance", "shot": sh["id"], "t0": a, "t1": b, "fade_in": 0, "fade_out": 0,
                          "text": T["provenance"].get(sp.get("provenance", "schematic"), sp.get("provenance")),
                          "x": W - margin, "y": 20 if portrait else 46, "anchor": "rt",
                          "size": 20 if portrait else 24})
        for tx in L.get("texts", []):
            it = dict(tx)
            it["shot"] = sh["id"]
            it["f0"] = ts["f0"]
            it["t0"] = a + tx.get("t0", 0.0)
            it["t1"] = a + tx["t1"] if tx.get("t1") is not None else b
            if it["t1"] >= b - 1e-6:
                it["fade_out"] = 0.0
            items.append(it)
    for s in tl["subtitles"]:
        items.append({"kind": "subtitle", "text": s["text"], "t0": s["t0"], "t1": s["t1"], "fade_in": 0.08,
                      "fade_out": 0.08, "x": W / 2, "y": H - (178 if portrait else 92),
                      "size": 33 if portrait else 44, "max_w": W * (0.86 if portrait else 0.72), "line": s["line"]})
    if draft:
        items.append({"kind": "label", "text": T["draft"], "t0": 0, "t1": tl["duration"], "fade_in": 0, "fade_out": 0,
                      "x": W / 2, "y": H - 22 if portrait else 16, "anchor": "cb" if portrait else "ct",
                      "size": 16 if portrait else 20, "font": "mono",
                      "color": "#FFFFFF", "bg": {"fill": "#C0392B", "opacity": 0.85, "radius": 8, "pad": [10, 4]}})
    write_json(P.p("07_overlays", "overlays.json"), {"w": W, "h": H, "fps": tl["fps"], "duration": tl["duration"],
                                                     "draft_mark": draft, "unverified_sources": len(unverified),
                                                     "items": items})
    log(f"overlays: {len(items)} text items ({len(tl['subtitles'])} subtitles){' — DRAFT mark' if draft else ''}",
        "ok")


# ============================================================================ 08 compose

class _Reader:
    def __init__(self, path, w, h):
        self.w, self.h = w, h
        self.proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "rawvideo",
                                      "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.idx = -1
        self.last = None

    def get(self, i):
        while self.idx < i:
            buf = self.proc.stdout.read(self.w * self.h * 3)
            if len(buf) < self.w * self.h * 3:
                break
            self.last = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
            self.idx += 1
        return self.last

    def close(self):
        self.proc.stdout.close()
        self.proc.kill()


def mix_narration(P, tl):
    import soundfile as sf
    from .tts import SR
    total = np.zeros(int((tl["duration"] + 0.5) * SR), np.float32)
    audio = read_json(P.p("06_audio", "audio.json"))
    for lid, (a, b) in tl["lines"].items():
        data, sr = sf.read(P.p("06_audio", audio["lines"][lid]["wav"]), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        i = int(a * SR)
        total[i:i + len(data)] += data[: max(0, len(total) - i)]
    out = P.p("06_audio", "narration.wav")
    lufs = None
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(SR)
        lufs = meter.integrated_loudness(total)
        if np.isfinite(lufs):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                total = pyln.normalize.loudness(total, lufs, C.LOUDNESS_LUFS)
        # soft limiter above -2 dBFS instead of hard clipping
        thr = 0.8
        a = np.abs(total)
        over = a > thr
        total[over] = np.sign(total[over]) * (thr + (1 - thr) * np.tanh((a[over] - thr) / (1 - thr)))
        lufs_after = meter.integrated_loudness(total)
    except Exception:
        lufs_after = None
    sf.write(out, total, SR)
    return out, lufs, lufs_after


def stage_compose(P):
    from .overlays import OverlayRenderer, composite
    tl = read_json(P.p("timeline.json"))
    ov = read_json(P.p("07_overlays", "overlays.json"))
    W, H, fps = P.fmt["w"], P.fmt["h"], tl["fps"]
    wav, lufs_in, lufs_out = mix_narration(P, tl)
    fd = P.p("08_final")
    fd.mkdir(parents=True, exist_ok=True)
    out = fd / f"{P.brief['video_id']}.mp4"
    tmp = fd / "_video_only.mp4"
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                            "-crf", "18", "-pix_fmt", "yuv420p", str(tmp)], stdin=subprocess.PIPE)
    O = OverlayRenderer(W, H, P.theme, P.lang)
    items = ov["items"]
    readers = {}
    shots = tl["shots"]
    X = C.XFADE_FRAMES
    t_start = time.time()
    for f in range(tl["n_frames"]):
        t = f / fps
        k = next((i for i, s in enumerate(shots) if s["f0"] <= f < s["f0"] + s["n_frames"]), len(shots) - 1)
        s = shots[k]
        rd = readers.get(s["id"]) or readers.setdefault(s["id"], _Reader(P.p("05_renders", f"{s['id']}.mp4"), W, H))
        frame = rd.get(f - s["f0"])
        # cross-fade into the next shot
        if k + 1 < len(shots) and f >= s["f0"] + s["n_frames"] - X // 2:
            nx = shots[k + 1]
            rn = readers.get(nx["id"]) or readers.setdefault(nx["id"], _Reader(P.p("05_renders", f"{nx['id']}.mp4"), W, H))
            nf = rn.get(0)
            u = (f - (s["f0"] + s["n_frames"] - X // 2)) / X
            frame = (frame.astype(np.float32) * (1 - u) + nf.astype(np.float32) * u).astype(np.uint8)
        elif k > 0 and f < s["f0"] + X // 2:
            pv = shots[k - 1]
            rp = readers.get(pv["id"])
            if rp is not None and rp.last is not None:
                u = 0.5 + (f - s["f0"]) / X
                frame = (rp.last.astype(np.float32) * (1 - u) + frame.astype(np.float32) * u).astype(np.uint8)
        vis = [it for it in items if it.get("t0", 0) - 0.01 <= t <= it.get("t1", 1e9) + 0.01]
        lf_items = []
        for it in vis:
            if "f0" in it:
                it = dict(it, _lf=f - it["f0"])
            lf_items.append(it)
        over = O.render(lf_items, f, t)
        enc.stdin.write(composite(frame, over).tobytes())
        # close readers of finished shots
        if k > 1 and shots[k - 2]["id"] in readers:
            readers.pop(shots[k - 2]["id"]).close()
    enc.stdin.close()
    enc.wait()
    for r in readers.values():
        r.close()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-i", str(wav), "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    tmp.unlink(missing_ok=True)
    m = read_json(P.p("metrics.json"), {}) or {}
    m["loudness"] = {"before_lufs": lufs_in, "after_lufs": lufs_out, "target": C.LOUDNESS_LUFS}
    write_json(P.p("metrics.json"), m)
    log(f"compose: {out.name} {tl['duration']:.1f}s, {time.time() - t_start:.0f}s wall, "
        f"loudness {lufs_out if lufs_out is None else round(lufs_out, 1)} LUFS", "ok")
    return out


# ============================================================================ preview (contact sheet, no encoding)

def preview(P, per_shot=2, out=None, width=None):
    """Contact sheet: per_shot frames per shot, graphics + full overlay layer, straight from layouts."""
    from PIL import Image
    from .overlays import OverlayRenderer, composite
    from .render2d import Renderer
    tl = read_json(P.p("timeline.json"))
    ov = read_json(P.p("07_overlays", "overlays.json"))
    W, H = P.fmt["w"], P.fmt["h"]
    R = Renderer(W, H, P.theme, str(P.p("05_renders")))
    O = OverlayRenderer(W, H, P.theme, P.lang)
    tiles = []
    for s in tl["shots"]:
        L = read_json(P.p("05_renders", f"{s['id']}.layout.json"))
        for k in range(per_shot):
            lf = int(s["n_frames"] * (0.35 + 0.6 * k / max(1, per_shot - 1))) - 1 if per_shot > 1 else s["n_frames"] // 2
            lf = max(0, min(s["n_frames"] - 1, lf))
            f = s["f0"] + lf
            t = f / tl["fps"]
            g = R.render_frame(L["items"], lf, lf / tl["fps"])
            vis = [dict(it, _lf=f - it["f0"]) if "f0" in it else it for it in ov["items"]
                   if it.get("t0", 0) <= t <= it.get("t1", 1e9)]
            tiles.append(Image.fromarray(composite(g, O.render(vis, f, t))))
    tw = width or (360 if W < H else 640)
    th = int(tw * H / W)
    cols = 6 if W < H else 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    out = out or P.p("preview.png")
    sheet.save(out)
    return out
