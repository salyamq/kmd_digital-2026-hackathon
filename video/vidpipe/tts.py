"""TTS adapter (swappable) + text preparation (expansions, numbers to words, stress dictionary).

Providers: yandex (SpeechKit API v3, needs YANDEX_API_KEY) | rhvoice (offline, apt; the fallback) | silero (torch hub;
needs internet once) | espeak (robotic) | none (silent, for dry runs).
'+' before a vowel marks stress for SpeechKit, Silero and RHVoice alike; the stress dictionary is applied in prepare().
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .util import RES_DIR, read_json

DEFAULT_VOICES = {"yandex": {"ru": "alexander", "en": "john"},
                  "rhvoice": {"ru": "aleksandr-hq", "en": "slt"},
                  "silero": {"ru": "eugene", "en": "en_0"},
                  "espeak": {"ru": "ru", "en": "en-us"}}
SR = 48000


def available_provider(preferred=None):
    """Pick the TTS engine. A requested cloud engine without credentials falls back to RHVoice (offline)."""
    if preferred == "yandex":
        from .tts_yandex import have_credentials
        if have_credentials():
            return "yandex"
        print("! --tts yandex: YANDEX_API_KEY not found (env or .env) — falling back to RHVoice", flush=True)
        preferred = "rhvoice"
    order = [preferred] if preferred else []
    order += ["silero", "rhvoice", "espeak", "none"]
    for p in order:
        if p == "rhvoice" and shutil.which("RHVoice-test"):
            return p
        if p == "espeak" and shutil.which("espeak-ng"):
            return p
        if p == "silero":
            try:
                import torch  # noqa: F401
                if (Path.home() / ".cache/torch/hub/snakers4_silero-models_master").exists() or preferred == "silero":
                    return p
            except ImportError:
                pass
        if p == "none":
            return p
    return "none"


def numbers_mode(provider, requested=None):
    """'words' = expand digits with num2words; 'raw' = let the engine normalize (SpeechKit does this itself)."""
    if requested in ("raw", "words"):
        return requested
    return "raw" if provider == "yandex" else "words"


# ------------------------------------------------------------------ text preparation

def _num_words(m, lang):
    from num2words import num2words
    s = m.group().replace(" ", "").replace(" ", "")
    try:
        if re.search(r"[.,]", s):
            v = float(s.replace(",", "."))
            return num2words(v, lang=lang)
        return num2words(int(s), lang=lang)
    except Exception:
        return m.group()


def prepare(text, lang, expansions=None, stress=None, numbers="words", emphasis=False):
    """Text sent to the TTS engine: markup, abbreviations, numbers, stress marks.
    numbers='raw' keeps digits (and units) for engines that normalize them; emphasis=True turns our on-screen
    *word* markup into SpeechKit's **word** emphasis instead of dropping it."""
    t = re.sub(r"\*([^*]+)\*", r"**\1**" if emphasis else r"\1", text)
    t = re.sub(r"(?<!\*)\*(?!\*)", "", t)           # stray single asterisks (e.g. 'β*')
    t = t.replace("«", "").replace("»", "").replace("“", "").replace("”", "")
    # a free-standing '+' is arithmetic, not a stress mark
    t = re.sub(r"(?<=\s)\+(?=\s)", "плюс" if lang == "ru" else "plus", t)
    defaults = read_json(RES_DIR / "tts_expansions.json", {}).get(lang, {})
    if "abbr" in defaults or "units" in defaults:
        exp = dict(defaults.get("abbr", {}))
        if numbers == "words":
            exp.update(defaults.get("units", {}))
    else:                                     # older flat format
        exp = {k: v for k, v in defaults.items() if not k.startswith("_")}
    exp.update(expansions or {})
    for k in sorted(exp, key=len, reverse=True):
        t = re.sub(rf"(?<![\w-]){re.escape(k)}(?![\w-])", exp[k], t)
    if numbers == "words":
        t = re.sub(r"(\d)\s?[–—-]\s?(\d)", r"\1 — \2", t)      # ranges
        t = re.sub(r"\d+(?:[.,]\d+)?", lambda m: _num_words(m, lang), t)
    if stress:
        def rep(m):
            w = m.group()
            s_ = stress.get(w.lower())
            if not s_:
                return w
            return s_[0].upper() + s_[1:] if w[0].isupper() and not s_.startswith("+") else s_
        # words already carrying a '+' are split by this regex into parts that are not in the dictionary,
        # so explicit stress in the script always wins over the dictionary
        t = re.sub(r"[\w-]+", rep, t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ synthesis

def synth(text, out_wav, lang, provider, voice=None, rate=None, role=None, speed=None, log=None):
    """Synthesize `text` (already prepared) to a 48 kHz mono WAV. Returns duration in seconds.
    `log(dict)` receives one record per external call (cloud engines only)."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    voice = voice or DEFAULT_VOICES.get(provider, {}).get(lang)
    if provider == "yandex":
        from .tts_yandex import synthesize
        audio, meta = synthesize(text, voice, role, speed, lang, log=log)
        sf.write(out_wav, audio, SR, subtype="PCM_16")
        if meta.get("warning"):
            print(f"! {meta['warning']}", flush=True)
        return len(audio) / SR
    if provider == "rhvoice":
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
            tmp = f.name
        raw = str(out_wav) + ".raw.wav"
        cmd = ["RHVoice-test", "-p", voice, "-o", raw, "-i", tmp]
        if rate:
            cmd[1:1] = ["-r", str(rate)]
        subprocess.run(cmd, check=True, capture_output=True)
        _to_sr(raw, out_wav)
        Path(raw).unlink(missing_ok=True)
        Path(tmp).unlink(missing_ok=True)
    elif provider == "espeak":
        raw = str(out_wav) + ".raw.wav"
        subprocess.run(["espeak-ng", "-v", voice, "-s", str(int(150 * (rate or 100) / 100)), "-w", raw, text],
                       check=True, capture_output=True)
        _to_sr(raw, out_wav)
        Path(raw).unlink(missing_ok=True)
    elif provider == "silero":
        import torch
        model, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language=lang,
                                  speaker="v4_ru" if lang == "ru" else "v3_en")
        audio = model.apply_tts(text=text, speaker=voice, sample_rate=SR, put_accent=True, put_yo=True)
        sf.write(out_wav, audio.numpy(), SR)
    else:  # none: silent placeholder with an estimated duration (dry run)
        dur = max(0.8, len(text) / 14.0)
        sf.write(out_wav, np.zeros(int(dur * SR), np.float32), SR)
    data, sr = sf.read(out_wav)
    return len(data) / sr


def _to_sr(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "1", str(dst)],
                   check=True)


# ------------------------------------------------------------------ timing

VOWELS = set("аеёиоуыэюяaeiouy")


def word_timings(text, wav_path):
    """Estimate per-word times: proportional to syllables, then snapped to real pauses in the audio."""
    data, sr = sf.read(wav_path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    hop = int(0.01 * sr)
    n = len(data) // hop
    if n < 5:
        return [], []
    env = np.sqrt(np.convolve((data[:n * hop].reshape(n, hop).astype(float) ** 2).mean(axis=1), np.ones(3) / 3, "same"))
    thr = max(env.max() * 0.04, 1e-4)
    voiced = np.where(env > thr)[0]
    if not len(voiced):
        return [], []
    t_start, t_end = float(voiced[0] * 0.01), float((voiced[-1] + 1) * 0.01)
    silent = env <= thr
    pauses = []
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            if (j - i) >= 12 and i * 0.01 > t_start and j * 0.01 < t_end:
                pauses.append(((i + j) / 2) * 0.01)
            i = j
        else:
            i += 1
    toks = re.findall(r"\S+", text)                      # keep *markup* for subtitle highlighting
    weights = [max(1, sum(1 for c in w.lower() if c in VOWELS)) + (0.6 if re.search(r"[,.;:!?—]$", w) else 0)
               for w in toks]
    tot = sum(weights)
    words, t = [], t_start
    for w, wt in zip(toks, weights):
        d = (t_end - t_start) * wt / tot
        words.append({"w": w, "t0": round(t, 3), "t1": round(t + d, 3)})
        t += d
    # snap word boundaries after punctuation to the nearest detected pause
    for k, wd in enumerate(words[:-1]):
        if re.search(r"[,.;:!?—]$", wd["w"]) and pauses:
            pz = float(min(pauses, key=lambda p: abs(p - wd["t1"])))
            if abs(pz - wd["t1"]) < 0.6:
                wd["t1"] = round(pz, 3)
                words[k + 1]["t0"] = round(pz, 3)
    return words, pauses


def chunk_words(words, max_chars):
    """Group words into subtitle chunks (<= max_chars), preferring breaks after punctuation.
    A standalone dash is glued to the previous word so it never starts or ends a line alone."""
    merged = []
    for w in words:
        if merged and w["w"] in ("—", "–", "-"):
            merged[-1] = {"w": merged[-1]["w"] + " " + w["w"], "t0": merged[-1]["t0"], "t1": w["t1"]}
        else:
            merged.append(dict(w))
    words = merged
    chunks, cur = [], []
    for w in words:
        cand = " ".join(x["w"] for x in cur + [w])
        if cur and len(cand) > max_chars:
            # backtrack to the last punctuation if it gives a reasonable chunk
            cut = None
            for i in range(len(cur) - 1, 0, -1):
                if re.search(r"[,;:—]$", cur[i]["w"]) and len(" ".join(x["w"] for x in cur[:i + 1])) > max_chars * 0.45:
                    cut = i + 1
                    break
            if cut:
                chunks.append(cur[:cut])
                cur = cur[cut:]
            else:
                chunks.append(cur)
                cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["w"]) and len(" ".join(x["w"] for x in cur)) > max_chars * 0.35:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        if not c:
            continue
        txt = " ".join(x["w"] for x in c)
        if txt.count("*") % 2:
            txt = txt.replace("*", "")
        out.append({"text": txt, "t0": float(c[0]["t0"]), "t1": float(c[-1]["t1"])})
    return out
