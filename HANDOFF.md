# SpecForge Handoff

Date: 2026-05-02

## Repository State

Branch: `main`
Remote: `https://github.com/rsqrd-labs/specforge.git`
Latest pushed commit: `2714944 T-074 + T-085: Catch SecurityError/ProviderError; extract shared stream helper`

## Current Implementation Status

Tasks `T-001` through `T-085` are defined in `tasks.md`. **T-067 through T-085** are the Phase 5 code-review mitigation tasks. Below is the exact completion state:

### Completed (T-067 – T-074, T-085)

| Task | Commit | Description |
|------|--------|-------------|
| T-067 | `36eaae4` | Fix credit service SELECT SUM + FOR UPDATE PostgreSQL crash |
| T-068 | `9a2e5e3` | Implement OAuth state parameter CSRF protection |
| T-069 | `6bee7b5` | Remove JWT token query parameter from auth middleware |
| T-070 | `384da31` | Fix rollback API field name mismatch (`version` → `version_number`) |
| T-071 | `9cfbee3` | Add missing database indexes (migration 0002) |
| T-072 | `894c671` | Protect Prometheus /metrics endpoint with bearer token auth |
| T-073 | `88d9ae9` | Add 500KB content size limits to AcceptDiffRequest and ContentEditRequest |
| T-074 | `2714944` | Catch SecurityError and ProviderError in SSE stream generators |
| T-085 | `2714944` | Extract shared `_stream_stage()` helper (done alongside T-074) |

### Remaining Phase 5 Tasks

These tasks are defined in `tasks.md` but NOT yet implemented. Work on them in order:

| Task | Title | Finding | Key File(s) |
|------|-------|---------|------------|
| **T-075** | Fix rate limiter and CSRF to use verified JWT claims | C9 | `backend/middleware/rate_limit.py`, `backend/middleware/csrf.py` |
| **T-076** | Cache LLM adapter instances in gateway | I1 | `backend/services/llm/gateway.py` |
| **T-077** | Configure SQLAlchemy connection pool for production | I2 | `backend/database.py`, `backend/config.py` |
| **T-078** | Validate WorkspaceCreate model against VALID_MODELS allowlist | I3 | `backend/schemas/workspace.py` |
| **T-079** | Fix apply_diff to use index positions instead of str.find | I4 | `backend/services/pipeline/diff_engine.py` |
| **T-080** | Add error callbacks to background eval asyncio tasks | I5 | `backend/services/pipeline/stage_manager.py` |
| **T-081** | Add double-refund guard to credit_service.refund() | I8 | `backend/services/credit_service.py` |
| **T-082** | Fix WorkspaceService.get authorization to prevent timing oracle | I9 | `backend/services/workspace_service.py` |
| **T-083** | Sanitize selected_text in refine stage router path | I10 | `backend/routers/stage.py` |
| **T-084** | Wrap Workspace.tsx async handlers in useCallback | I11 | `frontend/src/pages/Workspace.tsx` |

T-085 was completed as part of T-074 (they were naturally combined since T-085 is a prerequisite of T-074).

## Working Pattern

For each task:
1. Read the affected file(s)
2. Implement the fix
3. Run `cd backend && uv run pytest tests/ -q` (backend tasks)
   or `cd frontend && pnpm tsc --noEmit && pnpm test` (frontend tasks)
4. Run relevant harness test: `cd backend && uv run pytest ../harness/tests/backend/test_phase5_contract.py -k "<test_name>" -q`
5. Commit: `git add <files> && git commit -m "T-0XX: <description>..."`
6. After every 3-5 tasks: `git push origin main` and update this HANDOFF.md

## Harness Contract Tests

All contract tests for Phase 5 are in `harness/tests/backend/test_phase5_contract.py`.
Run from the `backend/` directory: `uv run pytest ../harness/tests/backend/test_phase5_contract.py -q`

Current harness pass/fail state (as of `2714944`):
- T-067 (C1): ✅ green
- T-068 (C2): need to verify
- T-069 (C3): need to verify
- T-070 (C4): need to verify
- T-071 (C5): ✅ green (4 tests)
- T-072 (C6): ✅ green
- T-073 (C7): ✅ green (3 tests)
- T-074 (C8): ✅ green (2 tests)
- T-075–T-084: 🔴 red (not yet implemented)

## Key Architecture Notes

**Auth flow (post T-068/T-069):**
- `GET /auth/google` → async `get_google_auth_url()` stores OAuth state in Redis (TTL 600s) → redirects to Google
- Google redirects to frontend `/auth/callback?code=xxx&state=yyy`
- Frontend `AuthCallback.tsx` reads both `code` AND `state`, passes both to backend
- `GET /auth/callback?code=xxx&state=yyy` → verifies state from Redis (single-use), exchanges code
- Only `Authorization: Bearer` header accepted — no `?token=` query param fallback

**SSE streaming (post T-074/T-085):**
- `_stream_stage(stage_id, user, db)` shared helper in `routers/stage.py`
- Catches: `StageDependencyError`, `RateLimitError`, `SecurityError`, `ProviderError`, `Exception`
- All errors emit structured SSE `{"error": "...", "detail": "..."}` before closing

**Credit service (post T-067):**
- `deduct()` now locks individual rows with `SELECT CreditLedger FOR UPDATE`, sums in Python
- No aggregate+lock pattern anywhere in credit_service.py

**Metrics endpoint (post T-072):**
- Set `METRICS_TOKEN` env var to enable bearer token auth
- Without token configured: only loopback IPs (127.0.0.1, ::1) are allowed

## Environment & Commands

```bash
# Backend tests (run from backend/)
uv run pytest tests/ -q

# Frontend type check + tests (run from frontend/)
pnpm tsc --noEmit
pnpm test

# Phase 5 harness (run from backend/)
uv run pytest ../harness/tests/backend/test_phase5_contract.py -q

# Run full stack
docker compose up --build
```

## Resume Checklist

```bash
git log --oneline -5          # Verify last commit
git status --short            # Check working tree
cd backend && uv run pytest tests/ -q   # Confirm baseline green
```

Then proceed with **T-075** (rate limiter / CSRF verified JWT claims) as the next task.
