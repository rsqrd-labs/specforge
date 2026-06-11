"""Per-operation output token budgets for LLM generation calls.

This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
timeout= enforcement is delegated to each concrete adapter implementation.

Budget sizing: frontier reasoning models (Opus 4.8 / GPT-5.5 at high effort,
Gemini 3.5 thinking) bill reasoning tokens against the same max_tokens budget
as visible output.  Budgets therefore carry headroom above the expected
artifact size so thinking never starves the artifact — an 8K budget that was
adequate for non-reasoning models produced truncated or compressed artifacts
once high-effort reasoning landed (issue #19 fallout).
"""

from __future__ import annotations

from services.llm.model_catalog import model_max_output_tokens

OUTPUT_TOKEN_BUDGETS: dict[str, int] = {
    # Live GPT-5.5 spec chunks measured ~15-18K estimated output tokens
    # (reasoning + an 8-section chunk body); 16384 truncated them, so core
    # generation budgets sit at 24576 with the limit-stop repair doubling
    # into the 32768 model ceiling.
    "spec.generate": 24576,
    "plan.generate": 24576,
    "harness.generate": 24576,
    "tasks.generate": 24576,
    "refine.focused": 768,
    "refine.section": 4096,
    "regenerate.full": 24576,
    "summary.create": 2048,
    "eval.score": 1024,
}


def output_budget_for_operation(operation: str) -> int:
    try:
        return OUTPUT_TOKEN_BUDGETS[operation]
    except KeyError as exc:
        raise ValueError(f"Unknown output budget operation: {operation!r}") from exc


def resolve_output_budget(
    operation: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> int:
    """The operation budget clamped to the model's output-token ceiling.

    Unknown models fall back to the raw operation budget rather than failing:
    budget resolution must never brick a generation that routing accepted.
    """
    budget = output_budget_for_operation(operation)
    if provider and model:
        try:
            return min(budget, model_max_output_tokens(provider, model))
        except ValueError:
            return budget
    return budget
