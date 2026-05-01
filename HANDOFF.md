# SpecForge Handoff

Date: 2026-05-01

## Current State

**ALL V1 TASKS COMPLETE (T-001 through T-049)**

```
Current branch: main
Latest commit: 4dbb251 T-049: Add smoke test checklist for staging validation
```

Working tree is clean. All commits pushed to `https://github.com/rsqrd-labs/specforge.git`.

## What Is Being Built

SpecForge is an AI-powered 4-stage pipeline that turns a plain-English problem statement into:

1. **SPEC** — software specification document
2. **PLAN** — implementation plan
3. **HARNESS** — test harness with file-level code stubs
4. **TASKS** — atomic task list with test references

**Stack:**
- Backend: FastAPI + SQLAlchemy async + PostgreSQL + Redis + python-jose (RS256 JWT)
- Frontend: React 18 + TypeScript + Vite + Tailwind + Zustand + CodeMirror 6
- Auth: Google OAuth via Authlib, HttpOnly refresh cookies, Redis session tracking
- LLM: Abstract adapter layer (Anthropic / OpenAI / Google), streaming via SSE
- Deployment: Railway (backend) + Vercel (frontend), CI via GitHub Actions

## All Completed Tasks

### Phase 1 — Foundation (T-001 to T-010)
- T-001: Monorepo structure
- T-002: Backend Python project (uv, Python 3.12)
- T-003: FastAPI app factory, `/health`, DB session
- T-004: Vite + React + TypeScript + Tailwind frontend
- T-005: Frontend types and Axios API service
- T-006: SQLAlchemy ORM models (`User`, `Workspace`, `Stage`, `StageVersion`, `CreditLedger`, `EvalResult`)
- T-007: Alembic initial migration
- T-008: Pydantic schemas
- T-009: Auth service (Google OAuth, RS256 JWTs, refresh rotation, Redis sessions)
- T-010: Auth middleware (`get_current_user`, `get_optional_user`)

### Phase 1 — Backend (T-011 to T-028)
- T-011: Auth router (`/auth/google`, `/auth/callback`, `/auth/refresh`, `/auth/logout`, `/auth/me`)
- T-012: Rate limiting middleware (Redis sorted-set sliding window; global IP 1000 req/min, login 5/5min, per-user 100/min)
- T-013–T-017: LLM gateway + adapters (Anthropic, OpenAI, Google) + providers router (`GET /providers`)
- T-018: Credit service (`get_balance` with Redis cache, `deduct` with `SELECT FOR UPDATE`, `refund`)
- T-019: Credit check middleware (`require_credits(n)` FastAPI dependency)
- T-020: Workspace service + router (CRUD, creates 4 Stage records on workspace creation)
- T-021: Prompt builder (`build_prompt` fetches upstream stage content from Redis cache)
- T-022: Prompt guard (regex injection scanner) + output validator (system prompt leak detector)
- T-023: Diff engine (`compute_diff` via `difflib`, `apply_diff` via string replace)
- T-024: Stage manager (`generate` streaming, `refine`, `finalise`, `rollback`, `handle_content_edit`, `_mark_downstream_stale`)
- T-025: Stage router (all endpoints including SSE streaming, accept/reject diff, versions list, eval get, content patch)
- T-026: Online eval service (`run_eval` using `claude-haiku-4-5-20251001` as judge, fired as `asyncio.create_task` after generate)
- T-027: Export service + `POST /workspaces/{id}/export` (zip SPEC.md, PLAN.md, TASKS.md, harness/ files)
- T-028: Credits router (`GET /credits/balance`, `GET /credits/history` paginated)

### Phase 1 — Frontend (T-029 to T-038)
- T-029: SSE service (`createSSEConnection` streams the backend POST response with `fetch`)
- T-030: Zustand stores (`userStore`, `workspaceStore`, `stageStore` with `subscribeWithSelector` for zero-re-render streaming)
- T-031: React Router + page shell (`Landing`, `Dashboard`, `Workspace` placeholder, `ProtectedRoute`)
- T-032: Dashboard UI (workspace grid, `WorkspaceCard`, `CreateWorkspaceModal` with validation, `CreditBanner`, `CreditMeter`)
- T-033: `StageNavigator` component (status dots, locked non-clickable, active highlight)
- T-034: `StageEditor` CodeMirror 6 component (streaming token insertion via `subscribeWithSelector`, debounced `onContentChange`, selection handle via `ref`)
- T-035: `DiffViewer` component (manual unified diff parser, +/- line colors, accept/reject buttons)
- T-036: `GenerateBar`, `CreditConfirmModal`, `StalenessWarning`, and `HumanReviewGate` created
- T-037: `QualityBadge`, `CoveragePanel`, and `TaskValidationPanel` created
- T-038: Full `Workspace.tsx` assembly plus `useCredits` and `useStream` hooks

### Phase 1 — Infrastructure & Hardening (T-039 to T-049)
- T-039: Observability (`structlog` JSON logs, Prometheus `/metrics`, optional Sentry and OTLP tracing)
- T-040: CI pipeline (`.github/workflows/ci.yml` with TruffleHog, bandit, safety, ruff, black, pytest coverage, pnpm audit, tsc, vitest)
- T-041: Stuck in-progress stage recovery (`services/pipeline/recovery_service.py`, background loop every 5min, refunds credits for stages stuck >10min)
- T-042: Human review gate backend (`POST /stages/{id}/acknowledge-gate` sets `review_gate_acknowledged = True`; column added in T-006 initial schema)
- T-043: Large-selection warning UI in refine flow (frontend shows warning with "Proceed with diff" / "Use Regenerate" when `large_selection=True`)
- T-044: Railway + Vercel deployment (`backend/Procfile`, `backend/railway.json`, `frontend/vercel.json`, CI deploy step)
- T-045: AES-256 key vault (`services/security/key_vault.py` using Fernet, `encrypt`/`decrypt` with `DecryptionError`, 5 unit tests)
- T-046: LLM per-user rate limiting (10 calls/min + 200 calls/day checked in `stage_manager.generate()` and `refine()`, `RateLimitError` → 429 SSE event or HTTP 429)
- T-047: Backend test coverage to 87% (95 passing tests, all lint clean, services/ at 87% line coverage)
- T-048: Frontend Vitest integration tests (22 tests in `WorkspaceFlow.test.tsx` + `CreditSystem.test.tsx`, jsdom + @testing-library/react)
- T-049: Smoke test checklist (`docs/SMOKE_TEST_CHECKLIST.md`, 45 manual items covering full user journey)

## Current Test State

```bash
# Backend
cd backend
uv run pytest tests/ --cov=services --cov-fail-under=80 -q
# 95 passed, 2 warnings, 87% services coverage

uv run ruff check .           # All checks passed
uv run black --check .        # All done
uv run bandit -r config.py database.py main.py middleware models prompts routers schemas services  # No issues
uv run safety check --full-report --ignore 64459 --ignore 64396  # 0 reported

# Frontend
cd frontend
pnpm tsc --noEmit             # 0 errors
pnpm audit --audit-level moderate  # No known vulnerabilities
pnpm test                     # 22 passed (WorkspaceFlow + CreditSystem tests)
```

## Key File Map

### Deployment & CI
```
.github/workflows/ci.yml             — TruffleHog, backend security/lint/tests, frontend audit/typecheck/vitest, deploy to Railway + Vercel
backend/Procfile                     — gunicorn UvicornWorker for Railway
backend/railway.json                 — alembic upgrade head + gunicorn start, healthcheck at /health
frontend/vercel.json                 — SPA rewrite rule
docs/SMOKE_TEST_CHECKLIST.md         — 45-item manual test checklist
```

### Backend
```
backend/
  main.py                          — FastAPI app with lifespan context manager (starts recovery loop)
  config.py                        — Settings (pydantic BaseSettings)
  database.py                      — async_engine, get_db
  models/                          — SQLAlchemy ORM (User, Workspace, Stage, StageVersion, CreditLedger, EvalResult)
  schemas/                         — Pydantic schemas (auth, workspace, stage, credits)
  routers/
    auth.py                        — /auth/* (google, callback, refresh, logout, me)
    workspace.py                   — /workspaces/* + /workspaces/{id}/export
    stage.py                       — /stages/* (all stage operations incl. acknowledge-gate)
    credits.py                     — /credits/balance, /credits/history
    providers.py                   — /providers
  middleware/
    auth.py                        — get_current_user (bearer + ?token= fallback)
    credit_check.py                — require_credits(n) dependency
    rate_limit.py                  — RateLimitMiddleware (Redis sorted-set sliding window)
  services/
    auth_service.py                — Google OAuth, JWT sign/verify, Redis session
    credit_service.py              — get_balance (Redis cached), deduct (FOR UPDATE), refund
    workspace_service.py           — create (makes 4 Stage records), get, list, update, archive
    observability.py               — structlog config, Prometheus metrics, optional Sentry/OTLP
    llm/
      base.py                      — BaseLLMAdapter ABC, ProviderError
      gateway.py                   — get_llm(provider, model) factory
      anthropic_adapter.py         — stream() + complete()
      openai_adapter.py            — stream() + complete()
      google_adapter.py            — stream() + complete()
      provider_config.py           — PROVIDER_MODELS dict
    evals/
      online_eval.py               — run_eval() (haiku judge, async background task)
    pipeline/
      stage_manager.py             — generate (SSE + LLM rate limits), refine, finalise, rollback, handle_content_edit
      prompt_builder.py            — build_prompt (fetches upstream from Redis)
      diff_engine.py               — compute_diff, apply_diff
      export_service.py            — build_export (zip with 4 files + parsed harness/)
      recovery_service.py          — recover_stuck_stages(), run_recovery_loop() (every 5 min)
    security/
      prompt_guard.py              — scan() (regex injection detection)
      output_validator.py          — validate() (system prompt leak detection)
      key_vault.py                 — encrypt()/decrypt() via Fernet AES-256
  tests/                           — 95 unit tests across all services
```

### Frontend
```
frontend/src/
  App.tsx                          — BrowserRouter with /, /dashboard, /workspace/:id routes
  types/
    user.ts, workspace.ts, stage.ts
  services/
    api.ts                         — Axios client, all API calls
    sseService.ts                  — createSSEConnection (fetch POST stream parser)
  hooks/
    useCredits.ts                  — polls credit balance every 30s
    useStream.ts                   — manages stage streaming, store updates, eval polling
  store/
    userStore.ts, workspaceStore.ts, stageStore.ts (subscribeWithSelector)
  components/
    shared/ProtectedRoute.tsx, CreditMeter.tsx
    dashboard/WorkspaceCard.tsx, CreateWorkspaceModal.tsx, CreditBanner.tsx
    workspace/StageNavigator.tsx, StageEditor.tsx, DiffViewer.tsx
             GenerateBar.tsx, CreditConfirmModal.tsx, StalenessWarning.tsx
             HumanReviewGate.tsx, QualityBadge.tsx, CoveragePanel.tsx
             TaskValidationPanel.tsx
  pages/Landing.tsx, Dashboard.tsx, Workspace.tsx
  __tests__/
    setup.ts                       — @testing-library/jest-dom import
    WorkspaceFlow.test.tsx         — 12 tests: StageNavigator, GenerateBar, StalenessWarning, HumanReviewGate
    CreditSystem.test.tsx          — 10 tests: CreditMeter, CreditBanner, CreditConfirmModal
```

## Critical Implementation Details

### Streaming Auth Pattern
Generation uses a streaming `POST` response. The frontend `sseService.ts` uses `fetch` with the bearer token header. The backend accepts `?token=<jwt>` for compatibility.

### Streaming Architecture
`stageStore.appendToken()` uses Zustand's `subscribeWithSelector` — does NOT trigger React re-renders. `StageEditor` subscribes to `streamingContent[stageId]` directly and applies CodeMirror transactions. **Do not change this to `useStore()` hooks.**

### Credit Refund Flow
`stage_manager.refine()` returns `DiffResponse` with `ledger_id: UUID`. The frontend stores this and passes it to `POST /stages/{id}/reject-diff` when the user rejects.

### Stage Order & Dependencies
```python
STAGE_ORDER = ["spec", "plan", "harness", "tasks"]
STAGE_DEPENDENCIES = {
    "spec": [],
    "plan": ["spec"],
    "harness": ["spec", "plan"],
    "tasks": ["spec", "plan", "harness"],
}
```

### Credit Costs
```python
CREDIT_COSTS = {"generate": 10, "refine": 3, "regenerate": 10}
```

### LLM Rate Limits (per user)
- 10 calls / 60 seconds (Redis key: `ratelimit:llm:{user_id}`)
- 200 calls / 86400 seconds daily (Redis key: `ratelimit:llm_daily:{user_id}`)
- Exceeded → `RateLimitError` → SSE `{"error": "rate_limit_exceeded", "retry_after": N}` or HTTP 429

### Review Gate
`Stage.review_gate_acknowledged` starts `False`. Frontend shows `HumanReviewGate` before any non-spec stage generation. After user proceeds, calls `POST /stages/{id}/acknowledge-gate`. Gate never shown again after acknowledgement.

### Recovery Service
`services/pipeline/recovery_service.py` runs as a background asyncio task (every 5 min). Finds stages stuck `in_progress` for >10 min, finds corresponding ledger entry within 60s window, calls `credit_service.refund()`, resets stage to `draft`.

### Redis Cache Keys
- Stage content: `stage:{workspace_id}:{stage_type}` (TTL 1h)
- Credit balance: `credits:{user_id}` (TTL 5min)
- Auth session: `session:{jti}` (TTL = token expiry)
- Rate limit: `ratelimit:{key}` (sorted set)
- LLM rate limit: `ratelimit:llm:{user_id}`, `ratelimit:llm_daily:{user_id}`

## Deployment

### Backend → Railway
- `railway.json` runs `alembic upgrade head` then starts gunicorn with 2 UvicornWorker processes
- Healthcheck: `GET /health` (30s timeout)
- Requires: `RAILWAY_TOKEN` secret in GitHub Actions

### Frontend → Vercel
- `vercel.json` rewrites all non-API routes to `/index.html` for SPA routing
- CI deploy step: `vercel --prod`
- Requires: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` secrets in GitHub Actions

## Tooling

```bash
# Backend
cd backend
uv sync                          # install deps
uv run pytest tests/ -q          # run tests
uv run ruff check .              # lint
uv run black .                   # format
uv run alembic upgrade head      # run migrations
uv run uvicorn main:app --reload # dev server

# Frontend
cd frontend
pnpm install
pnpm tsc --noEmit               # type check
pnpm test                       # vitest
pnpm dev                        # Vite on :5173
```

## Local Environment

```
DATABASE_URL=postgresql+asyncpg://specforge:specforge@localhost:5432/specforge
REDIS_URL=redis://localhost:6379/0
ENCRYPTION_MASTER_KEY=<32-byte base64 Fernet key>
```

All other secrets in `backend/.env`. Docker Compose runs `db` and `redis`.

## Stop Point

**All V1 tasks complete (T-001 through T-049).** All commits pushed to remote.

Next steps for production launch:
1. Execute `docs/SMOKE_TEST_CHECKLIST.md` against staging environment.
2. Resolve any failures (file as bugs).
3. Tag `v1.0.0` release.
4. Configure Railway and Vercel project secrets (`RAILWAY_TOKEN`, `VERCEL_TOKEN`, etc.) for CI auto-deploy.
