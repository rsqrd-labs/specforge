from __future__ import annotations

from collections.abc import AsyncGenerator

import anthropic
import httpx

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError
from services.llm.completion import LLMCompletionInfo
from services.llm.model_catalog import model_request_policy

# Explicit timeouts prevent a hung provider from blocking a credit reservation
# indefinitely.  connect/write are short (fast-fail on connection issues);
# read allows long streaming responses.  H-6 — T-182.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._request_policy = model_request_policy("anthropic", model)
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
            raise ProviderError("anthropic", exc) from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
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
            raise ProviderError("anthropic", exc) from exc

    def _messages_request(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        cache_system: bool = False,
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
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }
        effort = self._request_policy["reasoning_effort"]
        if effort:
            request["extra_body"] = {"effort": effort}
        return request


def _object_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": str(value)}
