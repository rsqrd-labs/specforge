"""Unit tests for the dedicated CPU-offload seam (F7 — scalability audit P2).

The seam (``services.cpu_offload.run_cpu_bound``) is what every F7 async wrapper
(``sanitize_text_async``, ``validate_async``, ``scan_async``,
``validate_sections_async``, ``validate_artifact_completeness_async``,
``compute_diff_async``, ``assert_valid_problem_statement_async``) routes through,
so its contract is pinned here once:

  CO-1  the size gate: small inputs run INLINE (caller thread), large inputs run
        on the dedicated ``cpu-offload`` pool (never the default executor);
  CO-2  results and exceptions propagate unchanged through the pool;
  CO-3  the pool is rebuilt after a lifespan shutdown (test-client safety) and
        its size follows ``cpu_offload_max_workers`` clamped to >= 1;
  CO-4  the event loop keeps scheduling peers while offloaded work runs — the
        actual F7 property.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from config import settings
from services import cpu_offload


@pytest.fixture(autouse=True)
def _fresh_cpu_executor():
    """Isolate module-level pool state: each test builds (and drops) its own."""
    cpu_offload.shutdown_cpu_executor()
    cpu_offload._CPU_EXECUTOR = None
    yield
    cpu_offload.shutdown_cpu_executor()
    cpu_offload._CPU_EXECUTOR = None


def _thread_name() -> str:
    return threading.current_thread().name


# ---------------------------------------------------------------------------
# CO-1: size gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_small_input_runs_inline_on_caller_thread(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 4_096)
    caller = _thread_name()

    ran_on = await cpu_offload.run_cpu_bound("short", _thread_name)

    assert ran_on == caller, (
        "An input below cpu_offload_min_chars must run inline — the thread "
        f"dispatch round-trip costs more than a short pass. Ran on {ran_on!r}."
    )


@pytest.mark.asyncio
async def test_large_input_runs_on_dedicated_pool(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 10)

    ran_on = await cpu_offload.run_cpu_bound("x" * 11, _thread_name)

    assert ran_on.startswith("cpu-offload"), (
        "An input at/above cpu_offload_min_chars must run on the dedicated "
        "bounded pool (thread_name_prefix='cpu-offload'), never inline or on "
        f"the default executor. Ran on {ran_on!r}."
    )


@pytest.mark.asyncio
async def test_min_chars_zero_offloads_everything(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)

    ran_on = await cpu_offload.run_cpu_bound("", _thread_name)

    assert ran_on.startswith("cpu-offload"), (
        "cpu_offload_min_chars=0 must offload every call (the documented "
        "force-offload escape hatch)."
    )


@pytest.mark.asyncio
async def test_huge_min_chars_forces_inline_everywhere(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 10**9)
    caller = _thread_name()

    ran_on = await cpu_offload.run_cpu_bound("y" * 100_000, _thread_name)

    assert ran_on == caller, (
        "A huge cpu_offload_min_chars must disable offload entirely (the "
        "documented force-inline escape hatch)."
    )


# ---------------------------------------------------------------------------
# CO-2: results, args/kwargs, and exceptions propagate unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_args_and_kwargs_propagate_through_pool(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)

    def combine(a: str, b: str, *, sep: str = "-") -> str:
        return f"{a}{sep}{b}"

    assert await cpu_offload.run_cpu_bound("size", combine, "L", "R", sep="+") == "L+R"


@pytest.mark.asyncio
async def test_exception_propagates_unchanged_from_pool(monkeypatch) -> None:
    """Validators raise domain exceptions (MissingSectionError etc.); the pool
    must re-raise the exact instance so caller contracts are identical."""
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)

    class DomainError(ValueError):
        pass

    marker = DomainError("boom")

    def raises() -> None:
        raise marker

    with pytest.raises(DomainError) as excinfo:
        await cpu_offload.run_cpu_bound("size", raises)
    assert excinfo.value is marker


# ---------------------------------------------------------------------------
# CO-3: pool lifecycle & sizing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_recreated_after_shutdown(monkeypatch) -> None:
    """Mirrors the PDF executor guard: a FastAPI test client's lifespan teardown
    calls shutdown_cpu_executor(); a later offload must not hit
    'cannot schedule new futures after interpreter shutdown'."""
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)

    assert (await cpu_offload.run_cpu_bound("s", _thread_name)).startswith(
        "cpu-offload"
    )
    cpu_offload.shutdown_cpu_executor()
    assert (await cpu_offload.run_cpu_bound("s", _thread_name)).startswith(
        "cpu-offload"
    )


def test_shutdown_is_idempotent_and_safe_when_never_built() -> None:
    # _fresh_cpu_executor left _CPU_EXECUTOR = None; both calls must be no-ops.
    cpu_offload.shutdown_cpu_executor()
    cpu_offload.shutdown_cpu_executor()


def test_pool_size_follows_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_max_workers", 7)
    assert cpu_offload._new_cpu_executor()._max_workers == 7


def test_pool_size_clamped_to_at_least_one(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cpu_offload_max_workers", 0)
    assert cpu_offload._new_cpu_executor()._max_workers == 1


# ---------------------------------------------------------------------------
# CO-4: the F7 property — the loop keeps scheduling peers during offload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_during_offloaded_work(monkeypatch) -> None:
    """While a 200ms CPU-ish pass runs on the pool, a peer coroutine must keep
    getting scheduled. Inline, the same pass would freeze the loop and the peer
    would tick ~once; offloaded it must tick many times."""
    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    ticks = 0

    async def peer() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    peer_task = asyncio.create_task(peer())
    try:
        # time.sleep releases the GIL like the interpreter's switch interval
        # does between the validators' many small operations.
        await cpu_offload.run_cpu_bound("size", time.sleep, 0.2)
    finally:
        peer_task.cancel()
        try:
            await peer_task
        except asyncio.CancelledError:
            pass

    assert ticks >= 5, (
        f"Peer coroutine ticked only {ticks} times during a 200ms offloaded "
        "pass — the loop was starved, meaning the work ran inline."
    )


# ---------------------------------------------------------------------------
# Shipped defaults (P2). Pinned on the class fields (not the live instance) so
# a local .env cannot mask an accidental default change.
# ---------------------------------------------------------------------------


def test_p2_settings_ship_with_documented_defaults() -> None:
    from config import Settings

    fields = Settings.model_fields
    assert fields["cpu_offload_max_workers"].default == 4
    assert fields["cpu_offload_min_chars"].default == 4_096
    assert fields["pdf_export_max_workers"].default == 2
    assert fields["public_share_cache_ttl_seconds"].default == 60
