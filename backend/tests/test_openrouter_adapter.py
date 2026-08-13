"""Unit tests for the OpenRouter adapter (issue #152).

Mirrors test_openai_adapter.py's guard coverage (the chat-completions path
this adapter is modelled on) plus OpenRouter-specific behavior: usage/cost
accounting (stream_options + usage.include, since — unlike OpenAI's dead
chat-completions path — this IS the live path), route pinning
(data_collection=deny, allow_fallbacks=false), reasoning.effort gating on
the catalog value, and BatchUnsupportedError on all three batch methods.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from services.llm.base import (
    BatchUnsupportedError,
    ProviderError,
    ProviderRateLimitError,
)

# ---------------------------------------------------------------------------
# Helpers — build fake chunk objects that match the openai SDK shape
# ---------------------------------------------------------------------------


def _chunk(content: str | None = None, choices: list | None = None) -> Any:
    if choices is not None:
        return SimpleNamespace(choices=choices)
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(choices=[choice])


def _chunk_empty_choices(usage: Any = None) -> Any:
    """Usage-only chunk: choices=[] (no delta at all)."""
    return SimpleNamespace(choices=[], usage=usage)


def _chunk_delta_none() -> Any:
    choice = SimpleNamespace(delta=None)
    return SimpleNamespace(choices=[choice])


async def _fake_stream(chunks: list[Any]) -> AsyncIterator[Any]:
    for chunk in chunks:
        yield chunk


def _make_adapter(
    chunks: list[Any] | None = None,
    *,
    model: str = "deepseek/deepseek-v3.2",
    reasoning_effort: str | None = None,
) -> Any:
    from services.llm.openrouter_adapter import OpenRouterAdapter

    adapter = OpenRouterAdapter.__new__(OpenRouterAdapter)
    adapter.model = model
    adapter._request_policy = {"reasoning_effort": reasoning_effort}
    adapter.last_completion = None

    mock_create = AsyncMock()
    if chunks is not None:
        mock_create.return_value = _fake_stream(chunks)

    mock_completions = MagicMock()
    mock_completions.create = mock_create
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client = MagicMock()
    mock_client.chat = mock_chat
    adapter._client = mock_client

    return adapter


# ---------------------------------------------------------------------------
# OR-1: usage-only chunks (choices=[]) yield a sentinel and capture usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_choices_chunk_yields_liveness_sentinel_and_captures_usage() -> (
    None
):
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        prompt_tokens_details=SimpleNamespace(cached_tokens=2),
        cost=0.0001,
    )
    adapter = _make_adapter([_chunk_empty_choices(usage=usage), _chunk("hello")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["", "hello"]
    assert adapter.last_completion is not None
    assert adapter.last_completion.usage["prompt_tokens"] == 10
    assert adapter.last_completion.usage["cost"] == 0.0001


# ---------------------------------------------------------------------------
# OR-2 / OR-3: delta=None and delta.content=None both yield sentinels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_none_chunk_yields_liveness_sentinel() -> None:
    adapter = _make_adapter([_chunk_delta_none(), _chunk("world")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["", "world"]


@pytest.mark.asyncio
async def test_reasoning_delta_content_none_yields_liveness_sentinel() -> None:
    """delta.content=None is also how OpenRouter's reasoning_details deltas
    arrive — no special-cased branch is needed, guard 3 covers them."""
    adapter = _make_adapter([_chunk(content=None), _chunk("end")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["", "end"]


# ---------------------------------------------------------------------------
# OR-4 / OR-5 / OR-6: normal / mixed / empty streams
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_chunks_are_yielded() -> None:
    adapter = _make_adapter([_chunk("Hello"), _chunk(", "), _chunk("world!")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["Hello", ", ", "world!"]


@pytest.mark.asyncio
async def test_mixed_stream_yields_only_content() -> None:
    chunks = [
        _chunk("The "),
        _chunk_empty_choices(),
        _chunk("answer"),
        _chunk_delta_none(),
        _chunk(content=None),
    ]
    adapter = _make_adapter(chunks)

    result = ""
    async for token in adapter.stream("sys", "user", 200):
        result += token

    assert result == "The answer"


@pytest.mark.asyncio
async def test_entirely_empty_stream_yields_nothing() -> None:
    adapter = _make_adapter([])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == []


# ---------------------------------------------------------------------------
# OR-7 / OR-8: error wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_error_is_wrapped_as_provider_error_labelled_openrouter() -> None:
    adapter = _make_adapter()

    async def _raising_stream(*_a: Any, **_kw: Any) -> Any:
        raise openai.APIError("upstream error", request=MagicMock(), body=None)

    adapter._client.chat.completions.create = AsyncMock(side_effect=_raising_stream)

    with pytest.raises(ProviderError) as raised:
        async for _ in adapter.stream("sys", "user", 100):
            pass

    assert raised.value.provider == "openrouter"
    assert not isinstance(raised.value, ProviderRateLimitError)


@pytest.mark.asyncio
async def test_rate_limit_error_is_wrapped_with_retry_after() -> None:
    adapter = _make_adapter()

    response = MagicMock()
    response.headers = {"retry-after": "30"}
    error = openai.RateLimitError("rate limited", response=response, body=None)

    async def _raising_stream(*_a: Any, **_kw: Any) -> Any:
        raise error

    adapter._client.chat.completions.create = AsyncMock(side_effect=_raising_stream)

    with pytest.raises(ProviderRateLimitError) as raised:
        async for _ in adapter.stream("sys", "user", 100):
            pass

    assert raised.value.provider == "openrouter"
    assert raised.value.retry_after == 30.0


# ---------------------------------------------------------------------------
# OR-9: request shape — stream_options, usage.include, pinned provider route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_request_includes_usage_accounting_and_pinned_route() -> None:
    adapter = _make_adapter([_chunk("hi")])

    async for _ in adapter.stream("sys", "user", 4096):
        pass

    kwargs = adapter._client.chat.completions.create.await_args.kwargs
    assert kwargs["model"] == "deepseek/deepseek-v3.2"
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["extra_body"]["usage"] == {"include": True}
    assert kwargs["extra_body"]["provider"] == {
        "data_collection": "deny",
        "allow_fallbacks": False,
    }
    # No reasoning field when the catalog entry sets no effort (deepseek-v3.2).
    assert "reasoning" not in kwargs["extra_body"]


@pytest.mark.asyncio
async def test_reasoning_effort_sent_only_when_catalog_declares_it() -> None:
    adapter = _make_adapter(
        [_chunk("hi")], model="z-ai/glm-5.2", reasoning_effort="medium"
    )

    async for _ in adapter.stream("sys", "user", 4096):
        pass

    kwargs = adapter._client.chat.completions.create.await_args.kwargs
    assert kwargs["extra_body"]["reasoning"] == {"effort": "medium"}


# ---------------------------------------------------------------------------
# OR-10: complete()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_extracts_message_content_and_captures_usage() -> None:
    adapter = _make_adapter(model="qwen/qwen3.8-max", reasoning_effort="medium")
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Done"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, cost=0.0005),
        model="qwen/qwen3.8-max",
    )
    adapter._client.chat.completions.create = AsyncMock(return_value=response)

    result = await adapter.complete("sys", "user", 4096)

    assert result == "Done"
    kwargs = adapter._client.chat.completions.create.await_args.kwargs
    assert kwargs["extra_body"]["reasoning"] == {"effort": "medium"}
    assert "stream" not in kwargs
    assert adapter.last_completion is not None
    assert adapter.last_completion.usage["cost"] == 0.0005
    assert adapter.last_completion.raw["resolved_model"] == "qwen/qwen3.8-max"


# ---------------------------------------------------------------------------
# OR-11: base_url points at OpenRouter
# ---------------------------------------------------------------------------


def test_adapter_targets_the_openrouter_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.llm.openrouter_adapter import OpenRouterAdapter

    monkeypatch.setattr("config.settings.openrouter_api_key", "sk-or-test")
    adapter = OpenRouterAdapter("deepseek/deepseek-v3.2", api_key="sk-or-test")

    assert str(adapter._client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# OR-12: Message Batches are unsupported — falls back to the sync path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_methods_raise_batch_unsupported_error() -> None:
    adapter = _make_adapter()

    with pytest.raises(BatchUnsupportedError):
        await adapter.submit_batch([])
    with pytest.raises(BatchUnsupportedError):
        await adapter.poll_batch("batch-id")
    with pytest.raises(BatchUnsupportedError):
        await adapter.fetch_batch_results("batch-id")
