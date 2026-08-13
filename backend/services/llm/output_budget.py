"""Per-operation output token budgets for LLM generation calls.

This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
timeout= enforcement is delegated to each concrete adapter implementation.

Budget sizing: frontier reasoning models (Opus 4.8 / GPT-5.5 at high effort,
Gemini 3.5 thinking) bill reasoning tokens against the same max_tokens budget
as visible output.  Budgets therefore carry headroom above the expected
artifact size so thinking never starves the artifact — an 8K budget that was
adequate for non-reasoning models produced truncated or compressed artifacts
once high-effort reasoning landed (issue #19 fallout).

Phase 4 — evidence-backed right-sizing (issue #26)
--------------------------------------------------
The default budgets below are deliberately generous; the live evidence in
`OUTPUT_TOKEN_BUDGETS`' comments (spec chunks measured ~15-18K output tokens;
16384 truncated them) *justifies* the current sizes and supports lowering none
of them.  Right-sizing is therefore gated, never guessed:

* `OUTPUT_TOKEN_BUDGET_OVERRIDES` adds **per-(operation, provider)** granularity
  on top of the per-operation default.  An override is promoted into this dict
  only after the ledger-driven analysis (`scripts/analyze_output_budgets.py`)
  shows, for that exact (operation, provider), enough samples, a zero
  truncation rate, and a p95 + headroom that fits under the current budget.
  See `docs/evals/OUTPUT_BUDGET_TUNING.md` for the promotion gate.
* `recommend_output_budget` is the pure, testable kernel of that analysis. It
  never recommends a budget below the per-operation completeness floor or above
  the model's output ceiling, and refuses to recommend any change when the
  evidence is thin or truncation is already occurring.

`max_tokens` is a per-request parameter, not part of the cached prompt prefix,
so changing a budget does not shatter provider prompt caching; it invalidates
the Thought2Build output cache once (like a prompt-version bump) and restabilizes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from services.llm.model_catalog import model_max_output_tokens

OUTPUT_TOKEN_BUDGETS: dict[str, int] = {
    # A core-gen chunk is reasoning + an ~8-section body. With medium-effort
    # reasoning billed against max_tokens, 24576 truncated nearly every chunk
    # and the doubling repair clamped to the old 32768 model ceiling (so it
    # could not recover) — almost every generation failed with
    # provider_stopped_by_limit. The core-gen ceilings across all three
    # providers are now 64K (model_catalog.py — below every current-gen model's
    # real output cap), so the first attempt sits at 49152 (comfortably fits
    # reasoning + a full dense chunk) and the limit-stop repair still doubles
    # into the 64K ceiling.
    "spec.generate": 49152,
    "plan.generate": 49152,
    "harness.generate": 49152,
    "tasks.generate": 49152,
    # A user-requested gap patch emits several complete test files. The old
    # hard-coded 2048 truncated after roughly one file and left files half-written,
    # which then broke fence parity for the whole merged harness. Sized like a
    # core-generation chunk with reasoning headroom; the completeness-aware merge
    # drops any still-truncated trailing block.
    "harness.patch": 32768,
    "refine.focused": 768,
    "refine.section": 4096,
    "regenerate.full": 49152,
    "summary.create": 2048,
    "eval.score": 1024,
    # A full keynote payload is six acts of slides, one speaker note per slide,
    # a demo script, a technical appendix, plus bounded citation excerpts on every
    # source_map entry and architecture layer — routinely > 16K output tokens once
    # notes and diagrams are dense. The old hardcoded 16384 systematically
    # truncated the richest decks (the parse-failure signature), so this is sized
    # to fit a full deck with reasoning headroom; the truncation-doubling retry
    # (storyboard_service) still backstops a rare overrun on models whose output
    # ceiling exceeds this (escalation-tier Sonnet/GPT/Gemini).  P3.3.
    "storyboard.generate": 32768,
}

# Per-(operation, provider) budget overrides — the Phase-4 right-sizing surface.
#
# Add a REDUCTION here ONLY after the ledger analysis clears the promotion gate
# for that exact (operation, provider) pair (see module docstring and
# docs/evals/OUTPUT_BUDGET_TUNING.md). Keys not present fall through to the
# per-operation default in OUTPUT_TOKEN_BUDGETS, so an unmeasured provider is
# never silently shrunk.
#
# The single entry below is an INCREASE, not a right-sizing reduction, and is
# therefore outside the evidence gate (which only ever proposes reductions —
# `recommend_output_budget` refuses to return a value >= the current budget).
# Rationale: Gemini bills thought tokens against `max_output_tokens`, and on
# Google `refine.focused` resolves to the MID entry (Gemini 3.6 Flash,
# thinking_level="high") rather than to Flash-Lite — the cheap `small` tier is
# unreachable for this operation because the Google tier policy is ("mid",
# "strong"). At the 768-token cross-provider default a single thinking burst
# consumes the entire budget and the call returns finish_reason=MAX_TOKENS with
# empty text. 4096 leaves the thinking headroom that a focused patch needs while
# staying far below the model's 64000 ceiling. Anthropic/OpenAI keep the 768
# default: their focused-refine models are not billed this way.
#
# The openrouter entries below are the same class of INCREASE, for the same
# mechanism. OpenRouter's docs are explicit that "reasoning tokens are
# considered output tokens and charged accordingly" and that "max_tokens must
# be strictly higher than the reasoning budget to ensure there are tokens
# available for the final response after thinking" — so every reasoning-capable
# model on that provider has Gemini's shape, and the entire openrouter ladder
# (DeepSeek V4 Flash and Pro) accepts reasoning_effort.
#
# These three operations are the cheap NON-core paths, so
# `core_generation_low_reasoning` cannot help them: `model_request_policy`
# lowers effort only when the operation is in CORE_GENERATION_OPERATIONS. The
# adapter therefore sends `reasoning: {"exclude": true}` on its non-streaming
# `complete()` path for exactly these operations (openrouter_adapter
# ._suppress_reasoning), which is what keeps the numbers below modest rather
# than speculative — they carry the payload plus a safety margin for a model
# that emits some reasoning anyway, not a full medium-effort burst.
#
# eval.score is the one that must not be tight: the critic is FAIL-OPEN, so a
# judge truncated at finish_reason=length returns empty text, the error is
# swallowed, and quality scoring silently stops while every generation keeps
# succeeding. There is no alert for that.
OUTPUT_TOKEN_BUDGET_OVERRIDES: dict[tuple[str, str], int] = {
    ("refine.focused", "google"): 4096,
    ("refine.focused", "openrouter"): 4096,
    ("summary.create", "openrouter"): 8192,
    ("eval.score", "openrouter"): 4096,
}

# Conservative absolute floors below which the *recommender* will never drop a
# budget, regardless of observed p95. These backstop a pathological sample (e.g.
# a window where most generations errored early and produced tiny outputs) from
# proposing a budget too small to fit a complete artifact + its reasoning. They
# sit well above `artifact_validator._min_body_chars` (which is per-section and
# in characters) because a full multi-section artifact needs far more than any
# single section's minimum. They are a safety net, not the target: the target is
# always `headroom × observed p95`.
_OUTPUT_BUDGET_FLOORS: dict[str, int] = {
    "spec.generate": 8192,
    "plan.generate": 8192,
    "harness.generate": 8192,
    "tasks.generate": 8192,
    "harness.patch": 4096,
    "regenerate.full": 8192,
    "storyboard.generate": 16384,
    "refine.section": 2048,
    "refine.focused": 512,
    "summary.create": 1024,
    "eval.score": 512,
}
_DEFAULT_FLOOR = 512

# Recommendation gate constants (issue #26 Phase 4).
# Headroom above p95: p95 means 1-in-20 calls exceed it, so the budget must
# clear the upper tail; 1.30 covers typical p95→p99 spread for these artifacts,
# and the `provider_stopped_by_limit` doubling repair backstops the rare miss.
RECOMMENDATION_HEADROOM = 1.30
# Statistical floor: too few observations make a percentile meaningless.
RECOMMENDATION_MIN_SAMPLES = 200
# Any truncation at the current budget means it is already too tight — never
# propose lowering it. Expressed as a fraction of calls stopped by the limit.
RECOMMENDATION_MAX_TRUNCATION_RATE = 0.005


def budget_floor_for_operation(operation: str) -> int:
    """The absolute floor the recommender will not drop *operation* below."""
    return _OUTPUT_BUDGET_FLOORS.get(operation, _DEFAULT_FLOOR)


def output_budget_for_operation(operation: str, provider: str | None = None) -> int:
    """The configured output budget for *operation*, honoring a per-provider
    override when one has been promoted for ``(operation, provider)``."""
    if provider is not None:
        override = OUTPUT_TOKEN_BUDGET_OVERRIDES.get((operation, provider))
        if override is not None:
            return override
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
    """The operation budget (with any per-provider override) clamped to the
    model's output-token ceiling.

    Unknown models fall back to the raw operation budget rather than failing:
    budget resolution must never brick a generation that routing accepted.
    """
    budget = output_budget_for_operation(operation, provider)
    if provider and model:
        try:
            return min(budget, model_max_output_tokens(provider, model))
        except ValueError:
            return budget
    return budget


@dataclass(frozen=True)
class BudgetRecommendation:
    """A single (operation, provider) right-sizing verdict from the ledger.

    ``recommended_budget is None`` means "make no change" — either the evidence
    is insufficient/unsafe, or the observed distribution already fits the
    current budget. A non-None value is always strictly below ``current_budget``
    (the recommender only proposes reductions; growth is handled at runtime by
    the limit-stop repair, not by this advisory path).
    """

    operation: str
    provider: str
    samples: int
    p95_output_tokens: int | None
    truncation_rate: float | None
    current_budget: int
    recommended_budget: int | None
    rationale: str


def recommend_output_budget(
    operation: str,
    provider: str,
    *,
    samples: int,
    p95_output_tokens: int | None,
    truncation_rate: float | None,
    current_budget: int,
    model_ceiling: int | None = None,
) -> BudgetRecommendation:
    """Evidence-backed budget verdict for one (operation, provider) pair.

    Pure function (the test surface for Phase 4). Encodes the promotion gate:

    1. ``samples >= RECOMMENDATION_MIN_SAMPLES`` — a percentile from a handful of
       calls is noise.
    2. ``truncation_rate`` known and ``<= RECOMMENDATION_MAX_TRUNCATION_RATE`` —
       any meaningful rate of ``stopped_by_limit`` means the *current* budget is
       already too small; lowering it would be actively wrong.
    3. Target ``= ceil(p95 × RECOMMENDATION_HEADROOM)``, clamped to
       ``[floor(operation), model_ceiling]``. Reasoning tokens are intentionally
       NOT added on top: they are already inside ``output_tokens`` (and thus
       inside p95), so adding a separate reasoning allowance would double-count.
    4. A change is proposed only when the clamped target is **strictly below**
       the current budget. Otherwise the observed distribution already fits and
       we leave the (generous, repair-guarded) default in place.
    """

    def verdict(recommended: int | None, rationale: str) -> BudgetRecommendation:
        return BudgetRecommendation(
            operation=operation,
            provider=provider,
            samples=samples,
            p95_output_tokens=p95_output_tokens,
            truncation_rate=truncation_rate,
            current_budget=current_budget,
            recommended_budget=recommended,
            rationale=rationale,
        )

    if samples < RECOMMENDATION_MIN_SAMPLES:
        return verdict(
            None,
            f"insufficient_samples: {samples} < {RECOMMENDATION_MIN_SAMPLES}",
        )
    if p95_output_tokens is None or p95_output_tokens <= 0:
        return verdict(None, "no_output_token_data")
    if truncation_rate is None:
        return verdict(None, "truncation_rate_unknown")
    if truncation_rate > RECOMMENDATION_MAX_TRUNCATION_RATE:
        return verdict(
            None,
            "truncation_observed: "
            f"{truncation_rate:.4f} > {RECOMMENDATION_MAX_TRUNCATION_RATE} "
            "(current budget already too tight; do not lower)",
        )

    target = math.ceil(p95_output_tokens * RECOMMENDATION_HEADROOM)
    floor = budget_floor_for_operation(operation)
    target = max(target, floor)
    if model_ceiling is not None:
        target = min(target, model_ceiling)

    if target >= current_budget:
        return verdict(
            None,
            "no_reduction_available: "
            f"p95={p95_output_tokens} × {RECOMMENDATION_HEADROOM} "
            f"= {target} >= current {current_budget}",
        )

    return verdict(
        target,
        f"reduce: p95={p95_output_tokens} × {RECOMMENDATION_HEADROOM} "
        f"-> {target} (floor {floor}) < current {current_budget}, "
        f"truncation={truncation_rate:.4f}",
    )
