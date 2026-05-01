# SpecForge Handoff

Date: 2026-05-01

## Current State

Branch: `main`  
Remote: `https://github.com/rsqrd-labs/specforge.git`

Latest pushed commits:
- `58c082a T-055: Show eval scores in stage navigator`
- `0f2e71f T-054: Add streaming editor overlay`
- `93f8b24 T-053: Initialize frontend Sentry`
- `8ad8ff9 T-052: Add hourly auth rate limit`
- `4936f46 T-051: Sanitize persisted user text`
- `595a1ad T-050: Add CSRF protection`

Current implementation status:
- T-001 through T-049 are complete from the original V1 plan.
- Prompt hardening work is complete and pushed.
- T-050 CSRF Middleware is complete and pushed.
- T-051 Input Sanitization with Bleach is complete and pushed.
- T-052 Hourly Auth Rate Limit Tier is complete and pushed.
- T-053 Sentry Initialization is complete and pushed.
- T-054 StreamingOverlay Component is complete and pushed.
- T-055 Quality Badge in StageNavigator is complete and pushed.
- T-056 Dockerfile and README Quickstart is implemented locally and ready to commit/push after this handoff update.
- Next task after T-056 is T-057 Fix Google Login Redirect Contract.

Known unrelated working-tree artifacts that predate this pass and should not be reverted casually:
- Deleted: `Design.md.md`
- Untracked: `Design.md`
- Untracked Phase 4 harness files under `harness/tests/...`
- Untracked `frontend/vitest.harness.config.ts`
- Untracked `harness/node_modules`

## What Was Just Completed

### Prompt Hardening

Commit `c0854a8` updated the stage-generation prompts:
- Added shared security/privacy and professional-output rules in `backend/prompts/base.py`.
- Hardened `spec.py`, `plan.py`, `harness.py`, and `tasks.py` against prompt injection, role override, secret extraction, and system prompt leakage.
- Expanded `prompt_guard.py` and `output_validator.py`.
- Added focused tests in `backend/tests/test_security.py`.

Verified:
```bash
cd backend
uv run pytest tests/test_security.py tests/test_prompt_builder.py -q
uv run ruff check prompts services/security tests/test_security.py
uv run black --check prompts services/security tests/test_security.py
```

### T-050 CSRF Middleware

Commit `595a1ad` implemented:
- `backend/services/security/csrf.py`
  - `generate_csrf_token(session_id: str) -> str`
  - `verify_csrf_token(token: str, session_id: str, max_age_seconds: int = 3600) -> bool`
- `backend/middleware/csrf.py`
  - Enforces `X-CSRF-Token` on mutating requests when a bearer token contains a parseable `sub`.
  - Exempts safe methods and OAuth/session endpoints: `/auth/google`, `/auth/callback`, `/auth/refresh`, `/auth/logout`.
  - Invalid/missing CSRF with valid auth returns 403.
  - Invalid/unparseable auth is left to auth dependencies so those routes can still return 401.
- `backend/main.py`
  - Registers `CsrfMiddleware`.
- `backend/routers/auth.py`
  - Adds `GET /auth/csrf-token`.
- `frontend/src/services/api.ts`
  - Fetches/caches CSRF tokens from `/auth/csrf-token`.
  - Attaches `X-CSRF-Token` to axios mutating requests.
  - Clears cached CSRF token when access token changes.
- `frontend/src/services/sseService.ts`
  - Attaches CSRF token to streaming `POST` requests.
- `backend/tests/test_csrf.py`
  - Adds CSRF token and middleware tests.

Verified:
```bash
cd backend
uv run pytest tests/test_csrf.py tests/test_auth_router.py -q
uv run ruff check services/security/csrf.py middleware/csrf.py main.py routers/auth.py tests/test_csrf.py
uv run black --check services/security/csrf.py middleware/csrf.py main.py routers/auth.py tests/test_csrf.py

cd frontend
pnpm tsc --noEmit
```

### T-051 Input Sanitization with Bleach

Commit `4936f46` implemented:
- `backend/services/security/sanitizer.py`
  - Removes complete `<script>` and `<style>` blocks.
  - Uses `bleach.clean(..., tags=[], attributes={}, strip=True)` to strip all remaining HTML.
- `backend/services/workspace_service.py`
  - Sanitizes workspace `name` and `problem_statement` before create.
  - Sanitizes workspace `name` before update.
- `backend/routers/stage.py`
  - Sanitizes refine `instruction` before calling `stage_manager.refine()`.
- Tests:
  - `backend/tests/test_sanitizer.py`
  - Added workspace create/update sanitizer assertions.
  - Added stage refine route sanitizer assertion.

Verified:
```bash
cd backend
uv run pytest tests/test_sanitizer.py tests/test_workspace.py tests/test_stage_router.py -q
uv run ruff check services/security/sanitizer.py services/workspace_service.py routers/stage.py tests/test_sanitizer.py tests/test_workspace.py tests/test_stage_router.py
uv run black --check services/security/sanitizer.py services/workspace_service.py routers/stage.py tests/test_sanitizer.py tests/test_workspace.py tests/test_stage_router.py
```

### T-052 Hourly Auth Rate Limit Tier

Commit `8ad8ff9` implemented:
- `backend/middleware/rate_limit.py`
  - Adds `login_hourly:{ip}` sliding-window check for `/auth/google` and `/auth/callback`.
  - Allows 20 attempts per hour and returns `429` with `Retry-After: 3600` on the 21st.
  - Existing 5 attempts / 5 minutes tier remains in place.
- `backend/tests/test_rate_limit.py`
  - Covers 20th hourly login attempt allowed.
  - Covers 21st hourly login attempt blocked.

Verified:
```bash
cd backend
uv run pytest tests/test_rate_limit.py -q
uv run ruff check middleware/rate_limit.py tests/test_rate_limit.py
uv run black --check middleware/rate_limit.py tests/test_rate_limit.py
```

### T-053 Sentry Initialization

Commit `93f8b24` implemented:
- `frontend/src/main.tsx`
  - Imports `@sentry/react`.
  - Calls `Sentry.init()` only when `VITE_SENTRY_DSN` is configured.
  - Enables `Sentry.browserTracingIntegration()` with `tracesSampleRate: 0.1`.
- Backend note:
  - Backend Sentry already exists in `backend/services/observability.py::setup_sentry()`.
  - `backend/main.py::create_app()` invokes it via `setup_observability(app, async_engine)`.
  - Do not duplicate backend Sentry setup inline in `main.py`.

Verified:
```bash
cd frontend
pnpm tsc --noEmit
pnpm vitest run --config vitest.harness.config.ts ../harness/tests/frontend/phase4-sentry.contract.test.ts

cd backend
uv run pytest tests/test_observability.py -q
```

### T-054 StreamingOverlay Component

Commit `0f2e71f` implemented:
- `frontend/src/components/workspace/StreamingOverlay.tsx`
  - Named export `StreamingOverlay`.
  - Renders nothing when `isVisible` is false.
  - Renders a semi-transparent, `pointer-events-none` overlay with a pulsing cursor and `Generating...` label when visible.
- `frontend/src/pages/Workspace.tsx`
  - Wraps the editor section with `relative`.
  - Mounts `<StreamingOverlay isVisible={isStreaming} />` over `StageEditor`.

Verified:
```bash
cd frontend
pnpm tsc --noEmit
pnpm vitest run --config vitest.harness.config.ts ../harness/tests/frontend/phase4-streaming-overlay.contract.test.tsx
```

### T-055 Quality Badge in StageNavigator

Commit `58c082a` implemented:
- `frontend/src/components/workspace/StageNavigator.tsx`
  - Shows `eval_result.overall_score` inline for stages with evals.
  - Keeps version display for finalised stages.
  - Applies green/amber/red score classes by threshold.
  - Handles `overall_score: null` safely.

Verified:
```bash
cd frontend
pnpm tsc --noEmit
pnpm vitest run --config vitest.harness.config.ts ../harness/tests/frontend/phase4-navigator-quality-badge.contract.test.tsx
pnpm vitest run src/__tests__/WorkspaceFlow.test.tsx
```

### T-056 Dockerfile and README Quickstart

Implemented locally:
- `backend/Dockerfile`
  - Uses `python:3.12-slim`.
  - Installs `uv`, syncs from `uv.lock`, and runs gunicorn with `UvicornWorker`.
- `backend/.dockerignore`
  - Excludes local env/cache/venv artifacts from image context.
- `docker-compose.yml`
  - Adds `api` service on `localhost:8000`.
  - Adds `frontend` service on `localhost:5173` so `docker compose up --build` provides a usable app.
  - Keeps `db` and `redis` healthchecks.
- `README.md`
  - Replaces placeholder with project overview, four-step self-hosting, dev setup, env var table, and verification commands.

Verified:
```bash
docker compose config
cd backend
uv run pytest ../harness/tests/backend/test_phase4_contract.py -q -k "dockerfile or docker_compose or readme"
```

## Pending Tasks

Continue in `tasks.md` order:
- T-057: Fix Google Login Redirect Contract
- T-058: Remove Access Token localStorage Fallback
- T-059: Harden Refresh Cookie Attributes
- T-060: Refresh Token Reuse Revokes All Sessions
- T-061: Provider-Specific Eval Judge Selection
- T-062: Isolate Background Eval Database Session
- T-063: Secure and Refund Refine Flow
- T-064: Resolve Refine Billing Semantics
- T-065: Return 404 for Cross-User Workspace Access
- T-066: Sensitive Data Redaction for Logs and Sentry

## Critical Implementation Notes

Streaming:
- `frontend/src/services/sseService.ts` sends streaming generate/regenerate requests with `fetch`.
- Because T-050 adds CSRF enforcement, SSE `POST` requests now need both `Authorization` and `X-CSRF-Token`.
- `stageStore.appendToken()` uses Zustand `subscribeWithSelector`; do not replace it with normal React store reads in the editor.

Credits:
- Current refine behavior still deducts before diff and refunds on reject.
- T-064 intentionally changes that to deduct on accept only.

Auth:
- Access token still has a localStorage fallback in `api.ts`; T-058 removes it.
- Refresh cookie is still `SameSite=Lax` and not scoped to `/auth/refresh`; T-059 fixes it.
- Refresh-token reuse detection still does not revoke every user session; T-060 fixes it.

Evals:
- Online eval currently uses Anthropic Haiku regardless of workspace provider.
- Background eval currently receives the request-scoped DB session.
- T-061 and T-062 address those.

## Recommended Next Steps

1. Commit and push T-050 with `HANDOFF.md`.
2. Start T-051.
3. After each task:
   - Run focused backend/frontend tests.
   - Update `HANDOFF.md` with task status, commands run, and next task.
   - Commit only files related to that task and `HANDOFF.md`.
   - Push `main` to `origin`.
