# SpecForge Handoff

Date: 2026-05-01

## Current State

Branch: `main`  
Remote: `https://github.com/rsqrd-labs/specforge.git`

Latest pushed commits:
- `HEAD T-064: Charge refine credits on accept`
- `ef1694c T-063: Secure refine flow refunds`
- `b38042b T-062: Isolate background eval sessions`
- `a445ddf T-061: Use provider-specific eval judges`
- `cc2808e T-060: Revoke sessions on refresh token reuse`
- `1c94623 T-059: Harden refresh cookie attributes`
- `1124f15 T-058: Keep access tokens in memory only`
- `397b035 T-057: Fix Google auth redirect contract`
- `5610a4d T-056: Add Docker quickstart`
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
- T-056 Dockerfile and README Quickstart is complete and pushed.
- T-057 Fix Google Login Redirect Contract is complete and pushed.
- T-058 Remove Access Token localStorage Fallback is complete and pushed.
- T-059 Harden Refresh Cookie Attributes is complete and pushed.
- T-060 Refresh Token Reuse Revokes All Sessions is complete and pushed.
- T-061 Provider-Specific Eval Judge Selection is complete and pushed.
- T-062 Isolate Background Eval Database Session is complete and pushed.
- T-063 Secure and Refund Refine Flow is complete and pushed.
- T-064 Resolve Refine Billing Semantics is complete and will be pushed with this handoff.
- Next task after T-064 is T-065 Return 404 for Cross-User Workspace Access.

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

Commit `5610a4d` implemented:
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

### T-057 Fix Google Login Redirect Contract

Commit `397b035` implemented:
- `frontend/src/pages/Landing.tsx`
  - Reads `redirect_url` from `POST /auth/google`.
  - Keeps runtime redirect behavior through `window.location.assign`.
  - Adds an injectable `assignLocation` prop for deterministic testing.
- `frontend/src/__tests__/Landing.test.tsx`
  - Mocks `api.post()`.
  - Asserts the backend `redirect_url` is used for redirect.

Verified:
```bash
cd frontend
pnpm tsc --noEmit
pnpm vitest run src/__tests__/Landing.test.tsx

cd backend
uv run pytest tests/test_auth_router.py::test_post_auth_google_returns_redirect_url -q
```

### T-058 Remove Access Token localStorage Fallback

Commit `1124f15` implemented:
- `frontend/src/services/api.ts`
  - `getAccessToken()` now returns only the in-memory `accessToken`.
  - No localStorage/sessionStorage fallback remains for access tokens.
- `harness/tests/frontend/api.contract.test.ts`
  - Contract now rejects both `getItem` and `setItem` access-token web-storage usage.
  - Fixed test path resolution for harness Vitest runs.

Verified:
```bash
cd frontend
pnpm tsc --noEmit
pnpm vitest run --config vitest.harness.config.ts ../harness/tests/frontend/api.contract.test.ts
```

### T-059 Harden Refresh Cookie Attributes

Commit `1c94623` implemented:
- `backend/routers/auth.py`
  - Refresh cookie now uses `SameSite=Strict`.
  - Refresh cookie is scoped to `Path=/auth/refresh`.
  - Logout deletes the same scoped cookie.
- `backend/tests/test_auth_router.py`
  - Asserts `HttpOnly`, `Secure`, strict SameSite, path scope, and max age.
  - Asserts logout clear-cookie uses the refresh path.

Verified:
```bash
cd backend
uv run pytest tests/test_auth_router.py -q
uv run ruff check routers/auth.py tests/test_auth_router.py
uv run black --check routers/auth.py tests/test_auth_router.py
```

### T-060 Refresh Token Reuse Revokes All Sessions

Commit `cc2808e` implemented:
- `backend/services/auth_service.py`
  - Adds `user_sessions:{user_id}` Redis set index for refresh JTIs.
  - Stores each refresh JTI in both `session:{jti}` and the per-user session set.
  - Removes old JTI from the session set during normal rotation.
  - On refresh-token reuse/missing session, deletes every indexed `session:{jti}` for that user and clears the set.
  - Logout removes only the presented refresh session from the user session set.
- `backend/tests/test_auth_service.py`
  - Extends fake Redis with set operations.
  - Tests normal rotation index updates.
  - Tests reuse detection revokes all active user sessions.
  - Tests logout revokes only the presented session.

Verified:
```bash
cd backend
uv run pytest tests/test_auth_service.py -q
uv run ruff check services/auth_service.py tests/test_auth_service.py
uv run black --check services/auth_service.py tests/test_auth_service.py
```

### T-061 Provider-Specific Eval Judge Selection

Commit `a445ddf` implemented:
- `backend/services/llm/provider_config.py`
  - Adds `JUDGE_MODELS` for Anthropic, OpenAI, and Google.
- `backend/services/evals/online_eval.py`
  - Uses `get_llm(provider, judge_model)` instead of hardcoded `AnthropicAdapter`.
  - Defaults remain Anthropic/Haiku for direct calls that do not pass a provider.
- `backend/services/pipeline/stage_manager.py`
  - Passes workspace provider and configured judge model when scheduling evals.
- `backend/routers/providers.py`
  - Includes `judge_model` in provider catalog responses.
- `backend/tests/test_online_eval.py`
  - Verifies provider-specific judge dispatch.

Verified:
```bash
cd backend
uv run pytest tests/test_online_eval.py tests/test_stage_manager.py tests/test_llm_gateway.py -q
uv run ruff check services/evals/online_eval.py services/pipeline/stage_manager.py services/llm/provider_config.py routers/providers.py tests/test_online_eval.py
uv run black --check services/evals/online_eval.py services/pipeline/stage_manager.py services/llm/provider_config.py routers/providers.py tests/test_online_eval.py
```

### T-062 Isolate Background Eval Database Session

Commit `b38042b` implemented:
- `backend/services/evals/online_eval.py`
  - Adds `run_eval_background(...)`.
  - Opens a fresh `AsyncSessionLocal()` inside the background task.
  - Calls `run_eval(...)` with that local session.
- `backend/services/pipeline/stage_manager.py`
  - Schedules `run_eval_background(...)` with primitive values only.
  - No longer passes the streaming request-scoped DB session into `asyncio.create_task()`.
- `backend/tests/test_online_eval.py`
  - Verifies `run_eval_background()` opens and exits its own session context.

Verified:
```bash
cd backend
uv run pytest tests/test_online_eval.py tests/test_stage_manager.py -q
uv run ruff check services/evals/online_eval.py services/pipeline/stage_manager.py tests/test_online_eval.py
uv run black --check services/evals/online_eval.py services/pipeline/stage_manager.py tests/test_online_eval.py
```

### T-063 Secure and Refund Refine Flow

Commit `ef1694c` implemented:
- `backend/services/pipeline/stage_manager.py`
  - Scans refine instruction and selected text before deduction.
  - Rejects unsafe refine inputs before any credit deduction or LLM call.
  - Refunds refine deduction if provider completion fails.
  - Validates replacement output and refunds on system-prompt leak detection.
- `backend/routers/stage.py`
  - Maps refine `SecurityError` to HTTP 400 with `security_check_failed`.
- `backend/tests/test_stage_manager.py`
  - Covers injection rejection before deduction.
  - Covers provider-error refund.
  - Covers unsafe-output refund.

Verified:
```bash
cd backend
uv run pytest tests/test_stage_manager.py tests/test_stage_router.py -q
uv run ruff check services/pipeline/stage_manager.py routers/stage.py tests/test_stage_manager.py tests/test_stage_router.py
uv run black --check services/pipeline/stage_manager.py routers/stage.py tests/test_stage_manager.py tests/test_stage_router.py
```

### T-064 Resolve Refine Billing Semantics

Current `HEAD` implements:
- `backend/services/pipeline/stage_manager.py`
  - Makes refine preview free: no credit deduction or ledger id is created while generating the diff preview.
  - Keeps prompt-injection scanning, rate limiting, and output validation in the preview path.
- `backend/schemas/stage.py`
  - Removes `ledger_id` from `DiffResponse`.
  - Removes the obsolete reject-diff body schema.
- `backend/routers/stage.py`
  - Charges 3 credits in `POST /stages/{stage_id}/accept-diff`.
  - Returns HTTP 402 with `{"code": "insufficient_credits", "required": 3}` when accept cannot be billed.
  - Refunds the accept deduction if saving the accepted content fails.
  - Makes `POST /stages/{stage_id}/reject-diff` a discard-only operation returning `{"rejected": true}`.
- `frontend/src/types/stage.ts`
  - Removes `ledger_id` from `RefineResponse`.
- `frontend/src/services/api.ts`
  - Calls reject-diff without a ledger payload and expects `{ rejected: boolean }`.
- `frontend/src/pages/Workspace.tsx`
  - Runs refine preview without the credit confirmation modal.
  - Rejects a diff without requiring a ledger id.
- Tests:
  - Updated stage-manager tests so provider/output failures during preview do not charge or refund credits.
  - Added route tests for accept billing, insufficient credits, failed-save refund, and reject-without-refund.

Verified:
```bash
cd backend
uv run pytest tests/test_stage_manager.py tests/test_stage_router.py -q
uv run ruff check schemas/stage.py services/pipeline/stage_manager.py routers/stage.py tests/test_stage_manager.py tests/test_stage_router.py
uv run black --check schemas/stage.py services/pipeline/stage_manager.py routers/stage.py tests/test_stage_manager.py tests/test_stage_router.py

cd frontend
pnpm tsc --noEmit
```

## Pending Tasks

Continue in `tasks.md` order:
- T-065: Return 404 for Cross-User Workspace Access
- T-066: Sensitive Data Redaction for Logs and Sentry

## Critical Implementation Notes

Streaming:
- `frontend/src/services/sseService.ts` sends streaming generate/regenerate requests with `fetch`.
- Because T-050 adds CSRF enforcement, SSE `POST` requests now need both `Authorization` and `X-CSRF-Token`.
- `stageStore.appendToken()` uses Zustand `subscribeWithSelector`; do not replace it with normal React store reads in the editor.

Credits:
- Refine preview is free.
- Accepting a refine diff deducts 3 credits.
- Rejecting a refine diff is discard-only and does not alter credit balance.
- If accept-diff persistence fails after deduction, the deduction is refunded.

Auth:
- Access tokens are kept in memory only; the localStorage fallback was removed in T-058.
- Refresh cookies are `SameSite=Strict` and scoped to `/auth/refresh` from T-059.
- Refresh-token reuse revokes all tracked sessions from T-060.

Evals:
- Online eval uses provider-specific judge models from T-061.
- Background eval opens its own database session from T-062.

## Recommended Next Steps

1. Push T-064 if it has not already been pushed.
2. Start T-065.
3. After each task:
   - Run focused backend/frontend tests.
   - Update `HANDOFF.md` with task status, commands run, and next task.
   - Commit only files related to that task and `HANDOFF.md`.
   - Push `main` to `origin`.
