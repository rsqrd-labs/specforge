"""Unit tests for storyboard cheap-primary routing with mid-tier escalation.

Storyboard follows the same product-wide cheap-primary→mid policy as core
generation (issue #17 follow-up): the cheap tier is the primary and the route's
``fallback_tier`` (mid while ``core_cheap_primary`` is live) is the
quality-failure escalation target.

These are intentionally unit-level (no DB, no Redis) so they run in all
environments.  They test the ``_run_storyboard_completion`` escalation helper
and verify the discriminating cases:

1. Primary happy path — cheap succeeds, no escalation counter incremented.
2. Primary schema failure → mid escalation succeeds (``attempted`` + ``succeeded``).
3. Primary timeout → no escalation (transport failures must not escalate).
4. Google/no active escalation route → ``no_route`` metric, original error re-raised.
5. Postprocess (splice) failure → escalation, same as a schema failure.
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
    _resolve_storyboard_primary_route,
    _run_storyboard_completion,
)
from services.pipeline.storyboard_source import (
    SourceExcerpt,
    StoryboardSourcePackage,
)

_ESCALATION_METRIC = "specforge_storyboard_escalations_total"
_TRUNCATION_METRIC = "specforge_storyboard_truncation_retries_total"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(provider: str = "anthropic") -> StoryboardSourcePackage:
    return StoryboardSourcePackage(
        workspace_id=uuid.uuid4(),
        workspace_name="Test WS",
        problem_statement="Build a test product.",
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


def _make_primary_route(provider: str = "anthropic") -> LLMRoute:
    """The cheap-primary route, mirroring ``generation_tier_policy``.

    anthropic: cheap ``small`` (Haiku) escalating to ``mid`` (Sonnet).
    google:    no sub-Flash model, so it floors at ``mid`` (Flash) escalating to
               ``strong`` (which has no active model — surfaces directly).
    """
    if provider == "anthropic":
        model, tier, fallback = "claude-haiku-4-5-20251001", "small", "mid"
    else:  # google
        model, tier, fallback = "gemini-3.5-flash", "mid", "strong"
    return LLMRoute(
        provider=provider,
        model=model,
        model_tier=tier,
        operation="storyboard.generate",
        latency_class="background",
        cross_provider_fallback=False,
        reason="requested_tier",
        requested_tier=tier,
        fallback_tier=fallback,
        selection_reason="active_default",
    )


def _make_escalation_route() -> LLMRoute:
    """The mid-tier escalation route (Sonnet) for the anthropic cheap primary."""
    return LLMRoute(
        provider="anthropic",
        model="claude-sonnet-4-6",
        model_tier="mid",
        operation="storyboard.generate",
        latency_class="background",
        cross_provider_fallback=False,
        reason="requested_tier",
        requested_tier="mid",
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


def _read_truncation_counter(provider: str) -> float:
    return REGISTRY.get_sample_value(_TRUNCATION_METRIC, {"provider": provider}) or 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_resolve_primary_route_picks_cheap_tier(monkeypatch):
    """Storyboard's primary route is the provider's cheap-tier model.

    Verified against the real catalog/routing layer (no mocks): the cheap
    storyboard primary must actually resolve now that Haiku/Mini list
    ``storyboard.generate``, escalating to mid.  Pin the cheap-primary policy on
    explicitly to exercise that path independent of the product default.
    """
    from services.llm import provider_status, tier_policy

    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", True)
    monkeypatch.setattr(provider_status, "can_route", lambda *_args: True)
    monkeypatch.setattr(provider_status, "is_provider_configured", lambda *_args: True)
    monkeypatch.setattr(
        tier_policy.settings,
        "llm_provider_priority",
        "anthropic,openai,google",
    )

    route = _resolve_storyboard_primary_route(_make_source("anthropic"))
    assert route.model == "claude-haiku-4-5-20251001"
    assert route.model_tier == "small"
    assert route.fallback_tier == "mid"
    assert route.operation == "storyboard.generate"
    assert route.selection_reason == "active_default"


def test_resolve_primary_route_google_floors_at_mid(monkeypatch):
    """Google has no sub-Flash model, so its storyboard primary floors at mid."""
    from config import settings
    from services.llm import provider_status

    monkeypatch.setattr(settings, "llm_provider_priority", "google,anthropic,openai")
    monkeypatch.setattr(provider_status, "can_route", lambda *_args: True)
    monkeypatch.setattr(provider_status, "is_provider_configured", lambda *_args: True)
    route = _resolve_storyboard_primary_route(_make_source("google"))
    assert route.model == "gemini-3.5-flash"
    assert route.model_tier == "mid"
    assert route.fallback_tier == "strong"


@pytest.mark.asyncio
async def test_storyboard_primary_succeeds_no_escalation(monkeypatch):
    """Cheap primary succeeds: no escalation, counter stays flat."""
    source = _make_source("anthropic")
    primary_route = _make_primary_route("anthropic")
    fake_payload = MagicMock(spec=StoryboardPayload)

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        return fake_payload

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)

    before_attempted = _read_escalation_counter("generate", "anthropic", "attempted")
    before_succeeded = _read_escalation_counter("generate", "anthropic", "succeeded")

    result = await _run_storyboard_completion(
        source, "generate", primary_route=primary_route
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
async def test_storyboard_primary_schema_failure_escalates_to_mid(monkeypatch):
    """Cheap-primary schema failure triggers a one-shot mid escalation that succeeds.

    The ``attempted`` counter must increment once and ``succeeded`` must
    increment once.  The returned payload must be the mid model's output.
    """
    source = _make_source("anthropic")
    primary_route = _make_primary_route("anthropic")
    escalation_route = _make_escalation_route()
    escalation_payload = MagicMock(spec=StoryboardPayload)

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        if model_tier == "small":
            raise StoryboardPayloadError("schema", "missing required section heading")
        return escalation_payload  # mid model succeeds

    def _fake_resolve(*, operation, preferred_provider, requested_tier, **kwargs):
        if requested_tier == "mid":
            return escalation_route
        raise LLMRoutingError("unexpected tier in test")

    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _fake_complete)
    monkeypatch.setattr(storyboard_service, "resolve_llm_route", _fake_resolve)

    before_attempted = _read_escalation_counter("generate", "anthropic", "attempted")
    before_succeeded = _read_escalation_counter("generate", "anthropic", "succeeded")

    result = await _run_storyboard_completion(
        source, "generate", primary_route=primary_route
    )

    assert result is escalation_payload
    after_attempted = _read_escalation_counter("generate", "anthropic", "attempted")
    after_succeeded = _read_escalation_counter("generate", "anthropic", "succeeded")
    assert after_attempted - before_attempted == 1.0
    assert after_succeeded - before_succeeded == 1.0


@pytest.mark.asyncio
async def test_storyboard_primary_timeout_not_escalated(monkeypatch):
    """Primary timeout must NOT trigger escalation — surface the error directly.

    The escalation tier is slower and more expensive; escalating a timed-out
    primary attempt would likely also time out, burning the user's credit
    without benefit.
    """
    source = _make_source("anthropic")
    primary_route = _make_primary_route("anthropic")

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
        await _run_storyboard_completion(
            source, "generate", primary_route=primary_route
        )

    assert "timed out" in exc_info.value.summary
    assert len(resolve_called) == 0, "resolve_llm_route must not be called on timeout"
    assert (
        _read_escalation_counter("generate", "anthropic", "attempted")
        == before_attempted
    )


@pytest.mark.asyncio
async def test_storyboard_google_no_escalation_route_skipped(monkeypatch):
    """Google floors at mid (Flash) with no active strong escalation model.

    When the primary attempt fails with a quality error and the escalation tier
    (strong) routing raises ``LLMRoutingError``, the ``no_route`` outcome is
    recorded and the original failure is re-raised.  ``attempted`` stays flat.
    """
    source = _make_source("google")
    primary_route = _make_primary_route("google")

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
            source, "regenerate_section", primary_route=primary_route
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
async def test_storyboard_postprocess_failure_triggers_escalation(monkeypatch):
    """A postprocess error (e.g. splice validation) is treated as a quality failure.

    The cheap primary may produce a section that fails the splice re-validation.
    The postprocess ``StoryboardPayloadError`` must trigger mid escalation just
    like a schema failure from ``_complete_and_validate``.
    """
    source = _make_source("anthropic")
    primary_route = _make_primary_route("anthropic")
    escalation_route = _make_escalation_route()
    primary_payload = MagicMock(spec=StoryboardPayload)
    escalation_payload = MagicMock(spec=StoryboardPayload)

    call_count = {"complete": 0, "postprocess": 0}

    async def _fake_complete(src, *, provider=None, model=None, model_tier="unknown"):
        call_count["complete"] += 1
        return primary_payload if model_tier == "small" else escalation_payload

    def _postprocess(payload: StoryboardPayload) -> StoryboardPayload:
        call_count["postprocess"] += 1
        if payload is primary_payload:
            raise StoryboardPayloadError(
                "schema", "spliced section payload failed validation"
            )
        return escalation_payload  # escalation payload passes splice

    def _fake_resolve(*, operation, preferred_provider, requested_tier, **kwargs):
        if requested_tier == "mid":
            return escalation_route
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
        source,
        "regenerate_section",
        primary_route=primary_route,
        postprocess=_postprocess,
    )

    assert result is escalation_payload
    assert call_count["complete"] == 2  # primary + escalation
    # once for primary (fails the splice), once for the escalation payload
    assert call_count["postprocess"] == 2
    after_attempted = _read_escalation_counter(
        "regenerate_section", "anthropic", "attempted"
    )
    after_succeeded = _read_escalation_counter(
        "regenerate_section", "anthropic", "succeeded"
    )
    assert after_attempted - before_attempted == 1.0
    assert after_succeeded - before_succeeded == 1.0


# ---------------------------------------------------------------------------
# P3.3 — per-attempt output budget + one-shot truncation-doubling retry
# ---------------------------------------------------------------------------


def test_doubled_output_budget_clamps_to_model_ceiling() -> None:
    from services.pipeline.storyboard_service import _doubled_output_budget

    # Haiku's catalog output ceiling is 64000; a 32768 budget doubles to 65536
    # and clamps to 64000.
    assert (
        _doubled_output_budget("anthropic", "claude-haiku-4-5-20251001", 32768) == 64000
    )
    # Already at the ceiling -> unchanged, so the caller skips the retry.
    assert (
        _doubled_output_budget("anthropic", "claude-haiku-4-5-20251001", 64000) == 64000
    )
    # Unknown model -> doubled without a clamp (routing already accepted it).
    assert _doubled_output_budget("anthropic", "no-such-model", 1000) == 2000


@pytest.mark.asyncio
async def test_complete_and_validate_doubles_budget_on_truncation(monkeypatch):
    """A truncated first completion triggers exactly one doubled-budget retry.

    The retry runs BEFORE the repair loop and its (larger) output is what gets
    validated. Isolated from validation by stubbing ``_parse_validate_and_ground``
    so only the completion + truncation path is under test.
    """
    source = _make_source("anthropic")
    calls: list[int] = []
    truncated = '{"title": "X", "theme": {"palette":'  # cut off, no closing brace

    async def _fake_complete(provider, model, system, user, max_tokens, **kwargs):
        calls.append(max_tokens)
        return truncated if len(calls) == 1 else '{"ok": true}'

    sentinel = object()
    captured: dict[str, str] = {}

    async def _fake_parse(raw, src, *, repair):
        captured["raw"] = raw
        return sentinel

    monkeypatch.setattr(storyboard_service, "complete_with_timeout", _fake_complete)
    monkeypatch.setattr(storyboard_service, "_parse_validate_and_ground", _fake_parse)

    before = _read_truncation_counter("anthropic")
    result = await storyboard_service._complete_and_validate(
        source,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        model_tier="small",
    )

    assert result is sentinel
    assert len(calls) == 2  # initial + exactly one doubled retry
    assert calls[0] == 32768  # storyboard.generate budget, clamped to 64000 ceiling
    assert calls[1] == 64000  # doubled (65536) then clamped to the ceiling
    assert captured["raw"] == '{"ok": true}'  # the retry's output is validated
    assert _read_truncation_counter("anthropic") - before == 1.0


@pytest.mark.asyncio
async def test_complete_and_validate_no_retry_when_not_truncated(monkeypatch):
    """A complete first response (ends on a closing brace) skips the retry."""
    source = _make_source("anthropic")
    calls: list[int] = []

    async def _fake_complete(provider, model, system, user, max_tokens, **kwargs):
        calls.append(max_tokens)
        return '{"complete": true}'

    async def _fake_parse(raw, src, *, repair):
        return object()

    monkeypatch.setattr(storyboard_service, "complete_with_timeout", _fake_complete)
    monkeypatch.setattr(storyboard_service, "_parse_validate_and_ground", _fake_parse)

    before = _read_truncation_counter("anthropic")
    await storyboard_service._complete_and_validate(
        source,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        model_tier="small",
    )

    assert len(calls) == 1  # no retry
    assert _read_truncation_counter("anthropic") == before
