"""
Harness contracts for Phase 15 — Enterprise Production Hardening.

These tests are RED before T-174 through T-190 are implemented and GREEN after.

Every test maps to one or more findings from docs/CODE_REVIEW.md:
  C-1  finalise() missing SELECT FOR UPDATE → T-174
  C-2  generate_harness_patch allowlist contains dead/dangerous statuses → T-174
  C-3  OAuth state TOCTOU (get + delete not atomic) → T-175
  C-4  WeasyPrint blocks event loop → T-176
  H-1  Redis.from_url per-request (no pooling) → T-177
  H-2  N+1 coverage query in workspace list → T-178
  H-3  Recovery lock TTL == poll interval (dangerous) → T-179
  H-4  Auth cache not invalidated on credit change → T-180
  H-5  Markdown XSS (no rehype-sanitize) → T-181 (frontend)
  H-6  No httpx.Timeout on LLM adapters → T-182
  M-1  _coverage_label uses getattr on ORM (dead attribute) → T-183
  M-2  Rate limit fallback evicts only 1 entry at cap → T-184
  M-3  CSRF token has no nonce → T-185
  M-4  SSE cleanup nulls ref before close → T-186 (frontend)
  M-5  Eval polling silently drops error → T-187 (frontend)
  M-6  streamingContent typed as union with string → T-188 (frontend)
  M-7  SSE comment contradicts code → T-186 (frontend)
  L-1  STAGE_DEPENDENCIES defined twice → T-189a
  L-2  Double DB load in workspace router → T-189a
  L-3  CreditConfirmModal duplicate prop aliases → T-189b (frontend)
  L-4  ExportGitHubModal setTimeout auto-close → T-189b (frontend)
  L-5  TemplatesStrip no error boundary → T-189b (frontend)
  L-6  SharePublicLinkModal no focus trap → T-189b (frontend)
  L-7  Docker ports bound to 0.0.0.0 → T-189c
  L-8  Rate limit overrides undocumented → T-189c

Design invariants enforced here:
  * finalise() acquires a row-level lock — no concurrent finalise side-effects.
  * generate_harness_patch() only starts on draft/stale/finalised stages.
  * OAuth state is consumed atomically — no replay window.
  * PDF export runs in a thread pool — event loop stays unblocked.
  * Redis is injected as a pooled dependency — no per-request from_url calls.
  * Coverage derivation is batched — workspace list is O(1) queries.
  * Recovery lock TTL is at least 3x the poll interval.
  * Credit invalidation clears the auth middleware user cache.
  * Every LLM adapter specifies an httpx.Timeout.
  * _coverage_label accepts coverage as an explicit parameter.
  * Rate limit fallback evicts a bulk fraction at cap.
  * CSRF tokens contain a nonce component.
  * STAGE_DEPENDENCIES has exactly one definition in the backend.
  * Docker Compose binds DB/Redis ports to 127.0.0.1.
  * Rate limit override constants are documented inline.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import BACKEND_ROOT, REPO_ROOT, import_backend, read_backend_file


# ---------------------------------------------------------------------------
# T-174 (C-1): finalise() must use SELECT FOR UPDATE
# ---------------------------------------------------------------------------


def test_phase15_finalise_uses_select_for_update() -> None:
    # T-174 / C-1: Two concurrent finalise() calls must not both apply
    # side-effects. _load_stage must be called with lock=True so PostgreSQL
    # issues SELECT FOR UPDATE, serialising access.
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    # Find the finalise function body — everything between 'def finalise' and
    # the next 'async def' or 'def ' at the same or lower indent level.
    # The simplest check: verify that _load_stage is called with lock=True
    # somewhere in the file AND that the finalise function exists.
    assert "def finalise" in source or "async def finalise" in source, (
        "stage_manager.py must define a finalise function. T-174."
    )
    assert re.search(r"_load_stage\([^)]*lock\s*=\s*True", source), (
        "finalise() must call _load_stage(..., lock=True) to prevent concurrent "
        "finalise race. C-1 — T-174."
    )


# ---------------------------------------------------------------------------
# T-174 (C-2): generate_harness_patch allowlist must exclude dead statuses
# ---------------------------------------------------------------------------


def test_phase15_generate_harness_patch_status_allowlist() -> None:
    # T-174 / C-2: The status allowlist in generate_harness_patch must NOT
    # contain "in_progress" (allows double generation) or "final" (dead alias
    # for "finalised"). Allowlist must be ("draft", "stale", "finalised").
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert "generate_harness_patch" in source, (
        "stage_manager.py must define generate_harness_patch. T-174."
    )

    # Extract the region around generate_harness_patch to scope the check.
    fn_start = source.find("generate_harness_patch")
    region = source[fn_start : fn_start + 2000]

    assert '"in_progress"' not in region and "'in_progress'" not in region, (
        "generate_harness_patch status allowlist must NOT contain 'in_progress'. "
        "Allowing in_progress lets a new generation start on a running stage — "
        "double credits + corrupt generation state. C-2 — T-174."
    )
    # "final" as a standalone status (not as part of "finalised") must be gone.
    # We check for the quoted standalone form.
    assert '"final"' not in region and "'final'" not in region, (
        "generate_harness_patch status allowlist must NOT contain 'final' "
        "(dead alias; real status is 'finalised'). C-2 — T-174."
    )
    assert "finalised" in region, (
        "generate_harness_patch status allowlist must contain 'finalised'. "
        "C-2 — T-174."
    )


# ---------------------------------------------------------------------------
# T-175 (C-3): OAuth state must be consumed atomically via getdel
# ---------------------------------------------------------------------------


def test_phase15_oauth_state_uses_getdel() -> None:
    # T-175 / C-3: get() + delete() on the OAuth state key is a TOCTOU race.
    # getdel() is atomic — read and delete in one round-trip.
    source = read_backend_file("services", "auth_service.py")

    assert "getdel" in source, (
        "auth_service.py must use redis.getdel(state_key) to consume the OAuth "
        "state atomically. A separate get() + delete() allows two simultaneous "
        "callbacks to both pass the CSRF check. C-3 — T-175."
    )


def test_phase15_oauth_state_no_separate_delete_after_get() -> None:
    # T-175 / C-3: Confirm the two-op pattern is gone — no redis.delete on the
    # state_key occurring after a redis.get on the state_key in the same function.
    source = read_backend_file("services", "auth_service.py")

    # The fix replaces get+delete with getdel. The state key variable name may
    # vary but the pattern of calling both get and delete should be gone.
    # We look for getdel being present (tested above) and then verify the old
    # two-op pattern is absent by checking that 'state_key' does not appear
    # in a 'redis.delete(' call (or await redis.delete).
    if "state_key" in source:
        # Allow delete calls for OTHER keys, but the state_key delete should
        # be folded into getdel. A direct assertion: if getdel is present and
        # delete(state_key) is also present, warn. This is a soft check because
        # the state key variable might be named differently.
        delete_state = re.search(r"redis\.delete\(state_key\)", source)
        assert not delete_state, (
            "auth_service.py must not call redis.delete(state_key) separately — "
            "the get+delete TOCTOU must be replaced with getdel. C-3 — T-175."
        )


# ---------------------------------------------------------------------------
# T-176 (C-4): PDF export must use run_in_executor
# ---------------------------------------------------------------------------


def test_phase15_pdf_export_uses_run_in_executor() -> None:
    # T-176 / C-4: WeasyPrint's write_pdf() is synchronous and CPU-bound.
    # Calling it directly inside an async handler blocks the entire event loop.
    # It must be dispatched to a thread pool via run_in_executor.
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    assert "run_in_executor" in source, (
        "pdf_export_service.py must call run_in_executor to dispatch WeasyPrint "
        "to a thread pool. Calling write_pdf() synchronously on the event loop "
        "blocks all concurrent requests. C-4 — T-176."
    )


def test_phase15_pdf_sync_helper_is_module_level() -> None:
    # T-176 / C-4: The synchronous WeasyPrint call must live in a module-level
    # (non-async) helper function so run_in_executor can call it cleanly.
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    # A module-level sync helper will start at column 0 with 'def _render_pdf'
    # or similar (not 'async def').
    has_sync_helper = bool(
        re.search(r"^def _render_pdf", source, re.MULTILINE)
        or re.search(r"^def _.*pdf.*\(", source, re.MULTILINE)
    )
    assert has_sync_helper, (
        "pdf_export_service.py must define a module-level (non-async) helper "
        "function that calls write_pdf(), callable by run_in_executor. C-4 — T-176."
    )


# ---------------------------------------------------------------------------
# T-177 (H-1): No Redis.from_url in request handlers
# ---------------------------------------------------------------------------


def test_phase15_no_redis_from_url_in_request_handlers() -> None:
    # T-177 / H-1: Redis.from_url() per-request creates un-pooled connections.
    # All handlers must use the shared app.state.redis via a get_redis dependency.
    router_dir = BACKEND_ROOT / "routers"
    service_dir = BACKEND_ROOT / "services"
    violations: list[str] = []

    for search_dir in (router_dir, service_dir):
        if not search_dir.exists():
            continue
        for py_file in search_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            if "Redis.from_url(" in content or "from_url(" in content:
                # Allow imports and TYPE_CHECKING blocks; look for actual calls.
                lines = content.splitlines()
                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if (
                        "from_url(" in stripped
                        and not stripped.startswith("#")
                        and "import" not in stripped
                    ):
                        violations.append(f"{py_file.relative_to(REPO_ROOT)}:{i}")

    assert not violations, (
        "Redis.from_url() must not appear in routers or services — use the "
        "get_redis FastAPI dependency that returns app.state.redis. Violations:\n"
        + "\n".join(violations)
        + "\nH-1 — T-177."
    )


def test_phase15_get_redis_dependency_exists() -> None:
    # T-177 / H-1: The get_redis dependency must exist in dependencies.py or
    # a similar module so routers can inject the shared Redis client.
    candidates = [
        BACKEND_ROOT / "dependencies.py",
        BACKEND_ROOT / "deps.py",
        BACKEND_ROOT / "database.py",
    ]
    found = False
    for candidate in candidates:
        if candidate.exists() and "get_redis" in candidate.read_text(encoding="utf-8"):
            found = True
            break
    assert found, (
        "A get_redis FastAPI dependency must be defined (e.g. in "
        "backend/dependencies.py). It should return request.app.state.redis. "
        "H-1 — T-177."
    )


# ---------------------------------------------------------------------------
# T-178 (H-2): Coverage derivation must be batched (no N+1)
# ---------------------------------------------------------------------------


def test_phase15_workspace_list_no_n_plus_one() -> None:
    # T-178 / H-2: _derive_coverage_summary must accept a list/sequence of IDs
    # (not a single UUID) so it can issue one batched query for all workspaces.
    source = read_backend_file("routers", "workspace.py")

    # The function signature in workspace.py (or the service it delegates to)
    # should accept a list. Check that the router does NOT call it inside a
    # list comprehension or for-loop over workspaces.
    list_comp_pattern = re.search(
        r"for\s+\w+\s+in\s+workspaces.*_derive_coverage_summary",
        source,
        re.DOTALL,
    )
    assert not list_comp_pattern, (
        "workspace.py must not call _derive_coverage_summary inside a loop over "
        "workspaces. This causes N+1 queries. The function must accept a list of "
        "IDs and issue one batched query. H-2 — T-178."
    )


# ---------------------------------------------------------------------------
# T-179 (H-3): Recovery lock TTL must exceed poll interval
# ---------------------------------------------------------------------------


def test_phase15_recovery_lock_ttl_exceeds_poll_interval() -> None:
    # T-179 / H-3: If TTL == POLL_INTERVAL, a slow recovery run expires the
    # lock and allows a concurrent recovery runner — double recovery.
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    ttl_match = re.search(r"_RECOVERY_LOCK_TTL\s*=\s*(\d+)", source)
    poll_match = re.search(r"_POLL_INTERVAL_SECONDS\s*=\s*(\d+)", source)

    assert ttl_match, "stage_manager.py must define _RECOVERY_LOCK_TTL. H-3 — T-179."
    assert poll_match, (
        "stage_manager.py must define _POLL_INTERVAL_SECONDS. H-3 — T-179."
    )

    ttl = int(ttl_match.group(1))
    poll = int(poll_match.group(1))

    assert ttl >= 3 * poll, (
        f"_RECOVERY_LOCK_TTL ({ttl}s) must be at least 3× _POLL_INTERVAL_SECONDS "
        f"({poll}s) to prevent lock expiry during slow recovery runs. "
        f"H-3 — T-179."
    )


def test_phase15_recovery_lock_heartbeat_exists() -> None:
    # T-179 / H-3: The recovery loop must refresh the lock TTL each iteration
    # so a long-running recovery does not lose the lock mid-flight.
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    has_expire_heartbeat = "redis.expire" in source or "await redis.expire" in source
    assert has_expire_heartbeat, (
        "stage_manager.py recovery loop must call redis.expire(lock_key, TTL) "
        "each iteration to keep the lock alive during long recoveries. "
        "H-3 — T-179."
    )


# ---------------------------------------------------------------------------
# T-180 (H-4): Credit invalidation must clear auth cache
# ---------------------------------------------------------------------------


def test_phase15_credit_invalidation_clears_auth_cache() -> None:
    # T-180 / H-4: credit_service._invalidate() must call invalidate_user_cache
    # from middleware/auth.py to flush the stale credit_balance entry.
    source = read_backend_file("services", "credit_service.py")

    assert "invalidate_user_cache" in source, (
        "credit_service.py must import and call invalidate_user_cache() from "
        "middleware.auth so the 30s cached credit_balance is flushed immediately "
        "after every charge or grant. H-4 — T-180."
    )


def test_phase15_auth_middleware_exports_invalidate_user_cache() -> None:
    # T-180 / H-4: The auth middleware must expose the invalidation function
    # so credit_service can import it without circular import issues.
    source = read_backend_file("middleware", "auth.py")

    assert "invalidate_user_cache" in source, (
        "middleware/auth.py must define and export an invalidate_user_cache() "
        "function that removes the given user_id from _USER_CACHE. H-4 — T-180."
    )


# ---------------------------------------------------------------------------
# T-182 (H-6): LLM adapters must specify httpx.Timeout
# ---------------------------------------------------------------------------


def test_phase15_llm_adapters_have_httpx_timeout() -> None:
    # T-182 / H-6: A hung provider connection holds the event loop slot and
    # the credit reservation indefinitely. Each adapter must set explicit
    # connect and read timeouts.
    llm_dir = BACKEND_ROOT / "services" / "llm"
    assert llm_dir.exists(), "backend/services/llm/ must exist. H-6 — T-182."

    adapter_files = [
        f
        for f in llm_dir.iterdir()
        if f.suffix == ".py" and f.name not in ("__init__.py", "gateway.py")
    ]
    assert adapter_files, (
        "backend/services/llm/ must contain at least one adapter file. H-6 — T-182."
    )

    missing_timeout: list[str] = []
    for adapter_file in adapter_files:
        content = adapter_file.read_text(encoding="utf-8")
        has_timeout = (
            "httpx.Timeout" in content
            or "Timeout(" in content
            or "timeout=" in content
        )
        if not has_timeout:
            missing_timeout.append(str(adapter_file.relative_to(REPO_ROOT)))

    assert not missing_timeout, (
        "The following LLM adapter files do not configure a timeout. Add "
        "httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0) to each "
        "adapter's httpx.AsyncClient constructor:\n"
        + "\n".join(missing_timeout)
        + "\nH-6 — T-182."
    )


def test_phase15_gateway_has_wall_clock_timeout() -> None:
    # T-182 / H-6: The gateway must apply an asyncio.wait_for wall-clock timeout
    # to cap total generation time regardless of per-chunk read timeouts.
    source = read_backend_file("services", "llm", "gateway.py")

    assert "wait_for" in source or "asyncio.wait_for" in source, (
        "services/llm/gateway.py must use asyncio.wait_for to apply a wall-clock "
        "timeout to the generation call. This ensures a credit reservation is "
        "released even if the provider never closes the stream. H-6 — T-182."
    )


# ---------------------------------------------------------------------------
# T-183 (M-1): _coverage_label must accept explicit parameter
# ---------------------------------------------------------------------------


def test_phase15_pdf_coverage_label_receives_explicit_parameter() -> None:
    # T-183 / M-1: _coverage_label uses getattr(workspace, "coverage_summary")
    # but the ORM Workspace model has no coverage_summary attribute — it's a
    # computed Pydantic field. The function always returns None. Fix: accept
    # the already-derived coverage as an explicit parameter.
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")

    assert "_coverage_label" in source, (
        "pdf_export_service.py must define _coverage_label. M-1 — T-183."
    )

    assert 'getattr(workspace, "coverage_summary"' not in source and (
        "getattr(workspace, 'coverage_summary'" not in source
    ), (
        "_coverage_label must not use getattr(workspace, 'coverage_summary') — "
        "this attribute does not exist on the ORM model and always returns None. "
        "Pass the pre-computed CoverageSummary as an explicit argument. "
        "M-1 — T-183."
    )


# ---------------------------------------------------------------------------
# T-184 (M-2): Rate limit fallback must bulk-evict at cap
# ---------------------------------------------------------------------------


def test_phase15_rate_limit_fallback_bulk_eviction() -> None:
    # T-184 / M-2: Single-key eviction cannot keep up with a burst of distinct
    # IPs. The fallback must remove a meaningful batch when the cap is reached.
    source = read_backend_file("middleware", "rate_limit.py")

    # The fix uses itertools.islice or a slice to remove multiple entries at once.
    has_bulk_evict = (
        "islice" in source
        or "2_000" in source
        or "2000" in source
        or (re.search(r"del\s+_fallback", source) and "islice" in source)
    )
    assert has_bulk_evict, (
        "middleware/rate_limit.py must bulk-evict a fraction (≥ 20%) of the "
        "fallback OrderedDict when the cap is reached. Single popitem() eviction "
        "cannot bound memory under a burst. Use itertools.islice to delete 2000+ "
        "entries at once. M-2 — T-184."
    )


# ---------------------------------------------------------------------------
# T-185 (M-3): CSRF token must contain a nonce
# ---------------------------------------------------------------------------


def test_phase15_csrf_token_contains_nonce() -> None:
    # T-185 / M-3: The current HMAC-only token is deterministic given user_id
    # and timestamp — no replay protection. A nonce makes each token unique.
    # Look in security services and middleware for CSRF token generation.
    csrf_candidates = [
        BACKEND_ROOT / "services" / "security" / "csrf.py",
        BACKEND_ROOT / "services" / "security" / "csrf_service.py",
        BACKEND_ROOT / "middleware" / "csrf.py",
        BACKEND_ROOT / "middleware" / "rate_limit.py",
    ]
    # Also search any file containing "csrf" in its name.
    all_backend_files = list(BACKEND_ROOT.rglob("*.py"))
    csrf_files = [
        f
        for f in all_backend_files
        if "csrf" in f.name.lower() or "csrf" in f.read_text(encoding="utf-8")[:2000]
    ]

    found_nonce = False
    for f in csrf_files:
        content = f.read_text(encoding="utf-8")
        if (
            "nonce" in content
            or "token_hex" in content
            or "token_bytes" in content
            or "secrets.token" in content
        ) and "csrf" in content.lower():
            found_nonce = True
            break

    assert found_nonce, (
        "CSRF token generation must include a random nonce (e.g. "
        "secrets.token_hex(16)) mixed into the HMAC input. The current "
        "timestamp-only HMAC is deterministic and replayable. M-3 — T-185."
    )


# ---------------------------------------------------------------------------
# T-189a (L-1): STAGE_DEPENDENCIES must be defined exactly once
# ---------------------------------------------------------------------------


def test_phase15_stage_dependencies_single_definition() -> None:
    # T-189a / L-1: Two definitions of STAGE_DEPENDENCIES that diverge silently
    # produce different dependency graphs for stage unlock vs. stage ordering.
    definition_sites: list[str] = []
    for py_file in BACKEND_ROOT.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        if re.search(r"^STAGE_DEPENDENCIES\s*=", content, re.MULTILINE):
            definition_sites.append(str(py_file.relative_to(REPO_ROOT)))

    assert len(definition_sites) == 1, (
        f"STAGE_DEPENDENCIES must be defined exactly once in the backend. "
        f"Found {len(definition_sites)} definitions:\n"
        + "\n".join(definition_sites)
        + "\nRemove duplicates and import from the canonical location. "
        "L-1 — T-189a."
    )


# ---------------------------------------------------------------------------
# T-189c (L-7): Docker Compose frontend port must bind to 127.0.0.1
# ---------------------------------------------------------------------------


def test_phase15_docker_compose_frontend_port_bound_to_localhost() -> None:
    # T-189c / L-7: The Vite dev server port 5173:5173 is the actual L-7
    # finding — it exposes unminified source, source maps, and hot-reload
    # websockets to any machine on the same LAN without 127.0.0.1 binding.
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist at repository root."
    content = compose_file.read_text(encoding="utf-8")

    # The frontend port 5173 must be prefixed with 127.0.0.1.
    # "5173:5173" without a prefix binds to 0.0.0.0 (all interfaces).
    unbound_frontend = re.search(
        r'(?<![0-9\.])(5173:5173)', content
    )
    assert not unbound_frontend, (
        "docker-compose.yml must bind the Vite frontend port as "
        "'127.0.0.1:5173:5173' to prevent exposure of the dev server "
        "to LAN neighbours. L-7 — T-189c."
    )


def test_phase15_docker_compose_db_redis_ports_bound_to_localhost() -> None:
    # T-189c / L-7 extension: While fixing the frontend port, also bind
    # the database (5432) and Redis (6379) ports to localhost.
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist at repository root."
    content = compose_file.read_text(encoding="utf-8")

    unbound_db = re.search(r'(?<![0-9\.])(5432:5432)', content)
    unbound_redis = re.search(r'(?<![0-9\.])(6379:6379)', content)

    assert not unbound_db, (
        "docker-compose.yml must bind the PostgreSQL port as "
        "'127.0.0.1:5432:5432'. L-7 extension — T-189c."
    )
    assert not unbound_redis, (
        "docker-compose.yml must bind the Redis port as "
        "'127.0.0.1:6379:6379'. L-7 extension — T-189c."
    )


# ---------------------------------------------------------------------------
# T-189c (L-8): Auth rate limit Compose overrides must be documented
# ---------------------------------------------------------------------------


def test_phase15_docker_compose_auth_rate_limits_documented() -> None:
    # T-189c / L-8: AUTH_LOGIN_BURST_LIMIT and AUTH_LOGIN_HOURLY_LIMIT in
    # docker-compose.yml override production-safe defaults. A developer who
    # copies the Compose config to staging gets relaxed rate limits silently.
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist at repository root."
    content = compose_file.read_text(encoding="utf-8")

    for var in ("AUTH_LOGIN_BURST_LIMIT", "AUTH_LOGIN_HOURLY_LIMIT"):
        if var in content:
            # The variable must appear on a line that also has a comment
            # or be immediately preceded by a comment line.
            lines = content.splitlines()
            found_comment = False
            for i, line in enumerate(lines):
                if var in line:
                    # Check inline comment on same line
                    if "#" in line and ("local" in line.lower() or "dev" in line.lower() or "staging" in line.lower()):
                        found_comment = True
                        break
                    # Check comment on preceding line
                    if i > 0 and "#" in lines[i - 1] and (
                        "local" in lines[i - 1].lower() or "dev" in lines[i - 1].lower()
                    ):
                        found_comment = True
                        break
            assert found_comment, (
                f"docker-compose.yml: {var} must have an inline or preceding "
                f"comment noting it is 'Local dev only — do not copy to "
                f"staging/production'. L-8 — T-189c."
            )

    # Also check LOCAL_TESTING_HANDBOOK.md mentions these overrides.
    handbook = REPO_ROOT / "docs" / "LOCAL_TESTING_HANDBOOK.md"
    if handbook.exists():
        handbook_text = handbook.read_text(encoding="utf-8")
        assert (
            "AUTH_LOGIN_BURST_LIMIT" in handbook_text
            or "AUTH_LOGIN_HOURLY_LIMIT" in handbook_text
            or ("rate limit" in handbook_text.lower() and "compose" in handbook_text.lower())
        ), (
            "docs/LOCAL_TESTING_HANDBOOK.md must document the "
            "AUTH_LOGIN_BURST_LIMIT / AUTH_LOGIN_HOURLY_LIMIT Compose overrides "
            "and their dev-only scope. L-8 — T-189c."
        )


# ---------------------------------------------------------------------------
# T-191: LLM instance cache must have bounded size
# ---------------------------------------------------------------------------


def test_phase15_llm_instance_cache_has_bounded_size() -> None:
    # T-191: _INSTANCES in gateway.py is a plain dict that is never evicted.
    # Under diverse user load (custom API keys), memory grows monotonically.
    # The cache must have a defined max size with LRU eviction.
    source = read_backend_file("services", "llm", "gateway.py")

    has_bounded_cache = (
        "LRUCache" in source
        or "OrderedDict" in source
        or "_INSTANCE_CACHE_MAX" in source
        or "maxsize" in source
    )
    assert has_bounded_cache, (
        "services/llm/gateway.py: _INSTANCES must use a bounded cache structure "
        "(LRUCache, OrderedDict with eviction, or similar) with a named max-size "
        "constant. A plain dict that is never evicted grows without bound. "
        "T-191."
    )

    # The cache must not silently grow — verify a size cap constant exists.
    has_cap_constant = (
        "_INSTANCE_CACHE_MAX" in source
        or "maxsize" in source
        or re.search(r"=\s*\d{2,3}\b", source)  # a numeric cap (e.g. 256)
    )
    assert has_cap_constant, (
        "services/llm/gateway.py: define a named constant for the instance "
        "cache max size (e.g. _INSTANCE_CACHE_MAX = 256). T-191."
    )


# ---------------------------------------------------------------------------
# T-192: CSRF exempt paths — logout must not be exempt
# ---------------------------------------------------------------------------


def test_phase15_csrf_logout_not_exempt() -> None:
    # T-192: /auth/logout is a mutation (destroys the session). It must not
    # be in _EXEMPT_PATHS — exempting it enables cross-site logout attacks.
    csrf_files = list(BACKEND_ROOT.rglob("csrf*.py")) + list(
        (BACKEND_ROOT / "middleware").glob("*.py")
    )
    for f in csrf_files:
        content = f.read_text(encoding="utf-8")
        if "_EXEMPT_PATHS" in content or "EXEMPT_PATHS" in content:
            # Check that /auth/logout does not appear in the exempt list.
            # Allow it as a comment explaining why it's NOT exempt.
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if "/auth/logout" in line and not line.strip().startswith("#"):
                    # The path appears as code (not a comment) in this file.
                    assert False, (
                        f"{f.relative_to(REPO_ROOT)}: '/auth/logout' must not "
                        f"appear in _EXEMPT_PATHS (line {i + 1}). Logout is a "
                        f"mutation and requires CSRF protection to prevent "
                        f"cross-site logout attacks. T-192."
                    )


def test_phase15_csrf_exempt_paths_all_documented() -> None:
    # T-192: Every path in _EXEMPT_PATHS must have an inline comment explaining
    # why it is safe to exempt from CSRF protection.
    for f in BACKEND_ROOT.rglob("*.py"):
        content = f.read_text(encoding="utf-8")
        if "_EXEMPT_PATHS" not in content:
            continue
        lines = content.splitlines()
        in_exempt = False
        for line in lines:
            stripped = line.strip()
            if "_EXEMPT_PATHS" in stripped and "=" in stripped:
                in_exempt = True
            if in_exempt:
                # A string literal in the list without a comment is a violation.
                if re.search(r'["\']/.+["\']', stripped) and "#" not in stripped:
                    assert False, (
                        f"{f.relative_to(REPO_ROOT)}: exempt path '{stripped}' "
                        f"has no inline comment explaining why it is safe to "
                        f"skip CSRF. Add '# exempt: <reason>'. T-192."
                    )
                if stripped.startswith("]") or stripped.startswith(")"):
                    in_exempt = False


# ---------------------------------------------------------------------------
# T-193: Public share page must have CSP configured
# ---------------------------------------------------------------------------


def test_phase15_public_share_csp_configured() -> None:
    # T-193: The /p/:slug public share page is unauthenticated and renders
    # LLM-generated Markdown. It needs an explicit Content-Security-Policy.
    csp_found = False

    # Check frontend/_headers
    headers_file = REPO_ROOT / "frontend" / "public" / "_headers"
    if headers_file.exists():
        content = headers_file.read_text(encoding="utf-8")
        if "Content-Security-Policy" in content and ("/p/" in content or "/*" in content):
            csp_found = True

    # Check vercel.json
    vercel_json = REPO_ROOT / "vercel.json"
    if vercel_json.exists():
        content = vercel_json.read_text(encoding="utf-8")
        if "Content-Security-Policy" in content:
            csp_found = True

    # Check backend public endpoint
    workspace_router = read_backend_file("routers", "workspace.py")
    if "Content-Security-Policy" in workspace_router:
        csp_found = True

    assert csp_found, (
        "The public share page (/p/:slug) must have a Content-Security-Policy "
        "configured via frontend/public/_headers, vercel.json, or the backend "
        "public endpoint response headers. The page is unauthenticated and "
        "renders LLM-generated content. T-193."
    )


# ---------------------------------------------------------------------------
# T-194: Prometheus metrics for SSE, PDF, and eval
# ---------------------------------------------------------------------------


def test_phase15_sse_failure_counter_defined() -> None:
    # T-194: SSE streaming failures are invisible in metrics. A counter must
    # be defined and incremented when a stream terminates on error.
    all_backend = list(BACKEND_ROOT.rglob("*.py"))
    found = any(
        "specforge_sse_stream_failures_total" in f.read_text(encoding="utf-8")
        for f in all_backend
    )
    assert found, (
        "backend/ must define a Prometheus Counter "
        "'specforge_sse_stream_failures_total' and increment it on SSE "
        "streaming failure. T-194."
    )


def test_phase15_pdf_export_histogram_defined() -> None:
    # T-194: PDF export duration is not measured. A histogram makes the
    # event-loop blocking issue (C-4) visible in production dashboards.
    all_backend = list(BACKEND_ROOT.rglob("*.py"))
    found = any(
        "specforge_pdf_export_duration_seconds" in f.read_text(encoding="utf-8")
        for f in all_backend
    )
    assert found, (
        "backend/ must define a Prometheus Histogram "
        "'specforge_pdf_export_duration_seconds' and observe it on every "
        "PDF export call. T-194."
    )


def test_phase15_eval_failure_counter_defined() -> None:
    # T-194: Eval polling failure rate is not instrumented. Silent drop after
    # 12 retries is invisible in metrics without an explicit counter.
    all_backend = list(BACKEND_ROOT.rglob("*.py"))
    found = any(
        "specforge_eval_poll_failures_total" in f.read_text(encoding="utf-8")
        for f in all_backend
    )
    assert found, (
        "backend/ must define a Prometheus Counter "
        "'specforge_eval_poll_failures_total' and increment it when eval "
        "polling gives up after max retries. T-194."
    )


# ---------------------------------------------------------------------------
# T-195: Missing concurrency and integration test file
# ---------------------------------------------------------------------------


def test_phase15_concurrency_tests_exist() -> None:
    # T-195: Five test categories have no regression coverage. A dedicated
    # test_concurrency.py must contain all five test functions.
    test_file = BACKEND_ROOT / "tests" / "test_concurrency.py"
    assert test_file.exists(), (
        "backend/tests/test_concurrency.py must exist with concurrency and "
        "integration tests for the five missing test categories. T-195."
    )
    content = test_file.read_text(encoding="utf-8")

    required_tests = [
        "finalise",          # concurrency test for the C-1 race
        "in_progress",       # harness-patch on in_progress → 409 (C-2)
        "replay",            # OAuth state replay (C-3)
        "cleanup_done",      # SSE lifecycle on disconnect
        "invalidat",         # credit balance staleness / cache invalidation (H-4)
    ]
    missing = [kw for kw in required_tests if kw not in content]
    assert not missing, (
        f"backend/tests/test_concurrency.py is missing tests covering: "
        + ", ".join(missing)
        + ". All five concurrency/integration test categories from the "
        "Testing Assessment must be present. T-195."
    )
