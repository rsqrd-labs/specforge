from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.llm.base import BaseLLMAdapter
from services.llm.cost_registry import get_provider_capabilities, model_tier
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
) -> BackgroundLLMResult:
    if operation in INTERACTIVE_OPERATIONS:
        raise BatchEligibilityError(
            f"Interactive operation {operation!r} cannot use background batch."
        )
    if operation not in ELIGIBLE_BATCH_OPERATIONS:
        raise BatchEligibilityError(f"Operation {operation!r} is not batch-eligible.")

    batch = allow_batch and _provider_supports_batch(provider)
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


def _provider_supports_batch(provider: str) -> bool:
    try:
        return bool(get_provider_capabilities(provider)["supports_batch"])
    except Exception:
        return False


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
