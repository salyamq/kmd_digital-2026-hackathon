# QA report — gr_latyshova_short

Summary: ℹ️ info: 2, ☐ manual: 1, ✅ pass: 23

## Truth

| | check | details |
|---|---|---|
| ✅ | Every claim maps to a page + verbatim quote found in the chapter | {'verified': 11} |
| ✅ | Every factual narration line has a source |  |
| ✅ | Every spoken number is in the source table |  |
| ✅ | Every on-screen number is sourced (claim/dataset/model/axis) |  |
| ℹ️ | Values not taken from the chapter are marked as assumptions (listed in the passport) | 5 assumptions |
| ✅ | in rendered frames the curve point is at the tool's depth | 5/5 sampled frames within 4 px (worst 0.9 px); 0 frames without probe |
| ✅ | in rendered frames the curve point is at the tool's depth | 5/5 sampled frames within 4 px (worst 0.5 px); 0 frames without probe |
| ✅ | Scene-spec invariants hold (model/layout level) | 12 checks |
| ✅ | No AI-generated text, digits, axes or arrows: all text is composited from JSON | 0 AI clips generated; prompts checked for text/digit/diagram words |
| ✅ | Every AI clip starts/ends on a verified frame; no AI clip shows mechanism or data | no class D shots |
| ✅ | Гамма-каротаж (ГК) не излучает и не принимает «отражённое» излучение — он измеряет естественную радиоактивность пород. |  |
| ✅ | Provenance label on each frame matches how it was made |  |
| ✅ | ≥70% of screen time is class A/B (visual data/process) | A: 91%, T: 9% |
| ✅ | Text cards (class T) ≤ 25% of screen time | T: 9% |
| ✅ | Every mechanism/data line is shown on a visual template (class A/B/C) |  |
| ℹ️ | Visual shots with a question/fact strip beside the visual (overlay_card) | 55% of screen time |
| ✅ | ≤2 class D clips | 0 |

## Form

| | check | details |
|---|---|---|
| ✅ | One style, one theme, one subtitle style for the whole video | style F, fonts bundled in assets/fonts |
| ✅ | Subtitles readable on a phone (size, length, ≥0.6 s on screen), no overflow (wrapped to max width) | 34 chunks; too long: []; very short: 0 |
| ✅ | Subtitles synced to the voice (chunk inside its line's audio) | [] |
| ✅ | Stress/pronunciation of terms checked against the dictionary | dictionary entries: 50; glossary terms in narration without entry: [] |
| ✅ | Length within target 30-60 s | 56.4 s |
| ✅ | Hook comes in the first 3 s | first line 'hook' at 0.25 s |
| ✅ | Loudness about -16.0 LUFS | -16.0 LUFS |

## Coverage

| | check | details |
|---|---|---|
| ✅ | All requested visuals covered by templates |  |

## Mentor

| | check | details |
|---|---|---|
| ☐ | Mentor reviewed scene specs + source table before final render | see mentor_pack.md |

## Fixes log

No manual fixes recorded yet (add entries to fixes.json: {when, what, minutes}).

## Time

Machine time by stage (s): {'script': 0.04, 'shotlist': 0.28, 'specs': 0.33, 'models': 0.85, 'audio': 3.23, 'layout': 0.35, 'render': 28.06, 'overlays': 0.01, 'compose': 44.03, 'qa': 0.21, 'passport': 0.0}
Total machine minutes: 1.3
