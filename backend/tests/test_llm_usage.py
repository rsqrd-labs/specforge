from __future__ import annotations

from decimal import Decimal

from services.llm.usage import (
    NormalizedUsage,
    estimate_cost_usd,
    estimate_tokens,
    estimated_usage_from_text,
    normalize_provider_usage,
)


def test_normalizes_openai_usage_with_cached_tokens() -> None:
    usage = normalize_provider_usage(
        "openai",
        {
            "prompt_tokens": 1000,
            "completion_tokens": 250,
            "prompt_tokens_details": {"cached_tokens": 600},
        },
    )

    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 600
    assert usage.output_tokens == 250
    assert usage.usage_estimation_method == "provider_reported"


def test_normalizes_openai_usage_responses_api() -> None:
    # The Responses API (gpt-5.4-mini, the OpenAI core-gen primary) reports
    # cached tokens under input_tokens_details, not prompt_tokens_details.
    usage = normalize_provider_usage(
        "openai",
        {
            "input_tokens": 1000,
            "output_tokens": 250,
            "input_tokens_details": {"cached_tokens": 600},
            "output_tokens_details": {"reasoning_tokens": 40},
        },
    )

    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 600
    assert usage.output_tokens == 250
    assert usage.reasoning_tokens == 40
    assert usage.usage_estimation_method == "provider_reported"


def test_normalizes_anthropic_usage_with_cache_tokens() -> None:
    # Anthropic's input_tokens EXCLUDES cache activity (unlike OpenAI/Google),
    # so normalization totals base + read + write into input_tokens and keeps
    # reads and writes separate — writes are premium-priced, never discounted
    # (issue #82).
    usage = normalize_provider_usage(
        "anthropic",
        {
            "input_tokens": 1000,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 100,
            "output_tokens": 200,
        },
    )

    assert usage.input_tokens == 1400
    assert usage.cached_input_tokens == 300
    assert usage.cache_write_input_tokens == 100
    assert usage.output_tokens == 200


def test_normalizes_anthropic_usage_without_cache_tokens() -> None:
    usage = normalize_provider_usage(
        "anthropic",
        {"input_tokens": 1000, "output_tokens": 200},
    )

    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens is None
    assert usage.cache_write_input_tokens is None
    assert usage.output_tokens == 200


def test_normalizes_google_usage_including_thought_tokens() -> None:
    usage = normalize_provider_usage(
        "google",
        {
            "promptTokenCount": 1000,
            "cachedContentTokenCount": 700,
            "candidatesTokenCount": 100,
            "thoughtsTokenCount": 50,
        },
    )

    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 700
    assert usage.output_tokens == 150


def test_unknown_usage_is_marked_unknown() -> None:
    usage = normalize_provider_usage("openai", None)

    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.usage_estimation_method == "unknown"


def test_estimated_usage_from_text_is_labelled_estimated() -> None:
    usage = estimated_usage_from_text(
        provider="openai",
        model="gpt-4o-mini",
        system="system prompt",
        user="user prompt",
        output="model output",
    )

    assert usage.input_tokens is not None
    assert usage.output_tokens is not None
    assert usage.usage_estimation_method == "tokenizer_estimated"


def test_estimate_cost_uses_uncached_cached_and_output_rates() -> None:
    usage = NormalizedUsage(
        input_tokens=1000,
        cached_input_tokens=600,
        output_tokens=250,
        provider_usage_raw=None,
        usage_estimation_method="provider_reported",
    )

    cost = estimate_cost_usd("openai", "gpt-4o-mini", usage)

    assert cost == Decimal("0.0002550")


def test_cost_is_none_when_usage_is_unknown() -> None:
    usage = NormalizedUsage(
        input_tokens=None,
        cached_input_tokens=None,
        output_tokens=None,
        provider_usage_raw=None,
        usage_estimation_method="unknown",
    )

    assert estimate_cost_usd("openai", "gpt-4o-mini", usage) is None


# --- Issue #82 acceptance: official Anthropic worked pricing examples -------
# Claude Haiku 4.5 catalog rates per MTok: input $1.00, cache read $0.10,
# 5m cache write $1.25 (1.25x input), 1h cache write $2.00 (2x input),
# output $5.00.

_HAIKU = "claude-haiku-4-5-20251001"


def _anthropic_cost(raw_usage: dict) -> Decimal | None:
    return estimate_cost_usd(
        "anthropic", _HAIKU, normalize_provider_usage("anthropic", raw_usage)
    )


def test_anthropic_pricing_no_cache() -> None:
    cost = _anthropic_cost({"input_tokens": 100_000, "output_tokens": 10_000})

    # 100K * $1/M + 10K * $5/M = 0.10 + 0.05
    assert cost == Decimal("0.15")


def test_anthropic_pricing_cache_read_hit() -> None:
    cost = _anthropic_cost(
        {
            "input_tokens": 1_000,
            "cache_read_input_tokens": 100_000,
            "output_tokens": 10_000,
        }
    )

    # 1K base * $1/M + 100K read * $0.10/M + 10K out * $5/M
    assert cost == Decimal("0.001") + Decimal("0.01") + Decimal("0.05")


def test_anthropic_pricing_5m_cache_write() -> None:
    cost = _anthropic_cost(
        {
            "input_tokens": 1_000,
            "cache_creation_input_tokens": 100_000,
            "output_tokens": 10_000,
        }
    )

    # 1K base * $1/M + 100K write * $1.25/M (5m premium, NOT the read
    # discount) + 10K out * $5/M
    assert cost == Decimal("0.001") + Decimal("0.125") + Decimal("0.05")


def test_anthropic_pricing_1h_cache_write_uses_ttl_breakdown() -> None:
    cost = _anthropic_cost(
        {
            "input_tokens": 1_000,
            "cache_creation_input_tokens": 100_000,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 0,
                "ephemeral_1h_input_tokens": 100_000,
            },
            "output_tokens": 10_000,
        }
    )

    # 1K base * $1/M + 100K write * $2/M (1h premium) + 10K out * $5/M
    assert cost == Decimal("0.001") + Decimal("0.2") + Decimal("0.05")


def test_anthropic_pricing_mixed_read_and_write() -> None:
    cost = _anthropic_cost(
        {
            "input_tokens": 2_000,
            "cache_read_input_tokens": 50_000,
            "cache_creation_input_tokens": 30_000,
            "output_tokens": 5_000,
        }
    )

    # 2K base * $1/M + 50K read * $0.10/M + 30K write * $1.25/M
    # + 5K out * $5/M
    expected = (
        Decimal("0.002") + Decimal("0.005") + Decimal("0.0375") + Decimal("0.025")
    )
    assert cost == expected


def test_anthropic_pricing_inconsistent_ttl_breakdown_defaults_to_5m() -> None:
    # A breakdown that does not reconcile with the total is untrusted; every
    # write token falls back to the default 5m rate.
    cost = _anthropic_cost(
        {
            "input_tokens": 0,
            "cache_creation_input_tokens": 100_000,
            "cache_creation": {"ephemeral_1h_input_tokens": 40_000},
            "output_tokens": 0,
        }
    )

    assert cost == Decimal("0.125")


def test_anthropic_historical_raw_usage_reconciles() -> None:
    # Reconciliation path for pre-fix ledger rows: re-normalizing the persisted
    # provider_usage_raw dict yields the corrected token split and price.
    raw = {
        "input_tokens": 1_000,
        "cache_read_input_tokens": 300,
        "cache_creation_input_tokens": 100,
        "output_tokens": 200,
    }
    usage = normalize_provider_usage("anthropic", raw)

    assert usage.provider_usage_raw == raw
    reconciled = normalize_provider_usage("anthropic", usage.provider_usage_raw)
    assert reconciled == usage
    assert estimate_cost_usd("anthropic", _HAIKU, reconciled) == (
        # 1K base * $1/M + 300 read * $0.10/M + 100 write * $1.25/M
        # + 200 out * $5/M
        Decimal("0.001")
        + Decimal("0.00003")
        + Decimal("0.000125")
        + Decimal("0.001")
    )


def test_cache_write_without_write_rate_returns_none() -> None:
    # Providers/models without a cache-write rate cannot price write tokens;
    # the estimate degrades to None rather than silently mispricing.
    usage = NormalizedUsage(
        input_tokens=1_000,
        cached_input_tokens=None,
        output_tokens=100,
        provider_usage_raw=None,
        usage_estimation_method="provider_reported",
        cache_write_input_tokens=500,
    )

    assert estimate_cost_usd("openai", "gpt-4o-mini", usage) is None


def test_estimate_tokens_is_deterministic() -> None:
    assert estimate_tokens("openai", "gpt-4o-mini", "abcd") == 1
    assert estimate_tokens("openai", "gpt-4o-mini", "abcde") == 2


# --- openrouter (issue #152) -------------------------------------------------


def test_normalizes_openrouter_usage_with_cache_reads_and_writes() -> None:
    """OpenRouter reports BOTH cached_tokens (reads) and cache_write_tokens
    under prompt_tokens_details. The OpenAI normaliser reads only the first, so
    delegating to it left every write token priced as uncached input."""
    usage = normalize_provider_usage(
        "openrouter",
        {
            "prompt_tokens": 10_000,
            "completion_tokens": 2_000,
            "prompt_tokens_details": {
                "cached_tokens": 6_000,
                "cache_write_tokens": 1_000,
            },
            "completion_tokens_details": {"reasoning_tokens": 500},
        },
    )

    # prompt_tokens INCLUDES both cache buckets (the OpenAI convention, not
    # Anthropic's disjoint one), so estimate_cost_usd subtracts them off.
    assert usage.input_tokens == 10_000
    assert usage.cached_input_tokens == 6_000
    assert usage.cache_write_input_tokens == 1_000
    assert usage.output_tokens == 2_000
    assert usage.reasoning_tokens == 500
    assert usage.usage_estimation_method == "provider_reported"


def test_openrouter_cache_hit_is_visibly_cheaper_in_the_ledger() -> None:
    """The point of the whole pinning exercise: a cache hit must show up as a
    lower recorded cost. The retired entries set cached_input == input, so a
    perfect hit cost exactly the same as a miss and the ledger could not
    measure the thing the provider switch was for."""
    model = "deepseek/deepseek-v4-flash"
    hit = normalize_provider_usage(
        "openrouter",
        {
            "prompt_tokens": 10_000,
            "completion_tokens": 2_000,
            "prompt_tokens_details": {"cached_tokens": 6_000},
        },
    )
    miss = normalize_provider_usage(
        "openrouter", {"prompt_tokens": 10_000, "completion_tokens": 2_000}
    )

    hit_cost = estimate_cost_usd("openrouter", model, hit)
    miss_cost = estimate_cost_usd("openrouter", model, miss)
    assert hit_cost is not None and miss_cost is not None
    assert hit_cost < miss_cost
    # uncached 4_000*0.14 + cached 6_000*0.0028 + output 2_000*0.28, per million
    assert hit_cost == Decimal("0.00056") + Decimal("0.0000168") + Decimal("0.00056")


def test_openrouter_cache_writes_are_priced_not_dropped() -> None:
    """Populating cache_write_input_tokens is only safe because every openrouter
    entry carries a non-None cache_write_5m rate — otherwise estimate_cost_usd
    returns None and the ledger records NO cost at all (the trap the original
    adapter avoided by never populating writes)."""
    usage = normalize_provider_usage(
        "openrouter",
        {
            "prompt_tokens": 5_000,
            "completion_tokens": 1_000,
            "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 2_000},
        },
    )

    for model in ("deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro"):
        assert estimate_cost_usd("openrouter", model, usage) is not None
