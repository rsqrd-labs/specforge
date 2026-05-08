# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

SpecForge is a full-stack SaaS web app that turns a user's idea into a structured engineering spec through a four-stage LLM pipeline: **Spec → Plan → Harness → Tasks**. Each stage can be streamed, refined, diffed, and version-controlled. Users authenticate with Google OAuth, consume credits per generation, and can connect their own LLM API keys.

## Development Commands

### Starting the full stack (recommended)
```bash
docker compose up --build
```
- PostgreSQL on 5432, Redis on 6379, FastAPI on 8000, Vite on 5173

### Backend (without Docker)
```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend (without Docker)
```bash
cd frontend
pnpm install
pnpm dev          # Vite dev server on 5173, proxies /api → localhost:8000
pnpm build        # tsc --noEmit && vite build
pnpm tsc          # type-check only
```

### Backend tests
```bash
cd backend
uv run pytest tests/ -q                                  # all tests
uv run pytest tests/test_auth_service.py -q              # single file
uv run pytest tests/ --cov=services --cov-fail-under=80  # with coverage (80% required)
uv run ruff check .                                      # lint
uv run black --check .                                   # format check
```

### Frontend tests
```bash
cd frontend
pnpm test         # vitest run
```

### Harness / contract tests
```bash
cd harness
# backend contract tests
pytest tests/backend/ -q
# frontend contract tests (separate vitest config)
npx vitest run --config ../frontend/vitest.harness.config.ts
```

## Architecture

### Backend (`backend/`)
FastAPI app with async SQLAlchemy (PostgreSQL) and Redis.

- **`routers/`** — HTTP endpoints grouped by domain: `auth`, `workspaces`, `stages`, `credits`, `providers`
- **`services/pipeline/`** — Core stage generation logic: runs the four-stage flow, handles SSE streaming, diffs, version snapshots, and recovery
- **`services/llm/`** — Provider adapters (Anthropic, OpenAI, Google Gemini) behind a unified gateway; routes calls based on user's configured provider
- **`services/evals/`** — Online quality scoring of generated stages
- **`services/security/`** — CSRF enforcement, prompt injection guard, output validator (detects system-prompt leakage), sanitizer (bleach), Fernet-encrypted key vault
- **`services/credit_service.py`** — Ledger-based credit accounting; checks balance before generation, charges on completion
- **`middleware/`** — Rate limiting, CSRF enforcement, auth extraction
- **`models/`** — SQLAlchemy ORM: `User`, `Workspace`, `Stage`, `StageVersion`, `CreditLedger`, `EvalResult`

### Frontend (`frontend/src/`)
React 18 + TypeScript SPA. State via Zustand; routing via React Router 6.

- **`pages/`** — `Landing`, `AuthCallback`, `Dashboard`, `Workspace` (main editor view)
- **`components/workspace/`** — The core product UI: `StageEditor`, `StageNavigator`, `DiffViewer`, `HumanReviewGate`, `StreamingOverlay`, `QualityBadge`, `CoveragePanel`, `TaskValidationPanel`
- **`services/api.ts`** — Axios client; automatically attaches CSRF token to mutating requests
- **`services/sseService.ts`** — SSE client for streaming stage generation progress
- **`store/`** — Zustand stores: `userStore`, `workspaceStore`, `stageStore`

### Key Cross-Cutting Concerns

**Auth flow**: Google OAuth → frontend `/auth/callback` → frontend calls backend `/auth/callback` → JWT access token (in-memory on frontend) + refresh token (HTTP-only cookie). CSRF tokens required on all mutating requests.

**Stage generation flow**: Frontend calls POST to trigger generation → backend streams progress via SSE → frontend `StreamingOverlay` updates in real time → `HumanReviewGate` blocks progression until user approves.

**LLM routing**: Every generation goes through `services/llm/gateway.py`. If the user has stored a provider API key (encrypted in DB), it uses that; otherwise falls back to the platform key. Credit accounting is provider-aware.

**Observability**: Prometheus at `/metrics`, structured logging via `structlog`, optional Sentry (scrubs secrets), optional OTLP. Health check at `/health` reports db/redis status.

## Environment Variables

Backend uses `.env` (see `backend/config.py` for all keys):
- `DATABASE_URL`, `REDIS_URL`
- `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` (RS256 PEM keys)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`
- `ENCRYPTION_MASTER_KEY` (Fernet, for stored user API keys)
- `CSRF_SECRET`, `METRICS_TOKEN`
- Optional: `SENTRY_DSN`, `GRAFANA_OTLP_ENDPOINT`, `GRAFANA_OTLP_TOKEN`
- Optional: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`

Frontend uses `.env`:
- `VITE_API_URL` (defaults to `http://localhost:8000` via proxy in dev)
- `VITE_SENTRY_DSN` (optional)

## CI

`.github/workflows/ci.yml` runs on every push:
1. TruffleHog secret scan
2. Backend: ruff → black → bandit → pip-audit → pytest (80% coverage)
3. Frontend: pnpm audit → tsc → vitest → vite build
4. On `main` push: deploy backend to Railway, frontend to Vercel

## Design System

The UI uses a **Modern Indica** color theme with glassmorphism effects. See `Design.md` for the full design spec including color tokens, typography, and component patterns. Tailwind is the styling layer; avoid inline styles.
