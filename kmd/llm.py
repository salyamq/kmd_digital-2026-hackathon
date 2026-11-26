"""LLM access for every stage. Provider-agnostic, cached, schema-validated.

Providers (env KMD_LLM_PROVIDER, or auto-detected):
  anthropic  - ANTHROPIC_API_KEY, model KMD_LLM_MODEL (set explicitly)
  openai     - OPENAI_API_KEY (+ OPENAI_BASE_URL for OpenRouter / vLLM / Ollama), model KMD_LLM_MODEL
  queue      - no API: requests are written to runs/<ch>/llm/pending/ and answered by a worker
               (`kmd llm answer`). Used for the dev runs of this repo (Claude Opus 5.5 agents).

Every response is cached under runs/<ch>/llm/<task>/<key>.json, so re-runs and rebuilds are free
and reproducible; the jury can replay a run without any API key.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import jinja2
import jsonschema

from .config import PROMPTS, SCHEMAS, load_env, read_json, write_json


class PendingLLM(Exception):
    """Raised by the queue provider: the request was written to disk and awaits an answer."""

    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


class LLMError(Exception):
    pass


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(PROMPTS)),
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
)
_env.filters["tojson_ru"] = lambda o, indent=None: json.dumps(o, ensure_ascii=False, indent=indent)


def load_schema(name: str | dict | None) -> dict | None:
    if name is None or isinstance(name, dict):
        return name
    return read_json(SCHEMAS / (name if name.endswith(".json") else f"{name}.schema.json"))


def render(prompt: str, variables: dict) -> tuple[str, str, str]:
    """Return (system, user, template_source)."""
    src_path = PROMPTS / f"{prompt}.md"
    src = src_path.read_text(encoding="utf-8")
    text = _env.get_template(f"{prompt}.md").render(**variables)
    m = re.split(r"^---(system|user)---\s*$", text, flags=re.M)
    parts = {}
    for i in range(1, len(m) - 1, 2):
        parts[m[i]] = m[i + 1].strip()
    if "user" not in parts:
        parts = {"system": "", "user": text.strip()}
    return parts.get("system", ""), parts["user"], src


def provider_name() -> str:
    load_env()
    p = os.environ.get("KMD_LLM_PROVIDER")
    if p:
        return p
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "queue"


def _schema_instruction(schema: dict | None) -> str:
    if not schema:
        return "\n\nОтвет — только JSON, без пояснений и без ```."
    return (
        "\n\nОтвет — только один JSON-объект, валидный по этой JSON Schema, без пояснений и без ```:\n"
        + json.dumps(schema, ensure_ascii=False)
    )


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            return json.loads(text[i : j + 1])
        raise


def validate(obj, schema: dict | None) -> None:
    if schema:
        jsonschema.validate(obj, schema)


def _b64(path: str) -> tuple[str, str]:
    import base64
    import mimetypes

    mime = mimetypes.guess_type(path)[0] or "image/png"
    return mime, base64.b64encode(Path(path).read_bytes()).decode()


def _call_anthropic(system: str, user: str, max_tokens: int, images=()) -> tuple[str, dict, str]:
    import anthropic

    model = os.environ.get("KMD_LLM_MODEL", "claude-opus-4-5")
    client = anthropic.Anthropic()
    content = []
    for im in images:
        mime, data = _b64(im)
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
    content.append({"type": "text", "text": user})
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}]
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
    return text, usage, model


def _call_openai(system: str, user: str, max_tokens: int, images=()) -> tuple[str, dict, str]:
    import openai

    model = os.environ.get("KMD_LLM_MODEL", "gpt-4.1")
    if images and os.environ.get("KMD_LLM_VISION_MODEL"):
        # text-only main model (e.g. a free one): requests with images go to a vision model
        model = os.environ["KMD_LLM_VISION_MODEL"]
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    options = {}
    if base_url and urlsplit(base_url).hostname == "openrouter.ai":
        default = "off" if model.startswith("deepseek/deepseek-v4") else "default"
        reasoning = os.environ.get("KMD_OPENROUTER_REASONING", default)
        if reasoning not in ("off", "default"):
            raise LLMError("KMD_OPENROUTER_REASONING must be 'off' or 'default'")
        if reasoning == "off":
            options["extra_body"] = {
                "reasoning": {"enabled": False},
                "provider": {"require_parameters": True},
            }
    client = openai.OpenAI(base_url=base_url)
    content = [{"type": "text", "text": user}]
    for im in images:
        mime, data = _b64(im)
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    r = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content if images else user}],
        **options,
    )
    choice = r.choices[0] if r.choices else None
    text = (choice.message.content or "") if choice else ""
    u = r.usage
    usage = {"input_tokens": getattr(u, "prompt_tokens", 0), "output_tokens": getattr(u, "completion_tokens", 0)}
    usage["finish_reason"] = getattr(choice, "finish_reason", None)
    extra = getattr(u, "model_extra", None) or {}
    cost = getattr(u, "cost", None)
    if not isinstance(cost, (int, float)):
        cost = extra.get("cost")
    if isinstance(cost, (int, float)):
        usage["cost_usd"] = cost
    return text, usage, model


def _call_with_retry(call, system, user, max_tokens, images, tries=None):
    """Retry transport failures: HTTP 429/5xx, dropped connections, a malformed gateway body
    (free OpenRouter endpoints sometimes return a truncated/non-JSON body), an empty answer.
    Schema/JSON problems in a well-formed answer are handled by the caller's re-ask loop."""
    tries = tries or int(os.environ.get("KMD_LLM_RETRIES", "6"))
    delay = 10.0
    for i in range(tries):
        try:
            text, usage, model = call(system, user, max_tokens, images)
            if text.strip() or usage.get("finish_reason") == "length":
                return text, usage, model
            err = f"empty answer (finish_reason={usage.get('finish_reason')})"
        except Exception as e:  # noqa: BLE001 - provider SDKs raise many types
            status = getattr(e, "status_code", None)
            if status is not None and status < 500 and status not in (408, 409, 429):
                raise
            err = f"{type(e).__name__}: {str(e)[:200]}"
        if i == tries - 1:
            raise LLMError(f"LLM call failed after {tries} tries: {err}")
        print(f"[llm] retry {i + 1}/{tries - 1} in {delay:.0f}s: {err}", file=sys.stderr, flush=True)
        time.sleep(delay)
        delay = min(delay * 2, 120.0)


def complete_json(
    run_dir: Path,
    task: str,
    prompt: str,
    variables: dict,
    schema: str | dict | None = None,
    max_tokens: int = 32000,
    attempts: int = 3,
    images: list | tuple = (),
):
    """Render prompt, return parsed+validated JSON. Cached. May raise PendingLLM (queue).

    `images`: paths of images (e.g. page scans / figure crops) sent with the user message to a
    vision model. They enter the cache key by content hash. In queue mode their absolute paths are
    listed in the request (`images`) and the worker must look at them.
    """
    schema_d = load_schema(schema)
    system, user, src = render(prompt, variables)
    user_full = user + _schema_instruction(schema_d)
    images = [str(Path(i).resolve()) for i in images]
    img_hashes = [hashlib.sha256(Path(i).read_bytes()).hexdigest()[:16] for i in images]
    key_parts = [prompt, src, system, user_full] + ([img_hashes] if images else [])
    key = hashlib.sha256(json.dumps(key_parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:20]
    task_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", task)
    cache = Path(run_dir) / "llm" / task_slug / f"{key}.json"
    if cache.exists():
        return read_json(cache)["response"]

    prov = provider_name()
    request = {
        "task": task,
        "key": key,
        "prompt": prompt,
        "system": system,
        "user": user_full,
        "schema": schema_d,
        "images": images,
        "cache_path": str(cache.relative_to(Path(run_dir).parent.parent)) if Path(run_dir).is_absolute() else str(cache),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if prov == "queue":
        pend = Path(run_dir) / "llm" / "pending" / f"{task_slug}__{key}.json"
        if not pend.exists():
            write_json(pend, request)
        raise PendingLLM(pend)

    call = {"anthropic": _call_anthropic, "openai": _call_openai}.get(prov)
    if not call:
        raise LLMError(f"unknown provider {prov}")
    last_err = None
    msgs_user = user_full
    for _ in range(attempts):
        text, usage, model = _call_with_retry(call, system, msgs_user, max_tokens, images)
        try:
            obj = _extract_json(text)
            validate(obj, schema_d)
        except (json.JSONDecodeError, jsonschema.ValidationError) as e:
            last_err = str(e)
            if usage.get("finish_reason") == "length":
                last_err = f"ответ оборвался на лимите {max_tokens} токенов: {last_err}"
            msgs_user = (user_full + f"\n\nПредыдущий ответ не прошёл проверку: {last_err[:1200]}"
                         "\nВерни один полный JSON. Сохрани покрытие и цитаты, сокращай пояснения.")
            continue
        write_json(cache, {"request": request, "response": obj, "provider": prov, "model": model, "usage": usage})
        return obj
    raise LLMError(f"{task}: invalid JSON after {attempts} attempts: {last_err}")


def answer_pending(pending_file: Path, response_file: Path, model: str = "claude-opus-5.5 (agent queue)") -> Path:
    """Validate a worker's answer to a queued request and move it into the cache."""
    from .config import ROOT

    req = read_json(pending_file)
    raw = Path(response_file).read_text(encoding="utf-8")
    obj = _extract_json(raw)
    validate(obj, req.get("schema"))
    cache = Path(req["cache_path"])
    if not cache.is_absolute():
        cache = ROOT / cache
    usage = {"input_chars": len(req["system"]) + len(req["user"]), "output_chars": len(raw)}
    write_json(cache, {"request": req, "response": obj, "provider": "queue", "model": model, "usage": usage})
    Path(pending_file).unlink()
    return cache


def parallelism() -> int:
    """How many independent LLM requests a stage may run at once (KMD_LLM_PARALLEL, default 4).
    The queue provider answers instantly (PendingLLM), so it stays sequential."""
    if provider_name() == "queue":
        return 1
    return max(1, int(os.environ.get("KMD_LLM_PARALLEL", "4")))


def pmap(fn, items):
    """Apply fn to items, concurrently for API providers. Returns a list in input order of
    ("ok", result) or ("pending", path). Other exceptions propagate (first one in input order)."""
    items = list(items)

    def one(x):
        try:
            return ("ok", fn(x))
        except PendingLLM as p:
            return ("pending", p.path)

    n = min(parallelism(), len(items))
    if n <= 1:
        return [one(x) for x in items]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(one, x) for x in items]
        return [f.result() for f in futures]


def gather(calls):
    """Run zero-arg callables; collect results and pending requests instead of stopping at the first.

    Returns (results, pending_paths). results[i] is None where pending.
    """
    results, pending = [], []
    for kind, val in pmap(lambda c: c(), calls):
        if kind == "pending":
            results.append(None)
            pending.append(val)
        else:
            results.append(val)
    return results, pending
