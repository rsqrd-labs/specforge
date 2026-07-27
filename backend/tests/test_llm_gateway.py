from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
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
    adapter = get_llm("openai", "gpt-5.5")
    assert adapter.__class__.__name__ == "OpenAIAdapter"


def test_get_llm_google_returns_adapter() -> None:
    adapter = get_llm("google", "gemini-3.6-flash")
    assert adapter.__class__.__name__ == "GoogleAdapter"


def test_get_llm_rebuilds_adapter_when_provider_key_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_llm_cache()
    monkeypatch.setenv("OPENAI_API_KEY", "first-key")
    first = get_llm("openai", "gpt-5.5")

    monkeypatch.setenv("OPENAI_API_KEY", "second-key")
    second = get_llm("openai", "gpt-5.5")

    assert first is not second
    assert len(gateway._INSTANCES) == 2
    clear_llm_cache()


def test_get_llm_cache_is_operation_policy_aware() -> None:
    clear_llm_cache()

    first = get_llm("openai", "gpt-5.4-mini", operation="plan.generate")
    second = get_llm("openai", "gpt-5.4-mini", operation="refine.section")
    third = get_llm("openai", "gpt-5.4-mini", operation="plan.generate")

    assert first is third
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
        "get_llm() must return a fresh adapter after TTL expiry.  " "L-1 — T-223."
    )
    # The cache should contain only the newly-built adapter (the stale one was
    # evicted before insertion of the new one).
    assert len(gateway._INSTANCES) == 1
    clear_llm_cache()


@pytest.mark.asyncio
async def test_anthropic_adapter_stream_yields_tokens() -> None:
    """Text events are yielded as tokens; non-text events (thinking deltas,
    lifecycle events) yield an empty liveness sentinel for the stream
    watchdog — issue #19."""

    def _event(type_: str, text: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(type=type_, text=text)

    async def fake_events() -> AsyncGenerator[SimpleNamespace, None]:
        yield _event("message_start")
        yield _event("thinking")
        for token in ["Hello", " ", "world"]:
            yield _event("text", token)
        yield _event("message_stop")

    class _FakeMessageStream:
        def __aiter__(self):
            return fake_events()

        get_final_message = AsyncMock(
            return_value=MagicMock(
                stop_reason="end_turn", usage=MagicMock(input_tokens=3)
            )
        )

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=_FakeMessageStream())
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    adapter = get_llm("anthropic", "claude-sonnet-4-6")
    with patch.object(adapter._client.messages, "stream", return_value=mock_stream_ctx):
        tokens = [t async for t in adapter.stream("sys", "user", 100)]

    assert tokens == ["", "", "Hello", " ", "world", ""]
    assert "".join(tokens) == "Hello world"
    assert adapter.last_completion is not None
    assert adapter.last_completion.finish_reason == "end_turn"
    assert adapter.last_completion.stopped_by_limit is False


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
            yield SimpleNamespace(type="response.output_text.delta", delta=content)

    adapter = get_llm("openai", "gpt-5.5")
    with patch.object(
        adapter._client.responses,
        "create",
        new_callable=AsyncMock,
        return_value=fake_chunks(),
    ):
        tokens = [t async for t in adapter.stream("sys", "user", 100)]

    assert tokens == ["Hi", " there"]


@pytest.mark.asyncio
async def test_openai_adapter_complete_returns_string() -> None:
    mock_response = MagicMock()
    mock_response.output_text = "Done"
    mock_response.status = "completed"

    adapter = get_llm("openai", "gpt-5.5")
    with patch.object(
        adapter._client.responses,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await adapter.complete("sys", "user", 100)

    assert result == "Done"
