"""LangfuseClient — single integration point for optional Langfuse LLM observability.

When ``settings.langfuse_secret_key`` is empty, every public method is a no-op
and the Langfuse SDK is **never imported**. When configured, the SDK client is
constructed lazily on first use and cached for the lifetime of the process.

Every public method is:

* **async-safe** — calls into the synchronous Langfuse v2 SDK, which queues
  outbound HTTP on its own background thread; the async wrapper performs no
  blocking I/O on the event loop.
* **exception-swallowing** — any failure (network error, auth failure, schema
  rejection) is logged via ``structlog`` at ``error`` level and never
  re-raised. A Langfuse outage cannot break stage generation, refine, eval,
  credits, or any other user-facing flow (V1 spec Assumption 7).
* **redaction-aware** — every payload is routed through
  ``services.observability.redact_sensitive_data`` before being submitted, so
  API keys, JWT tokens, and other secret-shaped strings are scrubbed using
  the same ruleset that already protects logs and Sentry events. No
  Langfuse-specific redaction patterns are defined.

Pinned to ``langfuse>=2.60,<3``: v3+ moved to an OpenTelemetry context-manager
API and a newer ``opentelemetry-api`` that conflicts with the project's
``opentelemetry-instrumentation-* == 0.49.*`` line. v2.60 exposes the
imperative ``trace/span/generation/score`` surface this wrapper composes
around. See Plan §15.9 Q5.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

from config import settings
from services.observability import redact_sensitive_data

logger = structlog.get_logger(__name__)


class LangfuseClient:
    """Async-safe, exception-swallowing wrapper around the Langfuse v2 SDK."""

    def __init__(self) -> None:
        self._enabled: bool = bool(settings.langfuse_secret_key.strip())
        self._client: Any | None = None
        self._init_lock = threading.Lock()
        self._spans: dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _ensure_client(self) -> Any | None:
        if not self._enabled:
            return None
        if self._client is not None:
            return self._client
        with self._init_lock:
            if self._client is not None:
                return self._client
            try:
                from langfuse import Langfuse  # imported lazily on first use only

                self._client = Langfuse(
                    secret_key=settings.langfuse_secret_key,
                    public_key=settings.langfuse_public_key,
                    host=settings.langfuse_host,
                )
            except Exception:
                # Construction failure (bad keys, unreachable host) flips the
                # client into permanent no-op mode for this process.
                logger.error("langfuse.init.failed", exc_info=True)
                self._enabled = False
                self._client = None
        return self._client

    async def create_trace(
        self,
        *,
        name: str,
        trace_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Create a Langfuse trace and return its id. Returns None when the
        client is disabled or the SDK call fails.

        ``trace_id`` is honored when provided so callers can propagate their
        own UUID through the request and receive it back unchanged.
        """
        client = self._ensure_client()
        if client is None:
            return None
        try:
            resolved_trace_id = trace_id or str(uuid4())
            client.trace(
                id=resolved_trace_id,
                name=name,
                user_id=user_id,
                metadata=redact_sensitive_data(metadata or {}),
            )
            return resolved_trace_id
        except Exception:
            logger.error("langfuse.create_trace.failed", exc_info=True)
            return None

    async def create_span(
        self,
        *,
        trace_id: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Create a span inside ``trace_id`` and return its observation id."""
        client = self._ensure_client()
        if client is None:
            return None
        try:
            span_id = str(uuid4())
            span = client.span(
                id=span_id,
                trace_id=trace_id,
                name=name,
                metadata=redact_sensitive_data(metadata or {}),
            )
            if span is not None:
                self._spans[span_id] = span
            return span_id
        except Exception:
            logger.error("langfuse.create_span.failed", exc_info=True)
            return None

    async def end_span(self, span_id: str | None) -> None:
        """Best-effort span completion. Never raises."""
        if span_id is None:
            return None
        client = self._ensure_client()
        if client is None:
            return None
        try:
            span = self._spans.pop(span_id, None)
            if span is not None and hasattr(span, "end"):
                span.end()
                return None
            client.span(id=span_id, end_time=datetime.now(UTC))
        except Exception:
            logger.error("langfuse.end_span.failed", exc_info=True)
            return None

    async def mark_span_failed(self, span_id: str | None, exc: Exception) -> None:
        """Best-effort span failure marker. Never raises."""
        if span_id is None:
            return None
        client = self._ensure_client()
        if client is None:
            return None
        try:
            span = self._spans.pop(span_id, None)
            metadata = redact_sensitive_data({"error": str(exc)})
            if span is not None and hasattr(span, "end"):
                span.end(level="ERROR", status_message=str(metadata["error"]))
                return None
            client.span(
                id=span_id,
                end_time=datetime.now(UTC),
                level="ERROR",
                status_message=str(metadata["error"]),
            )
        except Exception:
            logger.error("langfuse.mark_span_failed.failed", exc_info=True)
            return None

    async def create_generation(
        self,
        *,
        span_id: str | None = None,
        trace_id: str | None = None,
        name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        input: Any = None,
        output: Any = None,
        usage: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Record one generation. ``input`` and ``output`` are redacted before
        submission. Returns the generation id so callers can later attach a
        score to the same observation.
        """
        client = self._ensure_client()
        if client is None:
            return None
        try:
            generation_id = str(uuid4())
            merged_metadata = dict(metadata or {})
            if provider is not None:
                merged_metadata.setdefault("provider", provider)
            client.generation(
                id=generation_id,
                trace_id=trace_id,
                parent_observation_id=span_id,
                name=name,
                model=model,
                input=redact_sensitive_data(input),
                output=redact_sensitive_data(output),
                usage_details=usage,
                metadata=redact_sensitive_data(merged_metadata),
            )
            return generation_id
        except Exception:
            logger.error("langfuse.create_generation.failed", exc_info=True)
            return None

    async def score_generation(
        self,
        *,
        generation_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """Attach a score to an existing generation observation."""
        client = self._ensure_client()
        if client is None:
            return None
        try:
            client.score(
                observation_id=generation_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception:
            logger.error("langfuse.score_generation.failed", exc_info=True)
            return None

    async def add_to_dataset(
        self,
        *,
        dataset_name: str,
        item: dict[str, Any],
        source_observation_id: str | None = None,
    ) -> None:
        """Append an item to a Langfuse dataset (e.g. ``high_quality_generations``).

        Item content is redacted before submission. Errors are logged and
        swallowed; the caller never sees a failure.
        """
        client = self._ensure_client()
        if client is None:
            return None
        try:
            client.create_dataset_item(
                dataset_name=dataset_name,
                input=redact_sensitive_data(item),
                source_observation_id=source_observation_id,
            )
        except Exception:
            logger.error("langfuse.add_to_dataset.failed", exc_info=True)
            return None

    async def flush(self) -> None:
        """Drain queued events to Langfuse before the consumer thread is
        torn down. Best-effort; never raises.

        The Langfuse v2 SDK queues trace/span/generation/score/dataset
        events on a background consumer thread that flushes in batches
        (default ``LANGFUSE_FLUSH_AT=15`` events or every ``0.5s``). On
        graceful shutdown — rolling deploys, SIGTERM during a Railway
        restart, or test process exit — anything still in the queue is
        dropped when the interpreter unloads. Calling ``client.flush()``
        forces a synchronous drain. We dispatch it to a worker thread
        because the SDK call is blocking; we never want shutdown to
        stall on a slow Langfuse host.
        """
        if not self._enabled or self._client is None:
            return
        try:
            await asyncio.to_thread(self._client.flush)
        except Exception:
            logger.error("langfuse.flush.failed", exc_info=True)

    async def get_prompt(
        self,
        name: str,
        version: int | None = None,
    ) -> str | None:
        """Fetch the latest (or pinned) prompt template body for ``name``.

        Returns ``None`` when the client is disabled, the prompt does not
        exist, the fetch times out, or any error occurs. Callers must always
        have a local fallback. Uses the SDK's built-in TTL cache via
        ``cache_ttl_seconds``.

        The Langfuse v2 SDK's ``get_prompt`` is synchronous: on a cache miss
        it issues a blocking HTTP call with up to 3 retries × ~10s timeout.
        Calling it directly from an async context would block the event loop
        and stall every concurrent request on the worker. We dispatch the
        call to a worker thread and bound the wait with
        ``langfuse_prompt_fetch_timeout_seconds`` so a slow or unreachable
        Langfuse host degrades gracefully to the local fallback rather than
        wedging stage generation.

        On timeout the worker thread continues running until the SDK's own
        timeout fires; we drop its eventual result. This is acceptable
        because the application-level prompt cache (``prompts/base.py``)
        ensures we make at most one such call per prompt name per TTL.
        """
        client = self._ensure_client()
        if client is None:
            return None
        try:
            # Default executor: Langfuse get_prompt() is I/O-bound (fast), not
            # CPU-bound — it must not use the dedicated _PDF_EXECUTOR which is
            # reserved for WeasyPrint rendering.  asyncio.to_thread() dispatches
            # to the default ThreadPoolExecutor, keeping the two workloads
            # isolated.  LF-2 — T-211.
            prompt = await asyncio.wait_for(
                asyncio.to_thread(
                    client.get_prompt,
                    name,
                    version=version,
                    cache_ttl_seconds=settings.langfuse_prompt_cache_ttl,
                ),
                timeout=settings.langfuse_prompt_fetch_timeout_seconds,
            )
            body = getattr(prompt, "prompt", None)
            return body if isinstance(body, str) and body else None
        except asyncio.TimeoutError:
            logger.warning(
                "langfuse.get_prompt.timeout",
                prompt_name=name,
                timeout_seconds=settings.langfuse_prompt_fetch_timeout_seconds,
            )
            return None
        except Exception:
            logger.error("langfuse.get_prompt.failed", exc_info=True)
            return None


_INSTANCE: LangfuseClient | None = None
_INSTANCE_LOCK = threading.Lock()


def get_langfuse_client() -> LangfuseClient:
    """Return the process-wide LangfuseClient singleton."""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = LangfuseClient()
    return _INSTANCE


def reset_langfuse_client() -> None:
    """Drop the cached singleton. Intended for tests that reload settings to
    flip the enabled/disabled mode mid-process. No-op outside of tests."""
    global _INSTANCE
    _INSTANCE = None
