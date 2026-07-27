from __future__ import annotations

import re
from collections.abc import AsyncGenerator

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import settings
from services.llm.base import (
    RATE_LIMIT_STATUS_CODES,
    BaseLLMAdapter,
    ProviderError,
    ProviderRateLimitError,
    classify_provider_status,
    extract_retry_after,
)
from services.llm.completion import LLMCompletionInfo
from services.llm.model_catalog import model_request_policy
from services.llm.prompt_cache import PromptCachePolicy

# Explicit read timeout (milliseconds) prevents a hung Gemini connection from
# blocking a credit reservation indefinitely.  H-6 — T-182.
_DEFAULT_TIMEOUT_MS = 300_000  # 5 minutes


# Gemini never sets a ``Retry-After`` HTTP header on a 429. It returns the wait
# as a google.rpc.RetryInfo entry inside the JSON error body, and restates it in
# the human-readable message. Both forms are read below, because discarding the
# hint makes every retry fire inside the still-closed quota window and burns the
# whole retry budget in seconds (the generation then fails with the sibling
# chunks' paid-for output thrown away).
_RETRY_INFO_TYPE_SUFFIX = "google.rpc.RetryInfo"
_RETRY_DELAY_RE = re.compile(r"retry in\s+([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE)
_DURATION_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*s\s*$", re.IGNORECASE)


def _google_retry_after(exc: genai_errors.APIError) -> float | None:
    """Seconds Google asked us to wait before retrying, or ``None``.

    Tries, in order: the standard ``Retry-After`` header (never seen from Gemini
    today, but free), the structured ``RetryInfo.retryDelay`` in the error body,
    and finally the delay restated in the error message. Purely advisory — any
    malformed or missing hint returns ``None`` and the caller falls back to
    exponential backoff. Never raises.
    """
    header_hint = extract_retry_after(exc)
    if header_hint is not None:
        return header_hint

    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        error_block = details.get("error")
        entries = error_block.get("details") if isinstance(error_block, dict) else None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if not str(entry.get("@type", "")).endswith(_RETRY_INFO_TYPE_SUFFIX):
                    continue
                match = _DURATION_RE.match(str(entry.get("retryDelay", "")))
                if match:
                    return float(match.group(1))

    message = getattr(exc, "message", None)
    if isinstance(message, str):
        match = _RETRY_DELAY_RE.search(message)
        if match:
            return float(match.group(1))
    return None


def _wrap_google_error(exc: genai_errors.APIError) -> ProviderError:
    """Map a Google genai SDK error to the right ProviderError subclass (F2).

    A 429 (RESOURCE_EXHAUSTED) or 503 (UNAVAILABLE) becomes a
    ``ProviderRateLimitError`` so the pipeline retries in place without
    escalating the model tier; everything else stays a generic ``ProviderError``.
    The genai ``APIError`` exposes the HTTP status on ``.code``.
    """
    if classify_provider_status(exc) in RATE_LIMIT_STATUS_CODES:
        return ProviderRateLimitError(
            "google", exc, retry_after=_google_retry_after(exc)
        )
    return ProviderError("google", exc)


class GoogleAdapter(BaseLLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        operation: str | None = None,
    ) -> None:
        self.model = model
        self.last_completion: LLMCompletionInfo | None = None
        self._request_policy = model_request_policy("google", model, operation)
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
        cache_policy: PromptCachePolicy | None = None,
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
            raise _wrap_google_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise ProviderError("google", exc) from exc

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,  # explicit caching deferred; implicit applies
        cache_policy: PromptCachePolicy | None = None,
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
            raise _wrap_google_error(exc) from exc
        except (httpx.HTTPError, RuntimeError, OSError) as exc:
            raise ProviderError("google", exc) from exc


def _capture_google_completion(
    completion: LLMCompletionInfo | None,
    response,
) -> None:
    if completion is None:
        return
    response_id = getattr(response, "response_id", None)
    if response_id:
        completion.raw["provider_response_id"] = str(response_id)
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
