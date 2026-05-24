from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import openai

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError

# Explicit timeouts prevent a hung provider from blocking a credit reservation
# indefinitely.  connect/write are short (fast-fail on connection issues);
# read allows long streaming responses.  H-6 — T-182.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self._client = openai.AsyncOpenAI(
            api_key=api_key or settings.openai_api_key,
            timeout=_DEFAULT_TIMEOUT,
        )

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
                # Guard 1: OpenAI sends usage-only chunks where choices=[] to
                # report token counts.  Accessing choices[0] on such a chunk
                # raises IndexError and crashes the SSE stream, leaving any
                # credit reservation unreleased.  HF-2 — T-199.
                if not chunk.choices:
                    continue
                # Guard 2: The final chunk may have delta=None (no content).
                if chunk.choices[0].delta is None:
                    continue
                # Guard 3: Tool-use and stop chunks send delta.content=None.
                content = chunk.choices[0].delta.content
                if content is None:
                    continue
                yield content
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
