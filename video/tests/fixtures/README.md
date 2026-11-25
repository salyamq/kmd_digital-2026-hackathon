# Selftest fixtures — UNSEEN nodes

Two nodes the pipeline was never tuned on, used by `python -m vidpipe selftest` to show that the same code
handles a new topic end-to-end with the rule planner (no LLM, no hand-written plan):

| node | domain | expected visual path |
|---|---|---|
| `ru_slug_catcher` | gas gathering / gas treatment | formula in the node → `data_chart` (class B, simulation) |
| `ru_drilling_mud` | drilling | node mentions the caliper log → Volve LAS curve `CALI` → `depth_track` (class A, real data) |

The `pages/pNNN.txt` files are **synthetic chapter text written for these tests** (not taken from a book).
They exist so the truth gate can check "claim → page + verbatim quote" the same way it does for a real chapter.
Formula parameter values are marked as assumptions in the node, so they are listed in the passport.
