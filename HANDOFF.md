# SpecForge Handoff

Date: 2026-05-01

## Current State

Branch: `main`  
Remote: `https://github.com/rsqrd-labs/specforge.git`

Latest pushed commits:
- `c0854a8 Harden stage generation prompts`
- `b9276b0 Add second-pass gap closure tasks`

Current implementation status:
- T-001 through T-049 are complete from the original V1 plan.
- Prompt hardening work is complete and pushed.
- T-050 CSRF Middleware is implemented locally and ready to commit/push after this handoff update.
- Next task after T-050 is T-051 Input Sanitization with Bleach.

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

Implemented locally:
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

## Pending Tasks

Continue in `tasks.md` order:
- T-051: Input Sanitization with Bleach
- T-052: Hourly Auth Rate Limit Tier
- T-053: Frontend Sentry initialization plus backend harness alignment
- T-054: StreamingOverlay component
- T-055: Quality Badge in StageNavigator
- T-056: Dockerfile and README Quickstart
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
