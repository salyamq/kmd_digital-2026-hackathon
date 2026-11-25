"""Score checker findings against a calibration key.

    python tests/calibration/score.py tests/calibration/baraboshkin_pack/findings.json tests/calibration/baraboshkin_key.json

Scoring mirrors the TZ: a hit counts 1 with correct fix+page (we approximate: fix present and page present
for source-based errors), 0.5 otherwise; any finding on a true item is a false alarm.
"""
import json
import sys

f = json.load(open(sys.argv[1]))
key = json.load(open(sys.argv[2]))
found = {x["target_id"]: x for x in f["findings"]}
errors = {k: v for k, v in key.items() if v}
hits, half, fa, miss, type_ok = 0, 0, [], [], 0
for k, v in errors.items():
    x = found.get(k)
    if not x:
        miss.append(k)
        continue
    full = bool(x.get("fix")) and (x.get("page") is not None or v["type"] in ("frame_error", "it_analogy_without_limit", "outdated_as_current"))
    hits += 1 if full else 0
    half += 0 if full else 1
    type_ok += x["error_type"] == v["type"]
for k in found:
    if k not in errors:
        fa.append(k)
score = hits + 0.5 * half
print(f"errors={len(errors)} items={len(key)} found_full={hits} found_half={half} missed={miss} false_alarms={fa}")
print(f"recall={(hits + half) / len(errors):.2f} credit={score}/{len(errors)} type_match={type_ok}/{hits + half} precision={(hits + half) / max(1, hits + half + len(fa)):.2f}")
