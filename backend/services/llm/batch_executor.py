"""Synchronous fallback executor for non-interactive judge/eval operations.

This is the *real-time* path for background LLM work: it calls the adapter's
``complete()`` immediately, at full price. The real provider Message Batches path
(the 50% discount) lives in ``services/evals/eval_batch.py`` and runs on the arq
worker; this module is what eval falls back to when batching is off, the provider
has no batch adapter, or the durable queue is unavailable.

Because this path is **not** a provider batch, it records ``batch=False`` on the
cost event — claiming the batch flag here while paying the full real-time price
would halve the recorded cost (``estimate_cost_usd(batch=...)``) and corrupt the
ledger. Only ``eval_batch`` records ``batch=True``.

HTTP timeout policy (H-6 — T-182): timeout= enforcement is delegated to the
underlying adapter's httpx.Timeout configuration.  This module does not make
direct HTTP calls; it delegates to BaseLLMAdapter implementations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.llm.base import BaseLLMAdapter
from services.llm.cost_ledger import LLMCostContext
from services.llm.cost_registry import model_tier
from services.llm.gateway import get_llm
from services.llm.instrumented_adapter import InstrumentedAdapter

logger = logging.getLogger(__name__)

ELIGIBLE_BATCH_OPERATIONS = frozenset(
    {
        "eval.score",
        "summary.create",
        "audit.artifact_quality",
        "prompt_regression.run",
    }
)
INTERACTIVE_OPERATIONS = frozenset(
    {
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
        "refine.focused",
        "refine.section",
        "regenerate.full",
    }
)
_DEAD_LETTER_JOBS: list[dict[str, Any]] = []


class BatchEligibilityError(ValueError):
    pass


@dataclass(frozen=True)
class BackgroundLLMResult:
    output: str
    batch: bool
    provider: str
    model: str
    operation: str


async def complete_background_llm(
    *,
    operation: str,
    provider: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    stage_type: str,
    prompt_version: str = "local",
    allow_batch: bool = True,
    adapter_factory: Callable[[str, str], BaseLLMAdapter] = get_llm,
    cost_context: LLMCostContext | None = None,
) -> BackgroundLLMResult:
    if operation in INTERACTIVE_OPERATIONS:
        raise BatchEligibilityError(
            f"Interactive operation {operation!r} cannot use background batch."
        )
    if operation not in ELIGIBLE_BATCH_OPERATIONS:
        raise BatchEligibilityError(f"Operation {operation!r} is not batch-eligible.")

    # This is the synchronous real-time path — it never claims the batch
    # discount (the real provider-batch path is services/evals/eval_batch.py).
    # ``allow_batch`` is retained for call-site/back-compat but no longer drives
    # a cost-affecting flag here.
    del allow_batch
    batch = False
    try:
        adapter = adapter_factory(provider, model)
        instrumented = InstrumentedAdapter(
            adapter,
            provider=provider,
            model=model,
            stage_type=stage_type,
            action=operation,
            model_tier=_model_tier_or_unknown(provider, model),
            prompt_version=prompt_version,
            operation=operation,
            cache_hit=False,
            batch=batch,
            cross_provider_fallback=False,
            cost_context=cost_context,
        )
        output = await instrumented.complete(system, user, max_tokens=max_tokens)
        return BackgroundLLMResult(
            output=output,
            batch=batch,
            provider=provider,
            model=model,
            operation=operation,
        )
    except Exception as exc:
        _record_dead_letter(
            operation=operation,
            provider=provider,
            model=model,
            batch=batch,
            error=str(exc),
        )
        raise


def dead_letter_jobs() -> list[dict[str, Any]]:
    return list(_DEAD_LETTER_JOBS)


def clear_dead_letter_jobs() -> None:
    _DEAD_LETTER_JOBS.clear()


def _model_tier_or_unknown(provider: str, model: str) -> str:
    try:
        return model_tier(provider, model)
    except Exception:
        return "unknown"


def _record_dead_letter(
    *,
    operation: str,
    provider: str,
    model: str,
    batch: bool,
    error: str,
) -> None:
    entry = {
        "operation": operation,
        "provider": provider,
        "model": model,
        "batch": batch,
        "error": error,
    }
    _DEAD_LETTER_JOBS.append(entry)
    logger.error("llm.background_job_failed", extra=entry)
