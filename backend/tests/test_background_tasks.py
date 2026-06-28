"""Tests for the F6 bounded background-task registry (scalability audit)."""

from __future__ import annotations

import asyncio
import gc

import pytest

from services.pipeline.background_tasks import (
    BoundedTaskRegistry,
    build_advisory_semaphore,
)


async def test_spawn_registers_then_self_removes_and_publishes_gauge() -> None:
    published: list[tuple[str, int]] = []
    reg = BoundedTaskRegistry(
        "t", error_event="boom", gauge_setter=lambda n, c: published.append((n, c))
    )
    started = asyncio.Event()

    async def work() -> str:
        started.set()
        return "ok"

    task = reg.spawn(work())
    # Registered synchronously at spawn, before the coroutine has run.
    assert len(reg) == 1
    assert task in reg
    result = await task
    assert result == "ok"
    # Done-callback removes it and republishes 0.
    await asyncio.sleep(0)
    assert len(reg) == 0
    assert published[0] == ("t", 0)  # gauge published at construction
    assert ("t", 1) in published  # bumped on spawn
    assert published[-1] == ("t", 0)  # back to 0 after self-removal


async def test_detached_task_survives_dropped_reference() -> None:
    """The registry's strong ref keeps a task alive when the caller drops it."""
    reg = BoundedTaskRegistry("gc", error_event="boom")
    ran = asyncio.Event()

    async def work() -> None:
        await asyncio.sleep(0.02)
        ran.set()

    reg.spawn(work())  # return value deliberately not held
    del_target = None  # nothing references the task but the registry
    gc.collect()
    await asyncio.wait_for(ran.wait(), timeout=1.0)
    assert del_target is None  # (silence linters; the point is `ran` fired)


async def test_failing_task_is_removed_and_swallowed(monkeypatch) -> None:
    errors: list[tuple] = []
    from services.pipeline import background_tasks as bt

    monkeypatch.setattr(
        bt.logger, "error", lambda event, **kw: errors.append((event, kw))
    )
    reg = BoundedTaskRegistry("e", error_event="eval_background_failed")

    async def boom() -> None:
        raise ValueError("nope")

    task = reg.spawn(boom())
    # The failure must not propagate to anyone but the done-callback logger.
    with pytest.raises(ValueError):
        await task
    await asyncio.sleep(0)
    assert len(reg) == 0
    assert errors and errors[0][0] == "eval_background_failed"


async def test_cancelled_task_does_not_log_error(monkeypatch) -> None:
    errors: list = []
    from services.pipeline import background_tasks as bt

    monkeypatch.setattr(bt.logger, "error", lambda event, **kw: errors.append(event))
    reg = BoundedTaskRegistry("c", error_event="boom")

    async def forever() -> None:
        await asyncio.sleep(10)

    task = reg.spawn(forever())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert len(reg) == 0
    assert errors == []  # cancellation is not an error


async def test_advisory_semaphore_bounds_concurrency() -> None:
    sem = build_advisory_semaphore(1)
    assert isinstance(sem, asyncio.Semaphore)
    reg = BoundedTaskRegistry("s", error_event="boom", semaphore=sem)
    concurrent = 0
    peak = 0
    release = asyncio.Event()

    async def work() -> None:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await release.wait()
        concurrent -= 1

    t1 = reg.spawn(work())
    t2 = reg.spawn(work())
    # Both registered, but only one may run while the semaphore (size 1) is held.
    await asyncio.sleep(0.01)
    assert len(reg) == 2
    assert peak == 1
    release.set()
    await asyncio.gather(t1, t2)
    assert peak == 1  # never two at once


def test_build_advisory_semaphore_disabled_returns_none() -> None:
    assert build_advisory_semaphore(0) is None
    assert build_advisory_semaphore(-3) is None


async def test_soft_max_high_water_warns_once(monkeypatch) -> None:
    warnings: list[dict] = []
    from services.pipeline import background_tasks as bt

    monkeypatch.setattr(
        bt.logger,
        "warning",
        lambda event, **kw: warnings.append({"event": event, **kw}),
    )
    reg = BoundedTaskRegistry("hw", error_event="boom", soft_max=2)
    release = asyncio.Event()

    async def block() -> None:
        await release.wait()

    tasks = [reg.spawn(block()) for _ in range(4)]
    await asyncio.sleep(0)
    # Crossed soft_max=2 → exactly one high-water warning (one-shot).
    hw = [w for w in warnings if w["event"] == "background_tasks_high_water"]
    assert len(hw) == 1
    assert hw[0]["registry"] == "hw" and hw[0]["soft_max"] == 2
    release.set()
    await asyncio.gather(*tasks)


async def test_registry_is_iterable_and_len_drop_in_for_set() -> None:
    reg = BoundedTaskRegistry("i", error_event="boom")
    release = asyncio.Event()

    async def block() -> None:
        await release.wait()

    spawned = [reg.spawn(block()) for _ in range(3)]
    assert len(list(reg)) == 3  # iterable like the bare set it replaces
    assert all(t in reg for t in spawned)
    release.set()
    await asyncio.gather(*spawned)
