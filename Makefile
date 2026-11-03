.PHONY: install dev backend frontend test typecheck check

install:
	uv sync
	cd frontend && npm install

# Validates config first (fails fast without ANTHROPIC_API_KEY), then runs both servers.
dev:
	uv run python -m backend --check
	trap 'kill 0' INT TERM EXIT; \
	uv run python -m backend --reload & \
	(cd frontend && npm run dev) & \
	wait

backend:
	uv run python -m backend --reload

frontend:
	cd frontend && npm run dev

test:
	uv run pytest

typecheck:
	uv run mypy
	cd frontend && npm run typecheck

check: typecheck test
