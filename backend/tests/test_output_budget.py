"""Phase-4 output-budget right-sizing tests (issue #26)."""

from __future__ import annotations

import math

import pytest

from services.llm.cost_ledger import output_token_percentiles
from services.llm.output_budget import (
    OUTPUT_TOKEN_BUDGET_OVERRIDES,
    OUTPUT_TOKEN_BUDGETS,
    RECOMMENDATION_HEADROOM,
    RECOMMENDATION_MIN_SAMPLES,
    budget_floor_for_operation,
    output_budget_for_operation,
    recommend_output_budget,
    resolve_output_budget,
)


# --------------------------------------------------------------------------- #
# per-(operation, provider) overrides
# --------------------------------------------------------------------------- #
def test_default_budget_unchanged_when_no_override() -> None:
    assert output_budget_for_operation("spec.generate") == 24576
    assert output_budget_for_operation("spec.generate", "anthropic") == 24576


def test_override_takes_precedence(monkeypatch) -> None:
    monkeypatch.setitem(
        OUTPUT_TOKEN_BUDGET_OVERRIDES, ("spec.generate", "openai"), 16384
    )
    # Override applies only to the matched (operation, provider) pair.
    assert output_budget_for_operation("spec.generate", "openai") == 16384
    assert output_budget_for_operation("spec.generate", "anthropic") == 24576
    assert output_budget_for_operation("spec.generate") == 24576


def test_resolve_output_budget_honors_override_then_clamps(monkeypatch) -> None:
    # Override below the model ceiling survives the clamp.
    monkeypatch.setitem(
        OUTPUT_TOKEN_BUDGET_OVERRIDES, ("plan.generate", "openai"), 12000
    )
    assert (
        resolve_output_budget("plan.generate", provider="openai", model="gpt-5.4-mini")
        == 12000
    )


def test_overrides_dict_ships_empty() -> None:
    # The promotion surface must ship empty — no provider silently shrunk.
    assert OUTPUT_TOKEN_BUDGET_OVERRIDES == {}


def test_build_eval_request_threads_provider_override(monkeypatch) -> None:
    # Guards the wiring: a per-(operation, provider) override must reach the
    # eval-judge budget on both the sync and deferred-batch paths.
    from services.evals.online_eval import build_eval_request

    monkeypatch.setitem(OUTPUT_TOKEN_BUDGET_OVERRIDES, ("eval.score", "anthropic"), 512)
    _, _, max_tokens = build_eval_request("spec", "content", "spec", "anthropic")
    assert max_tokens == 512
    # No override for openai -> default eval.score budget.
    _, _, default_tokens = build_eval_request("spec", "content", "spec", "openai")
    assert default_tokens == OUTPUT_TOKEN_BUDGETS["eval.score"]


def test_unknown_operation_raises() -> None:
    with pytest.raises(ValueError):
        output_budget_for_operation("nope.generate")


# --------------------------------------------------------------------------- #
# recommend_output_budget — the promotion gate
# --------------------------------------------------------------------------- #
_CURRENT = OUTPUT_TOKEN_BUDGETS["spec.generate"]


def _rec(**kw):
    base = dict(
        operation="spec.generate",
        provider="openai",
        samples=1000,
        p95_output_tokens=8000,
        truncation_rate=0.0,
        current_budget=_CURRENT,
    )
    base.update(kw)
    op = base.pop("operation")
    provider = base.pop("provider")
    return recommend_output_budget(op, provider, **base)


def test_insufficient_samples_recommends_no_change() -> None:
    rec = _rec(samples=RECOMMENDATION_MIN_SAMPLES - 1)
    assert rec.recommended_budget is None
    assert "insufficient_samples" in rec.rationale


def test_missing_output_data_recommends_no_change() -> None:
    assert _rec(p95_output_tokens=None).recommended_budget is None
    assert _rec(p95_output_tokens=0).recommended_budget is None


def test_unknown_truncation_rate_recommends_no_change() -> None:
    rec = _rec(truncation_rate=None)
    assert rec.recommended_budget is None
    assert "truncation_rate_unknown" in rec.rationale


def test_any_truncation_blocks_reduction() -> None:
    # Even a small but above-threshold truncation rate blocks lowering.
    rec = _rec(truncation_rate=0.01)
    assert rec.recommended_budget is None
    assert "truncation_observed" in rec.rationale


def test_valid_reduction_uses_p95_times_headroom() -> None:
    rec = _rec(p95_output_tokens=8000, truncation_rate=0.0)
    expected = math.ceil(8000 * RECOMMENDATION_HEADROOM)
    assert rec.recommended_budget == expected
    assert expected < _CURRENT


def test_reduction_floored_to_completeness_floor() -> None:
    # A pathologically tiny p95 cannot drop the budget below the floor.
    rec = _rec(p95_output_tokens=10, truncation_rate=0.0)
    assert rec.recommended_budget == budget_floor_for_operation("spec.generate")


def test_no_reduction_when_distribution_already_fits() -> None:
    # p95 near the ceiling: headroom pushes target >= current -> no change.
    rec = _rec(p95_output_tokens=20000, truncation_rate=0.0)
    assert rec.recommended_budget is None
    assert "no_reduction_available" in rec.rationale


def test_model_ceiling_clamps_target() -> None:
    rec = _rec(
        p95_output_tokens=8000,
        truncation_rate=0.0,
        current_budget=40000,
        model_ceiling=9000,
    )
    # ceil(8000*1.3)=10400 clamped to 9000, still < current 40000.
    assert rec.recommended_budget == 9000


def test_recommendation_carries_inputs_for_audit() -> None:
    rec = _rec()
    assert rec.operation == "spec.generate"
    assert rec.provider == "openai"
    assert rec.samples == 1000
    assert rec.current_budget == _CURRENT


# --------------------------------------------------------------------------- #
# output_token_percentiles — SQL aggregation shape
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_output_token_percentiles_shape() -> None:
    class _Row:
        operation = "spec.generate"
        provider = "openai"
        samples = 500
        p50_output_tokens = 12000.0
        p90_output_tokens = 15000.0
        p95_output_tokens = 16000.0
        max_output_tokens = 18000
        p50_reasoning_tokens = 2000.0
        p95_reasoning_tokens = 4000.0
        truncation_rate = 0.0

    class _DB:
        async def execute(self, stmt):
            return [_Row()]

    rows = await output_token_percentiles(_DB())
    assert rows == [
        {
            "operation": "spec.generate",
            "provider": "openai",
            "samples": 500,
            "p50_output_tokens": 12000,
            "p90_output_tokens": 15000,
            "p95_output_tokens": 16000,
            "max_output_tokens": 18000,
            "p50_reasoning_tokens": 2000,
            "p95_reasoning_tokens": 4000,
            "truncation_rate": 0.0,
        }
    ]


@pytest.mark.asyncio
async def test_output_token_percentiles_handles_nulls() -> None:
    class _Row:
        operation = "plan.generate"
        provider = "anthropic"
        samples = 0
        p50_output_tokens = None
        p90_output_tokens = None
        p95_output_tokens = None
        max_output_tokens = None
        p50_reasoning_tokens = None
        p95_reasoning_tokens = None
        truncation_rate = None

    class _DB:
        async def execute(self, stmt):
            return [_Row()]

    rows = await output_token_percentiles(_DB())
    assert rows[0]["p95_output_tokens"] is None
    assert rows[0]["truncation_rate"] is None
    assert rows[0]["samples"] == 0


@pytest.mark.asyncio
async def test_output_token_percentiles_empty_ledger() -> None:
    class _DB:
        async def execute(self, stmt):
            return []

    assert await output_token_percentiles(_DB()) == []


# --------------------------------------------------------------------------- #
# input_token_percentiles — assembled-prompt distribution (compression Phase A)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_input_token_percentiles_shape() -> None:
    from services.llm.cost_ledger import input_token_percentiles

    class _Row:
        operation = "spec.generate"
        provider = "anthropic"
        samples = 300
        p50_input_tokens = 6000.0
        p90_input_tokens = 9000.0
        p95_input_tokens = 10000.0
        max_input_tokens = 42000

    class _DB:
        async def execute(self, stmt):
            return [_Row()]

    rows = await input_token_percentiles(_DB())
    assert rows == [
        {
            "operation": "spec.generate",
            "provider": "anthropic",
            "samples": 300,
            "p50_input_tokens": 6000,
            "p90_input_tokens": 9000,
            "p95_input_tokens": 10000,
            "max_input_tokens": 42000,
        }
    ]


@pytest.mark.asyncio
async def test_input_token_percentiles_handles_nulls_and_empty() -> None:
    from services.llm.cost_ledger import input_token_percentiles

    class _Row:
        operation = "plan.generate"
        provider = "google"
        samples = 0
        p50_input_tokens = None
        p90_input_tokens = None
        p95_input_tokens = None
        max_input_tokens = None

    class _DBWithNulls:
        async def execute(self, stmt):
            return [_Row()]

    class _EmptyDB:
        async def execute(self, stmt):
            return []

    rows = await input_token_percentiles(_DBWithNulls())
    assert rows[0]["p95_input_tokens"] is None
    assert rows[0]["samples"] == 0
    assert await input_token_percentiles(_EmptyDB()) == []
