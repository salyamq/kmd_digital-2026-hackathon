# Architecture: «Глава → курс» pipeline

This document is the **contract** between the pipeline stages. Every stage reads files
written by the previous stage and writes its own files; no stage reads the book directly
except `ingest` (and `verify`/`checker`, which re-read the source to check claims).

The full task statement is in `docs/TZ.md` (Russian). Read it before changing a stage.

## Principles (from the TZ, non-negotiable)

1. **Learning layer is the single source of truth.** Course, tasks, cards, illustrations,
   video specs are built from `layer.json`, never from the book.
2. **Engine knows no geology.** Everything domain-specific lives in `domains/<domain>/`
   (glossary, misconceptions, physics checklist, IT bridges, style guide, stress dictionary,
   difficulty-type routing hints). A new domain = a new folder, no code change.
3. **No hardcoded chapters.** A chapter is a YAML file in `chapters/`. The engine must run
   on unseen chapters (other authors, schools, English) — test set is given after freeze.
4. **Every claim has a verbatim author quote and a PDF page.** Code (not the LLM) checks
   that the quote is on that page and that every number in node/course text exists in the source.
5. **Model-written vs author content is marked** on every field (`by: "author" | "model"`).
6. **Models are replaceable.** All LLM calls go through `kmd/llm.py` (provider abstraction).
7. **Human corrections are overrides + edit log**, never hand-edits of generated files:
   `overrides/<chapter>/<node_id>.json` (JSON merge-patch over the node) + one line in
   `edits/journal.jsonl` with minutes. `make rebuild CH=<chapter>` rebuilds everything
   downstream (step page, tasks, video) with one command.
8. **Deterministic graphics for facts.** Illustration/frame classes A (data) and B (process)
   are rendered by code from a state model. Generative imagery only for class C/D and never
   with cores, thin sections, sections/schemes, curves, text, digits, logos.

## Directory layout

```
kmd/                 engine (python package, domain-agnostic)
  cli.py             `python -m kmd ...` entry point (also via Makefile)
  config.py          chapter + domain config loading, paths
  llm.py             LLM providers (openai-compatible, anthropic, queue) + cache
  ingest/            md+pdf -> units.json, page images
  layer/             LLM extraction -> layer.json, coverage.json
  verify/            quote/number checks -> verify_report.json
  route/             format routing -> routing.json
  course/            step content (LLM) -> steps/*.json ; static site builder -> site/
  visuals/           scene templates (A/B), illustration renderer
  video/             scene spec -> frames -> TTS -> ASR check -> mp4 + passport
  checker/           review of an external package -> findings.json
  edits.py           edit journal + overrides merge
prompts/             versioned prompt templates (jinja2, markdown). Part of frozen version.
schemas/             JSON Schemas for every artifact below
domains/<domain>/    domain pack (geology now; drilling built at test time)
chapters/<id>.yaml   chapter configs
runs/<chapter>/      all outputs of one chapter (committed: they are the deliverable)
overrides/<chapter>/ human corrections (JSON merge-patches), each logged in edits/
edits/journal.jsonl  manual edit log (who, when, what, minutes, commit)
docs/                TZ, architecture, playbook
```

Source books are NOT in git (size, publication ban). Path to them: env `KMD_DATA`
(default `~/kmd_data`), files referenced from chapter YAML relative to it.

## Stages and artifacts (`runs/<chapter>/`)

| # | Stage | Command | Reads | Writes |
|---|-------|---------|-------|--------|
| 0 | ingest | `kmd ingest CH` | chapter yaml, md, pdf | `units.json`, `pages/p<N>.png`, `source_pages.json` |
| 1 | layer | `kmd layer CH` | units, domain pack | `layer.json`, `coverage.json` |
| 1b | verify | `kmd verify CH` | layer, source_pages | `verify_report.json` (+ fails the build on hard errors) |
| 2 | route | `kmd route CH` | layer, domain pack | `routing.json` |
| 3 | scenes | `kmd scenes CH` | layer, routing | `scenes/<node_id>.json` (scene specs) |
| 4 | course | `kmd course CH` | layer, routing, scenes | `steps/<node_id>.json`, `tasks.json`, `cards.json`, `illustrations/*.svg|png` |
| 4b | site | `kmd site CH` | all of the above | `site/` (open `site/index.html` from disk) |
| 5 | video | `kmd video CH NODE --format short|long` | layer, scene | `video/<node_id>/{passport.json,script.json,*.mp4,*.srt}` |
| - | check | `kmd check PACKAGE_DIR --chapter CH` | external package + source | `findings.json` |
| - | all | `kmd run CH` | | stages 0–4b; stops with exit code 3 if LLM requests are pending |

Stage functions are idempotent: re-running reuses the LLM cache, so a rebuild after an
override costs zero LLM calls except for the nodes whose inputs changed.

### units.json (ingest)
Chapter split into units — the denominator of coverage.
```json
{"chapter":"latyshova","units":[
  {"id":"u017","kind":"paragraph|heading|figure|formula|table|example|problem|list",
   "page":91,"section":"§ 18","text":"...","figure_no":"21"|null}
]}
```
`source_pages.json`: `{"<page>": "<full markdown text of that PDF page>"}` for the chapter pages
(used by verify to find quotes).

### layer.json (the learning layer) — see `schemas/layer.schema.json`
```
{chapter, domain, schema_version, title, parts:[{id,title,node_ids}],
 nodes:[Node], order:[node_id...]}
```
Node (exact field names; text fields are `{"text":..., "by":"author"|"model"}` = `T`):
- `id` stable: `<domain_prefix>.<chapter>.<section>.<nn>` e.g. `geo.latyshova.s20.03`
- `title_book` (str), `title_beginner` (3–7 words)
- `difficulty`: `{primary: "М|В|И|Ф|П|Пр|Н|Р", secondary: same|null, threshold: str}`
- `order_rationale`: T — why this node comes at this point
- `layers`: `{mechanism: T, practice: T, nuances: T, deeper: [{title, text, by}]}`
- `claims`: `[{id, kind: "observation|inference|assumption", text, quote, page, unit_ids:[], by}]`
  `quote` is verbatim from the book; `text` is the plain-language restatement.
- `worked_examples`: `[{id, page, title, condition, steps:[str], result, numbers:[str], unit_ids}]`
- `book_problems`: `[{number, text, figure: str|null, page, unit_id}]`
- `terms`: `[{term, definition, en, page, by}]`
- `formulas`: `[{id, latex, meaning, vars:[{symbol, meaning, unit}], page}]`
- `tables`: `[{id, caption, page, columns:[str], rows:[[str]], ocr_fixes:[str]}]`
- `figures`: `[{number, page, caption, role: "example|problem|illustration", redraw: bool}]`
- `misconception`: `{text, correction, claim_ids, by}` | null
- `data_meaning`: `{text, inputs, outputs, breaks_where, hypotheses:[str], by}`
- `it_analogy`: `{text, breaks_where, by:"model"}`
- `current_practice`: T (how it is done today; model-written, marked)
- `inefficiency_lens`: `{inputs, manual_steps, judgment_points, time, typical_errors, by}`
- `links`: `[{to, type: "prerequisite|example|refutes_misconception|to_data"}]`
- `unit_ids`: units covered by this node

### coverage.json
`[{unit_id, page, kind, node_id|null, reason|null}]` — every unit maps to a node or has a
reason. `kmd verify` fails if any unit is missing.

### routing.json
`[{node_id, format: "short|long|interactive|data_practice|cards|text", difficulty,
   video_criteria:["time_change|invisible_visible|scale_jump|counterintuitive|cause_effect"],
   rationale, hook_only: bool}]`

### scenes/<node_id>.json (scene spec)
`{node_id, template, objects:[...], params:{...}, invariants:[str], assumptions:[str],
  exaggerations:[{what, factor}], frames:[{id, class:"A|B|C|D", provenance:"реальные данные|симуляция|схема", description, claim_ids}]}`
`template` names a scene template in `kmd/visuals/templates/` (one per difficulty pattern:
log_track, cross_section, pressure_diffusion, sequence/timeline, process_chain, ...).

### steps/<node_id>.json (step page), tasks.json, cards.json
See `schemas/step.schema.json`, `schemas/task.schema.json`. Blocks follow the TZ table
"Обязательные блоки страницы шага". Task types: `single|multiple|order|cloze|numeric`.
Each task has `claim_id` and `evidence` — a substring of the step text that contains the answer
(code-checked).

### video passport
`video/<node_id>/passport.json`: node card, script with timecodes and claim ids per phrase,
source table, scene spec ref, frame classes + provenance labels, exaggerations, prediction
question + transfer question, data/IT bridge, measured tempo (wpm), LUFS, ASR WER, sync.

## LLM layer (`kmd/llm.py`)

`llm.complete_json(run_dir, task, prompt, variables, schema)`:
- renders `prompts/<prompt>.md` (jinja2; `---system---` / `---user---` sections),
- cache key = sha256(prompt name + template text + rendered messages + schema),
- cache file `runs/<chapter>/llm/<task>/<key>.json` (request, response, provider, model, usage),
- provider from env `KMD_LLM_PROVIDER` = `anthropic|openai|queue` (auto: anthropic if
  `ANTHROPIC_API_KEY`, else openai if `OPENAI_API_KEY` (+`OPENAI_BASE_URL` for OpenRouter/vLLM/Ollama),
  else `queue`),
- `queue` provider writes `runs/<chapter>/llm/pending/<task>__<key>.json` and raises
  `PendingLLM`; stages collect pending items and the CLI exits with code 3.
  A worker (human or agent) answers with `kmd llm answer <pending-file> <response.json>`
  which validates against the schema and moves it into the cache.
- responses are always validated with jsonschema; API providers retry with the error.

Dev runs of this repo were answered by Claude Opus 5.5 through the queue (see MANIFEST.yaml).

## Domain pack (`domains/<domain>/`)
`pack.yaml` (name, id prefix, language, voice), `glossary.json` (RU/EN), `misconceptions.json`,
`physics_checklist.md`, `it_bridges.json`, `styleguide.json` (lithology/fluid/curve colors, axis
conventions), `stress_dict.json` (term -> pronunciation for TTS), `difficulty_types.yaml`
(8 types, video-worthiness hints, scene templates per type), `personas.md`.
`kmd domain new <id> --from-chapter CH` drafts a pack for a new domain with the LLM (timed).
