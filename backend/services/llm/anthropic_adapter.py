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
        self, system: str, user: str, max_tokens: int
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
                ),
            ) as stream:
                async for text in stream.text_stream:
                    yield text
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

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
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

    def _messages_request(self, *, system: str, user: str, max_tokens: int) -> dict:
        request = {
            "model": self.model,
            "system": system,
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
