"""LLM token usage normalisation and cost estimation utilities.

This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
timeout= enforcement is delegated to each concrete adapter implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from services.llm.cost_registry import get_model_cost

UsageEstimationMethod = Literal["provider_reported", "tokenizer_estimated", "unknown"]


@dataclass(frozen=True)
class NormalizedUsage:
    # Cross-provider contract: input_tokens is the TOTAL prompt the model saw,
    # cache activity included; cached_input_tokens (cache READS, priced at the
    # read-discount rate) and cache_write_input_tokens (cache WRITES, priced at
    # the write-premium rate) are both subsets of it.
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    provider_usage_raw: dict | None
    usage_estimation_method: UsageEstimationMethod
    # Observability breakout only: reasoning/thinking tokens are ALREADY
    # included in output_tokens and billed at the output rate, so this value is
    # never added to estimate_cost_usd (that would double-count).
    reasoning_tokens: int | None = None
    # Prompt-cache WRITE tokens (issue #82). Anthropic charges cache creation
    # at a premium over the base input rate (5m TTL 1.25x, 1h TTL 2x) while
    # only cache reads get the discount, so writes must never be folded into
    # cached_input_tokens. None for providers without a write premium.
    cache_write_input_tokens: int | None = None


def normalize_provider_usage(provider: str, raw_usage: Any) -> NormalizedUsage:
    if raw_usage is None:
        return NormalizedUsage(
            input_tokens=None,
            cached_input_tokens=None,
            output_tokens=None,
            provider_usage_raw=None,
            usage_estimation_method="unknown",
        )

    usage = _to_dict(raw_usage)
    if provider == "openai":
        return _normalize_openai_usage(usage)
    if provider == "anthropic":
        return _normalize_anthropic_usage(usage)
    if provider == "google":
        return _normalize_google_usage(usage)
    if provider == "openrouter":
        # Plain OpenAI-shape delegation (issue #152 Phase 1). OpenRouter's
        # chat-completions usage object nests cached-read tokens under
        # prompt_tokens_details.cached_tokens — the same field
        # _normalize_openai_usage already reads — so cache READS are
        # captured correctly from day one. cache_write_input_tokens is
        # deliberately left unpopulated here: this is the safe branch either
        # way (see services/llm/openrouter_adapter.py's module docstring) —
        # it never risks the None-rate/nonzero-tokens trap in
        # estimate_cost_usd below, at the cost of a small under-count if
        # OpenRouter ever reports genuine cache-write tokens.
        return _normalize_openai_usage(usage)

    return NormalizedUsage(
        input_tokens=_int_or_none(usage.get("input_tokens")),
        cached_input_tokens=_int_or_none(usage.get("cached_input_tokens")),
        output_tokens=_int_or_none(usage.get("output_tokens")),
        provider_usage_raw=usage,
        usage_estimation_method="provider_reported",
        reasoning_tokens=_int_or_none(usage.get("reasoning_tokens")),
        cache_write_input_tokens=_int_or_none(usage.get("cache_write_input_tokens")),
    )


def estimate_tokens(provider: str, model: str, text: str) -> int | None:
    del provider, model
    if not text:
        return 0
    # Conservative tokenizer fallback used only when the provider does not
    # report usage. It is intentionally labelled as estimated in telemetry.
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def estimate_cost_usd(
    provider: str,
    model: str,
    usage: NormalizedUsage,
    *,
    batch: bool = False,
) -> Decimal | None:
    """Estimate USD cost for a call's token usage.

    ``batch=True`` applies the provider Message Batches 50% discount (Anthropic
    and OpenAI both halve input *and* output token rates for batched requests),
    so a genuinely batched call records ~half the cost of the same real-time
    call. Only the deferred-batch collect path sets this — the synchronous
    fallback runs at full price and must leave it False (no double-discount).
    """
    cost = get_model_cost(provider, model)
    input_tokens = usage.input_tokens
    cached_input_tokens = usage.cached_input_tokens or 0
    cache_write_tokens = usage.cache_write_input_tokens or 0
    output_tokens = usage.output_tokens

    if (
        input_tokens is None
        and cached_input_tokens == 0
        and cache_write_tokens == 0
        and output_tokens is None
    ):
        return None

    uncached_input_tokens = max(
        (input_tokens or 0) - cached_input_tokens - cache_write_tokens, 0
    )
    # Cache writes are priced per TTL (issue #82): the provider's
    # ``cache_creation`` breakdown in the raw usage splits 5m/1h write tokens;
    # without a consistent breakdown all writes are priced at the default 5m
    # rate (the only TTL our adapters request).
    write_5m_tokens, write_1h_tokens = _cache_write_ttl_split(
        cache_write_tokens, usage.provider_usage_raw
    )
    if (
        (uncached_input_tokens and cost["input_cost_per_million"] is None)
        or (cached_input_tokens and cost["cached_input_cost_per_million"] is None)
        or (write_5m_tokens and cost.get("cache_write_5m_cost_per_million") is None)
        or (write_1h_tokens and cost.get("cache_write_1h_cost_per_million") is None)
        or ((output_tokens or 0) and cost["output_cost_per_million"] is None)
    ):
        return None

    total = Decimal("0")
    total += _token_cost(
        uncached_input_tokens,
        cost["input_cost_per_million"],
    )
    total += _token_cost(
        cached_input_tokens,
        cost["cached_input_cost_per_million"],
    )
    total += _token_cost(
        write_5m_tokens,
        cost.get("cache_write_5m_cost_per_million"),
    )
    total += _token_cost(
        write_1h_tokens,
        cost.get("cache_write_1h_cost_per_million"),
    )
    total += _token_cost(
        output_tokens or 0,
        cost["output_cost_per_million"],
    )
    if batch:
        # Provider Message Batches discount: 50% off all token usage.
        total *= Decimal("0.5")
    return total


def estimated_usage_from_text(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    output: str,
) -> NormalizedUsage:
    input_text = f"{system}\n{user}"
    return NormalizedUsage(
        input_tokens=estimate_tokens(provider, model, input_text),
        cached_input_tokens=None,
        output_tokens=estimate_tokens(provider, model, output),
        provider_usage_raw=None,
        usage_estimation_method="tokenizer_estimated",
    )


def _normalize_openai_usage(usage: dict) -> NormalizedUsage:
    # Chat Completions nests cached tokens under ``prompt_tokens_details``; the
    # Responses API (used by gpt-5.4-mini, the OpenAI core-gen primary) nests
    # them under ``input_tokens_details``. Read either so automatic prefix-cache
    # hits are captured for both APIs — without the fallback, Responses-API
    # models report ``cached_input_tokens == 0`` even on perfect hits and the
    # cost ledger prices cached input at the full uncached rate.
    details = _to_dict(
        usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
    )
    # Reasoning tokens live under completion_tokens_details (Chat Completions)
    # or output_tokens_details (Responses API); both are already counted inside
    # completion/output_tokens.
    output_details = _to_dict(
        usage.get("completion_tokens_details") or usage.get("output_tokens_details")
    )
    return NormalizedUsage(
        input_tokens=_first_int(usage, "prompt_tokens", "input_tokens"),
        cached_input_tokens=_first_int(details, "cached_tokens", "cached_input_tokens"),
        output_tokens=_first_int(
            usage,
            "completion_tokens",
            "output_tokens",
        ),
        provider_usage_raw=usage,
        usage_estimation_method="provider_reported",
        reasoning_tokens=_first_int(output_details, "reasoning_tokens"),
    )


def _normalize_anthropic_usage(usage: dict) -> NormalizedUsage:
    # Anthropic reports three DISJOINT input components (issue #82): base
    # ``input_tokens`` (excludes all cache activity, unlike OpenAI/Google whose
    # prompt counts include cached tokens), ``cache_read_input_tokens``
    # (discounted), and ``cache_creation_input_tokens`` (premium-priced
    # writes). Normalise to the cross-provider contract: input_tokens = the
    # full prompt (base + read + write), with reads and writes broken out
    # separately so each is priced at its own rate.
    base_input = _first_int(usage, "input_tokens")
    cache_read = _first_int(usage, "cache_read_input_tokens")
    cache_write = _first_int(usage, "cache_creation_input_tokens")
    components = [
        value for value in (base_input, cache_read, cache_write) if value is not None
    ]
    return NormalizedUsage(
        input_tokens=sum(components) if components else None,
        cached_input_tokens=cache_read or None,
        output_tokens=_first_int(usage, "output_tokens"),
        provider_usage_raw=usage,
        usage_estimation_method="provider_reported",
        cache_write_input_tokens=cache_write or None,
    )


def _normalize_google_usage(usage: dict) -> NormalizedUsage:
    candidates = _first_int(usage, "candidatesTokenCount", "candidates_token_count")
    thoughts = _first_int(usage, "thoughtsTokenCount", "thoughts_token_count") or 0
    return NormalizedUsage(
        input_tokens=_first_int(usage, "promptTokenCount", "prompt_token_count"),
        cached_input_tokens=_first_int(
            usage,
            "cachedContentTokenCount",
            "cached_content_token_count",
        ),
        output_tokens=(candidates + thoughts) if candidates is not None else thoughts,
        provider_usage_raw=usage,
        usage_estimation_method="provider_reported",
        # thoughtsTokenCount is already folded into output_tokens above.
        reasoning_tokens=(thoughts or None),
    )


def _cache_write_ttl_split(total: int, raw_usage: dict | None) -> tuple[int, int]:
    """Split cache-write tokens into ``(5m, 1h)`` for TTL-specific pricing.

    Anthropic's ``cache_creation`` usage object breaks the write total down by
    TTL (``ephemeral_5m_input_tokens`` / ``ephemeral_1h_input_tokens``). The
    breakdown is only trusted when it reconciles with the total; otherwise
    every write token is priced at the 5m rate — the default TTL, and the only
    one our adapters request (``cache_control: {"type": "ephemeral"}``).
    """
    if total <= 0:
        return 0, 0
    breakdown = _to_dict((raw_usage or {}).get("cache_creation"))
    write_5m = _int_or_none(breakdown.get("ephemeral_5m_input_tokens")) or 0
    write_1h = _int_or_none(breakdown.get("ephemeral_1h_input_tokens")) or 0
    if write_5m >= 0 and write_1h >= 0 and write_5m + write_1h == total:
        return write_5m, write_1h
    return total, 0


def _token_cost(tokens: int, cost_per_million: float | int | None) -> Decimal:
    if tokens <= 0 or cost_per_million is None:
        return Decimal("0")
    return (Decimal(tokens) / Decimal(1_000_000)) * Decimal(str(cost_per_million))


def _first_int(mapping: dict, *keys: str) -> int | None:
    for key in keys:
        value = _int_or_none(mapping.get(key))
        if value is not None:
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "__dict__"):
        return {
            key: item for key, item in vars(value).items() if not key.startswith("_")
        }
    return {}
