from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import openai

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError
from services.llm.completion import LLMCompletionInfo

# Explicit timeouts prevent a hung provider from blocking a credit reservation
# indefinitely.  connect/write are short (fast-fail on connection issues);
# read allows long streaming responses.  H-6 — T-182.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._client = openai.AsyncOpenAI(
            api_key=api_key or settings.openai_api_key,
            timeout=_DEFAULT_TIMEOUT,
        )

    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        self.last_completion = LLMCompletionInfo.started(
            provider="openai",
            model=self.model,
            max_tokens=max_tokens,
        )
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
                    usage = getattr(chunk, "usage", None)
                    if usage is not None and self.last_completion is not None:
                        self.last_completion.usage = _object_to_dict(usage)
                    continue
                choice = chunk.choices[0]
                if self.last_completion is not None:
                    self.last_completion.apply_finish_reason(
                        getattr(choice, "finish_reason", None)
                    )
                # Guard 2: The final chunk may have delta=None (no content).
                if choice.delta is None:
                    continue
                # Guard 3: Tool-use and stop chunks send delta.content=None.
                content = choice.delta.content
                if content is None:
                    continue
                yield content
        except openai.OpenAIError as exc:
            raise ProviderError("openai", exc) from exc

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        self.last_completion = LLMCompletionInfo.started(
            provider="openai",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
            )
            choice = response.choices[0]
            if self.last_completion is not None:
                self.last_completion.apply_finish_reason(
                    getattr(choice, "finish_reason", None)
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.last_completion.usage = _object_to_dict(usage)
            return choice.message.content or ""
        except openai.OpenAIError as exc:
            raise ProviderError("openai", exc) from exc


def _object_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": str(value)}
