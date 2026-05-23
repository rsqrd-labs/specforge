from __future__ import annotations

from collections.abc import AsyncGenerator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError

# Explicit read timeout (milliseconds) prevents a hung Gemini connection from
# blocking a credit reservation indefinitely.  H-6 — T-182.
_DEFAULT_TIMEOUT_MS = 300_000  # 5 minutes


class GoogleAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self._client = genai.Client(
            api_key=api_key or settings.google_api_key,
            http_options=types.HttpOptions(timeout=_DEFAULT_TIMEOUT_MS),
        )

    def _config(self, system: str, max_tokens: int) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )

    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        try:
            response = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=user,
                config=self._config(system, max_tokens),
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except genai_errors.APIError as exc:
            raise ProviderError("google", exc) from exc

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=user,
                config=self._config(system, max_tokens),
            )
            return response.text or ""
        except genai_errors.APIError as exc:
            raise ProviderError("google", exc) from exc
