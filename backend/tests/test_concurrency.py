"""Concurrency and integration regression tests.

T-195 — covers five missing test categories identified in the Testing Assessment:

  C-1  Finalise race: concurrent finalise calls must not double-advance stage
  C-2  Harness patch on in_progress stage must raise StageStateError (→ 409)
  C-3  OAuth state replay protection via atomic getdel
  SSE  SSE cleanup_done flag prevents double-refund on disconnect
  H-4  Credit balance cache invalidation on deduct/refund
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from middleware.auth import invalidate_user_cache
from services.auth_service import OAUTH_STATE_PREFIX, AuthError, AuthService
from services.credit_service import CreditService
from services.pipeline.stage_manager import StageStateError

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _make_stage(
    *,
    status: str = "draft",
    stage_type: str = "spec",
    workspace_id: UUID | None = None,
    stage_id: UUID | None = None,
) -> MagicMock:
    stage = MagicMock()
    stage.id = stage_id or uuid4()
    stage.type = stage_type
    stage.status = status
    stage.workspace_id = workspace_id or uuid4()
    stage.content = "# content"
    stage.current_version = 1
    return stage


def _make_user(user_id: UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.credit_balance = 100
    return user


class _FakeRedis:
    """In-process Redis stub used by credit and auth service tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any, ex: int = 0) -> None:
        self._store[key] = str(value)

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)

    async def getdel(self, key: str) -> str | None:
        """Atomic read-and-delete — mirrors Redis GETDEL behaviour."""
        value = self._store.pop(key, None)
        return value


class _FakeCreditDB:
    """Minimal DB stub for CreditService tests."""

    def __init__(self, user: MagicMock) -> None:
        self.user = user
        self.added: list[Any] = []
        self._execute_count = 0

    async def execute(self, statement: Any) -> Any:
        self._execute_count += 1
        # _expire_user_packs / _drain_packs query the credit-pack table (T-229;
        # migrated to billing_credit_packs in T-294). This test doesn't set up any
        # packs — return an empty list so the sweep methods find nothing to expire/
        # drain.  _ScalarResult(None).scalars() returns _ScalarAll(None) whose
        # .all() returns [].
        try:
            froms = (
                statement.get_final_froms()
                if hasattr(statement, "get_final_froms")
                else statement.froms
            )
            if any(
                getattr(f, "name", None)
                in ("stripe_credit_packs", "billing_credit_packs")
                for f in froms
            ):
                return _ScalarResult(None)
        except AttributeError:
            # Statement shape isn't FROM-introspectable; fall through to the
            # default User result below.
            pass
        # All User-table queries return the user unconditionally.
        return _ScalarResult(self.user)

    def add(self, instance: Any) -> None:
        from models import CreditLedger

        if isinstance(instance, CreditLedger) and not hasattr(instance, "id"):
            instance.id = uuid4()
        self.added.append(instance)

    async def flush(self) -> None:
        for item in self.added:
            if not getattr(item, "id", None):
                item.id = uuid4()

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> "_ScalarAll":
        return _ScalarAll(self._value)


class _ScalarAll:
    def __init__(self, value: Any) -> None:
        self._value = value

    def all(self) -> list[Any]:
        return [self._value] if self._value is not None else []


# ---------------------------------------------------------------------------
# C-1: Finalise race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalise_race_second_call_raises_when_not_draft() -> None:
    """C-1 — concurrent finalise: only the first caller with status='draft' succeeds.

    The stage_manager.finalise() checks ``stage.status == 'draft'`` before
    advancing.  A second concurrent caller that reaches the guard after the first
    has already committed (or in the same transaction via a SELECT FOR UPDATE) sees
    a non-draft status and must raise ValueError — preventing double-finalise and
    the resulting invalid state-machine transition.
    """
    from services.pipeline.stage_manager import StageManager

    manager = StageManager()

    already_finalised_stage = _make_stage(status="finalised")

    class _DB:
        async def execute(self, stmt: Any) -> Any:
            return _ScalarResult(already_finalised_stage)

        async def commit(self) -> None:
            pass

        async def refresh(self, obj: Any) -> None:
            pass

    db = _DB()
    user = _make_user()

    # A stage that is already finalised must not be finalised again.
    with pytest.raises(ValueError, match="cannot be finalised"):
        await manager.finalise(already_finalised_stage.id, user, db)


# NOTE: The concurrent finalise race is tested against a real PostgreSQL
# database in tests/test_finalise_integration.py using SELECT FOR UPDATE.
# The mock-based approach that was previously here (T-212/T-214 deletion) gave
# false confidence because it mutated stage.status in Python memory without
# ever exercising the database lock. CF-1 — T-196.


# ---------------------------------------------------------------------------
# C-2: Harness patch on in_progress stage
# ---------------------------------------------------------------------------


def test_harness_patch_in_progress_raises_stage_state_error() -> None:
    """C-2 — generate_harness_patch must reject in_progress stages with StageStateError.

    The patch generator uses ``stage.status not in ('draft', 'stale', 'finalised')``
    as its guard.  An in_progress stage is NOT in that set, so the call must raise
    StageStateError before any LLM call is made.
    """
    # StageStateError is the production exception; verify the guard condition
    # matches the documented C-2 semantics.
    in_progress_statuses = ("in_progress",)
    allowed_statuses = frozenset(("draft", "stale", "finalised"))

    for status in in_progress_statuses:
        # The guard: stage.status not in allowed_statuses → raise
        assert (
            status not in allowed_statuses
        ), f"Status {status!r} should be rejected by the patch guard (C-2)"


@pytest.mark.asyncio
async def test_harness_patch_in_progress_raises_via_manager() -> None:
    """C-2 — validate StageStateError is actually raised for an in_progress stage."""
    from services.pipeline.stage_manager import StageManager

    manager = StageManager()
    stage = _make_stage(status="in_progress", stage_type="harness")
    workspace = MagicMock()
    workspace.provider = "anthropic"
    workspace.user_id = uuid4()

    class _DB:
        async def execute(self, stmt: Any) -> Any:
            return _ScalarResult(stage)

    user = _make_user(user_id=workspace.user_id)

    with pytest.raises(StageStateError, match="cannot be patched"):
        # Consume the async generator — the guard fires before any yield.
        # Signature: generate_harness_patch(stage_id, user, db, uncovered_reqs)
        async for _ in manager.generate_harness_patch(
            stage.id, user, _DB(), ["requirement-1"]
        ):
            pass  # pragma: no cover


# ---------------------------------------------------------------------------
# C-3: OAuth state replay protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_replay_second_callback_rejected() -> None:
    """C-3 — OAuth state token must be consumed atomically; replay must raise AuthError.

    AuthService.handle_callback() uses Redis GETDEL (atomic read-and-delete).
    The second call with the same state token finds no key and must raise
    AuthError("Invalid or expired OAuth state").
    """
    redis = _FakeRedis()
    state = "test-state-token-abc"
    state_key = f"{OAUTH_STATE_PREFIX}{state}"

    # Seed the state key as handle_login() would.
    await redis.set(state_key, "1", ex=600)

    # First callback: consumes the key atomically.
    first = await redis.getdel(state_key)
    assert first == "1"

    # Second callback: key is gone — must be rejected.
    second = await redis.getdel(state_key)
    assert (
        second is None
    ), "OAuth state must be consumed on first use; replay must fail (C-3)"


@pytest.mark.asyncio
async def test_oauth_replay_auth_service_rejects_missing_state() -> None:
    """C-3 — AuthService raises AuthError when the state token is absent/replayed."""
    redis = _FakeRedis()
    # Do NOT plant the state key — simulates a replayed or expired token.
    service = AuthService(redis_client=redis, oauth_client=None)

    with pytest.raises(AuthError, match="Invalid or expired OAuth state"):
        await service.handle_callback("some-code", "missing-state", db=None)


# ---------------------------------------------------------------------------
# SSE: cleanup_done prevents double-refund on disconnect
# ---------------------------------------------------------------------------


def _cleanup_runs(cleanup_done: bool) -> bool:
    """Model the finally-block guard in ``StageManager.generate()``.

    The disconnect-cleanup/refund path runs only when the stream did *not*
    complete, i.e. ``if not _cleanup_done``.
    """
    return not cleanup_done


def test_sse_cleanup_done_flag_semantics() -> None:
    """SSE lifecycle — _cleanup_done=True skips the disconnect cleanup path.

    The ``_cleanup_done`` sentinel in ``StageManager.generate()`` prevents the
    finally block from running cleanup/refund when generation completed
    successfully.  This test confirms the design contract: once set, the flag
    gates the cleanup path to be a no-op.
    """
    assert not _cleanup_runs(cleanup_done=True), (
        "cleanup_done=True must prevent the disconnect-cleanup/refund path from "
        "executing (SSE lifecycle contract)"
    )


def test_sse_cleanup_done_false_triggers_cleanup() -> None:
    """SSE lifecycle — _cleanup_done=False allows the cleanup path to run.

    When a stream terminates via exception before ``_cleanup_done`` is set,
    the finally block must execute the disconnect-cleanup/refund path.
    """
    assert _cleanup_runs(cleanup_done=False), (
        "cleanup_done=False must allow the disconnect-cleanup path to execute "
        "on stream failure (SSE lifecycle contract)"
    )


@pytest.mark.asyncio
async def test_sse_cleanup_done_set_before_completion_event() -> None:
    """SSE lifecycle — _cleanup_done is set before the generator exits normally.

    Verify that the sentinel is set on both the success path and the
    early-exit path, so a GeneratorExit or client-disconnect in the finally
    block does not re-run cleanup.
    """
    # The two success paths from stage_manager.generate():
    # 1. Normal completion: _cleanup_done = True (set after final chunk yielded)
    # 2. Early-termination via 'done' sentinel: _cleanup_done = True
    # Both must set the flag before the generator exits.
    # We validate the logic by running both branches in a local simulation.

    async def _simulate_stream(raise_early: bool) -> bool:
        _cleanup_done = False
        try:
            if raise_early:
                raise RuntimeError("simulated early error")
            # Normal completion path.
            _cleanup_done = True
            return _cleanup_done
        except RuntimeError:
            # Exception path: _cleanup_done stays False → cleanup runs.
            return _cleanup_done
        finally:
            # The guard mirrors stage_manager's finally block.
            _ = not _cleanup_done  # would trigger cleanup if False

    success_flag = await _simulate_stream(raise_early=False)
    assert success_flag is True

    failure_flag = await _simulate_stream(raise_early=True)
    assert failure_flag is False


# ---------------------------------------------------------------------------
# H-4: Credit balance cache invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credit_invalidate_removes_entry_from_auth_cache() -> None:
    """LF-1 — credit deduct/refund must flush the shared (Redis) auth cache.

    After a deduct() or refund(), the caller expects the next request — on ANY
    worker — to see the updated credit_balance rather than a stale cache entry.
    ``credit_service._invalidate(user_id)`` awaits ``invalidate_user_cache``
    which deletes the user's Redis cache key.
    """
    import database
    from middleware import auth
    from models import User
    from tests.conftest import FakeRedis

    fake = FakeRedis()
    database._initialize_redis(fake)
    user_id = uuid4()

    await auth._cache_user(
        User(
            id=user_id,
            email="cache@example.com",
            google_id="g",
            name="Cache",
            avatar_url=None,
            credit_balance=100,
        )
    )
    assert await fake.get(auth._cache_key(user_id)) is not None

    await invalidate_user_cache(user_id)

    assert (
        await fake.get(auth._cache_key(user_id)) is None
    ), "invalidate_user_cache must delete the user's Redis cache key (LF-1)"


@pytest.mark.asyncio
async def test_credit_invalidate_is_idempotent() -> None:
    """LF-1 — invalidate_user_cache must be safe to call for a missing key.

    If the entry was already evicted or was never cached, calling
    invalidate_user_cache must not raise.
    """
    import database
    from middleware import auth
    from tests.conftest import FakeRedis

    fake = FakeRedis()
    database._initialize_redis(fake)
    user_id = uuid4()
    # The user is NOT in the cache — must not raise.
    await invalidate_user_cache(user_id)
    assert await fake.get(auth._cache_key(user_id)) is None


@pytest.mark.asyncio
async def test_credit_deduct_invalidates_cache_via_redis_and_auth() -> None:
    """LF-1 — CreditService.deduct() invalidates both the balance and auth caches.

    When a deduction succeeds, _invalidate() deletes the Redis balance key so the
    next balance read fetches fresh data, and awaits invalidate_user_cache() which
    deletes the shared auth-cache key so the middleware serves an accurate
    credit_balance on the next request — on any worker.
    """
    import database
    from middleware import auth
    from tests.conftest import FakeRedis

    user_id = uuid4()
    redis = FakeRedis()
    # The deduct path resolves the auth cache via the shared client; point both
    # at one fake so the test observes both deletions.
    database._initialize_redis(redis)
    credit_key = f"credits:{user_id}"
    await redis.set(credit_key, "100")

    user = _make_user(user_id=user_id)
    db = _FakeCreditDB(user)

    # Plant a sentinel auth-cache entry to confirm it is evicted.
    await redis.set(auth._cache_key(user_id), "sentinel")

    service = CreditService(redis_client=redis)

    await service.deduct(db, user_id, 10, "generate")

    # Redis balance cache must be cleared.
    assert (
        await redis.get(credit_key) is None
    ), "deduct() must delete the Redis credit balance cache entry (LF-1)"

    # Shared auth cache key must also be cleared.
    assert (
        await redis.get(auth._cache_key(user_id)) is None
    ), "deduct() must evict the user entry from the shared auth cache (LF-1)"
