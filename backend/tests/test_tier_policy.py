"""Tests for the product-wide cheap-primary tier policy (issue #17 follow-up).

These lock the single source of truth that core generation, the storyboard
keynote, and increment generation all read, plus the anti-drift guarantee that
``stage_manager``'s core-gen view stays byte-identical to the shared helper.
"""

from __future__ import annotations

import pytest

from services.llm import tier_policy
from services.llm.tier_policy import DEFAULT_TIER_POLICY, generation_tier_policy
from services.pipeline import stage_manager


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("anthropic", ("small", "mid")),
        ("openai", ("mini", "mid")),
        ("google", ("mid", "strong")),
    ],
)
def test_cheap_primary_live_policy(provider, expected, monkeypatch):
    # Default (cheap-primary live): each provider starts at its catalog cheap
    # floor and escalates one tier.
    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", True)
    assert generation_tier_policy(provider) == expected


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google"])
def test_flag_off_reverts_every_provider_to_mid_first(provider, monkeypatch):
    # One toggle reverts every feature to the pre-cheap-swap mid→strong default.
    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", False)
    assert generation_tier_policy(provider) == DEFAULT_TIER_POLICY == ("mid", "strong")


def test_unknown_provider_falls_back_to_mid_first(monkeypatch):
    # An unrecognised provider is never silently downgraded.
    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", True)
    assert generation_tier_policy("acme") == ("mid", "strong")


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google"])
@pytest.mark.parametrize("cheap_primary", [True, False])
def test_shared_policy_matches_stage_manager_core_view(
    provider, cheap_primary, monkeypatch
):
    # Anti-drift: stage_manager's core-gen policy is the same shared helper, so
    # the two can never diverge under either flag state.
    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", cheap_primary)
    shared = generation_tier_policy(provider)
    core_view = stage_manager._core_generation_tier_policy(provider)
    assert shared == core_view
