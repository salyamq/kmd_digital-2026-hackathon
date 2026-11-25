"""`kmd site CH`: steps/*.json + tasks.json + cards.json (+ layer, routing, scenes, video) -> runs/<ch>/site/.

The site opens from disk (file://), no server, no CDN: every page is static HTML rendered here; the
small amount of state (progress, task results, card marks, theme) lives in localStorage. KaTeX is
vendored. Data for the interactive parts is embedded as JSON inside the pages (no fetch).
"""
from __future__ import annotations

import hashlib
import html
import json
import random
import re
import shutil
from pathlib import Path

import jinja2

from ..config import chapter_config, read_json, run_dir, write_json
from ..course.stage import redraw_ills

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
VENDOR = HERE / "vendor"
TEMPLATES = HERE / "templates"

FORMAT = {
    "short": ("Видео", "▶"),
    "long": ("Видео-разбор", "▶"),
    "interactive": ("Интерактив", "⟳"),
    "data_practice": ("Решение на данных", "◆"),
    "cards": ("Карточки", "▤"),
    "text": ("Текст", "¶"),
}
KIND_RU = {"observation": "наблюдение", "inference": "вывод", "assumption": "допущение"}
DIFF_RU = {
    "М": "масштаб", "В": "время", "И": "интерпретация", "Ф": "формализм",
    "П": "пространство", "Пр": "процесс/прибор", "Н": "неочевидное", "Р": "распознавание",
}
LINK_RU = {"prerequisite": "предпосылка", "example": "пример", "refutes_misconception": "опровергает заблуждение", "to_data": "переход к данным"}


# ---------------------------------------------------------------- text helpers

def pages_label(pages) -> str:
    ps = sorted({int(p) for p in (pages or []) if p is not None})
    if not ps:
        return ""
    runs, start, prev = [], ps[0], ps[0]
    for p in ps[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append((start, prev))
        start = prev = p
    runs.append((start, prev))
    return "стр. " + ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in runs)


def md(text, terms: list[str] | None = None) -> str:
    """Tiny inline markup: **term** -> <dfn>/<strong>; HTML escaped; $..$ kept for KaTeX."""
    s = html.escape(str(text or ""), quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", lambda m: f'<strong class="term">{m.group(1)}</strong>', s)
    return s


def jdump(o) -> str:
    """JSON safe to embed inside <script>."""
    return json.dumps(o, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def srt_to_vtt(srt: str) -> str:
    body = re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", srt.replace("\r", ""))
    return "WEBVTT\n\n" + body.strip() + "\n"


def _rng(key: str) -> random.Random:
    return random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:12], 16))


# ---------------------------------------------------------------- tasks view

def task_view(t: dict, step: dict, step_url: str) -> dict:
    """Presentation of a task: shuffled options (deterministic), answer key for JS."""
    v = {
        "id": t["id"], "type": t["type"], "question": t["question"], "explanation": t.get("explanation", ""),
        "page": t.get("page"), "link": f"{step_url}#{t['anchor'] or 'how'}" if step_url is not None else None,
        "step_title": step["title_beginner"], "step_index": step["index"], "node_id": step["node_id"],
    }
    rng = _rng(t["id"])
    if t["type"] in ("single", "multiple"):
        idx = list(range(len(t["options"])))
        rng.shuffle(idx)
        v["options"] = [t["options"][i] for i in idx]
        v["key"] = sorted(idx.index(c) for c in t["correct"])
        v["answer_text"] = "; ".join(t["options"][c] for c in t["correct"])
    elif t["type"] == "order":
        items = list(t["items"])
        idx = list(range(len(items)))
        for _ in range(10):
            rng.shuffle(idx)
            if idx != sorted(idx):
                break
        v["items"] = [{"text": items[i], "pos": i} for i in idx]
        v["key"] = list(range(len(items)))
        v["answer_text"] = " → ".join(items)
    elif t["type"] == "cloze":
        parts = (t.get("text") or "").split("___")
        blanks = []
        for b in t.get("blanks", []):
            opts = list(b.get("options") or [])
            if opts:
                rng.shuffle(opts)
            blanks.append({"options": opts, "answers": b["answers"]})
        v["parts"] = parts
        v["blanks"] = blanks
        v["key"] = [b["answers"] for b in t.get("blanks", [])]
        filled = parts[0]
        for i, b in enumerate(t.get("blanks", [])):
            filled += f"[{b['answers'][0]}]" + (parts[i + 1] if i + 1 < len(parts) else "")
        v["answer_text"] = filled
    elif t["type"] == "numeric":
        v["key"] = {"answer": t["answer"], "tolerance": t.get("tolerance") or 0}
        v["unit"] = t.get("unit") or ""
        v["answer_text"] = f"{t['answer']:g}".replace(".", ",") + (f" {t['unit']}" if t.get("unit") else "")
    return v


# ---------------------------------------------------------------- link map (arc diagram)

def link_map_svg(steps: list[dict], url_of: dict) -> str:
    """Steps top-down in path order; arcs on the left from a step to the steps it relies on."""
    idx = {s["node_id"]: i for i, s in enumerate(steps)}
    row, top, W = 64, 20, 640
    left = 120  # arcs live in [0, left)
    H = top * 2 + row * len(steps)
    edges = []
    for s in steps:
        for l in s.get("links", []):
            if l.get("to") in idx and l["to"] != s["node_id"]:
                edges.append((idx[l["to"]], idx[s["node_id"]], l.get("type", "prerequisite")))
    out = [f'<svg class="linkmap" viewBox="0 0 {W} {H}" role="img" aria-labelledby="lm-title" xmlns="http://www.w3.org/2000/svg">',
           '<title id="lm-title">Карта связей шагов: дуги слева ведут от шага к шагам, на которые он опирается</title>',
           '<defs><marker id="lm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0,0 L10,5 L0,10 z" class="lm-arrowhead"/></marker></defs>']
    cy = lambda i: top + row * i + row / 2 - 6
    for a, b, typ in sorted(edges, key=lambda e: -(e[1] - e[0])):
        span = b - a
        x = left - 12 - min(span, 6) * 15
        out.append(f'<path class="lm-edge lm-{typ}" d="M{left},{cy(a):.0f} C{x},{cy(a):.0f} {x},{cy(b):.0f} {left},{cy(b):.0f}" marker-start="url(#lm-arrow)"><title>Шаг {b+1} опирается на шаг {a+1}: {LINK_RU.get(typ, typ)}</title></path>')
    prev_part = None
    for i, s in enumerate(steps):
        y = top + row * i
        part = s["part"]["title"]
        out.append(f'<a href="{url_of[s["node_id"]]}" class="lm-node" data-node="{s["node_id"]}">')
        out.append(f'<rect x="{left}" y="{y+4}" width="{W-left-6}" height="{row-20}" rx="10" class="lm-box"/>')
        out.append(f'<text x="{left+14}" y="{y+29}" class="lm-num">{s["index"]}</text>')
        title = s["title_beginner"]
        if len(title) > 46:
            title = title[:44] + "…"
        out.append(f'<text x="{left+44}" y="{y+29}" class="lm-title">{html.escape(title)}</text>')
        out.append("</a>")
        if part != prev_part:
            prev_part = part
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- media

def find_media(rd: Path, site: Path, step: dict, scene: dict | None) -> dict | None:
    nid = step["node_id"]
    vdir = rd / "video" / nid
    videos = []
    if vdir.exists():
        for mp4 in sorted(vdir.glob("*.mp4")):
            v = {"src": f"../video/{nid}/{mp4.name}", "name": mp4.stem, "vertical": "short" in mp4.stem or "9x16" in mp4.stem}
            srt = mp4.with_suffix(".srt")
            if not srt.exists():
                cands = sorted(vdir.glob("*.srt"))
                srt = cands[0] if cands else None
            if srt and srt.exists():
                vtt = site / "media" / f"{slug(nid)}-{mp4.stem}.vtt"
                vtt.parent.mkdir(parents=True, exist_ok=True)
                vtt.write_text(srt_to_vtt(srt.read_text(encoding="utf-8")), encoding="utf-8")
                v["vtt"] = f"media/{vtt.name}"
            pas = vdir / f"passport.{mp4.stem}.json"
            if not pas.exists():
                pas = vdir / "passport.json"
            if pas.exists():
                try:
                    p = read_json(pas)
                    if p.get("format") in (None, mp4.stem):
                        v["passport"] = {k: p[k] for k in ("prediction_question", "transfer_question", "exaggerations", "data_bridge") if p.get(k)}
                except Exception:
                    pass
            videos.append(v)
    if videos:
        return {"kind": "video", "videos": videos}
    if step["format"] in ("short", "long", "interactive") and scene and (scene.get("template") or scene.get("views")):
        frames = render_scene_frames(scene, site / "media" / slug(nid))
        if frames:
            return {"kind": "animation", "frames": frames, "interactive": step["format"] == "interactive",
                    "invariants": scene.get("invariants", []), "assumptions": scene.get("assumptions", []),
                    "exaggerations": scene.get("exaggerations", [])}
    return None


def render_scene_frames(scene: dict, out: Path) -> list[dict]:
    """Animation frames rendered by kmd.visuals from the node's scene spec (same state model as the video).

    Two scene layouts are accepted: {template, params, frames} or {views: {name: {template, params}},
    frames: [{view, t: [t0, t1] | t, description, provenance}]}. One still per frame (end of its time span)."""
    try:
        import kmd.visuals as V
        meta = {e["name"]: e for e in V.catalog()}
    except Exception:
        return []
    views = scene.get("views") or {}
    if not views and scene.get("template"):
        views = {"main": {"template": scene["template"], "params": scene.get("params", {})}}
    specs = [f for f in (scene.get("frames") or []) if isinstance(f, dict)]
    jobs = []
    if specs:
        for f in specs:
            v = views.get(f.get("view")) or (next(iter(views.values())) if len(views) == 1 else None)
            if not v or v.get("template") not in meta:
                continue
            t = f.get("t")
            if isinstance(t, (list, tuple)) and t:
                t = t[-1]
            if not meta[v["template"]].get("animatable"):
                t = None
            jobs.append((v, t, f.get("description", ""), f.get("provenance")))
    else:
        for v in views.values():
            if v.get("template") in meta:
                n = 6 if meta[v["template"]].get("animatable") else 1
                for k in range(n):
                    jobs.append((v, round(k / max(1, n - 1), 3) if n > 1 else None, "", None))
    if not jobs:
        return []
    key = hashlib.sha256(json.dumps([[j[0], j[1]] for j in jobs], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]
    out.mkdir(parents=True, exist_ok=True)
    stamp = out / "spec.hash"
    cached = stamp.exists() and stamp.read_text() == key
    frames = []
    for k, (v, t, desc, prov) in enumerate(jobs):
        base, mbase = out / f"f{k:02d}", out / f"m{k:02d}"
        tpl = v["template"]
        if not (cached and base.with_suffix(".svg").exists() and mbase.with_suffix(".svg").exists()):
            try:
                r = V.render(tpl, v.get("params", {}), base, size=(1200, 750), t=t, exaggerations=scene.get("exaggerations") if isinstance(scene.get("exaggerations"), list) else None, formats=("svg",))
                V.render(tpl, v.get("params", {}), mbase, size=(480, 680), t=t, exaggerations=scene.get("exaggerations") if isinstance(scene.get("exaggerations"), list) else None, formats=("svg",))
                prov = prov or r.get("provenance")
            except Exception as e:
                print(f"[site] scene frame {k} for {scene.get('node_id')}: {str(e)[:200]}")
                continue
        frames.append({"src": f"media/{out.name}/{base.name}.svg", "src_m": f"media/{out.name}/{mbase.name}.svg", "t": t,
                       "caption": desc, "provenance": prov or meta[tpl].get("provenance", "симуляция")})
    stamp.write_text(key)
    return frames


def format_label(s: dict) -> tuple[str, str]:
    """What the step really offers (routing format, downgraded honestly when the media is missing)."""
    fmt, media = s.get("format", "text"), s.get("media") or {}
    if media.get("kind") == "video":
        return FORMAT["long"] if fmt == "long" else FORMAT["short"]
    if media.get("kind") == "animation":
        return ("Интерактив", "⟳") if media.get("interactive") else ("Анимация", "⟳")
    if any(b["kind"] == "decision" for b in s.get("blocks", [])) and fmt == "data_practice":
        return FORMAT["data_practice"]
    if fmt == "cards":
        return FORMAT["cards"]
    return FORMAT["text"]


# ---------------------------------------------------------------- build

def build(chapter: str) -> Path:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    layer = read_json(rd / "layer.json")
    order = [n for n in layer.get("order", [])] or [n["id"] for n in layer["nodes"]]
    steps = []
    for nid in order:
        p = rd / "steps" / f"{nid}.json"
        if p.exists():
            steps.append(read_json(p))
    if not steps:
        raise FileNotFoundError(f"no steps in {rd/'steps'}: run `kmd course {chapter}` first")
    steps.sort(key=lambda s: s["index"])
    for i, s in enumerate(steps):
        s["index"] = i + 1
    tasks = {t["id"]: t for t in (read_json(rd / "tasks.json")["tasks"] if (rd / "tasks.json").exists() else [])}
    cards = read_json(rd / "cards.json")["cards"] if (rd / "cards.json").exists() else []
    scenes = {}
    if (rd / "scenes").exists():
        for f in (rd / "scenes").glob("*.json"):
            try:
                sc = read_json(f)
                scenes[sc.get("node_id", f.stem)] = sc
            except Exception:
                pass

    site = rd / "site"
    if site.exists():
        shutil.rmtree(site)
    (site / "img").mkdir(parents=True)
    shutil.copytree(STATIC, site / "assets")
    if VENDOR.exists():
        shutil.copytree(VENDOR, site / "assets" / "vendor")

    url_of = {s["node_id"]: f"step-{s['index']:02d}.html" for s in steps}
    title_of = {s["node_id"]: s["title_beginner"] for s in steps}
    index_of = {s["node_id"]: s["index"] for s in steps}

    # illustrations: inline builtin SVG (theme-aware), copy visuals files
    for s in steps:
        # pick up book-figure redraws that appeared after `kmd course` ran
        have = {i.get("file") for i in s.get("illustrations", [])}
        s.setdefault("illustrations", []).extend(i for i in redraw_ills(rd, s["node_id"]) if i["file"] not in have)
        redrawn = {str((i.get("redrawn_from") or {}).get("figure")) for i in s["illustrations"] if i.get("redraw")}
        for b in s.get("blocks", []):
            if b.get("kind") == "book_figures":
                for f in b.get("items", []):
                    f["redrawn"] = str(f.get("number")) in redrawn
        for ill in s.get("illustrations", []):
            f = rd / ill["file"] if not Path(ill["file"]).is_absolute() else Path(ill["file"])
            ill["inline"] = None
            ill["src"] = None
            if not f.exists():
                continue
            if ill.get("renderer") == "builtin" and f.suffix == ".svg":
                svg = f.read_text(encoding="utf-8")
                svg = re.sub(r"<style>.*?</style>", "", svg, flags=re.S)
                ill["inline"] = svg
            else:
                dst = site / "img" / f.name
                shutil.copy2(f, dst)
                ill["src"] = f"img/{f.name}"
                fm = rd / ill["file_m"] if ill.get("file_m") else None
                if fm and fm.exists():
                    shutil.copy2(fm, site / "img" / fm.name)
                    ill["src_m"] = f"img/{fm.name}"
        s["media"] = find_media(rd, site, s, scenes.get(s["node_id"]))
        s["format_label"] = format_label(s)
        # related steps
        rel: dict[str, dict] = {}
        for l in s.get("links", []):
            if l.get("to") not in url_of:
                continue
            r = rel.setdefault(l["to"], {"title": title_of[l["to"]], "url": url_of[l["to"]], "index": index_of[l["to"]], "types": []})
            t = LINK_RU.get(l.get("type"), l.get("type"))
            if t not in r["types"]:
                r["types"].append(t)
        s["relies_on"] = [dict(r, type=", ".join(r["types"])) for r in rel.values()]
        s["used_by"] = []
    for s in steps:
        for r in s["relies_on"]:
            tgt = next(x for x in steps if x["index"] == r["index"])
            tgt["used_by"].append({"title": s["title_beginner"], "url": url_of[s["node_id"]], "index": s["index"], "type": r["type"]})

    parts = []
    for s in steps:
        if not parts or parts[-1]["id"] != s["part"]["id"]:
            parts.append({"id": s["part"]["id"], "title": s["part"]["title"], "steps": []})
        parts[-1]["steps"].append(s)

    total_min = sum(s["minutes"] for s in steps)
    course = {
        "chapter": cfg["id"],
        "title": layer.get("title") or cfg.get("title", ""),
        "book": cfg.get("book", {}),
        "steps": [{"node_id": s["node_id"], "index": s["index"], "title": s["title_beginner"], "url": url_of[s["node_id"]], "minutes": s["minutes"]} for s in steps],
        "minutes": total_min,
        "n_tasks": len(tasks),
        "n_cards": len(cards),
    }
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=jinja2.select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["md"] = lambda t: jinja2.Markup(md(t)) if hasattr(jinja2, "Markup") else md(t)
    try:
        from markupsafe import Markup
        env.filters["md"] = lambda t: Markup(md(t))
    except Exception:
        pass
    env.filters["pages"] = pages_label
    env.globals.update(FORMAT=FORMAT, KIND_RU=KIND_RU, DIFF_RU=DIFF_RU, LINK_RU=LINK_RU, course=course, parts=parts,
                       course_json=jdump(course))

    def page(name, out, **kw):
        html_s = env.get_template(name).render(**kw)
        (site / out).write_text(html_s, encoding="utf-8")

    all_views = []
    for i, s in enumerate(steps):
        views = [task_view(tasks[tid], s, "") for tid in s["task_ids"] if tid in tasks]
        for v in views:
            v["link"] = f"#{tasks[v['id']]['anchor'] or 'how'}"
        all_views += [dict(v, link=f"{url_of[s['node_id']]}{v['link']}") for v in views]
        prev_s = steps[i - 1] if i > 0 else None
        next_s = steps[i + 1] if i + 1 < len(steps) else None
        ills_after = {}
        for ill in s.get("illustrations", []):
            ab = ill.get("after_block") or "how"
            if ab == "book_figures" and not any(b.get("kind") == "book_figures" for b in s.get("blocks", [])):
                ab = "how"
            ills_after.setdefault(ab, []).append(ill)
        page("step.html", url_of[s["node_id"]], s=s, tasks=views, tasks_json=jdump(views),
             prev=prev_s and {"url": url_of[prev_s["node_id"]], "title": prev_s["title_beginner"]},
             next=next_s and {"url": url_of[next_s["node_id"]], "title": next_s["title_beginner"]},
             ills_after=ills_after, page_id="step")
    page("index.html", "index.html", page_id="index")
    page("tasks.html", "tasks.html", tasks=all_views, tasks_json=jdump(all_views), page_id="tasks", steps=steps)
    card_views = [dict(c, step_title=title_of.get(c["node_id"], ""), step_index=index_of.get(c["node_id"]), url=url_of.get(c["node_id"])) for c in cards if c["node_id"] in url_of]
    page("cards.html", "cards.html", cards=card_views, cards_json=jdump(card_views), page_id="cards")
    page("summary.html", "summary.html", steps=steps, page_id="summary")
    page("map.html", "map.html", steps=steps, svg=link_map_svg(steps, url_of), page_id="map")

    size = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    write_json(rd / "site_report.json", {"chapter": cfg["id"], "steps": len(steps), "tasks": len(all_views), "cards": len(card_views),
                                         "size_mb": round(size / 1e6, 2), "media": {s["node_id"]: (s["media"] or {}).get("kind") for s in steps}})
    print(f"[site] {site/'index.html'}  ({len(steps)} steps, {len(all_views)} tasks, {len(card_views)} cards, {size/1e6:.1f} MB)")
    return site
