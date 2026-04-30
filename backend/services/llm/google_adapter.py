from __future__ import annotations

from collections.abc import AsyncGenerator

import google.api_core.exceptions
import google.generativeai as genai

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError


class GoogleAdapter(BaseLLMAdapter):
    def __init__(self, model: str) -> None:
        self.model = model
        genai.configure(api_key=settings.google_api_key)

    def _make_model(self, system: str) -> genai.GenerativeModel:
        return genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system,
        )

    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        try:
            gen_model = self._make_model(system)
            response = await gen_model.generate_content_async(
                user,
                stream=True,
                generation_config={"max_output_tokens": max_tokens},
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except google.api_core.exceptions.GoogleAPIError as exc:
            raise ProviderError("google", exc) from exc

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        try:
            gen_model = self._make_model(system)
            response = await gen_model.generate_content_async(
                user,
                generation_config={"max_output_tokens": max_tokens},
            )
            return response.text
        except google.api_core.exceptions.GoogleAPIError as exc:
            raise ProviderError("google", exc) from exc
