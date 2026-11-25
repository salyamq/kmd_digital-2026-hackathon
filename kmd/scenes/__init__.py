"""`kmd scenes CH [--node ID]`: layer + routing -> runs/<ch>/scenes/<node_id>.json (scene specs).

For every node routed to video or interactive, the LLM writes a scene spec (views of one world built
from catalog templates, frames with class/provenance/claim ids, invariants, assumptions,
exaggerations, physics self-check). Code then checks it: template params against each template's
schema and invariants (physics), frame references, claim ids, format rules. Errors go back to the
LLM once or twice (`scene_fix`); the final spec carries `checks` with what remained.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .. import llm
from ..config import chapter_config, domain_pack, read_json, run_dir, write_json

VIDEO_FORMATS = ("short", "long", "interactive")

FORMAT_RULES = {
    "short": ("шортс 9:16, 40–75 секунд, ОДИН когнитивный шаг и один механизм; 4–7 кадров, по 6–12 секунд; "
              "вертикальная компоновка (каротажный планшет вертикален и ложится в кадр естественно; разрезы и графики "
              "перекомпоновываются, а не сжимаются); без таблиц и формул."),
    "long": ("разбор 16:9, 1,5–3 минуты: решение на данных или процесс на нескольких масштабах; синхронные виды рядом "
             "(например разрез + кривые, или профиль давления + график во времени + вид сверху — из одной модели); "
             "6–12 кадров по 10–20 секунд."),
    "interactive": ("интерактив в курсе: 2–5 кадров-состояний, пользователь двигает параметр анимации шаблона; "
                    "спецификация нужна для паспорта и для анимации на странице шага."),
}
FRAMES_HINT = {"short": "4–7 кадров.", "long": "6–12 кадров.", "interactive": "2–5 кадров."}


# ------------------------------------------------------------------------------------------ inputs
def load_routing(rd: Path) -> dict:
    p = rd / "routing.json"
    if not p.exists():
        return {}
    r = read_json(p)
    if isinstance(r, dict):
        r = r.get("routing") or r.get("nodes") or list(r.values())
    return {x["node_id"]: x for x in r if isinstance(x, dict) and "node_id" in x}


def misconception_texts(pack: dict) -> list[str]:
    m = pack.get("misconceptions") or []
    if isinstance(m, dict):
        m = m.get("items") or []
    return [x.get("text", "") for x in m if isinstance(x, dict) and x.get("text")]


def conventions_text(sg: dict) -> str:
    conv = sg.get("conventions", {})
    lines = []
    for k, v in conv.items():
        if isinstance(v, dict) and v.get("name_ru"):
            lines.append(f"- {v['name_ru']}")
        elif isinstance(v, str):
            lines.append(f"- {v}")
    fl = sg.get("fluids", {})
    cols = ", ".join(f"{v['ru']} — {v['color']}" for k, v in fl.items() if isinstance(v, dict) and k in ("gas", "oil", "water"))
    if cols:
        lines.append(f"- Цвета флюидов: {cols}; {fl.get('density_order_note', '')}")
    lith = ", ".join(f"{k} = {v['ru']}" for k, v in sg.get("lithology", {}).items())
    if lith:
        lines.append(f"- Коды литологии для параметров lith: {lith}")
    return "\n".join(lines)


def slim_node(node: dict) -> dict:
    """Node without bookkeeping fields the scene does not need."""
    drop = {"unit_ids", "order_rationale", "inefficiency_lens", "links"}
    n = {k: v for k, v in node.items() if k not in drop}
    n["claims"] = [{k: c.get(k) for k in ("id", "kind", "text", "quote", "page")} for c in node.get("claims", [])]
    return n


# ------------------------------------------------------------------------------------------ checks
def check_scene(scene: dict, node: dict, fmt: str) -> tuple[list[str], list[str], dict]:
    """Return (errors, warnings, fixed_scene). Provenance/class are set from the template (code is the truth)."""
    from .. import visuals

    errors, warns = [], []
    sc = copy.deepcopy(scene)
    claim_ids = {c["id"] for c in node.get("claims", [])}
    views = sc.get("views", {})
    normalized = {}
    for name, v in views.items():
        try:
            tpl = visuals.get_template(v["template"])
        except KeyError as e:
            errors.append(f"вид «{name}»: {e}")
            continue
        v["template"] = tpl.name
        try:
            p = tpl.normalize(v["params"])
        except Exception as e:  # jsonschema.ValidationError
            errors.append(f"вид «{name}» ({tpl.name}): параметры не по схеме: {str(e).splitlines()[0][:300]}")
            continue
        normalized[name] = (tpl, p)
        for i in tpl.check(p):
            (errors if i.level == "error" else warns).append(f"вид «{name}» ({tpl.name}) [{i.code}]: {i.message}")
    frames = sc.get("frames", [])
    seen = set()
    for f in frames:
        if f["id"] in seen:
            errors.append(f"кадр {f['id']}: повторяющийся id")
        seen.add(f["id"])
        if f["view"] not in views:
            errors.append(f"кадр {f['id']}: вид «{f['view']}» не описан в views")
            continue
        bad = [c for c in f.get("claim_ids", []) if c not in claim_ids]
        if bad:
            errors.append(f"кадр {f['id']}: нет таких утверждений в узле: {bad}")
        t0, t1 = f["t"]
        if t0 > t1:
            warns.append(f"кадр {f['id']}: t идёт назад ({t0} → {t1})")
        if f["view"] in normalized:
            tpl, p = normalized[f["view"]]
            if f.get("params_override"):
                try:
                    p2 = tpl.normalize({**v_params(views, f["view"]), **f["params_override"]})
                    for i in tpl.check(p2):
                        if i.level == "error":
                            errors.append(f"кадр {f['id']} (params_override) [{i.code}]: {i.message}")
                    p = p2
                except Exception as e:
                    errors.append(f"кадр {f['id']}: params_override не по схеме: {str(e).splitlines()[0][:200]}")
            prov = tpl.provenance_for(p)
            if f.get("provenance") != prov:
                warns.append(f"кадр {f['id']}: метка «{f.get('provenance')}» заменена на «{prov}» (как сделан кадр)")
                f["provenance"] = prov
    n = len(frames)
    lim = {"short": (3, 8), "long": (5, 14), "interactive": (2, 6)}[fmt]
    if not (lim[0] <= n <= lim[1]):
        errors.append(f"формат {fmt}: кадров должно быть {lim[0]}–{lim[1]}, сейчас {n}")
    if not any(f.get("true_scale") for f in frames):
        warns.append("нет кадра в истинном масштабе (нужен хотя бы один в серии роликов)")
    used = {c for f in frames for c in f.get("claim_ids", [])}
    if not used:
        errors.append("ни один кадр не ссылается на утверждения узла")
    failed = [c["item"] for c in sc.get("checklist", []) if not c.get("ok")]
    for it in failed:
        warns.append(f"самопроверка: «{it}» — не выполнено (нужна оговорка в ролике)")
    sc["format"] = fmt
    sc["node_id"] = node["id"]
    return errors, warns, sc


def v_params(views: dict, name: str) -> dict:
    return dict(views[name]["params"])


# ------------------------------------------------------------------------------------------ stage
def build_scene(rd: Path, node: dict, route: dict, fmt: str, pack: dict, max_fix: int = 2) -> dict:
    """LLM scene spec + code checks (+ repair). May raise llm.PendingLLM."""
    from .. import visuals
    from ..visuals.style import styleguide

    cfg_lang = {"ru": "русский", "en": "английский", "kk": "казахский"}
    sg = styleguide(pack.get("pack", {}).get("id") or "geology")
    v = {
        "node": slim_node(node),
        "route": {"video_criteria": route.get("video_criteria") or [], "rationale": route.get("rationale") or "",
                  "scene_template": route.get("scene_template") or ""},
        "format": fmt,
        "format_rules": FORMAT_RULES[fmt],
        "frames_hint": FRAMES_HINT[fmt],
        "catalog": visuals.catalog_text(),
        "conventions": conventions_text(sg),
        "checklist": pack.get("physics_checklist") or "",
        "misconceptions": misconception_texts(pack),
        "course_language_name": cfg_lang.get(pack.get("pack", {}).get("language", "ru"), "русский"),
    }
    task = f"scene.{node['id']}.{fmt}"
    scene = llm.complete_json(rd, task, "scene_spec", v, schema="scene")
    errors, warns, fixed = check_scene(scene, node, fmt)
    attempt = 0
    while errors and attempt < max_fix:
        attempt += 1
        vf = {"node": slim_node(node), "catalog": v["catalog"], "scene": fixed, "errors": errors}
        scene = llm.complete_json(rd, f"{task}.fix{attempt}", "scene_fix", vf, schema="scene")
        errors, warns, fixed = check_scene(scene, node, fmt)
    fixed["checks"] = {"errors": errors, "warnings": warns, "fix_rounds": attempt,
                       "status": "ok" if not errors else "errors"}
    return fixed


def select_nodes(layer: dict, routing: dict, pack: dict) -> list[tuple[dict, dict, str]]:
    out = []
    types = (pack.get("difficulty_types") or {}).get("types", {})
    for n in layer["nodes"]:
        r = routing.get(n["id"])
        if r is None and not routing:
            tf = (types.get(n.get("difficulty", {}).get("primary"), {}) or {}).get("typical_formats") or []
            fmt = tf[0] if tf and tf[0] in VIDEO_FORMATS else None
            r = {"format": fmt} if fmt else None
        if r and r.get("format") in VIDEO_FORMATS:
            out.append((n, r, r["format"]))
    return out


def run(chapter: str, node: str | None = None, fmt: str | None = None, **kw) -> list[Path]:
    cfg = chapter_config(chapter)
    rd = run_dir(chapter)
    lp = rd / "layer.json"
    if not lp.exists():
        raise FileNotFoundError(f"{lp} not found: run `kmd layer {chapter}` first")
    layer = read_json(lp)
    pack = domain_pack(cfg.get("domain") or layer.get("domain") or "geology")
    routing = load_routing(rd)
    todo = select_nodes(layer, routing, pack)
    if node:
        nodes = {n["id"]: n for n in layer["nodes"]}
        if node not in nodes:
            raise KeyError(f"node {node} not in layer")
        hit = [t for t in todo if t[0]["id"] == node]
        r = hit[0][1] if hit else routing.get(node, {})
        f = fmt or (hit[0][2] if hit else "short")
        todo = [(nodes[node], r, f)]
    elif fmt:
        todo = [(n, r, fmt) for n, r, _ in todo]
    pending = []
    for n, r, f in todo:
        try:
            sc = build_scene(rd, n, r, f, pack)
        except llm.PendingLLM as p:
            pending.append(p.path)
            continue
        write_json(scene_path(rd, n["id"], f, r.get("format")), sc)
        st = sc["checks"]
        print(f"[scenes] {n['id']} ({f}): {st['status']}, {len(st['errors'])} errors, {len(st['warnings'])} warnings")
    return pending


def scene_path(rd: Path, node_id: str, fmt: str, routed_fmt: str | None) -> Path:
    """scenes/<node>.json for the routed format; scenes/<node>.<fmt>.json for any other requested format."""
    if routed_fmt in (None, fmt):
        return rd / "scenes" / f"{node_id}.json"
    return rd / "scenes" / f"{node_id}.{fmt}.json"


def load_scene(chapter: str, node_id: str, fmt: str | None = None) -> dict | None:
    rd = run_dir(chapter)
    for p in ([rd / "scenes" / f"{node_id}.{fmt}.json"] if fmt else []) + [rd / "scenes" / f"{node_id}.json"]:
        if p.exists():
            sc = read_json(p)
            if fmt is None or sc.get("format") == fmt:
                return sc
    return None


def dumps(scene: dict) -> str:
    return json.dumps(scene, ensure_ascii=False, indent=1)
