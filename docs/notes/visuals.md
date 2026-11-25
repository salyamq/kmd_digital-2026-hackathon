# Visuals & video (owner: visuals agent)

## Illustration API (for the course stage)

```python
from kmd import visuals
visuals.catalog()            # [{name, title, description, use_for, class, provenance, animatable, params_schema, example}]
visuals.catalog_text()       # compact Russian text of all templates (+schemas, examples) to paste into an LLM prompt
visuals.check(name, params)  # [{level, code, message}] invariant issues (physics checklist), no rendering
visuals.render_illustration(spec, out_dir, fmt="svg")
# -> {path, alt, caption, class, provenance, redrawn_from, exaggerations, template, claim_ids, issues}
# raises visuals.InvariantError (has .issues) when params break an invariant -> ask the LLM to fix params
```

`spec` = `schemas/illustration.schema.json`:
`{id, template, params, caption, claim_ids, [node_id, title, alt, class, provenance, redrawn_from:{figure,page}, exaggerations, size: wide|tall|square|[w,h], t]}`.

On the picture itself the renderer puts: provenance badge (top-left), title, legend, red footer
«не в масштабе: вертикальный масштаб ×N; …» (computed from the real axes geometry), «перерисовано по
рис. N, стр. M» (from `redrawn_from`), and the named convention (e.g. «конвенция: международная (API)»).
Caption gets «(перерисовано по рис. N, стр. M)» appended automatically. SVG text stays text (`svg.fonttype=none`).
Typical sizes: 10–200 KB per SVG (cross sections are rasterized inside the SVG).

## Templates (`kmd/visuals/templates/`, one state model each; `t∈[0,1]` animates)

| name | class/label | state model | t drives |
|---|---|---|---|
| log_track | B / симуляция | petrophysical forward model (Archie, SP from ρф/ρв, Wyllie, density, caliper/mud cake, micro-log) on a layered column; borehole + tool | tool depth (wireline: bottom → up), curves drawn to tool |
| cross_section | B / схема | layer-index field from thicknesses + structure + fault plane; fluids by horizontal GOC/OWC in the connected trap | contacts descend (trap filling) |
| pressure_diffusion | B / симуляция | exact (erf, −Ei line source, FD for radial p=const) and ПССС (R=√(rc²+4κt), l=√(2κt), l=2√(κt)) | time after start; p(r), p(t), plan synced |
| timeline_growth | B / схема | event sequence on a surface: deposit (sheet/wedge/lens/mound/prograde/fill), sea level, erode (unconformity), subside | event progress |
| radial_invasion | B / схема | radii of mud cake / flushed / invaded zone + R(r) profile | invasion front ∝ √t |
| plan_map | B / схема | z(x,y) of reservoir top (dome/anticline/monocline/points) + horizontal contacts | wells appear |
| crossplot | A / реальные данные (симуляция if only formulas) | points, digitized curves, formulas (safe eval), regions, thresholds, query point | curves drawn / query |
| comparison_bar | A / реальные данные | numbers from the chapter | bars grow |
| process_chain | B / схема | DAG of observation/inference/assumption/action nodes | nodes revealed in causal order |
| well_column | B / симуляция | hydrostatics ρgh, ECD, pore/frac gradients, gas kick in closed/open well (drilling domain) | bubble rises |

Invariants (examples): layer order/overlap, fluids only in permeable rock, gas→oil→water in one connected
reservoir, GOC above OWC, seal above reservoir, contact above crest, open trap warning, κ plausible, p > 0,
ECD ≥ mud density, casing OD decreasing with depth, deposits above sea level warning, formula safety.

Colors/hatches/curve conventions: `domains/<domain>/styleguide.json` (templates never hardcode them).
Book-figure redraws: use `crossplot` (digitized points / formula) or `log_track`/`cross_section` with params
read from the page image, plus `redrawn_from: {figure, page}`.

Tests: `.venv/bin/python -m pytest -q tests/test_visuals_*.py`.

## Scenes, redraws, video (added 2026-11-25)

- `kmd scenes CH [--node ID]`: for nodes routed short/long/interactive → LLM `scene_spec` → code checks
  (each view's params vs template schema + invariants, frame refs, claim ids, frame count, provenance set from
  the template) → `scene_fix` repair (≤2) → `runs/<ch>/scenes/<node>.json` with `checks`.
  Then the **redraw stage** (`kmd/visuals/redraw.py`) runs: figures with role example/problem or redraw:true →
  PDF crop (300 dpi) + page PNG → vision LLM `scene_redraw` (schema `redraw`) → invariants + control points from
  worked examples (point must land in the author's region) → `runs/<ch>/illustrations/redraw_<fig>.svg/.json`
  + index `redraws.json` (contract in the module docstring). Infeasible figures are recorded with the reason.
- `kmd video CH NODE --format short|long`: scene (built if missing) → `video_script` (+`video_script_fix`) with
  code rules (≤18 words, numbers in words, claim ids, hook first, prediction ?, transfer last, captions ≤8 words,
  abbreviations expanded, model assumptions said as such) → TTS per phrase (edge-tts ru-RU-DmitryNeural; if any
  phrase fails after retries the WHOLE video switches to local piper ru_RU-dmitri, then espeak-ng) → timeline
  (lead 0.35 s, gaps 0.28 s, prediction pause 1.3 s, caption ≥1.6 s, end hold 1.8 s) → −16 LUFS + limiter →
  frames (templates at model state t, 12.5 states/s, 4 processes, cached by code+scene hash) → H.264 +
  soft subtitle track + .srt → faster-whisper **medium** ASR: WER, terms, sync → `passport.json`.
- Env: `KMD_TTS_ENGINES` (default `edge-tts,piper,espeak-ng`), `KMD_TTS_RETRIES` (20), `KMD_ASR_MODEL` (medium),
  `KMD_VIDEO_FORCE=1` renders despite remaining spec/script errors.
- Known: edge-tts is throttled from this sandbox (≈30–90 % of new requests fail, content-dependent); cached
  phrases are reused, so re-running fills the cache. On-screen captions are key words; full text is in the
  toggleable subtitle track (TZ: «полный текст — в отключаемых субтитрах»).
- Template aliases for names in `domains/geology/difficulty_types.yaml`: see `ALIASES` in `kmd/visuals/illustrate.py`.
  No template yet for `pore_scale`, depth-broken log charts (fig. 73) or free-form facies bodies (kuznetsov 10.5).
