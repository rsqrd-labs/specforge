"""InstrumentedAdapter — composes Langfuse instrumentation around any
``BaseLLMAdapter`` without modifying the adapter interface.

HTTP timeout policy (H-6 — T-182): timeout= enforcement is delegated to the
wrapped adapter's httpx.Timeout configuration.  This class does not make
direct HTTP calls; it observes and re-yields whatever the wrapped adapter
produces.

This is the only place provider calls get observed for Langfuse purposes. The
adapter modules themselves (``anthropic_adapter.py``, ``openai_adapter.py``,
``google_adapter.py``) remain Langfuse-free, so adding a new provider still
means writing one adapter and nothing else.

Behaviour:

* ``stream()`` yields the wrapped adapter's tokens unchanged. After the stream
  closes (success, exception, or generator close), a single Langfuse
  ``generation`` is recorded with the full accumulated output. Streams are
  never recorded token-by-token.
* ``complete()`` returns the wrapped adapter's value unchanged. One generation
  is recorded around the call.
* ``last_generation_id`` is set after each call so callers (e.g. the stage
  manager threading the id into ``run_eval_background`` for T-127) can attach
  the eval score to the right generation.
* All instrumentation calls go through the no-op-tolerant ``LangfuseClient``,
  so a Langfuse outage cannot break streaming or completion.
* Inputs and outputs are redacted via
  ``services.observability.redact_sensitive_data`` before being submitted
  (defence in depth — ``LangfuseClient`` redacts again).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import structlog

from services import langfuse_service
from services.llm.base import BaseLLMAdapter, ProviderRateLimitError
from services.llm.completion import LLMCompletionInfo
from services.llm.cost_ledger import LLMCostContext, persist_cost_event
from services.llm.prompt_cache import PromptCachePolicy
from services.llm.provider_status import (
    record_provider_failure,
    record_provider_success,
)
from services.llm.usage import (
    estimate_cost_usd,
    estimated_usage_from_text,
    normalize_provider_usage,
)
from services.observability import record_llm_cost_event, redact_sensitive_data

logger = structlog.get_logger(__name__)


class InstrumentedAdapter(BaseLLMAdapter):
    def __init__(
        self,
        wrapped: BaseLLMAdapter,
        *,
        span_id: str | None = None,
        trace_id: str | None = None,
        provider: str,
        model: str,
        stage_type: str,
        action: str,
        model_tier: str | None = None,
        prompt_version: str = "local",
        operation: str | None = None,
        cache_hit: bool = False,
        batch: bool = False,
        cross_provider_fallback: bool = False,
        cost_context: LLMCostContext | None = None,
        retry_count: int | None = 0,
        repair_count: int | None = 0,
    ) -> None:
        self._wrapped = wrapped
        self._span_id = span_id
        self._trace_id = trace_id
        self._provider = provider
        self._model = model
        self._stage_type = stage_type
        self._action = action
        self._model_tier = model_tier or "unknown"
        self._prompt_version = prompt_version
        self._operation = operation or action
        self._cache_hit = cache_hit
        self._batch = batch
        self._cross_provider_fallback = cross_provider_fallback
        self._cost_context = cost_context
        self._retry_count = retry_count
        self._repair_count = repair_count
        self._generation_run_id: str | None = None
        self._chunk_key: str | None = None
        self._provider_request_id: str | None = None
        # Set after each recorded generation so downstream code (T-127 eval
        # score linking) can attach scores or dataset items to the same id.
        self.last_generation_id: str | None = None
        self.last_completion: LLMCompletionInfo | None = None

    def set_call_attempt_metadata(
        self,
        *,
        retry_count: int | None = None,
        repair_count: int | None = None,
    ) -> None:
        if retry_count is not None:
            self._retry_count = retry_count
        if repair_count is not None:
            self._repair_count = repair_count

    def set_request_context(
        self, *, generation_run_id: str | None, chunk_key: str | None
    ) -> None:
        self._generation_run_id = generation_run_id
        self._chunk_key = chunk_key

    def _request_log_fields(self, *, elapsed_ms: int | None = None) -> dict:
        completion = self.last_completion
        fields = {
            "generation_id": self._generation_run_id,
            "stage": self._stage_type,
            "chunk": self._chunk_key,
            "provider": self._provider,
            "model": self._model,
            "retry": self._retry_count,
            # Client-generated correlation id written before dispatch. Provider
            # response ids are attached separately when the stream returns one.
            "provider_request_id": self._provider_request_id,
            "provider_response_id": (
                completion.raw.get("provider_response_id")
                if completion is not None
                else None
            ),
        }
        if elapsed_ms is not None:
            fields["elapsed_ms"] = elapsed_ms
        return fields

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_policy: PromptCachePolicy | None = None,
    ) -> AsyncGenerator[str, None]:
        accumulated: list[str] = []
        start = time.perf_counter()
        first_event_latency_ms: int | None = None
        outcome = "failed"
        error_type: str | None = None
        # A provider that throttled the call before emitting a single token never
        # processed it and never bills for it. Booking a tokenizer-estimated row
        # anyway inflates llm_cost_events (a throttled 4-chunk tasks stage logged
        # ~$0.48 of spend that never happened) and pollutes the ledger that the
        # output-budget evidence gate reads.
        rejected_unbilled = False
        self._provider_request_id = str(uuid4())
        logger.info("llm.request_started", **self._request_log_fields())
        try:
            kwargs = {"cache_system": cache_system}
            if cache_policy is not None:
                kwargs["cache_policy"] = cache_policy
            async for token in self._wrapped.stream(system, user, max_tokens, **kwargs):
                if first_event_latency_ms is None:
                    first_event_latency_ms = int((time.perf_counter() - start) * 1000)
                accumulated.append(token)
                yield token
        except Exception as exc:
            error_type = type(exc).__name__
            rejected_unbilled = isinstance(exc, ProviderRateLimitError) and not (
                accumulated
            )
            record_provider_failure(self._provider, exc)
            raise
        else:
            outcome = "succeeded"
            record_provider_success(self._provider)
        finally:
            self.last_completion = getattr(self._wrapped, "last_completion", None)
            logger.info(
                "llm.request_finished",
                **self._request_log_fields(
                    elapsed_ms=int((time.perf_counter() - start) * 1000)
                ),
                outcome=outcome,
                error_type=error_type,
            )
            if not rejected_unbilled:
                await self._record_generation_bounded(
                    system=system,
                    user=user,
                    output="".join(accumulated),
                    start=start,
                    cache_policy=cache_policy,
                    first_event_latency_ms=first_event_latency_ms,
                )

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_policy: PromptCachePolicy | None = None,
    ) -> str:
        start = time.perf_counter()
        response: str = ""
        outcome = "failed"
        error_type: str | None = None
        rejected_unbilled = False  # see stream(): a throttled call is not billed
        self._provider_request_id = str(uuid4())
        logger.info("llm.request_started", **self._request_log_fields())
        try:
            # Forward max_tokens as a keyword so the wrapper is transparent to
            # callers/tests that pass (and assert) it by name.
            kwargs = {"cache_system": cache_system}
            if cache_policy is not None:
                kwargs["cache_policy"] = cache_policy
            response = await self._wrapped.complete(
                system, user, max_tokens=max_tokens, **kwargs
            )
            record_provider_success(self._provider)
            outcome = "succeeded"
            return response
        except Exception as exc:
            error_type = type(exc).__name__
            rejected_unbilled = isinstance(exc, ProviderRateLimitError)
            record_provider_failure(self._provider, exc)
            raise
        finally:
            self.last_completion = getattr(self._wrapped, "last_completion", None)
            logger.info(
                "llm.request_finished",
                **self._request_log_fields(
                    elapsed_ms=int((time.perf_counter() - start) * 1000)
                ),
                outcome=outcome,
                error_type=error_type,
            )
            # response stays "" if the wrapped call raised; recording an empty
            # output preserves trace context without re-raising the error.
            if not rejected_unbilled:
                await self._record_generation_bounded(
                    system=system,
                    user=user,
                    output=response,
                    start=start,
                    cache_policy=cache_policy,
                )

    async def _record_generation_bounded(self, **kwargs: Any) -> None:
        """Keep optional observability off the provider cleanup critical path."""
        try:
            async with asyncio.timeout(5):
                await self._record_generation(**kwargs)
        except TimeoutError:
            logger.warning(
                "instrumented_adapter.record_timeout",
                **self._request_log_fields(),
            )

    async def _record_generation(
        self,
        *,
        system: str,
        user: str,
        output: Any,
        start: float,
        cache_policy: PromptCachePolicy | None = None,
        first_event_latency_ms: int | None = None,
    ) -> None:
        """Submit one Langfuse generation. Never raises — LangfuseClient
        already swallows; the extra try/except here is belt-and-braces so a
        bug inside this wrapper cannot break the streaming path either."""
        try:
            latency_ms = int((time.perf_counter() - start) * 1000)
            redacted_input = redact_sensitive_data({"system": system, "user": user})
            redacted_output = redact_sensitive_data(output)
            cost_metadata = self._cost_metadata(
                system=system,
                user=user,
                output=str(output),
                latency_ms=latency_ms,
                cache_policy=cache_policy,
                first_event_latency_ms=first_event_latency_ms,
            )
            record_llm_cost_event(cost_metadata)
            logger.info("llm.cost_recorded", **cost_metadata)
            # Create the Langfuse generation first so its id can be persisted on
            # the cost-ledger row — the stage manager later sets quality_outcome
            # on that row by the same generation_id.  Langfuse failures must not
            # block the ledger write, so this is its own guarded step.
            generation_id: str | None = None
            try:
                client = langfuse_service.get_langfuse_client()
                generation_id = await client.create_generation(
                    span_id=self._span_id,
                    trace_id=self._trace_id,
                    name=f"{self._provider}.{self._action}",
                    provider=self._provider,
                    model=self._model,
                    input=redacted_input,
                    output=redacted_output,
                    metadata={
                        "stage_type": self._stage_type,
                        "action": self._action,
                        "latency_ms": latency_ms,
                        **cost_metadata,
                    },
                )
            except Exception:
                logger.error("instrumented_adapter.langfuse.failed", exc_info=True)
            self.last_generation_id = generation_id
            cost_metadata["generation_id"] = generation_id
            await persist_cost_event(cost_metadata)
        except Exception:
            # Defensive: a bug in the wrapper itself must never break the
            # caller. LangfuseClient already swallows but the recorder mock
            # used in tests can raise; this final guard preserves the
            # streaming contract.
            logger.error("instrumented_adapter.record.failed", exc_info=True)

    def _cost_metadata(
        self,
        *,
        system: str,
        user: str,
        output: str,
        latency_ms: int,
        cache_policy: PromptCachePolicy | None = None,
        first_event_latency_ms: int | None = None,
    ) -> dict[str, Any]:
        # Prefer the provider-reported usage captured by the wrapped adapter
        # (real input/cached/output/reasoning tokens); fall back to the
        # tokenizer estimate only when no usage chunk arrived.
        completion = self.last_completion
        usage = None
        if completion is not None and completion.usage is not None:
            usage = normalize_provider_usage(self._provider, completion.usage)
        if usage is None or (
            usage.input_tokens is None and usage.output_tokens is None
        ):
            usage = estimated_usage_from_text(
                provider=self._provider,
                model=self._model,
                system=system,
                user=user,
                output=output,
            )
        try:
            estimated_cost = estimate_cost_usd(
                self._provider, self._model, usage, batch=self._batch
            )
        except Exception:
            estimated_cost = None

        metadata = {
            "provider": self._provider,
            "model": self._model,
            "model_tier": self._model_tier,
            "prompt_version": self._prompt_version,
            "stage_type": self._stage_type,
            "operation": self._operation,
            "input_tokens": usage.input_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "cache_write_input_tokens": usage.cache_write_input_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "provider_usage_raw": usage.provider_usage_raw,
            "usage_estimation_method": usage.usage_estimation_method,
            "estimated_cost_usd": (
                float(estimated_cost) if estimated_cost is not None else None
            ),
            "latency_ms": latency_ms,
            "first_event_latency_ms": first_event_latency_ms,
            "finish_reason": completion.finish_reason if completion else None,
            "stopped_by_limit": (
                bool(completion.stopped_by_limit) if completion else False
            ),
            "cache_hit": self._cache_hit,
            "batch": self._batch,
            "cross_provider_fallback": self._cross_provider_fallback,
            "retry_count": self._retry_count,
            "repair_count": self._repair_count,
            "provider_prompt_cache_hit": bool(usage.cached_input_tokens),
            "prompt_cache_routing_key_fingerprint": (
                cache_policy.routing_key[-16:] if cache_policy else None
            ),
            "eligible_prefix_fingerprint": (
                cache_policy.eligible_prefix_fingerprint[:16] if cache_policy else None
            ),
            "prompt_cache_retention": (
                cache_policy.retention if cache_policy else None
            ),
            "resolved_model": (
                completion.raw.get("resolved_model") if completion else None
            ),
        }
        if self._cost_context is not None:
            metadata.update(self._cost_context.as_metadata())
        return metadata
