# ContentCreator

A one‑stop AI content creation platform: **prompt → multi‑shot AI video → full‑timeline editor → multi‑platform publish**, with a custom voice clone for narration.

> **Status: Phase 0 — skeleton.** Repo bootstrap with a working web ↔ api ↔ Postgres path. Real video generation, the timeline editor, voice cloning, and social publishing land in phases 1–4. See [`plans/`](#) (in chat) for the full roadmap.

---

## Architecture (target)

```
┌────────────────┐    HTTP    ┌──────────────────────┐
│ Next.js 16     │  ────────▶ │ FastAPI              │
│ (apps/web)     │            │ (apps/api)           │
│                │ ◀────────  │ + Alembic + SQLModel │
└────────────────┘            └─────────┬────────────┘
                                         │
                              ┌──────────┼─────────────┐
                              ▼          ▼             ▼
                          ┌──────┐   ┌──────┐    ┌──────────┐
                          │Redis │   │Postgres│  │ MinIO/S3 │
                          │(RQ)  │   │       │   │ (clips)  │
                          └──────┘   └──────┘    └──────────┘
                              │
                              ▼
                ┌─────────────────────────────────┐
                │ Workers (later phases):         │
                │  • Seedance 2.0 via OpenRouter  │
                │  • F5-TTS voice cloning         │
                │  • Remotion + ffmpeg renderer   │
                │  • YouTube / TikTok / IG upload │
                └─────────────────────────────────┘
```

| Component | Tech |
|---|---|
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind v4 |
| Backend | FastAPI, SQLModel, Alembic, RQ, structlog |
| DB | Postgres 16 |
| Queue | Redis 7 |
| Object storage | MinIO (S3‑compatible) for local dev |
| Video gen | Seedance 2.0 via OpenRouter (`bytedance/seedance-2.0`) |
| Editor | Remotion + custom timeline UI |
| Voice cloning | Self‑hosted F5‑TTS (with ElevenLabs fallback behind a `TTSProvider` interface) |
| Publishing | YouTube Data API v3, TikTok Content Posting API, Instagram Graph API |

---

## Prerequisites

- **Node ≥ 20** and **pnpm ≥ 9** (`npm i -g pnpm@9`)
- **Python ≥ 3.11** and **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Docker** + Docker Compose (for Postgres / Redis / MinIO)
- **ffmpeg** in `$PATH` (Phase 2+, for video rendering)

---

## Local setup

```bash
# 1. Clone and install
git clone https://github.com/tznBran/ContentCreator.git
cd ContentCreator
cp .env.example .env
cp apps/web/.env.local.example apps/web/.env.local
make install                      # installs JS + Python deps

# 2. Start infra (Postgres, Redis, MinIO)
make infra-up

# 3. Run migrations
cd apps/api && uv run alembic upgrade head && cd ../..

# 4. Run the backend (terminal 1)
make api-dev                      # http://localhost:8000

# 5. Run the frontend (terminal 2)
make web-dev                      # http://localhost:3000
```

Visit:
- App: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- MinIO console: <http://localhost:9001> (user / pass: `contentcreator` / `contentcreator`)

---

## Project layout

```
ContentCreator/
├── apps/
│   ├── web/                Next.js app (App Router, TS, Tailwind)
│   └── api/                FastAPI app (SQLModel, Alembic, RQ)
├── infra/
│   └── docker-compose.yml  Postgres + Redis + MinIO
├── .github/workflows/ci.yml
├── .env.example
├── Makefile
└── pnpm-workspace.yaml
```

### apps/web key paths

- `src/app/page.tsx` — landing
- `src/app/projects/` — list, new, detail
- `src/lib/api.ts` — typed client for the FastAPI backend
- `src/components/Header.tsx` — top nav

### apps/api key paths

- `content_creator_api/main.py` — FastAPI factory
- `content_creator_api/config.py` — env‑driven settings
- `content_creator_api/db.py` — engine + session
- `content_creator_api/models.py` — SQLModel tables
- `content_creator_api/routers/` — `health.py`, `projects.py`
- `alembic/` — migrations

---

## Environment variables

Copy `.env.example` to `.env` at the repo root. The backend reads it via Pydantic Settings. Important variables come online phase by phase:

| Variable | Used in | Notes |
|---|---|---|
| `DATABASE_URL`, `REDIS_URL`, `S3_*` | Phase 0 | Defaults match `infra/docker-compose.yml`. |
| `OPENROUTER_API_KEY` | Phase 1 | Required for Seedance 2.0 + LLM calls. |
| `TTS_PROVIDER`, `F5TTS_DEVICE`, `ELEVENLABS_API_KEY`, `REPLICATE_API_TOKEN` | Phase 3 | Pick one. F5‑TTS realistically wants a CUDA GPU. |
| `YOUTUBE_*`, `TIKTOK_*`, `META_*` | Phase 4 | OAuth client credentials per platform. |

---

## Common commands

```bash
make help            # list everything
make install         # install JS + Python deps
make infra-up        # postgres + redis + minio
make infra-down
make api-dev
make web-dev
make lint
make typecheck
make test            # backend tests
make build           # next build
```

---

## Roadmap

- [x] **Phase 0** — repo skeleton, web ↔ api ↔ db wiring, CI
- [x] **Phase 1** — single‑clip generation via Seedance 2.0, N‑variant scoring
- [x] **Phase 2** — multi‑shot pipeline + timeline editor + ffmpeg export
- [ ] **Phase 3** — voice cloning + narration + auto‑captions
- [ ] **Phase 4** — OAuth + multi‑platform publishing (YouTube, TikTok, Instagram)

### Running Phase 1 locally

Phase 1 introduces an RQ background worker that drives Seedance 2.0
generation and clip scoring. To exercise it end‑to‑end:

```bash
make infra-up               # postgres + redis + minio
make migrate                # alembic upgrade head
export OPENROUTER_API_KEY=…  # required to actually call the model
make api-dev                # terminal 1
make worker                 # terminal 2 — picks up generation jobs
make web-dev                # terminal 3
```

Then open a project, submit the "Generate clips" form, and watch the
variant grid update as each clip moves PENDING → GENERATING → DOWNLOADING →
SCORING → SUCCEEDED. Pick a winner with the **Use this clip** button.
