Replay cache for `--planner replay`. These two files are what the LLM planner stage is expected to return for
this node (format defined in vidpipe/resources/prompts/*). They were written by Claude during development,
following those prompts, because no LLM API key was available in the build environment. The pipeline treats
them exactly like a live LLM answer: same validation, same fallbacks. With ANTHROPIC_API_KEY (or an
OpenAI-compatible endpoint) set, `--planner llm` generates them live instead.

v3 (real chapter): rewritten against Латышова 1991, § 12, PDF pp. 64–69. Every factual line cites node claims
c1–c12 (page + verbatim quote); shot S2 draws table 12 (p. 65) from its cells. 5 shots: S1 and S4 are
`overlay_card` scenes (myth / question / facts / formula 40 beside the Volve GR log), S2 the table chart, S3 the
logging scene (bottom-to-top, p. 64), S5 the transfer question — the only full-screen card (9 % of screen time).
Lithology of the Volve formations and the choice of the two reference beds are assumptions (listed in the passport).
