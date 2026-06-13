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

import time
from collections.abc import AsyncGenerator
from typing import Any

import structlog

from services import langfuse_service
from services.llm.base import BaseLLMAdapter
from services.llm.completion import LLMCompletionInfo
from services.llm.cost_ledger import LLMCostContext, persist_cost_event
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
        # Set after each recorded generation so downstream code (T-127 eval
        # score linking) can attach scores or dataset items to the same id.
        self.last_generation_id: str | None = None
        self.last_completion: LLMCompletionInfo | None = None

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
    ) -> AsyncGenerator[str, None]:
        accumulated: list[str] = []
        start = time.perf_counter()
        try:
            async for token in self._wrapped.stream(
                system, user, max_tokens, cache_system=cache_system
            ):
                accumulated.append(token)
                yield token
        except Exception as exc:
            record_provider_failure(self._provider, exc)
            raise
        else:
            record_provider_success(self._provider)
        finally:
            self.last_completion = getattr(self._wrapped, "last_completion", None)
            await self._record_generation(
                system=system,
                user=user,
                output="".join(accumulated),
                start=start,
            )

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
    ) -> str:
        start = time.perf_counter()
        response: str = ""
        try:
            # Forward max_tokens as a keyword so the wrapper is transparent to
            # callers/tests that pass (and assert) it by name.
            response = await self._wrapped.complete(
                system, user, max_tokens=max_tokens, cache_system=cache_system
            )
            record_provider_success(self._provider)
            return response
        except Exception as exc:
            record_provider_failure(self._provider, exc)
            raise
        finally:
            self.last_completion = getattr(self._wrapped, "last_completion", None)
            # response stays "" if the wrapped call raised; recording an empty
            # output preserves trace context without re-raising the error.
            await self._record_generation(
                system=system,
                user=user,
                output=response,
                start=start,
            )

    async def _record_generation(
        self,
        *,
        system: str,
        user: str,
        output: Any,
        start: float,
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
            "output_tokens": usage.output_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "provider_usage_raw": usage.provider_usage_raw,
            "usage_estimation_method": usage.usage_estimation_method,
            "estimated_cost_usd": (
                float(estimated_cost) if estimated_cost is not None else None
            ),
            "latency_ms": latency_ms,
            "finish_reason": completion.finish_reason if completion else None,
            "stopped_by_limit": (
                bool(completion.stopped_by_limit) if completion else False
            ),
            "cache_hit": self._cache_hit,
            "batch": self._batch,
            "cross_provider_fallback": self._cross_provider_fallback,
        }
        if self._cost_context is not None:
            metadata.update(self._cost_context.as_metadata())
        return metadata
