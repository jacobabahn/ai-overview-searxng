.PHONY: check demo integration integration-down

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run ty check
	uv run pytest -q
	node --test tests/browser/*.test.js

demo:
	uv run python -m ai_overview.demo

integration:
	docker compose -f compose.test.yml up -d
	uv run python tests/integration/browser_check.py

integration-down:
	docker compose -f compose.test.yml down -v
