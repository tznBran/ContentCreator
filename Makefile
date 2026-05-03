.PHONY: help install web-dev api-dev worker dev infra-up infra-down infra-logs migrate lint typecheck test build clean

help:
	@echo "ContentCreator dev commands:"
	@echo "  make install       Install JS + Python deps"
	@echo "  make infra-up      Start Postgres, Redis, MinIO via docker compose"
	@echo "  make infra-down    Stop infra"
	@echo "  make api-dev       Run FastAPI with reload on :8000"
	@echo "  make web-dev       Run Next.js on :3000"
	@echo "  make worker        Run the RQ background worker"
	@echo "  make migrate       Run alembic upgrade head"
	@echo "  make dev           Start infra, api, and web together"
	@echo "  make lint          Lint web + api"
	@echo "  make typecheck     Typecheck web + api"
	@echo "  make test          Run api tests"
	@echo "  make build         Build web"

install:
	pnpm install
	cd apps/api && uv sync

infra-up:
	docker compose -f infra/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker-compose.yml down

infra-logs:
	docker compose -f infra/docker-compose.yml logs -f

api-dev:
	cd apps/api && uv run uvicorn content_creator_api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd apps/api && uv run python -m content_creator_api.worker

migrate:
	cd apps/api && uv run alembic upgrade head

web-dev:
	pnpm --filter web dev

dev: infra-up
	@echo "Run 'make api-dev' and 'make web-dev' in separate terminals."

lint:
	pnpm lint

typecheck:
	pnpm typecheck

test:
	pnpm api:test

build:
	pnpm --filter web build

clean:
	rm -rf node_modules apps/web/.next apps/web/node_modules apps/api/.venv apps/api/.mypy_cache apps/api/.ruff_cache apps/api/.pytest_cache
