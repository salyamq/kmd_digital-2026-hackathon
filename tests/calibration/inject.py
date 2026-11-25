"""Seeded error injector for checker calibration (blind-ish: the reviewer does not see the key).

    python tests/calibration/inject.py CHAPTER --seed 7 --n 25 --out tests/calibration/<name>_pack --key tests/calibration/<name>_key.json

Takes true claims (text + verbatim quote + page) from runs/<CH>/layer.json, picks ~25 at random, and plants
errors of the TZ types into ~20–25 % of them with generic, rule-based edits of the claim text (the quote stays
the author's, as in a real draft). Also adds one script line (IT analogy without limit), one scene
(layer-order invariant) and two frames (one AI frame asserting facts, one clean). True-but-surprising items
are claims with negations/limits («не», «только», «нельзя»), kept unchanged.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

ANTONYMS = [("больше", "меньше"), ("выше", "ниже"), ("увеличива", "уменьша"), ("растёт", "падает"), ("растет", "падает"),
            ("повыш", "пониж"), ("максимальн", "минимальн"), ("тем глубже", "тем мельче"), ("усили", "ослаб")]
QUALIFIERS = [r"\bкак правило,?\s*", r"\bобычно\s+", r"\bчасто\s+", r"\bиногда\s+", r"\bможет\s+", r"\bмогут\s+", r"\bв ряде случаев\s+"]
CONDITION = re.compile(r",?\s*(?:если|при|когда|только при|лишь при|в случае)\s(?:[^.;]|\.(?=\d))*?(?=(?<!\d)\.(?!\d)|;|$)", re.I)
MEASURE = [(r"\bрассчитывают\b", "непосредственно измеряют прибором"), (r"\bвычисляют\b", "непосредственно измеряют"),
           (r"\bнаходят по\b", "прямо измеряют вместо расчёта по"), (r"\bоценивают\b", "прямо измеряют")]
SCALING = [(r"корень из времени|√\(κt\)|√t", "линейно со временем"), (r"квадрат\w*", "первой степени"),
           (r"экспоненциально", "линейно"), (r"логарифм\w*", "линейной функцией")]


def mutate(kind: str, text: str, rnd: random.Random) -> str | None:
    t = text
    if kind == "sign_flip":
        for a, b in rnd.sample(ANTONYMS, len(ANTONYMS)):
            for x, y in ((a, b), (b, a)):
                if x in t:
                    return t.replace(x, y, 1)
    if kind == "overgeneralization":
        for q in QUALIFIERS:
            if re.search(q, t, re.I):
                return re.sub(q, "всегда ", t, count=1, flags=re.I)
        if " — " in t or " это " in t:
            return "Всегда и для любых пород: " + t[0].lower() + t[1:]
    if kind == "lost_condition":
        m = CONDITION.search(t)
        if m and len(t) - len(m.group()) > 30:
            return (t[: m.start()] + t[m.end():]).strip()
    if kind == "wrong_number":
        nums = re.findall(r"(?<![\w.,])\d+(?:,\d+)?(?![\w])", t)
        nums = [n for n in nums if n not in ("1", "2", "3")]
        if nums:
            n = rnd.choice(nums)
            v = float(n.replace(",", "."))
            new = v * rnd.choice([3, 5, 10]) if v < 50 else v / rnd.choice([3, 5, 10])
            s = (f"{new:.1f}".rstrip("0").rstrip(".")).replace(".", ",")
            return t.replace(n, s, 1)
    if kind == "measured_vs_derived":
        for p, r in MEASURE:
            if re.search(p, t):
                return re.sub(p, r, t, count=1)
    if kind == "wrong_scaling_law":
        for p, r in SCALING:
            if re.search(p, t):
                return re.sub(p, r, t, count=1)
    if kind == "missing_caveat":
        for sep in (", но ", "; но ", ", однако ", " — но "):
            if sep in t:
                return t.split(sep)[0].rstrip(",;") + "."
    if kind == "outdated_as_current":
        if re.search(r"палетк|графическ|вручную|бланк", t, re.I):
            return t.rstrip(".") + " — так это делается и сегодня в любой программе интерпретации."
    return None


def build(chapter: str, seed: int, n: int, rate: float):
    rnd = random.Random(seed)
    layer = json.loads(Path(f"runs/{chapter}/layer.json").read_text(encoding="utf-8"))
    claims = [c for nd in layer["nodes"] for c in nd["claims"] if len(c["text"]) > 40]
    rnd.shuffle(claims)
    picked = claims[:n]
    n_err = max(1, round(rate * (n + 4)))  # +4 for script/scene/frames
    kinds = ["sign_flip", "overgeneralization", "lost_condition", "wrong_number", "measured_vs_derived",
             "wrong_scaling_law", "missing_caveat", "outdated_as_current"]
    items, key = [], {}
    budget = n_err - 2  # two non-claim errors below (scene, frame)
    order = rnd.sample(kinds, len(kinds))
    used = set()
    for kind in order:
        if budget <= 0:
            break
        for c in picked:
            if c["id"] in used:
                continue
            new = mutate(kind, c["text"], rnd)
            if new and new != c["text"]:
                used.add(c["id"])
                key[c["id"]] = {"type": kind, "orig": c["text"], "fix": c["text"], "page": c["page"]}
                c["_text"] = new
                budget -= 1
                break
    for i, c in enumerate(picked):
        iid = f"v{i + 1:02d}"
        items.append({"id": iid, "text": c.get("_text", c["text"]), "quote": c["quote"], "page": c["page"]})
        k = key.pop(c["id"], None)
        key[iid] = k
        if k is None and re.search(r"\bне\b|только|нельзя|лишь", c["text"]):
            key[iid] = None  # true-but-surprising candidate
    pkg = {"package_id": f"inject_{chapter}_s{seed}", "chapter": chapter, "team": "synthetic (seeded injector)",
           "claims": items,
           "scripts": [{"id": "s1", "lines": [
               {"id": "s1.l1", "text": "Выделить коллектор по кривой — это как найти выброс в метриках сервера: всё выше порога и есть то, что ищем.", "claim_ids": []},
               {"id": "s1.l2", "text": "Дальше разберём, по каким признакам специалист отличает пласт-коллектор от неколлектора.", "claim_ids": []}]}],
           "scenes": [{"id": "sc1", "template": "cross_section", "objects": ["пласт-коллектор", "глина", "скважина"],
                       "invariants": ["более молодые слои располагаются под более древними", "глубина растёт вниз"],
                       "assumptions": ["пласт однородный"], "exaggerations": [{"what": "вертикальный масштаб", "factor": 20}]}],
           "frames": [{"id": "f1", "class": "C", "provenance": "иллюстрация ИИ", "description": "сгенерированная каротажная диаграмма с подписями кривых СП и сопротивления"},
                      {"id": "f2", "class": "B", "provenance": "симуляция", "description": "расчётная зона проникновения вокруг скважины, вертикальное преувеличение подписано «×20»"}]}
    key.update({"s1.l1": {"type": "it_analogy_without_limit", "fix": "назвать, где аналогия ломается"}, "s1.l2": None,
                "sc1": {"type": "frame_error", "fix": "молодые слои лежат на более древних"},
                "f1": {"type": "frame_error", "fix": "диаграмму делать кодом (класс A)"}, "f2": None})
    return pkg, key


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--rate", type=float, default=0.23)
    ap.add_argument("--out", required=True)
    ap.add_argument("--key", required=True)
    a = ap.parse_args()
    pkg, key = build(a.chapter, a.seed, a.n, a.rate)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    Path(a.out, "package.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(a.key).write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(key)} items, {sum(1 for v in key.values() if v)} errors -> {a.out}, key {a.key}")
