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
(``stage_provider_idle_timeout_seconds``, default 240s) matches the attempt cap,
so a dropped comment cannot pre-empt the hard deadline. Reasoning-delta chunks — which
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

Route preference — the single most load-bearing thing this adapter does.
OpenRouter serves one model slug from many upstream hosts that differ in
quantisation (fp4/fp8/unknown), price, cache-read price, real output ceiling,
latency and data-retention policy, and it load-balances between them by
default. Every request sends matching ``provider.order`` and ``provider.only``
lists sourced from the catalog entry's evaluated ``upstream_providers`` plus
``data_collection: "deny"``. This prevents an availability fallback from
silently landing on an unqualified host with a smaller output ceiling, different
quantisation, retention policy, latency or price. Cross-provider recovery is
owned by the durable application pipeline, where it is observable/checkpointed.

Three things break without that preference, and the first is the reason the
DeepSeek ladder exists at all:

* **Prompt caching would usually be zero.** On ``deepseek-v4-flash``,
  ``supports_implicit_caching`` is true for 1 of 19 upstream hosts (DeepSeek's
  own). An unpinned request lands on a caching host ~5% of the time, and
  prefix caching is per-host anyway, so consecutive chunks of one stage share
  nothing.
* **Cost accounting needs fallback evidence.** Catalog rates describe the
  preferred host; provider-reported cost and resolved-upstream metadata identify
  the exceptional fallback case.
* **The promotion gate stays reproducible in the healthy case.** Normal traffic
  tries the declared host first; fallback is an availability escape hatch.

Reasoning control: core generation sends the catalog's declared effort, but
the cheap non-core operations (judge/eval, focused+section refine, summary)
send ``reasoning: {"effort": "none"}`` on the non-streaming ``complete()``
path. Reasoning tokens are billed as output AND counted against
``max_tokens`` on OpenRouter, and those operations run on budgets of
1-8K tokens (``output_budget.OUTPUT_TOKEN_BUDGETS``) — a single medium-effort
reasoning burst consumes the whole budget and returns empty text with
``finish_reason=length``. That is the failure already documented for Gemini
at ``output_budget.py``'s ``("refine.focused","google")`` override. It is
applied to ``complete()`` only, never ``stream()``: reasoning deltas are the
liveness sentinel the stream watchdog depends on (see above).

Cache accounting: ``services/llm/usage.py::_normalize_openrouter_usage``
populates BOTH ``cached_input_tokens`` (from
``prompt_tokens_details.cached_tokens``) and ``cache_write_input_tokens``
(from ``prompt_tokens_details.cache_write_tokens``). Populating writes is
only safe because every openrouter catalog entry carries a non-``None``
``cache_write_5m_cost_per_million``: a ``None`` rate with non-zero write
tokens makes ``estimate_cost_usd()`` return ``None`` and the ledger records
no cost at all. Explicit ``cache_control`` breakpoints are deliberately not
sent — DeepSeek caching is automatic and needs none.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping

import httpx
import openai

from config import settings
from services.llm.base import (
    BaseLLMAdapter,
    ProviderError,
    ProviderRateLimitError,
    ProviderTerminalError,
    ProviderUnavailableError,
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

# The catalog's evaluated host list is both ordered and exclusive. OpenRouter may
# fail over only within that list; the durable pipeline owns broader recovery.
_BASE_PROVIDER_ROUTE = {
    "data_collection": "deny",
    "allow_fallbacks": True,
    # Fail routing instead of silently dropping/transforming a parameter the
    # catalog depends on (reasoning effort, max_tokens, response format, etc.).
    "require_parameters": True,
}


def _wrap_openrouter_error(exc: openai.OpenAIError) -> ProviderError:
    """Map an SDK error to the right ProviderError subclass (mirrors F2).

    The SDK is `openai`, but every raised exception is reported under the
    "openrouter" provider label so the circuit breaker, cost ledger, and
    observability all attribute failures to the provider actually called.
    """
    status = classify_provider_status(exc)
    error_type, provider_code, message = _openrouter_error_metadata(exc)
    common = {
        "status_code": status,
        "error_type": error_type,
        "provider_code": provider_code,
    }
    # OpenRouter uses 503 both for transient capacity and for a routing policy
    # that matches zero upstreams.  Retrying the latter unchanged only burns the
    # run deadline, so recognise the stable typed/message forms and fail fast.
    impossible_route = status == 503 and (
        "no available model provider" in message.lower()
        or "routing requirement" in message.lower()
        or error_type
        in {
            "no_available_provider",
            "provider_routing_error",
            "provider_unavailable_for_parameters",
        }
    )
    is_rate_limited = (
        isinstance(exc, getattr(openai, "RateLimitError", ()))
        or status in {429, 529}
        or (status == 503 and error_type == "provider_overloaded")
    )
    if is_rate_limited and not impossible_route:
        return ProviderRateLimitError(
            "openrouter",
            exc,
            retry_after=extract_retry_after(exc),
            **common,
        )
    if status in {400, 401, 402, 403} or impossible_route:
        return ProviderTerminalError(
            "openrouter",
            exc,
            failover_allowed=status in {401, 402, 503},
            **common,
        )
    if status in {408, 502, 503} or (status is not None and status >= 500):
        return ProviderUnavailableError("openrouter", exc, **common)
    return ProviderError("openrouter", exc, **common)


def _wrap_openrouter_transport_error(exc: Exception) -> ProviderError:
    """Normalise SDK-bypassing stream transport failures."""
    return ProviderUnavailableError(
        "openrouter", exc, error_type="transport", status_code=None
    )


def _openrouter_error_metadata(
    exc: Exception,
) -> tuple[str | None, str | None, str]:
    """Extract OpenRouter's stable typed-error vocabulary from SDK envelopes."""

    body = getattr(exc, "body", None)
    error: Mapping | None = body if isinstance(body, Mapping) else None
    if error is not None and isinstance(error.get("error"), Mapping):
        error = error["error"]
    metadata = error.get("metadata") if isinstance(error, Mapping) else None
    if not isinstance(metadata, Mapping):
        metadata = {}
    error_type = metadata.get("error_type")
    if error_type is None and isinstance(error, Mapping):
        error_type = error.get("error_type") or error.get("type")
    provider_code = metadata.get("provider_code")
    if provider_code is None and isinstance(error, Mapping):
        provider_code = error.get("code")
    message = error.get("message") if isinstance(error, Mapping) else None
    return (
        str(error_type) if error_type is not None else None,
        str(provider_code) if provider_code is not None else None,
        str(message or exc),
    )


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
            # The durable pipeline owns the bounded Retry-After/backoff and
            # cross-provider policy. SDK-default retries would be invisible to
            # its counters and multiply a four-chunk PLAN overload into many
            # correlated upstream attempts before our first retry begins.
            max_retries=0,
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
                    # Non-streaming path only. Suppressing reasoning here is
                    # what makes the small judge/refine/summary budgets viable;
                    # doing it on stream() would remove the watchdog's liveness
                    # sentinel (see the module docstring).
                    suppress_reasoning=self._suppress_reasoning(),
                ),
            )
            if not response.choices:
                raise ProviderUnavailableError(
                    "openrouter",
                    RuntimeError("OpenRouter returned no completion choices"),
                    error_type="empty_response",
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
            content = choice.message.content or ""
            if not content.strip():
                finish_reason = str(getattr(choice, "finish_reason", "") or "").lower()
                refusal = getattr(choice.message, "refusal", None)
                if refusal or finish_reason in {
                    "content_filter",
                    "safety",
                    "blocked",
                }:
                    raise ProviderTerminalError(
                        "openrouter",
                        RuntimeError("OpenRouter blocked the completion by policy"),
                        failover_allowed=False,
                        status_code=403,
                        error_type="content_policy_violation",
                    )
                raise ProviderUnavailableError(
                    "openrouter",
                    RuntimeError("OpenRouter returned an empty completion"),
                    error_type="empty_response",
                )
            return content
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
        suppress_reasoning: bool = False,
    ) -> dict:
        extra_body: dict = {
            # Attaches cost/cost_details to the final usage chunk — see the
            # module docstring's cache-accounting section.
            "usage": {"include": True},
            "provider": self._provider_route(),
        }
        reasoning = self._reasoning_field(suppress_reasoning=suppress_reasoning)
        if reasoning is not None:
            extra_body["reasoning"] = reasoning
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

    def _provider_route(self) -> dict:
        """The upstream-host routing block for this model (see module docstring).

        ``order``/``only`` are omitted when the catalog declares no upstream
        allow-list; OpenRouter then uses its normal availability-aware routing.
        """
        route = dict(_BASE_PROVIDER_ROUTE)
        allowlist = self._request_policy.get("upstream_providers") or ()
        if allowlist:
            route["order"] = list(allowlist)
            route["only"] = list(allowlist)
        return route

    def _reasoning_field(self, *, suppress_reasoning: bool) -> dict | None:
        """The ``reasoning`` request field, or None to omit it entirely.

        Suppression wins over effort: the cheap non-core operations run on
        output budgets far too small to absorb a reasoning burst (reasoning
        tokens bill as output AND count against ``max_tokens`` on OpenRouter),
        so they ask the model not to emit any. Callers only set this on the
        non-streaming path — see ``stream()``.
        """
        if suppress_reasoning and self._request_policy["supports_reasoning"]:
            # exclude=true only hides reasoning from the response; the model
            # still spends those billed tokens and can starve a 1-8K non-core
            # response. The active DeepSeek metadata reports mandatory=false,
            # so effort=none is the actual disable control.
            return {"effort": "none"}
        effort = self._request_policy["reasoning_effort"]
        if effort:
            # Gate on the effort VALUE, not on supports_reasoning: this must
            # never send an effort to a model whose catalog entry declares no
            # effort knob (the Haiku 4.5 precedent).
            return {"effort": effort}
        return None

    def _suppress_reasoning(self) -> bool:
        """True for the cheap non-core operations (judge/eval, refine, summary).

        Deliberately derived from the catalog's own core-operation set via
        ``model_request_policy`` rather than an operation list held here, so it
        cannot drift from ``CORE_GENERATION_OPERATIONS``.
        """
        return not self._request_policy["is_core_generation"]


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
    # responses (the preferred-host policy above still applies; this is for
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
