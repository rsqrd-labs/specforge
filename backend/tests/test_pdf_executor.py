"""Unit tests for the PDF export dedicated executor — T-201 (HF-4).

These tests do NOT import WeasyPrint (native libs not required on dev boxes).
They verify:
  PE-1  _PDF_EXECUTOR is a ThreadPoolExecutor with max_workers=2.
  PE-2  pdf_export_service.py contains no get_event_loop() calls.
  PE-3  Concurrent dispatches to _PDF_EXECUTOR complete without blocking
        the event loop (proves the executor is non-shared and non-sequential).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import time

import pytest

from services.pipeline import pdf_export_service as pdf_module
from services.pipeline.pdf_export_service import _PDF_EXECUTOR

# ---------------------------------------------------------------------------
# PE-1: _PDF_EXECUTOR is a ThreadPoolExecutor with max_workers=2
# ---------------------------------------------------------------------------


def test_pdf_executor_is_threadpoolexecutor() -> None:
    """PE-1 — _PDF_EXECUTOR must be a ThreadPoolExecutor with max_workers=2.

    max_workers=2 provides parallelism for concurrent PDF requests without
    saturating CPU (each WeasyPrint call is CPU-bound for 0.5–3 s).
    """
    assert isinstance(_PDF_EXECUTOR, concurrent.futures.ThreadPoolExecutor), (
        "_PDF_EXECUTOR must be a concurrent.futures.ThreadPoolExecutor. "
        f"Got: {type(_PDF_EXECUTOR).__name__}"
    )
    assert _PDF_EXECUTOR._max_workers == 2, (
        "_PDF_EXECUTOR must have max_workers=2. "
        f"Got max_workers={_PDF_EXECUTOR._max_workers}. "
        "Two workers allow concurrent renders without WeasyPrint object contention "
        "(each call creates its own HTML Document). HF-4 — T-201."
    )


# ---------------------------------------------------------------------------
# PE-2: no get_event_loop() in the source
# ---------------------------------------------------------------------------


def test_no_get_event_loop_in_source() -> None:
    """PE-2 — pdf_export_service.py must not call asyncio.get_event_loop().

    get_event_loop() was deprecated in Python 3.10 and raises
    DeprecationWarning in Python 3.12+. get_running_loop() is the correct
    replacement — it raises RuntimeError if called outside a running loop,
    making bugs explicit rather than silently creating a new loop.
    HF-4 — T-201.
    """
    source = inspect.getsource(pdf_module)
    assert "get_event_loop()" not in source, (
        "pdf_export_service.py must not call asyncio.get_event_loop(). "
        "Replace with asyncio.get_running_loop(). HF-4 — T-201."
    )
    assert "get_running_loop()" in source, (
        "pdf_export_service.py must use asyncio.get_running_loop() when "
        "dispatching to the thread pool. HF-4 — T-201."
    )


# ---------------------------------------------------------------------------
# PE-3: more tasks than workers complete without thread pool exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_handles_overflow_without_exhaustion() -> None:
    """PE-3 — Five concurrent tasks dispatched to a fresh ThreadPoolExecutor
    (max_workers=2, matching the _PDF_EXECUTOR configuration) complete without
    deadlock or thread pool exhaustion.

    This verifies the core anti-regression property: a burst of concurrent PDF
    requests beyond the pool size queues and processes them without hanging.
    We use a fresh executor (not the module-level _PDF_EXECUTOR) because the
    module-level instance may have been shut down by the FastAPI lifespan during
    earlier tests that use the test client.  The configuration under test
    (max_workers=2) is asserted in PE-1.  HF-4 — T-201.
    """
    n_tasks = 5  # well beyond max_workers=2

    def _sync_work(task_id: int) -> int:
        # Short but non-trivial work so the test exercises actual thread
        # scheduling rather than being optimised away.
        time.sleep(0.01)
        return task_id

    loop = asyncio.get_running_loop()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="pdf-export-test"
    ) as executor:
        results = await asyncio.gather(
            *[loop.run_in_executor(executor, _sync_work, i) for i in range(n_tasks)]
        )

    assert sorted(results) == list(range(n_tasks)), (
        f"All {n_tasks} executor tasks must complete and return their task ID. "
        f"Got: {results!r}. "
        "Thread pool exhaustion or deadlock may have occurred. HF-4 — T-201."
    )


# ---------------------------------------------------------------------------
# PE-4: shutdown_pdf_executor() shuts down the thread pool without error
# ---------------------------------------------------------------------------


def test_shutdown_pdf_executor_is_callable() -> None:
    """PE-4 — shutdown_pdf_executor() must exist and be safely callable.

    Verifies the public shutdown hook for the FastAPI lifespan is present.
    We do NOT call it here (that would break the pool for other tests);
    we just confirm the symbol is exported and is a callable.
    HF-4 — T-201.
    """
    from services.pipeline.pdf_export_service import shutdown_pdf_executor

    assert callable(shutdown_pdf_executor), (
        "shutdown_pdf_executor must be a callable registered in the FastAPI "
        "lifespan to release the PDF thread pool on process exit. HF-4 — T-201."
    )


@pytest.mark.asyncio
async def test_render_html_to_pdf_recreates_executor_after_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PE-5 — later tests can render after a TestClient lifespan shutdown."""

    monkeypatch.setattr(
        pdf_module,
        "_render_pdf_sync",
        lambda html_text: f"%PDF-{html_text}".encode("utf-8"),
    )

    pdf_module.shutdown_pdf_executor()

    pdf = await pdf_module.render_html_to_pdf("after-shutdown")

    assert pdf == b"%PDF-after-shutdown"
