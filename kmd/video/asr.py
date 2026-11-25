"""Local ASR check of the final voice track (faster-whisper on CPU): WER vs the script, terms intact,
voice/frame sync from word timestamps."""
from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

_MODEL = {}


def _model(name: str, *, local_files_only: bool = False):
    if name not in _MODEL:
        from faster_whisper import WhisperModel

        _MODEL[name] = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=local_files_only)
    return _MODEL[name]


def _num_words(m: re.Match) -> str:
    from num2words import num2words

    s = m.group(0).replace(",", ".")
    try:
        v = float(s)
        return num2words(int(v) if v.is_integer() else v, lang="ru")
    except Exception:  # noqa: BLE001
        return s


def normalize(text: str) -> list[str]:
    t = text.lower().replace("ё", "е").replace("\u0301", "")
    t = t.replace("%", " процентов ")
    t = re.sub(r"\d+(?:[.,]\d+)?", _num_words, t)
    t = re.sub(r"[^\w\s-]", " ", t)
    t = t.replace("-", " ")
    return [w for w in t.split() if w]


def wer(ref: list[str], hyp: list[str]) -> float:
    n, m = len(ref), len(hyp)
    if n == 0:
        return 0.0 if m == 0 else 1.0
    d = np.zeros((n + 1, m + 1), dtype=int)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    return float(d[n, m]) / n


def transcribe(wav: Path, model: str = "small", *, local_files_only: bool = False) -> list[dict]:
    tmp = Path(wav).with_suffix(".16k.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-ar", "16000", str(tmp)], check=True)
    a, _ = sf.read(tmp, dtype="float32")
    tmp.unlink()
    segs, _ = _model(model, local_files_only=local_files_only).transcribe(
        a, language="ru", word_timestamps=True, beam_size=5, vad_filter=False,
    )
    out = []
    for s in segs:
        for w in s.words or []:
            out.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
    return out


def check(wav: Path, phrases: list[dict], terms: list[str], model: str | None = None,
          *, local_files_only: bool = False) -> dict:
    """phrases: [{id, text, start, end}] with scheduled times. Returns metrics for the passport."""
    import os

    model = model or os.environ.get("KMD_ASR_MODEL", "medium")
    asr_words = transcribe(wav, model, local_files_only=local_files_only)
    hyp_tokens, hyp_times = [], []
    for w in asr_words:
        toks = normalize(w["word"])
        for tk in toks:
            hyp_tokens.append(tk)
            hyp_times.append(w["start"])
    ref_tokens, ref_owner = [], []
    for i, p in enumerate(phrases):
        toks = normalize(p["text"])
        ref_tokens += toks
        ref_owner += [i] * len(toks)
    w_strict = wer(ref_tokens, hyp_tokens)
    w_stem = wer([t[:5] for t in ref_tokens], [t[:5] for t in hyp_tokens])
    # alignment -> sync: scheduled phrase start vs heard start of its first matched word
    sm = difflib.SequenceMatcher(a=[t[:5] for t in ref_tokens], b=[t[:5] for t in hyp_tokens], autojunk=False)
    ref2hyp = {}
    for a0, b0, size in sm.get_matching_blocks():
        for k in range(size):
            ref2hyp[a0 + k] = b0 + k
    offsets = []
    per_phrase = []
    for i, p in enumerate(phrases):
        idx = [j for j, o in enumerate(ref_owner) if o == i]
        hit = next((ref2hyp[j] for j in idx if j in ref2hyp), None)
        if hit is None:
            per_phrase.append({"id": p["id"], "heard_start": None, "offset": None})
            continue
        # time of the first word minus the words before it inside the phrase is unknown -> use first matched word
        first_ref = next(j for j in idx if j in ref2hyp)
        heard = hyp_times[hit]
        pos = (first_ref - idx[0]) / max(len(idx), 1)
        expected = p["start"] + pos * (p["end"] - p["start"])
        off = heard - expected
        offsets.append(abs(off))
        per_phrase.append({"id": p["id"], "heard_start": round(heard, 2), "offset": round(off, 2)})
    heard_text = " ".join(w["word"] for w in asr_words)
    heard_norm = " ".join(normalize(heard_text))
    from rapidfuzz import fuzz

    term_res = []
    for t in terms:
        tn = " ".join(normalize(t))
        if not tn:
            continue
        ok = tn in heard_norm or fuzz.partial_ratio(tn, heard_norm) >= 88
        term_res.append({"term": t, "ok": bool(ok)})
    return {
        "asr_model": f"faster-whisper {model} (int8, CPU, local)",
        "wer": round(w_strict, 4),
        "wer_stem": round(w_stem, 4),
        "ref_words": len(ref_tokens),
        "heard_text": heard_text,
        "terms": term_res,
        "terms_ok": all(t["ok"] for t in term_res),
        "sync_max_s": round(max(offsets), 3) if offsets else None,
        "sync_mean_s": round(float(np.mean(offsets)), 3) if offsets else None,
        "sync_per_phrase": per_phrase,
    }
