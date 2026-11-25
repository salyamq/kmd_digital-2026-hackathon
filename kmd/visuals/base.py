"""Template base class, registry, invariant issues.

A template = parametric scene/illustration generator keyed by a difficulty pattern:
  * `params_schema`  JSON schema of the parameters (goes into LLM prompts via `catalog()`),
  * `check(params)`  invariant checks (physics/domain checklist) -> list[Issue],
  * `state(params,t)` ONE state model: everything drawn at time t is computed from it,
  * `draw(fig, rect, params, t, ctx)` draws into a figure region (used both for
    illustrations and for video frames, so a frame and an illustration never diverge),
  * `describe(params)` default alt text (Russian).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import jsonschema

REGISTRY: dict[str, "Template"] = {}


@dataclass
class Issue:
    level: str  # "error" | "warning"
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


class InvariantError(ValueError):
    def __init__(self, template: str, issues: list[Issue]):
        self.template = template
        self.issues = issues
        msg = "; ".join(f"[{i.code}] {i.message}" for i in issues if i.level == "error")
        super().__init__(f"{template}: invariant check failed: {msg}")


@dataclass
class DrawCtx:
    sg: dict
    dpi: float = 100.0
    base_px: float = 15.0        # body font size in output pixels
    mode: str = "illustration"   # "illustration" | "video"
    fig_px: tuple = (1200, 750)
    extra: dict = field(default_factory=dict)

    def pt(self, scale: float = 1.0) -> float:
        return self.base_px * scale * 72.0 / self.dpi


def apply_defaults(schema: dict, value):
    """Fill `default`s from a JSON schema (objects, nested objects, arrays of objects)."""
    if not isinstance(schema, dict):
        return value
    t = schema.get("type")
    if t == "object" and isinstance(value, dict):
        out = dict(value)
        for k, sub in (schema.get("properties") or {}).items():
            if k not in out and "default" in sub:
                out[k] = copy.deepcopy(sub["default"])
            if k in out:
                out[k] = apply_defaults(sub, out[k])
        return out
    if t == "array" and isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [apply_defaults(schema["items"], v) for v in value]
    return value


class Template:
    name: str = ""
    title_ru: str = ""
    description: str = ""           # Russian: what it shows, which state model
    use_for: list[str] = []         # difficulty types (М В И Ф П Пр Н Р) and patterns
    frame_class: str = "B"          # default class A|B|C|D
    provenance: str = "симуляция"   # default provenance label
    animatable: bool = False
    animation: str = ""             # what t in [0,1] drives
    default_size: tuple = (1200, 750)
    params_schema: dict = {"type": "object"}
    example: dict = {}

    # --- API ------------------------------------------------------------------
    @staticmethod
    def sg(params: dict | None = None) -> dict:
        from .style import styleguide

        return styleguide((params or {}).get("_domain") or "geology")

    def normalize(self, params: dict) -> dict:
        p = apply_defaults(self.params_schema, params or {})
        jsonschema.validate(p, self.params_schema)
        return p

    def check(self, params: dict) -> list[Issue]:
        return []

    def state(self, params: dict, t: float | None = None) -> dict:
        return {}

    def draw(self, fig, rect, params: dict, t: float | None, ctx: DrawCtx) -> dict:
        raise NotImplementedError

    def describe(self, params: dict) -> str:
        return self.title_ru

    def provenance_for(self, params: dict) -> str:
        return params.get("provenance") or self.provenance

    def class_for(self, params: dict) -> str:
        return params.get("frame_class") or self.frame_class

    def catalog_entry(self, compact: bool = False) -> dict:
        d = {
            "name": self.name,
            "title": self.title_ru,
            "description": self.description,
            "use_for": self.use_for,
            "class": self.frame_class,
            "provenance": self.provenance,
            "animatable": self.animatable,
            "animation": self.animation,
            "params_schema": self.params_schema,
        }
        if not compact:
            d["example"] = self.example
        return d


def register(cls):
    inst = cls()
    REGISTRY[inst.name] = inst
    return cls


def common_props() -> dict:
    """Properties every template accepts (title, provenance override)."""
    return {
        "title": {"type": "string", "description": "Заголовок рисунка (коротко, по-русски)", "default": ""},
        "provenance": {"enum": ["реальные данные", "симуляция", "схема"],
                       "description": "Переопределить метку происхождения (обычно не нужно)"},
        "frame_class": {"enum": ["A", "B"], "description": "Переопределить класс кадра"},
    }
