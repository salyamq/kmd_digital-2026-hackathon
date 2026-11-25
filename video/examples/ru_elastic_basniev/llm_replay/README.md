Replay cache for `--planner replay`. These two files are what the LLM planner stage is expected to return for
this node (format defined in vidpipe/resources/prompts/*). They were written by Claude during development,
following those prompts, because no LLM API key was available in the build environment. The pipeline treats
them exactly like a live LLM answer: same validation, same fallbacks. With ANTHROPIC_API_KEY (or an
OpenAI-compatible endpoint) set, `--planner llm` generates them live instead.

v3: restructured so text cards are ≤ 25 % of screen time and every mechanism line has a visual: the myth /
question / reveal sit beside the pressure-field simulation (S1), the three equations beside Δp(r) profiles at
1 h / 1 day / 10 days computed from the main formula (S3), and the data-engineer bridge beside the Volve build-up
(S7). Only the transfer question (S8) is a full-screen card. No chapter pages were provided → DRAFT mark stays.
