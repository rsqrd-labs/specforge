"""Offload CPU-bound, GIL-holding work off the event loop (F7 — scalability audit P2).

``bleach.clean``, the full-document regex validators (``output_validator``,
``prompt_guard``, ``artifact_validator``) and ``difflib``'s ``SequenceMatcher``
all run synchronously and hold the GIL. On a multi-KB-to-200KB LLM artifact a
single inline pass can stall the asyncio event loop for many milliseconds,
blocking every peer coroutine on the same worker (only ``WEB_CONCURRENCY`` of
them — audit §F4/§F7).

Each of these is a *many-small-operations* workload (per-pattern ``.search``,
per-section/line loops, html5lib's pure-Python tokenizer), so the GIL is released
at the interpreter switch interval and a worker thread lets the loop interleave
peers between hand-offs — turning one long contiguous stall into short, fairly
scheduled slices. (A single catastrophic-backtracking regex would *not* benefit;
these patterns are all linear/anchored, so offload is the right tool here.)

The work runs on a small, dedicated bounded thread pool — **not** the default
executor — so a CPU burst cannot starve the Langfuse / PDF I/O offload that also
uses threads (mirroring ``pdf_export_service``). The pool is deliberately small:
extra threads cannot win back wall-clock on GIL-bound work and only add scheduling
contention.

A size gate (``cpu_offload_min_chars``) keeps small inputs inline: the thread
round-trip costs more than a short pass, so only genuinely large payloads pay for
offload. Callers pass the dominant string input as ``sizer``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import threading
from typing import Callable, TypeVar

from config import settings

T = TypeVar("T")

# Lazily-built, process-wide dedicated pool. Built on first use (not at import)
# so a test that mutates ``cpu_offload_max_workers`` before the first offload
# still gets its size, and so module import never spawns threads.
_CPU_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_CPU_EXECUTOR_LOCK = threading.Lock()


def _new_cpu_executor() -> concurrent.futures.ThreadPoolExecutor:
    return concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, settings.cpu_offload_max_workers),
        thread_name_prefix="cpu-offload",
    )


def _get_cpu_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return a live CPU-offload pool, recreating it after a test-client shutdown.

    Mirrors ``pdf_export_service._get_pdf_executor``: a FastAPI test client's
    lifespan teardown calls :func:`shutdown_cpu_executor`, and a later test would
    otherwise hit ``RuntimeError: cannot schedule new futures after shutdown``.
    The recreate guard keeps the helper usable across app restarts in one process.
    """
    global _CPU_EXECUTOR
    with _CPU_EXECUTOR_LOCK:
        if _CPU_EXECUTOR is None or getattr(_CPU_EXECUTOR, "_shutdown", False):
            _CPU_EXECUTOR = _new_cpu_executor()
        return _CPU_EXECUTOR


def shutdown_cpu_executor() -> None:
    """Shut the CPU-offload pool down on process exit (FastAPI lifespan).

    ``wait=False`` lets the lifespan exit immediately; threads drain naturally at
    interpreter exit. Idempotent — safe to call when the pool was never built.
    """
    with _CPU_EXECUTOR_LOCK:
        if _CPU_EXECUTOR is not None:
            _CPU_EXECUTOR.shutdown(wait=False)


async def run_cpu_bound(
    sizer: str,
    func: Callable[..., T],
    /,
    *args: object,
    **kwargs: object,
) -> T:
    """Run ``func(*args, **kwargs)``, offloading to the CPU pool when large.

    ``sizer`` is the dominant string input (the LLM artifact / document). Below
    ``settings.cpu_offload_min_chars`` the call runs **inline** — the
    thread-dispatch round-trip would dominate a short pass — and at or above it the
    call is dispatched to the dedicated bounded pool so the event loop can
    interleave peers during the GIL hand-offs.

    Exceptions raised by ``func`` propagate unchanged: the validators raise
    (``MissingSectionError`` / ``IncompleteArtifactError`` / ``SecurityError`` via
    the caller), and ``run_in_executor`` re-raises in the awaiting coroutine, so
    that contract is identical to calling ``func`` directly.
    """
    if len(sizer) < settings.cpu_offload_min_chars:
        return func(*args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _get_cpu_executor(), functools.partial(func, *args, **kwargs)
    )
