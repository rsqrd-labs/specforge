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
    usage = normalize_provider_usage(
        "anthropic",
        {
            "input_tokens": 1000,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 100,
            "output_tokens": 200,
        },
    )

    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 400
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


def test_estimate_tokens_is_deterministic() -> None:
    assert estimate_tokens("openai", "gpt-4o-mini", "abcd") == 1
    assert estimate_tokens("openai", "gpt-4o-mini", "abcde") == 2
