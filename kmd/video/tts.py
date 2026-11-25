"""Text-to-speech: Microsoft online voices via edge-tts (only the script text leaves the machine),
fallback to local espeak-ng. Pronunciation dictionary from the domain pack (stress_dict.json).

Each phrase is synthesized separately, so phrase timing is exact (duration of its audio); word-level
timing is measured later by the local ASR (edge-tts word boundaries are not always delivered).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ..config import DOMAINS

SR = 24000
ACUTE = "\u0301"


def load_dict(domain: str) -> list[dict]:
    p = DOMAINS / domain / "stress_dict.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("entries", [])


def _ci(s: str) -> str:
    """Regex for a stem, case-insensitive on the first letter, е/ё-insensitive."""
    out = []
    for ch in s:
        if ch in "её":
            out.append("[её]")
        elif ch in "ЕЁ":
            out.append("[ЕЁ]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def apply_dict(text: str, entries: list[dict]) -> tuple[str, list[str]]:
    """Return (text for the synthesizer, terms used that need checking by ear)."""
    used = []
    out = text
    # abbreviations / symbols: exact tokens, longest first
    toks = sorted([e for e in entries if e.get("kind") in ("abbr", "symbol")], key=lambda e: -len(e["term"]))
    for e in toks:
        pat = r"(?<![\w])" + re.escape(e["term"]) + r"(?![\w])"
        if re.search(pat, out):
            out = re.sub(pat, e["say"], out)
            if e.get("check_by_ear"):
                used.append(e["term"])
    stems = sorted([e for e in entries if e.get("kind") == "stem"], key=lambda e: -len(e["term"]))
    for e in stems:
        stem = e["term"]
        say = e["say"]
        pat = r"(?<![\w\u0301])(" + _ci(stem[0].lower()) + "|" + _ci(stem[0].upper()) + ")" + _ci(stem[1:])

        def rep(m, say=say):
            first = m.group(1)
            s = say
            return (s[0].upper() + s[1:]) if first.isupper() else s

        new = re.sub(pat, rep, out)
        if new != out:
            out = new
            if e.get("check_by_ear"):
                used.append(stem)
    return out, used


async def _edge(text: str, voice: str, rate: str) -> bytes:
    import edge_tts

    c = edge_tts.Communicate(text, voice, rate=rate)
    audio = b""
    async for ch in c.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
    if not audio:
        raise RuntimeError("edge-tts: no audio")
    return audio


def _to_wav(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(SR), str(dst)], check=True)


def synth(text: str, out_dir: Path, *, voice: str = "ru-RU-DmitryNeural", rate: str = "+0%",
          fallback: str = "espeak-ng", retries: int = 10) -> dict:
    """Synthesize one phrase -> {wav, duration, engine, voice}. Cached by (text, voice, rate)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    wav = out_dir / f"{key}.wav"
    meta = out_dir / f"{key}.json"
    if wav.exists() and meta.exists():
        return json.loads(meta.read_text())
    engine = "edge-tts"
    err = None
    for i in range(retries):
        try:
            mp3 = out_dir / f"{key}.mp3"
            mp3.write_bytes(asyncio.run(_edge(text, voice, rate)))
            _to_wav(mp3, wav)
            mp3.unlink()
            break
        except Exception as e:  # noqa: BLE001 - network / service errors
            err = e
            import time

            time.sleep(min(2.0 + 1.5 * i, 10.0))
    else:
        if not shutil.which("espeak-ng"):
            raise RuntimeError(f"TTS failed and no fallback: {err}")
        engine, voice = "espeak-ng", "ru"
        # the fallback is cached under its own key, so the next run tries the online voice again
        key = hashlib.sha1(f"espeak|{rate}|{text}".encode()).hexdigest()[:16]
        wav = out_dir / f"{key}.wav"
        meta = out_dir / f"{key}.json"
        tmp = out_dir / f"{key}.espeak.wav"
        subprocess.run(["espeak-ng", "-v", "ru", "-s", "150", "-w", str(tmp), text.replace(ACUTE, "")], check=True)
        _to_wav(tmp, wav)
        tmp.unlink()
    data, sr = sf.read(wav)
    # trim leading/trailing silence (keeps phrase timing tight for sync)
    thr = 10 ** (-45 / 20)
    idx = np.where(np.abs(data) > thr)[0]
    if len(idx):
        a = max(0, idx[0] - int(0.03 * sr))
        b = min(len(data), idx[-1] + int(0.08 * sr))
        data = data[a:b]
        sf.write(wav, data, sr)
    m = {"wav": str(wav), "duration": len(data) / sr, "engine": engine, "voice": voice, "rate": rate, "text": text}
    meta.write_text(json.dumps(m, ensure_ascii=False))
    return m
