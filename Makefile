.PHONY: setup install test lint run scan paper live clean

PY := .venv/bin/python

setup: .venv
.venv:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

install: setup

test:
	$(PY) -m pytest tests/ -v

lint:
	$(PY) -m ruff check src/ tests/ scripts/

fmt:
	$(PY) -m ruff format src/ tests/ scripts/

run: paper

paper:
	MODE=PAPER $(PY) -m momentum.main

live:
	MODE=LIVE $(PY) -m momentum.main

scan:
	MODE=SCAN_ONLY $(PY) -m momentum.main

backtest:
	$(PY) scripts/backtest.py

clean:
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

all: setup test lint
