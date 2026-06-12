"""Unit tests for Phase 1: storyboard mid-first routing with strong escalation.

These are intentionally unit-level (no DB, no Redis) so they run in all
environments.  They test the ``_run_storyboard_completion`` escalation helper
and verify the four discriminating cases the advisor specified:

1. Mid-first happy path — mid succeeds, no escalation counter incremented.
2. Mid schema failure → strong escalation succeeds (``attempted`` + ``succeeded``).
3. Mid timeout → no escalation (transport failures must not escalate to strong).
4. Google/no active strong route → ``no_route`` metric, original error re-raised.

The flag-off path is covered by the existing integration suite in
``test_storyboard_service.py``; the tests here do not duplicate it.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from prometheus_client import REGISTRY

from prompts.storyboard import StoryboardPayload, StoryboardPayloadError
from services.llm.routing import LLMRoute, LLMRoutingError
from services.pipeline import storyboard_service
from services.pipeline.storyboard_service import (
    _run_storyboard_completion,
)
from services.pipeline.storyboard_source import (
    SourceExcerpt,
    StoryboardSourcePackage,
)

_ESCALATION_METRIC = "specforge_storyboard_strong_escalations_total"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(provider: str = "anthropic") -> StoryboardSourcePackage:
    model = "claude-sonnet-4-6" if provider == "anthropic" else "gemini-3.5-flash"
    return StoryboardSourcePackage(
        workspace_id=uuid.uuid4(),
        workspace_name="Test WS",
        problem_statement="Build a test product.",
        provider=provider,
        model=model,
        stage_versions={
            "spec": uuid.uuid4(),
            "plan": uuid.uuid4(),
            "harness": uuid.uuid4(),
            "tasks": uuid.uuid4(),
        },
        artifacts={
            "spec": "# Spec\n\n## Overview\nSpec content.",
            "plan": "# Plan\n\n## Architecture\nPlan content.",
            "harness": "# Harness\n\n## Coverage\nHarness content.",
            "tasks": "# Tasks\n\n## Must-have\n- T-1 auth.",
        },
        excerpts={
            "SPEC:overview": SourceExcerpt(
                source_id="SPEC:overview",
                stage="spec",
                heading="Overview",
                excerpt="overview text",
            )
        },
        missing_source_sections=[],
    )


def _make_mid_route(provider: str = "anthropic") -> LLMRoute:
    model = "claude-sonnet-4-6" if provider == "anthropic" else "gemini-3.5-flash"
    return LLMRoute(
        provider=provider,
        model=model,
        model_tier="mid",
        operation="storyboard.generate",
        latency_class="background",
        cross_provider_fallback=False,
        reason="requested_tier",
        requested_tier="mid",
        fallback_tier="strong",
        selection_reason="active_default",
    )


def _make_strong_route() -> LLMRoute:
    return LLMRoute(
        provider="anthropic",
        model="claude-opus-4-8",
        model_tier="strong",
        operation="storyboard.generate",
        latency_class="background",
        cross_provider_fallback=False,
        reason="requested_tier",
        requested_tier="strong",
        fallback_tier=None,
        selection_reason="active_same_tier",
    )


def _read_escalation_counter(action: str, provider: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value(
            _ESCALATION_METRIC,
            {"action": action, "provider": provider, "outcome": outcome},
        )
        or 0.0
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase1_mid_succeeds_no_escalation(monkeypatch):
    """Mid attempt succeeds: no escalation, counter stays flat."""
    source = _make_source("anthropic")
    mid_route = _make_mid_route("anthropic")
    fake_payload = MagicMock(spec=StoryboardPayload)

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        return fake_payload

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)

    before_attempted = _read_escalation_counter("generate", "anthropic", "attempted")
    before_succeeded = _read_escalation_counter("generate", "anthropic", "succeeded")

    result = await _run_storyboard_completion(
        source, "generate", primary_route=mid_route
    )

    assert result is fake_payload
    assert (
        _read_escalation_counter("generate", "anthropic", "attempted")
        == before_attempted
    )
    assert (
        _read_escalation_counter("generate", "anthropic", "succeeded")
        == before_succeeded
    )


@pytest.mark.asyncio
async def test_phase1_mid_schema_failure_escalates_to_strong(monkeypatch):
    """Mid schema failure triggers a one-shot strong escalation that succeeds.

    The ``attempted`` counter must increment once and ``succeeded`` must
    increment once.  The returned payload must be the strong model's output.
    """
    source = _make_source("anthropic")
    mid_route = _make_mid_route("anthropic")
    strong_route = _make_strong_route()
    strong_payload = MagicMock(spec=StoryboardPayload)

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        if model_tier == "mid":
            raise StoryboardPayloadError("schema", "missing required section heading")
        return strong_payload  # strong model succeeds

    def _fake_resolve(*, operation, preferred_provider, requested_tier, **kwargs):
        if requested_tier == "strong":
            return strong_route
        raise LLMRoutingError("unexpected tier in test")

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)
    monkeypatch.setattr(storyboard_service, "resolve_llm_route", _fake_resolve)

    before_attempted = _read_escalation_counter("generate", "anthropic", "attempted")
    before_succeeded = _read_escalation_counter("generate", "anthropic", "succeeded")

    result = await _run_storyboard_completion(
        source, "generate", primary_route=mid_route
    )

    assert result is strong_payload
    after_attempted = _read_escalation_counter("generate", "anthropic", "attempted")
    after_succeeded = _read_escalation_counter("generate", "anthropic", "succeeded")
    assert after_attempted - before_attempted == 1.0
    assert after_succeeded - before_succeeded == 1.0


@pytest.mark.asyncio
async def test_phase1_mid_timeout_not_escalated(monkeypatch):
    """Mid timeout must NOT trigger escalation — surface the error directly.

    Strong is slower and more expensive; escalating a timed-out mid attempt
    would likely also time out, burning the user's credit without benefit.
    """
    source = _make_source("anthropic")
    mid_route = _make_mid_route("anthropic")

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        raise StoryboardPayloadError("parse", "llm completion timed out")

    resolve_called = []

    def _fake_resolve(**kwargs):
        resolve_called.append(kwargs)
        raise AssertionError("resolve_llm_route must not be called on timeout")

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)
    monkeypatch.setattr(storyboard_service, "resolve_llm_route", _fake_resolve)

    before_attempted = _read_escalation_counter("generate", "anthropic", "attempted")

    with pytest.raises(StoryboardPayloadError) as exc_info:
        await _run_storyboard_completion(source, "generate", primary_route=mid_route)

    assert "timed out" in exc_info.value.summary
    assert len(resolve_called) == 0, "resolve_llm_route must not be called on timeout"
    assert (
        _read_escalation_counter("generate", "anthropic", "attempted")
        == before_attempted
    )


@pytest.mark.asyncio
async def test_phase1_google_no_strong_route_escalation_skipped(monkeypatch):
    """Google has no active strong-tier storyboard model (Pro Preview is preview).

    When the mid attempt fails with a quality error and strong-tier routing
    raises ``LLMRoutingError``, the ``no_route`` outcome is recorded and the
    original mid failure is re-raised.  The ``attempted`` counter must stay flat.
    """
    source = _make_source("google")
    mid_route = _make_mid_route("google")

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        raise StoryboardPayloadError("schema", "grounding failure: invalid source_id")

    def _fake_resolve(*, operation, preferred_provider, requested_tier, **kwargs):
        if requested_tier == "strong":
            raise LLMRoutingError(
                "No same-provider LLM route is available for "
                "operation='storyboard.generate', provider='google', tier='strong'."
            )
        raise AssertionError("unexpected primary routing call in test")

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)
    monkeypatch.setattr(storyboard_service, "resolve_llm_route", _fake_resolve)

    before_no_route = _read_escalation_counter(
        "regenerate_section", "google", "no_route"
    )
    before_attempted = _read_escalation_counter(
        "regenerate_section", "google", "attempted"
    )

    with pytest.raises(StoryboardPayloadError) as exc_info:
        await _run_storyboard_completion(
            source, "regenerate_section", primary_route=mid_route
        )

    assert "grounding failure" in exc_info.value.summary
    after_no_route = _read_escalation_counter(
        "regenerate_section", "google", "no_route"
    )
    after_attempted = _read_escalation_counter(
        "regenerate_section", "google", "attempted"
    )
    assert after_no_route - before_no_route == 1.0
    assert after_attempted == before_attempted


@pytest.mark.asyncio
async def test_phase1_postprocess_failure_triggers_escalation(monkeypatch):
    """A postprocess error (e.g. splice validation) is treated as a quality failure.

    The mid model may produce a section that fails the splice re-validation.
    The postprocess ``StoryboardPayloadError`` must trigger strong escalation
    just like a schema failure from ``_complete_and_validate``.
    """
    source = _make_source("anthropic")
    mid_route = _make_mid_route("anthropic")
    strong_route = _make_strong_route()
    mid_payload = MagicMock(spec=StoryboardPayload)
    strong_payload = MagicMock(spec=StoryboardPayload)

    call_count = {"complete": 0, "postprocess": 0}

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        call_count["complete"] += 1
        return mid_payload if model_tier == "mid" else strong_payload

    def _postprocess(payload: StoryboardPayload) -> StoryboardPayload:
        call_count["postprocess"] += 1
        if payload is mid_payload:
            raise StoryboardPayloadError(
                "schema", "spliced section payload failed validation"
            )
        return strong_payload  # strong payload passes splice

    def _fake_resolve(*, operation, preferred_provider, requested_tier, **kwargs):
        if requested_tier == "strong":
            return strong_route
        raise LLMRoutingError("unexpected in test")

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)
    monkeypatch.setattr(storyboard_service, "resolve_llm_route", _fake_resolve)

    before_attempted = _read_escalation_counter(
        "regenerate_section", "anthropic", "attempted"
    )
    before_succeeded = _read_escalation_counter(
        "regenerate_section", "anthropic", "succeeded"
    )

    result = await _run_storyboard_completion(
        source, "regenerate_section", primary_route=mid_route, postprocess=_postprocess
    )

    assert result is strong_payload
    assert call_count["complete"] == 2  # mid + strong
    assert call_count["postprocess"] == 2  # once for mid (fails), once for strong
    after_attempted = _read_escalation_counter(
        "regenerate_section", "anthropic", "attempted"
    )
    after_succeeded = _read_escalation_counter(
        "regenerate_section", "anthropic", "succeeded"
    )
    assert after_attempted - before_attempted == 1.0
    assert after_succeeded - before_succeeded == 1.0
