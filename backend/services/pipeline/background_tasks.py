"""Bounded background-task registries (F6 — scalability audit).

The generation pipeline spawns detached fire-and-forget tasks: the detached
generation pipeline itself, the best-effort eval score, the off-critical-path
critic, and the Demo-Day construction verifier. Each must outlive a client
disconnect, so a strong reference is held until the task completes — otherwise
the event loop's weak reference lets it be garbage-collected mid-flight.

Previously each of the four was an ad-hoc module-level ``set`` plus a hand-rolled
``add`` / ``add_done_callback(discard)`` / error-logger triple. This module DRYs
that into one registry that additionally:

  - exports the live task count as a gauge (``thought2build_background_tasks``), so a
    runaway fan-out is observable and alertable (audit §6/§8);
  - logs a high-water warning when the count crosses a soft ceiling — a
    back-pressure signal that something upstream of the F1 admission cap is
    leaking tasks rather than self-removing;
  - optionally gates each task behind a SHARED concurrency semaphore so the
    advisory post-``done`` work (eval + critic + verifier) cannot starve live
    generation streams for the provider key / DB pool / event loop. The live
    pipeline tasks are deliberately NOT gated — they are already bounded upstream
    by F1 admission control, and gating them would deadlock generation.

Critical invariant preserved from the original sets: the task is registered
SYNCHRONOUSLY at creation, before any ``await`` yields control, so it can never
be collected in the window between ``create_task`` and registration. The
registry is iterable / ``len()``-able as a drop-in for the bare ``set`` it
replaces.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Gauge publisher signature: (registry_name, live_count) -> None. Injected so the
# registry stays free of a hard observability import (and is trivially testable).
GaugeSetter = Callable[[str, int], None]


class BoundedTaskRegistry:
    """A strong-ref set of detached tasks with metrics, a soft cap, and optional
    shared-semaphore concurrency gating.

    ``soft_max`` is a back-pressure *signal*, not a hard limit: tasks are never
    dropped (advisory work shedding would silently lose eval/critic findings, and
    a dropped pipeline task would lose a paid generation). Crossing it logs a
    one-shot high-water warning that re-arms once the count halves. The true
    bound on how many tasks can exist is F1 admission control upstream, which caps
    the parents that spawn them.
    """

    def __init__(
        self,
        name: str,
        *,
        error_event: str,
        soft_max: int = 0,
        semaphore: asyncio.Semaphore | None = None,
        gauge_setter: GaugeSetter | None = None,
    ) -> None:
        self._name = name
        self._error_event = error_event
        self._soft_max = soft_max
        self._semaphore = semaphore
        self._gauge_setter = gauge_setter
        self._tasks: set[asyncio.Task] = set()
        self._high_water_active = False
        self._publish()

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        """Create, register, and (when configured) rate-gate a detached task.

        Returns the task so the caller can attach further done-callbacks (e.g. the
        pipeline's end-of-stream sentinel). Registration happens before any await
        yields, preserving the GC-safety the original sets provided.
        """
        runnable = self._gated(coro) if self._semaphore is not None else coro
        task = asyncio.create_task(runnable)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        self._publish()
        self._check_high_water()
        return task

    async def _gated(self, coro: Awaitable[Any]) -> Any:
        # The shared advisory semaphore: at most N of these run concurrently, so
        # post-`done` work yields the provider key / DB pool to live streams.
        async with self._semaphore:  # type: ignore[union-attr]
            return await coro

    def _on_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        self._publish()
        if self._high_water_active and len(self._tasks) * 2 <= self._soft_max:
            # Re-arm the one-shot warning once the backlog has clearly drained.
            self._high_water_active = False
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(self._error_event, extra={"error": str(exc)})

    def _check_high_water(self) -> None:
        if self._soft_max <= 0 or self._high_water_active:
            return
        if len(self._tasks) > self._soft_max:
            self._high_water_active = True
            logger.warning(
                "background_tasks_high_water",
                registry=self._name,
                count=len(self._tasks),
                soft_max=self._soft_max,
            )

    def _publish(self) -> None:
        if self._gauge_setter is None:
            return
        try:
            self._gauge_setter(self._name, len(self._tasks))
        except Exception:  # pragma: no cover — metrics must never break the work
            logger.debug("background_tasks_gauge_failed", registry=self._name)

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self) -> Iterator[asyncio.Task]:
        # Snapshot so iteration is safe against concurrent done-callback removal.
        return iter(tuple(self._tasks))

    def __contains__(self, task: object) -> bool:
        return task in self._tasks


def build_advisory_semaphore(limit: int) -> asyncio.Semaphore | None:
    """Shared semaphore for advisory post-``done`` work, or None when unbounded.

    A non-positive ``limit`` returns None ⇒ no gating (exactly the pre-F6
    behaviour, the instant-revert path). asyncio.Semaphore binds to the running
    loop lazily on first contention, so a module-level instance is safe in 3.12.
    """
    return asyncio.Semaphore(limit) if limit > 0 else None
