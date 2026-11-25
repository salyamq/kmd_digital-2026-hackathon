"""Unit tests for the Yandex SpeechKit v3 adapter with a mocked HTTP endpoint (no network, no real key).

Run:  python -m unittest discover -s tests -v
"""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vidpipe import tts, tts_yandex, envfile  # noqa: E402

FAKE_KEY = "unit-test-fake-key"
SR = 48000


def pcm_for(text, rate=SR):
    """Fake speech: one short tone burst per word, separated by silence (so timing code has pauses)."""
    words = max(1, len(text.split()))
    parts = []
    for i in range(words):
        t = np.arange(int(0.18 * rate)) / rate
        parts.append((0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2"))
        parts.append(np.zeros(int(0.05 * rate), "<i2"))
    return np.concatenate(parts).tobytes()


def stream_body(pcm, n_chunks=3, pretty=False):
    """SpeechKit v3 REST response: a stream of JSON objects with base64 audio chunks."""
    step = (len(pcm) // n_chunks) // 2 * 2 or len(pcm)
    objs = []
    for i in range(0, len(pcm), step):
        objs.append({"result": {"audioChunk": {"data": base64.b64encode(pcm[i:i + step]).decode()},
                                "startMs": "0", "lengthMs": "0"}})
    if pretty:
        return "\n".join(json.dumps(o, indent=2) for o in objs).encode()
    return "\n".join(json.dumps(o) for o in objs).encode()


class FakeResp:
    def __init__(self, data):
        self._data = data
        self.status = 200

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Recorder:
    """Mock for urllib.request.urlopen: records requests, answers with fake audio for the request text."""

    def __init__(self, fail_first=None):
        self.requests = []
        self.fail_first = list(fail_first or [])

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        self.requests.append({"url": req.full_url, "method": req.get_method(),
                              "headers": dict(req.header_items()), "body": body})
        if self.fail_first:
            code, payload = self.fail_first.pop(0)
            raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(payload.encode()))
        return FakeResp(stream_body(pcm_for(body["text"])))


class YandexTTSTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"YANDEX_API_KEY": FAKE_KEY}, clear=False)
        self.env.start()
        os.environ.pop("YANDEX_IAM_TOKEN", None)
        os.environ.pop("YANDEX_FOLDER_ID", None)
        # never read a developer's real .env during tests
        self.no_dotenv = mock.patch.object(envfile, "candidates", lambda: [self.tmp / "none.env"])
        self.no_dotenv.start()

    def tearDown(self):
        self.no_dotenv.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --------------------------------------------------------------------------------------------
    def test_request_format_wav_and_log(self):
        rec = Recorder()
        calls = []
        text = "Глины, как правило, радиоакт+ивнее чистых песч+аников."
        with mock.patch("urllib.request.urlopen", rec):
            dur = tts.synth(text, self.tmp / "a.wav", "ru", "yandex", "alexander", role="neutral", speed=1.1,
                            log=calls.append)
        self.assertEqual(len(rec.requests), 1)
        r = rec.requests[0]
        self.assertEqual(r["url"], "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis")
        self.assertEqual(r["method"], "POST")
        self.assertEqual(r["headers"].get("Authorization"), f"Api-Key {FAKE_KEY}")
        self.assertEqual(r["body"]["text"], text)                       # '+' stress marks sent unchanged
        self.assertIn({"voice": "alexander"}, r["body"]["hints"])
        self.assertIn({"role": "neutral"}, r["body"]["hints"])
        self.assertIn({"speed": "1.1"}, r["body"]["hints"])
        self.assertEqual(r["body"]["outputAudioSpec"],
                         {"rawAudio": {"audioEncoding": "LINEAR16_PCM", "sampleRateHertz": "48000"}})
        data, sr = sf.read(self.tmp / "a.wav")
        self.assertEqual(sr, 48000)
        self.assertEqual(data.ndim, 1)
        expected = len(pcm_for(text)) / 2 / SR
        self.assertAlmostEqual(dur, expected, places=3)
        self.assertAlmostEqual(len(data) / sr, expected, places=3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["chars"], len(text))
        self.assertAlmostEqual(calls[0]["audio_s"], expected, places=2)
        self.assertNotIn(FAKE_KEY, json.dumps(calls))

    def test_endpoint_override(self):
        rec = Recorder()
        with mock.patch.dict(os.environ, {"YANDEX_TTS_ENDPOINT": "https://tts.api.ml.yandexcloud.kz/"}), \
                mock.patch("urllib.request.urlopen", rec):
            tts.synth("Проверка.", self.tmp / "g.wav", "ru", "yandex")
        self.assertEqual(rec.requests[0]["url"], "https://tts.api.ml.yandexcloud.kz/tts/v3/utteranceSynthesis")

    def test_stress_dictionary_applied_before_request(self):
        rec = Recorder()
        stress = {"песчаники": "песч+аники", "глины": "гл+ины"}
        prepared = tts.prepare("Глины ярче, чем *песчаники*: до 150 API.", "ru", stress=stress,
                               numbers=tts.numbers_mode("yandex"))
        with mock.patch("urllib.request.urlopen", rec):
            tts.synth(prepared, self.tmp / "b.wav", "ru", "yandex")
        sent = rec.requests[0]["body"]["text"]
        self.assertIn("Гл+ины", sent)
        self.assertIn("песч+аники", sent)
        self.assertIn("150", sent)                 # auto numbers for yandex = raw digits
        self.assertNotIn("*", sent)                # on-screen markup removed
        self.assertNotIn("++", sent)

    def test_explicit_stress_wins_over_dictionary(self):
        out = tts.prepare("песч+аники и песчаники", "ru", stress={"песчаники": "песчан+ики"}, numbers="raw")
        self.assertEqual(out, "песч+аники и песчан+ики")

    def test_numbers_words_mode(self):
        out = tts.prepare("до 150 м", "ru", numbers="words")
        self.assertNotRegex(out, r"\d")

    def test_long_text_split_under_limit(self):
        sentence = "Давление в пласте снижается постепенно, и фронт возмущения уходит от скважины всё дальше. "
        long_sentence = " ".join(["слово"] * 70) + "."              # one sentence > 250 chars without commas
        text = sentence * 5 + long_sentence
        pieces = tts_yandex.split_text(text)
        self.assertTrue(all(len(p) <= tts_yandex.MAX_CHARS for p in pieces), [len(p) for p in pieces])
        self.assertEqual(" ".join(pieces).split(), text.split())       # nothing lost, no word cut
        rec = Recorder()
        calls = []
        with mock.patch("urllib.request.urlopen", rec):
            dur = tts.synth(text, self.tmp / "c.wav", "ru", "yandex", log=calls.append)
        self.assertEqual(len(rec.requests), len(pieces))
        self.assertGreater(len(pieces), 2)
        audio = sum(len(pcm_for(p)) / 2 / SR for p in pieces) + tts_yandex.CHUNK_GAP_S * (len(pieces) - 1)
        self.assertAlmostEqual(dur, audio, places=2)
        self.assertEqual(sum(c["chars"] for c in calls), sum(len(p) for p in pieces))

    def test_unsupported_role_is_dropped(self):
        rec = Recorder()
        with mock.patch("urllib.request.urlopen", rec):
            tts.synth("Проверка.", self.tmp / "d.wav", "ru", "yandex", "alexander", role="whisper")
        hints = rec.requests[0]["body"]["hints"]
        self.assertNotIn({"role": "whisper"}, hints)

    def test_http_error_is_redacted_and_not_retried(self):
        rec = Recorder(fail_first=[(401, json.dumps({"message": f"bad key {FAKE_KEY}"}))])
        with mock.patch("urllib.request.urlopen", rec), self.assertRaises(tts_yandex.YandexTTSError) as cm:
            tts.synth("Проверка.", self.tmp / "e.wav", "ru", "yandex")
        self.assertNotIn(FAKE_KEY, str(cm.exception))
        self.assertIn("401", str(cm.exception))
        self.assertEqual(len(rec.requests), 1)

    def test_retry_on_503(self):
        rec = Recorder(fail_first=[(503, "{}")])
        with mock.patch("urllib.request.urlopen", rec), mock.patch("time.sleep"):
            dur = tts.synth("Проверка связи.", self.tmp / "f.wav", "ru", "yandex")
        self.assertEqual(len(rec.requests), 2)
        self.assertGreater(dur, 0)

    def test_parse_stream_variants(self):
        pcm = pcm_for("один два")
        for pretty in (False, True):
            out, _ = tts_yandex.parse_stream(stream_body(pcm, 4, pretty=pretty))
            self.assertEqual(out, pcm)
        with self.assertRaises(tts_yandex.YandexTTSError):
            tts_yandex.parse_stream(b'{"error": {"message": "quota"}}')

    def test_dotenv(self):
        p = self.tmp / ".env"
        p.write_text('# comment\nexport YANDEX_API_KEY="from-dotenv"\nOTHER_VAR=1 # trailing\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True):
            names = envfile.load_dotenv([p])
            self.assertEqual(os.environ["YANDEX_API_KEY"], "from-dotenv")
            self.assertEqual(os.environ["OTHER_VAR"], "1")
            self.assertEqual(sorted(names), ["OTHER_VAR", "YANDEX_API_KEY"])
        with mock.patch.dict(os.environ, {"YANDEX_API_KEY": "already-set"}, clear=True):
            envfile.load_dotenv([p])
            self.assertEqual(os.environ["YANDEX_API_KEY"], "already-set")     # env wins over .env

    def test_fallback_to_rhvoice_without_key(self):
        if not shutil.which("RHVoice-test"):
            self.skipTest("RHVoice not installed")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(tts.available_provider("yandex"), "rhvoice")

    def test_audio_stage_end_to_end_with_mock(self):
        """Full 'audio' stage on a real demo video dir, Yandex mocked: calls.jsonl has chars/seconds/cost, no key."""
        src = ROOT / "videos" / "gr_latyshova_short"
        if not (src / "01_script.json").exists():
            self.skipTest("demo video dir not present")
        vd = self.tmp / "vid"
        vd.mkdir()
        for f in ("00_brief.json", "01_script.json", "02_shotlist.json"):
            shutil.copy(src / f, vd / f)
        shutil.copytree(src / "03_scene_specs", vd / "03_scene_specs")
        b = json.loads((vd / "00_brief.json").read_text(encoding="utf-8"))
        b["tts"] = {"provider": "yandex", "voice": "dasha", "role": "friendly", "speed": 1.05}
        (vd / "00_brief.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        from vidpipe.pipeline import Project, stage_audio
        rec = Recorder()
        with mock.patch("urllib.request.urlopen", rec):
            out = stage_audio(Project(vd))
        self.assertEqual(out["provider"], "yandex")
        self.assertEqual(out["numbers"], "raw")
        script = json.loads((vd / "01_script.json").read_text(encoding="utf-8"))
        self.assertEqual(len(out["lines"]), len(script["lines"]))
        self.assertTrue(all(len(r["body"]["text"]) <= 250 for r in rec.requests))
        self.assertTrue(all({"voice": "dasha"} in r["body"]["hints"] for r in rec.requests))
        calls = [json.loads(l) for l in (vd / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), len(rec.requests))
        self.assertTrue(all(c["kind"] == "tts" and c["chars"] > 0 and c["audio_s"] > 0 for c in calls))
        self.assertTrue(all("cost" in c and "currency" in c for c in calls))
        everything = (vd / "calls.jsonl").read_text() + (vd / "06_audio" / "audio.json").read_text()
        self.assertNotIn(FAKE_KEY, everything)
        # the stress dictionary of the demo domain pack reached the request
        joined = " ".join(r["body"]["text"] for r in rec.requests)
        self.assertIn("+", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
