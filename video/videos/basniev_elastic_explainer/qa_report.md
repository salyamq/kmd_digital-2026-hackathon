# QA report — basniev_elastic_explainer

Summary: ❌ fail: 1, ℹ️ info: 2, ☐ manual: 1, ✅ pass: 24, ⚠️ warn: 1

## Truth

| | check | details |
|---|---|---|
| ❌ | Every claim maps to a page + verbatim quote | {'no_quote': 8}; chapter pages not provided — quotes cannot be checked |
| ✅ | Every factual narration line has a source |  |
| ✅ | Every spoken number is in the source table |  |
| ✅ | Every on-screen number is sourced (claim/dataset/model/axis) |  |
| ℹ️ | Values not taken from the chapter are marked as assumptions (listed in the passport) | 16 assumptions |
| ✅ | front marker in map and chart at the model's front radius | 3/3 sampled frames within 5 px (worst 0.6 px); 2 frames without probe |
| ✅ | drawn curve head is at the data point for that time | 2/2 sampled frames within 5 px (worst 0.5 px); 3 frames without probe |
| ✅ | front marker in map and chart at the model's front radius | 5/5 sampled frames within 5 px (worst 0.5 px); 0 frames without probe |
| ✅ | drawn curve head is at the data point for that time | 5/5 sampled frames within 5 px (worst 0.6 px); 0 frames without probe |
| ✅ | drawn curve head is at the data point for that time | 5/5 sampled frames within 5 px (worst 0.6 px); 0 frames without probe |
| ✅ | drawn curve head is at the data point for that time | 5/5 sampled frames within 5 px (worst 0.5 px); 0 frames without probe |
| ✅ | Scene-spec invariants hold (model/layout level) | 17 checks |
| ✅ | No AI-generated text, digits, axes or arrows: all text is composited from JSON | 0 AI clips generated; prompts checked for text/digit/diagram words |
| ✅ | Every AI clip starts/ends on a verified frame; no AI clip shows mechanism or data | no class D shots |
| ✅ | Provenance label on each frame matches how it was made |  |
| ✅ | ≥70% of screen time is class A/B (visual data/process) | A: 25%, B: 70%, T: 5% |
| ✅ | Text cards (class T) ≤ 25% of screen time | T: 5% |
| ✅ | Every mechanism/data line is shown on a visual template (class A/B/C) |  |
| ℹ️ | Visual shots with a question/fact strip beside the visual (overlay_card) | 49% of screen time |
| ✅ | ≤2 class D clips | 0 |

## Form

| | check | details |
|---|---|---|
| ✅ | One style, one theme, one subtitle style for the whole video | style F, fonts bundled in assets/fonts |
| ⚠️ | Subtitles readable on a phone (size, length, ≥0.6 s on screen), no overflow (wrapped to max width) | 52 chunks; too long: []; very short: 1 |
| ✅ | Subtitles synced to the voice (chunk inside its line's audio) | [] |
| ✅ | Stress/pronunciation of terms checked against the dictionary | dictionary entries: 50; glossary terms in narration without entry: [] |
| ✅ | Length within target 120-240 s | 137.9 s |
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

Machine time by stage (s): {'script': 0.02, 'shotlist': 0.3, 'specs': 0.24, 'models': 0.3, 'audio': 6.9, 'layout': 1.34, 'render': 115.94, 'overlays': 0.19, 'compose': 244.56, 'qa': 1.46, 'passport': 0.0}
Total machine minutes: 6.2
