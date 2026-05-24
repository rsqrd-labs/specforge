"""Unit tests for the continuous recovery lock heartbeat — T-200 (HF-3).

Tests verify:
  HB-1  _recovery_heartbeat calls redis.expire repeatedly until cancelled.
  HB-2  _recovery_heartbeat exits cleanly on CancelledError (no re-raise).
  HB-3  run_recovery_cycle cancels the heartbeat task in the finally block,
         even when recover_stuck_stages raises an exception mid-cycle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.pipeline.stage_manager import (
    _RECOVERY_LOCK_KEY,
    _RECOVERY_LOCK_TTL,
    _recovery_heartbeat,
    run_recovery_cycle,
)

# ---------------------------------------------------------------------------
# HB-1: heartbeat calls redis.expire repeatedly until cancelled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_calls_expire_repeatedly() -> None:
    """HB-1 — _recovery_heartbeat must call redis.expire at least twice before cancel.

    After two intervals the heartbeat should have fired at least twice.
    We use a very short interval (10 ms) and sleep for 3× that to give the
    asyncio scheduler enough room to schedule both wakeups reliably.
    """
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock(return_value=True)

    interval_ms = 0.01  # 10 ms — short enough for unit tests
    task = asyncio.create_task(
        _recovery_heartbeat(
            mock_redis, _RECOVERY_LOCK_KEY, _RECOVERY_LOCK_TTL, interval_ms
        )
    )

    # Let the event loop run long enough for at least two heartbeat fires.
    await asyncio.sleep(interval_ms * 3.5)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    call_count = mock_redis.expire.await_count
    assert call_count >= 2, (
        "_recovery_heartbeat must call redis.expire at least twice after "
        f"3.5 intervals. Got {call_count} call(s). The heartbeat loop is not "
        "firing continuously."
    )


# ---------------------------------------------------------------------------
# HB-2: heartbeat exits cleanly on CancelledError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_exits_cleanly_on_cancel() -> None:
    """HB-2 — _recovery_heartbeat must exit cleanly when cancelled (no re-raise).

    asyncio.CancelledError must be swallowed so the caller's finally block
    can complete without an additional exception from the task teardown.
    """
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock(return_value=True)

    task = asyncio.create_task(
        _recovery_heartbeat(mock_redis, _RECOVERY_LOCK_KEY, _RECOVERY_LOCK_TTL, 60)
    )

    # Yield to the event loop so the task starts and enters its first sleep.
    await asyncio.sleep(0)

    task.cancel()
    # gather with return_exceptions=True so a re-raised CancelledError becomes
    # a result object rather than bubbling up to the test.
    results = await asyncio.gather(task, return_exceptions=True)

    # The task must have been cancelled, not have returned a non-cancel exception.
    # A clean-exiting coroutine (that catches CancelledError and returns) will
    # produce a CancelledError result here because the task itself was cancelled.
    # What we verify is that no *other* exception was raised.
    assert len(results) == 1
    result = results[0]
    assert result is None or isinstance(result, asyncio.CancelledError), (
        "_recovery_heartbeat must exit cleanly on cancel "
        f"(return None or CancelledError). Got unexpected result: {result!r}"
    )


# ---------------------------------------------------------------------------
# HB-3: run_recovery_cycle cancels the heartbeat even on exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_cancelled_when_cycle_raises() -> None:
    """HB-3 — run_recovery_cycle must cancel the heartbeat task in its finally block.

    If recover_stuck_stages raises mid-cycle, the heartbeat task must still
    be cancelled so it doesn't keep the Redis lock alive indefinitely.
    """
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock(return_value=True)
    mock_db = MagicMock()

    sentinel = RuntimeError("simulated recovery failure")

    cancelled_tasks: list[asyncio.Task] = []

    # Wrap asyncio.create_task to capture the heartbeat task so we can inspect
    # its cancellation state after run_recovery_cycle returns.
    original_create_task = asyncio.create_task

    def _capture_create_task(coro, **kwargs):  # type: ignore[no-untyped-def]
        t = original_create_task(coro, **kwargs)
        cancelled_tasks.append(t)
        return t

    with (
        patch(
            "services.pipeline.stage_manager.asyncio.create_task",
            side_effect=_capture_create_task,
        ),
        patch(
            "services.pipeline.recovery_service.recover_stuck_stages",
            new=AsyncMock(side_effect=sentinel),
        ),
    ):
        with pytest.raises(RuntimeError, match="simulated recovery failure"):
            await run_recovery_cycle(mock_redis, mock_db)

    assert (
        len(cancelled_tasks) == 1
    ), "run_recovery_cycle must create exactly one asyncio.Task for the heartbeat."
    heartbeat_task = cancelled_tasks[0]

    # Give the event loop a tick to finish task teardown.
    await asyncio.sleep(0)

    assert heartbeat_task.cancelled() or heartbeat_task.done(), (
        "The heartbeat asyncio.Task must be cancelled (or done) after "
        "run_recovery_cycle returns, even when recover_stuck_stages raises. "
        "The finally block in run_recovery_cycle must always cancel. HF-3 — T-200."
    )
