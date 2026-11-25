# vidpipe selftest

date: 2026-11-25 15:44

| part | result | details |
|---|---|---|
| templates | PASS | 30 renders (template × orientation); all ok |
| unit tests | PASS | 21 tests, 0 failures, 0 errors |
| unseen: ru_slug_catcher | PASS | 53.767 s video; overlay_card(B), overlay_card(B), overlay_card(B), question_card(T); QA {'claims_verified': 'pass', 'card_share': 'pass', 'mechanism_visuals': 'pass', 'ab_share': 'pass'}; shares B: 92%, T: 8%; built in 73 s |
| unseen: ru_drilling_mud | PASS | 54.4 s video; overlay_card(A), overlay_card(A), question_card(T); QA {'claims_verified': 'pass', 'card_share': 'pass', 'mechanism_visuals': 'pass', 'ab_share': 'pass'}; shares A: 88%, T: 12%; built in 73 s |
| mutation (wrong number + fake quote) | PASS | claims_verified=fail; spoken_numbers=fail; draft_mark=True |
| robustness (--from with missing outputs) | PASS | fails fast: True; folders recreated: True |
| determinism (rebuild twice) | PASS | rebuild 1 b1a1fb0dc70ba78e = rebuild 2 b1a1fb0dc70ba78e; make b1a1fb0dc70ba78e (same) |
