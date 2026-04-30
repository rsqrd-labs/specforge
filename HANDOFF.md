# SpecForge Handoff

Date: 2026-04-30

## Current State

Work has been completed through **T-037**, with additional discrepancy fixes for streaming, stage authorization, refine API typing, and the review-gate endpoint.

```
Current branch: main
Last commit: c36aaa7
```

Working tree has local changes from the discrepancy fixes. Commit and push after verification.

## What Is Being Built

SpecForge is an AI-powered 4-stage pipeline that turns a plain-English problem statement into:

1. **SPEC** — software specification document
2. **PLAN** — implementation plan
3. **HARNESS** — test harness with file-level code stubs
4. **TASKS** — atomic task list with test references

**Stack:**
- Backend: FastAPI + SQLAlchemy async + PostgreSQL + Redis + python-jose (RS256 JWT)
- Frontend: React + TypeScript + Vite + Tailwind + Zustand + CodeMirror 6
- Auth: Google OAuth via Authlib, HttpOnly refresh cookies, Redis session tracking
- LLM: Abstract adapter layer (Anthropic / OpenAI / Google), streaming via SSE

## Completed Tasks (T-001 through T-037)

### Phase 1 — Foundation (T-001 to T-010, done by Codex)
- T-001: Monorepo structure
- T-002: Backend Python project (uv, Python 3.12)
- T-003: FastAPI app factory, `/health`, DB session
- T-004: Vite + React + TypeScript + Tailwind frontend
- T-005: Frontend types and Axios API service
- T-006: SQLAlchemy ORM models (`User`, `Workspace`, `Stage`, `StageVersion`, `CreditLedger`, `EvalResult`)
- T-007: Alembic initial migration (migration `0001` is the only migration so far)
- T-008: Pydantic schemas
- T-009: Auth service (Google OAuth, RS256 JWTs, refresh rotation, Redis sessions)
- T-010: Auth middleware (`get_current_user`, `get_optional_user`)

### Phase 1 — Backend (T-011 to T-028, done in this session)
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

### Phase 1 — Frontend (T-029 to T-037, done)
- T-029: SSE service (`createSSEConnection` streams the backend POST response with `fetch`)
- T-030: Zustand stores (`userStore`, `workspaceStore`, `stageStore` with `subscribeWithSelector` for zero-re-render streaming)
- T-031: React Router + page shell (`Landing`, `Dashboard`, `Workspace` placeholder, `ProtectedRoute`)
- T-032: Dashboard UI (workspace grid, `WorkspaceCard`, `CreateWorkspaceModal` with validation, `CreditBanner`, `CreditMeter`)
- T-033: `StageNavigator` component (status dots, locked non-clickable, active highlight)
- T-034: `StageEditor` CodeMirror 6 component (streaming token insertion via `subscribeWithSelector`, debounced `onContentChange`, selection handle via `ref`)
- T-035: `DiffViewer` component (manual unified diff parser, +/- line colors, accept/reject buttons)
- T-036: `GenerateBar`, `CreditConfirmModal`, `StalenessWarning`, and `HumanReviewGate` created.
- T-037: `QualityBadge`, `CoveragePanel`, and `TaskValidationPanel` created.

## Recent Commits

```
5d2e6ba Fix stage streaming and authorization contracts
c36aaa7 T-033/T-034/T-035/T-036 partial: Stage navigator, editor, diff viewer, generate bar, credit confirm modal
5c6ac12 T-032: Implement Dashboard UI with workspace grid and create modal
b93944f T-029/T-030/T-031: SSE service, Zustand stores, React Router with page shell
90564bd T-028: Add credits router with balance and paginated history endpoints
aea94fd T-027: Add export service and POST /workspaces/{id}/export endpoint
d5b5b73 T-026: Add online eval service with async background judge scoring
d4090ab T-025: Add stage router with SSE streaming, refine, finalise, rollback, and diff endpoints
6833b35 T-024: Add stage manager with streaming generation, finalise, rollback, and refine
9a8c73e Add security prompt guard, output validator, and diff engine (T-022, T-023)
d97d9d6 Add prompt system and pipeline prompt builder (T-021)
```

## Current Test State

```bash
cd backend && uv run pytest tests/ -q
# 76 passed, 2 warnings
```

All lint clean:
```bash
uv run ruff check .   # All checks passed
uv run black --check . # All done
cd ../frontend && pnpm tsc --noEmit  # 0 errors
```

## Next Task to Resume: T-038

T-037 is complete. The backend review-gate endpoint `POST /stages/{id}/acknowledge-gate` was also added early so `HumanReviewGate` can call a real endpoint.

### T-038: Workspace Page — Full Assembly

This is the big one. Complete `frontend/src/pages/Workspace.tsx` and add two hooks:

**`frontend/src/hooks/useCredits.ts`:**
- Polls `GET /credits/balance` every 30 seconds
- Returns `{balance: number | null, isLoading: boolean}`

**`frontend/src/hooks/useStream.ts`:**
- Takes `stageId: string`
- Opens the streaming `POST /stages/{id}/generate` or `/regenerate` request via `createSSEConnection`
- Calls `stageStore.startStream(stageId)` before streaming
- Each token → `stageStore.appendToken(stageId, token)`
- On done → `stageStore.finaliseStream(stageId)`, fetch updated stage from API, poll `GET /stages/{id}/eval` every 5 seconds (max 6 times = 30s) until eval is present
- On error → call `stageStore.finaliseStream(stageId)`, surface error to user

**`frontend/src/pages/Workspace.tsx` (complete):**
- Two-panel layout: `StageNavigator` on left (240px fixed), right panel = `StageEditor` + toolbar
- On mount: fetch workspace via `workspaceStore.fetchWorkspace(id)`, set all stages in `stageStore`
- Active stage = first non-locked stage by default, toggled via `StageNavigator`
- Generate flow:
  1. Show `CreditConfirmModal` (cost 10)
  2. If stage `review_gate_acknowledged = false` AND stage is not spec, show `HumanReviewGate`
  3. On proceed: call `useStream`
- Refine flow:
  1. User selects text in editor (via `StageEditor` ref `getSelection()`)
  2. Instruction input appears
  3. Show `CreditConfirmModal` (cost 3)
  4. Call `POST /stages/{id}/refine`
  5. If `large_selection = true` in response, show inline warning (see T-043)
  6. Show `DiffViewer`; on accept call `POST /stages/{id}/accept-diff`; on reject call `POST /stages/{id}/reject-diff` with `ledger_id` from response
- Content edits: `StageEditor.onContentChange` → debounced `PATCH /stages/{id}/content`
- Show `StalenessWarning` when `stage.status === "stale"`
- Export button in header: active only when all 4 stages finalised → `POST /workspaces/{id}/export` → browser download

## Remaining Tasks (T-039 to T-049)

### Backend / Hardening
- **T-039**: Observability (`structlog` JSON logging, OpenTelemetry, Prometheus `/metrics`, Sentry)
- **T-040**: CI pipeline (`.github/workflows/ci.yml` — TruffleHog, bandit, safety, ruff, black, pytest 80% coverage, pnpm audit, tsc, vitest)
- **T-041**: Stuck in-progress stage recovery (background task every 5min, refunds credits for stages >10min in `in_progress`)
- **T-042**: Done early — human review gate backend (`POST /stages/{id}/acknowledge-gate` endpoint, sets `review_gate_acknowledged = True`)
- **T-043**: Large selection warning frontend (already done in backend — `DiffResponse.large_selection` is populated. Frontend just needs to show warning in refine flow when `large_selection = true`)
- **T-044**: Railway + Vercel deployment (`Procfile`, `railway.json`, `vercel.json`, CI deploy step)
- **T-045**: AES-256 key vault (`services/security/key_vault.py` using Fernet)
- **T-046**: LLM rate limiting tier (per-user tier-based limits for LLM calls)
- **T-047**: Backend unit test coverage pass (80% across `services/`)
- **T-048**: Frontend integration test pass (vitest)
- **T-049**: End-to-end smoke test

## Key File Map

### Backend
```
backend/
  main.py                          — FastAPI app factory create_app(redis_client=None)
  config.py                        — Settings (pydantic BaseSettings)
  database.py                      — async_engine, get_db
  models/                          — SQLAlchemy ORM (User, Workspace, Stage, StageVersion, CreditLedger, EvalResult)
  schemas/                         — Pydantic schemas (auth, workspace, stage, credits)
  routers/
    auth.py                        — /auth/* (google, callback, refresh, logout, me)
    workspace.py                   — /workspaces/* + /workspaces/{id}/export
    stage.py                       — /stages/* (all stage operations)
    credits.py                     — /credits/balance, /credits/history
    providers.py                   — /providers
  middleware/
    auth.py                        — get_current_user (supports bearer auth and ?token= query param fallback)
    credit_check.py                — require_credits(n) dependency
    rate_limit.py                  — RateLimitMiddleware (Redis sorted-set sliding window)
  services/
    auth_service.py                — Google OAuth, JWT sign/verify, Redis session
    credit_service.py              — get_balance (Redis cached), deduct (FOR UPDATE), refund
    workspace_service.py           — create (makes 4 Stage records), get, list, update, archive
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
      stage_manager.py             — generate (SSE), refine, finalise, rollback, handle_content_edit
      prompt_builder.py            — build_prompt (fetches upstream from Redis)
      diff_engine.py               — compute_diff, apply_diff
      export_service.py            — build_export (zip with 4 files + parsed harness/)
    security/
      prompt_guard.py              — scan() (regex injection detection)
      output_validator.py          — validate() (system prompt leak detection)
  tests/
    test_auth_middleware.py
    test_auth_router.py
    test_credit_service.py
    test_credits_router.py
    test_diff_engine.py
    test_export_service.py
    test_online_eval.py
    test_providers_router.py
    test_rate_limit.py
    test_security.py
    test_stage_manager.py
    test_stage_router.py
    test_workspace_router.py
```

### Frontend
```
frontend/src/
  App.tsx                          — BrowserRouter with /, /dashboard, /workspace/:id routes
  main.tsx                         — React entry point
  types/
    user.ts                        — User interface
    workspace.ts                   — Workspace, WorkspaceWithStages, CreateWorkspacePayload
    stage.ts                       — Stage, StageVersion, EvalResult, etc.
  services/
    api.ts                         — Axios client with interceptors, all API calls
    sseService.ts                  — createSSEConnection (fetch POST stream parser)
  store/
    userStore.ts                   — user, isLoading, fetchMe
    workspaceStore.ts              — workspaces, currentWorkspace, fetchWorkspace, createWorkspace
    stageStore.ts                  — stages, streamingContent, activeStream, appendToken
  config/
    providers.ts                   — PROVIDERS array (anthropic, openai, google with models)
  components/
    shared/
      ProtectedRoute.tsx           — checks userStore.user, redirects to / if null
      CreditMeter.tsx              — balance display, "0 credits" waitlist state
    dashboard/
      WorkspaceCard.tsx            — card with stage progress dots, navigates to /workspace/:id
      CreateWorkspaceModal.tsx     — name + problem statement + provider + model form
      CreditBanner.tsx             — top banner, red when ≤5 credits
    workspace/
      StageNavigator.tsx           — vertical list with status dots, locked = non-clickable
      StageEditor.tsx              — CodeMirror 6, subscribeWithSelector streaming, selection ref
      DiffViewer.tsx               — unified diff parser with add/remove line colors
      GenerateBar.tsx              — status-driven action buttons
      CreditConfirmModal.tsx       — "This will use N credits" confirmation dialog
      StalenessWarning.tsx
      HumanReviewGate.tsx
      QualityBadge.tsx
      CoveragePanel.tsx
      TaskValidationPanel.tsx
  pages/
    Landing.tsx                    — "Sign in with Google" button
    Dashboard.tsx                  — workspace grid + create modal + credit banner
    Workspace.tsx                  — PLACEHOLDER ONLY — needs full assembly (T-038)
```

## Critical Implementation Details

### Streaming Auth Pattern
Generation uses a streaming `POST` response. The frontend `sseService.ts` uses `fetch` with the bearer token header and parses SSE `data:` chunks from the response body. The backend still accepts `?token=<jwt>` for compatibility, but the frontend no longer depends on `EventSource`.

### Streaming Architecture
`stageStore.appendToken()` uses Zustand's `subscribeWithSelector` — it does NOT trigger React re-renders. `StageEditor` subscribes to `streamingContent[stageId]` directly and applies CodeMirror transactions. This is intentional — avoid changing this to `useStore()` hooks.

### Credit Refund Flow
When `stage_manager.refine()` deducts credits, it returns `DiffResponse` with `ledger_id: UUID`. The frontend must store this `ledger_id` and pass it to `POST /stages/{id}/reject-diff` body when the user rejects the diff.

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
Generating a stage raises `StageDependencyError` (→ SSE error event) if upstream stages are not `finalised`.

### Credit Costs
```python
CREDIT_COSTS = {"generate": 10, "refine": 3, "regenerate": 10}
```

### Review Gate
`Stage.review_gate_acknowledged` is a boolean column in the DB. It starts `False`. Before generating any non-spec stage, the frontend should show `HumanReviewGate`. After the user clicks proceed, call `POST /stages/{id}/acknowledge-gate`. After that the gate is never shown again for that stage.

### DiffResponse `large_selection`
`stage_manager.refine()` already computes and returns `large_selection: bool` in the response when the selection covers >80% of the document. The frontend refine flow should check this and show a warning before proceeding.

### Redis Cache Keys
- Stage content cache: `stage:{workspace_id}:{stage_type}` (TTL 1h, set on finalise, deleted on invalidate)
- Credit balance cache: `credits:{user_id}` (TTL 5min)
- Auth session: `session:{jti}` (TTL = token expiry)
- Rate limit: `ratelimit:{key}` (sorted set)

## Tooling

```bash
# Backend
cd backend
uv sync                          # install deps
uv run pytest tests/ -q          # run tests (74 pass)
uv run ruff check .              # lint
uv run black --check .           # format check
uv run black .                   # format fix
uv run alembic upgrade head      # run migrations
uv run uvicorn main:app --reload # dev server

# Frontend
cd frontend
pnpm install
pnpm tsc --noEmit                # type check
pnpm dev                         # dev server (Vite on :5173)
```

## Local Environment

```
DATABASE_URL=postgresql+asyncpg://specforge:specforge@localhost:5432/specforge
REDIS_URL=redis://localhost:6379/0
```

All other secrets in `backend/.env` are placeholders. Docker Compose runs `db` and `redis`.

## Stop Point

Last completed: T-037 plus discrepancy fixes. Local changes are not committed yet.

**Resume from:** T-038, then T-039...T-049 in order.

Commit and push after each task completes successfully (tests pass, `pnpm tsc --noEmit` exits 0).
