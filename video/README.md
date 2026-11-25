# video/ — vidpipe: node.json → verified explainer video

`vidpipe` turns one node of the learning layer into a short Russian (or English) explainer video plus a
machine-readable passport and a QA report. Every fact in the narration is traced to a **page + verbatim quote** of
the chapter, motion and curves come from **state models or real open data** (Equinor Volve), and all text on screen
is composited from JSON (no AI-drawn text, numbers or diagrams).

```bash
python -m vidpipe make --node node.json --pages chapter_pages/ --domain domain_pack/ --format short --style F
# -> videos/<id>/08_final/<id>.mp4  +  passport.json  +  qa_report.md
```

Nothing in the code is topic-specific: book, chapter, domain and visuals come from the inputs. The contract for
those inputs (node.json fields, quote rules, domain pack, CLI flags, output files) is in **[INTERFACE.md](INTERFACE.md)**.
Limitations and the TODO list: **[TODO.md](TODO.md)**.

| folder | what |
|---|---|
| `vidpipe/` | the package: CLI, planners (rule + LLM), state-model evaluator, scene templates (`templates/`), Cairo renderer, text layer, QA, TTS adapters; `resources/` = prompts, themes, legend, `video_models.json`, `tts_prices.json`, Yandex voices |
| `examples/` | demo nodes (`ru_gr_latyshova` = real chapter, `ru_elastic_basniev`, `en_decline_unseen`, `bare_minimal`) + `domain_pack_demo` |
| `tests/` | unit tests + `fixtures/` (two unseen nodes with synthetic pages) used by `selftest` |
| `scripts/` | `extract_pages.py` (PDF → page files), `tts_smoke.sh` (Yandex voice test) |
| `data/` | small Volve subset (LAS 2.6 MB, CSV 2.4 MB) + `catalog.json` + [licence notice](data/LICENCE-DATA.md) |
| `assets/fonts/` | Inter, JetBrains Mono (SIL OFL 1.1, licence files included) |
| `videos/` | planning files of two reference builds (script, shots, specs, passport, QA) — media is git-ignored |
| `demo/` | two short rendered demo videos |
| `docs/` | template contact sheets, latest selftest report |

---

## Install

Python **3.9 – 3.13** (`requirements.txt` pins one tested set for 3.9–3.12 and one for 3.13; full selftest passed on 3.9.25 and 3.13.18). Run every command from this `video/` folder.

**macOS (Homebrew)**

```bash
brew install ffmpeg cairo pkg-config poppler espeak-ng tesseract tesseract-lang
cd video
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # pycairo builds against Homebrew's cairo (needs pkg-config)
```

RHVoice (the offline Russian voice) has no Homebrew formula: on macOS use Yandex SpeechKit (`--tts yandex`),
`espeak-ng` (robotic, `--tts espeak`) or `--tts none` (silent, timing from word count).

**Ubuntu / Debian**

```bash
sudo apt-get install -y ffmpeg libcairo2-dev pkg-config python3-dev python3-venv poppler-utils \
     rhvoice rhvoice-russian rhvoice-english tesseract-ocr tesseract-ocr-rus
cd video
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

(`rhvoice` packages come from Ubuntu universe or the RHVoice PPA. Optional: `pip install -r requirements-optional.txt`.)

Check the setup: `python -m vidpipe selftest --quick` (≈ 1 min, no voice needed).

## Configure keys (.env)

```bash
cp .env.example .env      # then fill in only what you use; .env is git-ignored
```

| variable | for |
|---|---|
| `YANDEX_API_KEY` | `--tts yandex` (Yandex SpeechKit API v3, service-account API key) |
| `YANDEX_TTS_ENDPOINT` | other region, e.g. Kazakhstan `https://tts.api.ml.yandexcloud.kz` |
| `FAL_KEY`, `VIDPIPE_VIDEO_MODEL` | `--ai-video fal` (paid AI clips for class D atmosphere shots; off by default) |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (+ `VIDPIPE_LLM_MODEL`, `VIDPIPE_LLM_BASE_URL`) | `--planner llm` |

Keys are read from the environment or `.env` and are never printed or written to logs. Without a Yandex key
`--tts yandex` falls back to RHVoice with a warning. Yandex voice test: `bash scripts/tts_smoke.sh`.

## Run

```bash
# 1. unseen node, rule planner, no LLM — passes QA with its (synthetic) pages
python -m vidpipe make --node tests/fixtures/ru_drilling_mud/node.json --pages tests/fixtures/ru_drilling_mud/pages \
       --domain examples/domain_pack_demo --format short --style F --planner rule

# 2. real chapter (Латышова 1991, § 12): first extract the pages from the PDF (book text is not in git)
python scripts/extract_pages.py --pdf <Латышова_1991.pdf> --pages 64-69 --out examples/ru_gr_latyshova/pages
python -m vidpipe make --node examples/ru_gr_latyshova/node.json --pages examples/ru_gr_latyshova/pages \
       --domain examples/domain_pack_demo --format short --style F \
       --planner replay --llm-cache examples/ru_gr_latyshova/llm_replay --tts yandex --id gr_latyshova_short

# 3. re-voice / re-render a committed reference build without re-planning (extract the pages first, see 2,
#    otherwise QA cannot check the quotes and the video gets the DRAFT mark)
python -m vidpipe rebuild videos/gr_latyshova_short --from audio --tts yandex --voice alexander

# 4. 16:9 explainer from a replayed plan (no pages → DRAFT mark)
python -m vidpipe make --node examples/ru_elastic_basniev/node.json --domain examples/domain_pack_demo \
       --format explainer --planner replay --llm-cache examples/ru_elastic_basniev/llm_replay --id basniev_elastic_explainer

# preflight / library / preview
python -m vidpipe check --node N.json --pages P/ --domain D/
python -m vidpipe templates
python -m vidpipe preview videos/<id>
```

A short (9:16, 30–60 s) takes about 1 minute on a laptop CPU; a 2–3 min explainer about 6 minutes.

## Where outputs go

`videos/<id>/` (or `--out DIR`): **`08_final/<id>.mp4`**, `passport.json`, `qa_report.md`, `qa.json`,
`source_table.json`, `coverage_report.md`, `mentor_pack.md`, plus stage folders. Details: INTERFACE.md §8.
Only the planning files (`00_brief` … `03_scene_specs`, reports) are meant for git; renders, audio, overlays,
final mp4 and API call logs are git-ignored and re-created by `rebuild`.

## How it works (one paragraph)

Stages `script → shotlist → specs → models → audio → layout → render → overlays → compose → qa → passport`; each
writes files and can be re-run alone (`rebuild --from/--only`). The planner (rules, or an LLM with the prompts in
`vidpipe/resources/prompts/`) writes the narration with sources and a shot list of **scene templates** with
**state models** (formula / PDE / LAS / CSV / table). Templates turn one state array per shot into the picture,
the chart and the labels, so e.g. the curve point is always at the logging tool's depth — QA checks this on
rendered frames via probe colours. The text layer (titles, cards, labels, subtitles, provenance chips) is drawn
separately and composited last. QA = truth (quotes, numbers, sources, physics anti-examples, frame invariants) +
form (subtitles, stress dictionary, length, loudness) + coverage (missing visuals).

## Tests

```bash
python -m vidpipe selftest            # ≈ 6 min, writes selftest_out/selftest_report.md
python -m vidpipe selftest --quick    # ≈ 1 min: templates + unit tests + truth-level mutation test
python -m unittest discover -s tests  # unit tests only
```

Last run (Python 3.9.25, pinned requirements, RHVoice) — `docs/selftest_report.md`:

| part | result |
|---|---|
| templates (15 drawable templates × 9:16 + 16:9) | PASS — 30 renders |
| unit tests | PASS — 21 tests |
| unseen node: gas slug catcher (formula → chart) | PASS — 53.8 s, B 92 % / T 8 %, all claims verified |
| unseen node: drilling mud (caliper → Volve CALI log) | PASS — 54.4 s, A 88 % / T 12 %, all claims verified |
| mutation: wrong number + fake quote | PASS — QA fails `claims_verified` and `spoken_numbers`, DRAFT appears |
| robustness: `--from` with missing outputs | PASS — fails fast naming the stage; folders re-created |
| determinism: rebuild twice | PASS — identical mp4 SHA-256 |

## What is stubbed or not exercised

| part | status |
|---|---|
| LLM planner (`--planner llm`) | Anthropic and OpenAI-compatible adapters implemented, tested only against a local mock server. The demo plans in `examples/*/llm_replay/` were written by Claude following the prompts and are replayed (`--planner replay`). |
| Yandex SpeechKit TTS | real adapter; verified by the team on a laptop (voice `alexander`, KZ endpoint) and by mocked unit tests |
| AI video, class D (`--ai-video fal`) | adapter written, never called against fal.ai (no key); default `none` = deterministic cross-zoom between two verified frames, $0. `wan_local` is a placeholder. |
| Silero TTS | adapter written, not executed |
| Class C photos | `photo` template works; the demo domain pack has no licensed photos |
| Renderer | Cairo draw-list renderer instead of Manim (deterministic, frame-exact sync, probe-based QA) |
| Demo domain pack | small stand-in (stress dictionary, glossary); the team's real pack goes in `--domain` |
