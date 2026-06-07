"""Production readiness audit contract tests.

Covers the blockers and high-risk issues identified in the final
production readiness audit (2026-05-04). Each test maps to a task
in tasks.md (T-114 through T-120).
"""

from __future__ import annotations

import re

import pytest
from harness_utils import REPO_ROOT, import_backend, read_backend_file


# ---------------------------------------------------------------------------
# T-114 — B-1: Credit ledger unique constraint must not break repeat deductions
# ---------------------------------------------------------------------------


def test_credit_ledger_constraint_is_not_broad_unique_on_user_reason() -> None:
    """The migration chain must not leave a plain UNIQUE(user_id, reason) in effect.

    Migration 0003 introduced UNIQUE(user_id, reason) on credit_ledger, which
    prevents users from making more than one deduction with the same reason string
    (e.g. "generate"). A subsequent migration must drop that broad constraint and
    replace it with a partial index scoped to refund rows only.

    Acceptance: either 0003 itself uses a partial index, OR a later migration
    drops "uq_credit_ledger_user_reason" and adds a partial index on
    reason LIKE 'refund:%'.
    """
    versions_dir = REPO_ROOT / "backend" / "migrations" / "versions"
    all_migration_sources = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(versions_dir.glob("*.py"))
    )

    # The broad constraint must be dropped somewhere in the chain
    broad_constraint_dropped = "drop_constraint" in all_migration_sources and (
        "uq_credit_ledger_user_reason" in all_migration_sources
    )

    # A partial index scoped to refund rows must be created somewhere in the chain
    partial_index_created = (
        "uq_credit_ledger_refund_reason" in all_migration_sources
        or (
            "LIKE 'refund:%'" in all_migration_sources
            or "LIKE" in all_migration_sources
            and "refund" in all_migration_sources
        )
    )

    assert broad_constraint_dropped and partial_index_created, (
        "The migration chain does not fix the broad UNIQUE(user_id, reason) constraint "
        "on credit_ledger. Add a migration that: (1) drops 'uq_credit_ledger_user_reason', "
        "(2) creates a partial unique index WHERE reason LIKE 'refund:%'. "
        "Without this fix, users cannot generate or refine content more than once."
    )


def test_credit_service_deduct_does_not_catch_integrity_error() -> None:
    """deduct() must not silently swallow IntegrityError.

    If deduct() caught IntegrityError (as refund() does), the broad unique
    constraint would silently reject legitimate deductions. The IntegrityError
    catch belongs exclusively in refund() where it acts as a double-refund guard.
    """
    source = read_backend_file("services", "credit_service.py")

    # Split on method boundaries (handles 4-space indentation inside a class).
    # Each chunk starts at an "async def <name>" line.
    method_chunks: dict[str, str] = {}
    current_name = "__module__"
    current_lines: list[str] = []
    for line in source.splitlines():
        m = re.match(r"\s+async def (\w+)\b", line)
        if m:
            method_chunks[current_name] = "\n".join(current_lines)
            current_name = m.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)
    method_chunks[current_name] = "\n".join(current_lines)

    assert "deduct" in method_chunks, "deduct() method must exist in credit_service.py"
    deduct_body = method_chunks["deduct"]

    assert "IntegrityError" not in deduct_body, (
        "deduct() must not catch IntegrityError. "
        "That catch belongs only in refund() as a double-refund guard. "
        "Silently swallowing IntegrityError in deduct() would hide the broken "
        "UNIQUE(user_id, reason) constraint."
    )


def test_refund_uses_unique_reason_derived_from_original_entry_id() -> None:
    """refund() must use a reason that is unique per original ledger entry.

    The double-refund guard relies on a reason string that is unique per
    deduction (e.g. f'refund:{ledger_entry_id}'). A fixed string like 'refund'
    would itself hit the unique constraint on the second refund of any kind.
    """
    source = read_backend_file("services", "credit_service.py")

    # The refund reason must include the ledger entry id (a UUID),
    # making it globally unique.
    assert "refund:" in source and "ledger_entry_id" in source, (
        "refund() must construct a unique reason string that includes the "
        "original ledger entry ID (e.g. f'refund:{ledger_entry_id}')."
    )


def test_credit_service_can_deduct_multiple_times_with_same_reason() -> None:
    """Functional: CreditService.deduct() must succeed on repeated calls.

    Exercises the application-layer credit path in isolation. Uses a fake DB
    that does NOT raise IntegrityError, confirming that the deduct logic itself
    has no uniqueness restriction at the application layer.
    """
    credit_service_mod = import_backend("services.credit_service")
    CreditService = credit_service_mod.CreditService
    models_mod = import_backend("models")
    CreditLedger = models_mod.CreditLedger
    User = models_mod.User

    from uuid import uuid4

    class _Redis:
        def __init__(self):
            self._s = {}
        async def get(self, k): return self._s.get(k)
        async def set(self, k, v, ex=0): self._s[k] = str(v)
        async def delete(self, *keys):
            for k in keys: self._s.pop(k, None)

    class _PacksResult:
        def __init__(self, packs):
            self._packs = list(packs)
        def scalars(self): return self
        def all(self): return list(self._packs)

    class _DB:
        def __init__(self, user, rows, packs=None):
            self._user = user
            self._rows = list(rows)
            self._packs = list(packs or [])
            self.added = []
        async def execute(self, _stmt):
            try:
                froms = (
                    _stmt.get_final_froms()
                    if hasattr(_stmt, "get_final_froms")
                    else _stmt.froms
                )
                if any(
                    getattr(from_, "name", None)
                    in ("stripe_credit_packs", "billing_credit_packs")
                    for from_ in froms
                ):
                    return _PacksResult(self._packs)
            except AttributeError:
                pass
            return self
        def scalars(self): return self
        def all(self): return list(self._rows)
        def scalar_one(self): return sum(r.amount for r in self._rows)
        def scalar_one_or_none(self): return self._user
        def add(self, obj):
            if isinstance(obj, CreditLedger):
                if not hasattr(obj, "id") or obj.id is None:
                    obj.id = uuid4()
                self._rows.append(obj)
            self.added.append(obj)
        async def flush(self): pass
        async def commit(self): pass

    import asyncio

    async def _run():
        user_id = uuid4()
        svc = CreditService(redis_client=_Redis())
        user = User(
            id=user_id,
            email=f"{user_id}@example.com",
            google_id=f"google-{user_id}",
            credit_balance=100,
        )
        ledger = [CreditLedger(id=uuid4(), user_id=user_id, amount=100, reason="signup")]
        db = _DB(user, ledger)

        # First deduction — must succeed
        e1 = await svc.deduct(db, user_id, 10, "generate")
        assert e1.amount == -10, "First deduction must succeed"

        # Second deduction with identical reason — must also succeed
        e2 = await svc.deduct(db, user_id, 10, "generate")
        assert e2.amount == -10, (
            "Second deduction with reason='generate' failed. "
            "The UNIQUE(user_id, reason) constraint in migration 0003 prevents "
            "repeat operations. Fix: use a partial index scoped to refund rows."
        )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# T-115 — H-3: Docker Compose API port must not be exposed on all interfaces
# ---------------------------------------------------------------------------


def test_compose_does_not_expose_api_port_on_all_interfaces() -> None:
    """The API service port in docker-compose.yml must be bound to localhost.

    Exposing :8000 without a host binding lets any host on the network hit
    the API directly, bypassing any intended reverse-proxy layer. Datastores
    (postgres, redis) are already correctly bound to 127.0.0.1 — the API
    service must follow the same convention for self-hosted deployments.
    """
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    # Fail if the API service uses a bare port mapping that listens on 0.0.0.0
    assert '"8000:8000"' not in compose, (
        "docker-compose.yml exposes the API port 8000 on all interfaces. "
        "Change to '127.0.0.1:8000:8000' so the API is only reachable via "
        "a reverse proxy in self-hosted deployments."
    )


# ---------------------------------------------------------------------------
# T-116 — H-4: FastAPI docs must be disabled in production
# ---------------------------------------------------------------------------


def test_fastapi_docs_are_disabled_in_production() -> None:
    """create_app() must disable /docs and /redoc when environment is production.

    The auto-generated Swagger UI enumerates the full API surface including
    all parameters, schemas, and endpoints. In production this should be
    inaccessible to unauthenticated users.

    Acceptable implementations:
    - Pass docs_url=None and redoc_url=None to FastAPI() when environment==production
    - Guard both endpoints behind auth
    """
    main_source = read_backend_file("main.py")

    # Look for explicit disabling of docs in production context
    docs_disabled = (
        "docs_url=None" in main_source
        or "redoc_url=None" in main_source
        or (
            "docs_url" in main_source
            and ("production" in main_source or "environment" in main_source)
        )
    )

    assert docs_disabled, (
        "FastAPI docs (/docs, /redoc) are not disabled in production. "
        "Pass docs_url=None, redoc_url=None to FastAPI() when "
        "settings.environment == 'production', or gate both endpoints "
        "behind authentication."
    )


def test_fastapi_app_does_not_expose_openapi_schema_in_production() -> None:
    """When environment=production, /openapi.json must also be suppressed."""
    main_source = read_backend_file("main.py")

    openapi_disabled = (
        "openapi_url=None" in main_source
        or (
            "openapi_url" in main_source
            and ("production" in main_source or "environment" in main_source)
        )
    )

    assert openapi_disabled, (
        "FastAPI's /openapi.json schema endpoint is not disabled in production. "
        "Pass openapi_url=None to FastAPI() when environment == 'production'."
    )


# ---------------------------------------------------------------------------
# T-117 — H-2: Production startup validation must cover critical secrets
# ---------------------------------------------------------------------------


def _validate_fn_body(config_source: str) -> str:
    """Extract only the lines inside validate_production_settings()."""
    lines = config_source.splitlines()
    inside = False
    body: list[str] = []
    for line in lines:
        if re.match(r"^def validate_production_settings\b", line):
            inside = True
        elif inside and line and not line[0].isspace():
            break
        if inside:
            body.append(line)
    return "\n".join(body)


def test_production_validation_checks_jwt_key_strength() -> None:
    """validate_production_settings() must reject obviously-weak JWT keys.

    A deploy with JWT_PRIVATE_KEY='ci-test-private-key' should fail the
    production startup check. The validator must confirm the private key
    starts with the PEM header that indicates a real RSA/EC key.
    """
    config_source = read_backend_file("config.py")
    fn_body = _validate_fn_body(config_source)

    assert fn_body, "validate_production_settings() must exist in config.py"

    # The function body must reference the jwt_private_key setting AND
    # the '-----BEGIN' PEM marker that distinguishes real keys from stubs.
    has_jwt_check = (
        "jwt_private_key" in fn_body.lower()
        and "-----BEGIN" in fn_body
    )

    assert has_jwt_check, (
        "validate_production_settings() does not verify JWT_PRIVATE_KEY strength. "
        "Add a check inside the function that settings.jwt_private_key starts with "
        "'-----BEGIN' to reject CI stub keys at production startup."
    )


def test_production_validation_checks_encryption_key_is_not_default() -> None:
    """validate_production_settings() must reject the CI placeholder encryption key.

    ENCRYPTION_MASTER_KEY='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=' is
    the CI fixture value. Deploying to production with this key means all
    encrypted user data uses a publicly known key.
    """
    config_source = read_backend_file("config.py")
    fn_body = _validate_fn_body(config_source)

    assert fn_body, "validate_production_settings() must exist in config.py"

    # The function body must reference encryption_master_key AND either the
    # literal CI placeholder string or a named constant that holds it
    # (defined at module level).
    literal_in_fn = (
        "encryption_master_key" in fn_body.lower()
        and "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" in fn_body
    )
    constant_in_fn = (
        "encryption_master_key" in fn_body.lower()
        and "_CI_ENCRYPTION_KEY" in fn_body
        and "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" in config_source
    )
    has_encryption_check = literal_in_fn or constant_in_fn

    assert has_encryption_check, (
        "validate_production_settings() does not check ENCRYPTION_MASTER_KEY. "
        "Add a check inside the function that rejects the known CI placeholder "
        "value 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=' at production startup."
    )


# ---------------------------------------------------------------------------
# T-118 — H-1: Rate limiter count check must be atomic
# ---------------------------------------------------------------------------


def test_rate_limiter_uses_atomic_count_before_add() -> None:
    """sliding_window_check must evaluate the count before adding the request.

    Current implementation adds the member (ZADD) then reads the count (ZCARD),
    so concurrent requests can all exceed the limit simultaneously before any
    rejection fires. The correct order is ZCARD-then-ZADD or a Lua script that
    does both atomically.

    Acceptable implementations:
    1. Lua script that checks count, conditionally adds, returns result atomically.
    2. Check ZCARD before ZADD in the pipeline (check-then-add with cleanup on reject).
    """
    source = read_backend_file("middleware", "rate_limit.py")

    uses_lua = "lua" in source.lower() or "eval" in source.lower() or "register_script" in source.lower()
    uses_check_before_add = bool(
        re.search(
            r"zcard.*zadd|ZCARD.*ZADD",
            source,
            re.IGNORECASE | re.DOTALL,
        )
    )

    assert uses_lua or uses_check_before_add, (
        "sliding_window_check adds the request (ZADD) before checking the count "
        "(ZCARD). Under concurrent load this allows ~2× the configured rate limit "
        "to slip through before any rejection fires. "
        "Fix: use a Lua script that checks the count atomically before adding, "
        "or reorder to ZCARD → conditional ZADD."
    )


# ---------------------------------------------------------------------------
# T-119 — M-2: Migrations must run before the app starts in Docker
# ---------------------------------------------------------------------------


def test_docker_compose_or_dockerfile_runs_migrations_on_startup() -> None:
    """The Docker stack must run 'alembic upgrade head' before starting uvicorn.

    Without this, a fresh deployment against an empty database or a re-deploy
    after a schema migration will start the app against a stale schema, causing
    silent query failures rather than a clear error at boot.

    Acceptable locations:
    - docker-compose.yml api.command contains 'alembic upgrade head'
    - backend/Dockerfile CMD or ENTRYPOINT runs migrations
    - A dedicated entrypoint script (entrypoint.sh) that runs migrations first
    """
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile_path = REPO_ROOT / "backend" / "Dockerfile"
    entrypoint_path = REPO_ROOT / "backend" / "entrypoint.sh"

    compose_migrates = "alembic upgrade head" in compose
    dockerfile_migrates = (
        dockerfile_path.exists()
        and "alembic upgrade head" in dockerfile_path.read_text(encoding="utf-8")
    )
    entrypoint_migrates = (
        entrypoint_path.exists()
        and "alembic upgrade head" in entrypoint_path.read_text(encoding="utf-8")
    )

    assert compose_migrates or dockerfile_migrates or entrypoint_migrates, (
        "Neither docker-compose.yml, backend/Dockerfile, nor backend/entrypoint.sh "
        "runs 'alembic upgrade head' before starting the application. "
        "Add it to the api service command in docker-compose.yml:\n"
        "  command: sh -c 'uv run alembic upgrade head && uv run uvicorn main:app ...'"
    )


# ---------------------------------------------------------------------------
# T-120 — M-4: Recovery service must not hardcode credit costs
# ---------------------------------------------------------------------------


def test_recovery_service_uses_credit_costs_constant() -> None:
    """recover_stuck_stages() must reference CREDIT_COSTS, not a hardcoded integer.

    If the generation cost changes (e.g. from 10 to 15 credits), hardcoded
    integers in the recovery service log misleading information — the actual
    refund via credit_service.refund() is correct (it uses the original ledger
    entry), but the log line reports the wrong amount.
    """
    source = read_backend_file("services", "pipeline", "recovery_service.py")

    has_hardcoded_cost = bool(
        re.search(
            r"credits_refunded\s*=\s*10\b",
            source,
        )
    )

    assert not has_hardcoded_cost, (
        "recovery_service.py hardcodes 'credits_refunded = 10' instead of "
        "referencing CREDIT_COSTS['generate']. Import CREDIT_COSTS from "
        "services.pipeline.stage_manager and use CREDIT_COSTS['generate'] "
        "so the log value stays in sync if the cost changes."
    )
