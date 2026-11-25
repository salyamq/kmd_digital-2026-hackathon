# Course + site stages (owner: course agent)

## Commands
```
python -m kmd course CH          # steps/*.json, tasks.json, cards.json, illustrations/, course_report.json
python -m kmd course CH --node ID
python -m kmd site CH            # runs/CH/site/index.html (open from disk)
python -m kmd.course.reuse CH    # dev/queue only: re-answer pending course_step requests whose node is unchanged
pytest tests/test_course_*.py
```

## What the LLM writes vs what code assembles
One request per node, prompt `prompts/course_step.md`, answer schema `schemas/course_step_llm.schema.json`
(+ `$defs.task` injected from `schemas/task.schema.json`). The LLM writes only the beginner text:
title, essence (2–3 sentences), «Как это работает» paragraphs (each cites claim_ids), «По шагам»,
«Цифры и условия», «Решение на данных» (signs → rule → conclusion + practice cases), illustration specs,
tasks, cards. Code takes verbatim from the layer: worked examples, formulas, tables (+OCR fixes), terms,
misconception, data meaning (+hypotheses, inefficiency lens), analogy, current practice, deeper, book
problems, book figures, all claims with quotes (block «Источник»). Pages come from claim pages, never from the LLM.

## Code checks after the LLM (kmd/course/stage.py `assemble`)
- every claim id of the node is cited by some «Как это работает» paragraph (= all author ideas covered);
- sentences ≤ 20 words (essence, paragraphs, procedure, numbers, decision rule/conclusion); title 3–7 words;
- numbers in model text ⊂ numbers of `source_pages.json` + author fields of the layer (uses `kmd.verify` extractor);
- task: claim_id exists, `evidence` is a substring (normalized) of the step text, single has one key,
  multiple ≥ 2 keys, cloze blanks == `___` count and answer visible in evidence, numeric answer occurs in evidence;
- illustration template exists and renders (visuals invariants → error).
Hard errors → one repair request (`prompts/course_step_fix.md`, same context + error list). What still
fails is dropped (tasks, illustrations) and listed in `steps/<id>.json.checks` and `course_report.json`.
Chapter level: ≥ 15 tasks, ≥ 4 types, ≥ 1 «решение на данных» step (`plan()` forces the decision block on
routing `data_practice` nodes, else on the node with most worked examples / types И,Н,Р).

## Illustrations
`kmd/course/illustrate.py`: templates of `kmd.visuals` (catalog_text goes into the prompt; rendered with
`render_illustration`, plus a `size: tall` variant for phones) and built-in domain-free SVG templates
(`kmd/course/figures.py`: chain, contrast, ranges, decision, regions2d — 360-unit viewBox, theme-aware
classes, inlined into the page). Extra illustrations may be announced by visuals in
`runs/CH/illustrations/manifest.json` = `[{node_id, file, class, provenance, caption, alt, claim_ids}]`.

## Site (kmd/site)
Static multi-page HTML rendered by jinja (`templates/`), `static/app.js` + `style.css`, KaTeX vendored
(`vendor/katex`, MIT). State in localStorage `kmd:<chapter>:*` (done steps, last place, task results, card
marks), theme in `kmd:theme`. Pages: index (path by parts, minutes, progress, resume), step-NN (own TOC,
blocks, illustrations with provenance, media, tasks, sources, prev/next), tasks, cards, summary (print CSS),
map (arc diagram SVG + text list).
Media: mp4 in `runs/CH/video/<node>/` → `<video>` (+ .srt → .vtt subtitles, relative link `../video/...`);
else for routing short/long/interactive nodes with `scenes/<node>.json` → animation frames rendered by
`kmd.visuals.render(template, params, t=0..1)` (wide + tall variants) with play/slider.
Order tasks: pointer events (mouse + finger; verified with real CDP touch events,
`tests/fixtures/course/touchdrag.mjs`) and ↑/↓ buttons for keyboard.

## Known gaps / notes
- The prompt embeds the visuals catalog text, so any catalog change invalidates the course cache;
  `kmd.course.reuse` re-submits the previous answer when the node block is unchanged (still fully re-checked).
- Book figures are not redrawn by the course stage unless the LLM can fill a template from the node text
  (`redrawn_from`); real redraws from scans belong to visuals (manifest.json hook).
