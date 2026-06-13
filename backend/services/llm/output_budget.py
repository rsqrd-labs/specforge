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
the SpecForge output cache once (like a prompt-version bump) and restabilizes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

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

# Per-(operation, provider) budget overrides — the Phase-4 right-sizing surface.
#
# EMPTY BY DESIGN. Add a key here ONLY after the ledger analysis clears the
# promotion gate for that exact (operation, provider) pair (see module docstring
# and docs/evals/OUTPUT_BUDGET_TUNING.md). Keys not present fall through to the
# per-operation default in OUTPUT_TOKEN_BUDGETS, so an unmeasured provider is
# never silently shrunk.
OUTPUT_TOKEN_BUDGET_OVERRIDES: dict[tuple[str, str], int] = {}

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
    "regenerate.full": 8192,
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
