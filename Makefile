PY ?= .venv/bin/python
CH ?= latyshova
VIDEO_FORMAT ?= short
VIDEO_TTS ?= microsoft
TRAIN = latyshova basniev kuznetsov
CONTROL = vendelshtein barenblatt baraboshkin

.PHONY: setup run rebuild demo-edit all train control site video library test pending
setup:            ## create venv and install deps
	uv venv -q .venv -p 3.12 && uv pip install -q -p .venv -r requirements.txt
run:              ## full pipeline for one chapter: make run CH=latyshova
	$(PY) -m kmd run $(CH) $(if $(VIDEO_NODE),--video-node $(VIDEO_NODE) --video-format $(VIDEO_FORMAT) --tts $(VIDEO_TTS))
video:
	$(PY) -m kmd video $(CH) $(VIDEO_NODE) --format $(VIDEO_FORMAT) --tts $(VIDEO_TTS)
library:
	$(PY) -m kmd library
rebuild:          ## after an override: make rebuild CH=latyshova
	$(PY) -m kmd rebuild $(CH) $(if $(filter 1,$(VIDEO)),--video --tts $(VIDEO_TTS))
demo-edit:        ## defense: make demo-edit CH=latyshova CLAIM=<claim id> OLD=1856 NEW=1857 [VIDEO=1]
	$(PY) -m kmd demo-edit $(CH) --claim $(CLAIM) --replace "$(OLD)" "$(NEW)" $(if $(filter 1,$(VIDEO)),--video)
train:
	for c in $(TRAIN); do $(PY) -m kmd run $$c || exit $$?; done
control:
	for c in $(CONTROL); do $(PY) -m kmd run $$c || exit $$?; done
pending:
	$(PY) -m kmd llm pending
test:
	$(PY) -m pytest -q tests
	$(PY) -m unittest discover -s video/tests -t video
