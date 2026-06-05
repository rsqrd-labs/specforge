"""Regression + billing-lane tests for the generic job wrapper (Phase 22 — T-293).

The T-293 refactor parameterised the monolithic ``github_job`` into
``make_job_wrapper`` so a new ``billing_job`` can share the durable base contract
(retry → backoff → dead-letter) while routing to its OWN ``billing:deadletter``
Redis list. These tests pin the two invariants the refactor must not break:

1. GitHub behaviour is unchanged — a ``GitHubThrottledError`` still
   *requeues-not-deadletters* (off the try budget) and real failures still
   dead-letter to ``gh:deadletter``.
2. The billing lane retries then dead-letters to ``billing:deadletter`` after
   ``JOB_MAX_TRIES``, with its own retry/dead-letter counters.

A keyed fake pool records WHICH Redis list each record landed in (the existing
``test_queue.py`` fake ignores the key), which is the discriminating assertion.
"""

from __future__ import annotations

from typing import Any

import pytest
from arq.worker import Retry

from services.integrations.github_governor import GitHubThrottledError
from services.observability import (
    BILLING_JOB_DEADLETTERED_TOTAL,
    BILLING_JOB_RETRIES_TOTAL,
    GITHUB_JOB_DEADLETTERED_TOTAL,
)
from services.queue import (
    BILLING_DEAD_LETTER_KEY,
    GH_DEAD_LETTER_KEY,
    JOB_MAX_TRIES,
    billing_job,
    github_job,
)

pytestmark = pytest.mark.asyncio


class _KeyedFakePool:
    """ArqRedis stand-in recording dead-letter list ops BY KEY + requeues."""

    def __init__(self) -> None:
        # key -> list of pushed records
        self.lpushed: dict[str, list[str]] = {}
        # (name, args, kwargs, defer_by) for each requeue
        self.requeued: list[
            tuple[str, tuple[Any, ...], dict[str, Any], float | None]
        ] = []

    async def lpush(self, key: str, value: str) -> None:
        self.lpushed.setdefault(key, []).append(value)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        pass

    async def enqueue_job(
        self,
        name: str,
        *args: Any,
        _job_id: str | None = None,
        _defer_by: float | None = None,
        **kwargs: Any,
    ) -> object:
        self.requeued.append((name, args, kwargs, _defer_by))
        return object()  # non-None: a fresh-id requeue took effect


# ---------------------------------------------------------------------------
# GitHub behaviour preserved (R6)
# ---------------------------------------------------------------------------


async def test_github_throttle_requeues_not_deadletters() -> None:
    """A GitHubThrottledError requeues (deferred) and writes NO dead-letter."""
    pool = _KeyedFakePool()

    @github_job("export_push")
    async def throttled(ctx: dict[str, Any], push_id: str) -> None:
        raise GitHubThrottledError(12.5, reason="secondary")

    # Even past the try budget, a throttle must never dead-letter (backpressure).
    result = await throttled(
        {"job_try": JOB_MAX_TRIES, "job_id": "p1", "redis": pool}, "p1"
    )
    assert result is None
    assert pool.lpushed == {}, "a throttle must not write a dead-letter record"
    assert len(pool.requeued) == 1, "the job must be requeued deferred"
    name, args, _kwargs, defer_by = pool.requeued[0]
    assert name == "export_push" and args == ("p1",)
    assert defer_by == pytest.approx(12.5)  # the throttle's retry_after


async def test_github_failure_deadletters_to_gh_key() -> None:
    """A real GitHub job failure dead-letters to 'gh:deadletter' (unchanged)."""
    pool = _KeyedFakePool()

    @github_job("export_push")
    async def boom(ctx: dict[str, Any], push_id: str) -> None:
        raise RuntimeError("permanent")

    before = GITHUB_JOB_DEADLETTERED_TOTAL.labels(job="export_push")._value.get()
    result = await boom({"job_try": JOB_MAX_TRIES, "job_id": "p1", "redis": pool}, "p1")
    assert result is None
    assert list(pool.lpushed) == [GH_DEAD_LETTER_KEY]
    assert BILLING_DEAD_LETTER_KEY not in pool.lpushed
    record = pool.lpushed[GH_DEAD_LETTER_KEY][0]
    assert "export_push" in record and "RuntimeError" in record
    assert (
        GITHUB_JOB_DEADLETTERED_TOTAL.labels(job="export_push")._value.get()
        == before + 1
    )


# ---------------------------------------------------------------------------
# Billing lane: own dead-letter key + counters
# ---------------------------------------------------------------------------


async def test_billing_job_deadletters_to_billing_key() -> None:
    """A billing job past JOB_MAX_TRIES dead-letters to 'billing:deadletter'."""
    pool = _KeyedFakePool()

    @billing_job("billing_process_webhook")
    async def boom(ctx: dict[str, Any], event_id: str) -> None:
        raise ValueError("bad event")

    before = BILLING_JOB_DEADLETTERED_TOTAL.labels(
        job="billing_process_webhook"
    )._value.get()
    result = await boom(
        {"job_try": JOB_MAX_TRIES, "job_id": "wh1", "redis": pool}, "wh1"
    )
    assert result is None
    # Routed to the billing list, NOT the GitHub one — the lane separation.
    assert list(pool.lpushed) == [BILLING_DEAD_LETTER_KEY]
    assert GH_DEAD_LETTER_KEY not in pool.lpushed
    record = pool.lpushed[BILLING_DEAD_LETTER_KEY][0]
    assert "billing_process_webhook" in record and "ValueError" in record
    assert (
        BILLING_JOB_DEADLETTERED_TOTAL.labels(
            job="billing_process_webhook"
        )._value.get()
        == before + 1
    )


async def test_billing_job_retries_with_backoff_before_cap() -> None:
    """Before the cap a billing job retries (Retry) + increments its counter."""
    pool = _KeyedFakePool()

    @billing_job("billing_process_webhook")
    async def boom(ctx: dict[str, Any]) -> None:
        raise RuntimeError("transient")

    before = BILLING_JOB_RETRIES_TOTAL.labels(
        job="billing_process_webhook"
    )._value.get()
    with pytest.raises(Retry) as exc:
        await boom({"job_try": 1, "job_id": "wh1", "redis": pool})
    assert exc.value.defer_score is not None
    assert pool.lpushed == {}, "a retry must not dead-letter"
    assert (
        BILLING_JOB_RETRIES_TOTAL.labels(job="billing_process_webhook")._value.get()
        == before + 1
    )


async def test_billing_job_has_no_throttle_special_case() -> None:
    """billing_job has no special handlers: a throttle-shaped error dead-letters
    like any other failure (it is never requeued off the try budget)."""
    pool = _KeyedFakePool()

    @billing_job("billing_process_webhook")
    async def throttled(ctx: dict[str, Any]) -> None:
        raise GitHubThrottledError(5.0, reason="secondary")

    result = await throttled({"job_try": JOB_MAX_TRIES, "job_id": "wh1", "redis": pool})
    assert result is None
    assert list(pool.lpushed) == [BILLING_DEAD_LETTER_KEY]
    assert pool.requeued == [], "billing has no requeue-throttle handler"


async def test_billing_job_success_passes_through() -> None:
    @billing_job("billing_process_webhook")
    async def ok(ctx: dict[str, Any]) -> str:
        return "granted"

    assert await ok({"job_try": 1, "redis": _KeyedFakePool()}) == "granted"
