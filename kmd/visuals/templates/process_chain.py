"""process_chain: cause -> effect / signal -> conclusion diagram (provenance «схема»).

Node kinds keep observation, inference, assumption and action visually distinct (honesty layer:
the «signal → conclusion» arrow is visible, not hidden). t reveals nodes in topological order.
"""
from __future__ import annotations

import math
import textwrap

from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from ..base import DrawCtx, Issue, Template, common_props, register

KINDS = ["observation", "inference", "assumption", "action", "cause", "effect", "warning"]


def _layers(nodes, edges):
    ids = [n["id"] for n in nodes]
    preds = {i: [] for i in ids}
    for e in edges:
        if e["from"] in preds and e["to"] in preds:
            preds[e["to"]].append(e["from"])
    rank = {}

    def r(i, stack=()):
        if i in rank:
            return rank[i]
        if i in stack:
            return 0
        rank[i] = 0 if not preds[i] else 1 + max(r(p, stack + (i,)) for p in preds[i])
        return rank[i]

    for i in ids:
        r(i)
    return rank


def _has_cycle(nodes, edges):
    adj = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["from"] in adj:
            adj[e["from"]].append(e["to"])
    color = {}

    def dfs(u):
        color[u] = 1
        for v in adj.get(u, []):
            if color.get(v) == 1 or (color.get(v) is None and v in adj and dfs(v)):
                return True
        color[u] = 2
        return False

    return any(color.get(n) is None and dfs(n) for n in adj)


@register
class ProcessChain(Template):
    name = "process_chain"
    title_ru = "Цепочка «причина → следствие» / «признак → правило → вывод»"
    description = (
        "Схема из блоков и стрелок. Виды блоков различаются цветом: наблюдение (сигнал, что измерено), "
        "вывод (интерпретация), допущение, действие специалиста, причина, следствие, «иначе…» (предупреждение/"
        "контрпример). Подходит для порядка операций, причинно-следственных цепочек, логики интерпретации "
        "«признаки → правило → вывод», «решение на данных». Метка «схема»."
    )
    use_for = ["П", "Пр", "Р", "Н", "И", "решение на данных", "порядок действий", "причинность"]
    frame_class = "B"
    provenance = "схема"
    animatable = True
    animation = "t∈[0,1]: блоки появляются по порядку причинности"
    default_size = (1200, 700)
    params_schema = {
        "type": "object",
        "required": ["nodes"],
        "properties": {
            **common_props(),
            "nodes": {"type": "array", "minItems": 1, "maxItems": 14,
                      "items": {"type": "object", "required": ["id", "text"],
                                "properties": {"id": {"type": "string"}, "text": {"type": "string", "maxLength": 120},
                                               "kind": {"enum": KINDS, "default": "cause"}}}},
            "edges": {"type": "array", "default": [],
                      "items": {"type": "object", "required": ["from", "to"],
                                "properties": {"from": {"type": "string"}, "to": {"type": "string"},
                                               "label": {"type": "string", "maxLength": 40}}}},
            "direction": {"enum": ["auto", "lr", "tb"], "default": "auto"},
            "show_kind_labels": {"type": "boolean", "default": True},
        },
    }
    example = {
        "title": "От сигнала к выводу: коллектор или нет",
        "nodes": [
            {"id": "a", "text": "ПС отклоняется влево от линии глин", "kind": "observation"},
            {"id": "b", "text": "Диаметр скважины меньше номинального", "kind": "observation"},
            {"id": "c", "text": "Пласт проницаем: фильтрат уходит в породу, на стенке корка", "kind": "inference"},
            {"id": "d", "text": "Пресный раствор: ρф > ρв", "kind": "assumption"},
            {"id": "e", "text": "Выделить пласт как коллектор и оценить насыщение", "kind": "action"},
        ],
        "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}, {"from": "d", "to": "c", "label": "условие"},
                  {"from": "c", "to": "e"}],
    }

    def check(self, params):
        iss = []
        ids = [n["id"] for n in params["nodes"]]
        if len(set(ids)) != len(ids):
            iss.append(Issue("error", "dup_id", "повторяющиеся id блоков"))
        for e in params["edges"]:
            if e["from"] not in ids or e["to"] not in ids:
                iss.append(Issue("error", "edge_ref", f"стрелка {e['from']}→{e['to']} ссылается на несуществующий блок"))
        if _has_cycle(params["nodes"], params["edges"]):
            iss.append(Issue("warning", "cycle", "в схеме есть цикл (проверить причинность)"))
        return iss

    def describe(self, params):
        txt = {n["id"]: n["text"] for n in params["nodes"]}
        if params["edges"]:
            return "Схема: " + "; ".join(f"«{txt.get(e['from'], '')}» → «{txt.get(e['to'], '')}»" for e in params["edges"])
        return "Схема: " + "; ".join(n["text"] for n in params["nodes"])

    def state(self, params, t=None):
        rank = _layers(params["nodes"], params["edges"])
        order = sorted(params["nodes"], key=lambda n: (rank[n["id"]], params["nodes"].index(n)))
        # the chain is fully built within the first 10 % of the frame time: the voice talks about the whole chain
        nvis = len(order) if t is None else max(1, math.ceil(min(1.0, t / 0.1) * len(order) - 1e-9))
        return {"rank": rank, "order": [n["id"] for n in order], "visible": {n["id"] for n in order[:nvis]}}

    def draw(self, fig, rect, params, t, ctx: DrawCtx):
        sg = ctx.sg
        st = self.state(params, t)
        rank = st["rank"]
        x0, y0, w, h = rect
        Wpx, Hpx = w * ctx.fig_px[0], h * ctx.fig_px[1]
        direction = params["direction"]
        if direction == "auto":
            direction = "lr" if Wpx >= Hpx * 1.1 else "tb"
        ax = fig.add_axes(rect)
        ax.set_axis_off()
        ax.set_xlim(0, Wpx)
        ax.set_ylim(0, Hpx)
        nl = max(rank.values()) + 1
        layers = [[n for n in params["nodes"] if rank[n["id"]] == i] for i in range(nl)]
        maxper = max(len(l) for l in layers)
        pos = {}
        if direction == "lr":
            cw, ch = Wpx / nl, Hpx / maxper
            bw, bh = cw * 0.84, min(ch * 0.84, Hpx * 0.42)
            for i, lay in enumerate(layers):
                for j, n in enumerate(lay):
                    cy = Hpx - (j + 0.5) * Hpx / len(lay)
                    pos[n["id"]] = (cw * (i + 0.5), cy)
        else:
            fs0 = ctx.base_px * 0.95
            k = max(1, int(Wpx // (fs0 * 0.62 * 15 + fs0)))
            rows = []
            for lay in layers:
                for j in range(0, len(lay), k):
                    rows.append(lay[j:j + k])
            nr = len(rows)
            ch = Hpx / nr
            perrow = max(len(r_) for r_ in rows)
            bw = min(Wpx / perrow * 0.9, Wpx * 0.8)
            bh = ch * 0.74
            for i, row in enumerate(rows):
                for j, n in enumerate(row):
                    pos[n["id"]] = ((j + 0.5) * Wpx / len(row), Hpx - ch * (i + 0.5))
        # largest font at which every box text fits its box
        for scale in (0.95, 0.85, 0.76, 0.68, 0.6):
            fs = ctx.base_px * scale
            chars = max(8, int((bw - fs) / (fs * 0.66)))
            need = max(len(textwrap.wrap(n["text"], chars, break_long_words=False)) * 1.3 * fs +
                       (1.9 if params["show_kind_labels"] else 0.6) * fs for n in params["nodes"])
            if need <= bh:
                break
        for n in params["nodes"]:
            if n["id"] not in st["visible"]:
                continue
            kind = n.get("kind", "cause")
            ks = sg["process_chain"].get(kind, {"color": "#37474F", "bg": "#ECEFF1", "ru": kind})
            cx, cy = pos[n["id"]]
            lines = textwrap.wrap(n["text"], chars, break_long_words=False)
            need_h = (len(lines) * 1.3 + (1.9 if params["show_kind_labels"] else 0.6)) * fs
            hh = max(bh * 0.55, min(bh, need_h))
            ax.add_patch(FancyBboxPatch((cx - bw / 2, cy - hh / 2), bw, hh,
                                        boxstyle=f"round,pad=0,rounding_size={fs * 0.6}", fc=ks["bg"], ec=ks["color"],
                                        lw=2.0, ls="--" if kind == "assumption" else "-", zorder=3))
            if params["show_kind_labels"]:
                ax.text(cx - bw / 2 + fs * 0.5, cy + hh / 2 - fs * 0.35, ks.get("ru", kind).upper(), ha="left", va="top",
                        fontsize=ctx.pt(0.62), color=ks["color"], fontweight="bold", zorder=4)
                ty = (cy + hh / 2 - fs * 1.25 + cy - hh / 2) / 2
            else:
                ty = cy
            ax.text(cx, ty, "\n".join(lines), ha="center", va="center", fontsize=fs * 72 / ctx.dpi,
                    color="#1A1A1A", zorder=4, linespacing=1.2)
            pos[n["id"]] = (cx, cy, hh)
        for e in params["edges"]:
            if e["from"] not in st["visible"] or e["to"] not in st["visible"]:
                continue
            (ax_, ay, ah), (bx, by, bh_) = pos[e["from"]], pos[e["to"]]
            if direction == "lr":
                p1, p2 = (ax_ + bw / 2, ay), (bx - bw / 2, by)
            else:
                p1, p2 = (ax_, ay - ah / 2), (bx, by + bh_ / 2)
            ar = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=fs * 1.4, lw=1.8, color="#37474F",
                                 connectionstyle="arc3,rad=0.0", zorder=2, shrinkA=2, shrinkB=2)
            ax.add_patch(ar)
            if e.get("label"):
                ax.text((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, e["label"], ha="center", va="center",
                        fontsize=ctx.pt(0.72), color="#37474F", zorder=5,
                        bbox=dict(fc="white", ec="none", alpha=0.9, pad=1))
        kinds = []
        for n in params["nodes"]:
            k = n.get("kind", "cause")
            if k not in kinds:
                kinds.append(k)
        legend = [{"kind": "patch", "label": sg["process_chain"].get(k, {}).get("ru", k),
                   "color": sg["process_chain"].get(k, {}).get("bg", "#EEE")} for k in kinds]
        return {"exaggerations": [], "legend": legend if not params["show_kind_labels"] else [], "notes": [],
                "axes": [ax]}
