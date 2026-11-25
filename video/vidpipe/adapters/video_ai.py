"""Swappable AI video adapter: generate_clip(first_frame, last_frame, prompt, seconds, aspect).

Only for class D (atmosphere) shots. Never called with text/numbers/diagrams in the prompt (checked).
Providers: none (default: deterministic cross-zoom fallback, $0) | fal (needs FAL_KEY) | wan_local (ComfyUI URL).
Every call is logged with provider, model, seconds, cost and wall time.
"""
import base64
import json
import os
import time
import urllib.request
from pathlib import Path

from ..templates.media import _prompt_ok
from ..util import RES_DIR, read_json, log, log_external_call


def provider_from_brief(brief):
    p = (brief.get("ai_video") or {}).get("provider", "none")
    if p == "fal" and not os.environ.get("FAL_KEY"):
        log("ai_video=fal but FAL_KEY is not set: using the deterministic fallback", "warn")
        return "none"
    return p


def _data_uri(path):
    b = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(b).decode()


def _req(url, body=None, key=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Authorization": f"Key {key}", "content-type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read().decode())


def estimate_cost(seconds, model_key=None):
    models = read_json(RES_DIR / "video_models.json")
    model_key = model_key or os.environ.get("VIDPIPE_VIDEO_MODEL", "fal:fal-ai/kling-video/o1/image-to-video")
    m = models.get(model_key, {})
    durs = m.get("durations") or [seconds]
    billed = min([d for d in durs if d >= seconds] or [max(durs)])
    return billed, (billed * m["price_per_s"]) if m.get("price_per_s") else None


def generate_clip(first_frame, last_frame, prompt, seconds, aspect, provider, out, video_dir=None):
    if not _prompt_ok(prompt):
        log("AI prompt contains digits/text/diagram words — refused", "err")
        return None
    if provider == "fal":
        key = os.environ["FAL_KEY"]
        model_key = os.environ.get("VIDPIPE_VIDEO_MODEL", "fal:fal-ai/kling-video/o1/image-to-video")
        m = read_json(RES_DIR / "video_models.json")[model_key]
        endpoint = model_key.split(":", 1)[1]
        billed, cost = estimate_cost(seconds, model_key)
        body = {"prompt": prompt, m["first"]: _data_uri(first_frame), m["last"]: _data_uri(last_frame),
                m["duration"]: str(billed), "aspect_ratio": "9:16" if aspect == "portrait" else "16:9",
                "negative_prompt": "text, letters, numbers, captions, labels, arrows, diagrams, logos, watermark"}
        t0 = time.time()
        sub = _req(f"https://queue.fal.run/{endpoint}", body, key)
        status_url, resp_url = sub["status_url"], sub["response_url"]
        while True:
            st = _req(status_url, None, key, "GET")
            if st.get("status") == "COMPLETED":
                break
            if st.get("status") in ("FAILED", "ERROR"):
                log(f"fal job failed: {st}", "err")
                return None
            time.sleep(4)
        res = _req(resp_url, None, key, "GET")
        url = res["video"]["url"]
        urllib.request.urlretrieve(url, out)
        info = {"provider": "fal", "model": endpoint, "seconds": billed, "cost_usd": cost, "seed": res.get("seed"),
                "wall_s": round(time.time() - t0, 1), "prompt": prompt, "first_frame": str(first_frame),
                "last_frame": str(last_frame), "path": str(out)}
        if video_dir:
            log_external_call(video_dir, kind="video", **{k: v for k, v in info.items() if k != "path"})
        return info
    if provider == "wan_local":
        log("wan_local adapter: set VIDPIPE_COMFYUI_URL and a Wan 2.2 FLF2V workflow (not configured)", "warn")
        return None
    return None
