from __future__ import annotations

from collections.abc import AsyncGenerator

import anthropic

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError


class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, model: str) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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
