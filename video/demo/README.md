# Demo videos (9:16 shorts, offline RHVoice voice)

| file | node | planner | size | QA |
|---|---|---|---|---|
| `gr_latyshova_short.mp4` (56 s) | `examples/ru_gr_latyshova` — real chapter, Латышова 1991 § 12 | replayed plan (`llm_replay/`) | 6.6 MB | all pass, every claim verified on its page, no DRAFT |
| `unseen_ru_drilling_mud.mp4` (54 s) | `tests/fixtures/ru_drilling_mud` — unseen node, synthetic pages | rule planner (no LLM) | 5.2 MB | all pass; mechanism shown on the Volve caliper (CALI) log |

Built with RHVoice; the team's laptop build uses Yandex SpeechKit (`--tts yandex`, voice `alexander`).
The 16:9 Basniev explainer (2 min 18 s, 22 MB) is not committed: rebuild it with the command in `../README.md`.
