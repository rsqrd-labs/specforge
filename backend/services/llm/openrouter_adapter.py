"""OpenRouter provider adapter (issue #152).

A thin ``chat_completions`` adapter over the ``openai`` SDK, pointed at
OpenRouter's OpenAI-Chat-Completions-compatible endpoint
(``https://openrouter.ai/api/v1``). This is deliberately modelled on
``openai_adapter.py``'s chat-completions path (guard-for-guard) rather than
its ``responses`` path — every active OpenAI catalog entry uses ``responses``
today, so that path carries live production traffic; OpenRouter's day-one
catalog is chat-completions only.

Liveness sentinel — what actually reaches this adapter, and what does not:
OpenRouter emits ``: OPENROUTER PROCESSING`` SSE comment lines while a
request is queued upstream (the pre-first-token gap). The openai SDK's
stream decoder drops any line starting with ``:`` before it becomes a chunk
(``openai/_streaming.py``), so those comments never reach this adapter and
can never reset the stream watchdog's idle timer. This is an accepted,
documented gap, not an oversight: the idle timeout
(``stage_provider_idle_timeout_seconds``, default 180s) already tolerates a
generous cold-start/queueing delay, and reasoning-delta chunks — which
carry the actual multi-minute silent phases the watchdog exists to survive
(issue #19) — arrive as real ``data:`` events with ``delta.content = None``
and DO reach guard 3 below, which yields the empty liveness sentinel exactly
as it does for OpenAI. Only the (bounded, pre-first-token) queueing gap is
unrecoverable through this SDK; building a hand-rolled SSE parser to close
it was considered and rejected as disproportionate risk for a bounded delay.

Usage/cost accounting: unlike the OpenAI adapter (whose active catalog
entries all use the ``responses`` API and so never exercise this code path
in production), this adapter is live-usage-critical from day one, so it
requests ``stream_options={"include_usage": True}`` (the OpenAI-compatible
mechanism for a final usage-only chunk) AND OpenRouter's own
``usage: {"include": true}`` extra body field (which additionally attaches
``cost`` / ``cost_details.upstream_inference_cost`` to that chunk, carried
through verbatim in ``provider_usage_raw`` for reconciliation against the
catalog-rate estimate — OpenRouter's ~5% platform fee is not folded into
``estimate_cost_usd``, which stays authoritative from catalog rates so the
ledger's cost math stays shaped like every other provider).

Route pinning: every request pins ``provider.data_collection = "deny"`` and
``provider.allow_fallbacks = false``. OpenRouter serves one model slug from
multiple upstream hosts that can differ in quantisation, latency, real
output ceiling and data-retention policy, with fallback between hosts on by
default. Without pinning, the golden-corpus promotion gate (Phase 2) would
grade whichever host answered that afternoon while production runs whichever
host answers next — different evidence for the same claim — and the data
policy would vary by host. Pinning makes both reproducible.

Cache-write accounting is deliberately NOT populated in Phase 1: plain
``_normalize_openai_usage`` delegation (services/llm/usage.py) is the safe
branch either way — with ``cache_write_input_tokens`` left ``None``,
``_cache_write_ttl_split`` returns ``(0, 0)`` and the catalog's cache-write
rate is never consulted, so there is no risk of the None-rate-with-nonzero-
tokens trap that silently zeroes a cost row. ``cached_input_tokens`` (cache
READS) is different and IS populated by plain delegation — OpenRouter
reports ``prompt_tokens_details.cached_tokens`` today — which is why every
openrouter catalog entry sets a real (conservative, no-discount-assumed)
``cached_input_cost_per_million`` rather than leaving it ``None``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import openai

from config import settings
from services.llm.base import (
    RATE_LIMIT_STATUS_CODES,
    BaseLLMAdapter,
    ProviderError,
    ProviderRateLimitError,
    classify_provider_status,
    extract_retry_after,
)
from services.llm.completion import LLMCompletionInfo
from services.llm.model_catalog import model_request_policy
from services.llm.prompt_cache import PromptCachePolicy

_BASE_URL = "https://openrouter.ai/api/v1"

# Project-standard HTTP timeout policy (H-6 — T-182), identical to every
# other adapter: connect/write short (fast-fail), read long (streaming).
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)

# Pinned upstream route (see module docstring): no silent fallback between
# hosts serving the same model slug, and no upstream data retention.
_PINNED_PROVIDER_ROUTE = {"data_collection": "deny", "allow_fallbacks": False}


def _wrap_openrouter_error(exc: openai.OpenAIError) -> ProviderError:
    """Map an SDK error to the right ProviderError subclass (mirrors F2).

    The SDK is `openai`, but every raised exception is reported under the
    "openrouter" provider label so the circuit breaker, cost ledger, and
    observability all attribute failures to the provider actually called.
    """
    status = classify_provider_status(exc)
    is_rate_limited = (
        isinstance(exc, getattr(openai, "RateLimitError", ()))
        or status in RATE_LIMIT_STATUS_CODES
    )
    if is_rate_limited:
        return ProviderRateLimitError(
            "openrouter", exc, retry_after=extract_retry_after(exc)
        )
    return ProviderError("openrouter", exc)


def _wrap_openrouter_transport_error(exc: Exception) -> ProviderError:
    """Normalise SDK-bypassing stream transport failures."""
    return ProviderError("openrouter", exc)


class OpenRouterAdapter(BaseLLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._request_policy = model_request_policy("openrouter", model, operation)
        self._client = openai.AsyncOpenAI(
            api_key=api_key or settings.openrouter_api_key,
            base_url=_BASE_URL,
            timeout=_DEFAULT_TIMEOUT,
        )

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # not wired in Phase 1 — see module docstring
        cache_policy: PromptCachePolicy | None = None,
    ) -> AsyncGenerator[str, None]:
        del cache_system, cache_policy
        self.last_completion = LLMCompletionInfo.started(
            provider="openrouter",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            response = await self._client.chat.completions.create(
                **self._chat_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                ),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in response:
                _capture_resolved_model(self.last_completion, chunk)
                # Guard 1: a usage-only chunk (choices=[]) reports token
                # counts (and, via stream_options + usage.include, OpenRouter
                # cost fields). Accessing choices[0] on it raises IndexError.
                # HF-2 — T-199 precedent, reused verbatim.
                if not chunk.choices:
                    usage = getattr(chunk, "usage", None)
                    if usage is not None and self.last_completion is not None:
                        self.last_completion.usage = _object_to_dict(usage)
                    yield ""
                    continue
                choice = chunk.choices[0]
                if self.last_completion is not None:
                    self.last_completion.apply_finish_reason(
                        getattr(choice, "finish_reason", None)
                    )
                # Guard 2: the final chunk may have delta=None.
                if choice.delta is None:
                    yield ""
                    continue
                # Guard 3: reasoning-delta and tool-use chunks send
                # delta.content=None. This is also where OpenRouter's
                # reasoning_details deltas land — content stays None on them,
                # so they yield the liveness sentinel through this same path
                # without any OpenRouter-specific branching (see module
                # docstring).
                content = choice.delta.content
                if content is None:
                    yield ""
                    continue
                yield content
        except openai.OpenAIError as exc:
            raise _wrap_openrouter_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise _wrap_openrouter_transport_error(exc) from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # not wired in Phase 1 — see module docstring
        cache_policy: PromptCachePolicy | None = None,
    ) -> str:
        del cache_system, cache_policy
        self.last_completion = LLMCompletionInfo.started(
            provider="openrouter",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            response = await self._client.chat.completions.create(
                **self._chat_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                ),
            )
            choice = response.choices[0]
            if self.last_completion is not None:
                _capture_resolved_model(self.last_completion, response)
                self.last_completion.apply_finish_reason(
                    getattr(choice, "finish_reason", None)
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.last_completion.usage = _object_to_dict(usage)
            return choice.message.content or ""
        except openai.OpenAIError as exc:
            raise _wrap_openrouter_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise _wrap_openrouter_transport_error(exc) from exc

    def _chat_request(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
    ) -> dict:
        extra_body: dict = {
            # Attaches cost/cost_details to the final usage chunk — see the
            # module docstring's usage/cost accounting section.
            "usage": {"include": True},
            "provider": dict(_PINNED_PROVIDER_ROUTE),
        }
        effort = self._request_policy["reasoning_effort"]
        if effort:
            # Gate on the effort VALUE, not on supports_reasoning: this must
            # never send the field to a model whose catalog entry declares
            # no effort knob (the Haiku 4.5 precedent — deepseek-v3.2 mirrors
            # that shape today with supports_reasoning=False).
            extra_body["reasoning"] = {"effort": effort}
        request: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "extra_body": extra_body,
        }
        return request


def _capture_resolved_model(
    completion: LLMCompletionInfo | None,
    response_or_chunk,
) -> None:
    if completion is None:
        return
    resolved_model = getattr(response_or_chunk, "model", None)
    if resolved_model:
        completion.raw["resolved_model"] = str(resolved_model)
    # OpenRouter echoes the concrete upstream host it routed to on some
    # responses (provider pinning above still applies; this is purely for
    # ledger/forensics visibility into which host actually served the call).
    provider_name = getattr(response_or_chunk, "provider", None)
    if provider_name:
        completion.raw["resolved_upstream_provider"] = str(provider_name)


def _object_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": str(value)}
