"""Stream watchdog, runtime tier fallback, and output-budget tests.

These cover the issue-#19 fixes: a steadily streaming generation is never
killed regardless of total duration (the old flat per-stream timeout was the
failure mode), a stalled stream dies at the idle bound, runaway streams die at
the hard cap, failed strong-tier generations retry once on the mid tier, and
output budgets are clamped to the model's output-token ceiling.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from services.llm.output_budget import (
    OUTPUT_TOKEN_BUDGETS,
    resolve_output_budget,
)
from services.pipeline import stage_manager as stage_manager_module
from services.pipeline.stage_manager import (
    StreamWatchdogTimeout,
    _chunk_output_budget,
    _chunk_specs_for_stage,
    _runtime_fallback_route,
    _watchdog_stream,
)


def _patch_watchdog(idle: float, cap: float):
    return (
        patch.object(
            stage_manager_module.settings,
            "stage_provider_idle_timeout_seconds",
            idle,
        ),
        patch.object(
            stage_manager_module.settings,
            "stage_provider_call_timeout_seconds",
            cap,
        ),
    )


@pytest.mark.asyncio
async def test_watchdog_kills_stalled_stream_at_idle_bound() -> None:
    async def stalled():
        await asyncio.sleep(5)
        yield "too late"

    idle_patch, cap_patch = _patch_watchdog(0.05, 10.0)
    with idle_patch, cap_patch:
        with pytest.raises(StreamWatchdogTimeout) as exc_info:
            async for _ in _watchdog_stream(
                stalled(), stage_type="spec", provider="anthropic"
            ):
                pass

    assert exc_info.value.kind == "idle"
    assert isinstance(exc_info.value, TimeoutError)


@pytest.mark.asyncio
async def test_watchdog_allows_slow_but_steady_stream() -> None:
    """A generation that keeps producing tokens must never be killed, even
    when its total duration far exceeds the idle bound — this is the exact
    long-input regression behind issue #19."""

    async def steady():
        for index in range(20):
            await asyncio.sleep(0.02)
            yield f"token-{index} "

    idle_patch, cap_patch = _patch_watchdog(0.1, 10.0)
    with idle_patch, cap_patch:
        tokens = [
            token
            async for token in _watchdog_stream(
                steady(), stage_type="spec", provider="anthropic"
            )
        ]

    assert len(tokens) == 20


@pytest.mark.asyncio
async def test_watchdog_treats_empty_sentinels_as_liveness() -> None:
    """Adapters yield empty-string sentinels for provider events with no
    visible text (reasoning/thinking deltas, pings).  These must reset the
    idle timer — a reasoning model silent for longer than the idle bound
    stays alive while provider events keep arriving — but must never be
    forwarded to the consumer."""

    async def thinking_then_text():
        # 8 sentinel gaps of 0.03s: each below the 0.1s idle bound, but the
        # total silent-thinking phase (0.24s) is far beyond it.
        for _ in range(8):
            await asyncio.sleep(0.03)
            yield ""
        yield "artifact"

    idle_patch, cap_patch = _patch_watchdog(0.1, 10.0)
    with idle_patch, cap_patch:
        tokens = [
            token
            async for token in _watchdog_stream(
                thinking_then_text(), stage_type="spec", provider="anthropic"
            )
        ]

    assert tokens == ["artifact"]


@pytest.mark.asyncio
async def test_watchdog_enforces_hard_cap_on_runaway_stream() -> None:
    async def runaway():
        while True:
            await asyncio.sleep(0.01)
            yield "x"

    idle_patch, cap_patch = _patch_watchdog(10.0, 0.08)
    with idle_patch, cap_patch:
        with pytest.raises(StreamWatchdogTimeout) as exc_info:
            async for _ in _watchdog_stream(
                runaway(), stage_type="tasks", provider="openai"
            ):
                pass

    assert exc_info.value.kind == "hard_cap"


def test_runtime_fallback_route_escalates_on_same_provider(
    monkeypatch,
) -> None:
    # Pin the cheap-primary policy on explicitly (independent of the product
    # default): on it, core gen starts on the cheap primary (Haiku, small) and a
    # runtime failure escalates to the provider's mid tier (Sonnet).
    from services.llm import tier_policy

    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", True)

    same_provider = MagicMock()
    same_provider.provider = "anthropic"
    same_provider.model = "claude-sonnet-4-6"
    same_provider.model_tier = "mid"
    monkeypatch.setattr(
        stage_manager_module, "resolve_llm_route", lambda **_kwargs: same_provider
    )

    primary = MagicMock()
    primary.provider = "anthropic"
    primary.model = "claude-haiku-4-5-20251001"
    primary.model_tier = "small"
    primary.operation = "spec.generate"

    fallback = _runtime_fallback_route(primary)

    assert fallback is same_provider
    assert fallback.provider == primary.provider
    assert fallback.model_tier == "mid"


def test_runtime_fallback_route_stops_when_already_at_escalation_tier(
    monkeypatch,
) -> None:
    # Under the cheap-primary policy a mid-tier failure has nowhere left to
    # escalate (mid IS the escalation tier).  Pin it on explicitly.
    from services.llm import tier_policy

    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", True)

    mid = MagicMock()
    mid.provider = "anthropic"
    mid.model = "claude-sonnet-4-6"
    mid.model_tier = "mid"
    mid.operation = "spec.generate"

    fallback = _runtime_fallback_route(mid)
    assert fallback is None


def test_output_budgets_carry_reasoning_headroom() -> None:
    """Core generation budgets must exceed the pre-fix 8K ceiling: reasoning
    tokens share the budget with visible output on frontier models."""
    for operation in (
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
    ):
        assert OUTPUT_TOKEN_BUDGETS[operation] > 8192


def test_resolve_output_budget_clamps_to_model_ceiling() -> None:
    # Gemini Flash-Lite's catalog ceiling (4096) is below the spec budget — the
    # budget is clamped down to the model's hard ceiling. (The core-gen ceilings
    # across all three providers were raised to 64K — below every current-gen
    # model's real output cap — so the cheap primaries are never clamped and the
    # limit-stop repair has real headroom.)
    assert (
        resolve_output_budget(
            "spec.generate",
            provider="google",
            model="gemini-3.1-flash-lite",
        )
        == 4096
    )
    # Opus's ceiling (64000) is above the spec budget — budget wins.
    assert (
        resolve_output_budget(
            "spec.generate",
            provider="anthropic",
            model="claude-opus-4-8",
        )
        == OUTPUT_TOKEN_BUDGETS["spec.generate"]
    )
    # Unknown models fall back to the raw budget rather than failing.
    assert (
        resolve_output_budget("spec.generate", provider="anthropic", model="nope")
        == OUTPUT_TOKEN_BUDGETS["spec.generate"]
    )


def test_chunk_output_budgets_are_fixed_and_model_clamped(monkeypatch) -> None:
    route = MagicMock()
    route.provider = "anthropic"
    route.model = "claude-opus-4-8"
    spec_chunk = _chunk_specs_for_stage("spec")[0]
    plan_chunk = _chunk_specs_for_stage("plan")[0]
    harness_contract, harness_files = _chunk_specs_for_stage("harness")
    tasks_chunk = _chunk_specs_for_stage("tasks")[0]

    assert _chunk_output_budget("spec", spec_chunk, route) == 32_768
    assert _chunk_output_budget("plan", plan_chunk, route) == 32_768
    assert _chunk_output_budget("tasks", tasks_chunk, route) == 32_768
    assert _chunk_output_budget("harness", harness_contract, route) == 24_576
    assert _chunk_output_budget("harness", harness_files, route) == 49_152

    monkeypatch.setattr(
        stage_manager_module, "model_max_output_tokens", lambda *_: 8_192
    )
    assert _chunk_output_budget("spec", spec_chunk, route) == 8_192


def test_settings_reject_generation_bounds_outside_contract() -> None:
    from pydantic import ValidationError

    import config

    with pytest.raises(ValidationError, match="must be 300"):
        config.Settings(stage_generation_deadline_seconds=301)
    with pytest.raises(ValidationError, match="must be 1..90"):
        config.Settings(stage_provider_idle_timeout_seconds=91)
    with pytest.raises(ValidationError, match="at least 45"):
        config.Settings(stage_retry_min_remaining_seconds=44)
