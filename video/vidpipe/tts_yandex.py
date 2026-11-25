"""Yandex SpeechKit API v3 (REST) adapter: POST https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis

* Region: YANDEX_TTS_ENDPOINT overrides the URL (Kazakhstan region: https://tts.api.ml.yandexcloud.kz).
* Auth: "Authorization: Api-Key <YANDEX_API_KEY>" (service-account API key; .env is loaded if present).
  Optional: YANDEX_IAM_TOKEN (Bearer) instead of the key, YANDEX_FOLDER_ID -> x-folder-id header.
  The key is read only when building the request and is never printed, logged or written to disk.
* Output: raw LINEAR16_PCM at 48 kHz mono (our pipeline rate), so chunks are simply concatenated.
* Response: a stream of JSON objects {"result": {"audioChunk": {"data": <base64>}, ...}}.
* Limits: API v3 accepts at most 250 characters (and 24 s of audio) per request, so text is split by sentence
  (then by clause, then by words) into requests of <= MAX_CHARS characters.
* Markup: '+' before a stressed vowel (same convention as our stress dictionary), sil<[ms]> pauses.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

import numpy as np

from .envfile import load_dotenv
from .util import RES_DIR, read_json

ENDPOINT = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
PATH = "/tts/v3/utteranceSynthesis"


def endpoint():
    """YANDEX_TTS_ENDPOINT overrides the service URL, e.g. the Kazakhstan region: https://tts.api.ml.yandexcloud.kz"""
    load_dotenv()
    e = os.environ.get("YANDEX_TTS_ENDPOINT", "").strip().rstrip("/")
    if not e:
        return ENDPOINT
    return e if e.endswith(PATH) else e + PATH
SR = 48000
MAX_CHARS = 250            # API v3 per-request limit (characters, incl. spaces and markup)
CHUNK_GAP_S = 0.06         # silence inserted between consecutive requests of one line


class YandexTTSError(RuntimeError):
    pass


def have_credentials():
    load_dotenv()
    return bool(os.environ.get("YANDEX_API_KEY") or os.environ.get("YANDEX_IAM_TOKEN"))


def _headers():
    load_dotenv()
    key = os.environ.get("YANDEX_API_KEY")
    tok = os.environ.get("YANDEX_IAM_TOKEN")
    if key:
        h = {"Authorization": f"Api-Key {key}"}
    elif tok:
        h = {"Authorization": f"Bearer {tok}"}
    else:
        raise YandexTTSError("YANDEX_API_KEY is not set (put it in .env or the environment)")
    h["Content-Type"] = "application/json"
    if os.environ.get("YANDEX_FOLDER_ID"):
        h["x-folder-id"] = os.environ["YANDEX_FOLDER_ID"]
    return h


def _redact(msg):
    for name in ("YANDEX_API_KEY", "YANDEX_IAM_TOKEN"):
        v = os.environ.get(name)
        if v:
            msg = msg.replace(v, "***")
    return msg


# ------------------------------------------------------------------ voices / roles

def voice_table():
    return read_json(RES_DIR / "yandex_voices.json")


def resolve_voice(voice, role, lang):
    """Default voice per language; drop a role the voice does not support (the API would reject it)."""
    vt = voice_table()
    voice = voice or vt["default"].get(lang, vt["default"]["ru"])
    info = vt["voices"].get(voice)
    warn = None
    if info is None:
        warn = f"voice '{voice}' is not in resources/yandex_voices.json; sending it unchanged"
    elif role and role not in info["roles"]:
        warn = f"voice '{voice}' has no role '{role}' (roles: {info['roles'] or 'none'}); role dropped"
        role = None
    return voice, role, warn


# ------------------------------------------------------------------ text splitting

def split_text(text, limit=MAX_CHARS):
    """Split into request-sized pieces: sentences packed together up to `limit`, long sentences split at
    clause punctuation, then at spaces. Never splits inside a word, so '+' stress marks stay attached."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    pieces = []
    for s in sentences:
        if len(s) <= limit:
            pieces.append(s)
            continue
        parts = re.split(r"(?<=[,;:—–])\s+", s)
        cur = ""
        for p in parts:
            if len(p) > limit:                       # still too long: split at spaces
                for w in p.split(" "):
                    if cur and len(cur) + 1 + len(w) > limit:
                        pieces.append(cur)
                        cur = w
                    else:
                        cur = f"{cur} {w}".strip()
                continue
            if cur and len(cur) + 1 + len(p) > limit:
                pieces.append(cur)
                cur = p
            else:
                cur = f"{cur} {p}".strip()
        if cur:
            pieces.append(cur)
    # pack short sentences together (fewer requests, more natural prosody)
    packed, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) <= limit:
            cur = f"{cur} {p}"
        else:
            if cur:
                packed.append(cur)
            cur = p
    if cur:
        packed.append(cur)
    return packed


# ------------------------------------------------------------------ request / response

def build_body(text, voice, role=None, speed=None, volume=None):
    hints = [{"voice": voice}]
    if role:
        hints.append({"role": role})
    if speed is not None:
        hints.append({"speed": str(float(speed))})
    if volume is not None:
        hints.append({"volume": str(float(volume))})
    return {"text": text, "hints": hints,
            "outputAudioSpec": {"rawAudio": {"audioEncoding": "LINEAR16_PCM", "sampleRateHertz": str(SR)}},
            "loudnessNormalizationType": "LUFS"}


def parse_stream(raw):
    """Decode the concatenated / newline-delimited JSON objects of the response into PCM bytes."""
    txt = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    dec = json.JSONDecoder()
    i, n = 0, len(txt)
    pcm = bytearray()
    words = []
    while i < n:
        while i < n and txt[i] in " \r\n\t,[]":
            i += 1
        if i >= n:
            break
        obj, j = dec.raw_decode(txt, i)
        i = j
        if "error" in obj:
            e = obj["error"]
            raise YandexTTSError(f"API error: {e.get('message', e)}")
        res = obj.get("result", obj)
        data = (res.get("audioChunk") or {}).get("data")
        if data:
            pcm += base64.b64decode(data)
        for w in res.get("wordTimings") or []:
            words.append(w)
    return bytes(pcm), words


def request_once(text, voice, role=None, speed=None, timeout=60, retries=3):
    body = json.dumps(build_body(text, voice, role, speed)).encode("utf-8")
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(endpoint(), data=body, headers=_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return parse_stream(r.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:400]
            except Exception:
                pass
            last = YandexTTSError(_redact(f"HTTP {e.code}: {detail or e.reason}"))
            if e.code not in (429, 500, 502, 503, 504):
                raise last
        except urllib.error.URLError as e:
            last = YandexTTSError(_redact(f"network error: {e.reason}"))
        time.sleep(1.5 * (attempt + 1))
    raise last


def price_per_char():
    p = (read_json(RES_DIR / "tts_prices.json") or {}).get("yandex", {})
    v = p.get("price_per_1m_chars")
    return (None, p.get("currency")) if v is None else (float(v) / 1e6, p.get("currency"))


def synthesize(text, voice=None, role=None, speed=None, lang="ru", log=None):
    """Returns (int16 numpy array at 48 kHz, meta). `log(dict)` is called once per HTTP request with
    chars / audio seconds / estimated cost (never the key)."""
    voice, role, warn = resolve_voice(voice, role, lang)
    pieces = split_text(text)
    if not pieces:
        raise YandexTTSError("empty text")
    ppc, cur = price_per_char()
    audio, word_timings, t = [], [], 0.0
    gap = np.zeros(int(CHUNK_GAP_S * SR), np.int16)
    for k, piece in enumerate(pieces):
        t0 = time.time()
        pcm, words = request_once(piece, voice, role, speed)
        a = np.frombuffer(pcm, dtype="<i2").copy()
        dur = len(a) / SR
        if log:
            log({"kind": "tts", "provider": "yandex", "voice": voice, "role": role, "speed": speed,
                 "chars": len(piece), "audio_s": round(dur, 3), "request": k + 1, "of": len(pieces),
                 "cost": None if ppc is None else round(len(piece) * ppc, 6), "currency": cur,
                 "wall_s": round(time.time() - t0, 2)})
        for w in words:
            w = dict(w)
            w["offset_s"] = t
            word_timings.append(w)
        audio.append(a)
        t += dur
        if k + 1 < len(pieces):
            audio.append(gap)
            t += CHUNK_GAP_S
    out = np.concatenate(audio) if audio else np.zeros(0, np.int16)
    return out, {"voice": voice, "role": role, "speed": speed, "requests": len(pieces),
                 "chars": sum(len(p) for p in pieces), "warning": warn, "word_timings": word_timings}
