from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

import anthropic
import httpx

from config import settings
from services.llm.base import (
    RATE_LIMIT_STATUS_CODES,
    BaseLLMAdapter,
    BatchRequest,
    BatchResultItem,
    ProviderError,
    ProviderRateLimitError,
    classify_provider_status,
    extract_retry_after,
)
from services.llm.completion import LLMCompletionInfo
from services.llm.model_catalog import model_request_policy

# Explicit timeouts prevent a hung provider from blocking a credit reservation
# indefinitely.  connect/write are short (fast-fail on connection issues);
# read allows long streaming responses.  H-6 — T-182.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


def _wrap_anthropic_error(exc: anthropic.APIError) -> ProviderError:
    """Map an Anthropic SDK error to the right ProviderError subclass (F2).

    A 429 (``RateLimitError``) or 529 overloaded becomes a
    ``ProviderRateLimitError`` carrying any ``Retry-After`` hint so the pipeline
    retries in place without escalating the model tier; everything else stays a
    generic ``ProviderError``.
    """
    status = classify_provider_status(exc)
    if isinstance(exc, anthropic.RateLimitError) or status in RATE_LIMIT_STATUS_CODES:
        return ProviderRateLimitError(
            "anthropic", exc, retry_after=extract_retry_after(exc)
        )
    return ProviderError("anthropic", exc)


class AnthropicAdapter(BaseLLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._request_policy = model_request_policy("anthropic", model, operation)
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key,
            timeout=_DEFAULT_TIMEOUT,
        )

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_user_prefix: str | None = None,
    ) -> AsyncGenerator[str, None]:
        self.last_completion = LLMCompletionInfo.started(
            provider="anthropic",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            async with self._client.messages.stream(
                **self._messages_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    cache_system=cache_system,
                    cache_user_prefix=cache_user_prefix,
                ),
            ) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield event.text
                    else:
                        # Liveness sentinel: reasoning/thinking deltas, pings,
                        # and block boundaries carry no visible text but prove
                        # the provider stream is healthy.  The stream watchdog
                        # resets its idle timer on every yielded item and
                        # forwards only non-empty tokens, so a frontier model
                        # reasoning silently for minutes is never killed as
                        # "stalled" (issue #19).
                        yield ""
                final_message = await stream.get_final_message()
                if self.last_completion is not None:
                    self.last_completion.apply_finish_reason(
                        getattr(final_message, "stop_reason", None)
                    )
                    usage = getattr(final_message, "usage", None)
                    if usage is not None:
                        self.last_completion.usage = _object_to_dict(usage)
        except anthropic.APIError as exc:
            raise _wrap_anthropic_error(exc) from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_user_prefix: str | None = None,
    ) -> str:
        self.last_completion = LLMCompletionInfo.started(
            provider="anthropic",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            response = await self._client.messages.create(
                **self._messages_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    cache_system=cache_system,
                    cache_user_prefix=cache_user_prefix,
                ),
            )
            if self.last_completion is not None:
                self.last_completion.apply_finish_reason(
                    getattr(response, "stop_reason", None)
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.last_completion.usage = _object_to_dict(usage)
            return response.content[0].text
        except anthropic.APIError as exc:
            raise _wrap_anthropic_error(exc) from exc

    async def submit_batch(self, requests: Sequence[BatchRequest]) -> str:
        """Create a Message Batch (50% discount) and return its id.

        Each request reuses ``_messages_request`` for body parity with the live
        path, minus ``extra_body`` (a client-level kwarg the per-request batch
        params do not carry — the judge's reasoning effort is non-critical and
        omitting it never changes correctness). A batch-of-one still earns the
        full batch discount, so the caller need not aggregate.
        """
        try:
            batch_requests = [
                {
                    "custom_id": req.custom_id,
                    "params": self._batch_params(
                        system=req.system,
                        user=req.user,
                        max_tokens=req.max_tokens,
                    ),
                }
                for req in requests
            ]
            batch = await self._client.beta.messages.batches.create(
                requests=batch_requests
            )
            return batch.id
        except anthropic.APIError as exc:
            raise _wrap_anthropic_error(exc) from exc

    async def poll_batch(self, provider_batch_id: str) -> str:
        try:
            batch = await self._client.beta.messages.batches.retrieve(provider_batch_id)
            return str(getattr(batch, "processing_status", "") or "")
        except anthropic.APIError as exc:
            raise _wrap_anthropic_error(exc) from exc

    async def fetch_batch_results(
        self, provider_batch_id: str
    ) -> dict[str, BatchResultItem]:
        results: dict[str, BatchResultItem] = {}
        try:
            # The async SDK's results() is itself a coroutine that fetches the
            # results file; it must be awaited before async-iterating the
            # per-request entries (it returns an AsyncJSONLDecoder).
            stream = await self._client.beta.messages.batches.results(provider_batch_id)
            async for entry in stream:
                results[entry.custom_id] = _normalize_batch_result(entry)
        except anthropic.APIError as exc:
            raise _wrap_anthropic_error(exc) from exc
        return results

    def _batch_params(self, *, system: str, user: str, max_tokens: int) -> dict:
        params = self._messages_request(
            system=system,
            user=user,
            max_tokens=max_tokens,
            cache_system=False,
        )
        params.pop("extra_body", None)
        return params

    def _messages_request(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        cache_system: bool = False,
        cache_user_prefix: str | None = None,
    ) -> dict:
        # When caching is enabled and requested, wrap the system string as a
        # content block with cache_control so the provider can store and reuse
        # the token representation across calls that share this stable prefix.
        # Anthropic requires ≥1024 tokens (Sonnet/Opus) or ≥2048 (Haiku 4.5)
        # to create a cache entry; the ASDD base prompt (~4 K tokens) easily
        # clears both thresholds.  No beta header needed for Claude 4 models.
        if cache_system and settings.llm_prompt_cache_enabled:
            system_value: object = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_value = system

        request: dict = {
            "model": self.model,
            "system": system_value,
            "messages": [
                {
                    "role": "user",
                    "content": _user_content(user, cache_user_prefix),
                }
            ],
            "max_tokens": max_tokens,
        }
        effort = self._request_policy["reasoning_effort"]
        if effort:
            request["extra_body"] = {"effort": effort}
        return request


# Anthropic only creates a cache entry for a block of ≥1024 tokens (Sonnet/Opus)
# or ≥2048 tokens (Haiku 4.5); below that the cache_control marker is silently
# ignored.  Marking only prefixes that comfortably clear the largest floor keeps
# us off that edge entirely (it cannot turn into an API error on a sub-minimum
# block) and avoids spending a breakpoint on a block that could never cache —
# notably the *compressed* spec problem statement, which is small and
# output-bound, so it loses nothing.  ~4 chars/token × 2048 ≈ 8K chars,
# conservative; the input-heavy stages (plan/harness/tasks embed up to 200K
# chars of upstream artifacts) clear it by a wide margin.
_MIN_CACHEABLE_PREFIX_CHARS = 8192


def _user_content(user: str, cache_user_prefix: str | None) -> object:
    """Build the ``user`` message content, caching its stable prefix when asked.

    Issue #39 (Lever A): chunked stage generation re-sends an identical
    ``base_user_prompt`` (problem statement + up to 200K chars of upstream
    artifacts) on every chunk and every repair, with only a short per-chunk
    suffix changing.  Splitting the user message into a stable prefix block
    (marked ``cache_control: ephemeral``) and a variable suffix block lets
    Anthropic reuse the cached prefix tokens on chunks 2+/repairs — the dominant
    per-chunk input cost for plan/harness/tasks.

    The split is purely a transport optimisation: Anthropic concatenates text
    blocks, so the model sees byte-identical input and the generated artifact is
    unchanged.  Returns the plain string (the pre-#39 request, the regression
    pin) whenever caching is off, no prefix was given, the prefix is not a proper
    prefix of ``user`` with a non-empty suffix (never an empty text block, which
    the API rejects), or the prefix is too small to be cacheable anyway.
    """
    if (
        not cache_user_prefix
        or not settings.llm_prompt_cache_enabled
        or not user.startswith(cache_user_prefix)
        or len(cache_user_prefix) >= len(user)
        or len(cache_user_prefix) < _MIN_CACHEABLE_PREFIX_CHARS
    ):
        return user
    return [
        {
            "type": "text",
            "text": cache_user_prefix,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": user[len(cache_user_prefix) :]},
    ]


def _normalize_batch_result(entry) -> BatchResultItem:
    """Map one Anthropic batch result entry to a provider-neutral item.

    Succeeded entries carry a full Message (``result.message``); errored/expired/
    canceled entries carry no usable text. Tolerant of SDK shape via getattr so a
    minor SDK bump cannot break collection.
    """
    custom_id = entry.custom_id
    result = getattr(entry, "result", None)
    status = str(getattr(result, "type", "") or "errored")
    if status == "succeeded":
        message = getattr(result, "message", None)
        content = getattr(message, "content", None) or []
        text = next(
            (
                getattr(block, "text", None)
                for block in content
                if getattr(block, "type", None) == "text"
            ),
            None,
        )
        usage = getattr(message, "usage", None)
        return BatchResultItem(
            custom_id=custom_id,
            status="succeeded",
            text=text,
            usage=_object_to_dict(usage) if usage is not None else None,
            finish_reason=getattr(message, "stop_reason", None),
        )
    error = getattr(result, "error", None)
    return BatchResultItem(
        custom_id=custom_id,
        status=status,
        error=str(getattr(error, "type", None) or error or status),
    )


def _object_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": str(value)}
