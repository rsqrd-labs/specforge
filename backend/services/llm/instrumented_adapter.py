"""InstrumentedAdapter — composes Langfuse instrumentation around any
``BaseLLMAdapter`` without modifying the adapter interface.

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
from services.llm.provider_status import (
    record_provider_failure,
    record_provider_success,
)
from services.llm.usage import estimate_cost_usd, estimated_usage_from_text
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
        # Set after each recorded generation so downstream code (T-127 eval
        # score linking) can attach scores or dataset items to the same id.
        self.last_generation_id: str | None = None

    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        accumulated: list[str] = []
        start = time.perf_counter()
        try:
            async for token in self._wrapped.stream(system, user, max_tokens):
                accumulated.append(token)
                yield token
        except Exception as exc:
            record_provider_failure(self._provider, exc)
            raise
        else:
            record_provider_success(self._provider)
        finally:
            await self._record_generation(
                system=system,
                user=user,
                output="".join(accumulated),
                start=start,
            )

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        start = time.perf_counter()
        response: str = ""
        try:
            response = await self._wrapped.complete(system, user, max_tokens)
            record_provider_success(self._provider)
            return response
        except Exception as exc:
            record_provider_failure(self._provider, exc)
            raise
        finally:
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
            self.last_generation_id = generation_id
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
        usage = estimated_usage_from_text(
            provider=self._provider,
            model=self._model,
            system=system,
            user=user,
            output=output,
        )
        try:
            estimated_cost = estimate_cost_usd(self._provider, self._model, usage)
        except Exception:
            estimated_cost = None

        return {
            "provider": self._provider,
            "model": self._model,
            "model_tier": self._model_tier,
            "prompt_version": self._prompt_version,
            "stage_type": self._stage_type,
            "operation": self._operation,
            "input_tokens": usage.input_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "output_tokens": usage.output_tokens,
            "provider_usage_raw": usage.provider_usage_raw,
            "usage_estimation_method": usage.usage_estimation_method,
            "estimated_cost_usd": (
                float(estimated_cost) if estimated_cost is not None else None
            ),
            "latency_ms": latency_ms,
            "cache_hit": self._cache_hit,
            "batch": self._batch,
            "cross_provider_fallback": self._cross_provider_fallback,
        }
