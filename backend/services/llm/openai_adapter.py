from __future__ import annotations

from collections.abc import AsyncGenerator

import openai

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self._client = openai.AsyncOpenAI(api_key=api_key or settings.openai_api_key)

    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                stream=True,
                max_tokens=max_tokens,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta is not None:
                    yield delta
        except openai.OpenAIError as exc:
            raise ProviderError("openai", exc) from exc

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except openai.OpenAIError as exc:
            raise ProviderError("openai", exc) from exc
