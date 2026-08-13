from __future__ import annotations

import pytest

from services.llm import model_catalog as catalog_module
from services.llm.model_catalog import (
    CORE_GENERATION_OPERATIONS,
    CORE_GENERATION_TIER_LADDER,
    MODEL_CATALOG,
    REQUIRED_PROVIDERS,
    core_generation_ladder,
    core_generation_tier_policy,
    default_model_for_operation,
    iter_model_entries,
    model_entry,
    model_request_policy,
    validate_core_generation_ladder,
    validate_model_catalog,
)


def test_catalog_validates_at_startup() -> None:
    validate_model_catalog()


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-5.4-mini"),
        ("google", "gemini-3.6-flash"),
        ("openrouter", "deepseek/deepseek-v4-flash"),
    ],
)
def test_core_generation_defaults_are_cheap_primary_models(
    provider: str,
    expected_model: str,
) -> None:
    for operation in CORE_GENERATION_OPERATIONS:
        assert default_model_for_operation(provider, operation) == expected_model


def test_no_deprecated_model_is_an_active_default() -> None:
    deprecated_ids = {
        "claude-opus-4-7",
        "gpt-4o",
        "gpt-4o-mini",
        "o1-preview",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        # Superseded by the Gemini 3.6 Flash / 3.5 Flash-Lite cutover. Retained
        # in the catalog (deprecate-don't-delete) so historical cost-ledger and
        # stage rows still resolve an entry, but never routable again.
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    }

    for entry in MODEL_CATALOG:
        if entry.model_id in deprecated_ids:
            assert entry.status == "deprecated"
            assert entry.default_operations == ()


def test_preview_gemini_models_are_cataloged_but_not_production_defaults() -> None:
    for model_id in ("gemini-3.1-pro-preview", "gemini-3-flash-preview"):
        entry = model_entry("google", model_id)

        assert entry.status == "preview"
        assert entry.default_operations == ()


# --- Phase 5b: core-generation tier ladder -----------------------------------


def test_every_required_provider_declares_a_ladder() -> None:
    assert set(CORE_GENERATION_TIER_LADDER) == set(REQUIRED_PROVIDERS)


def test_derived_policy_is_byte_identical_to_shipped_cheap_primary() -> None:
    # Phase 5b is a *behavior-preserving* normalization: deriving the live
    # cheap-primary policy from the catalog ladder must reproduce exactly what
    # Phase 5 shipped as a hand-maintained dict. If this changes, a model
    # actually runs differently and the Phase-5 golden-corpus gate is required.
    assert core_generation_tier_policy("anthropic") == ("small", "mid")
    assert core_generation_tier_policy("openai") == ("mini", "mid")
    assert core_generation_tier_policy("google") == ("mid", "strong")
    assert core_generation_tier_policy("openrouter") == ("mid", "strong")


def test_stage_manager_policy_derives_from_catalog_ladder() -> None:
    from services.pipeline import stage_manager

    for provider in REQUIRED_PROVIDERS:
        assert stage_manager.CORE_GENERATION_TIER_POLICY[provider] == (
            core_generation_tier_policy(provider)
        )


def test_google_judge_model_is_flash_lite_not_the_core_gen_primary() -> None:
    """The Google judge/eval path must stay on the cheap small tier.

    ``provider_config.JUDGE_MODELS`` is derived from
    ``default_model_for_operation(provider, "eval.score")``. If the mid entry
    (3.6 Flash) ever declares ``eval.score``, routing_priority 1 would beat
    Flash-Lite's 30 and every judge/critic/eval call would silently move onto
    the 5x-more-expensive core-generation model.
    """
    from services.llm.provider_config import JUDGE_MODELS

    assert JUDGE_MODELS["google"] == "gemini-3.5-flash-lite"
    flash = model_entry("google", "gemini-3.6-flash")
    assert "eval.score" not in flash.recommended_operations
    assert "summary.create" not in flash.recommended_operations


def test_google_flash_lite_uses_minimal_thinking_for_tight_judge_budgets() -> None:
    """Gemini bills thought tokens against ``max_output_tokens``.

    Every operation that lands on Flash-Lite runs on a tight budget
    (eval.score 1024, call_judge_model 2048, summary.create 2048). A higher
    thinking level lets a reasoning burst consume the whole budget and return
    finish_reason=MAX_TOKENS with empty text.
    """
    assert model_entry("google", "gemini-3.5-flash-lite").thinking_level == "minimal"
    for operation in ("eval.score", "summary.create", None):
        policy = model_request_policy("google", "gemini-3.5-flash-lite", operation)
        assert policy["thinking_level"] == "minimal"


def test_google_focused_refine_budget_clears_thinking_overhead() -> None:
    """On Google, ``refine.focused`` resolves to the MID entry (3.6 Flash at
    thinking_level="high"), not to Flash-Lite — the ``small`` tier is
    unreachable because Google's tier policy is ("mid", "strong").

    At the 768-token cross-provider default, thinking alone exhausts the budget.
    The per-(operation, provider) override must keep real headroom, and must not
    leak onto the other providers, whose refine models are not billed this way.
    """
    from services.llm.output_budget import resolve_output_budget

    google_budget = resolve_output_budget(
        "refine.focused", provider="google", model="gemini-3.6-flash"
    )
    assert google_budget >= 4096
    assert (
        resolve_output_budget("refine.focused", provider="openai", model="gpt-5.4-mini")
        == 768
    )


def test_google_floor_stays_mid_flash_lite_is_not_a_core_gen_default() -> None:
    # Flash-Lite (small) exists and is active, but is deliberately NOT a core-gen
    # default — Google's documented floor is mid (Flash). Lowering it is a routing
    # change gated by the Phase-5 live eval, not a Phase-5b edit.
    assert core_generation_ladder("google")[0] == "mid"
    flash_lite = model_entry("google", "gemini-3.5-flash-lite")
    assert flash_lite.tier == "small"
    assert not any(
        op in flash_lite.default_operations for op in CORE_GENERATION_OPERATIONS
    )


def test_ladders_are_strictly_increasing_in_capability() -> None:
    rank = catalog_module._CORE_TIER_RANK
    for provider, ladder in CORE_GENERATION_TIER_LADDER.items():
        ranks = [rank[tier] for tier in ladder]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks), f"{provider} ladder not strict: {ladder}"


def test_each_primary_tier_resolves_to_exactly_one_active_default() -> None:
    for provider in REQUIRED_PROVIDERS:
        primary_tier = core_generation_ladder(provider)[0]
        actives = [
            entry
            for entry in MODEL_CATALOG
            if entry.provider == provider
            and entry.tier == primary_tier
            and entry.status == "active"
            and any(op in entry.default_operations for op in CORE_GENERATION_OPERATIONS)
        ]
        assert len(actives) == 1, (provider, primary_tier, actives)


def test_ladder_validator_rejects_non_increasing_ladder(monkeypatch) -> None:
    monkeypatch.setitem(CORE_GENERATION_TIER_LADDER, "anthropic", ("mid", "small"))
    with pytest.raises(RuntimeError, match="strictly"):
        validate_core_generation_ladder()


def test_ladder_validator_rejects_unknown_tier(monkeypatch) -> None:
    monkeypatch.setitem(CORE_GENERATION_TIER_LADDER, "openai", ("judge", "mid"))
    with pytest.raises(RuntimeError, match="non-core tier"):
        validate_core_generation_ladder()


def test_ladder_validator_rejects_too_short_ladder(monkeypatch) -> None:
    monkeypatch.setitem(CORE_GENERATION_TIER_LADDER, "google", ("mid",))
    with pytest.raises(RuntimeError, match="primary, fallback"):
        validate_core_generation_ladder()


def test_frontier_adapter_policy_is_explicit() -> None:
    assert model_request_policy("openai", "gpt-5.5") == {
        "adapter_api": "responses",
        "supports_reasoning": True,
        "supports_thinking": False,
        # Medium, not the API default of high — GPT-5.5 is now OpenAI's
        # full-artifact PRIMARY (the fallback reached when Anthropic is
        # unconfigured or its circuit is open), so it runs under the same
        # locked 270s/300s interactive deadline that used to keep Opus 5 on
        # medium too (Opus 5 has since moved to high, unmeasured — see the
        # claude-opus-5 assertion below). A high-effort timeout here would
        # fail exactly when Anthropic is already down, which is the reason
        # GPT-5.5 was deliberately NOT moved to high in the same change.
        "reasoning_effort": "medium",
        "thinking_level": None,
        "automatic_prompt_caching": True,
        "prompt_cache_key": True,
        "extended_prompt_cache_retention": True,
        "cached_token_accounting": True,
        "minimum_cacheable_input_tokens": 1024,
        # Aggregator-only: OpenAI is reached directly, so there is no upstream
        # host to pin (see ModelCatalogEntry.upstream_providers).
        "upstream_providers": (),
        # No operation was passed, so this is not a core-generation call.
        "is_core_generation": False,
    }
    assert (
        model_request_policy("google", "gemini-3.6-flash")["thinking_level"] == "high"
    )
    # Opus 5 runs the four core stages at HIGH effort (since 2026-08-06, a
    # deliberate quality-over-margin trade after medium was judged not up to
    # the mark in production — see the claude-opus-5 catalog entry). The call
    # cap moved to 270s in the same change to give high-effort reasoning more
    # room, but the chunk length targets are still sized against the medium
    # throughput measurement, so this pairing is unmeasured at high effort and
    # may need retargeting if chunks start timing out.
    assert (
        model_request_policy("anthropic", "claude-opus-5")["reasoning_effort"] == "high"
    )


def test_core_generation_low_reasoning_is_flagged_and_operation_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "core_generation_low_reasoning", True)

    # Haiku 4.5 rejects the `effort` parameter, so the override has nothing to
    # lower — it must stay None rather than becoming "low". The GPT-5.4 Mini
    # case below is what covers the effort-lowering path itself.
    assert (
        model_request_policy(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "spec.generate",
        )["reasoning_effort"]
        is None
    )
    assert (
        model_request_policy("openai", "gpt-5.4-mini", "tasks.generate")[
            "reasoning_effort"
        ]
        == "low"
    )
    assert (
        model_request_policy("google", "gemini-3.6-flash", "harness.generate")[
            "thinking_level"
        ]
        == "low"
    )

    # The same cheap primary models keep their catalog policy outside core stage
    # generation, preventing judge/eval/refine/storyboard policy leakage.
    assert (
        model_request_policy(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "refine.focused",
        )["reasoning_effort"]
        is None
    )
    assert (
        model_request_policy("openai", "gpt-5.4-mini", "eval.score")["reasoning_effort"]
        == "medium"
    )
    assert (
        model_request_policy("google", "gemini-3.6-flash", "storyboard.generate")[
            "thinking_level"
        ]
        == "high"
    )


def test_core_generation_low_reasoning_flag_off_preserves_catalog_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "core_generation_low_reasoning", False)

    assert (
        model_request_policy(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "plan.generate",
        )["reasoning_effort"]
        is None
    )
    assert (
        model_request_policy("openai", "gpt-5.4-mini", "tasks.generate")[
            "reasoning_effort"
        ]
        == "medium"
    )
    assert (
        model_request_policy("google", "gemini-3.6-flash", "spec.generate")[
            "thinking_level"
        ]
        == "high"
    )


# --- issue #152: openrouter provider wiring ----------------------------------


_OPENROUTER_ACTIVE_MODELS = (
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
)


def test_openrouter_declared_as_required_provider_with_a_ladder() -> None:
    assert "openrouter" in REQUIRED_PROVIDERS
    # Mirrors GOOGLE's shape, not anthropic/openai's: the floor is `mid`, with
    # no active `small` entry, because every tier must be a pinnable DeepSeek V4
    # slug for prompt caching to exist at all.
    assert CORE_GENERATION_TIER_LADDER["openrouter"] == ("mid", "strong")


def test_openrouter_catalog_entries_use_the_cross_provider_output_convention() -> None:
    for model_id in _OPENROUTER_ACTIVE_MODELS:
        entry = model_entry("openrouter", model_id)
        assert entry.adapter_api == "chat_completions"
        assert entry.status == "active"
        assert entry.default_max_output_tokens == 64000
        assert entry.rollout_notes


def test_openrouter_entries_price_every_token_bucket() -> None:
    """`_normalize_openrouter_usage` populates cache READ *and WRITE* tokens, so
    every rate they can be multiplied by must be non-None. estimate_cost_usd
    returns None — recording NO cost for the call — if any bucket with non-zero
    tokens has a None rate.

    Covers deprecated entries too: a retired model can still be named on
    historical ledger rows that get re-priced.
    """
    for entry in iter_model_entries("openrouter"):
        for field in (
            "input_cost_per_million",
            "cached_input_cost_per_million",
            "output_cost_per_million",
            "cache_write_5m_cost_per_million",
        ):
            assert getattr(entry, field) is not None, f"{entry.model_id}.{field}"
        # 1h writes are unreachable: OpenRouter carries no ephemeral_5m/1h
        # breakdown, so _cache_write_ttl_split attributes 100% to the 5m bucket.
        assert entry.cache_write_1h_cost_per_million is None


def test_every_active_openrouter_entry_pins_an_upstream_host() -> None:
    """Without `provider.only`, OpenRouter load-balances across every host
    serving the slug. On deepseek-v4-flash only 1 of 19 hosts supports prefix
    caching, hosts disagree on real output ceiling by 32x, and catalog rates
    (which are the pinned host's) stop describing what is billed."""
    for model_id in _OPENROUTER_ACTIVE_MODELS:
        entry = model_entry("openrouter", model_id)
        assert entry.upstream_providers, f"{model_id} is unpinned"
        assert model_request_policy("openrouter", model_id)["upstream_providers"] == (
            entry.upstream_providers
        )


def test_openrouter_operation_coverage_matches_the_live_tier_policies() -> None:
    """Every operation a live policy can resolve at a given openrouter tier
    must actually find a model there — the silent-continue trap
    (routing._model_for_operation returns None -> resolve_platform_route_by_
    provider quietly tries the next PROVIDER instead of raising).

    Asserts _model_for_operation directly rather than through
    resolve_platform_route_by_provider/get_llm: is_provider_configured() is
    False for openrouter in CI (no OPENROUTER_API_KEY), so routing through
    the configured-gated resolvers would pass for the wrong reason.
    """
    from services.llm.routing import _model_for_operation

    core_ops = set(CORE_GENERATION_OPERATIONS)
    cheap_ops = {"refine.focused", "refine.section", "storyboard.generate"}

    # mid (deepseek-v4-flash) is the LADDER FLOOR: sole core-gen default, the
    # full cheap ladder, and the judge/summary path. On anthropic/openai those
    # last two live one tier lower, but this provider has no `small`.
    for operation in core_ops | cheap_ops | {"summary.create", "eval.score"}:
        resolved = _model_for_operation("openrouter", "mid", operation)
        assert resolved is not None, f"mid/{operation} did not resolve"
    for operation in ("spec.generate", "eval.score", "refine.section"):
        assert _model_for_operation("openrouter", "mid", operation) == (
            "deepseek/deepseek-v4-flash",
            "active_default",
        )

    # strong (deepseek-v4-pro): full-artifact primary + storyboard escalation
    # slot only — deliberately NOT refine.focused/refine.section (matches the
    # Opus 5 / GPT-5.5 shape; mid always resolves those first).
    for operation in core_ops | {"storyboard.generate"}:
        resolved = _model_for_operation("openrouter", "strong", operation)
        assert resolved is not None, f"strong/{operation} did not resolve"
    assert _model_for_operation("openrouter", "strong", "spec.generate") == (
        "deepseek/deepseek-v4-pro",
        "active_same_tier",
    )
    for operation in (
        "refine.focused",
        "refine.section",
        "summary.create",
        "eval.score",
    ):
        assert _model_for_operation("openrouter", "strong", operation) is None

    # No active `small` entry — the ladder floor is deliberately `mid`.
    for operation in core_ops | cheap_ops | {"summary.create", "eval.score"}:
        assert _model_for_operation("openrouter", "small", operation) is None


def test_openrouter_reasoning_effort_is_gated_on_the_catalog_value() -> None:
    for model_id in _OPENROUTER_ACTIVE_MODELS:
        policy = model_request_policy("openrouter", model_id)
        assert policy["supports_reasoning"] is True
        assert policy["reasoning_effort"] == "medium"


def _cheap_core_default(provider: str):
    """The provider's cheap-ladder primary that holds the core-gen defaults."""
    primary_tier = CORE_GENERATION_TIER_LADDER[provider][0]
    for entry in iter_model_entries(provider):
        if (
            entry.status == "active"
            and entry.tier == primary_tier
            and "spec.generate" in entry.default_operations
        ):
            return entry
    return None


def test_low_reasoning_never_degrades_an_artifact_fallback_tier() -> None:
    """`_LOW_REASONING_CORE_MODELS` must not contain a model that full-artifact
    generation can land on.

    The override exists to cheapen the CHEAP ladder's core generation. On
    anthropic/openai it cannot touch an artifact call by construction: their
    low-reasoning model sits at `small`/`mini`, strictly below the `mid` their
    `_CORE_ARTIFACT_TIER_POLICY` de-escalates to.

    openrouter's two-tier ladder collapses that separation — deepseek-v4-flash
    is the cheap primary AND the artifact fallback — so a row there would run
    the rescue attempt for a failed artifact at minimum reasoning. Worse, since
    core stages route through the artifact policy rather than the cheap ladder,
    that de-escalated retry is the ONLY way flash meets a core operation at all.

    KNOWN VIOLATION, deliberately pinned rather than fixed here: google.
    Its `strong` tier has no active model, so `_route_for_provider` falls
    through to `mid` (Gemini 3.6 Flash) for EVERY full-artifact generation —
    not merely a de-escalated retry — and Flash is low-reasoning registered.
    Its catalog `thinking_level` is "high"; on a core operation it resolves
    "low". That is a live quality bug on the Google failover path, predating
    this test. It is not fixed here because changing it changes which model
    behaviour actually runs, which rides the Phase-5 golden-corpus gate
    (docs/evals/CATALOG_HYGIENE.md). Pinning the set keeps it visible and stops
    anyone joining it by accident.
    """
    from services.llm.model_catalog import _LOW_REASONING_CORE_MODELS
    from services.llm.routing import _model_for_operation
    from services.pipeline.stage_manager import (
        _CORE_ARTIFACT_TIER_POLICY,
        _DEMO_DAY_ARTIFACT_TIER_POLICY,
    )

    known_violations = {"google/gemini-3.6-flash (artifact tier mid)"}

    offenders = set()
    for provider in sorted(REQUIRED_PROVIDERS):
        artifact_tiers = {
            tier
            for table in (_CORE_ARTIFACT_TIER_POLICY, _DEMO_DAY_ARTIFACT_TIER_POLICY)
            for tier in table.get(provider, ())
            if tier
        }
        for tier in artifact_tiers:
            resolved = _model_for_operation(provider, tier, "spec.generate")
            if resolved and (provider, resolved[0]) in _LOW_REASONING_CORE_MODELS:
                offenders.add(f"{provider}/{resolved[0]} (artifact tier {tier})")
    assert offenders == known_violations, (
        f"artifact-serving low-reasoning models changed: {offenders} != "
        f"{known_violations}. Any NEW entry runs a real full-artifact call at "
        "minimum reasoning. Removing the google entry requires the golden-corpus "
        "gate, since it changes which model behaviour actually runs."
    )


def test_cheap_core_defaults_with_an_effort_knob_are_low_reasoning_registered() -> None:
    """A cheap core-gen default that accepts an effort should be registered —
    unless registering it would violate the artifact-fallback rule above, which
    is exactly openrouter's case. Encoding both halves keeps the flag from
    becoming a silent no-op AND from silently degrading an artifact retry.
    """
    from services.llm.model_catalog import _LOW_REASONING_CORE_MODELS
    from services.pipeline.stage_manager import _CORE_ARTIFACT_TIER_POLICY

    for provider in sorted(REQUIRED_PROVIDERS):
        entry = _cheap_core_default(provider)
        if entry is None or entry.reasoning_effort is None:
            continue  # nothing to lower — legitimately absent (Haiku 4.5)
        registered = (provider, entry.model_id) in _LOW_REASONING_CORE_MODELS
        # Exempt when the cheap primary's tier is also an artifact tier.
        exempt = entry.tier in set(_CORE_ARTIFACT_TIER_POLICY.get(provider, ()))
        assert registered != exempt, (
            f"{provider}/{entry.model_id}: registered={registered} exempt={exempt}. "
            "A cheap core-gen default with an effort knob must be low-reasoning "
            "registered, UNLESS its tier is also a full-artifact tier — in which "
            "case registering it would degrade artifact generation."
        )


def test_openrouter_keeps_full_effort_on_every_core_generation_path() -> None:
    """Concretely: neither openrouter model drops to `low` on a core operation,
    so a de-escalated artifact retry reasons at its catalog effort."""
    for model_id in _OPENROUTER_ACTIVE_MODELS:
        for operation in ("spec.generate", "regenerate.full", "harness.generate"):
            policy = model_request_policy("openrouter", model_id, operation)
            assert policy["reasoning_effort"] == "medium", (model_id, operation)
            assert policy["is_core_generation"] is True


def test_low_reasoning_override_still_applies_where_it_is_safe() -> None:
    """The override is not dead. Anthropic's cheap primary (Haiku 4.5, `small`)
    is registered and sits strictly below the `mid` its artifact policy falls
    back to, so it is lowered without ever touching an artifact call.

    Haiku declares no effort knob, so only `supports_thinking` models show a
    visible change — which is the whole reason `model_request_policy` gates on
    the effort VALUE rather than on `supports_reasoning`.
    """
    from services.llm.model_catalog import _LOW_REASONING_CORE_MODELS

    assert ("anthropic", "claude-haiku-4-5-20251001") in _LOW_REASONING_CORE_MODELS
    haiku = model_request_policy(
        "anthropic", "claude-haiku-4-5-20251001", "spec.generate"
    )
    # No effort knob to lower — the override must not invent one.
    assert haiku["reasoning_effort"] is None
    # And the mid tier its artifact policy de-escalates to is untouched.
    assert ("anthropic", "claude-sonnet-5") not in _LOW_REASONING_CORE_MODELS


def test_no_live_call_site_enables_cross_provider_fallback() -> None:
    """Adding openrouter to PROVIDER_CAPABILITY_REGISTRY makes it reachable
    from resolve_llm_route's cross-provider branch (routing.py), which
    iterates ALL registered providers with no is_provider_configured/
    can_route guard — unlike the two platform resolvers. That branch is only
    entered when a caller passes allow_cross_provider=True. Phase 1 must stay
    behaviourally inert while LLM_PROVIDER_PRIORITY omits "openrouter"; this
    pins that no call site anywhere in the backend flips that default so
    something can reach openrouter through that unguarded seam.

    Walks the whole services/ and routers/ tree rather than a fixed file
    list — a hardcoded list of "the current call sites" is exactly the
    vacuous-check shape the openrouter issue's own reviews flagged elsewhere
    (a new call site added later would pass a fixed-list version of this
    test while silently breaking the invariant).
    """
    from conftest import BACKEND_ROOT  # noqa: PLC0415

    offenders = []
    for directory in ("services", "routers"):
        for path in (BACKEND_ROOT / directory).rglob("*.py"):
            if "allow_cross_provider=True" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(BACKEND_ROOT))
    assert not offenders, (
        f"{offenders} enable cross-provider fallback, which would make "
        "openrouter reachable through routing.resolve_llm_route without "
        "an is_provider_configured/can_route guard."
    )
