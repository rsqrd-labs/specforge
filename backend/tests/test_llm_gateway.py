from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from services.llm import gateway
from services.llm.base import BaseLLMAdapter, ProviderError
from services.llm.gateway import clear_llm_cache, get_llm


def test_get_llm_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_llm("unknown", "model")


def test_base_adapter_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        BaseLLMAdapter()  # type: ignore[abstract]


def test_get_llm_anthropic_returns_adapter() -> None:
    adapter = get_llm("anthropic", "claude-sonnet-4-6")
    assert adapter.__class__.__name__ == "AnthropicAdapter"


def test_get_llm_openai_returns_adapter() -> None:
    adapter = get_llm("openai", "gpt-4o")
    assert adapter.__class__.__name__ == "OpenAIAdapter"


def test_get_llm_google_returns_adapter() -> None:
    adapter = get_llm("google", "gemini-1.5-pro")
    assert adapter.__class__.__name__ == "GoogleAdapter"


def test_get_llm_rebuilds_adapter_when_provider_key_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_llm_cache()
    monkeypatch.setenv("OPENAI_API_KEY", "first-key")
    first = get_llm("openai", "gpt-4o")

    monkeypatch.setenv("OPENAI_API_KEY", "second-key")
    second = get_llm("openai", "gpt-4o")

    assert first is not second
    assert len(gateway._INSTANCES) == 2
    clear_llm_cache()


def test_get_llm_rebuilds_adapter_after_ttl_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapters older than _INSTANCE_CACHE_TTL_SECONDS must be evicted and
    rebuilt on the next get_llm() call.  This ensures stale httpx connection
    pools are recycled periodically rather than served indefinitely.
    L-1 — T-223.
    """
    import time

    clear_llm_cache()
    # Shorten the TTL to 0 so the adapter is immediately stale.
    monkeypatch.setattr(gateway, "_INSTANCE_CACHE_TTL_SECONDS", 0.0)

    first = get_llm("anthropic", "claude-sonnet-4-6")

    # Advance monotonic time by enough to exceed TTL=0.
    # We sleep briefly so _time.monotonic() returns a value > created_at + 0.
    time.sleep(0.01)

    second = get_llm("anthropic", "claude-sonnet-4-6")

    assert first is not second, (
        "get_llm() must return a fresh adapter after TTL expiry.  "
        "L-1 — T-223."
    )
    # The cache should contain only the newly-built adapter (the stale one was
    # evicted before insertion of the new one).
    assert len(gateway._INSTANCES) == 1
    clear_llm_cache()


@pytest.mark.asyncio
async def test_anthropic_adapter_stream_yields_tokens() -> None:

    async def fake_text_stream() -> AsyncGenerator[str, None]:
        for token in ["Hello", " ", "world"]:
            yield token

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(
        return_value=MagicMock(text_stream=fake_text_stream())
    )
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    adapter = get_llm("anthropic", "claude-sonnet-4-6")
    with patch.object(adapter._client.messages, "stream", return_value=mock_stream_ctx):
        tokens = [t async for t in adapter.stream("sys", "user", 100)]

    assert tokens == ["Hello", " ", "world"]


@pytest.mark.asyncio
async def test_anthropic_adapter_stream_raises_provider_error() -> None:

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(
        side_effect=anthropic.APIConnectionError(request=MagicMock())
    )
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    adapter = get_llm("anthropic", "claude-sonnet-4-6")
    with patch.object(adapter._client.messages, "stream", return_value=mock_stream_ctx):
        with pytest.raises(ProviderError) as exc_info:
            async for _ in adapter.stream("sys", "user", 100):
                pass

    assert exc_info.value.provider == "anthropic"


@pytest.mark.asyncio
async def test_openai_adapter_stream_yields_tokens() -> None:
    async def fake_chunks() -> AsyncGenerator[Any, None]:
        for content in ["Hi", " there"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            yield chunk

    adapter = get_llm("openai", "gpt-4o")
    with patch.object(
        adapter._client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=fake_chunks(),
    ):
        tokens = [t async for t in adapter.stream("sys", "user", 100)]

    assert tokens == ["Hi", " there"]


@pytest.mark.asyncio
async def test_openai_adapter_complete_returns_string() -> None:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Done"

    adapter = get_llm("openai", "gpt-4o")
    with patch.object(
        adapter._client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await adapter.complete("sys", "user", 100)

    assert result == "Done"
