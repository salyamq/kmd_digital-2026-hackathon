# vidpipe — input / output contract

This is what the learning layer and the LLM planner hand to the video pipeline, and what they get back.
If your output follows this file, `python -m vidpipe make …` turns it into a video whose facts are checked
against the book. Everything here is **data** — no code change is needed for a new book, chapter or domain.

```
node.json  ──┐
pages/     ──┤
domain/    ──┼──►  vidpipe make  ──►  videos/<id>/08_final/<id>.mp4
data/      ──┤                         videos/<id>/passport.json
(plan)     ──┘                         videos/<id>/qa_report.md (+ qa.json, source_table.json, coverage_report.md)
```

Contents: [1 node.json](#1-nodejson) · [2 quotes and pages — how to pass QA](#2-quotes-and-pages--how-to-pass-qa) ·
[3 chapter pages dir](#3-chapter-pages-directory---pages) · [4 domain pack](#4-domain-pack---domain) ·
[5 open data](#5-open-data---data) · [6 plans from the LLM planner](#6-plans-from-your-llm-planner-optional) ·
[7 CLI](#7-cli) · [8 outputs](#8-outputs) · [9 examples](#9-examples)

---

## 1. node.json

One JSON object per node (a list with one object, or `{"node": {...}}`, is also accepted).
Check what the pipeline sees before building: `python -m vidpipe check --node node.json --pages pages/ --domain domain/`.

### Fields

| field | type | required | what it becomes in the video | accepted aliases |
|---|---|---|---|---|
| `id` | string | **yes** (defaults to file name) | video id, file names | `node_id`, `slug`, `key` |
| `title` | string; `*word*` = accent colour | **yes** | header on every frame | `name`, `heading`, `topic` |
| `claims` | list of claim objects (below) | **yes** | narration of the mechanism; the only source of facts | `statements`, `facts`, `key_points`, `assertions` |
| `lang` | `"ru"` \| `"en"` | no (auto-detected) | voice, subtitles, UI strings | `language`, `locale` |
| `source` | object `{title, book, chapter, pages}` | recommended | kicker line; `book` (with year) goes to the passport and may be cited on screen | `chapter`, `book`, `reference` |
| `misconception` | object `{wrong, right, claim_id}` | recommended | hook (myth) → reveal (fact); `right` must be backed by `claim_id` | `myth`, `misconceptions[0]`; inner: `myth`/`belief`, `correct`/`correction`/`truth` |
| `what_it_means_for_data` | object `{text, curves, claim_ids}` | recommended | the "in the data" line; `curves` picks the dataset curve/column | `data_meaning`, `in_data`, `for_data` |
| `it_analogy` | string | recommended | the bridge line for data engineers | `analogy`, `it_bridge` |
| `prediction_question` | string or `{text, options: [2–3 str]}` | recommended | question asked before the reveal (options shown as A/B/C) | `predict_question`, `question_before` |
| `transfer_question` | string | recommended | closing "check yourself" question (the one full-screen card) | `question_after`, `check_question` |
| `difficulty_types` | list of strings | no | tags in the passport (`misconception`, `measurement`, `process`, …) | `difficulty`, `types` |
| `formulas` | list of formula objects (below) | no | a computed chart (class B "simulation") if the node has no dataset curve | `equations`, `formula` |
| `visual_hints` | `{template, class, params, model}` | no | forces a specific scene for the mechanism lines | `visuals`, `scene_hints` |

A string is accepted wherever a claim object is expected (`"claims": ["…", "…"]`), but such claims have no
page/quote, so QA cannot verify them and the video gets the **DRAFT** mark.

### Claim object

| key | type | required for QA pass | notes |
|---|---|---|---|
| `id` | string, unique in the node (`"c1"`) | yes | referenced by `misconception.claim_id`, `what_it_means_for_data.claim_ids`, formulas, plans |
| `text` | string | yes | what the narrator says — your own wording, short (≤ 25 words reads well), **no formulas** (they are read aloud) |
| `page` | integer (or `"с. 65"`, `"p. 65"` — the first number is taken) | **yes** | page of the quote, numbered like the files in `--pages` (see §3) |
| `quote` | string | **yes** | verbatim fragment of that page, rules in §2 |

Aliases: `statement`/`claim`/`fact` for `text`; `verbatim`/`citation`/`evidence` for `quote`; `page_ref`/`p` for
`page`; or `{"source": {"page": …, "quote": …}}`.

### Formula object (optional)

```json
{"claim_id": "c4", "page": 42, "quote": "V = (Qп − Qо)·t",
 "expr": "(Qin - Qout) * t",
 "params": {"Qin":  {"value": 120, "unit": "m3/hour", "source": {"assumption": true, "note": "illustrative"}},
            "Qout": {"value": 30,  "unit": "m3/hour", "source": {"page": 42, "quote": "…"}}},
 "grid": {"t": {"from": 0, "to": 1200, "n": 120, "unit": "s"}},
 "derived": {"chi": "k/(mu*beta)"},
 "x_label": "t, мин", "x_display_unit": "minute", "y_label": "V, м³", "y_display_unit": "m3",
 "display": "накопленный объём жидкости"}
```

* `expr` is a numpy expression over the `grid` axes and `params`. Allowed: `+ - * / **`, `exp log log10 sqrt sin cos
  tan erf erfc E1 Ei minimum maximum where clip smoothstep pi`. Anything else is rejected.
* Units are converted to SI (pint; `m3/hour`, `mPa*s`, `D`, `bar`, `сут`, `ч` …); `*_display_unit` converts back.
* `quote` = the formula **as printed** on the page (§2). Every parameter value is either sourced (`page`+`quote`)
  or `{"assumption": true, "note": "why"}` — assumptions are listed in the passport.

### How fields become lines (rule planner, no LLM)

`misconception.wrong` → hook · `prediction_question` → prediction · `misconception.right` → reveal ·
remaining `claims` (up to 3 for `short`, 8 for `explainer`, trimmed to the word budget) → mechanism ·
`what_it_means_for_data.text` → data · `it_analogy` → bridge · `transfer_question` → transfer.
Word budget: `short` 60–115 words (30–60 s), `explainer` 240–470 words (2–4 min), ~2 words/s.

The visual for hook → mechanism is chosen from node content, in this order: `visual_hints` → domain pack
`visuals.json` keyword → a LAS curve from `what_it_means_for_data.curves` (→ `depth_track`, real data) → a CSV
column from `curves` (→ `data_chart`, real data) → a `formulas` entry (→ `data_chart`, simulation) → lithology words
in the claims (→ `cross_section`). If none applies the mechanism falls back to text cards and the coverage report
says `needs_visual` (QA then fails the "cards ≤ 25 %" rule — on purpose).

---

## 2. Quotes and pages — how to pass QA

QA check `claims_verified` passes only if **every** claim/formula/table the script uses is `verified`:

| status | meaning | fix |
|---|---|---|
| `verified` | the quote occurs on the cited page (±1 page: quotes may cross a page break) | — |
| `wrong_page` | the quote exists, but on another page | fix `page` (the report says where it was found) |
| `near` | only a similar text exists (≥ 75 % similar), e.g. one word changed | copy the quote again, exactly |
| `not_found` | no such text in the chapter | it is a paraphrase or a fabricated quote — use the book's words |
| `no_pages` / `no_quote` | `--pages` missing, or claim without `quote` | provide pages / quotes |

Rules for a quote:

1. **Copy, don't paraphrase.** One contiguous fragment of the page text, at least 6 characters. Do not join two
   fragments with `…`, do not drop words in the middle. A whole sentence or a clause is ideal (10–40 words).
2. What is ignored when comparing: letter case, `ё`/`е`, typographic quotes `«» “ ” „ " '`, the dash family
   `- – — −` (all treated as `-`), whitespace and line breaks, words hyphenated across a line break (`стра-\nницы`),
   markdown symbols `* _ # > |`, stress marks.
3. Everything else must match: words and their endings, digits, decimal commas (`0,7` ≠ `0.7`), Greek letters,
   subscripts written as letters (`Iоп1`), punctuation inside the quote. Mind Latin/Cyrillic look-alikes
   (`K` vs `К`, `o` vs `о`) — copy from the page text, not from a re-typed version.
4. `page` = the page number of the `--pages` file that contains the quote (§3). For a PDF processed with
   `scripts/extract_pages.py` that is the **PDF page index**, not the number printed on the paper page.
5. Numbers: every number the narrator says must appear in the line's sources or the chapter (`spoken_numbers`);
   every number shown on screen must be in the source table, a dataset, a model or an axis (`screen_numbers`).
6. Scanned pages (images → OCR) are the only case where a fuzzy match (≥ 92 %) on the cited page counts as verified.

Example — page `p065.txt` contains: `Из всех осадочных пород наиболее радиоактивными являются глины, поэтому …`

```json
{"id": "c3", "page": 65, "quote": "Из всех осадочных пород наиболее радиоактивными являются глины",
 "text": "Самые радиоактивные из осадочных пород — глины."}                         ✔ verified
{"id": "c3", "page": 66, "quote": "Из всех осадочных пород наиболее радиоактивными являются глины"}   ✘ wrong_page
{"id": "c3", "page": 65, "quote": "Из всех осадочных пород наименее радиоактивными являются глины"}  ✘ near
{"id": "c3", "page": 65, "quote": "Глины — самые радиоактивные породы"}                               ✘ not_found
```

If anything is not verified the video still renders, but QA fails and a red **DRAFT** label is burned in.

---

## 3. Chapter pages directory (`--pages`)

* **One text file per page**: `p064.txt`, `p065.txt`, … (`.txt` or `.md`; the last number in the file name is
  the page number). Make them from a PDF with
  `python scripts/extract_pages.py --pdf book.pdf --pages 64-69 --out pages/` (find a section first with `--find`).
* **Or one markdown file with page markers** on their own line: `<!-- page 65 -->`, `## стр. 65`, `[page 65]`,
  `Страница 65`, `с. 65`.
* **Or scans**: `p065.png/jpg/tif` → OCR (`tesseract`, rus+eng) if no text file exists for that page.
* `README*`, `notes*`, files starting with `.` or `_` are ignored (not chapter text).

---

## 4. Domain pack (`--domain`)

A folder; files are found by name, any of them may be missing (built-in defaults are used:
`vidpipe/resources/default_domain/`). Example: `examples/domain_pack_demo/`.

| file name pattern | format | used for |
|---|---|---|
| `*stress*` (`.tsv/.csv/.json/.txt`) | `word<TAB>stressed form` with `+` before the stressed vowel (`песч+аник`) or an acute accent; JSON `{word: stressed}` or `[{word, stressed}]` | TTS pronunciation (all engines); QA warns on glossary terms without an entry |
| `*glossar*` / `*terms*` (`.json/.csv`) | `[{term, en?, abbr?, spoken?, definition?}]` | `abbr` + `spoken` → abbreviation read as written (`ГМ` → `гэ-эм`) |
| `*expansion*` / `*abbrev*` | `{abbr: spoken}` or two-column table | extra TTS expansions |
| `*physics*` / `*checklist*` (`.json`) | `{"rules": [{id, text, applies_if: [regex], forbid: [regex], allow_if_negated: true}], "spec_rules": [...], "manual": [str]}` | physics anti-examples: QA fails if narration or on-screen text matches `forbid` (myth lines are exempt) |
| `*physics*.md` | `- [ ] item` lines | manual checklist in `mentor_pack.md` |
| `*legend*.json` / `*style*.json` | partial copy of `default_domain/legend.json` (lithology colours/patterns, aliases, fluid colours, curve colours) | merged over the defaults; one legend for all videos |
| `*visual*.json` | `[{match: [keywords], template, class, params, model?}]` | keyword → scene, for topics without data or formula |
| `*.jpg/*.png` + `photos.json` | `[{file, source, license, caption, tags}]` | class C photo shots (licence required) |
| `*misconcep*.json` | list | context for the LLM planner |

Lithology keys understood by templates: `sandstone shale clay siltstone limestone dolomite marl salt anhydrite coal
conglomerate chalk basement unknown` (Russian names are mapped by `lithology_aliases`, e.g. `песчаник`, `глины`).

---

## 5. Open data (`--data`)

Default: `video/data/`. Every `.las` (curves + units), `.csv` (columns) and `.sgy/.segy` (listed) under the given
dirs is scanned. `data/catalog.json` adds what the files can't say:

```json
[{"file": "volve/volve_daily_production.csv", "dataset": "Equinor Volve", "license": "Equinor Open Data Licence (Volve)",
  "kind": "production_daily", "time_column": "DATEPRD", "well_column": "NPD_WELL_BORE_NAME",
  "units": {"BORE_OIL_VOL": "Sm3/d"}, "description": "…"}]
```

A node uses a dataset by naming the curve/column in `what_it_means_for_data.curves` (`["GR"]`, `["CALI"]`,
`["BORE_OIL_VOL"]`). Curve words in the text are also recognised (`vidpipe/resources/mnemonics.json`), but an
explicit `curves` list always wins.

---

## 6. Plans from your LLM planner (optional)

The pipeline can plan by itself (`--planner rule`, or `--planner llm` with an API key). If your planner produces
the plan, save two files in a folder and run `--planner replay --llm-cache <folder>`; they go through exactly the
same validation and QA. Prompts that describe the format: `vidpipe/resources/prompts/`. Full examples:
`examples/ru_gr_latyshova/llm_replay/`.

`script.json`

```json
{"title": "…", "kicker": "…",
 "lines": [
   {"id": "L1", "role": "hook", "myth": true, "asserts_fact": false, "sources": [], "text": "Многие думают, что …"},
   {"id": "L3", "role": "reveal", "asserts_fact": true,
    "sources": [{"type": "claim", "claim_id": "c1", "page": 65, "quote": "<verbatim, as in node.json>"}],
    "text": "На самом деле прибор *регистрирует* …"},
   {"id": "L6", "role": "data", "asserts_fact": true,
    "sources": [{"type": "dataset", "dataset": "Equinor Volve", "file": "15-9-19_SR_COMP.las", "curve": "GR"}],
    "text": "…"}],
 "prediction_question": {"text": "…", "options": ["…", "…"]},
 "transfer_question": {"text": "…"},
 "data_it_bridge": {"where_in_data": "…", "manual_work": "…", "hypotheses": []}}
```

* `role` ∈ `hook prediction reveal mechanism data bridge transfer outro`. Every line with `asserts_fact: true`
  needs at least one source. `*word*` = accent colour on screen; `+` before a vowel = stress.

`shots.json` — every line covered once, in order:

```json
{"shots": [
  {"id": "S1", "line_ids": ["L1", "L2", "L3"], "template": "overlay_card", "class": "A", "provenance": "data",
   "params": {"base": {"template": "depth_track", "params": {"track": {"curve": "GR", "unit": "API"}}},
              "cards": [{"kind": "myth", "text": "…?", "at": 0.2},
                        {"kind": "question", "text": "…", "options": ["…", "…"], "at": "L2"},
                        {"kind": "fact", "text": "…", "at": "L3", "source_ref": "c1"}]},
   "model": {"type": "las", "file": "15-9-19_SR_COMP.las", "curve": "GR", "depth_from": 4278, "depth_to": 4366},
   "invariants": ["…"], "assumptions": ["…"], "exaggerations": ["…"]}]}
```

* Templates and their required params: `python -m vidpipe templates` (list at the end of this file).
* Frame classes: **A** real data · **B** simulation / schematic · **C** real photo · **D** AI atmosphere (≤ 2,
  no facts) · **T** full-screen text card.
* QA rules your plan must meet: A+B ≥ 70 % of screen time; T ≤ 25 %; every `mechanism`/`data` line on a visual
  (A/B/C) — put questions, myths, facts and equations as `overlay_card` cards beside a visual instead of full cards.
* Time references in params: seconds, `"L3"` (line start), `"L3.end"`, `"L3+0.5"`, `"40%"` of the shot.
* Model types: `las`, `csv`, `table` (cells checked on the page), `formula`, `pde_diffusion`.

---

## 7. CLI

Run from `video/`. `./make_video …` = `python -m vidpipe make …`.

| command | what it does |
|---|---|
| `make --node N --pages P --domain D --format short\|explainer --style F\|N\|M` | build a video from scratch |
| `rebuild videos/<id> [--from STAGE] [--to STAGE] [--only STAGE …]` | re-run stages from saved files (default `--from specs`) |
| `check --node N --pages P --domain D` | preflight: quotes found, missing fields, matching dataset curves |
| `templates` | template library with required fields |
| `preview videos/<id>` | contact sheet PNG (no encoding) |
| `tts --provider yandex --text "…" --out t.wav` | one-off voice test |
| `selftest [out] [--quick]` | the test suite (§ README) |

`make` options:

| flag | values (default) | meaning |
|---|---|---|
| `--node` | path (required) | node.json |
| `--pages` | dir | chapter pages (§3); without it nothing can be verified → DRAFT |
| `--domain` | dir | domain pack (§4) |
| `--data` | dir, repeatable (`video/data`) | open data dirs (§5) |
| `--format` | `short` (9:16, 30–60 s) \| `explainer` (16:9, 2–4 min) | |
| `--style` | `F` flat schematic, warm paper (default) \| `N` night industrial \| `M` macro, dark warm | one visual theme per video |
| `--out` / `--id` | `video/videos` / `<node id>_<format>_<style>` | where the video folder goes |
| `--lang` | `ru` \| `en` | override detection |
| `--planner` | `auto` (LLM if key, else rules) \| `rule` \| `llm` \| `replay` | who writes script + shots |
| `--llm-provider`, `--llm-model`, `--llm-base-url`, `--llm-cache` | | LLM settings; `--llm-cache` = folder for replay |
| `--tts` | `yandex` \| `rhvoice` \| `silero` \| `espeak` \| `none` | voice; `yandex` falls back to RHVoice if no key |
| `--voice`, `--role`, `--speed` | e.g. `alexander`, `good`, `1.0` | Yandex voice settings (`--rate` for RHVoice) |
| `--tts-numbers` | `auto` \| `raw` \| `words` | digits sent as-is (Yandex) or expanded to words |
| `--ai-video` | `none` \| `fal` \| `wan_local` | class D clips (`fal` is paid; off by default) |
| `--from`, `--to`, `--only` | stage names | partial runs |

Stages, in order: `brief script shotlist specs models audio layout render overlays compose qa passport`.
`--from`/`--only` first checks that every file the requested stages read exists (or is produced earlier in the
same run) and otherwise stops with the stage to re-run — before any paid API call.

Exit code: `0` when the video was produced, even if QA failed — read `qa.json` for the verdict.
`selftest` exits non-zero if a part fails.

---

## 8. Outputs

```
videos/<id>/
  00_brief.json            inputs + settings of this build (paths repo-relative)
  01_script.json           narration lines with roles and sources
  02_shotlist.json         shots: template, class, lines
  03_scene_specs/S*.json   params + state model per shot (what the renderer reads)
  04_models/               evaluated state models (cache)            ┐
  05_renders/              graphics-only shot renders + QA frames    │ git-ignored,
  06_audio/                one WAV per line + narration.wav          │ re-created by
  07_overlays/overlays.json  every piece of text (composited last)   │ rebuild
  08_final/<id>.mp4        THE VIDEO (H.264 + AAC, −16 LUFS)         ┘
  passport.json            machine-readable passport (below)
  qa_report.md / qa.json   QA verdict, human / machine
  source_table.json        every source: claims (page, quote, status), datasets, params, assumptions
  coverage_report.md/.json templates used, gaps (needs_visual, needs_data, needs_new_template, fallbacks)
  mentor_pack.md           what a human reviewer should look at
  calls.jsonl              paid API calls (chars, seconds, cost) — git-ignored
```

`passport.json` keys: `video_id`, `rebuild_command`, `rebuild_from_scratch_command`, `output` (mp4 path), `format`,
`node_card`, `script`, `source_table`, `scene_specs`, `frames` (class + provenance per shot), `exaggerations`,
`prediction_question`, `transfer_question`, `data_it_bridge`, `metrics`, `tools` (planner, TTS voice, renderer,
encoder), `qa_summary` (`{pass, fail, warn, manual, info}`), `qa_failures`, `coverage_gaps`, `open_questions`
(assumptions to confirm), `datasets` (with licences).

`qa.json` — list of `{section, id, status, text, details}`; `status` ∈ `pass fail warn info manual`. Ids:
`claims_verified facts_have_sources spoken_numbers screen_numbers assumptions_listed <shot>:frame_same_y
invariants_model no_ai_text ai_frames_verified physics:<rule id> provenance_labels ab_share card_share
mechanism_visuals overlay_cards d_clips style subtitles_readable subtitles_synced stress length hook_3s loudness
templates spec_review`. A video is publishable when there is no `fail` and the `manual` review is done.

---

## 9. Examples

### Minimal node (builds, but QA fails honestly: no pages, no visual)

```json
{"id": "porosity_min",
 "title": "Пористость коллектора",
 "claims": [
   {"id": "c1", "text": "Пористость — доля объёма пор в общем объёме породы.", "page": 12,
    "quote": "Пористостью называется доля объёма пор в общем объёме породы"}]}
```

`examples/bare_minimal/node.json` is even smaller (two bare strings) and is used as a robustness test.

### Full node (passes QA with its pages; this is `tests/fixtures/ru_drilling_mud/`)

```json
{
  "id": "test_drilling_mud",
  "title": "Буровой раствор: почему ствол скважины *не цилиндр*",
  "lang": "ru",
  "source": {"title": "Бурение · § 21", "book": "Синтетический учебный фрагмент для автотеста vidpipe, 2026",
             "chapter": "§ 21. Буровой раствор и состояние ствола скважины", "pages": "117–118"},
  "difficulty_types": ["misconception", "measurement"],
  "misconception": {
    "wrong": "Буровой раствор нужен только для смазки долота",
    "right": "Раствор выносит шлам, охлаждает долото и своим давлением удерживает пластовые флюиды",
    "claim_id": "c1"
  },
  "claims": [
    {"id": "c1", "text": "Буровой раствор выносит шлам, охлаждает долото и гидростатическим давлением удерживает пластовые флюиды.",
     "page": 117, "quote": "Буровой раствор выносит выбуренную породу (шлам) на поверхность, охлаждает долото и своим гидростатическим давлением удерживает пластовые флюиды."},
    {"id": "c2", "text": "Против глин раствор может вызывать набухание и обрушение стенок: ствол расширяется, образуются каверны.",
     "page": 118, "quote": "Против глин раствор на водной основе может вызывать набухание и обрушение стенок скважины: диаметр ствола увеличивается, образуются каверны."},
    {"id": "c3", "text": "Против проницаемых песчаников на стенке образуется глинистая корка, и диаметр бывает чуть меньше номинального.",
     "page": 118, "quote": "Против проницаемых песчаников фильтрат раствора уходит в пласт, а на стенке образуется глинистая корка"},
    {"id": "c4", "text": "Каверны видны на кавернограмме — диаграмме диаметра скважины.",
     "page": 118, "quote": "Это видно на кавернограмме — диаграмме диаметра скважины."}
  ],
  "what_it_means_for_data": {
    "text": "В LAS-файле это кривая CALI: где ствол шире номинала — каверны, и показания других методов там под сомнением.",
    "curves": ["CALI"],
    "claim_ids": ["c4"]
  },
  "it_analogy": "Для дата-инженера CALI — флаг качества: по нему отмечают интервалы, где другие кривые искажены.",
  "prediction_question": {"text": "Где ствол окажется шире номинала — против глин или против песчаников?",
                          "options": ["против глин", "против песчаников"]},
  "transfer_question": "Против глин кавернограмма показывает рост диаметра. Чему из других кривых вы поверите меньше?"
}
```

```bash
python -m vidpipe make --node tests/fixtures/ru_drilling_mud/node.json --pages tests/fixtures/ru_drilling_mud/pages \
       --domain examples/domain_pack_demo --format short --style F --planner rule
```

More: `examples/ru_gr_latyshova/node.json` (real chapter, 12 claims, formula 40, table 12),
`tests/fixtures/ru_slug_catcher/node.json` (with a `formulas` entry), `examples/en_decline_unseen/node.json`
(English, alternative key names: `statements`, `myth`, `analogy`, `data_meaning`).

---

## Appendix — template library (`python -m vidpipe templates`)

| template | classes | required params |
|---|---|---|
| `depth_track` | A, B | `track: {curve, unit, range?, log?, title?}`; model `las` (or formula over `depth`) |
| `data_chart` | A, B | `y: [model arrays]` (line/step/scatter) or `kind: range_bars` + `lo`, `hi`, `labels` |
| `field_evolution` | B | `field: {output, x_axis, t_axis}`; model `formula`/`pde_diffusion` over (x or r, t) |
| `cross_section` | B | `units: [{name, lith, thickness}]` |
| `pore_scale` | B | — (grains always touch) |
| `inset_callouts` | B, C | `base: {template, params}`, `inset: {template, params, focus, pos, radius}` |
| `overlay_card` | A, B, C (class of its base) | `base: {template, params}`, `cards: [{kind, text, at, options?, label?, source_ref?}]` |
| `photo` | C | `src` (licensed photo from the domain pack) |
| `ai_clip` | D | `first_frame`, `last_frame`, `prompt` (mood only) |
| `title_card`, `question_card` | T, D | `title` / `question` |
| `misconception_card` | T | `wrong`, `right` |
| `equation_card` | T | `lines` |
| `before_after` | T | `left`, `right` |
| `summary_list` | T | `items` |
| `text_panel` | T | `text` |
| `process_steps` | T | `steps` |
