#!/usr/bin/env bash
# Smoke test for the Yandex SpeechKit TTS provider. Run on a machine that can reach tts.api.cloud.yandex.net:
#   bash scripts/tts_smoke.sh                     # male voice (alexander)
#   VOICE=dasha ROLE=friendly SPEED=1.05 bash scripts/tts_smoke.sh
# Needs YANDEX_API_KEY in the environment or in .env (repo root or vidpipe/). The key is never printed.
set -euo pipefail
cd "$(dirname "$0")/.."

VOICE="${VOICE:-alexander}"
ROLE="${ROLE:-neutral}"
SPEED="${SPEED:-1.0}"
OUT_DIR="${OUT_DIR:-.}"
PY="${PYTHON:-python3}"

$PY - <<'PYEOF'
import os, sys
from vidpipe.envfile import load_dotenv
load_dotenv()
if not (os.environ.get("YANDEX_API_KEY") or os.environ.get("YANDEX_IAM_TOKEN")):
    sys.exit("YANDEX_API_KEY not found in the environment or .env")
print("credentials: found (not shown)")
PYEOF

run() {  # $1 = out file, $2 = text, $3... = extra args
  local out="$1"; local text="$2"; shift 2
  echo
  echo "=== $out"
  $PY -m vidpipe tts --provider yandex --voice "$VOICE" --role "$ROLE" --speed "$SPEED" \
      --domain examples/domain_pack_demo --text "$text" --out "$OUT_DIR/$out" "$@"
}

# 1) stress marks: explicit '+' in the text + one word stressed by the dictionary (пьезопроводность)
run test.wav "Гл+ины, как правило, радиоакт+ивнее чистых песч+аников. Темп расхождения давления задаёт пьезопроводность пласта."

# 2) numbers: SpeechKit's own reading of digits vs our num2words expansion — listen and compare
NUM_TEXT="Давление выросло с 200 до 301 бара за 30 суток, а дебит упал на 15 процентов."
run test_numbers_raw.wav   "$NUM_TEXT" --numbers raw
run test_numbers_words.wav "$NUM_TEXT" --numbers words

echo
echo "Done. Listen to test.wav (stress), test_numbers_raw.wav vs test_numbers_words.wav (numbers)."
echo "If raw sounds right (correct case endings), keep the default: --tts-numbers auto (= raw for yandex)."
echo "Then: python -m vidpipe rebuild videos/<id> --from audio --tts yandex --voice $VOICE --role $ROLE --speed $SPEED"
