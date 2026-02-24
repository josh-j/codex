.PHONY: lint format check test all jinja-lint ansible-lint setup

all: setup lint check test jinja-lint ansible-lint

setup:
	ansible-galaxy collection install -r requirements.yml

lint:
	ruff check .

format:
	ruff format .

check:
	mypy .

test:
	pytest tests/unit

jinja-lint:
	find . -type d -name .venv -prune -o -name "*.j2" -print | xargs j2lint --ignore jinja-statements-indentation single-statement-per-line --

ansible-lint:
	ANSIBLE_COLLECTIONS_PATH=$(CURDIR)/collections ansible-lint --exclude .venv
