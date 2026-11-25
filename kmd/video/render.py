"""Timeline -> audio track (loudness-normalized) + frames (parallel) -> mp4 with soft subtitles + .srt."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import soundfile as sf

FPS = 25            # output frame rate
RENDER_FPS = 12.5   # model states rendered per second (each image is shown for 2 output frames)
LEAD = 0.35          # silence before the first phrase (hook starts within the first 3 s)
GAP = 0.28           # between phrases
PRED_PAUSE = 1.3     # pause after the prediction question (TZ: 1–1.5 s)
MIN_CAPTION = 1.6    # caption on screen at least 1.5 s
END_HOLD = 1.8       # final state held on screen
TARGET_LUFS = -16.0
PEAK_LIMIT = 10 ** (-1.0 / 20)


# ----------------------------------------------------------------------------------------- timeline
def build_timeline(phrases: list[dict], tts: dict, prediction_qid: str | None) -> dict:
    t = LEAD
    rows = []
    for i, p in enumerate(phrases):
        d = tts[p["id"]]["duration"]
        start, end = t, t + d
        disp_end = max(end, start + MIN_CAPTION)
        pause = PRED_PAUSE if p["id"] == prediction_qid else 0.0
        rows.append({**p, "start": round(start, 3), "end": round(end, 3), "pause": pause})
        t = disp_end + pause + (GAP if i < len(phrases) - 1 else 0)
    total = t + END_HOLD
    for i, r in enumerate(rows):
        r["display_end"] = rows[i + 1]["start"] if i + 1 < len(rows) else total
    return {"phrases": rows, "total": round(total, 3)}


def frame_blocks(rows: list[dict]) -> list[dict]:
    """Consecutive phrases on the same scene frame form one block: the model state t runs t0 -> t1 over it."""
    blocks = []
    for i, r in enumerate(rows):
        bstart = 0.0 if i == 0 else r["start"]
        if blocks and blocks[-1]["frame_id"] == r["frame_id"]:
            blocks[-1]["end"] = r["display_end"]
            blocks[-1]["phrases"].append(r["id"])
            if r.get("pause"):
                blocks[-1]["pauses"].append((max(r["end"], r["start"] + MIN_CAPTION), r["pause"]))
        else:
            blocks.append({"frame_id": r["frame_id"], "start": bstart, "end": r["display_end"], "phrases": [r["id"]],
                           "pauses": [(max(r["end"], r["start"] + MIN_CAPTION), r["pause"])] if r.get("pause") else []})
    return blocks


def state_at(tau: float, timeline: dict, scene_frames: dict, blocks: list[dict]) -> dict:
    rows = timeline["phrases"]
    blk = next((b for b in blocks if b["start"] <= tau < b["end"]), blocks[-1])
    f = scene_frames[blk["frame_id"]]
    t0, t1 = f["t"]
    # active time excludes prediction pauses (the model freezes while the viewer thinks)
    span = blk["end"] - blk["start"] - sum(d for _, d in blk["pauses"])
    el = tau - blk["start"]
    overlay = None
    for ps, d in blk["pauses"]:
        if tau >= ps + d:
            el -= d
        elif tau >= ps:
            el -= tau - ps
            overlay = "predict"
    frac = min(1.0, max(0.0, el / span)) if span > 0 else 1.0
    t = t0 + (t1 - t0) * frac
    row = next((r for r in rows if r["start"] <= tau < r["display_end"]), None)
    if row is None:
        row = rows[0] if tau < rows[0]["start"] else rows[-1]
    return {"frame_id": blk["frame_id"], "t": round(t, 4), "caption": row["caption"], "overlay": overlay,
            "phrase_id": row["id"]}


# ----------------------------------------------------------------------------------------- audio
def mix_audio(timeline: dict, tts: dict, out_wav: Path, sr: int = 24000) -> dict:
    import pyloudnorm as pyln

    n = int(timeline["total"] * sr) + sr
    y = np.zeros(n, dtype=np.float64)
    for r in timeline["phrases"]:
        a, s = sf.read(tts[r["id"]]["wav"])
        if a.ndim > 1:
            a = a.mean(axis=1)
        if s != sr:
            raise ValueError("unexpected sample rate")
        i = int(r["start"] * sr)
        y[i: i + len(a)] += a[: max(0, n - i)]
    y = y[: int(timeline["total"] * sr)]
    meter = pyln.Meter(sr)
    loud0 = meter.integrated_loudness(y)
    y = pyln.normalize.loudness(y, loud0, TARGET_LUFS)
    peak = float(np.max(np.abs(y)))
    if peak > PEAK_LIMIT:  # soft limiter above the knee
        knee = 0.7 * PEAK_LIMIT
        over = np.abs(y) > knee
        y[over] = np.sign(y[over]) * (knee + (PEAK_LIMIT - knee) * np.tanh((np.abs(y[over]) - knee) / (PEAK_LIMIT - knee)))
    loud = meter.integrated_loudness(y)
    sf.write(out_wav, y.astype(np.float32), sr, subtype="PCM_16")
    return {"lufs": round(float(loud), 2), "peak_dbfs": round(20 * np.log10(max(np.max(np.abs(y)), 1e-9)), 2),
            "clipping": bool(np.max(np.abs(y)) >= 0.999)}


# ----------------------------------------------------------------------------------------- frames
_COMPOSER = None


def _init(scene, fmt, domain):
    global _COMPOSER
    from .compose import Composer

    _COMPOSER = Composer(scene, fmt, domain)


def _render_one(job):
    path, fid, t, caption, overlay = job
    if not Path(path).exists():
        _COMPOSER.render(path, fid, t, caption=caption, overlay=overlay)
    return path


def render_frames(scene: dict, fmt: str, timeline: dict, cache: Path, domain: str = "geology",
                  workers: int | None = None) -> list[tuple[str, float]]:
    """Return [(png, duration)] for the concat demuxer (identical consecutive frames merged)."""
    import hashlib

    cache.mkdir(parents=True, exist_ok=True)
    frames = {f["id"]: f for f in scene["frames"]}
    blocks = frame_blocks(timeline["phrases"])
    nfr = int(round(timeline["total"] * RENDER_FPS))
    seq, jobs = [], {}
    from .compose import LAYOUT

    # code version of the drawing (templates + composer) is part of the cache key
    code = "".join(sorted(p.read_text() for p in (Path(__file__).parent.parent / "visuals").rglob("*.py")))
    code += (Path(__file__).parent / "compose.py").read_text()
    from ..config import DOMAINS

    sgp = DOMAINS / domain / "styleguide.json"
    code += sgp.read_text() if sgp.exists() else ""
    skey = hashlib.sha1(json.dumps([scene["views"], scene["frames"], scene.get("title"), LAYOUT[fmt], code],
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]
    for k in range(nfr):
        st = state_at(k / RENDER_FPS, timeline, frames, blocks)
        key = hashlib.sha1(json.dumps([skey, fmt, st["frame_id"], st["t"], st["caption"], st["overlay"]],
                                      ensure_ascii=False).encode()).hexdigest()[:16]
        p = str(cache / f"{key}.png")
        jobs[p] = (p, st["frame_id"], st["t"], st["caption"], st["overlay"])
        seq.append(p)
    todo = [j for p, j in jobs.items() if not Path(p).exists()]
    workers = workers or max(1, min(4, os.cpu_count() or 1))
    if todo:
        ctx = mp.get_context("fork")
        with ctx.Pool(workers, initializer=_init, initargs=(scene, fmt, domain)) as pool:
            for i, _ in enumerate(pool.imap_unordered(_render_one, todo, chunksize=4)):
                if (i + 1) % 200 == 0:
                    print(f"[video] frames {i + 1}/{len(todo)}")
    out = []
    for p in seq:
        if out and out[-1][0] == p:
            out[-1] = (p, out[-1][1] + 1.0 / RENDER_FPS)
        else:
            out.append((p, 1.0 / RENDER_FPS))
    return out


# ----------------------------------------------------------------------------------------- output
def _ts(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def write_srt(timeline: dict, path: Path, width: int = 42) -> None:
    lines = []
    for i, r in enumerate(timeline["phrases"], 1):
        end = max(r["end"], r["start"] + MIN_CAPTION) + r.get("pause", 0)
        end = min(end, r["display_end"])
        txt = "\n".join(textwrap.wrap(r["text"], width))
        lines.append(f"{i}\n{_ts(r['start'])} --> {_ts(end)}\n{txt}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def encode(frames: list[tuple[str, float]], audio: Path, srt: Path, out: Path, size: tuple) -> dict:
    lst = out.with_suffix(".ffconcat")
    with open(lst, "w") as f:
        f.write("ffconcat version 1.0\n")
        for p, d in frames:
            f.write(f"file '{p}'\nduration {d:.4f}\n")
        f.write(f"file '{frames[-1][0]}'\n")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
           "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:s",
           "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos,fps={FPS},format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-tune", "stillimage",
           "-c:a", "aac", "-b:a", "128k", "-c:s", "mov_text", "-metadata:s:s:0", "language=rus",
           "-metadata:s:s:0", "title=Субтитры (полный текст)", "-movflags", "+faststart", "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    lst.unlink()
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(out)],
                        capture_output=True, text=True, check=True)
    fmt = json.loads(pr.stdout)["format"]
    return {"duration_s": round(float(fmt["duration"]), 2), "size_mb": round(int(fmt["size"]) / 1e6, 2)}
