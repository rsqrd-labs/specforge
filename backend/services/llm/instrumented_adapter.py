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
from services.observability import redact_sensitive_data

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
    ) -> None:
        self._wrapped = wrapped
        self._span_id = span_id
        self._trace_id = trace_id
        self._provider = provider
        self._model = model
        self._stage_type = stage_type
        self._action = action
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
            return response
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
                },
            )
            self.last_generation_id = generation_id
        except Exception:
            # Defensive: a bug in the wrapper itself must never break the
            # caller. LangfuseClient already swallows but the recorder mock
            # used in tests can raise; this final guard preserves the
            # streaming contract.
            logger.error("instrumented_adapter.record.failed", exc_info=True)
