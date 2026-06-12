from __future__ import annotations

from collections.abc import AsyncGenerator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import settings
from services.llm.base import BaseLLMAdapter, ProviderError
from services.llm.completion import LLMCompletionInfo
from services.llm.model_catalog import model_request_policy

# Explicit read timeout (milliseconds) prevents a hung Gemini connection from
# blocking a credit reservation indefinitely.  H-6 — T-182.
_DEFAULT_TIMEOUT_MS = 300_000  # 5 minutes


class GoogleAdapter(BaseLLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._request_policy = model_request_policy("google", model)
        self._client = genai.Client(
            api_key=api_key or settings.google_api_key,
            http_options=types.HttpOptions(timeout=_DEFAULT_TIMEOUT_MS),
        )

    def _config(self, system: str, max_tokens: int) -> types.GenerateContentConfig:
        thinking_level = self._request_policy["thinking_level"]
        return types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=(
                types.ThinkingConfig(thinking_level=thinking_level)
                if thinking_level
                else None
            ),
        )

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # explicit caching deferred; implicit applies
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
                # Chunks without visible text (thinking phases, metadata-only
                # chunks) yield an empty liveness sentinel: the stream watchdog
                # resets its idle timer on every yielded item and forwards only
                # non-empty tokens, so silent thinking is never killed as
                # "stalled" (issue #19).
                yield chunk.text or ""
        except genai_errors.APIError as exc:
            raise ProviderError("google", exc) from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # explicit caching deferred; implicit applies
    ) -> str:
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
