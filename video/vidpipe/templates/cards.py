"""Card templates: text-led frames with simple vector graphics. Text is emitted for the overlay layer."""
import numpy as np

from .base import Template, T, panel, fit_size, measure


def _even_times(n, ctx, start=0.4, end_margin=0.8):
    if n <= 0:
        return []
    span = max(0.5, ctx.duration - start - end_margin)
    return [start + span * i / max(1, n) for i in range(n)]


class TitleCard(Template):
    name = "title_card"
    purpose = "Opening/section title: kicker + big title (+ subtitle). No facts beyond the title."
    classes = ("T", "D")
    required = {"title": "str (use *word* to accent a keyword)"}
    optional = {"kicker": "small mono line above", "subtitle": "str", "badge": "short number like 01"}
    example = {"kicker": "ГЕОФИЗИКА · 01", "title": "Что *на самом деле* меряет зонд", "badge": "01"}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        items = [{"type": "rect", "x": bx, "y": by + bh * 0.30, "w": ctx.s(14), "h": bh * 0.36, "fill": th["accent"],
                  "t0": 0.1, "appear": "draw", "fade_in": 0.5},
                 {"type": "circle", "cx": bx + bw * 0.86, "cy": by + bh * 0.2, "r": bw * 0.10, "stroke": th["accent2"],
                  "lw": 6, "t0": 0.2, "appear": "draw", "fade_in": 0.8},
                 {"type": "circle", "cx": bx + bw * 0.86, "cy": by + bh * 0.2, "r": bw * 0.05, "fill": th["accent3"],
                  "t0": 0.5, "appear": "grow", "fade_in": 0.5}]
        texts = []
        x = bx + ctx.s(40)
        if p.get("kicker"):
            texts.append(T(p["kicker"].upper(), x, by + bh * 0.30 + ctx.s(10), size=ctx.s(24), font="mono",
                           color=th["ink_soft"], anchor="lt", t0=0.2))
        texts.append(T(p["title"], x, by + bh * 0.30 + ctx.s(56), size=ctx.s(64), font="display", color=th["ink"],
                       anchor="lt", t0=0.35, max_w=bw - ctx.s(80), line_h=1.04,
                       upper=th["header"].get("title_case") == "upper", hl_color=th["accent"]))
        if p.get("subtitle"):
            texts.append(T(p["subtitle"], x, by + bh * 0.72, size=ctx.s(30), font="body", color=th["ink_soft"],
                           anchor="lt", t0=0.8, max_w=bw - ctx.s(80)))
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}


class MisconceptionCard(Template):
    name = "misconception_card"
    purpose = "Myth vs fact. The myth appears first and is struck through when the fact is revealed."
    classes = ("T",)
    required = {"wrong": "the misconception (short)", "right": "the correct statement (short, sourced)"}
    optional = {"reveal_at": "time-ref when the fact appears (default 45%)", "wrong_label": "str", "right_label": "str"}
    example = {"wrong": "Зонд посылает излучение и ловит отражение", "right": "Зонд только *принимает* естественное излучение пород",
               "reveal_at": "50%"}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        tr = ctx.at(p.get("reveal_at"), ctx.duration * 0.45)
        items, texts = [], []
        if ctx.portrait:
            A = (bx, by + 10, bw, bh * 0.42)
            B = (bx, by + bh * 0.52, bw, bh * 0.44)
        else:
            A = (bx + bw * 0.02, by + bh * 0.12, bw * 0.46, bh * 0.70)
            B = (bx + bw * 0.52, by + bh * 0.12, bw * 0.46, bh * 0.70)
        # myth panel
        items.append(panel(*A, th, t0=0.1, appear="grow", fade_in=0.35))
        items.append({"type": "icon", "kind": "cross", "cx": A[0] + ctx.s(52), "cy": A[1] + ctx.s(52), "size": ctx.s(40),
                      "stroke": "#FFFFFF", "fill": th["bad"], "t0": 0.3, "appear": "grow", "fade_in": 0.3})
        texts.append(T(p.get("wrong_label", ctx.T["myth"]).upper(), A[0] + ctx.s(96), A[1] + ctx.s(52), size=ctx.s(24),
                       font="mono", color=th["bad"], anchor="lm", t0=0.3))
        mw = A[2] - ctx.s(60)
        szw = fit_size(th, p["wrong"], "title", ctx.s(38), mw, A[3] - ctx.s(124), line_h=1.1)
        texts.append(T(p["wrong"], A[0] + ctx.s(30), A[1] + ctx.s(100), size=szw, font="title", color=th["ink"],
                       anchor="lt", max_w=mw, t0=0.45, line_h=1.1, source_ref=p.get("wrong_ref"), myth=True,
                       max_h=A[3] - ctx.s(110),
                       tracks={"opacity": {"kf": [[tr, 1.0], [tr + 0.4, 0.45]]}}))
        # strike-through when revealed
        items.append({"type": "line", "x1": A[0] + ctx.s(24), "y1": A[1] + A[3] * 0.62, "x2": A[0] + A[2] - ctx.s(24),
                      "y2": A[1] + A[3] * 0.48, "stroke": th["bad"], "lw": ctx.s(7), "t0": tr, "appear": "draw",
                      "fade_in": 0.35})
        # fact panel
        items.append(panel(*B, th, t0=tr, appear="grow", fade_in=0.35, stroke=th["good"], lw=4))
        items.append({"type": "icon", "kind": "check", "cx": B[0] + ctx.s(52), "cy": B[1] + ctx.s(52), "size": ctx.s(40),
                      "stroke": "#FFFFFF", "fill": th["good"], "t0": tr + 0.15, "appear": "grow", "fade_in": 0.3})
        texts.append(T(p.get("right_label", ctx.T["fact"]).upper(), B[0] + ctx.s(96), B[1] + ctx.s(52),
                       size=ctx.s(24), font="mono", color=th["good"], anchor="lm", t0=tr + 0.15))
        szr = fit_size(th, p["right"], "title", ctx.s(38), B[2] - ctx.s(60), B[3] - ctx.s(124), line_h=1.1)
        texts.append(T(p["right"], B[0] + ctx.s(30), B[1] + ctx.s(100), size=szr, font="title", color=th["ink"],
                       anchor="lt", max_w=B[2] - ctx.s(60), t0=tr + 0.3, line_h=1.1, hl_color=th["accent"],
                       max_h=B[3] - ctx.s(110),
                       source_ref=p.get("right_ref")))
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {"reveal_t": tr}}


class QuestionCard(Template):
    name = "question_card"
    purpose = "Prediction question (asked before the reveal) or transfer question (at the end), optional options."
    classes = ("T", "D")
    required = {"question": "str"}
    optional = {"options": "list of short answers", "kind": "prediction|transfer", "timer": "bool countdown ring",
                "label": "str above the question"}
    example = {"question": "Где ГК будет выше: в глине или в песчанике?", "options": ["в глине", "в песчанике"],
               "kind": "prediction", "timer": True}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        kind = p.get("kind", "prediction")
        lab = p.get("label") or (ctx.T["predict"] if kind == "prediction" else ctx.T["transfer"])
        opts = p.get("options") or []
        items, texts = [], []
        cx = bx + bw / 2
        # vertical budget: icon + label + question panel + options must fit in the content box
        k = 1.0
        for _ in range(10):
            r = ctx.s(64) * k
            ph = (ctx.s(220) if ctx.portrait else ctx.s(150)) * k
            opt_h = ctx.s(70) * k
            n_rows = len(opts) if ctx.portrait else (1 if opts else 0)
            total = 2 * r + ctx.s(70) * k + ph + (ctx.s(30) * k + n_rows * opt_h if opts else 0)
            if total <= bh or k < 0.6:
                break
            k *= 0.92
        cy = by + r + ctx.s(10)
        items.append({"type": "circle", "cx": cx, "cy": cy, "r": r, "fill": th["accent"], "t0": 0.05,
                      "appear": "grow", "fade_in": 0.4})
        items.append({"type": "icon", "kind": "question", "cx": cx, "cy": cy, "size": r * 1.1, "stroke": "#FFFFFF",
                      "lw": ctx.s(9) * k, "t0": 0.25, "appear": "grow", "fade_in": 0.3})
        if p.get("timer", kind == "prediction"):
            items.append({"type": "circle", "cx": cx, "cy": cy, "r": r + ctx.s(12) * k, "stroke": th["accent2"],
                          "lw": ctx.s(6) * k, "t0": 0.4, "appear": "draw", "fade_in": max(0.5, ctx.duration - 0.8)})
        texts.append(T(lab.upper(), cx, cy + r + ctx.s(36) * k, size=ctx.s(24) * k, font="mono", color=th["ink_soft"],
                       anchor="cm", t0=0.3))
        pw = bw if ctx.portrait else bw * 0.72
        px = cx - pw / 2
        py = cy + r + ctx.s(64) * k
        items.append(panel(px, py, pw, ph, th, t0=0.3, appear="grow", fade_in=0.35))
        szq = fit_size(th, p["question"], "title", ctx.s(40) * k, pw - ctx.s(60), ph - ctx.s(30), line_h=1.1)
        texts.append(T(p["question"], cx, py + ph / 2, size=szq, font="title", color=th["ink"], anchor="cm",
                       max_w=pw - ctx.s(60), align="center", t0=0.45, line_h=1.1, myth=p.get("myth", False),
                       max_h=ph - ctx.s(20)))
        if opts:
            ts = _even_times(len(opts), ctx, start=1.0, end_margin=1.2)
            oy = py + ph + ctx.s(30) * k
            labels = [f"*{chr(65 + i)}* · {o}" for i, o in enumerate(opts)]
            osz = ctx.s(30) * k
            gap = ctx.s(24)
            if not ctx.portrait:            # one centred row: measure real widths, shrink until it fits
                while True:
                    ws = [measure(th, lb, "body", osz, 0)[0] + 48 for lb in labels]
                    if sum(ws) + gap * (len(ws) - 1) <= bw or osz < ctx.s(18):
                        break
                    osz *= 0.92
                x = cx - (sum(ws) + gap * (len(ws) - 1)) / 2
            for i, (lb, t_o) in enumerate(zip(labels, ts)):
                if ctx.portrait:
                    ox, oyy, anc = cx, oy + i * opt_h, "ct"
                else:
                    ox, oyy, anc = x, oy, "lt"
                    x += ws[i] + gap
                texts.append(T(lb, ox, oyy, size=osz, font="body", color=th["ink"], anchor=anc, t0=t_o,
                               bg={"fill": th["panel"], "stroke": th["ink"], "stroke_w": 2, "radius": 30, "pad": [24, 10]}))
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}


class BeforeAfter(Template):
    name = "before_after"
    purpose = "Two-column comparison (before/after, manual/automated, intuition/reality) with items appearing in turn."
    classes = ("T",)
    required = {"left": "{title, items:[str]}", "right": "{title, items:[str]}"}
    optional = {"left_icon": "icon kind", "right_icon": "icon kind", "times": "list of time-refs for items"}
    example = {"left": {"title": "Вручную", "items": ["Интерпретатор ставит границы"]},
               "right": {"title": "Автоматически", "items": ["Модель получает ГК как признак"]}}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        items, texts = [], []
        cols = [p["left"], p["right"]]
        icons = [p.get("left_icon", "eye"), p.get("right_icon", "db")]
        colors = [th["accent"], th["accent2"]]
        n_items = sum(len(c.get("items", [])) for c in cols)
        ts = [ctx.at(x) for x in p.get("times", [])] or _even_times(n_items, ctx, start=0.9)
        k = 0
        for ci, c in enumerate(cols):
            if ctx.portrait:
                X, Y, W, H = bx, by + ci * (bh * 0.51), bw, bh * 0.47
            else:
                X, Y, W, H = bx + ci * bw * 0.51, by + bh * 0.05, bw * 0.47, bh * 0.85
            t0 = 0.15 + ci * 0.35
            items.append(panel(X, Y, W, H, th, t0=t0, appear="grow", fade_in=0.35))
            items.append({"type": "rect", "x": X, "y": Y, "w": W, "h": ctx.s(70), "r": 26, "fill": colors[ci],
                          "t0": t0, "fade_in": 0.35})
            items.append({"type": "icon", "kind": icons[ci], "cx": X + ctx.s(44), "cy": Y + ctx.s(35), "size": ctx.s(34),
                          "stroke": "#FFFFFF", "t0": t0 + 0.2})
            texts.append(T(c.get("title", ""), X + ctx.s(80), Y + ctx.s(35), size=ctx.s(30), font="title",
                           color="#FFFFFF", anchor="lm", t0=t0 + 0.2))
            yy = Y + ctx.s(100)
            for it in c.get("items", []):
                t_i = ts[k] if k < len(ts) else ts[-1]
                k += 1
                items.append({"type": "circle", "cx": X + ctx.s(36), "cy": yy + ctx.s(18), "r": ctx.s(8),
                              "fill": colors[ci], "t0": t_i, "appear": "grow"})
                texts.append(T(it, X + ctx.s(60), yy, size=ctx.s(29), font="body", color=th["ink"], anchor="lt",
                               max_w=W - ctx.s(90), t0=t_i, line_h=1.12))
                yy += measure(th, it, "body", ctx.s(29), W - ctx.s(90), 1.12)[1] + ctx.s(18)
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}


class EquationCard(Template):
    name = "equation_card"
    purpose = "Big equation / calculation card. Every number must be in the source table."
    classes = ("T",)
    required = {"lines": "list of equation strings, e.g. ['Δp ~ ln t']"}
    optional = {"caption": "str under the equation", "legend": "[{symbol, meaning}]", "times": "time-refs per line"}
    example = {"lines": ["χ = k / (μ·β*)"], "caption": "пьезопроводность", "legend": [{"symbol": "k", "meaning": "проницаемость"}]}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        items, texts = [], []
        lines = p["lines"]
        ts = [ctx.at(x) for x in p.get("times", [])] or _even_times(len(lines), ctx, start=0.3, end_margin=1.5)
        ph = min(bh * 0.55, ctx.s(130) * len(lines) + ctx.s(80))
        py = by + ctx.s(40)
        items.append(panel(bx, py, bw, ph, th, t0=0.1, appear="grow", fade_in=0.35))
        items.append({"type": "rect", "x": bx, "y": py, "w": ctx.s(12), "h": ph, "fill": th["accent"], "t0": 0.2})
        for i, (ln, t_l) in enumerate(zip(lines, ts)):
            texts.append(T(ln, bx + bw / 2, py + ctx.s(70) + i * ctx.s(120), size=ctx.s(56), font="display",
                           color=th["ink"], anchor="cm", t0=t_l, max_w=bw - ctx.s(60), align="center",
                           hl_color=th["accent"], source_ref=(p.get("refs") or [None] * len(lines))[i]
                           if i < len(p.get("refs") or []) else None))
        yy = py + ph + ctx.s(40)
        if p.get("caption"):
            texts.append(T(p["caption"], bx + bw / 2, yy, size=ctx.s(30), font="body", color=th["ink_soft"],
                           anchor="ct", max_w=bw - ctx.s(40), align="center", t0=ts[-1] + 0.4))
            yy += ctx.s(70)
        for j, lg in enumerate(p.get("legend", [])):
            t_g = ts[-1] + 0.6 + 0.35 * j
            col = j % 2 if not ctx.portrait else 0
            row = j // 2 if not ctx.portrait else j
            x = bx + (bw * 0.5 * col if not ctx.portrait else 0) + ctx.s(20)
            texts.append(T(f"*{lg['symbol']}* — {lg['meaning']}", x, yy + row * ctx.s(50), size=ctx.s(28),
                           font="body", color=th["ink"], anchor="lt", t0=t_g, hl_color=th["accent"],
                           max_w=(bw * 0.48 if not ctx.portrait else bw - 40)))
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}


class SummaryList(Template):
    name = "summary_list"
    purpose = "Vertical numbered list summarizing the path / key takeaways (items appear in turn)."
    classes = ("T",)
    required = {"items": "list of short strings"}
    optional = {"title": "str", "times": "time-refs"}
    example = {"title": "Итого", "items": ["ГК меряет природную радиоактивность", "Глины обычно ярче"]}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        items, texts = [], []
        lst = p["items"]
        ts = [ctx.at(x) for x in p.get("times", [])] or _even_times(len(lst), ctx, start=0.5)
        y = by + ctx.s(20)
        if p.get("title"):
            texts.append(T(p["title"], bx, y, size=ctx.s(40), font="title", color=th["ink"], anchor="lt", t0=0.1))
            y += ctx.s(80)
        step = min(ctx.s(120), (by + bh - y) / max(1, len(lst)))
        for i, (s, t_i) in enumerate(zip(lst, ts)):
            cy = y + i * step + ctx.s(30)
            if i < len(lst) - 1:
                items.append({"type": "line", "x1": bx + ctx.s(32), "y1": cy + ctx.s(30), "x2": bx + ctx.s(32),
                              "y2": cy + step - ctx.s(30), "stroke": th["muted"], "lw": 3, "dash": [6, 8],
                              "t0": t_i + 0.2, "appear": "draw"})
            items.append({"type": "circle", "cx": bx + ctx.s(32), "cy": cy, "r": ctx.s(28), "fill": th["accent"],
                          "t0": t_i, "appear": "grow", "fade_in": 0.3})
            texts.append(T(str(i + 1), bx + ctx.s(32), cy, size=ctx.s(28), font="mono", color="#FFFFFF", anchor="cm",
                           t0=t_i + 0.1, kind_num="enumeration"))
            texts.append(T(s, bx + ctx.s(80), cy, size=ctx.s(32), font="body", color=th["ink"], anchor="lm",
                           max_w=bw - ctx.s(90), t0=t_i + 0.1, line_h=1.12))
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}


class TextPanel(Template):
    name = "text_panel"
    purpose = "Panel with an icon, a short paragraph and optional chips (e.g. IT/data bridge, definitions). Fallback for any claim."
    classes = ("T",)
    required = {"text": "paragraph (use *word* for accents)"}
    optional = {"icon": "db|gear|eye|clock|warning|check|arrow", "title": "str", "chips": "list of short tags",
                "chips_title": "str"}
    example = {"title": "Где это в данных", "text": "Кривая ГК — входной *признак* для модели литологии", "icon": "db",
               "chips": ["LAS", "GR", "литология"]}

    def plan(self, p, model, ctx):
        th = ctx.theme
        bx, by, bw, bh = ctx.box
        items, texts = [], []
        ph = bh * (0.62 if p.get("chips") else 0.8)
        items.append(panel(bx, by + ctx.s(10), bw, ph, th, t0=0.1, appear="grow", fade_in=0.35))
        items.append({"type": "icon", "kind": p.get("icon", "arrow"), "cx": bx + ctx.s(70), "cy": by + ctx.s(80),
                      "size": ctx.s(54), "stroke": "#FFFFFF", "fill": th["accent2"], "t0": 0.3, "appear": "grow"})
        y = by + ctx.s(80)
        if p.get("title"):
            texts.append(T(p["title"], bx + ctx.s(130), y, size=ctx.s(32), font="title", color=th["ink"], anchor="lm",
                           t0=0.3, max_w=bw - ctx.s(160)))
        szt = fit_size(th, p["text"], "body", ctx.s(36), bw - ctx.s(80), ph - ctx.s(170), line_h=1.16)
        texts.append(T(p["text"], bx + ctx.s(40), by + ctx.s(160), size=szt, font="body", color=th["ink"],
                       anchor="lt", max_w=bw - ctx.s(80), t0=0.5, line_h=1.16, hl_color=th["accent"],
                       max_h=ph - ctx.s(160),
                       source_ref=p.get("source_ref")))
        chips = p.get("chips") or []
        if chips:
            cy = by + ph + ctx.s(60)
            if p.get("chips_title"):
                texts.append(T(p["chips_title"].upper(), bx, cy, size=ctx.s(22), font="mono", color=th["ink_soft"],
                               anchor="lm", t0=1.0))
                cy += ctx.s(50)
            ts = _even_times(len(chips), ctx, start=1.2, end_margin=0.8)
            x = bx
            for c, t_c in zip(chips, ts):
                w_est = ctx.s(22) * 0.62 * len(c) + ctx.s(50)
                if x + w_est > bx + bw:
                    x = bx
                    cy += ctx.s(64)
                texts.append(T(c, x, cy, size=ctx.s(26), font="mono", color=th["panel"], anchor="lm", t0=t_c,
                               bg={"fill": th["ink"], "radius": 22, "pad": [18, 9]}))
                x += w_est + ctx.s(18)
        return {"items": items, "texts": texts, "probes": [], "checks": [], "state": {}}
