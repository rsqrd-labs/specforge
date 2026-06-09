from __future__ import annotations

from collections.abc import AsyncGenerator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError
from services.llm.completion import LLMCompletionInfo

# Explicit read timeout (milliseconds) prevents a hung Gemini connection from
# blocking a credit reservation indefinitely.  H-6 — T-182.
_DEFAULT_TIMEOUT_MS = 300_000  # 5 minutes


class GoogleAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
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
        self.last_completion = LLMCompletionInfo.started(
            provider="google",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            response = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=user,
                config=self._config(system, max_tokens),
            )
            async for chunk in response:
                _capture_google_completion(self.last_completion, chunk)
                if chunk.text:
                    yield chunk.text
        except genai_errors.APIError as exc:
            raise ProviderError("google", exc) from exc

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        self.last_completion = LLMCompletionInfo.started(
            provider="google",
            model=self.model,
            max_tokens=max_tokens,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=user,
                config=self._config(system, max_tokens),
            )
            _capture_google_completion(self.last_completion, response)
            return response.text or ""
        except genai_errors.APIError as exc:
            raise ProviderError("google", exc) from exc


def _capture_google_completion(
    completion: LLMCompletionInfo | None,
    response,
) -> None:
    if completion is None:
        return
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        completion.apply_finish_reason(getattr(candidate, "finish_reason", None))
        if completion.finish_reason:
            break
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        completion.usage = _object_to_dict(usage)


def _object_to_dict(value) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": str(value)}
