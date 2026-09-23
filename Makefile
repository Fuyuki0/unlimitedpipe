PYTHON ?= .venv/bin/python

.PHONY: install test lint format typecheck check clean

install:  ## Create .venv and install UnlimitedPipe with dev tools
	python3 -m venv .venv
	$(PYTHON) -m pip install -q -e ".[dev]" -e examples/plugin-hackernews

test:  ## Run the test suite (no network needed)
	$(PYTHON) -m pytest tests examples/plugin-hackernews/tests

lint:  ## Lint, check formatting and types
	$(PYTHON) -m ruff check src tests examples
	$(PYTHON) -m ruff format --check src tests examples
	$(PYTHON) -m pyright --pythonpath $(PYTHON)

format:  ## Format and auto-fix
	$(PYTHON) -m ruff format src tests examples
	$(PYTHON) -m ruff check --fix src tests examples

typecheck:
	$(PYTHON) -m pyright --pythonpath $(PYTHON)

check: lint test  ## Everything CI runs

clean:
	rm -rf .pytest_cache .ruff_cache build dist src/*.egg-info
