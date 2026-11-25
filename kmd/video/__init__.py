"""`kmd video CH NODE --format short|long`: scene spec -> script for the ear -> TTS -> frames -> mp4 + passport.

Steps (each re-runnable; LLM answers and TTS are cached):
  1. scene spec (runs/<ch>/scenes/<node>.json; built here if missing) — must pass code checks,
  2. script for the ear (LLM `video_script`, code checks, `video_script_fix` repair),
  3. TTS per phrase (edge-tts, Microsoft online voice; espeak-ng fallback for the whole video),
  4. timeline (prediction pause, caption ≥ 1.5 s, final hold) -> loudness-normalized voice track,
  5. frames from the scene templates at model state t (one world), overlays -> H.264 + soft subtitles + .srt,
  6. local ASR check (WER, terms, sync) -> passport.json.
Outputs: runs/<ch>/video/<node>/{<fmt>.mp4, <fmt>.srt, script.<fmt>.json, passport.json}.
Caches (gitignored): runs/<ch>/tmp/video/<node>/.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import llm, scenes
from ..config import chapter_config, domain_pack, read_json, run_dir, write_json
from . import render, tts
from .script_checks import check_script, words

WPM_RANGE = (110, 150)


def _node(layer: dict, node_id: str) -> dict:
    for n in layer["nodes"]:
        if n["id"] == node_id:
            return n
    raise KeyError(f"node {node_id} not in layer")


def make_script(rd: Path, node: dict, scene: dict, fmt: str, entries: list[dict], lang: str = "русский",
                max_fix: int = 2) -> tuple[dict, list[str], list[str]]:
    v = {
        "node": scenes.slim_node(node),
        "scene": {k: scene[k] for k in ("title", "idea", "hook", "frames", "assumptions", "exaggerations", "data_bridge")
                  if k in scene},
        "format": fmt,
        "length_rule": ("шортс 40–75 секунд: 90–150 слов всего, 8–14 фраз." if fmt == "short" else
                        "разбор 1,5–3 минуты: 200–380 слов, 16–32 фразы."),
        "abbreviations": [e for e in entries if e.get("kind") in ("abbr", "symbol")],
        "course_language_name": lang,
    }
    task = f"video_script.{node['id']}.{fmt}"
    script = llm.complete_json(rd, task, "video_script", v, schema="video_script")
    errors, warns = check_script(script, scene, node, fmt, entries)
    k = 0
    while errors and k < max_fix:
        k += 1
        vf = {"node": scenes.slim_node(node), "frames": scene["frames"], "script": script, "errors": errors}
        script = llm.complete_json(rd, f"{task}.fix{k}", "video_script_fix", vf, schema="video_script")
        errors, warns = check_script(script, scene, node, fmt, entries)
    return script, errors, warns


_FAILED_ENGINES: set = set()


def synth_all(phrases: list[dict], entries: list[dict], cache: Path, voice: str, rate: str) -> tuple[dict, list[str]]:
    """All phrases with ONE engine/voice: the first engine that voices every phrase wins (TZ: one voice per series;
    on a voice failure the whole video switches)."""
    says, ear = {}, []
    for p in phrases:
        say, used = tts.apply_dict(p["text"], entries)
        says[p["id"]] = say
        ear += used
    last = None
    for eng in tts.engine_order():
        if eng in _FAILED_ENGINES:
            continue
        out = {}
        try:
            for p in phrases:
                out[p["id"]] = tts.synth(says[p["id"]], cache, engine=eng, voice=voice, rate=rate)
                out[p["id"]]["say"] = says[p["id"]]
            return out, sorted(set(ear))
        except Exception as e:  # noqa: BLE001
            last = e
            _FAILED_ENGINES.add(eng)
            print(f"[video] TTS engine {eng} failed ({e}); switching the whole video to the next engine")
    raise RuntimeError(f"all TTS engines failed: {last}")


def _wpm(timeline: dict) -> float:
    rows = timeline["phrases"]
    nw = sum(len(words(r["text"])) for r in rows)
    span = rows[-1]["end"] - rows[0]["start"] - sum(r.get("pause", 0) for r in rows)
    return nw / max(span, 1e-6) * 60


def _tool_versions() -> dict:
    import importlib.metadata as md

    def v(pkg):
        try:
            return md.version(pkg)
        except Exception:  # noqa: BLE001
            return None

    ff = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    return {"ffmpeg": ff, "edge-tts": v("edge-tts"), "faster-whisper": v("faster-whisper"),
            "matplotlib": v("matplotlib"), "numpy": v("numpy"),
            "external_services": {"edge-tts": "Microsoft online TTS: уходит только текст сценария"}}


def run(chapter: str, node: str | None = None, fmt: str = "short", **kw) -> list[Path]:
    if not node:
        raise ValueError("kmd video needs a node id")
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    layer = read_json(rd / "layer.json")
    nd = _node(layer, node)
    domain = cfg.get("domain") or layer.get("domain") or "geology"
    pack = domain_pack(domain)
    voice_cfg = (pack.get("pack") or {}).get("voice", {})
    voice = os.environ.get("KMD_TTS_VOICE") or voice_cfg.get("tts") or "ru-RU-DmitryNeural"
    entries = tts.load_dict(domain)
    # 1. scene
    scene = scenes.load_scene(chapter, node, fmt)
    if scene is None:
        route = scenes.load_routing(rd).get(node, {})
        try:
            scene = scenes.build_scene(rd, nd, route, fmt, pack)
        except llm.PendingLLM as p:
            return [p.path]
        write_json(scenes.scene_path(rd, node, fmt, route.get("format")), scene)
    if scene["checks"]["errors"] and not os.environ.get("KMD_VIDEO_FORCE"):
        print(f"[video] scene spec has errors, fix it first (or KMD_VIDEO_FORCE=1): {scene['checks']['errors']}")
        return []
    # 2. script
    try:
        script, s_err, s_warn = make_script(rd, nd, scene, fmt, entries)
    except llm.PendingLLM as p:
        return [p.path]
    if s_err and not os.environ.get("KMD_VIDEO_FORCE"):
        print(f"[video] script still breaks rules after repair: {s_err}")
        return []
    out_dir = rd / "video" / node
    cache = rd / "tmp" / "video" / node
    out_dir.mkdir(parents=True, exist_ok=True)
    phrases = script["phrases"]
    # 3–4. TTS + timeline (+ one tempo correction pass)
    rate = "+0%"
    for _ in range(3):
        audio, ear = synth_all(phrases, entries, cache / "tts", voice, rate)
        timeline = render.build_timeline(phrases, audio, script["prediction"]["question_phrase_id"])
        wpm = _wpm(timeline)
        if wpm > WPM_RANGE[1]:
            rate = f"{int(rate.strip('%')) - 8:+d}%"
        elif wpm < WPM_RANGE[0]:
            rate = f"{int(rate.strip('%')) + 8:+d}%"
        else:
            break
    wav = cache / f"{fmt}.voice.wav"
    loud = render.mix_audio(timeline, audio, wav)
    # 5. frames + encode
    from .compose import LAYOUT

    size = LAYOUT[fmt]["size"]
    frames = render.render_frames(scene, fmt, timeline, cache / f"frames_{fmt}", domain)
    srt = out_dir / f"{fmt}.srt"
    render.write_srt(timeline, srt)
    mp4 = out_dir / f"{fmt}.mp4"
    enc = render.encode(frames, wav, srt, mp4, size)
    # 6. ASR check
    terms = [t["term"] for t in script.get("terms_introduced", [])]
    try:
        from . import asr

        asr_res = asr.check(wav, timeline["phrases"], terms)
    except Exception as e:  # noqa: BLE001
        asr_res = {"error": str(e)}
    # passport
    write_json(out_dir / f"script.{fmt}.json", script)
    passport = build_passport(cfg, nd, scene, script, timeline, audio, loud, enc, asr_res, ear, wpm, voice, rate,
                              fmt, s_warn, size)
    pp = out_dir / "passport.json"
    specific = out_dir / f"passport.{fmt}.json"
    if specific.exists() or (pp.exists() and read_json(pp).get("format") != fmt):
        pp = specific
    write_json(pp, passport)
    print(f"[video] {node} {fmt}: {enc['duration_s']} s, {enc['size_mb']} MB, wpm {wpm:.0f}, LUFS {loud['lufs']}, "
          f"WER {asr_res.get('wer')}, sync max {asr_res.get('sync_max_s')} s -> {mp4}")
    return []


def build_passport(cfg, nd, scene, script, timeline, audio, loud, enc, asr_res, ear, wpm, voice, rate, fmt, s_warn,
                   size) -> dict:
    claims = {c["id"]: c for c in nd.get("claims", [])}
    used = []
    for r in timeline["phrases"]:
        for c in r.get("claim_ids", []):
            if c not in used:
                used.append(c)
    blocks = render.frame_blocks(timeline["phrases"])
    frames_out = []
    fmap = {f["id"]: f for f in scene["frames"]}
    for b in blocks:
        f = fmap[b["frame_id"]]
        tpl = scene["views"][f["view"]]["template"]
        frames_out.append({"id": f["id"], "start": round(b["start"], 2), "end": round(b["end"], 2), "class": f["class"],
                           "provenance": f["provenance"], "template": tpl, "view": f["view"], "t": f["t"],
                           "description": f["description"], "claim_ids": f.get("claim_ids", []),
                           "true_scale": bool(f.get("true_scale"))})
    q = next(r for r in timeline["phrases"] if r["id"] == script["prediction"]["question_phrase_id"])
    a = next(r for r in timeline["phrases"] if r["id"] == script["prediction"]["answer_phrase_id"])
    ear_list = sorted(set(ear) | {t["term"] for t in script.get("terms_introduced", [])})
    return {
        "node_id": nd["id"],
        "format": fmt,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "node_card": {"id": nd["id"], "title_book": nd.get("title_book"), "title_beginner": nd.get("title_beginner"),
                      "section": nd.get("section"), "difficulty": nd.get("difficulty"),
                      "book": f"{cfg['book'].get('author', '')}, «{cfg['book'].get('title', '')}»",
                      "pages": sorted({c.get("page") for c in nd.get("claims", []) if c.get("page")})},
        "video": {"file": f"{fmt}.mp4", "srt": f"{fmt}.srt", "script": f"script.{fmt}.json",
                  "resolution": f"{size[0]}x{size[1]}", "aspect": "9:16" if fmt == "short" else "16:9",
                  "fps": render.FPS, **enc,
                  "captions": "на кадре — ключевые слова (≤ 7–8 слов, вшиты); полный текст — отключаемые субтитры (дорожка mp4 и .srt)"},
        "script": [{"id": r["id"], "start": r["start"], "end": r["end"], "role": r["role"], "kind": r["kind"],
                    "text": r["text"], "caption": r["caption"], "frame_id": r["frame_id"], "claim_ids": r["claim_ids"],
                    "pause_after_s": r.get("pause", 0)} for r in timeline["phrases"]],
        "sources": [{"claim_id": c, "text": claims[c]["text"], "quote": claims[c].get("quote"), "page": claims[c].get("page"),
                     "kind": claims[c].get("kind")} for c in used if c in claims],
        "scene_spec": {k: scene.get(k) for k in ("title", "idea", "hook", "views", "objects", "invariants", "assumptions",
                                                 "exaggerations", "data_bridge", "checks")},
        "frames": frames_out,
        "exaggerations": scene.get("exaggerations", []),
        "true_scale_frame": any(f["true_scale"] for f in frames_out),
        "physics_checklist": scene.get("checklist", []),
        "reference_photos": [o for o in scene.get("objects", []) if o.get("reference")],
        "prediction": {"question": q["text"], "answer": a["text"], "pause_s": render.PRED_PAUSE,
                       "question_at_s": q["start"], "answer_at_s": a["start"]},
        "transfer_question": script.get("transfer_question"),
        "data_it_bridge": script.get("data_it_bridge") or scene.get("data_bridge"),
        "voice": {"engine": sorted({v["engine"] for v in audio.values()}),
                  "voice": sorted({v["voice"] for v in audio.values()}), "requested_voice": voice, "rate": rate,
                  "stress_dict": "domains/<domain>/stress_dict.json"},
        "metrics": {"wpm": round(wpm, 1), "lufs": loud["lufs"], "peak_dbfs": loud["peak_dbfs"], "clipping": loud["clipping"],
                    "wer": asr_res.get("wer"), "wer_stem": asr_res.get("wer_stem"), "terms_ok": asr_res.get("terms_ok"),
                    "sync_max_s": asr_res.get("sync_max_s"), "sync_mean_s": asr_res.get("sync_mean_s"),
                    "hook_ends_s": timeline["phrases"][0]["end"]},
        "asr": asr_res,
        "check_by_ear": ear_list,
        "script_warnings": s_warn,
        "manifest": _tool_versions(),
    }
