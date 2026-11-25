PY ?= .venv/bin/python
CH ?= latyshova
VIDEO_FORMAT ?= short
VIDEO_TTS ?= microsoft
TRAIN = latyshova basniev kuznetsov
CONTROL = vendelshtein barenblatt baraboshkin

.PHONY: setup run rebuild all train control site video test pending
setup:            ## create venv and install deps
	uv venv -q .venv -p 3.12 && uv pip install -q -p .venv -r requirements.txt
run:              ## full pipeline for one chapter: make run CH=latyshova
	$(PY) -m kmd run $(CH) $(if $(VIDEO_NODE),--video-node $(VIDEO_NODE) --video-format $(VIDEO_FORMAT) --tts $(VIDEO_TTS))
video:
	$(PY) -m kmd video $(CH) $(VIDEO_NODE) --format $(VIDEO_FORMAT) --tts $(VIDEO_TTS)
rebuild:          ## after an override: make rebuild CH=latyshova
	$(PY) -m kmd rebuild $(CH) $(if $(filter 1,$(VIDEO)),--video --tts $(VIDEO_TTS))
train:
	for c in $(TRAIN); do $(PY) -m kmd run $$c || exit $$?; done
control:
	for c in $(CONTROL); do $(PY) -m kmd run $$c || exit $$?; done
pending:
	$(PY) -m kmd llm pending
test:
	$(PY) -m pytest -q tests
	$(PY) -m unittest discover -s video/tests -t video
