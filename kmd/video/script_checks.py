"""Code checks of a video script (the «for the ear» rules of the TZ)."""
from __future__ import annotations

import re

GREEK = re.compile(r"[α-ωΑ-Ω]")
FORMULA = re.compile(r"[=<>^_\\/*+]|\$")
DIGIT = re.compile(r"\d")
LATIN = re.compile(r"[A-Za-z]")
ASSUME = re.compile(r"для примера|условн|допусти|предполож|возьм[её]м для|в модели", re.I)


def words(s: str) -> list[str]:
    return re.findall(r"[\wёЁ\u0301-]+", s)


def check_script(script: dict, scene: dict, node: dict, fmt: str, entries: list[dict]) -> tuple[list[str], list[str]]:
    errors, warns = [], []
    ph = script.get("phrases", [])
    frames = {f["id"] for f in scene.get("frames", [])}
    claims = {c["id"] for c in node.get("claims", [])}
    ids = [p["id"] for p in ph]
    if len(set(ids)) != len(ids):
        errors.append("повторяющиеся id фраз")
    if not ph:
        return ["нет фраз"], warns
    if ph[0]["role"] != "hook":
        errors.append("первая фраза должна быть крючком (role=hook): вопрос или парадокс, не определение")
    if len(words(ph[0]["text"])) > 16:
        errors.append("крючок длиннее 16 слов — не уложится в первые 3–4 секунды")
    roles = [p["role"] for p in ph]
    if "transfer" not in roles[-3:]:
        errors.append("в конце нужен вопрос на перенос (role=transfer среди последних фраз)")
    for p in ph:
        n = len(words(p["text"]))
        if n > 18:
            errors.append(f"{p['id']}: {n} слов в фразе (максимум 18)")
        cw = len(words(p["caption"]))
        if cw > 8:
            errors.append(f"{p['id']}: подпись на экране {cw} слов (максимум 7–8)")
        if GREEK.search(p["caption"]) or FORMULA.search(p["caption"]):
            errors.append(f"{p['id']}: в подписи формула или греческая буква: «{p['caption']}»")
        if DIGIT.search(p["text"]):
            errors.append(f"{p['id']}: числа в закадровом тексте нужно писать словами: «{p['text']}»")
        if GREEK.search(p["text"]):
            errors.append(f"{p['id']}: греческая буква в закадровом тексте (читать словами)")
        if p["frame_id"] not in frames:
            errors.append(f"{p['id']}: кадра {p['frame_id']} нет в спецификации сцены")
        bad = [c for c in p.get("claim_ids", []) if c not in claims]
        if bad:
            errors.append(f"{p['id']}: нет таких утверждений в узле: {bad}")
        if p["kind"] == "assumption" and not p.get("claim_ids"):
            if not ASSUME.search(p["text"]):
                errors.append(f"{p['id']}: допущение модели без claim_ids должно звучать как допущение "
                              f"(«для примера», «условно», «допустим»)")
        elif p["kind"] in ("observation", "inference") and not p.get("claim_ids") and p["role"] not in ("hook", "transfer", "final"):
            errors.append(f"{p['id']}: фраза-утверждение без claim_ids (голос не говорит больше источника)")
        if p["kind"] == "analogy" and "аналог" not in p["text"].lower() and "как будто" not in p["text"].lower() \
                and "похож" not in p["text"].lower() and "словно" not in p["text"].lower():
            warns.append(f"{p['id']}: аналогию стоит назвать аналогией в тексте")
    pr = script.get("prediction", {})
    if pr.get("question_phrase_id") not in ids or pr.get("answer_phrase_id") not in ids:
        errors.append("prediction: ссылки на несуществующие фразы")
    elif ids.index(pr["question_phrase_id"]) >= ids.index(pr["answer_phrase_id"]):
        errors.append("prediction: ответ должен идти после вопроса")
    else:
        q = ph[ids.index(pr["question_phrase_id"])]
        if "?" not in q["text"]:
            errors.append("prediction: фраза-вопрос должна быть вопросом")
    # frame order: frames should appear in the scene order (continuous world, no chaotic cuts)
    order = [f["id"] for f in scene.get("frames", [])]
    seq = []
    for p in ph:
        if not seq or seq[-1] != p["frame_id"]:
            seq.append(p["frame_id"])
    if len(seq) != len(set(seq)):
        warns.append("кадры возвращаются назад — проверить, что мир не «скачет»")
    unused = [f for f in order if f not in seq]
    if unused:
        warns.append(f"кадры сцены без закадрового текста: {unused}")
    # abbreviations expanded at first mention
    abbr = [e for e in entries if e.get("kind") == "abbr" and e.get("expansion")]
    full = " ".join(p["text"] for p in ph)
    for e in abbr:
        pat = r"(?<![\w])" + re.escape(e["term"]) + r"(?![\w])"
        m = [i for i, p in enumerate(ph) if re.search(pat, p["text"])]
        if not m:
            continue
        i = m[0]
        ctx = " ".join(p["text"] for p in ph[max(0, i - 1): i + 2]).lower()
        key = [w for w in re.findall(r"[а-яё]{5,}", e["expansion"].lower())][:2]
        if key and not all(k[:6] in ctx for k in key):
            warns.append(f"аббревиатура {e['term']} не раскрыта при первом упоминании ({e['expansion']})")
    if fmt == "short":
        nw = len(words(full))
        if nw > 175:
            errors.append(f"шортс: {nw} слов — при темпе 110–150 слов/мин это дольше 75 секунд")
        if nw < 80:
            warns.append(f"шортс: всего {nw} слов — короче 40 секунд")
    else:
        nw = len(words(full))
        if nw > 420:
            errors.append(f"разбор: {nw} слов — дольше 3 минут")
        if nw < 180:
            errors.append(f"разбор: {nw} слов — короче 1,5 минуты")
    return errors, warns
