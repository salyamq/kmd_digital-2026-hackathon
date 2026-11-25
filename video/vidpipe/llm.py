"""LLM adapter + LLM planner (node -> script -> shots/specs). Swappable provider, logged calls, JSON-only output.

Providers (env or CLI):
  anthropic     ANTHROPIC_API_KEY, model via VIDPIPE_LLM_MODEL (e.g. claude-sonnet-4-5)
  openai        OPENAI_API_KEY + VIDPIPE_LLM_BASE_URL (OpenAI, OpenRouter, vLLM, LM Studio, Ollama: http://localhost:11434/v1)
  replay        responses read from a cache dir (<stage>.json) — for exact rebuilds and offline demos
  kmd           the product pipeline's LLM layer (kmd/llm.py): any configured provider OR the file queue
                (no API key), cached under runs/<chapter>/llm/. Needs KMD_VIDPIPE_RUN_DIR (set by kmd/video/vidpipe.py).
                A queued request raises kmd.llm.PendingLLM, which must propagate (never fall back to rules).
Prices for the cost log: VIDPIPE_LLM_PRICE_IN / VIDPIPE_LLM_PRICE_OUT (USD per 1M tokens), else cost = null.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from .util import RES_DIR, log, log_external_call, write_json, read_json


class LLMError(RuntimeError):
    pass


def detect_provider():
    if os.environ.get("VIDPIPE_LLM_PROVIDER"):
        return os.environ["VIDPIPE_LLM_PROVIDER"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("VIDPIPE_LLM_BASE_URL"):
        return "openai"
    return None


def _extract_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            return json.loads(m.group())
        raise


class LLM:
    def __init__(self, provider, model=None, base_url=None, cache_dir=None, video_dir=None):
        self.provider = provider
        self.model = model or os.environ.get("VIDPIPE_LLM_MODEL") or \
            {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4.1"}.get(provider, "replay-cache")
        self.base_url = (base_url or os.environ.get("VIDPIPE_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.video_dir = Path(video_dir) if video_dir else None

    def _post(self, url, headers, body, timeout=300):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def complete(self, stage, system, user, max_tokens=12000):
        t0 = time.time()
        usage = {}
        if self.provider == "replay":
            p = self.cache_dir / f"{stage}.json"
            if not p.exists():
                raise LLMError(f"replay cache missing: {p}")
            text = p.read_text(encoding="utf-8")
        elif self.provider == "kmd":
            from kmd import llm as kmd_llm  # only available inside the product repo
            run_dir = Path(os.environ["KMD_VIDPIPE_RUN_DIR"])
            task = f"vidpipe.{os.environ.get('KMD_VIDPIPE_TASK', 'video')}.{stage}"
            obj = kmd_llm.complete_json(run_dir, task, "vidpipe_raw", {"system": system, "user": user},
                                        schema=None, max_tokens=max_tokens, attempts=1)
            text = json.dumps(obj, ensure_ascii=False)
        elif self.provider == "anthropic":
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise LLMError("ANTHROPIC_API_KEY not set")
            r = self._post("https://api.anthropic.com/v1/messages",
                           {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                           {"model": self.model, "max_tokens": max_tokens, "system": system, "temperature": 0.2,
                            "messages": [{"role": "user", "content": user}]})
            text = "".join(b.get("text", "") for b in r.get("content", []))
            usage = {"in": r.get("usage", {}).get("input_tokens"), "out": r.get("usage", {}).get("output_tokens")}
        elif self.provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "none")
            body = {"model": self.model, "temperature": 0.2, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if os.environ.get("VIDPIPE_LLM_JSON_MODE", "1") == "1":
                body["response_format"] = {"type": "json_object"}
            r = self._post(self.base_url + "/chat/completions",
                           {"Authorization": f"Bearer {key}", "content-type": "application/json"}, body)
            text = r["choices"][0]["message"]["content"]
            usage = {"in": r.get("usage", {}).get("prompt_tokens"), "out": r.get("usage", {}).get("completion_tokens")}
        else:
            raise LLMError(f"unknown provider {self.provider}")
        wall = round(time.time() - t0, 2)
        cost = 0.0 if self.provider == "replay" else None
        pi, po = os.environ.get("VIDPIPE_LLM_PRICE_IN"), os.environ.get("VIDPIPE_LLM_PRICE_OUT")
        if pi and po and usage.get("in") is not None:
            cost = round(usage["in"] / 1e6 * float(pi) + usage["out"] / 1e6 * float(po), 5)
        if self.video_dir:
            (self.video_dir / "llm").mkdir(parents=True, exist_ok=True)
            (self.video_dir / "llm" / f"{stage}_{int(t0)}.txt").write_text(text, encoding="utf-8")
            log_external_call(self.video_dir, kind="llm", provider=self.provider, model=self.model, stage=stage,
                              tokens_in=usage.get("in"), tokens_out=usage.get("out"), cost_usd=cost, wall_s=wall)
        return text

    def complete_json(self, stage, system, user, validate=None, retries=2):
        """Ask for JSON; if validate(obj) returns errors, send them back and retry."""
        msg = user
        last_err = None
        for attempt in range(retries + 1):
            text = self.complete(stage if attempt == 0 else f"{stage}_retry{attempt}", system, msg) \
                if self.provider != "replay" else self.complete(stage, system, msg)
            try:
                obj = _extract_json(text)
            except Exception as e:
                last_err = [f"invalid JSON: {e}"]
                obj = None
            if obj is not None:
                errs = validate(obj) if validate else []
                if not errs:
                    return obj, []
                last_err = errs
            if self.provider == "replay":
                break
            msg = user + "\n\nYOUR PREVIOUS ANSWER HAD THESE PROBLEMS — FIX ALL OF THEM AND ANSWER WITH JSON ONLY:\n- " + \
                "\n- ".join(last_err[:30])
        return obj, last_err or []


def load_prompt(name):
    return (RES_DIR / "prompts" / name).read_text(encoding="utf-8")


def compact_catalog(catalog):
    out = []
    for e in catalog:
        d = {k: e.get(k) for k in ("type", "kind", "dataset", "well", "description", "license") if e.get(k)}
        d["file"] = Path(e["file"]).name
        if e.get("curves"):
            d["curves"] = [{"mnemonic": c["mnemonic"], "unit": c["unit"],
                            "depth": [round(c["depth_min"]), round(c["depth_max"])]} for c in e["curves"]]
        if e.get("columns"):
            d["columns"] = e["columns"][:40]
        if e.get("units"):
            d["units"] = e["units"]
        out.append(d)
    return out


def llm_script(llm, node, pages, fmt, lang, domain):
    from .config import FORMATS
    from .planner import validate_script
    system = load_prompt("script_system.md").format(lang=lang)
    F = FORMATS[fmt]
    user = load_prompt("script_user.md").format(
        lang=lang, fmt=fmt, words_lo=F["words"][0], words_hi=F["words"][1],
        node=json.dumps({k: v for k, v in node.items() if k != "raw"}, ensure_ascii=False, indent=1)[:20000],
        pages=pages.excerpt(14000) if pages.available else "(chapter pages not provided)",
        glossary=json.dumps(domain.glossary[:60], ensure_ascii=False)[:4000],
        misconceptions=json.dumps(domain.misconceptions[:20], ensure_ascii=False)[:3000])

    def val(obj):
        errs, _ = validate_script(obj, node, pages, fmt)
        return errs
    obj, errs = llm.complete_json("script", system, user, validate=val)
    if obj:
        obj["planner"] = f"llm:{llm.provider}:{llm.model}"
    return obj, errs


def llm_shots(llm, script, node, pages, catalog, fmt, style, lang, domain, data_dirs):
    from .planner import validate_shots
    from .templates import catalog as tcat
    system = load_prompt("shots_system.md").format(
        lithologies=", ".join(domain.legend["lithology"].keys()), fluids=", ".join(domain.legend["fluids"].keys()))
    user = load_prompt("shots_user.md").format(
        lang=lang, fmt=fmt, style=style,
        script=json.dumps(script, ensure_ascii=False, indent=1)[:16000],
        node=json.dumps({k: v for k, v in node.items() if k != "raw"}, ensure_ascii=False)[:12000],
        pages=pages.excerpt(10000) if pages.available else "(chapter pages not provided)",
        templates=json.dumps(tcat(), ensure_ascii=False)[:24000],
        datasets=json.dumps(compact_catalog(catalog), ensure_ascii=False)[:8000])

    def split(obj):
        shots = obj.get("shots", [])
        sl = {"shots": [{k: v for k, v in s.items() if k not in ("params", "model", "invariants", "assumptions")}
                        for s in shots]}
        specs = [{"shot_id": s["id"], "template": s.get("template"), "class": s.get("class"),
                  "params": s.get("params") or {}, "model": s.get("model"), "invariants": s.get("invariants", []),
                  "assumptions": s.get("assumptions", []), "provenance": s.get("provenance"),
                  "needs_new_template": s.get("needs_new_template")} for s in shots]
        return sl, specs

    def val(obj):
        try:
            sl, specs = split(obj)
        except Exception as e:
            return [f"bad structure: {e}"]
        bad, _ = validate_shots(sl, specs, script, None, data_dirs)
        # unknown templates are coverage gaps, not retry reasons
        return [f"{k}: {v}" for k, vs in bad.items() for v in vs if "unknown template" not in v]
    obj, errs = llm.complete_json("shots", system, user, validate=val)
    if not obj:
        return None, None, errs
    sl, specs = split(obj)
    return sl, specs, errs
