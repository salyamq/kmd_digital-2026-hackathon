# Known limitations and TODO

## Known limitations

**Truth / QA**
* Quotes are matched against the text layer of the pages. A PDF with a broken text layer (wrong encoding,
  Latin/Cyrillic look-alikes) makes correct quotes fail; scans go through OCR, where only a ≥ 92 % fuzzy match is accepted.
* Page numbers are file page numbers (PDF page index for extracted PDFs), not the printed numbers of the paper book.
* The physics anti-example rules are regexes from the domain pack: they catch phrasings, not meaning.
* Lithology of real wells (Volve formations) and choices such as "which beds are the reference beds" are
  assumptions; they are listed in `passport.json → open_questions` and must be confirmed by a mentor.
* `bare_minimal` and nodes without data/formula/lithology words fall back to text cards; QA then fails the
  "cards ≤ 25 %" rule on purpose (reported as `needs_visual` in the coverage report).

**Planning**
* The rule planner builds one visual scene per video (hook → mechanism on the same scene). Multi-scene plans
  (insets, several models, before/after) need the LLM planner or `visual_hints` in the node.
* The LLM planner was not run against a live model in the build environment (only replayed plans and a mock
  server). Default model names in `vidpipe/llm.py` should be checked against the provider before use.
* Word budget assumes ~2 words/s (RHVoice and SpeechKit at speed 1.0). Very different voices/speeds change length.

**Audio**
* Russian number agreement: with `--tts-numbers words` num2words gives nominative forms; SpeechKit's own reading
  (`raw`, the default for Yandex) is usually better.
* RHVoice is not available on macOS (use Yandex, espeak-ng or `--tts none`).

**Rendering**
* Determinism is per machine: rebuilding gives an identical mp4, but different ffmpeg/x264/TTS versions give
  different bytes (same content).
* Class C (photo) and D (AI) frame labels are outside the organizers' label set — flagged in QA for a team decision.
* A 2–3 min explainer renders in ~6 min on a laptop CPU (single process).

**Data**
* Only three Volve files are bundled (one well's logs, its formation tops, daily production). Other datasets:
  drop LAS/CSV files into a folder and pass `--data <dir>` (add licence/units to a `catalog.json`).
* The official Equinor Open Data Licence PDF is not bundled yet (see `data/LICENCE-DATA.md`).

## TODO

- [ ] Run `--planner llm` end-to-end with the team's LLM and save its answers as replay caches.
- [ ] Accept the learning layer's node export directly (agree on one schema; INTERFACE.md §1 lists accepted aliases).
- [ ] Real domain pack from the team: stress dictionary for all terms, glossary with abbreviations, physics checklist, licensed photos.
- [ ] Add the Equinor licence PDF to `data/` before the repo goes public.
- [ ] Chapter pages for Basniev → remove the DRAFT mark from the explainer.
- [ ] Mentor review loop: record fixes in `videos/<id>/fixes.json` (minutes per fix) and report them in the passport.
- [ ] Parallel rendering of shots (multiprocessing) to cut explainer build time.
- [ ] Optional Manim backend behind the same layout JSON.
- [ ] Wire `wan_local` (ComfyUI Wan 2.2 FLF2V) or another first/last-frame video model for class D clips.
- [ ] Text-box collision check in QA (labels currently avoid each other by placement, not by a QA assertion).
- [ ] CI: `python -m vidpipe selftest --quick` on every push.
