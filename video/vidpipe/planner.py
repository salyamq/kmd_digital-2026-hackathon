"""Planners: node -> script -> shot list -> scene specs.

rule  : deterministic, no LLM. Uses only node content + data-driven maps (template_map.json, mnemonics.json,
        dataset catalog). Guaranteed to produce a valid, fully-sourced (or honestly-flagged) plan for ANY node.
llm   : see llm.py. Its output is validated here (validate_script / validate_shots) and any shot that fails
        is replaced by the rule planner's equivalent, so the pipeline never dies on a bad LLM answer.
"""
import re

import numpy as np

from .config import FORMATS, CLASS_LABEL
from .inputs import match_curves, norm_text
from .templates import REGISTRY
from .truth import numbers_in, quote_in_claims
from .util import RES_DIR, read_json, log

ROLES = ["hook", "prediction", "reveal", "mechanism", "data", "bridge", "transfer", "outro"]


# ============================================================================ helpers

def words(text):
    return len(re.findall(r"\w+", text or ""))


def strip_end(s):
    return re.sub(r"[.!?…\s]+$", "", (s or "").strip())


def short_title(text, limit=48):
    """First clause of a claim, for step titles. Never invents words, only cuts."""
    t = strip_end(text)
    if len(t) <= limit:
        return t
    for sep in [":", " — ", " – ", ";", ",", " — "]:
        if sep in t[:limit + 20]:
            head = t.split(sep)[0].strip()
            if 12 <= len(head) <= limit + 10:
                return head
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def claim_source(c):
    return {"type": "claim", "claim_id": c["id"], "page": c.get("page"), "quote": c.get("quote")}


def best_claim(text, claims, exclude=()):
    """Claim with the highest word overlap with text (to attach a source to a node-level statement)."""
    tw = set(re.findall(r"\w{4,}", norm_text(text)))
    best, score = None, 0.0
    for c in claims:
        if c["id"] in exclude:
            continue
        cw = set(re.findall(r"\w{4,}", norm_text((c.get("quote") or "") + " " + (c.get("text") or ""))))
        if not cw:
            continue
        s = len(tw & cw) / max(1, len(tw))
        if s > score:
            best, score = c, s
    return best if score >= 0.25 else None


def lang_pack(lang):
    i18n = read_json(RES_DIR / "i18n.json")
    return i18n.get(lang, i18n["en"]), i18n


# ============================================================================ rule-based script

def rule_script(node, fmt, lang):
    T, _ = lang_pack(lang)
    R = T["rule"]
    F = FORMATS[fmt]
    lines = []

    def add(role, text, sources=(), asserts=True, myth=False):
        if not text or not str(text).strip():
            return
        lines.append({"id": f"L{len(lines) + 1}", "role": role, "text": str(text).strip(),
                      "sources": list(sources), "asserts_fact": bool(asserts), "myth": myth})

    mis = node.get("misconception")
    claims = node.get("claims", [])
    used = set()
    if mis and mis.get("wrong"):
        w = strip_end(mis["wrong"])
        w = w[0].lower() + w[1:] if len(w) > 1 and not w[1].isupper() else w
        add("hook", R["hook_myth"].format(wrong=w), asserts=False, myth=True)
    else:
        add("hook", R["hook_title"].format(title=node["title"]), asserts=False)
    pq = node.get("prediction_question")
    if pq:
        add("prediction", pq if isinstance(pq, str) else (pq or {}).get("text"), asserts=False)
    elif mis and mis.get("wrong"):
        add("prediction", R["predict_generic"], asserts=False)
    elif claims:                       # no myth: let the viewer judge the first claim before it is explained
        c0 = strip_end(claims[0]["text"])
        c0 = c0[0].lower() + c0[1:] if len(c0) > 1 and not c0[1].isupper() else c0
        add("prediction", f"{T['connectors']['true_or_false']} {c0}?", asserts=False)
    else:
        add("prediction", R["predict_generic"], asserts=False)
    if mis and mis.get("right"):
        src = []
        c = next((c for c in claims if c["id"] == str(mis.get("claim_id"))), None) or best_claim(mis["right"], claims)
        if mis.get("quote"):
            src.append({"type": "claim", "claim_id": mis.get("claim_id") or (c or {}).get("id", "misconception"),
                        "page": mis.get("page"), "quote": mis["quote"]})
        elif c:
            src.append(claim_source(c))
            used.add(c["id"])
        add("reveal", mis["right"], src, asserts=True)
    max_mech = 3 if fmt == "short" else 8
    for c in [c for c in claims if c["id"] not in used][:max_mech]:
        add("mechanism", c["text"], [claim_source(c)])
        used.add(c["id"])
    dm = node.get("data_meaning", {})
    if dm.get("text"):
        src = [claim_source(c) for c in claims if c["id"] in [str(x) for x in dm.get("claim_ids", [])]]
        if not src:
            c = best_claim(dm["text"], claims)
            src = [claim_source(c)] if c else []
        add("data", dm["text"], src, asserts=True)
    if node.get("it_analogy"):
        add("bridge", node["it_analogy"], asserts=False)
    tq = node.get("transfer_question")
    add("transfer", tq if isinstance(tq, str) else (tq or {}).get("text") if tq else R["transfer_generic"],
        asserts=False)
    # fit the word budget: drop trailing mechanism lines first (keep at least one)
    while sum(words(l["text"]) for l in lines) > F["words"][1] and \
            sum(1 for l in lines if l["role"] == "mechanism") > 1:
        idx = max(i for i, l in enumerate(lines) if l["role"] == "mechanism")
        lines.pop(idx)
    for i, l in enumerate(lines):
        l["id"] = f"L{i + 1}"
    return {"node_id": node["id"], "lang": lang, "format": fmt, "title": node["title"],
            "kicker": (node.get("source") or {}).get("title") if isinstance(node.get("source"), dict) else None,
            "lines": lines,
            "prediction_question": next((l["text"] for l in lines if l["role"] == "prediction"), None),
            "transfer_question": next((l["text"] for l in lines if l["role"] == "transfer"), None),
            "data_it_bridge": {"where_in_data": dm.get("text"), "it_analogy": node.get("it_analogy"),
                               "manual_work": None},
            "planner": "rule"}


# ============================================================================ dataset helpers (generic)

def best_depth_window(las_file, curve, length):
    import lasio
    import warnings
    warnings.filterwarnings("ignore")
    las = lasio.read(las_file)
    d = np.asarray(las.index, float)
    v = np.asarray(las[curve], float)
    ok = np.isfinite(v)
    d, v = d[ok], v[ok]
    if len(d) < 50:
        return [float(d.min()), float(d.max())]
    best, score = None, -1
    for top in np.arange(max(d.min(), 200), d.max() - length, length / 6):
        m = (d >= top) & (d <= top + length)
        if m.sum() < 30:
            continue
        s = np.percentile(v[m], 90) - np.percentile(v[m], 10)
        if s > score:
            best, score = top, s
    if best is None:
        return [float(d.min()), float(min(d.max(), d.min() + length))]
    return [float(round(best)), float(round(best + length))]


def tops_layers(catalog, well, window):
    """Formation tops within the window as layers (lithology unknown unless the spec says otherwise)."""
    import pandas as pd
    for e in catalog:
        if e.get("kind") != "formation_tops":
            continue
        a_, b_ = norm_text(e.get("well") or "").replace(" ", ""), norm_text(well or "").replace(" ", "")
        if well and e.get("well") and not (a_.startswith(b_) or b_.startswith(a_)):
            continue
        df = pd.read_csv(e["file"])
        cols = list(df.columns)
        df = df.sort_values(cols[1])
        tops = list(zip(df[cols[0]], df[cols[1]].astype(float)))
        layers = []
        for i, (name, top) in enumerate(tops):
            base = tops[i + 1][1] if i + 1 < len(tops) else window[1]
            lt, lb = max(top, window[0]), min(base, window[1])
            if lb > lt:
                layers.append({"top": lt, "base": lb, "lith": "unknown", "label": str(name).title(),
                               "source_ref": f"dataset:{e['file'].split('/')[-1]}"})
        return layers, e
    return [], None


def match_csv_columns(catalog, wanted):
    """A CSV dataset whose columns include a wanted name; picks the entity (well) with the longest series."""
    import pandas as pd
    wanted = [str(w).lower() for w in wanted if w]
    for e in catalog:
        if e.get("type") != "csv":
            continue
        cols = {c.lower(): c for c in e.get("columns", [])}
        for w in wanted:
            if w in cols:
                col = cols[w]
                well = None
                if e.get("well_column"):
                    df = pd.read_csv(e["file"], usecols=[e["well_column"], col])
                    cnt = df[df[col] > 0].groupby(e["well_column"])[col].count()
                    if len(cnt):
                        well = str(cnt.idxmax())
                return e, col, well
    return None


def mechanism_visual(node, catalog, mech, fmt, lang, domain_visuals=None):
    """Pick an honest visual for mechanism lines from node content only. Returns
    (template, class, params, model, provenance, assumptions) or None. Order:
      1. node 'visual_hints' / domain-pack visuals.json keyword match (data supplied by people, not guessed)
      2. a matching open-data LAS curve      -> depth_track (A)
         or a CSV column named by the node  -> data_chart of the real series (A)
      3. a machine-readable formula in node  -> data_chart of the formula (B, simulation)
      4. lithology words in the claims       -> cross_section of those units (B, schematic)
    """
    text = norm_text(" ".join(l["text"] for l in mech))
    hints = node.get("visual_hints") or {}
    if isinstance(hints, dict) and hints.get("template"):
        return (hints["template"], hints.get("class", "B"), hints.get("params", {}), hints.get("model"),
                hints.get("provenance", "schematic"), ["visual from node visual_hints"])
    for v in domain_visuals or []:
        if any(norm_text(k) in text for k in v.get("match", [])):
            return (v["template"], v.get("class", "B"), v.get("params", {}), v.get("model"),
                    v.get("provenance", "schematic"), [f"visual from domain pack visuals.json ({v['match'][0]})"])
    hits = match_curves(catalog, node_terms(node))
    if hits:
        h = sorted(hits, key=lambda x: -(x["depth_max"] - x["depth_min"]))[0]
        win = best_depth_window(h["file"], h["curve"], 70 if fmt == "short" else 120)
        layers, _ = tops_layers(catalog, h.get("well"), win)
        model = {"type": "las", "file": h["file"], "curve": h["curve"], "depth_from": win[0] - 2,
                 "depth_to": win[1] + 2, "dataset": h.get("dataset")}
        return ("depth_track", "A", {"track": {"curve": h["curve"], "unit": h.get("unit", "")}, "window": win,
                                     "layers": layers, "readout": True,
                                     "motion": {"start": mech[0]["id"], "end": mech[-1]["id"] + ".end"}},
                model, "data", [f"depth window {win[0]:.0f}–{win[1]:.0f} m chosen automatically"])
    csv_hit = match_csv_columns(catalog, node.get("data_meaning", {}).get("curves", []))
    if csv_hit:                                     # real time series named by the node -> the effect in data
        e, col, well = csv_hit
        model = {"type": "csv", "file": e["file"], "x": e.get("time_column") or e["columns"][0], "y": [col],
                 "dataset": e.get("dataset")}
        if well:
            model["filter"] = {e["well_column"]: well}
        unit = (e.get("units") or {}).get(col, "")
        return ("data_chart", "A", {"y": [f"y_{col}"], "y_label": f"{col}, {unit}".strip(", "),
                                    "dates": bool(e.get("time_column")),
                                    "draw": {"start": mech[0]["id"], "end": mech[-1]["id"] + ".end"},
                                    "caption": f"{e.get('dataset', '')} · {well or ''} · {col}".strip(" ·")},
                model, "data", [f"series chosen automatically: {well or 'all rows'}, column {col}"])
    for f in node.get("formulas", []):
        if isinstance(f, dict) and f.get("expr") and f.get("params") and f.get("grid"):
            g = f["grid"]
            xname = next(iter(g))
            model = {"type": "formula", "expr": f["expr"], "params": f["params"], "derived": f.get("derived", {}),
                     "grid": g, "output": {"name": "y_f"},
                     "source": {"claim_id": f.get("claim_id"), "page": f.get("page"), "quote": f.get("quote")}}
            return ("data_chart", "B", {"x": f"axis_{xname}", "y": ["y_f"], "x_label": f.get("x_label", xname),
                                        "y_label": f.get("y_label", f.get("display", "")),
                                        "x_display_unit": f.get("x_display_unit"), "y_display_unit": f.get("y_display_unit"),
                                        "invert_y": f.get("invert_y", False), "series_labels": {"y_f": f.get("display", "")},
                                        "draw": {"start": mech[0]["id"], "end": mech[-1]["id"] + ".end"}},
                    model, "simulation", ["formula evaluated with the node's parameters"])
    from .inputs import DomainPack
    dom = DomainPack(None)
    found = []
    for alias, key in dom.legend["lithology_aliases"].items():
        for m in re.finditer(rf"\b{re.escape(alias)}\w*", text):
            found.append((m.start(), key, m.group()))
    for key in dom.legend["lithology"]:
        for m in re.finditer(rf"\b{re.escape(key)}\w*", text):
            found.append((m.start(), key, m.group()))
    order = []
    for _, key, word in sorted(found):
        if key not in [k for k, _ in order]:
            order.append((key, word))
    if order:
        units = [{"name": w, "lith": k, "thickness": 1} for k, w in order[:4]]
        if len(units) == 2:
            units = units + [dict(units[0])]
        return ("cross_section", "B", {"units": units, "reveal": "bottom_up", "labels": True,
                                       "times": [mech[0]["id"]] * len(units)}, None, "schematic",
                ["layer order and thickness are schematic (lithologies named in the claims)"])
    return None


def node_terms(node):
    terms = list(node.get("data_meaning", {}).get("curves", []))
    if terms:                 # curves named by the author beat words guessed from text ('плотность раствора' != DEN)
        return list(dict.fromkeys(terms))
    txt = " ".join([node.get("title", ""), node.get("data_meaning", {}).get("text", "")] +
                   [c.get("text", "") for c in node.get("claims", [])])
    aliases = read_json(RES_DIR / "mnemonics.json", {})
    t = norm_text(txt)
    for mn, al in aliases.items():
        if mn.startswith("_"):
            continue
        if re.search(rf"\b{mn.lower()}\b", t) or any(a in t for a in al if len(a) > 3):
            terms.append(mn)
    return list(dict.fromkeys(terms))


# ============================================================================ rule-based shots + specs

def rule_shots_specs(script, node, catalog, fmt, style, lang, domain_visuals=None):
    T, _ = lang_pack(lang)
    tmap = read_json(RES_DIR / "template_map.json")
    lines = script["lines"]
    by_role = {}
    for l in lines:
        by_role.setdefault(l["role"], []).append(l)
    shots, specs, coverage = [], [], []
    mis = node.get("misconception") or {}
    terms = node_terms(node)
    curve_hits = match_curves(catalog, terms)

    def new_shot(line_ids, template, cls, params, model=None, prov=None, assumptions=(), exaggerations=(),
                 invariants=(), needs=None):
        sid = f"S{len(shots) + 1}"
        shots.append({"id": sid, "line_ids": line_ids, "template": template, "class": cls, "style": style,
                      "method": "render2d" if template not in ("ai_clip",) else "ai_clip",
                      "provenance": prov or CLASS_LABEL[cls], "first_frame_src": None, "last_frame_src": None,
                      "exaggerations": list(exaggerations)})
        specs.append({"shot_id": sid, "template": template, "class": cls, "params": params, "model": model,
                      "invariants": list(invariants), "assumptions": list(assumptions),
                      "provenance": prov or CLASS_LABEL[cls]})
        if needs:
            coverage.append({"shot": sid, **needs})
        return sid

    ids = lambda role: [l["id"] for l in by_role.get(role, [])]
    from .templates import REGISTRY as _REG

    def src_of(l):
        return next((x.get("claim_id") for x in l.get("sources", []) if x.get("claim_id")), None)

    def card_for(l):
        """Card that accompanies a line on an overlay_card (None: keep the previous card on screen)."""
        r = l["role"]
        if r == "hook":
            if l.get("myth") and mis.get("wrong"):
                return {"kind": "myth", "text": strip_end(mis["wrong"]) + "?", "at": 0.2}
            return {"kind": "text", "text": l["text"], "at": 0.2}
        if r == "prediction":
            pq = node.get("prediction_question")
            if isinstance(pq, dict) and pq.get("options"):
                opts = pq["options"]
            elif not pq and mis.get("wrong"):           # generic "is the myth true?" line
                opts = T["rule"]["options_myth"]
            else:
                opts = []
            return {"kind": "question", "text": l["text"], "at": l["id"], "options": opts}
        if r in ("reveal", "bridge") or len(l["text"]) <= 90:
            c = {"kind": "fact" if r == "reveal" else "text", "text": l["text"], "at": l["id"]}
            if src_of(l):
                c["source_ref"] = src_of(l)
            return c
        return None

    def overlay(line_objs, base_tpl, base_params, cls, model, prov, assumptions=(), needs=None):
        cards = [c for c in (card_for(l) for l in line_objs) if c]
        if not cards:
            return new_shot([l["id"] for l in line_objs], base_tpl, cls, base_params, model, prov=prov,
                            assumptions=assumptions, needs=needs)
        return new_shot([l["id"] for l in line_objs], "overlay_card", cls,
                        {"base": {"template": base_tpl, "params": base_params}, "cards": cards}, model, prov=prov,
                        assumptions=assumptions, needs=needs)

    mech = by_role.get("mechanism", [])
    intro = by_role.get("hook", []) + by_role.get("prediction", []) + by_role.get("reveal", [])
    vis = mechanism_visual(node, catalog, mech or intro, fmt, lang, domain_visuals) if (mech or intro) else None
    data_vis = None                                    # (template, class, params, model, prov) of the data shot
    if vis:
        # 1-3. hook, prediction, reveal and mechanism share ONE visual scene; myth/question/facts are cards
        #      beside it (overlay_card), so no line is spent on a full-screen text card.
        tpl_, cls_, params_, model_, prov_, ass_ = vis
        group = intro + mech
        if (model_ or {}).get("type") in ("las", "csv"):   # real data: the data lines continue the same scene
            dl = by_role.get("data", [])
            group += dl
            if dl:
                key = "motion" if tpl_ == "depth_track" else "draw"
                params_.setdefault(key, {})["end"] = dl[-1]["id"] + ".end"
                for l in dl:
                    l.setdefault("sources", []).append({"type": "dataset", "dataset": model_.get("dataset"),
                                                        "file": model_["file"].split("/")[-1],
                                                        "curve": model_.get("curve") or model_["y"][0]})
            data_vis = (tpl_, cls_, params_, model_, prov_)
        overlay(group, tpl_, params_, cls_, model_, prov_, ass_)
    else:
        # nothing visual is known for this node: cards, and the coverage report says what is missing
        hp = ids("hook") + ids("prediction")
        if hp:
            q = (strip_end(mis["wrong"]) + "?") if mis.get("wrong") else next(l["text"] for l in lines if l["id"] == hp[-1])
            new_shot(hp, "question_card", "T", {"question": q, "kind": "prediction", "timer": True,
                                                "myth": bool(mis.get("wrong")),
                                                "options": T["rule"]["options_myth"] if mis.get("wrong") else []},
                     prov="schematic")
        for l in by_role.get("reveal", []):
            new_shot([l["id"]], "misconception_card", "T",
                     {"wrong": strip_end(mis.get("wrong", "")) or "—", "right": l["text"], "reveal_at": "10%",
                      "right_ref": src_of(l)}, prov="schematic")
        if mech:
            steps = [{"title": l["text"], "source_ref": src_of(l)} for l in mech]
            new_shot([l["id"] for l in mech], "process_steps", "T",
                     {"steps": steps, "times": [l["id"] for l in mech]}, prov="schematic",
                     needs={"wanted_template": "visual for mechanism lines", "status": "needs_visual",
                            "reason": "no matching dataset curve, machine-readable formula, lithology terms, photo or "
                                      "domain-pack visual hint; the LLM planner (or node visual_hints) must supply one"})
    # 4. data lines not yet shown: real data if the catalog has it; otherwise the mechanism scene, finished,
    #    with the line as a card (and a coverage gap 'needs_data')
    csv_hit = match_csv_columns(catalog, node.get("data_meaning", {}).get("curves", []))
    covered_now = {i for sh_ in shots for i in sh_["line_ids"]}
    for l in by_role.get("data", []):
        if l["id"] in covered_now:
            continue
        if csv_hit and not curve_hits:
            e, col, well = csv_hit
            model = {"type": "csv", "file": e["file"], "x": e.get("time_column") or e["columns"][0], "y": [col],
                     "dataset": e.get("dataset")}
            if well:
                model["filter"] = {e["well_column"]: well}
            unit = (e.get("units") or {}).get(col, "")
            l.setdefault("sources", []).append({"type": "dataset", "dataset": e.get("dataset"),
                                                "file": e["file"].split("/")[-1], "curve": col})
            params = {"y": [f"y_{col}"], "y_label": f"{col}, {unit}".strip(", "), "dates": bool(e.get("time_column")),
                      "draw": {"start": l["id"], "end": l["id"] + ".end"},
                      "caption": f"{e.get('dataset', '')} · {well or ''} · {col}".strip(" ·")}
            new_shot([l["id"]], "data_chart", "A", params, model, prov="data",
                     assumptions=[f"series chosen automatically: {well or 'all rows'}, column {col}"])
            data_vis = ("data_chart", "A", params, model, "data")
            continue
        if curve_hits:
            h = sorted(curve_hits, key=lambda x: -(x["depth_max"] - x["depth_min"]))[0]
            length = 70 if fmt == "short" else 120
            win = best_depth_window(h["file"], h["curve"], length)
            layers, tops_e = tops_layers(catalog, h.get("well"), win)
            model = {"type": "las", "file": h["file"], "curve": h["curve"], "depth_from": win[0] - 2,
                     "depth_to": win[1] + 2, "dataset": h.get("dataset")}
            params = {"track": {"curve": h["curve"], "unit": h.get("unit", "")}, "window": win,
                      "layers": layers, "readout": True, "motion": {"start": l["id"]}}
            l.setdefault("sources", []).append({"type": "dataset", "dataset": h.get("dataset"),
                                                "file": h["file"].split("/")[-1], "curve": h["curve"]})
            new_shot([l["id"]], "depth_track", "A", params, model, prov="data",
                     assumptions=[f"depth window {win[0]:.0f}–{win[1]:.0f} m chosen automatically "
                                  "(max curve contrast); lithology of layers not shown (unknown)"],
                     invariants=["depth increases downward", "curve point depth == tool depth"])
            data_vis = ("depth_track", "A", params, model, "data")
        elif vis:
            tpl_, cls_, params_, model_, prov_, _ = vis
            new_shot([l["id"]], "overlay_card", cls_,
                     {"base": {"template": tpl_, "params": _REG[tpl_].settled_params(params_)},
                      "cards": [{"kind": "text", "text": l["text"], "at": l["id"], "source_ref": src_of(l)}]},
                     model_, prov=prov_,
                     needs={"wanted_template": "data_chart/depth_track", "status": "needs_data",
                            "reason": "no open dataset in the catalog matches the node's curves/terms; "
                                      "the line is shown over the mechanism scene"})
        else:
            new_shot([l["id"]], "text_panel", "T", {"title": T["bridge"], "text": l["text"], "icon": "db",
                                                     "chips": terms[:5]}, prov="schematic",
                     needs={"wanted_template": "data_chart/depth_track", "status": "needs_data",
                            "reason": "no open dataset in the catalog matches the node's curves/terms"})
    # 5. bridge: a card over the finished data (or mechanism) scene
    still = data_vis or (vis[:5] if vis else None)
    for l in by_role.get("bridge", []):
        if still:
            tpl_, cls_, params_, model_, prov_ = still
            new_shot([l["id"]], "overlay_card", cls_,
                     {"base": {"template": tpl_, "params": _REG[tpl_].settled_params(params_)},
                      "cards": [{"kind": "text", "label": T["roles"]["bridge"], "text": l["text"], "at": l["id"]}]},
                     model_, prov=prov_)
        else:
            new_shot([l["id"]], "text_panel", "T", {"title": T["roles"]["bridge"].capitalize(), "text": l["text"],
                                                     "icon": "db", "chips": terms[:5]}, prov="schematic")
    # 6. transfer: the one full-screen question card
    for l in by_role.get("transfer", []):
        new_shot([l["id"]], "question_card", "T", {"question": l["text"], "kind": "transfer", "timer": False},
                 prov="schematic")
    # any line not covered (e.g. outro) -> text panel
    covered = {i for s in shots for i in s["line_ids"]}
    for l in lines:
        if l["id"] not in covered:
            new_shot([l["id"]], "text_panel", "T", {"text": l["text"], "icon": "check"}, prov="schematic")
    order = {l["id"]: i for i, l in enumerate(lines)}
    pairs = sorted(zip(shots, specs), key=lambda p: order[p[0]["line_ids"][0]])
    shots, specs = [p[0] for p in pairs], [p[1] for p in pairs]
    for i, (s, sp) in enumerate(zip(shots, specs)):          # renumber in narrative order
        s["id"] = sp["shot_id"] = f"S{i + 1}"
    return {"shots": shots}, specs, coverage


# ============================================================================ validation (applies to ANY planner)

def validate_script(script, node, pages, fmt):
    errs, warns = [], []
    claims = {c["id"]: c for c in node.get("claims", [])}
    lines = script.get("lines") or []
    if not lines:
        errs.append("script has no lines")
    roles = [l.get("role") for l in lines]
    for r in ("hook", "prediction", "transfer"):
        if r not in roles:
            warns.append(f"no '{r}' line")
    for l in lines:
        if l.get("role") not in ROLES:
            warns.append(f"{l.get('id')}: unknown role {l.get('role')}")
        if not l.get("text"):
            errs.append(f"{l.get('id')}: empty text")
        if l.get("asserts_fact") and not l.get("sources"):
            errs.append(f"{l.get('id')}: states a fact without a source")
        for s in l.get("sources", []):
            if s.get("type", "claim") == "claim":
                cid = str(s.get("claim_id"))
                if cid not in claims and not s.get("quote"):
                    errs.append(f"{l['id']}: unknown claim_id {cid}")
                q = s.get("quote")
                if q and not quote_in_claims(q, node) and pages.available:
                    st = pages.find_quote(q, s.get("page"))["status"]
                    if st != "verified":
                        errs.append(f"{l['id']}: quote not found in node or chapter: «{q[:50]}…»")
        own = set()
        for s in l.get("sources", []):
            own |= set(numbers_in(str(s.get("quote") or "")))
            if s.get("claim_id") in claims:
                own |= set(numbers_in(claims[s["claim_id"]].get("quote") or ""))
                own |= set(numbers_in(claims[s["claim_id"]].get("text") or ""))
        for n in numbers_in(l.get("text", "")):
            if n not in own and not l.get("myth"):
                errs.append(f"{l['id']}: number {n} is not in this line's sources")
    total = sum(words(l.get("text", "")) for l in lines)
    lo, hi = FORMATS[fmt]["words"]
    if total > hi * 1.3:
        errs.append(f"script too long: {total} words (target {lo}-{hi})")
    elif not lo * 0.6 <= total <= hi * 1.15:
        warns.append(f"script length {total} words (target {lo}-{hi})")
    return errs, warns


def validate_shots(shotlist, specs, script, catalog_files, data_dirs):
    """Per-shot validation. Returns {shot_id: [errors]} and coverage gaps (needs_new_template)."""
    from .evaluator import check_expr, expr_symbols
    lines = {l["id"]: l for l in script["lines"]}
    bad, gaps = {}, []
    seen = []
    for sh, sp in zip(shotlist["shots"], specs):
        e = []
        tpl = REGISTRY.get(sp.get("template"))
        if tpl is None:
            gaps.append({"shot": sh["id"], "wanted_template": sp.get("template"), "status": "needs_new_template",
                         "reason": sp.get("needs_new_template") or "template not in library"})
            e.append(f"unknown template {sp.get('template')}")
        else:
            e += tpl().check_params(sp.get("params") or {}, sp.get("model") or None)
            if sh.get("class") not in tpl.classes:
                e.append(f"class {sh.get('class')} not allowed for {tpl.name} ({tpl.classes})")
        if sh.get("class") not in ("A", "B", "C", "D", "T"):
            e.append("class must be A|B|C|D|T")
        for lid in sh.get("line_ids", []):
            if lid not in lines:
                e.append(f"unknown line {lid}")
            elif sh.get("class") == "D" and lines[lid].get("asserts_fact"):
                e.append(f"class D shot carries factual line {lid}")
        seen += sh.get("line_ids", [])
        m = sp.get("model")
        if m:
            try:
                if m.get("type") == "formula":
                    names = set((m.get("params") or {}).keys()) | set((m.get("derived") or {}).keys()) | \
                            set((m.get("grid") or {}).keys())
                    for k, ex in (m.get("derived") or {}).items():
                        check_expr(ex, names)
                    check_expr(m["expr"], names)
                    for k, ex in (m.get("exprs") or {}).items():
                        check_expr(ex, names)
                    src = m.get("source") or {}
                    if not (src.get("quote") or src.get("claim_id") or src.get("assumption")):
                        e.append("formula without a source (page+quote, node claim_id, or explicit assumption)")
                elif m.get("type") in ("las", "csv"):
                    from .evaluator import _resolve
                    _resolve(m["file"], data_dirs)
            except Exception as ex:
                e.append(f"model: {ex}")
        if sp.get("needs_new_template"):
            gaps.append({"shot": sh["id"], "wanted_template": sp.get("needs_new_template"),
                         "status": "needs_new_template", "reason": "planner asked for a visual the library lacks"})
        if e:
            bad[sh["id"]] = e
    missing = [l for l in lines if l not in seen]
    if missing:
        bad["_lines"] = [f"lines not covered by any shot: {missing}"]
    # plan-level rules (estimated from word counts; QA re-checks on real durations)
    from .config import MAX_CARD_SHARE, VISUAL_ROLES
    wc = {lid: max(1, words(l.get("text", ""))) for lid, l in lines.items()}
    tot = sum(wc.values())
    card_w = sum(wc[i] for sh in shotlist["shots"] if sh.get("class") == "T" for i in sh.get("line_ids", []) if i in wc)
    plan_errs = []
    if tot and card_w / tot > MAX_CARD_SHARE + 0.05:
        plan_errs.append(f"text cards (class T) carry {card_w / tot:.0%} of the narration; keep them <= "
                         f"{MAX_CARD_SHARE:.0%} — put questions/facts on an overlay_card over a visual")
    for sh in shotlist["shots"]:
        if sh.get("class") == "T":
            for lid in sh.get("line_ids", []):
                if lid in lines and lines[lid].get("role") in VISUAL_ROLES:
                    plan_errs.append(f"{lid} ({lines[lid]['role']}) is on a text card {sh['id']}: give it a visual template")
    if plan_errs:
        bad["_plan"] = plan_errs
    return bad, gaps
