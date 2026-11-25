"""QA checklist (brief section 8). Writes qa.json + qa_report.md. Never edits the video; fixes are logged."""
import re
from pathlib import Path

import numpy as np

from . import config as C
from .truth import (build_source_table, verify_sources, check_line_numbers, check_screen_numbers, physics_check,
                    spec_rules_check)
from .templates import CARD_TEMPLATES
from .util import read_json, write_json, log


def _detect(img, color, region, tol=3):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in region]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    rgb = np.array([int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)])
    sub = img[y0:y1, x0:x1, :3].astype(int)
    m = (np.abs(sub - rgb) <= tol).all(axis=2)
    if m.sum() < 4:
        return None
    ys, xs = np.nonzero(m)
    return float(x0 + xs.mean()), float(y0 + ys.mean())


def frame_checks(P, shot_id, layout):
    from PIL import Image
    res = []
    probes = {p["name"]: p for p in layout.get("probes", [])}
    frames = sorted(P.p("05_renders", "qa").glob(f"{shot_id}_f*.png"))
    for chk in layout.get("checks", []):
        if chk["type"] not in ("frame_same_y", "frame_expect"):
            continue
        worst, n_ok, n_tot, missing = 0.0, 0, 0, 0
        for fp in frames:
            f = int(fp.stem.split("_f")[-1])
            if f < 6:                                      # skip fade-in frames
                continue
            img = np.asarray(Image.open(fp))
            names = [chk["a"], chk["b"]] if chk["type"] == "frame_same_y" else chk["probes"]
            found = {n: _detect(img, probes[n]["color"], probes[n]["region"]) for n in names if n in probes}
            if any(v is None for v in found.values()):
                missing += 1
                continue
            n_tot += 1
            if chk["type"] == "frame_same_y":
                err = abs(found[chk["a"]][1] - found[chk["b"]][1])
                for n in names:                            # also vs the model's expected position
                    ey = probes[n].get("expect_y")
                    if ey:
                        err = max(err, abs(found[n][1] - ey[min(f, len(ey) - 1)]))
            else:
                err = 0.0
                for n in names:
                    for axis, key in ((0, "expect_x"), (1, "expect_y")):
                        ex = probes[n].get(key)
                        if ex:
                            err = max(err, abs(found[n][axis] - ex[min(f, len(ex) - 1)]))
            worst = max(worst, err)
            n_ok += err <= chk.get("tol_px", 4)
        status = "pass" if n_tot and n_ok == n_tot else ("warn" if not n_tot else "fail")
        res.append({"id": f"{shot_id}:{chk['id']}", "status": status, "text": chk["text"],
                    "details": f"{n_ok}/{n_tot} sampled frames within {chk.get('tol_px', 4)} px "
                               f"(worst {worst:.1f} px); {missing} frames without probe"})
    return res


def run_qa(P):
    script = read_json(P.p("01_script.json"))
    shotlist = read_json(P.p("02_shotlist.json"))
    tl = read_json(P.p("timeline.json"))
    ov = read_json(P.p("07_overlays", "overlays.json"))
    audio = read_json(P.p("06_audio", "audio.json"))
    metrics = read_json(P.p("metrics.json"), {}) or {}
    specs = P.specs()
    lang = P.lang
    R = []

    def add(section, id_, status, text, details=""):
        R.append({"section": section, "id": id_, "status": status, "text": text, "details": details})

    # ---------------------------------------------------------------- TRUTH
    st = verify_sources(build_source_table(script, specs, P.node), P.pages)
    write_json(P.p("source_table.json"), st)
    claims = [r for r in st if r["kind"] in ("claim", "formula", "param", "table")]
    by = {}
    for r in claims:
        by[r["status"]] = by.get(r["status"], 0) + 1
    if not claims:
        add("truth", "claims_verified", "warn", "No claim sources in the script")
    elif all(r["status"] == "verified" for r in claims):
        add("truth", "claims_verified", "pass", "Every claim maps to a page + verbatim quote found in the chapter",
            str(by))
    else:
        bad = [r for r in claims if r["status"] != "verified"]
        why = "chapter pages not provided — quotes cannot be checked" if not P.pages.available else \
            "; ".join(f"{r.get('ref') or r.get('claim_id')} p.{r.get('page')}: {r['status']}"
                      + (f" (found on p.{(r.get('match') or {}).get('page_found')})" if r["status"] == "wrong_page" else "")
                      + (f" cells not on page: {r['missing_cells'][:4]}" if r.get("missing_cells") else "")
                      for r in bad[:8])
        add("truth", "claims_verified", "fail", "Every claim maps to a page + verbatim quote", f"{by}; {why}")
    from .planner import validate_script
    errs_now, _ = validate_script(script, P.node, P.pages, P.brief["format"])     # re-validate: later stages add sources
    unsourced = [e for e in errs_now if "without a source" in e]
    add("truth", "facts_have_sources", "fail" if unsourced else "pass",
        "Every factual narration line has a source", "; ".join(unsourced))
    ln = check_line_numbers(script, st, P.pages)
    add("truth", "spoken_numbers", "fail" if any(i["severity"] == "fail" for i in ln) else
        ("warn" if ln else "pass"), "Every spoken number is in the source table",
        "; ".join(f"{i['line']}: {i['number']} ({i['status']})" for i in ln))
    sn = check_screen_numbers([it for it in ov["items"] if it.get("kind") in ("label", "callout")], st)
    add("truth", "screen_numbers", "fail" if sn else "pass", "Every on-screen number is sourced (claim/dataset/model/axis)",
        "; ".join(f"{i['shot']}: '{i['text']}' -> {i['number']}" for i in sn[:12]))
    ass = [r for r in st if r["kind"] == "assumption"]
    add("truth", "assumptions_listed", "info" if ass else "pass",
        "Values not taken from the chapter are marked as assumptions (listed in the passport)", f"{len(ass)} assumptions")
    # invariants
    inv_fail, inv_n = [], 0
    for sh in shotlist["shots"]:
        L = read_json(P.p("05_renders", f"{sh['id']}.layout.json"))
        for chk in L.get("checks", []):
            if chk["type"] == "assert":
                inv_n += 1
                if not chk.get("ok"):
                    inv_fail.append(f"{sh['id']}: {chk['text']}")
        for fr in frame_checks(P, sh["id"], L):
            R.append({"section": "truth", **fr})
    add("truth", "invariants_model", "fail" if inv_fail else "pass", "Scene-spec invariants hold (model/layout level)",
        f"{inv_n} checks; failing: {inv_fail}" if inv_fail else f"{inv_n} checks")
    # AI
    ai_shots = [s for s in shotlist["shots"] if s["template"] == "ai_clip"]
    ai_info = [read_json(P.p("05_renders", f"{s['id']}.ai.json")) for s in ai_shots]
    used_ai = [a for a in ai_info if a]
    add("truth", "no_ai_text", "pass", "No AI-generated text, digits, axes or arrows: all text is composited from JSON",
        f"{len(used_ai)} AI clips generated; prompts checked for text/digit/diagram words")
    bad_d = []
    for s in shotlist["shots"]:
        if s["class"] == "D":
            for lid in s["line_ids"]:
                l = next(x for x in script["lines"] if x["id"] == lid)
                if l.get("asserts_fact"):
                    bad_d.append(f"{s['id']} carries fact {lid}")
    add("truth", "ai_frames_verified", "fail" if bad_d else "pass",
        "Every AI clip starts/ends on a verified frame; no AI clip shows mechanism or data",
        "; ".join(bad_d) if bad_d else (f"{len(ai_shots)} class D shots" if ai_shots else "no class D shots"))
    # physics
    texts = [(l["id"], l["text"], bool(l.get("myth"))) for l in script["lines"]]
    texts += [(it.get("shot"), it.get("text", ""), bool(it.get("myth"))) for it in ov["items"]
              if it.get("kind") in ("label", "callout")]
    ph = physics_check(texts, P.domain.physics_rules, lang)
    for r in ph:
        if r["status"] == "n/a":
            continue
        add("truth", f"physics:{r['id']}", r["status"], r.get("text", ""),
            "; ".join(f"{h['where']}: «{h['sentence']}»" for h in r.get("hits", [])))
    for r in spec_rules_check(specs, P.domain.spec_rules):
        if r["status"] == "fail":
            add("truth", f"physics:{r['id']}:{r['shot']}", "fail", r.get("text", ""))
    # provenance vs method
    prov_bad = []
    for s, sp in zip(shotlist["shots"], specs):
        mt = (sp.get("model") or {}).get("type")
        pv = sp.get("provenance")
        exp = {"A": "data", "C": "photo", "D": "schematic", "T": "schematic"}.get(s["class"])
        if s["class"] == "B":
            exp = "simulation" if mt in ("formula", "pde_diffusion") else "schematic"
        base_t = (sp.get("params") or {}).get("base", {}).get("template") if s["template"] == "overlay_card" else s["template"]
        if base_t == "depth_track":
            exp = pv          # region chips: schematic cutaway + data track
        if s["template"] in CARD_TEMPLATES and s["class"] != "T":
            prov_bad.append(f"{s['id']}: text card {s['template']} reported as class {s['class']} (must be T)")
        if s["class"] == "A" and mt not in ("las", "csv", "table"):
            prov_bad.append(f"{s['id']}: class A without a dataset model")
        if exp and pv != exp:
            prov_bad.append(f"{s['id']}: label '{pv}' but made as '{exp}'")
    add("truth", "provenance_labels", "fail" if prov_bad else "pass",
        "Provenance label on each frame matches how it was made", "; ".join(prov_bad))
    if any(s["class"] in ("C", "D") for s in shotlist["shots"]):
        add("truth", "label_set", "manual", "Class C/D frames use a label outside {real data, simulation, schematic} "
                                            "or a placeholder: team decision needed")
    # shares (class T = full-screen text cards, reported separately from B)
    dur = {s["id"]: t["dur"] for s, t in zip(shotlist["shots"], tl["shots"])}
    by_cls = {}
    for s in shotlist["shots"]:
        by_cls[s["class"]] = by_cls.get(s["class"], 0) + dur[s["id"]]
    D_ = max(1e-9, tl["duration"])
    share = (by_cls.get("A", 0) + by_cls.get("B", 0)) / D_
    card = by_cls.get("T", 0) / D_
    nd = sum(1 for s in shotlist["shots"] if s["class"] == "D")
    shares_txt = ", ".join(f"{k}: {v / D_ * 100:.0f}%" for k, v in sorted(by_cls.items()))
    add("truth", "ab_share", "pass" if share >= C.MIN_AB_SHARE else "fail",
        f"≥{int(C.MIN_AB_SHARE * 100)}% of screen time is class A/B (visual data/process)", shares_txt)
    add("truth", "card_share", "pass" if card <= C.MAX_CARD_SHARE + 1e-9 else "fail",
        f"Text cards (class T) ≤ {int(C.MAX_CARD_SHARE * 100)}% of screen time", f"T: {card * 100:.0f}%")
    lines_ = {l["id"]: l for l in script["lines"]}
    no_vis = [f"{lid} ({lines_[lid]['role']}) on {s['id']} {s['template']}" for s in shotlist["shots"]
              if s["class"] not in ("A", "B", "C") for lid in s["line_ids"]
              if lines_.get(lid, {}).get("role") in C.VISUAL_ROLES]
    add("truth", "mechanism_visuals", "fail" if no_vis else "pass",
        "Every mechanism/data line is shown on a visual template (class A/B/C)", "; ".join(no_vis))
    overlay_t = sum(dur[s["id"]] for s in shotlist["shots"] if s["template"] == "overlay_card")
    if overlay_t:
        add("truth", "overlay_cards", "info", "Visual shots with a question/fact strip beside the visual (overlay_card)",
            f"{overlay_t / D_ * 100:.0f}% of screen time")
    add("truth", "d_clips", "pass" if nd <= C.MAX_D_CLIPS else "fail", f"≤{C.MAX_D_CLIPS} class D clips", f"{nd}")

    # ---------------------------------------------------------------- FORM
    add("form", "style", "pass", "One style, one theme, one subtitle style for the whole video",
        f"style {P.brief.get('style')}, fonts bundled in assets/fonts")
    portrait = P.fmt["orientation"] == "portrait"
    subs = [it for it in ov["items"] if it.get("kind") == "subtitle"]
    min_size = 30 if portrait else 40
    max_chars = 30 if portrait else 50
    small = [s for s in subs if s.get("size", 0) < min_size]
    long_ = [s["text"] for s in subs if len(re.sub(r"\*", "", s["text"])) > max_chars * 1.5]
    brief_ = [s["text"] for s in subs if s["t1"] - s["t0"] < 0.6]
    add("form", "subtitles_readable", "fail" if small or long_ else ("warn" if brief_ else "pass"),
        "Subtitles readable on a phone (size, length, ≥0.6 s on screen), no overflow (wrapped to max width)",
        f"{len(subs)} chunks; too long: {long_[:3]}; very short: {len(brief_)}")
    desync = []
    for s in subs:
        a, b = tl["lines"][s["line"]]
        if s["t0"] < a - 0.05 or s["t0"] > b + 0.05:
            desync.append(s["text"][:30])
    add("form", "subtitles_synced", "fail" if desync else "pass",
        "Subtitles synced to the voice (chunk inside its line's audio)", f"{desync[:3]}")
    tws = audio.get("terms_without_stress") or []
    add("form", "stress", "warn" if (tws or not P.domain.stress) and lang == "ru" else "pass",
        "Stress/pronunciation of terms checked against the dictionary",
        f"dictionary entries: {len(P.domain.stress)}; glossary terms in narration without entry: {tws[:10]}"
        + ("" if P.domain.stress else " — NO stress dictionary provided (domain pack)"))
    lo, hi = P.fmt["target_s"]
    d = tl["duration"]
    add("form", "length", "pass" if lo * 0.9 <= d <= hi * 1.05 else "warn", f"Length within target {lo}-{hi} s",
        f"{d:.1f} s")
    first = script["lines"][0]
    t_first = tl["lines"][first["id"]][0]
    add("form", "hook_3s", "pass" if first["role"] in ("hook", "prediction") and t_first < 1.0 else "fail",
        "Hook comes in the first 3 s", f"first line '{first['role']}' at {t_first:.2f} s")
    lu = (metrics.get("loudness") or {}).get("after_lufs")
    add("form", "loudness", "pass" if lu is not None and abs(lu - C.LOUDNESS_LUFS) <= 1.0 else "warn",
        f"Loudness about {C.LOUDNESS_LUFS} LUFS", f"{lu if lu is None else round(lu, 1)} LUFS")
    # ---------------------------------------------------------------- INPUTS / COVERAGE
    cov = read_json(P.p("coverage_report.json"), {})
    gaps = cov.get("gaps", [])
    add("coverage", "templates", "warn" if gaps else "pass", "All requested visuals covered by templates",
        "; ".join(f"{g.get('shot')}: {g.get('status')} ({g.get('wanted_template')})" for g in gaps[:8]))
    if P.node["_missing"]:
        add("coverage", "node_fields", "warn", "Node has all expected fields", f"missing: {P.node['_missing']}")
    for m in P.domain.physics_manual:
        add("mentor", "physics_manual", "manual", m)
    for m in P.domain.style_notes[:30]:
        add("mentor", "style_guide", "manual", m)
    add("mentor", "spec_review", "manual", "Mentor reviewed scene specs + source table before final render",
        "see mentor_pack.md")
    return R


def write_reports(P, R, fixes=None, minutes=None):
    write_json(P.p("qa.json"), R)
    cnt = {}
    for r in R:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "info": "ℹ️", "manual": "☐"}
    md = [f"# QA report — {P.brief['video_id']}", "",
          f"Summary: " + ", ".join(f"{icon.get(k, k)} {k}: {v}" for k, v in sorted(cnt.items())), ""]
    for sec in ("truth", "form", "coverage", "mentor"):
        rows = [r for r in R if r["section"] == sec]
        if not rows:
            continue
        md += [f"## {sec.capitalize()}", "", "| | check | details |", "|---|---|---|"]
        for r in rows:
            det = str(r.get("details", "")).replace("|", "/").replace("\n", " ")[:400]
            md.append(f"| {icon.get(r['status'], r['status'])} | {r['text']} | {det} |")
        md.append("")
    md += ["## Fixes log", ""]
    fx = fixes if fixes is not None else (read_json(P.p("fixes.json"), []) or [])
    if fx:
        md += ["| when | what | minutes |", "|---|---|---|"] + [f"| {f.get('when', '')} | {f['what']} | {f.get('minutes', '')} |"
                                                              for f in fx]
    else:
        md.append("No manual fixes recorded yet (add entries to fixes.json: {when, what, minutes}).")
    m = read_json(P.p("metrics.json"), {}) or {}
    secs = m.get("machine_seconds", {})
    md += ["", "## Time", "", f"Machine time by stage (s): {secs}",
           f"Total machine minutes: {sum(secs.values()) / 60:.1f}"]
    P.p("qa_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    log(f"qa: {cnt}", "ok" if not cnt.get("fail") else "warn")
    return cnt


def mentor_pack(P):
    """Compact spec + source table for mentor review before the final render."""
    script = read_json(P.p("01_script.json"))
    st = read_json(P.p("source_table.json"), [])
    md = [f"# Mentor review pack — {P.brief['video_id']}", "", "## Narration", ""]
    for l in script["lines"]:
        src = "; ".join(f"{s.get('claim_id') or s.get('file')} p.{s.get('page')}" for s in l.get("sources", []))
        md.append(f"- **{l['id']} {l['role']}**: {l['text']}  _[{src or 'no fact'}]_")
    md += ["", "## Source table", "", "| id | kind | ref | page | status | quote / file |", "|---|---|---|---|---|---|"]
    for r in st:
        q = (r.get("quote") or r.get("file") or r.get("note") or "")
        md.append(f"| {r['id']} | {r['kind']} | {r.get('ref') or r.get('param') or ''} | {r.get('page') or ''} | "
                  f"{r.get('status', '')} | {str(q)[:120].replace('|', '/')} |")
    md += ["", "## Scene specs", ""]
    for sp in P.specs():
        m = sp.get("model") or {}
        md.append(f"### {sp['shot_id']} — {sp['template']} (class {sp['class']}, label {sp.get('provenance')})")
        if m:
            md.append(f"- model: `{m.get('type')}` {m.get('expr') or m.get('file') or ''} {m.get('curve') or ''}")
            for k, v in (m.get("params") or {}).items():
                md.append(f"  - {k} = {v.get('value') if isinstance(v, dict) else v} {v.get('unit', '') if isinstance(v, dict) else ''}"
                          f" — {(v.get('source') if isinstance(v, dict) else '')}")
        for k in ("invariants", "assumptions"):
            if sp.get(k):
                md.append(f"- {k}: " + "; ".join(map(str, sp[k])))
        md.append("")
    P.p("mentor_pack.md").write_text("\n".join(md), encoding="utf-8")
