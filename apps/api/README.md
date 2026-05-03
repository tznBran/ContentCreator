# content-creator-api

FastAPI backend for the ContentCreator AI video platform. See the [repo README](../../README.md) for the full system overview.

## Local dev

```bash
# from repo root
make infra-up         # postgres, redis, minio
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn content_creator_api.main:app --reload --port 8000
```

## Lint / typecheck / test

```bash
uv run ruff check .
uv run mypy content_creator_api
uv run pytest
```
