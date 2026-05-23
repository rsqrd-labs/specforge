from __future__ import annotations

from collections.abc import AsyncGenerator

import anthropic
import httpx

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError

# Explicit timeouts prevent a hung provider from blocking a credit reservation
# indefinitely.  connect/write are short (fast-fail on connection issues);
# read allows long streaming responses.  H-6 — T-182.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key,
            timeout=_DEFAULT_TIMEOUT,
        )

    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        try:
            async with self._client.messages.stream(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.APIError as exc:
            raise ProviderError("anthropic", exc) from exc

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        try:
            response = await self._client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
            )
            return response.content[0].text
        except anthropic.APIError as exc:
            raise ProviderError("anthropic", exc) from exc
