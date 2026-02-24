.PHONY: lint format check test all jinja-lint ansible-lint

all: lint check test jinja-lint ansible-lint

lint:
	ruff check .

format:
	ruff format .

check:
	mypy .

test:
	pytest tests/unit

jinja-lint:
	find . -type d -name .venv -prune -o -name "*.j2" -print | xargs j2lint

ansible-lint:
	ansible-lint
