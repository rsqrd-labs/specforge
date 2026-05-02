# SpecForge: Staff-Level Code Review

**Reviewed:** Full stack — FastAPI backend, React/TypeScript frontend, infra, CI  
**Date:** 2026-05-02  
**Reviewer:** Staff/Principal Engineer (automated deep scan)  
**Scope:** Architecture, security, performance, reliability, code quality, testing, DX

---

## Table of Contents

- [Critical Issues (Must Fix)](#-critical-issues-must-fix)
- [Important Improvements](#-important-improvements)
- [Minor Suggestions](#-minor-suggestions)
- [Architectural Recommendations](#-architectural-recommendations)
- [Quick Wins](#-quick-wins)
- [Overall Assessment](#-overall-assessment)

---

## 🔴 Critical Issues (Must Fix)

---

### C1. `SELECT SUM() ... FOR UPDATE` Is Invalid PostgreSQL Syntax — Credit Service Crashes in Production

**File:** `backend/services/credit_service.py:70–76`

```python
result = await db.execute(
    select(func.coalesce(func.sum(CreditLedger.amount), 0))
    .where(CreditLedger.user_id == user_id)
    .with_for_update()   # ← INVALID on aggregate queries
)
```

PostgreSQL explicitly forbids `FOR UPDATE` with aggregate functions: `ERROR: FOR UPDATE is not allowed with aggregate functions`. This crashes every real `deduct()` call in production. Tests use a fake DB that silently ignores the clause — the bug is completely invisible in CI and will only surface under real load.

**Fix:** Use a subquery with row-level locking, or use a denormalized balance column with optimistic locking. At minimum:

```python
# Option: lock rows first, then aggregate in application
rows = await db.execute(
    select(CreditLedger.amount)
    .where(CreditLedger.user_id == user_id)
    .with_for_update()
)
balance = sum(r.amount for r in rows.scalars())
```

---

### C2. OAuth CSRF: State Parameter Discarded — Login Flow Is CSRF-Vulnerable

**File:** `backend/services/auth_service.py:76–91`

```python
def get_google_auth_url(self) -> str:
    authorization_url, _state = self.oauth_client.create_authorization_url(...)
    return authorization_url  # _state is discarded
```

The `handle_callback` receives a code but never verifies a `state` parameter. An attacker can construct a URL that, when visited by an authenticated victim, completes authentication as the attacker's Google account. Classic OAuth CSRF.

**Fix:** Generate a cryptographically random state, store it in a short-lived Redis key (keyed by state value), and verify it in `handle_callback` before exchanging the code.

---

### C3. JWT Tokens Accepted in Query Parameters — Logged by Every Proxy

**File:** `backend/middleware/auth.py:17`

```python
token_param: str | None = Query(default=None, alias="token"),
```

The auth middleware accepts `?token=<JWT>` as a URL parameter. Tokens in URLs appear in server access logs, nginx logs, Sentry breadcrumbs, browser history, CDN caches, and `Referer` headers. The SSE client (`sseService.ts`) already uses `Authorization: Bearer` headers via `fetch()`, so this fallback is completely unused dead code that is purely a liability.

**Fix:** Remove `token_param` entirely.

---

### C4. Rollback Feature Is Silently Broken — API Field Name Mismatch

**File:** `frontend/src/services/api.ts:265` vs `backend/schemas/stage.py:84`

```typescript
// Frontend sends:
api.post(`/stages/${id}/rollback`, { version })
```
```python
# Backend expects:
class RollbackRequest(BaseModel):
    version_number: int = Field(ge=1)
```

The frontend sends `{ version: N }`, the backend requires `{ version_number: N }`. Pydantic validation rejects every rollback call with a `422 Unprocessable Entity`. The feature is silently broken end-to-end.

**Fix:** Change `api.ts:265` to `{ version_number: version }`.

---

### C5. Missing Database Indexes — Full Table Scans on Every Core Query

**File:** `backend/migrations/versions/0001_initial_schema.py`

The migration creates no indexes beyond primary keys. Critical missing indexes:

| Table | Column(s) | Query affected |
|-------|-----------|----------------|
| `credit_ledger` | `user_id` | Every balance calc and deduction (SUM query) |
| `stages` | `workspace_id` | Every stage lookup |
| `stages` | `status` | Recovery service, dependency checks |
| `stages` | `updated_at` | Recovery service stuck-stage detection |
| `stage_versions` | `stage_id` | Version listing and rollback |
| `workspaces` | `user_id` | Workspace listing |
| `eval_results` | `stage_version_id` | Eval fetch |

The credit balance SUM will be catastrophically slow as the ledger grows. This will cause production outages at any meaningful scale.

**Fix:** Single Alembic migration. ~30 minutes of work:

```python
op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
op.create_index("ix_stages_workspace_id", "stages", ["workspace_id"])
op.create_index("ix_stages_status", "stages", ["status"])
op.create_index("ix_stages_updated_at", "stages", ["updated_at"])
op.create_index("ix_stage_versions_stage_id", "stage_versions", ["stage_id"])
op.create_index("ix_workspaces_user_id", "workspaces", ["user_id"])
op.create_index("ix_eval_results_stage_version_id", "eval_results", ["stage_version_id"])
```

---

### C6. `/metrics` Endpoint Is Publicly Accessible

**File:** `backend/services/observability.py:222`

```python
@app.get("/metrics", include_in_schema=False)
async def metrics() -> StarletteResponse:
    return StarletteResponse(generate_latest(), ...)
```

Prometheus metrics are exposed without any authentication. `include_in_schema=False` only hides the route from OpenAPI docs — it is still fully accessible. Leaks endpoint names, request rates, error rates, and latency distributions — all useful for pre-attack reconnaissance.

**Fix:** Add an IP allowlist dependency or a static bearer token check to the `/metrics` route.

---

### C7. Unbounded Content Size — Memory/Storage DoS

**File:** `backend/schemas/stage.py:78,91`

```python
class AcceptDiffRequest(BaseModel):
    proposed_content: str   # no max length

class ContentEditRequest(BaseModel):
    content: str            # no max length
```

A user can POST 100 MB of content and it will be stored in PostgreSQL's `Text` column, held in memory during the response, and streamed through the DB connection. Neither schema nor any middleware imposes a body size limit.

**Fix:** `Field(max_length=100_000)` on both fields.

---

### C8. `SecurityError` and `ProviderError` Not Caught in SSE Stream — Client Hangs

**File:** `backend/routers/stage.py:69–88`

The `_stream()` generator only catches `StageDependencyError` and `RateLimitError`. When a `SecurityError` (prompt injection / output validation failure) or `ProviderError` (LLM API down) is raised, the exception propagates out of the generator. The client receives a truncated stream with no error event and hangs until a connection timeout.

**Fix:**
```python
except (SecurityError, ProviderError) as exc:
    error_payload = json.dumps({"error": "generation_failed", "detail": str(exc)})
    yield f"data: {error_payload}\n\n"
```

---

### C9. User-ID Spoofing in Rate Limiter via Unverified JWT Claims

**File:** `backend/middleware/rate_limit.py:83`, `backend/middleware/csrf.py:51`

```python
claims = jose_jwt.get_unverified_claims(token)  # no signature verification
return claims.get("sub")
```

Anyone can craft a JWT with `sub = victim_user_id` (no valid signature needed) and their requests will be counted against the victim's per-user rate limit bucket. An attacker can exhaust a specific user's 100 req/min quota without spending a single real authenticated token. The CSRF middleware uses the same pattern.

**Fix:** Either verify the token before extracting claims for rate-limit keying, or use a separate signed identifier for the rate limit key (e.g., derive from the IP + a validated session token).

---

## 🟡 Important Improvements

---

### I1. LLM Adapter Creates New HTTP Client Per Generation

**File:** `backend/services/llm/anthropic_adapter.py:13`

```python
class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
```

`get_llm(provider, model)` instantiates a new adapter — and therefore a new `AsyncAnthropic` HTTP client with its own connection pool — on every single generation call. Under load, this exhausts file descriptors and prevents HTTP connection reuse.

**Fix:** Cache adapter instances by provider in `gateway.py` as module-level singletons.

---

### I2. DB Connection Pool Uses Defaults — Will Exhaust Under Load

**File:** `backend/database.py:7`

```python
async_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
```

SQLAlchemy defaults to `pool_size=5, max_overflow=10`. Under concurrent streaming generations, you will hit connection timeout errors.

**Fix:**
```python
async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)
```

---

### I3. LLM Model String Not Validated Against Allowed List

**File:** `backend/schemas/workspace.py:14`

```python
class WorkspaceCreate(BaseModel):
    model: str = Field(min_length=1)
```

`VALID_MODELS` exists in `provider_config.py` but is never used during workspace creation. A user can store `model="garbage"` and only get an API-level error on first generation — after already being charged credits if the refund path doesn't fire correctly.

**Fix:** Add a Pydantic validator:
```python
@field_validator("model")
@classmethod
def validate_model(cls, v: str, info: ValidationInfo) -> str:
    provider = info.data.get("provider")
    if provider and v not in VALID_MODELS.get(provider, set()):
        raise ValueError(f"Model {v!r} is not valid for provider {provider!r}")
    return v
```

---

### I4. `apply_diff` Uses `str.find` — Breaks on Duplicate Text

**File:** `backend/services/pipeline/diff_engine.py:22`

```python
def apply_diff(original: str, selected_text: str, replacement: str) -> str:
    idx = original.find(selected_text)   # first occurrence only
```

If the document contains the selected text more than once, the wrong occurrence gets replaced. The `RefineRequest` already includes `selection_start`/`selection_end` index positions. Use them.

**Fix:**
```python
def apply_diff(original: str, start: int, end: int, replacement: str) -> str:
    return original[:start] + replacement + original[end:]
```

---

### I5. `asyncio.create_task` Swallows Eval Exceptions Silently

**File:** `backend/services/pipeline/stage_manager.py:143`

```python
asyncio.create_task(run_eval_background(...))
```

Background tasks created this way fail silently. Failed evals are invisible in production.

**Fix:**
```python
task = asyncio.create_task(run_eval_background(...))
task.add_done_callback(
    lambda t: t.exception() and logger.error("eval_background_failed", exc_info=t.exception())
)
```

---

### I6. Frontend Polls for Eval 6 × 5s = 30 Seconds After Every Generation

**File:** `frontend/src/hooks/useStream.ts:19`

```typescript
async function pollEval(stageId: string): Promise<EvalResult | null> {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try { return await getStageEval(stageId) }
    catch { await new Promise(resolve => setTimeout(resolve, 5_000)) }
  }
  return null
}
```

At 100 concurrent users this is 600 extra DB queries per minute just for eval results. The eval is a background job — the frontend should not be driving the check cycle.

**Fix:** Include the eval result in the SSE done event on the backend, or push it via a subsequent SSE notification when the eval task completes.

---

### I7. Recovery Service Credit Refund Heuristic Is Fragile

**File:** `backend/services/pipeline/recovery_service.py:43`

```python
CreditLedger.created_at >= stage.updated_at - timedelta(seconds=60),
```

The 60-second window for finding the matching ledger entry can be missed under load, clock drift, or if a user has multiple stages stuck simultaneously (wrong ledger entry gets refunded).

**Fix:** Store `credit_ledger_entry_id` directly on the `Stage` model at deduction time, then use it exactly in the recovery path.

---

### I8. No Double-Refund Protection in Credit Ledger

**File:** `backend/services/credit_service.py:86`

If `refund()` is called twice with the same `ledger_entry_id` (e.g., recovery service racing the router exception handler), two positive ledger entries are created and the user receives double credits.

**Fix:**
```python
existing = await db.execute(
    select(CreditLedger).where(CreditLedger.reason == f"refund:{ledger_entry_id}")
)
if existing.scalar_one_or_none():
    return  # already refunded
```

---

### I9. `WorkspaceService.get` Has a Timing Oracle for IDOR

**File:** `backend/services/workspace_service.py:57–71`

The service fetches the workspace by ID first, then checks `user_id` in Python. A workspace that doesn't exist returns 404 immediately (no DB row found); an unauthorized workspace returns 404 after a full DB fetch. A timing oracle could enumerate workspace IDs.

**Fix:** Add `Workspace.user_id == user_id` to the `WHERE` clause in the DB query itself so both cases execute identically.

---

### I10. `selected_text` Sent to LLM Without Sanitization

**File:** `backend/routers/stage.py:130–131`

```python
sanitized_request = request.model_copy(
    update={"instruction": sanitize_text(request.instruction)}
)
```

Only `instruction` is sanitized. `selected_text` is passed raw to the LLM. Subsequent content edits via `PATCH /stages/{id}/content` can introduce content that bypasses the creation-time sanitization, which then flows unsanitized into the LLM context.

**Fix:** Sanitize both `instruction` and `selected_text`.

---

### I11. Missing `useCallback` on Workspace Async Handlers — Re-renders on Every Token

**File:** `frontend/src/pages/Workspace.tsx:163–317`

Nine async functions (`requestGeneration`, `runRefine`, `acceptDiff`, `handleFinalise`, `handleContentChange`, etc.) are redefined on every render. Child components that receive these as props (`GenerateBar`, `DiffViewer`, `StageNavigator`) re-render on every parent state change — including every SSE token arriving during streaming. A 4096-token generation triggers ~4096 × N unnecessary child renders.

**Fix:** Wrap all stable handlers in `useCallback` with appropriate dependencies.

---

### I12. No SSE Retry/Backoff on Transient Network Errors

**File:** `frontend/src/services/sseService.ts:123`

Any network error immediately calls `onError()` and terminates the stream. A momentary WiFi drop during a 30-second generation loses all progress and forces the user to restart.

**Fix:** Implement exponential backoff with 3 retries before surfacing the error. Resume from a checkpoint if the server supports it.

---

### I13. Modal Focus Trap Missing — Keyboard Navigation Breaks

**Files:** `frontend/src/components/workspace/CreditConfirmModal.tsx`, `HumanReviewGate.tsx`, `CreateWorkspaceModal.tsx`

No `role="dialog"`, no `aria-modal="true"`, no focus trap. Keyboard-only users can tab behind the modal overlay into the disabled background content.

**Fix:** Add `role="dialog"` + `aria-modal="true"` and integrate `focus-trap-react` for all three modals.

---

### I14. `generate` and `regenerate` Endpoints Are Identical — 30 Lines of Duplication

**File:** `backend/routers/stage.py:60–119`

Both endpoints contain copy-pasted identical code calling `stage_manager.generate()`. The distinction between first-time generation and force-regeneration should be a parameter on `generate`, not a separate endpoint.

---

## 🟢 Minor Suggestions

---

### M1. `sentry_dsn`, `grafana_otlp_endpoint`, `grafana_otlp_token` Should Be Optional at Type Level

**File:** `backend/config.py:21–23`

These are guarded in `observability.py` with `_is_configured_url()`, but Pydantic marks them as required `str`. The `.env.example` workarounds with placeholder strings is a leaky abstraction. Use `str = ""` to make optionality explicit.

---

### M2. `_DEPENDENCIES` Dict Is Defined Twice

**Files:** `backend/services/pipeline/stage_manager.py:31–36`, `backend/services/pipeline/prompt_builder.py:29–34`

Identical `STAGE_DEPENDENCIES` / `_DEPENDENCIES` dicts in both files can diverge independently. Extract to a shared `constants.py`.

---

### M3. `_maybe_await` Is a Test-Seam Anti-Pattern

**File:** `backend/services/auth_service.py:255`

```python
async def _maybe_await(self, value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
```

This exists to handle both sync and async mock return values in tests. It pushes test infrastructure concerns into production code. Tests should use `AsyncMock` directly.

---

### M4. `check_redis` in Health Check Creates a Throwaway Connection

**File:** `backend/main.py:37–51`

The health check creates a fresh Redis connection, pings it, and immediately discards it. This tests connectivity but not the actual Redis client pool the app uses. Reuse an existing client.

---

### M5. No Pagination on List Endpoints

`GET /workspaces` returns all workspaces; `GET /stages/{id}/versions` returns all versions. Add cursor-based pagination before users accumulate significant history.

---

### M6. CodeMirror Editor Has No ARIA Role

**File:** `frontend/src/components/workspace/StageEditor.tsx`

The editor container needs `role="textbox"`, `aria-multiline="true"`, `aria-label="Stage content editor"`. Screen readers cannot identify or interact with it.

---

### M7. Avatar `alt` Text Is Empty

**File:** `frontend/src/pages/Dashboard.tsx:48`

`alt=""` is correct for decorative images but incorrect for a user avatar that identifies the authenticated user.

**Fix:** `alt={`${user.name || user.email} avatar`}`

---

### M8. Silent `.catch()` Blocks Suppress Errors Completely

**Files:** `frontend/src/pages/Dashboard.tsx:18`, `frontend/src/hooks/useCredits.ts:23`, `frontend/src/pages/Workspace.tsx:150`

Several error paths call `.catch(() => undefined)` or `.catch(() => setBalance(null))` with no logging. Debugging production failures becomes impossible.

**Fix:** Add `console.error` (or structured logging service) calls before swallowing the error.

---

### M9. `HTTPException` Imported Inside Function Bodies

**File:** `backend/services/pipeline/stage_manager.py:252, 365`

`from fastapi import HTTPException` appears inside method bodies. Move to module-level imports.

---

### M10. Error Response Structure Is Inconsistent Across Endpoints

Some endpoints return `detail` as a string; others as a dict with varying field names (`error`, `code`, `message`, `detail`). This complicates consistent client-side error handling. Standardize on a single error envelope.

---

## 🧠 Architectural Recommendations

---

### A1. Stage Status Transitions Need a State Machine, Not String Comparisons

Stage transitions (`locked → draft → in_progress → finalised → stale`) are enforced via scattered `if stage.status != "draft"` checks across `stage_manager.py`. There is no centralized transition table to prevent illegal jumps (e.g., `locked → finalised`). As the system grows, invalid state bugs will accumulate.

**Recommendation:** Define an explicit allowed-transitions dict and a `transition(stage, target_status)` function that validates and applies atomically. This also makes the state machine auditable in a single place.

---

### A2. Credit Deduction Has Two Sources of Truth

The flow is: `require_credits` middleware (cached, advisory read) → `credit_service.deduct` (row-locked read + write). The middleware check is purely advisory since it reads a potentially stale Redis cache. This creates an illusion of atomicity. Either trust the row-locked `deduct` exclusively and remove the middleware check, or make both part of the same transaction.

---

### A3. Background Eval Needs a Proper Task Queue

`stage_manager.generate()` directly calls `run_eval_background()` via `asyncio.create_task`. This couples the generation critical path to the eval system. A crashed eval task is invisible; there is no dead-letter queue, retry policy, or observability. For a system this size, even a simple queue (ARQ/Celery) improves reliability and debuggability.

---

### A4. `Workspace.tsx` Is a God Component

**File:** `frontend/src/pages/Workspace.tsx` (530 lines, 17 state variables, 9+ async operations)

The component manages: streaming lifecycle, diff review state, credit modal flow, review gate flow, eval polling, export, editor content, staleness warnings, and error display — all in one component.

**Recommendation:** Extract into domain-specific custom hooks and sub-components:
- `useGenerationFlow()` — streaming, SSE, and stage state
- `useRefineFlow()` — selection, diff, accept/reject
- `useCreditFlow()` — modal, balance check, gate acknowledgement
- Keep `Workspace` as a thin orchestrator

---

### A5. LLM Adapters Should Be Singletons with Retry

All three adapters (`anthropic_adapter.py`, `openai_adapter.py`, `google_adapter.py`) create new HTTP clients per call and have no retry logic. Transient provider errors (rate limits, 503s) immediately surface as user-visible failures. Register adapters as singletons in `gateway.py` and add exponential backoff using `tenacity`.

---

## ⚡ Quick Wins

| # | Fix | File | Effort | Impact |
|---|-----|------|--------|--------|
| 1 | Add missing DB indexes (new migration) | `migrations/versions/` | 30 min | Critical — prevents prod outage |
| 2 | Fix rollback field name: `version` → `version_number` | `frontend/src/services/api.ts:265` | 2 min | Critical — broken feature |
| 3 | Remove `token_param` query param | `backend/middleware/auth.py:17` | 5 min | High — security |
| 4 | Catch `SecurityError`/`ProviderError` in `_stream()` | `backend/routers/stage.py:69–119` | 15 min | High — broken UX |
| 5 | Add `max_length` to `proposed_content` / `content` schemas | `backend/schemas/stage.py` | 5 min | High — DoS prevention |
| 6 | Protect `/metrics` with token or IP check | `backend/services/observability.py` | 15 min | Medium — info disclosure |
| 7 | Configure DB pool size | `backend/database.py` | 5 min | High — production reliability |
| 8 | Fix PostgreSQL `SUM + FOR UPDATE` | `backend/services/credit_service.py` | 30 min | Critical — crashes in prod |
| 9 | Fix OAuth state parameter generation + verification | `backend/services/auth_service.py` | 1 hr | High — security |
| 10 | Cache LLM adapter instances in gateway | `backend/services/llm/gateway.py` | 20 min | Medium — performance |
| 11 | Add `useCallback` to Workspace handlers | `frontend/src/pages/Workspace.tsx` | 45 min | Medium — streaming perf |
| 12 | Fix `apply_diff` to use index positions | `backend/services/pipeline/diff_engine.py` | 10 min | Medium — correctness |
| 13 | Add double-refund guard to `credit_service.refund` | `backend/services/credit_service.py` | 15 min | Medium — financial integrity |
| 14 | Add ARIA role + label to CodeMirror editor | `frontend/src/components/workspace/StageEditor.tsx` | 10 min | Medium — a11y |

---

## 📊 Overall Assessment

### Codebase Maturity: **Strong MVP approaching Production-Ready**

---

### Key Strengths

- **Auth security is genuinely solid.** RS256 JWTs with asymmetric keys, HTTP-only cookies scoped to `/auth/refresh` for refresh tokens, JTI-based refresh token rotation with session invalidation on reuse detection, HMAC CSRF tokens tied to user ID. Better than most production SaaS systems at this stage.
- **Credit accounting is principled.** Ledger-based double-entry with row locking (intent is correct even if the PostgreSQL aggregate syntax is broken), automatic refunds on provider failure, middleware pre-check — the design is sound.
- **Security defence-in-depth is real.** Prompt injection scanning, output validation for system prompt leakage, `bleach` HTML sanitization, Fernet encryption for user API keys, structured log scrubbing with secret redaction, Sentry event redaction — someone thought carefully about all of these.
- **Test structure is mature.** Isolated service tests with hand-rolled fakes (not fragile mocks), testing refund paths on LLM failure, rate limit enforcement, injection detection. The test philosophy is right.
- **CI is production-grade.** TruffleHog secret scanning, Bandit, Safety, 80% coverage threshold, `pnpm audit`. Rare to see this at MVP stage.
- **Observability is first-class.** Prometheus metrics, structured logging with `structlog`, OTLP traces, Sentry with secret scrubbing. Most companies don't get here until Series B.
- **Streaming architecture is clean.** SSE with fetch-based client, proper token accumulation, correct backpressure, credit refund on stream failure.

---

### Key Risks

1. **The PostgreSQL `SUM + FOR UPDATE` bug (C1) will crash every concurrent credit deduction in production.** Highest priority fix.
2. **Five missing DB indexes (C5) will degrade from fast to broken at ~1,000 users.**
3. **Rollback is silently broken (C4)** — field name mismatch causes 100% failure rate.
4. **Unhandled SSE exceptions (C8)** leave clients hanging on security violations and LLM errors.
5. **OAuth state bypass (C2)** is a real attack vector against users, not a theoretical concern.

---

### Final Verdict

This is a well-architected, thoughtfully secured codebase written by someone who clearly understands production engineering. The auth stack, observability, and security layering are genuinely impressive for an MVP. However, there are **critical bugs that will break the app in production** — the credit service PostgreSQL crash and the broken rollback are regressions that need immediate fixes. The missing indexes are a scalability time bomb.

**Fix C1, C4, C5, C8 (one day of work) and this is launchable. Fix C2, C3, C9 in the following sprint.**

The architectural debt (god component, no state machine for stage transitions, polling instead of push for evals) is real but not blocking. Address it as the team grows and the codebase is touched more frequently.

---

*Generated by automated staff-level review — 2026-05-02*
