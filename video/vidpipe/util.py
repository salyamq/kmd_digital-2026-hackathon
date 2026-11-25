"""Small shared helpers: JSON I/O, hashing, logging, stage timing."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent
RES_DIR = PKG_DIR / "resources"
FONT_DIR = ROOT_DIR / "assets" / "fonts"


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=_json_default)
    return path


def _json_default(o):
    # numpy scalars / arrays -> plain python
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serializable: {type(o)}")


def file_hash(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def text_hash(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def log(msg, level="info"):
    prefix = {"info": "·", "ok": "✓", "warn": "!", "err": "✗", "stage": "▶"}.get(level, "·")
    print(f"{prefix} {msg}", flush=True)


def slug(s, maxlen=40):
    s = re.sub(r"[^\w\-]+", "_", str(s).strip().lower(), flags=re.UNICODE)
    return s.strip("_")[:maxlen] or "video"


def deep_get(d, *keys, default=None):
    """deep_get(d, 'a', 'b') -> d['a']['b'] or default; also tries alternative keys given as tuples."""
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(k, (tuple, list)):
            found = None
            for kk in k:
                if isinstance(cur, dict) and kk in cur:
                    found = cur[kk]
                    break
            cur = found
        else:
            cur = cur.get(k) if isinstance(cur, dict) else None
    return default if cur is None else cur


class StageTimer:
    """Records wall time per stage into <video_dir>/metrics.json."""

    def __init__(self, video_dir, stage):
        self.path = Path(video_dir) / "metrics.json"
        self.stage = stage

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *exc):
        m = read_json(self.path, {}) or {}
        m.setdefault("machine_seconds", {})[self.stage] = round(time.time() - self.t0, 2)
        write_json(self.path, m)
        return False


def log_external_call(video_dir, **kw):
    """Append one external API call (provider, model, seconds, cost, wall time) to calls.jsonl."""
    path = Path(video_dir) / "calls.jsonl"
    kw.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(kw, ensure_ascii=False) + "\n")


def read_calls(video_dir):
    path = Path(video_dir) / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def env_flag(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")
