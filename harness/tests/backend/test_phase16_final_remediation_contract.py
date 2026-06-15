"""
Harness contracts for Phase 16 — Final Remediation & Enterprise Hardening.

These tests are RED before T-196 through T-216 are implemented and GREEN after.

Every test maps to one or more findings from docs/CODE_REVIEW_PASS_2.md:

  CF-1  finalise() missing SELECT FOR UPDATE (unresolved despite T-174)
        → T-196 — pessimistic lock wired in; misleading mock test deleted;
          real PostgreSQL integration test added
  CF-2  Circuit breaker observability-only — gateway never consults health
        → T-197 — can_route() added to provider_status; gateway enforces it
  HF-1  N+1 coverage query still present after T-178 partial fix
        → T-198 — batch query verified end-to-end
  HF-2  OpenAI adapter chunks with empty choices[] cause IndexError
        → T-199 — guard added before chunk.choices[0] access
  HF-3  Recovery lock heartbeat fires once, not continuously
        → T-200 — asyncio.Task for continuous expire refresh
  HF-4  asyncio.get_event_loop() deprecated in pdf_export_service
        → T-201 — get_running_loop() + dedicated ThreadPoolExecutor
  HF-5  RateLimitMiddleware creates its own Redis pool (inconsistent injection)
        → T-202 — lazy injection via request.app.state.redis
  HF-6  CSRF nonce not tracked in Redis — 1-hour replay window
        → T-203 — Redis SETNX nonce tracking in verify_csrf_token()
  HF-7  CI has no real DB/Redis service containers; coverage illusion
        → T-204 — services: block + alembic upgrade head + integration test
  MF-1  asyncio.shield() eval orphan tasks on timeout
        → T-205 — explicit task.cancel() + shielded cleanup
  MF-2  Cross-module private import (_derive_coverage_summary across modules)
        → T-206 — moved to shared coverage_utils module
  MF-3  refund() db.rollback() rolls back outer transaction
        → T-207 — savepoint (begin_nested) isolates IntegrityError
  MF-4  TemplatesStrip rendered without error boundary in Dashboard
        → T-208 (frontend) — wrapped in generic error boundary
  MF-5  Langfuse docker-compose image tag unpinned (latest)
        → T-209 — pinned to specific semver digest
  LF-1  Auth cache multi-worker incoherence (_USER_CACHE per-process)
        → T-210 — documented limitation + Redis-backed cache option
  LF-2  Thread pool contention: PDF exports share pool with Langfuse
        → T-211 — dedicated ThreadPoolExecutor for PDF
  LF-3  False-confidence test (test_finalise_concurrent_tasks_only_one_advances)
        → T-196 + T-212 — test deleted; replaced by real integration test
  LF-4  eval_results missing composite index on (stage_version_id, created_at)
        → T-213 — migration 0012 adds index
  T-214  test_concurrency.py misleading mock test must be removed
        → T-214 — explicit contract that the false-confidence test is gone
  T-215  LLM circuit breaker Prometheus metrics
        → T-215 — specforge_llm_circuit_rejections_total counter
  T-216  Production runbook for CF-1/CF-2 operational procedures
        → T-216 — RUNBOOK.md exists with required sections

Design invariants enforced here:
  * finalise() acquires row-level lock via SELECT FOR UPDATE — lock=True.
  * circuit-breaker can_route() wired into gateway.get_llm().
  * Coverage derivation is O(1) queries for workspace list (batch confirmed).
  * OpenAI adapter guards empty choices[] before index access.
  * Recovery lock is refreshed continuously during cycle execution.
  * PDF export uses get_running_loop() and a dedicated thread pool.
  * RateLimitMiddleware does not create its own Redis connection pool.
  * CSRF nonce stored in Redis after every verify — 1-hour replay window closed.
  * CI YAML contains a real postgres service container.
  * Timed-out eval tasks are explicitly cancelled — no orphan coroutines.
  * _derive_coverage_summary lives in a shared utility, not a private module.
  * refund() uses savepoint to isolate IntegrityError.
  * Langfuse image is pinned to a specific digest/tag (not :latest).
  * eval_results composite index exists in migration history.
  * The misleading mock concurrency test is DELETED.
  * specforge_llm_circuit_rejections_total counter exists and is wired.
  * RUNBOOK.md documents CF-1 and CF-2 operational procedures.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import BACKEND_ROOT, REPO_ROOT, read_backend_file


# ---------------------------------------------------------------------------
# T-196 (CF-1): finalise() MUST call _load_stage with lock=True
# ---------------------------------------------------------------------------


def test_phase16_finalise_uses_lock_true() -> None:
    """CF-1 — The T-174/Phase-15 fix was incomplete.

    `finalise()` calls `_load_stage(stage_id, db)` without `lock=True`.
    The `_load_stage` helper accepts `lock: bool = False` and applies
    `.with_for_update()` when True. The one-character gap means PostgreSQL
    never issues SELECT FOR UPDATE — two concurrent finalise() calls can
    both read status='draft', both advance the stage, and both charge credits.

    This test verifies the pessimistic lock is actually wired in.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert "async def finalise" in source or "def finalise" in source, (
        "stage_manager.py must define a finalise() function. CF-1 — T-196."
    )

    # Extract only the body of finalise() to avoid false positives from other
    # functions that correctly call _load_stage(lock=True).
    fn_match = re.search(
        r"(async\s+def\s+finalise\s*\([^)]*\)[^:]*:)(.*?)(?=\n\s{0,4}(?:async\s+)?def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, "Could not extract finalise() body. CF-1 — T-196."
    finalise_body = fn_match.group(2)

    assert re.search(r"_load_stage\([^)]*lock\s*=\s*True", finalise_body), (
        "finalise() must call _load_stage(..., lock=True) to issue SELECT FOR "
        "UPDATE. The current call omits lock=True, leaving a race window where "
        "two concurrent finalise() calls can both read status='draft' and both "
        "advance, double-charging credits and corrupting stage state. CF-1 — T-196."
    )


def test_phase16_finalise_integration_test_file_exists() -> None:
    """CF-1 — A real PostgreSQL integration test must accompany the SELECT FOR UPDATE fix.

    The mock-only concurrency test provides false confidence. A file named
    test_finalise_integration.py (or similar) must exist in backend/tests/
    and contain actual database-level SELECT FOR UPDATE coverage.
    """
    tests_dir = BACKEND_ROOT / "tests"
    candidates = list(tests_dir.glob("test_finalise_integration*.py")) + list(
        tests_dir.glob("test_*integration*.py")
    )
    found_db_test = False
    for f in candidates:
        content = f.read_text(encoding="utf-8")
        # Must reference real DB patterns — not just MagicMock
        if (
            "select_for_update" in content.lower()
            or "with_for_update" in content.lower()
            or "asyncpg" in content
            or "create_async_engine" in content
        ) and "AsyncSession" in content:
            found_db_test = True
            break

    assert found_db_test, (
        "backend/tests/ must contain a PostgreSQL integration test (e.g. "
        "test_finalise_integration.py) that exercises the SELECT FOR UPDATE "
        "path via a real AsyncSession + asyncpg connection. Mock-only tests "
        "cannot validate that PostgreSQL actually serialises concurrent "
        "finalise() calls. CF-1 — T-196."
    )


# ---------------------------------------------------------------------------
# T-214 (LF-3): Misleading mock concurrency test must be DELETED
# ---------------------------------------------------------------------------


def test_phase16_misleading_mock_finalise_test_is_gone() -> None:
    """LF-3 / T-214 — test_finalise_concurrent_tasks_only_one_advances must be removed.

    This test in test_concurrency.py uses a _RacingDB that mutates `stage.status`
    inside `execute()` to simulate the race. It NEVER issues a real SELECT FOR
    UPDATE. It passes regardless of whether the real code uses `lock=True` — it
    is a false-confidence test that masks the unfixed CF-1 bug.

    The test must be DELETED. Its coverage must be replaced by the real
    integration test required by T-196.
    """
    concurrency_file = BACKEND_ROOT / "tests" / "test_concurrency.py"
    if not concurrency_file.exists():
        return  # file gone entirely — also acceptable

    content = concurrency_file.read_text(encoding="utf-8")

    assert "test_finalise_concurrent_tasks_only_one_advances" not in content, (
        "backend/tests/test_concurrency.py must NOT contain "
        "'test_finalise_concurrent_tasks_only_one_advances'. This mock-based "
        "test simulates the CF-1 race via in-memory object mutation — it never "
        "touches PostgreSQL, never validates SELECT FOR UPDATE, and passes even "
        "when lock=True is absent. Delete it; replace with the integration test "
        "required by T-196 (test_finalise_integration.py). LF-3 — T-214."
    )


# ---------------------------------------------------------------------------
# T-197 (CF-2): Circuit breaker must be enforced in gateway.get_llm()
# ---------------------------------------------------------------------------


def test_phase16_provider_status_has_can_route() -> None:
    """CF-2 — provider_status.py must expose a can_route() function.

    The current implementation tracks failures correctly via
    record_provider_failure() and _provider_health() but the circuit is
    observability-only — no call site ever consults the health status before
    routing. A can_route(provider) -> bool function must exist so gateway.get_llm()
    can enforce the circuit and reject requests to unhealthy providers.
    """
    source = read_backend_file("services", "llm", "provider_status.py")

    assert "def can_route" in source or "async def can_route" in source, (
        "services/llm/provider_status.py must define a can_route(provider) -> bool "
        "function that returns False when the provider has exceeded its failure "
        "threshold. The current circuit is observability-only — failures are tracked "
        "but never enforced. CF-2 — T-197."
    )


def test_phase16_gateway_consults_can_route() -> None:
    """CF-2 — gateway.get_llm() must call can_route() before returning an adapter.

    Without this wiring, the circuit breaker never rejects requests. The gateway
    must raise (or fall through to a secondary provider) when can_route() returns
    False, ensuring unhealthy providers are not sent more traffic.
    """
    source = read_backend_file("services", "llm", "gateway.py")

    assert "can_route" in source, (
        "services/llm/gateway.py must import and call can_route() from "
        "provider_status to enforce the circuit breaker. The circuit is currently "
        "observability-only — failures are recorded but gateway.get_llm() never "
        "checks whether a provider is healthy before routing. CF-2 — T-197."
    )

    # Verify can_route is called inside get_llm(), not just imported
    fn_match = re.search(
        r"(async\s+def\s+get_llm\s*\([^)]*\)[^:]*:)(.*?)(?=\n\s{0,4}(?:async\s+)?def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    if fn_match:
        get_llm_body = fn_match.group(2)
        assert "can_route" in get_llm_body, (
            "can_route() must be called inside get_llm() body, not just imported. "
            "CF-2 — T-197."
        )


def test_phase16_circuit_breaker_rejection_counter_defined() -> None:
    """CF-2 / T-215 — A Prometheus counter must be incremented on circuit rejection.

    Without instrumentation, circuit breaker activations are silent. Operators
    cannot distinguish 'no traffic' from 'circuit open'. The counter
    specforge_llm_circuit_rejections_total must be defined and incremented
    when can_route() returns False.
    """
    all_backend = list(BACKEND_ROOT.rglob("*.py"))
    found = any(
        "specforge_llm_circuit_rejections_total" in f.read_text(encoding="utf-8")
        for f in all_backend
    )
    assert found, (
        "backend/ must define a Prometheus Counter "
        "'specforge_llm_circuit_rejections_total' and increment it every time "
        "a request is rejected because can_route() returns False. Without this "
        "metric, circuit breaker activations are invisible in dashboards. "
        "CF-2 / T-215."
    )


# ---------------------------------------------------------------------------
# T-198 (HF-1): Coverage derivation must be O(1) queries — batch verified
# ---------------------------------------------------------------------------


def test_phase16_derive_coverage_accepts_list() -> None:
    """HF-1 — _derive_coverage_summary must accept a list of IDs for batching.

    The T-178 fix was marked complete but the N+1 pattern may still be present.
    The workspace list endpoint must issue a single batched SQL query for coverage
    across all workspaces, not one query per workspace.

    This test verifies the function signature accepts a collection (not a single UUID)
    so it can issue a WHERE ... IN (...) query.
    """
    source = read_backend_file("routers", "workspace.py")

    # The function may have moved to coverage_utils; check both locations
    coverage_utils_path = BACKEND_ROOT / "services" / "coverage_utils.py"
    if coverage_utils_path.exists():
        source += coverage_utils_path.read_text(encoding="utf-8")

    # Check for list/sequence parameter in _derive_coverage_summary
    fn_match = re.search(
        r"def _derive_coverage_summary\s*\(([^)]*)\)",
        source,
    )
    if fn_match:
        params = fn_match.group(1)
        # Should accept list, Sequence, Iterable, or set — not just UUID
        has_collection_param = bool(
            re.search(r"list\[|List\[|Sequence\[|Iterable\[|set\[|Collection\[", params)
        )
        assert has_collection_param, (
            "_derive_coverage_summary() must accept a collection of workspace IDs "
            "(e.g. list[UUID]) so it can issue a single batched query. A single-UUID "
            "signature forces N+1 calls in the workspace list endpoint. HF-1 — T-198."
        )

    # Also confirm no per-workspace loop remains in the router
    loop_n_plus_1 = re.search(
        r"for\s+\w+\s+in\s+workspaces\b.*_derive_coverage_summary",
        source,
        re.DOTALL,
    )
    assert not loop_n_plus_1, (
        "workspace.py must not call _derive_coverage_summary inside a per-workspace "
        "loop. Issue a single batched query. HF-1 — T-198."
    )


def test_phase16_coverage_query_uses_in_clause() -> None:
    """HF-1 — The batched coverage query must use WHERE ... IN (workspace_ids).

    A single IN-clause query scales O(1) regardless of workspace count.
    """
    source = read_backend_file("routers", "workspace.py")
    coverage_utils_path = BACKEND_ROOT / "services" / "coverage_utils.py"
    if coverage_utils_path.exists():
        source += coverage_utils_path.read_text(encoding="utf-8")

    has_in_clause = (
        ".in_(" in source
        or "IN (" in source
        or "in_(" in source
        or "where_in" in source.lower()
    )
    assert has_in_clause, (
        "The batched coverage query must use a SQL IN clause (SQLAlchemy .in_() "
        "or equivalent) to fetch coverage for all workspace IDs in one round-trip. "
        "HF-1 — T-198."
    )


# ---------------------------------------------------------------------------
# T-199 (HF-2): OpenAI adapter must guard empty choices[]
# ---------------------------------------------------------------------------


def test_phase16_openai_adapter_guards_empty_choices() -> None:
    """HF-2 — OpenAI streaming chunks with empty choices[] must be skipped.

    The OpenAI API sends usage-only chunks where `chunk.choices` is an empty list.
    Accessing `chunk.choices[0]` on such a chunk raises IndexError, crashing the
    stream and leaving the credit reservation unreleased.

    The fix must check `if not chunk.choices: continue` (or equivalent) before
    any index access.
    """
    source = read_backend_file("services", "llm", "openai_adapter.py")

    # The guard must appear before any choices[0] access
    # Look for common guard patterns
    has_guard = bool(
        re.search(r"if\s+not\s+chunk\.choices", source)
        or re.search(r"if\s+len\(chunk\.choices\)\s*==\s*0", source)
        or re.search(r"if\s+chunk\.choices\s*and", source)
        or re.search(r"choices\s*=\s*\w+\.\s*choices.*\n.*if\s+not\s+choices", source, re.DOTALL)
    )
    assert has_guard, (
        "services/llm/openai_adapter.py must guard against empty chunk.choices "
        "before accessing chunk.choices[0]. The OpenAI API sends usage-only "
        "chunks where choices=[] and delta is absent — unguarded access raises "
        "IndexError, crashing the SSE stream. Add: "
        "  if not chunk.choices: continue\n"
        "HF-2 — T-199."
    )

    # Confirm choices[0] access still exists (the feature is not just removed)
    assert "choices[0]" in source or "choices[" in source, (
        "openai_adapter.py must still access chunk.choices[0] for normal streaming "
        "chunks — the guard must skip empty-choices chunks, not remove the access. "
        "HF-2 — T-199."
    )


# ---------------------------------------------------------------------------
# T-200 (HF-3): Recovery lock heartbeat must be a continuous asyncio.Task
# ---------------------------------------------------------------------------


def test_phase16_recovery_heartbeat_uses_asyncio_task() -> None:
    """HF-3 — Recovery lock heartbeat must use asyncio.create_task for continuous refresh.

    The current code calls `await refresh_recovery_lock(redis)` once before the
    recovery cycle begins. A long-running recovery (multiple stages, slow DB) will
    run past the lock TTL with no refresh, allowing a concurrent runner to acquire
    the lock and double-process the same stages.

    A continuous heartbeat (asyncio.Task that loops `redis.expire(lock_key, TTL)`
    every TTL/3 seconds) must be created before the cycle and cancelled after.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    # Must use asyncio.create_task for the heartbeat loop
    has_heartbeat_task = bool(
        re.search(r"create_task\s*\(", source)
        and (
            re.search(r"recovery.*heartbeat", source, re.IGNORECASE)
            or re.search(r"heartbeat.*recovery", source, re.IGNORECASE)
            or re.search(r"create_task.*expire", source, re.DOTALL)
            or re.search(r"_heartbeat\s*=\s*asyncio\.create_task", source)
        )
    )
    assert has_heartbeat_task, (
        "stage_manager.py recovery loop must use asyncio.create_task() to run a "
        "continuous heartbeat coroutine that calls redis.expire(lock_key, TTL) "
        "every TTL/3 seconds. A single pre-cycle refresh() call is insufficient "
        "for long-running recoveries. HF-3 — T-200."
    )


def test_phase16_recovery_heartbeat_is_cancelled_after_cycle() -> None:
    """HF-3 — The heartbeat task must be cancelled (and awaited) after the recovery cycle.

    Leaving the task running after the cycle ends either keeps the lock alive
    indefinitely or logs spurious errors. Use try/finally to guarantee cancellation.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    # After create_task, there must be a .cancel() call (typically in finally)
    has_cancel = bool(
        re.search(r"_heartbeat\w*\.cancel\(\)", source)
        or re.search(r"heartbeat\w*\.cancel\(\)", source)
        or (
            re.search(r"create_task", source)
            and re.search(r"\.cancel\(\)", source)
            and "heartbeat" in source.lower()
        )
    )
    assert has_cancel, (
        "stage_manager.py must cancel() the recovery heartbeat asyncio.Task after "
        "the recovery cycle completes (in a finally block). Uncancelled tasks keep "
        "the lock alive past recovery and may cause spurious log errors. "
        "HF-3 — T-200."
    )


# ---------------------------------------------------------------------------
# T-201 (HF-4): PDF export must use get_running_loop() and dedicated executor
# ---------------------------------------------------------------------------


def test_phase16_pdf_uses_get_running_loop() -> None:
    """HF-4 — asyncio.get_event_loop() is deprecated; use asyncio.get_running_loop().

    pdf_export_service.py calls `asyncio.get_event_loop().run_in_executor(...)`.
    `get_event_loop()` was deprecated in Python 3.10 and raises DeprecationWarning
    in Python 3.12+. In contexts where no loop is running, it creates a new loop
    (incorrect behaviour). `asyncio.get_running_loop()` is the correct API — it
    raises RuntimeError if called outside a running event loop, making bugs explicit.
    """
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    assert "get_event_loop()" not in source, (
        "pdf_export_service.py must not call asyncio.get_event_loop(). "
        "This API was deprecated in Python 3.10 and raises DeprecationWarning "
        "in Python 3.12+. Replace with asyncio.get_running_loop(). HF-4 — T-201."
    )

    assert "get_running_loop()" in source or "get_running_loop" in source, (
        "pdf_export_service.py must use asyncio.get_running_loop() (not "
        "get_event_loop()) when dispatching WeasyPrint to the thread pool. "
        "HF-4 — T-201."
    )


def test_phase16_pdf_uses_dedicated_executor() -> None:
    """HF-4 — PDF export should use a dedicated ThreadPoolExecutor.

    Sharing the default executor (None) with Langfuse's get_prompt() and other
    I/O-heavy tasks creates thread pool contention. A dedicated executor with a
    bounded worker count ensures PDF rendering does not starve other operations.
    """
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    has_dedicated_executor = bool(
        re.search(r"ThreadPoolExecutor\s*\(", source)
        and re.search(r"_PDF_EXECUTOR\s*=|PDF_EXECUTOR\s*=|_executor\s*=", source, re.IGNORECASE)
    )
    assert has_dedicated_executor, (
        "pdf_export_service.py must define a module-level dedicated "
        "ThreadPoolExecutor (e.g. _PDF_EXECUTOR = ThreadPoolExecutor(max_workers=2)) "
        "and pass it to run_in_executor(executor, ...). Using None (default) shares "
        "the global executor with Langfuse and other thread-heavy operations, causing "
        "contention during high PDF load. HF-4 / LF-2 — T-201."
    )


# ---------------------------------------------------------------------------
# T-202 (HF-5): RateLimitMiddleware must not create its own Redis pool
# ---------------------------------------------------------------------------


def test_phase16_rate_limit_no_redis_from_url() -> None:
    """HF-5 — RateLimitMiddleware must not call Redis.from_url() in production.

    The middleware constructor creates its own Redis connection pool when
    `redis_client=None` (the production path). This bypasses the shared pooled
    client maintained by the FastAPI lifespan, creating a second pool under load.

    The middleware must retrieve Redis lazily from `request.app.state.redis`
    in each call, not at construction time.
    """
    source = read_backend_file("middleware", "rate_limit.py")

    # The Redis.from_url() fallback in __init__ must be removed
    has_fallback = bool(
        re.search(r"redis_client\s+or\s+Redis\.from_url", source)
        or re.search(r"Redis\.from_url.*redis_url", source)
    )
    assert not has_fallback, (
        "middleware/rate_limit.py must not call Redis.from_url() as a fallback "
        "when redis_client=None. This creates a second, unpooled Redis connection "
        "pool in production. The middleware must lazily retrieve the shared Redis "
        "client from request.app.state.redis inside the __call__ method. "
        "HF-5 — T-202."
    )


def test_phase16_rate_limit_uses_app_state_redis() -> None:
    """HF-5 — RateLimitMiddleware must use request.app.state.redis for Redis access."""
    source = read_backend_file("middleware", "rate_limit.py")

    has_app_state = (
        "request.app.state.redis" in source
        or "app.state.redis" in source
    )
    assert has_app_state, (
        "middleware/rate_limit.py must access Redis via request.app.state.redis "
        "inside __call__(). This ensures all middleware uses the shared pooled "
        "client created during FastAPI lifespan startup. HF-5 — T-202."
    )


# ---------------------------------------------------------------------------
# T-203 (HF-6): CSRF nonce must be tracked in Redis (replay window closed)
# ---------------------------------------------------------------------------


def test_phase16_csrf_verify_accepts_redis_param() -> None:
    """HF-6 — verify_csrf_token() must accept a Redis client parameter.

    The current implementation validates the HMAC and timestamp but never records
    used nonces — the same token can be replayed for up to 1 hour (the token TTL).
    A CSRF token with a nonce provides no replay protection unless the nonce is
    stored after first use and rejected on repeat use.

    `verify_csrf_token()` must accept a `redis` parameter so it can perform
    an atomic SETNX to record and detect nonce reuse.
    """
    # Find csrf.py — may be in services/security/ or middleware/
    csrf_candidates = [
        BACKEND_ROOT / "services" / "security" / "csrf.py",
        BACKEND_ROOT / "services" / "security" / "csrf_service.py",
        BACKEND_ROOT / "middleware" / "csrf.py",
    ]
    csrf_file = None
    for candidate in csrf_candidates:
        if candidate.exists():
            csrf_file = candidate
            break

    assert csrf_file is not None, (
        "A CSRF module must exist in services/security/csrf.py or middleware/csrf.py. "
        "HF-6 — T-203."
    )

    source = csrf_file.read_text(encoding="utf-8")

    # verify_csrf_token must accept a redis parameter
    verify_fn = re.search(
        r"def verify_csrf_token\s*\(([^)]*)\)",
        source,
    )
    assert verify_fn, (
        "CSRF module must define verify_csrf_token(). HF-6 — T-203."
    )

    params = verify_fn.group(1)
    assert "redis" in params.lower() or "Redis" in params, (
        "verify_csrf_token() must accept a redis: Redis parameter so it can "
        "perform atomic nonce tracking. Current signature does not accept Redis "
        "— nonces cannot be stored and replay attacks remain possible for the "
        "full 1-hour token TTL. HF-6 — T-203."
    )


def test_phase16_csrf_verify_uses_setnx_for_nonce() -> None:
    """HF-6 — verify_csrf_token() must use Redis SETNX to atomically claim a nonce.

    SETNX (SET if Not eXists) atomically stores the nonce with the token's
    remaining TTL. A second call with the same nonce finds the key already set
    and rejects the replay. This closes the 1-hour window where a stolen token
    could be reused by an attacker.
    """
    csrf_candidates = [
        BACKEND_ROOT / "services" / "security" / "csrf.py",
        BACKEND_ROOT / "services" / "security" / "csrf_service.py",
        BACKEND_ROOT / "middleware" / "csrf.py",
    ]
    source = ""
    for candidate in csrf_candidates:
        if candidate.exists():
            source = candidate.read_text(encoding="utf-8")
            break

    has_setnx = bool(
        "setnx" in source.lower()
        or re.search(r"\.set\s*\([^)]*nx\s*=\s*True", source)
        or "set_if_not_exists" in source.lower()
    )
    assert has_setnx, (
        "verify_csrf_token() must use Redis SETNX (or SET NX=True) to atomically "
        "mark a nonce as used. Without this, the same CSRF token with a valid "
        "HMAC and timestamp can be replayed by an attacker for up to 1 hour. "
        "HF-6 — T-203."
    )


# ---------------------------------------------------------------------------
# T-204 (HF-7): CI must have real database and Redis service containers
# ---------------------------------------------------------------------------


def test_phase16_ci_has_postgres_service() -> None:
    """HF-7 — CI YAML must start a real PostgreSQL service container.

    The ci.yml sets DATABASE_URL and REDIS_URL environment variables but no
    `services:` block starts actual database/Redis containers. All tests run
    against mocks. This means:
    - Migration regressions (like the 0003→0005 incident) go undetected
    - SELECT FOR UPDATE behaviour cannot be validated
    - Deadlock detection requires a real DB

    A postgres: service container must be present in ci.yml.
    """
    ci_file = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), ".github/workflows/ci.yml must exist. HF-7 — T-204."

    content = ci_file.read_text(encoding="utf-8")

    has_postgres_service = bool(
        re.search(r"services\s*:", content)
        and re.search(r"postgres\s*:", content)
    )
    assert has_postgres_service, (
        ".github/workflows/ci.yml must include a `services: postgres:` container "
        "block so tests can run against a real PostgreSQL instance. The current CI "
        "sets DATABASE_URL but starts no actual database, creating a coverage "
        "illusion for migration and integration tests. HF-7 — T-204."
    )


def test_phase16_ci_runs_alembic_upgrade() -> None:
    """HF-7 — CI must run `alembic upgrade head` before pytest.

    Without this step, migration regression failures (wrong column types,
    missing indexes, constraint violations) are not caught in CI. The 0003→0005
    incident would have been caught if CI applied migrations against a real DB.
    """
    ci_file = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), ".github/workflows/ci.yml must exist. HF-7 — T-204."

    content = ci_file.read_text(encoding="utf-8")

    has_alembic = "alembic upgrade head" in content or "alembic upgrade" in content
    assert has_alembic, (
        ".github/workflows/ci.yml must run `alembic upgrade head` (or equivalent) "
        "before pytest so that migration regressions — wrong column types, missing "
        "indexes, constraint violations — are caught automatically. HF-7 — T-204."
    )


def test_phase16_ci_has_redis_service() -> None:
    """HF-7 — CI must also start a real Redis service container."""
    ci_file = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), ".github/workflows/ci.yml must exist. HF-7 — T-204."

    content = ci_file.read_text(encoding="utf-8")

    has_redis_service = bool(
        re.search(r"redis\s*:", content)
        and re.search(r"services\s*:", content)
    )
    assert has_redis_service, (
        ".github/workflows/ci.yml must include a `services: redis:` container "
        "so OAuth state, rate limiting, and credit cache integration tests run "
        "against real Redis. HF-7 — T-204."
    )


# ---------------------------------------------------------------------------
# T-205 (MF-1): asyncio.shield() eval orphan tasks must be cancelled on timeout
# ---------------------------------------------------------------------------


def test_phase16_eval_orphan_tasks_are_cancelled() -> None:
    """MF-1 — background eval tasks must never be orphaned/leaked.

    Original failure mode (T-205): stage_manager.py wrapped eval tasks in
    asyncio.shield() with a 30-second timeout; when the timeout fired the
    shielded task detached and ran indefinitely with no reference held, so under
    load orphaned eval tasks accumulated open connections and thread-pool slots.

    Issue #27 Phase 1 made LLM scoring strictly fire-and-forget and *removed* the
    shield()+timeout-that-abandons pattern entirely. The leak is now prevented by
    the canonical asyncio idiom instead: each eval task is created, a strong
    reference is retained in a module-level set (so it cannot be garbage-collected
    mid-flight), and a done-callback discards it on completion. Bounded runtime is
    enforced at the source by run_eval_background's own asyncio.wait_for timeout,
    which cancels the inner work on expiry. This is strictly safer than the old
    approach.

    The invariant this guards is unchanged — *no orphaned eval tasks* — so the
    contract accepts either the legacy shield()+explicit-cancel pattern OR the
    issue-#27 retained-reference + done-callback-discard pattern. It still fails
    on a bare, untracked ``asyncio.create_task`` with no leak protection.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    # Legacy pattern: explicit cancel in the shield() timeout handler.
    shield_region = ""
    shield_match = re.search(r"asyncio\.shield\s*\(", source)
    if shield_match:
        start = max(0, shield_match.start() - 500)
        end = min(len(source), shield_match.start() + 2000)
        shield_region = source[start:end]
    has_cancel_on_timeout = bool(
        re.search(r"TimeoutError.*\.cancel\(\)", shield_region, re.DOTALL)
        or re.search(r"\.cancel\(\).*TimeoutError", shield_region, re.DOTALL)
        or re.search(r"except.*Timeout.*\n.*cancel", shield_region)
        or (
            re.search(r"eval_task\s*=\s*asyncio\.create_task", source)
            and re.search(r"eval_task\.cancel\(\)", source)
        )
    )

    # Issue-#27 pattern: the created task is retained in a module-level set and
    # discarded via a done-callback — the documented way to keep a fire-and-forget
    # task from being GC'd mid-flight (no orphan, no unbounded set growth).
    eval_task_created = re.search(r"eval_task\s*=\s*asyncio\.create_task", source)
    retained_in_set = re.search(r"_BACKGROUND_EVAL_TASKS\.add\(\s*eval_task\s*\)", source)
    discarded_on_done = re.search(
        r"add_done_callback\(\s*_BACKGROUND_EVAL_TASKS\.discard\s*\)", source
    )
    has_tracked_fire_and_forget = bool(
        eval_task_created and retained_in_set and discarded_on_done
    )

    assert has_cancel_on_timeout or has_tracked_fire_and_forget, (
        "stage_manager.py must protect background eval tasks from orphaning — "
        "either by cancelling the shielded task in the TimeoutError handler "
        "(legacy) or by retaining the created task in _BACKGROUND_EVAL_TASKS and "
        "discarding it via add_done_callback (issue #27 fire-and-forget). Without "
        "one of these, an untracked task can be GC'd mid-flight or leak open "
        "connections and thread-pool slots under load. MF-1 — T-205."
    )


# ---------------------------------------------------------------------------
# T-206 (MF-2): _derive_coverage_summary must be in a shared utility module
# ---------------------------------------------------------------------------


def test_phase16_coverage_utils_module_exists() -> None:
    """MF-2 — _derive_coverage_summary must live in a shared utility module.

    pdf_export_service.py imports `_derive_coverage_summary` from
    `public_share_service.py` (a private function from a different service module).
    This cross-module private import creates a hidden coupling: any refactor of
    public_share_service.py breaks PDF export silently.

    The function must be moved to a shared module (e.g. services/coverage_utils.py)
    that both public_share_service.py and pdf_export_service.py import from.
    """
    # The shared utility module must exist
    coverage_utils = BACKEND_ROOT / "services" / "coverage_utils.py"
    assert coverage_utils.exists(), (
        "backend/services/coverage_utils.py must exist and define "
        "_derive_coverage_summary (or derive_coverage_summary) as the canonical "
        "location for coverage derivation logic. Both pdf_export_service.py and "
        "public_share_service.py must import from here. MF-2 — T-206."
    )

    content = coverage_utils.read_text(encoding="utf-8")
    assert "coverage_summary" in content.lower() or "derive_coverage" in content.lower(), (
        "backend/services/coverage_utils.py must define the coverage derivation "
        "function. MF-2 — T-206."
    )


def test_phase16_pdf_does_not_import_from_public_share() -> None:
    """MF-2 — pdf_export_service.py must not import private functions from public_share_service.

    Cross-module private imports create hidden coupling and fragile refactor surfaces.
    """
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    has_cross_import = bool(
        re.search(r"from\s+.*public_share_service\s+import\s+_", source)
        or re.search(r"import\s+public_share_service.*_derive", source)
    )
    assert not has_cross_import, (
        "pdf_export_service.py must not import private functions (prefixed with _) "
        "from public_share_service.py. Move the shared function to "
        "services/coverage_utils.py and import from there. MF-2 — T-206."
    )


# ---------------------------------------------------------------------------
# T-207 (MF-3): refund() must use savepoint (begin_nested) not db.rollback()
# ---------------------------------------------------------------------------


def test_phase16_refund_uses_savepoint_not_rollback() -> None:
    """MF-3 — refund() must use db.begin_nested() savepoint on IntegrityError.

    credit_service.py calls `await db.rollback()` in the IntegrityError handler
    inside refund(). This rolls back the entire outer transaction — any stage
    status update, content save, or telemetry write that was part of the same
    session is also rolled back silently.

    The fix: use `async with db.begin_nested(): await db.flush()` as a savepoint.
    An IntegrityError inside the savepoint rolls back only that savepoint, leaving
    the outer transaction intact.
    """
    source = read_backend_file("services", "credit_service.py")

    # Find the refund function body
    fn_match = re.search(
        r"(async\s+def\s+refund\s*\([^)]*\)[^:]*:)(.*?)(?=\n\s{0,4}(?:async\s+)?def\s+\w|\Z)",
        source,
        re.DOTALL,
    )

    if fn_match:
        refund_body = fn_match.group(2)

        # rollback() in the refund body is the bug
        has_bare_rollback = bool(
            re.search(r"await\s+db\.rollback\(\)", refund_body)
            and "begin_nested" not in refund_body
        )
        assert not has_bare_rollback, (
            "credit_service.py refund() must not call db.rollback() on "
            "IntegrityError — this rolls back the entire outer transaction. "
            "Use `async with db.begin_nested(): await db.flush()` to isolate "
            "the IntegrityError in a savepoint. MF-3 — T-207."
        )

        # Must use savepoint
        assert "begin_nested" in refund_body or "savepoint" in refund_body.lower(), (
            "credit_service.py refund() must use db.begin_nested() (SQLAlchemy "
            "savepoint) to safely handle IntegrityError without touching the outer "
            "transaction. MF-3 — T-207."
        )


# ---------------------------------------------------------------------------
# T-208 (MF-4): TemplatesStrip must be wrapped in an error boundary
# ---------------------------------------------------------------------------


def test_phase16_templates_strip_has_error_boundary() -> None:
    """MF-4 — TemplatesStrip must be wrapped in an error boundary in Dashboard.tsx.

    An unhandled exception inside TemplatesStrip (e.g. malformed template data
    from the API) propagates up and crashes the entire Dashboard, logging the
    user out of their work session. An error boundary must contain the failure
    to a recoverable in-place error state.
    """
    dashboard_path = REPO_ROOT / "frontend" / "src" / "pages" / "Dashboard.tsx"
    assert dashboard_path.exists(), "frontend/src/pages/Dashboard.tsx must exist. MF-4 — T-208."

    content = dashboard_path.read_text(encoding="utf-8")

    # Both usages of TemplatesStrip must appear inside an error boundary tag
    # Look for ErrorBoundary or similar wrapping TemplatesStrip
    has_error_boundary = bool(
        re.search(r"ErrorBoundary[^>]*>.*?TemplatesStrip", content, re.DOTALL)
        or (
            "TemplatesStrip" in content
            and (
                "ErrorBoundary" in content
                or "error-boundary" in content
                or "RendererErrorBoundary" in content
            )
        )
    )
    assert has_error_boundary, (
        "frontend/src/pages/Dashboard.tsx must wrap <TemplatesStrip> in an error "
        "boundary component. An unhandled error inside TemplatesStrip currently "
        "crashes the entire Dashboard page. Wrap with a component that catches "
        "the error and shows an inline fallback. MF-4 — T-208."
    )

    # A generic error boundary component must exist (Dashboard should not inline it)
    error_boundary_candidates = [
        REPO_ROOT / "frontend" / "src" / "components" / "ErrorBoundary.tsx",
        REPO_ROOT / "frontend" / "src" / "components" / "ui" / "ErrorBoundary.tsx",
        REPO_ROOT / "frontend" / "src" / "components" / "common" / "ErrorBoundary.tsx",
    ]
    found_component = any(p.exists() for p in error_boundary_candidates)
    assert found_component, (
        "A reusable ErrorBoundary React component must exist in "
        "frontend/src/components/. Dashboard.tsx and other consumers should "
        "import it rather than each defining their own. MF-4 — T-208."
    )


# ---------------------------------------------------------------------------
# T-209 (MF-5): Langfuse Docker image must be pinned (not :latest)
# ---------------------------------------------------------------------------


def test_phase16_langfuse_image_not_latest() -> None:
    """MF-5 — langfuse/langfuse image must be pinned to a specific version.

    A floating :latest tag means any new Langfuse release is pulled automatically
    on the next `docker compose pull`. A breaking change in Langfuse can take
    down production without any code change in this repo.

    The image must be pinned to a specific semver tag or SHA digest.
    """
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist at repository root."

    content = compose_file.read_text(encoding="utf-8")

    if "langfuse" not in content:
        return  # Langfuse not present in compose — skip

    # :latest is the forbidden pattern
    has_latest = bool(re.search(r"langfuse/langfuse\s*:\s*latest", content))
    assert not has_latest, (
        "docker-compose.yml must not use langfuse/langfuse:latest. Pin to a "
        "specific semver tag (e.g. langfuse/langfuse:2.84.0) or SHA digest "
        "(langfuse/langfuse@sha256:...) to prevent silent breaking changes during "
        "`docker compose pull`. MF-5 — T-209."
    )

    # Confirm a version is pinned
    has_pinned_version = bool(
        re.search(r"langfuse/langfuse\s*:\s*\d+\.\d+", content)
        or re.search(r"langfuse/langfuse@sha256:", content)
    )
    assert has_pinned_version, (
        "docker-compose.yml langfuse image must include a specific version tag "
        "(e.g. :2.84.0) or SHA digest. MF-5 — T-209."
    )


# ---------------------------------------------------------------------------
# T-210 (LF-1): Auth cache multi-worker incoherence must be documented
# ---------------------------------------------------------------------------


def test_phase16_auth_cache_limitation_documented() -> None:
    """LF-1 — _USER_CACHE multi-worker incoherence must be documented.

    `invalidate_user_cache()` only clears the in-process `_USER_CACHE` dict in
    the worker that handles the invalidation request. In a multi-worker deployment
    (uvicorn --workers=4, Railway horizontal scaling), other workers continue
    serving stale credit_balance values from their own caches for up to 30 seconds.

    This is a known architectural limitation. It must be:
    1. Documented in the source code with a clear comment explaining the limitation
    2. Documented in an architecture decision record or RUNBOOK.md
    """
    source = read_backend_file("middleware", "auth.py")

    # The source must have a comment about multi-worker cache limitations
    has_limitation_comment = bool(
        re.search(r"#.*multi.?worker", source, re.IGNORECASE)
        or re.search(r"#.*per.?process", source, re.IGNORECASE)
        or re.search(r"#.*single.?worker", source, re.IGNORECASE)
        or re.search(r"#.*worker.*(cache|stale)", source, re.IGNORECASE)
        or "NOTE:" in source and "worker" in source.lower()
    )
    assert has_limitation_comment, (
        "middleware/auth.py must document the multi-worker cache incoherence "
        "limitation. _USER_CACHE is in-process — invalidate_user_cache() only "
        "clears the cache in one worker. In multi-worker deployments, other workers "
        "continue serving stale credit_balance values. Add a comment: "
        "'# NOTE: _USER_CACHE is per-process — in multi-worker deployments, "
        "other workers may serve stale credit_balance for up to CACHE_TTL seconds.'"
        " LF-1 — T-210."
    )


def test_phase16_auth_cache_runbook_entry_exists() -> None:
    """LF-1 — RUNBOOK.md must document the multi-worker cache limitation and workaround."""
    runbook = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook.exists(), (
        "docs/RUNBOOK.md must exist. It must document operational procedures "
        "for the auth cache multi-worker limitation and circuit breaker. "
        "LF-1 / T-210 / T-216."
    )

    content = runbook.read_text(encoding="utf-8")
    assert "USER_CACHE" in content or "multi-worker" in content.lower() or "credit_balance" in content, (
        "docs/RUNBOOK.md must document the _USER_CACHE multi-worker incoherence: "
        "what it means in practice, how to detect stale credit readings, and the "
        "recommendation to migrate to Redis-backed user cache for multi-worker "
        "deployments. LF-1 — T-210."
    )


# ---------------------------------------------------------------------------
# T-211 (LF-2): PDF export must use a dedicated thread pool (not shared)
# ---------------------------------------------------------------------------


def test_phase16_pdf_dedicated_executor_not_shared() -> None:
    """LF-2 — PDF exports must not share the default thread pool with Langfuse.

    Langfuse's `get_prompt()` is called from `run_in_executor(None, ...)` which
    uses the default ThreadPoolExecutor. PDF rendering via WeasyPrint is CPU-bound
    and slow. Under concurrent load, PDF jobs monopolise the default executor
    threads, starving Langfuse prompt fetches and any other I/O-offloaded work.

    A dedicated _PDF_EXECUTOR must be used. This is also checked by T-201 (HF-4)
    but from the thread-contention angle.
    """
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    # Must not use run_in_executor(None, ...) for PDF rendering
    has_shared_pool = bool(
        re.search(r"run_in_executor\s*\(\s*None\s*,", source)
    )
    assert not has_shared_pool, (
        "pdf_export_service.py must not call run_in_executor(None, ...). "
        "None uses the default (shared) ThreadPoolExecutor, which PDF rendering "
        "shares with Langfuse get_prompt() and other I/O-offloaded work. "
        "Define and pass a dedicated _PDF_EXECUTOR. LF-2 — T-211."
    )


# ---------------------------------------------------------------------------
# T-213 (LF-4): eval_results composite index migration must exist
# ---------------------------------------------------------------------------


def test_phase16_eval_results_composite_index_migration_exists() -> None:
    """LF-4 — A migration adding composite index on eval_results(stage_version_id, created_at DESC) must exist.

    The eval polling query filters by stage_version_id and orders by created_at DESC
    to find the latest eval result. Without a composite index, PostgreSQL performs
    a sequential scan on what could be millions of eval rows at scale.

    A migration (0012_eval_results_composite_index.py or later) must exist and
    contain the CREATE INDEX statement.
    """
    migrations_dir = BACKEND_ROOT / "migrations" / "versions"
    assert migrations_dir.exists(), (
        "backend/migrations/versions/ must exist. LF-4 — T-213."
    )

    migration_files = list(migrations_dir.glob("*.py"))
    assert migration_files, (
        "backend/migrations/versions/ must contain migration files. LF-4 — T-213."
    )

    found_index = False
    for mf in migration_files:
        content = mf.read_text(encoding="utf-8")
        if (
            "eval_results" in content
            and "stage_version_id" in content
            and (
                "created_at" in content
                or "index" in content.lower()
            )
            and "create_index" in content.lower()
        ):
            found_index = True
            break

    assert found_index, (
        "backend/migrations/versions/ must contain a migration that creates a "
        "composite index on eval_results(stage_version_id, created_at DESC). "
        "The eval polling query is a hot path — without this index it performs "
        "a sequential scan. LF-4 — T-213."
    )


# ---------------------------------------------------------------------------
# T-216: RUNBOOK.md must cover CF-1 and CF-2 operational procedures
# ---------------------------------------------------------------------------


def test_phase16_runbook_covers_circuit_breaker_procedure() -> None:
    """T-216 — RUNBOOK.md must document CF-2 circuit breaker operational procedures.

    Operators need to know:
    - How to detect when the circuit breaker has opened (metric + log)
    - How to manually reset a provider's failure count
    - What the expected SLA impact is when a provider circuit opens
    - How to enable/disable the circuit for a specific provider
    """
    runbook = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook.exists(), (
        "docs/RUNBOOK.md must exist with circuit breaker and finalise race "
        "operational procedures. T-216."
    )

    content = runbook.read_text(encoding="utf-8")

    has_circuit_breaker_section = (
        "circuit breaker" in content.lower()
        or "circuit_breaker" in content.lower()
        or "can_route" in content
        or "specforge_llm_circuit_rejections_total" in content
    )
    assert has_circuit_breaker_section, (
        "docs/RUNBOOK.md must document the LLM circuit breaker: how to detect "
        "activation (specforge_llm_circuit_rejections_total metric), how to "
        "reset a provider's failure count, and the expected user impact when the "
        "circuit opens. T-216."
    )


def test_phase16_runbook_covers_finalise_race_procedure() -> None:
    """T-216 — RUNBOOK.md must document CF-1 finalise race operational procedures.

    Operators need to know:
    - How to detect a double-finalise incident (symptoms in logs/metrics)
    - The rollback procedure for a double-charged user
    - The SELECT FOR UPDATE guarantee and its PostgreSQL prerequisites
    """
    runbook = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook.exists(), (
        "docs/RUNBOOK.md must exist. T-216."
    )

    content = runbook.read_text(encoding="utf-8")

    has_finalise_section = (
        "finalise" in content.lower()
        or "SELECT FOR UPDATE" in content
        or "double-finalise" in content.lower()
        or "double finalise" in content.lower()
    )
    assert has_finalise_section, (
        "docs/RUNBOOK.md must document the CF-1 finalise race: how to detect a "
        "double-finalise incident in logs/metrics, how to reverse a double-charge, "
        "and confirmation that SELECT FOR UPDATE requires READ COMMITTED or higher "
        "isolation level (PostgreSQL default). T-216."
    )


def test_phase16_runbook_has_required_sections() -> None:
    """T-216 — RUNBOOK.md must have well-structured sections for operational use."""
    runbook = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook.exists(), "docs/RUNBOOK.md must exist. T-216."

    content = runbook.read_text(encoding="utf-8")

    required_section_keywords = [
        "circuit",     # circuit breaker section
        "finalise",    # or "finalize" — the race condition section
        "credit",      # credit / refund procedures
        "cache",       # auth cache multi-worker limitation
    ]

    missing = [kw for kw in required_section_keywords if kw not in content.lower()]
    assert not missing, (
        f"docs/RUNBOOK.md is missing sections covering: {', '.join(missing)}. "
        "The runbook must address: circuit breaker operations, finalise race "
        "incident response, credit refund procedures, and auth cache "
        "multi-worker limitations. T-216."
    )


# ---------------------------------------------------------------------------
# T-215: LLM circuit breaker metrics — counter increment verification
# ---------------------------------------------------------------------------


def test_phase16_circuit_rejection_counter_incremented_on_rejection() -> None:
    """T-215 — specforge_llm_circuit_rejections_total must be incremented by can_route().

    Defining the counter is insufficient — it must be incremented at the point
    where can_route() returns False and the request is rejected. This ensures
    the metric reflects actual circuit activations, not just initialization.
    """
    provider_status_path = BACKEND_ROOT / "services" / "llm" / "provider_status.py"
    gateway_path = BACKEND_ROOT / "services" / "llm" / "gateway.py"

    combined_source = ""
    for p in (provider_status_path, gateway_path):
        if p.exists():
            combined_source += p.read_text(encoding="utf-8")

    # The counter must be incremented (not just defined)
    has_increment = bool(
        re.search(r"specforge_llm_circuit_rejections_total.*\.inc\(\)", combined_source, re.DOTALL)
        or re.search(r"\.inc\(\).*specforge_llm_circuit_rejections_total", combined_source, re.DOTALL)
        or re.search(r"circuit_rejections.*\.inc\(\)", combined_source)
        or re.search(r"CIRCUIT_REJECTIONS.*\.inc\(\)", combined_source)
    )
    assert has_increment, (
        "specforge_llm_circuit_rejections_total.inc() must be called in "
        "provider_status.py (inside can_route()) or gateway.py (when can_route() "
        "returns False). The counter must be incremented at the rejection site, "
        "not just defined. T-215."
    )


# ---------------------------------------------------------------------------
# Integrity: all Phase 16 task IDs are referenced in at least one test
# ---------------------------------------------------------------------------


def test_phase16_all_task_ids_referenced() -> None:
    """Meta-test: every T-196 through T-216 task must appear in this file.

    If a task ID is not referenced in any test, it has no harness contract and
    cannot be verified green. This test ensures all 21 tasks are tracked.
    """
    this_file = Path(__file__).read_text(encoding="utf-8")

    missing = []
    for n in range(196, 217):  # T-196 through T-216 inclusive
        task_id = f"T-{n}"
        if task_id not in this_file:
            missing.append(task_id)

    assert not missing, (
        f"The following Phase 16 task IDs have no harness test referencing them: "
        + ", ".join(missing)
        + ". Every task must be validated by at least one test in this file."
    )
