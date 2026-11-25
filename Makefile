PY ?= .venv/bin/python
CH ?= latyshova
TRAIN = latyshova basniev kuznetsov
CONTROL = vendelshtein barenblatt baraboshkin

.PHONY: setup run rebuild all train control site test pending
setup:            ## create venv and install deps
	uv venv -q .venv -p 3.12 && uv pip install -q -p .venv -r requirements.txt
run:              ## full pipeline for one chapter: make run CH=latyshova
	$(PY) -m kmd run $(CH)
rebuild:          ## after an override: make rebuild CH=latyshova
	$(PY) -m kmd rebuild $(CH)
train:
	for c in $(TRAIN); do $(PY) -m kmd run $$c || exit $$?; done
control:
	for c in $(CONTROL); do $(PY) -m kmd run $$c || exit $$?; done
pending:
	$(PY) -m kmd llm pending
test:
	$(PY) -m pytest -q tests
