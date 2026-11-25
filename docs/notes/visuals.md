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
