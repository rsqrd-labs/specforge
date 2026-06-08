"""
Harness contracts for Phase 17 — Final Hardening & Enterprise Closure.

These tests are RED before T-217 through T-225 are implemented and GREEN after.

Every test maps to one or more findings from the third-pass enterprise code review
(2026-05-25):

  C-1   generate() stream timeouts never call record_provider_failure
        → T-217 — record_provider_failure() added to generate()'s except block

  H-1   Tasks stage user prompt regression — "For each plan section or contract"
        missing from build_user_prompt() output
        → T-218 — instruction restored in tasks.build_user_prompt()

  H-2   credit_service._invalidate() called after db.flush() but before
        db.commit() — concurrent get_balance() can re-populate Redis with stale
        pre-deduction balance
        → T-219 — public invalidate() method + post-commit calls in stage_manager

  H-3   RateLimitMiddleware bypasses ALL rate limiting (not just Redis) when
        app.state.redis is None during the startup window
        → T-225 — fallback to _local_fallback_check instead of call_next()

  M-2   No specforge_llm_circuit_state Gauge — operators cannot tell whether a
        provider circuit is currently open from dashboards
        → T-220 — Gauge added; updated in record_provider_failure/success

  M-4   Langfuse SDK v2 vs server v3 compatibility — exception-swallowing masks
        protocol-level failures; no startup check exists
        → T-221 — startup_check() method + lifespan call

  L-1   _INSTANCES adapter cache in gateway.py has no TTL — stale adapters
        served indefinitely until LRU eviction
        → T-223 — _INSTANCE_CACHE_TTL_SECONDS constant + tuple storage

  L-4   sliding_window_check() in stage_manager has no RedisError fallback —
        Redis failure propagates as internal_error SSE event
        → T-222 — try/except RedisError around sliding_window_check calls

  Ops   ENCRYPTION_MASTER_KEY, CSRF_SECRET, JWT rotation procedures absent
        from RUNBOOK.md
        → T-224 — RUNBOOK §8 Secret Rotation Procedures

Design invariants enforced here:
  * generate()'s inner except (ProviderError, TimeoutError) calls record_provider_failure.
  * tasks.build_user_prompt() output contains "For each plan section or contract".
  * credit_service.CreditService has a public invalidate() method.
  * stage_manager.py calls credit_service.invalidate after db.commit().
  * RateLimitMiddleware does NOT have a bare return call_next in the redis is None branch.
  * specforge_llm_circuit_state Gauge is defined and updated on failure + success.
  * LangfuseClient has a startup_check() method.
  * gateway._INSTANCE_CACHE_TTL_SECONDS constant exists; _INSTANCES stores tuples.
  * sliding_window_check calls in stage_manager are wrapped in RedisError handler.
  * RUNBOOK.md §8 covers ENCRYPTION_MASTER_KEY, CSRF_SECRET, JWT rotation.
"""

from __future__ import annotations

import re

from conftest import REPO_ROOT, read_backend_file


# ---------------------------------------------------------------------------
# T-217 (C-1): generate()'s except block MUST call record_provider_failure
# ---------------------------------------------------------------------------


def test_phase17_generate_except_block_calls_record_provider_failure() -> None:
    """C-1 — generate() stream timeouts must update the circuit breaker.

    asyncio.timeout() fires via CancelledError (BaseException), which bypasses
    InstrumentedAdapter.stream()'s `except Exception` block.  The outer
    `except (ProviderError, TimeoutError)` in generate() is the only place
    that can call record_provider_failure() for the timeout path.  Without it,
    three consecutive stream timeouts never trip the circuit breaker.

    This test verifies that the generate() except block now calls
    record_provider_failure(), mirroring the pattern already in refine() and
    generate_harness_patch() at lines 1324–1328.  C-1 — T-217.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert "async def generate" in source or "def generate" in source, (
        "stage_manager.py must define a generate() function.  C-1 — T-217."
    )

    # Extract only the body of generate() to avoid false positives from other
    # methods (refine, generate_harness_patch) that already call record_provider_failure.
    fn_match = re.search(
        r"(async\s+def\s+generate\s*\([^)]*\)[^:]*:)(.*?)(?=\n\s{0,4}(?:async\s+)?def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, (
        "Could not extract generate() body from stage_manager.py.  C-1 — T-217."
    )
    generate_body = fn_match.group(2)

    assert "record_provider_failure" in generate_body, (
        "generate() must call record_provider_failure() in its "
        "except (ProviderError, TimeoutError) block.  asyncio.timeout() fires "
        "via CancelledError which bypasses InstrumentedAdapter.stream()'s "
        "except Exception guard, so record_provider_failure is NEVER called on "
        "stream timeouts unless explicitly added here.  Without this call, "
        "three consecutive stream timeouts will never trip the circuit breaker "
        "and users will experience indefinite 360-second timeouts per request "
        "on a hung provider.  C-1 — T-217."
    )


def test_phase17_generate_except_block_references_circuit_task() -> None:
    """C-1 — The record_provider_failure call in generate() must reference T-217.

    Convention: every significant call site references its task ID in a comment.
    This ensures future developers understand why record_provider_failure is
    called here and can trace it back to the finding.  C-1 — T-217.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    fn_match = re.search(
        r"(async\s+def\s+generate\s*\([^)]*\)[^:]*:)(.*?)(?=\n\s{0,4}(?:async\s+)?def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, "Could not extract generate() body.  C-1 — T-217."
    generate_body = fn_match.group(2)

    # Must contain the task reference in the generate() body near the call.
    assert "T-217" in generate_body, (
        "generate()'s record_provider_failure call must include a T-217 comment "
        "for traceability.  C-1 — T-217."
    )


def test_phase17_generate_except_block_guards_against_double_counting() -> None:
    """C-1 — generate()'s record_provider_failure call MUST be inside a
    `if isinstance(exc, TimeoutError)` guard — NOT unconditional.

    Background on the double-counting bug this test prevents:
    InstrumentedAdapter.stream() already calls record_provider_failure() in its
    `except Exception` block for non-timeout ProviderErrors (e.g., HTTP 401).
    If generate()'s except (ProviderError, TimeoutError) block also calls
    record_provider_failure() unconditionally, a non-timeout ProviderError is
    recorded TWICE — once in InstrumentedAdapter, once in generate().  This trips
    the circuit after 2 failures instead of the documented 3.

    The isinstance(exc, TimeoutError) guard is the correct fix:
    - For TimeoutError: InstrumentedAdapter.stream()'s `except Exception` was bypassed
      by CancelledError (a BaseException), so record_provider_failure was NOT called.
      The guard allows the call to happen here — exactly once.
    - For ProviderError: InstrumentedAdapter.stream()'s `except Exception` already
      called record_provider_failure.  The guard prevents the second call — no double-count.

    C-1 — T-217.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    fn_match = re.search(
        r"(async\s+def\s+generate\s*\([^)]*\)[^:]*:)(.*?)(?=\n\s{0,4}(?:async\s+)?def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, (
        "Could not extract generate() body from stage_manager.py.  C-1 — T-217."
    )
    generate_body = fn_match.group(2)

    # The record_provider_failure call must be conditional on isinstance(exc, TimeoutError).
    # This prevents double-counting: InstrumentedAdapter.stream() already handles
    # non-timeout ProviderErrors in its except Exception block.
    has_isinstance_guard = re.search(
        r"if\s+isinstance\s*\(\s*exc\s*,\s*TimeoutError\s*\)[^:]*:.*?record_provider_failure",
        generate_body,
        re.DOTALL,
    )
    assert has_isinstance_guard, (
        "generate()'s record_provider_failure call must be inside an "
        "`if isinstance(exc, TimeoutError):` guard.  An unconditional call would "
        "double-count non-timeout ProviderErrors (already recorded by "
        "InstrumentedAdapter.stream()'s except Exception block), tripping the "
        "circuit after 2 failures instead of the documented 3.  "
        "The correct pattern is:\n"
        "    if isinstance(exc, TimeoutError):\n"
        "        record_provider_failure(route.provider, exc)\n"
        "C-1 — T-217."
    )


# ---------------------------------------------------------------------------
# T-218 (H-1): tasks.build_user_prompt() must contain traceability instruction
# ---------------------------------------------------------------------------


def test_phase17_tasks_build_user_prompt_contains_plan_section_instruction() -> None:
    """H-1 — tasks.build_user_prompt() must include plan-section coverage instruction.

    test_tasks_prompt_is_ordered_traceable_and_agent_executable in
    test_prompt_builder.py asserts that 'For each plan section or contract'
    appears in the user prompt returned by build_user_prompt().  This phrase
    guards a quality constraint: the LLM must trace plan-level contracts (not
    just spec requirements) to generated tasks.  The phrase was lost in a
    Phase 14 prompt rewrite without updating the test.

    This harness test enforces the same constraint at contract level so the
    gap cannot silently regress.  H-1 — T-218.
    """
    source = read_backend_file("prompts", "tasks.py")

    # The phrase must appear in build_user_prompt's return string — which means
    # it must be in the f-string body of build_user_prompt(), not just SYSTEM_PROMPT.
    fn_match = re.search(
        r"def\s+build_user_prompt\s*\([^)]*\)\s*->[^:]*:(.*?)(?=\ndef\s+|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, (
        "Could not extract build_user_prompt() from prompts/tasks.py.  H-1 — T-218."
    )
    fn_body = fn_match.group(1)

    assert "For each plan section or contract" in fn_body, (
        "tasks.build_user_prompt() must contain 'For each plan section or contract' "
        "in its returned string.  This instruction ensures the LLM traces plan-level "
        "architectural contracts — not just spec requirements — to generated tasks.  "
        "The phrase was lost in a Phase 14 rewrite and test_prompt_builder.py has "
        "been failing ever since.  Restore the instruction in build_user_prompt()'s "
        "step 0 coverage-map bullets.  H-1 — T-218."
    )


# ---------------------------------------------------------------------------
# T-219 (H-2): credit_service must have public invalidate(); stage_manager
#              must call it after db.commit()
# ---------------------------------------------------------------------------


def test_phase17_credit_service_has_public_invalidate_method() -> None:
    """H-2 — CreditService must expose a public invalidate() method.

    _invalidate() is called after db.flush() (within the transaction) — before
    the outer db.commit().  Between invalidation and commit, a concurrent
    get_balance() can read the uncommitted (pre-deduction) balance from
    PostgreSQL and re-populate Redis with a stale value.  The solution is a
    second, post-commit invalidation.  The public invalidate() method enables
    callers (stage_manager.py) to call it after db.commit().  H-2 — T-219.
    """
    source = read_backend_file("services", "credit_service.py")

    assert re.search(r"async\s+def\s+invalidate\s*\(\s*self\s*,\s*user_id", source), (
        "credit_service.CreditService must have a public `async def invalidate(self, user_id)` "
        "method.  This method is the post-commit cache eviction hook.  It must call "
        "self._invalidate(user_id).  callers in stage_manager.py call it after "
        "db.commit() to evict any stale Redis entries that were re-populated during "
        "the flush→commit window.  H-2 — T-219."
    )


def test_phase17_stage_manager_calls_invalidate_after_commit() -> None:
    """H-2 — stage_manager.py must call credit_service.invalidate() after db.commit().

    The post-commit invalidation pattern requires that every db.commit() which
    follows a credit write (deduct, credit, refund) is accompanied by a call to
    credit_service.invalidate().  This test verifies the call exists in
    stage_manager.py's generate() and/or refine() bodies.  H-2 — T-219.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert "credit_service.invalidate" in source, (
        "stage_manager.py must call credit_service.invalidate() after db.commit() "
        "in generate(), refine(), and any other method that calls deduct/credit/refund "
        "followed by db.commit().  Without this post-commit call, any concurrent "
        "get_balance() that re-populated Redis during the flush→commit window will "
        "show a stale (too-high) balance for up to 5 minutes.  H-2 — T-219."
    )

    # Verify T-219 is referenced in a comment near the call site.
    assert "T-219" in source, (
        "stage_manager.py must reference T-219 in a comment near the "
        "credit_service.invalidate() call for traceability.  H-2 — T-219."
    )


def test_phase17_credit_service_invalidate_references_finding() -> None:
    """H-2 — The public invalidate() docstring must reference H-2 and T-219."""
    source = read_backend_file("services", "credit_service.py")

    # Extract the public invalidate() method body
    fn_match = re.search(
        r"async\s+def\s+invalidate\s*\(\s*self[^)]*\)\s*->[^:]*:(.*?)(?=\n\s{0,4}async\s+def|\n\s{0,4}def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, (
        "public invalidate() method not found in credit_service.py.  H-2 — T-219."
    )
    method_body = fn_match.group(1)

    assert "T-219" in method_body or "H-2" in method_body, (
        "The public invalidate() method must reference T-219 (or H-2) in its "
        "docstring or comment for operational traceability.  H-2 — T-219."
    )


# ---------------------------------------------------------------------------
# T-220 (M-2): specforge_llm_circuit_state Gauge must be defined and updated
# ---------------------------------------------------------------------------


def test_phase17_circuit_state_gauge_defined() -> None:
    """M-2 — specforge_llm_circuit_state Gauge must be defined in provider_status.py.

    CIRCUIT_REJECTIONS (T-215) counts rejections but cannot tell operators
    whether a circuit is currently open.  The Gauge provides real-time
    open/closed status per provider for Grafana dashboards and alerting.
    M-2 — T-220.
    """
    source = read_backend_file("services", "llm", "provider_status.py")

    assert "specforge_llm_circuit_state" in source, (
        "provider_status.py must define a Gauge named "
        "'specforge_llm_circuit_state' for real-time circuit breaker state.  "
        "This allows operators to query `max by (provider) (specforge_llm_circuit_state) "
        "== 1` to detect open circuits without waiting for rejection counters.  "
        "M-2 — T-220."
    )

    assert "Gauge" in source, (
        "provider_status.py must import and use prometheus_client.Gauge for "
        "specforge_llm_circuit_state.  M-2 — T-220."
    )


def test_phase17_circuit_state_updated_on_failure_and_success() -> None:
    """M-2 — CIRCUIT_STATE.labels().set() must appear in both record_provider_failure
    and record_provider_success to keep the Gauge current.  M-2 — T-220.
    """
    source = read_backend_file("services", "llm", "provider_status.py")

    # Check record_provider_failure body contains CIRCUIT_STATE update.
    failure_match = re.search(
        r"def\s+record_provider_failure\s*\([^)]*\)(.*?)(?=\ndef\s+|\Z)",
        source,
        re.DOTALL,
    )
    assert failure_match, (
        "record_provider_failure() not found in provider_status.py.  M-2 — T-220."
    )
    assert "CIRCUIT_STATE" in failure_match.group(1), (
        "record_provider_failure() must update CIRCUIT_STATE Gauge.  M-2 — T-220."
    )

    # Check record_provider_success body contains CIRCUIT_STATE update.
    success_match = re.search(
        r"def\s+record_provider_success\s*\([^)]*\)(.*?)(?=\ndef\s+|\Z)",
        source,
        re.DOTALL,
    )
    assert success_match, (
        "record_provider_success() not found in provider_status.py.  M-2 — T-220."
    )
    assert "CIRCUIT_STATE" in success_match.group(1), (
        "record_provider_success() must update CIRCUIT_STATE Gauge to 0 (closed).  "
        "M-2 — T-220."
    )


def test_phase17_runbook_documents_circuit_state_gauge() -> None:
    """M-2 — RUNBOOK.md §1 must include specforge_llm_circuit_state PromQL.

    Operators need a documented query to create alerts on open circuits.
    M-2 — T-220.
    """
    runbook_path = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook_path.exists(), (
        "docs/RUNBOOK.md must exist.  Run T-216 first.  T-220."
    )
    content = runbook_path.read_text(encoding="utf-8")

    assert "specforge_llm_circuit_state" in content, (
        "RUNBOOK.md must document specforge_llm_circuit_state with a PromQL "
        "example.  Suggested: `max by (provider) (specforge_llm_circuit_state) == 1` "
        "to alert when any provider circuit is open.  M-2 — T-220."
    )


# ---------------------------------------------------------------------------
# T-221 (M-4): LangfuseClient must have startup_check() and lifespan must call it
# ---------------------------------------------------------------------------


def test_phase17_langfuse_client_has_startup_check_method() -> None:
    """M-4 — LangfuseClient must expose a startup_check() async method.

    The SDK's exception-swallowing design means protocol-level failures are
    logged silently as langfuse.create_trace.failed.  startup_check() calls
    auth_check() on lifespan start so version-skew or connectivity failures
    are detected immediately on deploy.  M-4 — T-221.
    """
    source = read_backend_file("services", "langfuse_service.py")

    assert re.search(r"async\s+def\s+startup_check\s*\(\s*self", source), (
        "LangfuseClient must have an `async def startup_check(self)` method that "
        "calls client.auth_check() (wrapped in asyncio.to_thread) and logs a "
        "WARNING if the check fails or times out.  The method must never raise.  "
        "M-4 — T-221."
    )


def test_phase17_langfuse_startup_check_uses_wait_for_timeout() -> None:
    """M-4 — startup_check() must bound its auth_check() call with asyncio.wait_for.

    auth_check() is a blocking SDK call.  Without a timeout, a slow or
    unreachable Langfuse server can stall the lifespan startup indefinitely.
    M-4 — T-221.
    """
    source = read_backend_file("services", "langfuse_service.py")

    fn_match = re.search(
        r"async\s+def\s+startup_check\s*\(\s*self[^)]*\)(.*?)(?=\n\s{0,4}async\s+def|\n\s{0,4}def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, (
        "startup_check() not found in langfuse_service.py.  M-4 — T-221."
    )
    method_body = fn_match.group(1)

    assert "asyncio.wait_for" in method_body, (
        "startup_check() must use asyncio.wait_for() to bound the auth_check() "
        "call so a slow Langfuse server cannot stall lifespan startup.  "
        "M-4 — T-221."
    )

    assert "auth_check" in method_body, (
        "startup_check() must call client.auth_check() via asyncio.to_thread.  "
        "M-4 — T-221."
    )


def test_phase17_langfuse_startup_check_never_raises() -> None:
    """M-4 — startup_check() must handle all exceptions without re-raising.

    A Langfuse outage or misconfiguration must never prevent application startup.
    Every exception path (TimeoutError, generic Exception) must be caught and
    logged, not re-raised.  M-4 — T-221.
    """
    source = read_backend_file("services", "langfuse_service.py")

    fn_match = re.search(
        r"async\s+def\s+startup_check\s*\(\s*self[^)]*\)(.*?)(?=\n\s{0,4}async\s+def|\n\s{0,4}def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, "startup_check() not found.  M-4 — T-221."
    method_body = fn_match.group(1)

    assert "except" in method_body, (
        "startup_check() must catch exceptions (at minimum asyncio.TimeoutError "
        "and a broad Exception) and return False without re-raising.  "
        "M-4 — T-221."
    )

    assert "asyncio.TimeoutError" in method_body or "TimeoutError" in method_body, (
        "startup_check() must explicitly handle asyncio.TimeoutError so a slow "
        "Langfuse server does not propagate a timeout exception to the lifespan.  "
        "M-4 — T-221."
    )


# ---------------------------------------------------------------------------
# T-222 (L-4): sliding_window_check in stage_manager must have RedisError fallback
# ---------------------------------------------------------------------------


def test_phase17_stage_manager_sliding_window_redis_error_fallback() -> None:
    """L-4 — sliding_window_check calls in stage_manager must catch RedisError.

    Without a try/except RedisError, a Redis connectivity blip propagates as
    an unhandled SSE 'internal_error' event.  The fix is fail-open with a
    WARNING log — matching RateLimitMiddleware's established behavior.
    L-4 — T-222.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    # The source must contain both sliding_window_check and a RedisError handler
    # in proximity.  We check that both symbols appear in the file — a more
    # precise structural test would require AST parsing.
    assert "sliding_window_check" in source, (
        "stage_manager.py must call sliding_window_check() for per-user LLM rate "
        "limiting.  L-4 — T-222."
    )

    # Check that RedisError is referenced (either imported or in an except clause)
    # near the sliding_window_check usage.
    assert "RedisError" in source, (
        "stage_manager.py must import or reference redis.exceptions.RedisError "
        "to handle Redis failures in sliding_window_check calls.  Without this, "
        "a Redis connectivity blip propagates as an internal_error SSE event "
        "instead of a graceful fail-open.  L-4 — T-222."
    )


def test_phase17_stage_manager_sliding_window_fallback_logs_warning() -> None:
    """L-4 — The RedisError fallback in stage_manager must log a WARNING with
    a distinctive event name that includes 'llm_rate_limit'.

    Fail-open behavior must be observable.  A WARNING log with stage_id and
    user_id context allows operators to detect degraded rate-limiting state.
    The log event name 'llm_rate_limit' or 'stage_manager.llm_rate_limit'
    is required to distinguish this from the middleware-level rate limit logs.
    L-4 — T-222.
    """
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    # Must contain the specific log event name — not just the word "rate_limit"
    # which appears in RateLimitError references throughout the file.
    assert "llm_rate_limit" in source, (
        "stage_manager.py must log a warning with event name containing "
        "'llm_rate_limit' when RedisError occurs in the sliding_window_check "
        "fallback path.  Example: logger.warning('stage_manager.llm_rate_limit"
        ".redis_unavailable ...).  This is needed to distinguish the LLM-tier "
        "rate limit bypass from the middleware-level rate limit bypass.  "
        "L-4 — T-222."
    )


# ---------------------------------------------------------------------------
# T-223 (L-1): gateway.py must have TTL constant and tuple-based _INSTANCES
# ---------------------------------------------------------------------------


def test_phase17_gateway_adapter_cache_has_ttl_constant() -> None:
    """L-1 — gateway.py must define _INSTANCE_CACHE_TTL_SECONDS.

    Without a TTL, stale adapters with dead connection pools are served
    indefinitely.  A 1-hour TTL ensures adapters are periodically rebuilt.
    L-1 — T-223.
    """
    source = read_backend_file("services", "llm", "gateway.py")

    assert "_INSTANCE_CACHE_TTL_SECONDS" in source, (
        "gateway.py must define _INSTANCE_CACHE_TTL_SECONDS (e.g., 3600.0) for "
        "time-based eviction of cached LLM adapter instances.  Without a TTL, "
        "adapters with stale connection pools are served indefinitely until the "
        "LRU cap forces eviction.  L-1 — T-223."
    )


def test_phase17_gateway_instances_stores_tuples_with_timestamp() -> None:
    """L-1 — _INSTANCES must store (adapter, created_at) tuples for TTL checking.

    TTL eviction requires knowing when each adapter was created.  The tuple
    pattern (adapter, monotonic_timestamp) is the minimal change to support
    this without introducing a new data structure.  L-1 — T-223.
    """
    source = read_backend_file("services", "llm", "gateway.py")

    # The get_llm function should unpack a tuple and check age.
    assert re.search(r"monotonic|perf_counter|time\(\)", source), (
        "gateway.py must use time.monotonic() (or equivalent) to record adapter "
        "creation timestamps for TTL checking.  L-1 — T-223."
    )

    # The TTL check should evict expired entries.
    assert "_INSTANCE_CACHE_TTL_SECONDS" in source and (
        "monotonic" in source or "time()" in source
    ), (
        "gateway.py must compare the cached adapter's age against "
        "_INSTANCE_CACHE_TTL_SECONDS to implement TTL eviction.  L-1 — T-223."
    )


# ---------------------------------------------------------------------------
# T-224 (Ops): RUNBOOK.md must have Secret Rotation Procedures section
# ---------------------------------------------------------------------------


def test_phase17_runbook_has_secret_rotation_section() -> None:
    """Ops — RUNBOOK.md must contain a Secret Rotation Procedures section.

    ENCRYPTION_MASTER_KEY, CSRF_SECRET, and JWT keys require documented
    rotation procedures.  Loss of these procedures forces ad-hoc rotations
    during incidents, increasing risk of data loss or user session disruption.
    T-224.
    """
    runbook_path = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook_path.exists(), (
        "docs/RUNBOOK.md must exist.  Run T-216 first.  T-224."
    )
    content = runbook_path.read_text(encoding="utf-8")

    # Accept either numbered (§8 or ## 8) or text heading ("Secret Rotation")
    has_rotation_section = (
        "Secret Rotation" in content
        or "secret rotation" in content.lower()
        or "§8" in content
        or "## 8" in content
    )
    assert has_rotation_section, (
        "RUNBOOK.md must contain a 'Secret Rotation' section (§8 or equivalent).  "
        "This section must cover ENCRYPTION_MASTER_KEY, CSRF_SECRET, and JWT key "
        "rotation procedures.  T-224."
    )


def test_phase17_runbook_secret_rotation_covers_all_keys() -> None:
    """Ops — RUNBOOK.md rotation section must cover all three critical secrets.

    Each secret has a distinct rotation impact and procedure:
    - ENCRYPTION_MASTER_KEY: requires re-encrypting stored user API keys
    - CSRF_SECRET: invalidates all outstanding CSRF tokens immediately
    - JWT_PRIVATE_KEY: forces all users to re-authenticate
    All three must be documented.  T-224.
    """
    runbook_path = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert runbook_path.exists(), "docs/RUNBOOK.md must exist.  T-224."
    content = runbook_path.read_text(encoding="utf-8")

    assert "ENCRYPTION_MASTER_KEY" in content, (
        "RUNBOOK.md must document ENCRYPTION_MASTER_KEY rotation.  Loss of this "
        "key makes all stored user API keys permanently unrecoverable.  T-224."
    )

    assert "CSRF_SECRET" in content, (
        "RUNBOOK.md must document CSRF_SECRET rotation.  Rotating this secret "
        "immediately invalidates all outstanding CSRF tokens — users will see 403 "
        "errors on their next mutating request.  T-224."
    )

    assert (
        "JWT_PRIVATE_KEY" in content
        or "JWT key" in content
        or "JWT rotation" in content.lower()
    ), (
        "RUNBOOK.md must document JWT key rotation.  Rotating JWT keys forces all "
        "users to re-authenticate.  T-224."
    )


# ---------------------------------------------------------------------------
# T-225 (H-3): RateLimitMiddleware must NOT bypass all tiers when redis is None
# ---------------------------------------------------------------------------


def test_phase17_rate_limit_startup_uses_fallback_not_bypass() -> None:
    """H-3 — RateLimitMiddleware must NOT have a bare 'return await call_next(request)'
    immediately after the redis is None check.

    The original code called return call_next() when app.state.redis is None,
    bypassing ALL rate limiting (IP global cap, per-user, all domain tiers).
    The fix uses _local_fallback_check instead — matching the RedisError fallback
    path already present.  H-3 — T-225.
    """
    source = read_backend_file("middleware", "rate_limit.py")

    # Extract the dispatch() method body.
    dispatch_match = re.search(
        r"async\s+def\s+dispatch\s*\([^)]*\)(.*?)(?=\n\s{0,4}async\s+def|\n\s{0,4}def\s+\w|\Z)",
        source,
        re.DOTALL,
    )
    assert dispatch_match, (
        "dispatch() not found in rate_limit.py.  H-3 — T-225."
    )
    dispatch_body = dispatch_match.group(1)

    none_check_pos = dispatch_body.find("redis is None")
    assert none_check_pos != -1, (
        "dispatch() must check 'redis is None' to handle startup window.  "
        "H-3 — T-225."
    )

    # Grab only the ~500 chars immediately following the None check — this is the
    # startup-window handling block.  The RedisError fallback block comes LATER and
    # also references _local_fallback_check; we must not count that as a pass.
    # 500 chars covers ~15 lines of Python, which is enough for the startup block
    # without reaching the RedisError except block further down.
    startup_block = dispatch_body[none_check_pos : none_check_pos + 500]

    assert "_local_fallback_check" in startup_block, (
        "When app.state.redis is None, RateLimitMiddleware must use "
        "_local_fallback_check within the startup block (the ~15 lines immediately "
        "after the 'redis is None' check), not bypass all rate limiting.  "
        "The current code calls 'return await call_next(request)' which bypasses "
        "ALL rate tiers.  Replace with: limited_response = await "
        "self._enforce_limits(request, ip, path, self._local_fallback_check).  "
        "H-3 — T-225."
    )

    # Also assert the anti-pattern is gone: the startup block must NOT contain
    # 'return await call_next' without going through _enforce_limits first.
    assert "return await call_next" not in startup_block, (
        "The 'redis is None' startup block must NOT contain "
        "'return await call_next(request)' — this would bypass all rate limiting.  "
        "Use _local_fallback_check via _enforce_limits instead.  H-3 — T-225."
    )


def test_phase17_rate_limit_startup_log_message_updated() -> None:
    """H-3 — The rate_limit.redis_not_ready WARNING region must not describe the
    startup window as 'bypassed' — it falls back to in-process limits.

    The current code says '— rate limiting bypassed until Redis is registered'.
    After T-225, rate limiting is NOT bypassed — it uses _local_fallback_check.
    The log message should say 'falling back to in-process rate limiting' so that
    monitoring alerts don't fire 'no rate limiting active' false alarms.
    H-3 — T-225.
    """
    source = read_backend_file("middleware", "rate_limit.py")

    # Find the region of source that contains 'redis_not_ready' (the warning block).
    # Use DOTALL to span the multiline string concatenation.
    # Look at up to 600 chars starting from the redis_not_ready string to capture
    # the full warning call (even if split across multiple string literals).
    redis_not_ready_pos = source.find("redis_not_ready")
    assert redis_not_ready_pos != -1, (
        "rate_limit.py must contain 'redis_not_ready' in a log message.  "
        "H-3 — T-225."
    )

    # Capture ~600 chars of context around the warning call.
    warning_region = source[max(0, redis_not_ready_pos - 100) : redis_not_ready_pos + 600]

    # The region must NOT contain 'bypassed' or 'bypass' (the pre-fix anti-pattern).
    assert "bypass" not in warning_region.lower(), (
        "The redis_not_ready warning region in rate_limit.py must NOT say 'bypass'.  "
        "The current pre-fix message says '— rate limiting bypassed until Redis is "
        "registered by the lifespan' — this is incorrect after T-225 because rate "
        "limiting is NOT bypassed (it uses _local_fallback_check).  Update to say "
        "'falling back to in-process rate limiting'.  H-3 — T-225."
    )
