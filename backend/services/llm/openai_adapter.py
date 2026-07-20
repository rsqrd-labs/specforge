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

# Explicit timeouts prevent a hung provider from blocking a credit reservation
# indefinitely.  connect/write are short (fast-fail on connection issues);
# read allows long streaming responses.  H-6 — T-182.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


def _wrap_openai_error(exc: openai.OpenAIError) -> ProviderError:
    """Map an OpenAI SDK error to the right ProviderError subclass (F2).

    A 429 (``RateLimitError``) becomes a ``ProviderRateLimitError`` carrying any
    ``Retry-After`` hint so the pipeline retries in place without escalating the
    model tier; everything else stays a generic ``ProviderError``.
    """
    status = classify_provider_status(exc)
    is_rate_limited = (
        isinstance(exc, getattr(openai, "RateLimitError", ()))
        or status in RATE_LIMIT_STATUS_CODES
    )
    if is_rate_limited:
        return ProviderRateLimitError(
            "openai", exc, retry_after=extract_retry_after(exc)
        )
    return ProviderError("openai", exc)


def _wrap_openai_transport_error(exc: Exception) -> ProviderError:
    """Normalise SDK-bypassing stream transport failures."""
    return ProviderError("openai", exc)


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._request_policy = model_request_policy("openai", model, operation)
        self._client = openai.AsyncOpenAI(
            api_key=api_key or settings.openai_api_key,
            timeout=_DEFAULT_TIMEOUT,
        )

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # automatic prefix caching; no explicit opt-in
        cache_policy: PromptCachePolicy | None = None,
    ) -> AsyncGenerator[str, None]:
        self.last_completion = LLMCompletionInfo.started(
            provider="openai",
            model=self.model,
            max_tokens=max_tokens,
        )
        if self._uses_responses_api():
            async for token in self._stream_responses_api(
                system, user, max_tokens, cache_policy
            ):
                yield token
            return
        async for token in self._stream_chat_completions(
            system, user, max_tokens, cache_policy
        ):
            yield token

    async def _stream_responses_api(
        self,
        system: str,
        user: str,
        max_tokens: int,
        cache_policy: PromptCachePolicy | None,
    ) -> AsyncGenerator[str, None]:
        try:
            response = await self._responses_client().create(
                **self._responses_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    stream=True,
                    cache_policy=cache_policy,
                ),
            )
            async for event in response:
                _capture_openai_response_completion(self.last_completion, event)
                delta = _responses_event_text_delta(event)
                # Non-text events (reasoning deltas, lifecycle events) yield an
                # empty liveness sentinel: the stream watchdog resets its idle
                # timer on every yielded item and forwards only non-empty
                # tokens, so silent reasoning phases are never killed as
                # "stalled" (issue #19).
                yield delta if delta else ""
        except openai.OpenAIError as exc:
            raise _wrap_openai_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise _wrap_openai_transport_error(exc) from exc

    async def _stream_chat_completions(
        self,
        system: str,
        user: str,
        max_tokens: int,
        cache_policy: PromptCachePolicy | None,
    ) -> AsyncGenerator[str, None]:
        try:
            response = await self._client.chat.completions.create(
                **self._chat_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    cache_policy=cache_policy,
                ),
                stream=True,
            )
            async for chunk in response:
                _capture_openai_resolved_model(self.last_completion, chunk)
                # Guard 1: OpenAI sends usage-only chunks where choices=[] to
                # report token counts.  Accessing choices[0] on such a chunk
                # raises IndexError and crashes the SSE stream, leaving any
                # credit reservation unreleased.  HF-2 — T-199.
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
                # Guard 2: The final chunk may have delta=None (no content).
                if choice.delta is None:
                    yield ""
                    continue
                # Guard 3: Tool-use and stop chunks send delta.content=None.
                # All three guard paths yield an empty liveness sentinel (see
                # the responses-API stream above) instead of skipping silently.
                content = choice.delta.content
                if content is None:
                    yield ""
                    continue
                yield content
        except openai.OpenAIError as exc:
            raise _wrap_openai_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise _wrap_openai_transport_error(exc) from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # automatic prefix caching; no explicit opt-in
        cache_policy: PromptCachePolicy | None = None,
    ) -> str:
        self.last_completion = LLMCompletionInfo.started(
            provider="openai",
            model=self.model,
            max_tokens=max_tokens,
        )
        if self._uses_responses_api():
            return await self._complete_responses_api(
                system, user, max_tokens, cache_policy
            )
        return await self._complete_chat_completions(
            system, user, max_tokens, cache_policy
        )

    async def _complete_responses_api(
        self,
        system: str,
        user: str,
        max_tokens: int,
        cache_policy: PromptCachePolicy | None,
    ) -> str:
        try:
            response = await self._responses_client().create(
                **self._responses_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    stream=False,
                    cache_policy=cache_policy,
                ),
            )
            _capture_openai_response_completion(self.last_completion, response)
            return _response_output_text(response)
        except openai.OpenAIError as exc:
            raise _wrap_openai_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise _wrap_openai_transport_error(exc) from exc

    async def _complete_chat_completions(
        self,
        system: str,
        user: str,
        max_tokens: int,
        cache_policy: PromptCachePolicy | None,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                **self._chat_request(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    cache_policy=cache_policy,
                ),
            )
            choice = response.choices[0]
            if self.last_completion is not None:
                _capture_openai_resolved_model(self.last_completion, response)
                self.last_completion.apply_finish_reason(
                    getattr(choice, "finish_reason", None)
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.last_completion.usage = _object_to_dict(usage)
            return choice.message.content or ""
        except openai.OpenAIError as exc:
            raise _wrap_openai_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise _wrap_openai_transport_error(exc) from exc

    def _uses_responses_api(self) -> bool:
        return self._request_policy["adapter_api"] == "responses"

    def _responses_client(self):
        responses = getattr(self._client, "responses", None)
        if responses is None:
            raise RuntimeError(
                "OpenAI Responses API is required for the configured model. "
                "Upgrade the openai SDK to a version that exposes client.responses."
            )
        return responses

    def _responses_request(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        stream: bool,
        cache_policy: PromptCachePolicy | None = None,
    ) -> dict:
        request = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": max_tokens,
            "stream": stream,
        }
        effort = self._request_policy["reasoning_effort"]
        if effort:
            # summary="auto" makes the API stream reasoning-summary deltas
            # during the otherwise fully-silent reasoning phase.  Without
            # them a high-effort model can produce zero stream events for
            # minutes, which trips the stream watchdog's idle bound and the
            # HTTP client's read timeout even though the generation is
            # healthy (issue #19).  The deltas carry no output text — the
            # stream path yields them as empty liveness sentinels.
            request["reasoning"] = {"effort": effort, "summary": "auto"}
        self._apply_prompt_cache_policy(request, cache_policy)
        return request

    def _chat_request(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        cache_policy: PromptCachePolicy | None = None,
    ) -> dict:
        request = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        self._apply_prompt_cache_policy(request, cache_policy)
        return request

    def _apply_prompt_cache_policy(
        self,
        request: dict,
        cache_policy: PromptCachePolicy | None,
    ) -> None:
        if not settings.llm_prompt_cache_enabled or cache_policy is None:
            return
        if self._request_policy.get("prompt_cache_key"):
            request["prompt_cache_key"] = cache_policy.routing_key
        if cache_policy.retention == "24h" and self._request_policy.get(
            "extended_prompt_cache_retention"
        ):
            request["prompt_cache_retention"] = "24h"


def _responses_event_text_delta(event) -> str | None:
    event_type = str(getattr(event, "type", ""))
    if event_type == "response.output_text.delta":
        delta = getattr(event, "delta", None)
        return str(delta) if delta is not None else None
    return None


def _capture_openai_response_completion(
    completion: LLMCompletionInfo | None,
    response_or_event,
) -> None:
    if completion is None:
        return
    response = getattr(response_or_event, "response", response_or_event)
    status = getattr(response, "status", None)
    if status:
        completion.apply_finish_reason(status)
    usage = getattr(response, "usage", None)
    if usage is not None:
        completion.usage = _object_to_dict(usage)
    resolved_model = getattr(response, "model", None)
    if resolved_model:
        completion.raw["resolved_model"] = str(resolved_model)
    response_id = getattr(response, "id", None)
    if response_id:
        completion.raw["provider_response_id"] = str(response_id)


def _capture_openai_resolved_model(
    completion: LLMCompletionInfo | None,
    response_or_chunk,
) -> None:
    if completion is None:
        return
    resolved_model = getattr(response_or_chunk, "model", None)
    if resolved_model:
        completion.raw["resolved_model"] = str(resolved_model)


def _response_output_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)
    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
    return "".join(parts)


def _object_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": str(value)}
