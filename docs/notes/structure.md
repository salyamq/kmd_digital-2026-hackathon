# Structure stages: ingest → layer → verify → route; checker; domain pack

Owner: STRUCTURE agent. Code in `kmd/{ingest,layer,verify,route,checker,domain}`, prompts `prompts/{layer_*,route_*,check_*,domain_*}.md`.

## Commands
```
python -m kmd ingest CH            # units.json, source_pages.json, pages/p<N>.png
python -m kmd layer CH             # queue: layer_extract_NN (one per chunk) -> layer_graph -> layer.json, coverage.json
python -m kmd verify CH            # verify_report.json; exit 2 on hard errors
python -m kmd route CH             # routing.json (one LLM request + code constraints)
python -m kmd check PKG --chapter CH [--out F]   # external package review -> findings.json
python -m kmd domain ID --from-chapter CH        # LLM-drafted domain pack -> domains/ID/ (+ BUILD.json timing)
# queue worker helpers (answering requests as the LLM):
python -m kmd.layer.show_request PENDING.json        # readable units of a layer_extract request
python -m kmd.layer.check_answer PENDING.json ANS.json  # schema + quotes on page + numbers + coverage, before `kmd llm answer`
python -m kmd.layer.migrate CH                        # re-key cached answers after display-only prompt changes
python tests/calibration/score.py FINDINGS KEY        # checker calibration score
```

## Ingest (`kmd/ingest`)
- md split by `<!-- page N -->` (N = PDF page). Segment cut by start/end marker lines (normalized, `#`-headings preferred), markers may be mid-page; end marker on page b+1 is allowed.
- Vision figure descriptions (`----` / `━━━ FORMAT …` / `KEYWORDS:`; closing `----` may be missing) are attached to the nearest figure caption as `description` (`description_by: vision`) and **removed from source_pages.json** — they are not author text, so quotes/numbers are never verified against them.
- Running headers/footers (repeated edge lines on ≥3 pages) and bare page numbers removed from units and source_pages.
- Unit kinds: heading, paragraph, list, formula, table, figure, example, problem, **fragment** (short orphan labels like «Уровень моря» — auto-covered with reason). Paragraphs continued across a page break / figure are merged (`page_end`, `page_breaks:[{offset,page}]` → shown to the LLM as ⟦стр. N⟧). Tables continued on the next page merged; table caption lines merged into the table unit (`table_no`, `caption`). Problems: under «Задачи»-type headings, or numbered items ≥10 continuing the previous problem numbering. `ocr_suspect` flags mojibake (Latin look-alikes).
- Section codes: `§ N` → sN, `N.N` → sN_N, `Глава V` → ch5, collisions → `ch24s1`; chapters without numbered sections → top-level headings become x1, x2…

## Layer (`kmd/layer`)
- Chunks ≈9 000 source chars (small sections grouped, big sections split at topic boundaries). Each chunk → `prompts/layer_extract.md` (schema `schemas/layer_extract.schema.json`). The LLM writes only what needs understanding; code copies problem texts, table cells (`parse_md_table`), figure captions, pages, ids.
- `prompts/layer_graph.md`: order for a novice, parts, links, order_rationale, merges; code shows each node's "uses terms defined elsewhere" to help ordering.
- Node id `<prefix>.<chapter>.<section>.<nn>`; section from the node's first unit; nn by book order within the section (stable when the cache is stable).
- Additive node fields (beyond ARCHITECTURE): `section`, `procedure:[str]`, `pages`, `worked_examples[].example_no/by`, `book_problems[].ocr_suspect`, `tables[].number/page_end/unit_id`, `figures[].unit_id/scan`.
- Coverage: every unit → node, or reason (headings follow the next covered unit; fragments, OCR-garbled and LLM-skipped units get reasons).

## Verify (`kmd/verify`)
- `find_quote(quote, page, chapter)`: normalization (case, ё/е, dashes, quotes, markdown/LaTeX wrappers, hyphenation, spaces around punctuation); exact substring on page, page±1 concatenation, else rapidfuzz partial_ratio ≥ 90; reports `other:<p>` when the quote is on another page.
- `check_text_numbers(text, chapter)`: every number in a learner-visible field must occur in the chapter source (units + pages); references («стр. 42», «рис. 1.24», «§ 20», «пример 46», «(23.4)») and exponents/indices are ignored; trivial 0–10, 100 allowed.
- Report: schema, unique ids, order/parts, links, unit ids, quotes, numbers in every field (with `by`), coverage, problem/example units represented, term-before-definition (warning; stem-based heuristic, noisy on short terms).

## Route (`kmd/route`)
One request per chapter (`prompts/route_format.md`, formats/criteria/templates read from `difficulty_types.yaml`). Code enforces: video only with a video criterion; no tables/≥2 formulas in shorts; ≥1 data_practice per chapter; hooks ≤ 20 % of videos.

## Checker (`kmd/checker`)
- Input: `schemas/external_package.schema.json` (claims with quote/page, scripts with lines, scenes, frames); loader also accepts loose JSON lists or text lines.
- Code checks: quote on wrong page (`wrong_page`, sev 1, fix = right page), quote not found → hint, numbers not in chapter → hint, frame rules (generated C/D frame asserting facts → `frame_error` sev 3; negated mentions «без надписей» ignored).
- Retrieval: top-3 chapter units by stem overlap (+page bonus) shown with pages. LLM review in batches of 10 (`prompts/check_review.md`): error taxonomy, severity 3/2/1, precision rules (contradiction with source / checklist / misconception only; surprising-but-true → ok; unsure → not reported).
- Precision guard: a source-based finding is kept only if its evidence quote is found in the chapter (page taken from where it is found).
- Calibration: `tests/calibration/baraboshkin_pack/` (29 items: 17 true incl. surprising ones, 9 injected errors of 8 types incl. wrong page, scene and frame errors) + `baraboshkin_key.json`. Result: 9/9 found with fix+page and correct type, 0 false alarms (after fixing one code false alarm on «без надписей и цифр»). **Caveat:** the pack and the LLM answers were produced by the same agent, so this measures the pipeline mechanics, not blind LLM recall; with an API model, rerun and compare.
- Blind-ish calibration (2026-11-25): `tests/calibration/inject.py CH --seed S` takes ~25 random true layer claims of a chapter without a hand-written pack, plants rule-based errors (sign_flip, overgeneralization, lost_condition, wrong_number, wrong_scaling_law, measured_vs_derived, missing_caveat, outdated_as_current; types applied where the claim text allows) at ~25%, adds fixed script/scene/frame items, writes the key separately. The reviewer (me, acting as the LLM) answered from request content only without opening the key.
  | pack | items | errors | found (full/half) | type match | false alarms |
  |---|---|---|---|---|---|
  | vendelshtein s11 | 30 | 7 (4 blind claims + 3 templated) | 7/0 | 7/7 | 0 |
  | barenblatt s5 | 30 | 8 (5 blind claims + 3 templated) | 8/0 | 8/8 | 0 |
  Blind claim part: 9/9 found with fix + page + evidence quote, 0 false alarms on 41 true claims. Templated items (IT analogy, scene, frame) are known to the reviewer and only test the pipeline. Generic fixes from this round: injector cut conditions at the dot inside formula numbers «(II.109)» (fixed regex); scorer required a page for `it_analogy_without_limit`/`outdated_as_current`, which have no source page (fixed). No prompt change was needed. Honest limits: the injected edits are rule-based and fairly visible (e.g. «всегда», reversed inequality, figure number); the reviewer knows the injection rules; measured_vs_derived / missing_caveat / outdated were not drawn by these seeds.

## Domain pack (`domains/geology`) and `kmd domain new`
Files: pack.yaml (id_prefix geo, audience, data_context), difficulty_types.yaml (8 types: description, signals, typical formats, video-worthiness criteria, scene templates, pitfalls; formats; criteria), misconceptions.json (20 TZ + 9 ours), physics_checklist.md (TZ + ours marked), glossary.json (92 RU/EN terms), it_bridges.json (13, each with breaks_where), personas.md (3 invented personas, marked as ours). `kmd domain new` drafts glossary, misconceptions, checklist, IT bridges, stress dict (visuals agent format: entries with kind abbr/symbol/stem), pack meta and per-type domain hints from a chapter digest in one LLM request; copies difficulty types/personas/styleguide from geology; writes BUILD.json with timings.
- End-to-end run (2026-11-25): `kmd domain demo_hydro --from-chapter barenblatt` → 1 pending request (prompt 29.7k chars) → answered (40 terms, 10 misconceptions, checklist, 8 IT bridges, 30 stress entries) → rerun writes `domains/demo_hydro/` (10 files) in 0.0 s code time. Wall time from first command to written pack: 49 s (08:03:39→08:04:28 UTC), including answering. Pack loads via `kmd.config.domain_pack`. Note: the CLI verb is `kmd domain ID --from-chapter CH` (no `new`). `demo_hydro` is a demo pack (underground hydromechanics), not used by any chapter.

## Results (dev runs, answers by Claude Opus 5.5 / GPT workers via queue)
| chapter | units | nodes | claims | quotes exact/fuzzy/missing | bad numbers | errors |
|---|---|---|---|---|---|---|
| latyshova | 167 | 34 | 269 | 268/1/0 | 0 | 0 |
| basniev | 349 | 60 | 420 | 417/3/0 | 0 | 0 |
| kuznetsov | 103 | 56 | 465 | 465/0/0 | 0 | 0 |
| baraboshkin (control) | 67 | 18 | 116 | 116/0/0 | 0 | 0 |
| barenblatt (control) | 167 | 19 | 114 | 114/0/0 | 0 | 0 |
| vendelshtein (control) | 159 | 32 | 193 | 193/0/0 | 0 | 0 |

## Known gaps / lessons
- Ingest: a footnote between the two halves of a paragraph split by a page break blocks the merge (barenblatt p.38–39); the LLM sees both halves in one chunk, so content is not lost.
- OCR damage stays in source: subscripts in Latyshova (ρп/ρн/kв mixed), problems 101–102 mojibake (flagged, not quoted), table typos (listed as `ocr_fixes`). Formulas in layer are re-typed by the LLM with a note when indices were restored by meaning.
- Kuznetsov/Basniev workers made very fine-grained nodes (56/60); graph merges were not used. Term-before-definition warnings are heuristic.
- `term_before_definition` is a warning only; course text should define a term at first use anyway.
- llm/pending is queue state — keep it out of git (suggest `runs/*/llm/pending/` in .gitignore).

## PDF-only ingest (`kmd/ingest/pdf2md.py`, 2026-11-25)
- If the chapter yaml has no `book.md` (or the file is missing, or `KMD_FORCE_PDF=1`), ingest converts the chapter pages ±1 of `book.pdf` into `runs/<ch>/source.md` with `<!-- page N -->` markers (+ `pdf2md_report.json`: source and quality per page), then ingests as usual.
- Per page: text layer (pymupdf dict: soft hyphens, line-end hyphenation, letter-spaced words joined, small raised digits → superscripts, headings by font size / bold numbered lines, formula debris kept as `$$ … $$`) if quality is good (≥150 chars, letters ≥0.6, garbled tokens ≤4 %, formula debris ≤20 %); else OCR: vision LLM (`prompts/ingest_ocr.md`, one cached request per page, page PNG at 200 dpi) or `KMD_PDF_OCR=tesseract` (rus+eng, installed via apt) or `off`. `KMD_PDF_MODE=auto|text|ocr`.
- Start/end markers: if exact match fails, fuzzy match (difflib ≥0.8 on the normalized line + next two lines), so `## 1.2 Дельты` is found in OCR text without `#`.
- Validation vs provided md (`python -m kmd.ingest.pdf_eval CH [pages] --ocr off|tesseract`, word-sequence similarity, math/markup/figure descriptions removed): text layer vendelshtein 0.91 (21 pages), barenblatt 0.82, latyshova 0.85, basniev 0.80 (formula pages: 23/29 flagged for OCR); scan baraboshkin with tesseract 0.97/0.95/0.98 on text pages, 0.45 on a figure page. Low scores are mostly figure text and formulas, partly errors in the reference md. Scratch configs `chapters/_pdftest_{vendelshtein,baraboshkin}.yaml` ingest end to end (fuzzy start marker found). Existing chapters' units/source_pages unchanged (they keep using md).
- Vision-LLM OCR path checked only up to the queued request (image path + prompt); no page was answered (budget).

## Book analyses (organizers, LLM-generated)
- Chapter yaml `analysis: analyses/<ch>.md` (under KMD_DATA); `kmd.ingest.analysis(ch)` → dict | None; `kmd.ingest.analysis_context(ch)` → meta, prerequisites, chapter dependencies, key definitions, weak sections (for a «Перед главой» page).
- Used only in the checker prompt (weak sections ≤8, key definitions ≤15, labelled as non-author hints). Not used in layer/course prompts (cache keys unchanged). The check_review template changed, so old check caches no longer match (calibration results above stay as recorded).
