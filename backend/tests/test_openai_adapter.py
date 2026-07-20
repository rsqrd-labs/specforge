"""Unit tests for OpenAI streaming adapter guards — T-199 (HF-2).

Tests verify that the three defensive guards added to OpenAIAdapter.stream()
correctly handle the edge-case chunks that the OpenAI API sends:

  OA-1  Usage-only chunks (choices=[]) yield an empty liveness sentinel.
  OA-2  Chunks with delta=None yield an empty liveness sentinel.
  OA-3  Chunks with delta.content=None yield an empty liveness sentinel.
  OA-4  Normal content chunks are yielded correctly.
  OA-5  A mixed stream (usage chunk + real content) concatenates to only the
        real content (sentinels are empty strings, invisible in the artifact).
  OA-6  An entirely empty stream yields nothing and does not raise.
  OA-7  OpenAIError is re-raised as ProviderError.

The empty-string sentinels exist for the stream watchdog (issue #19): every
provider event — visible text or not — resets the watchdog's idle timer, and
the watchdog forwards only non-empty tokens to consumers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

from services.llm.base import ProviderError

# ---------------------------------------------------------------------------
# Helpers — build fake chunk objects that match the openai SDK shape
# ---------------------------------------------------------------------------


def _chunk(content: str | None = None, choices: list | None = None) -> Any:
    """Build a minimal fake streaming chunk.

    If *choices* is supplied it is used directly; otherwise a single choice
    with ``delta.content = content`` is created.
    """
    if choices is not None:
        return SimpleNamespace(choices=choices)
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


def _chunk_empty_choices() -> Any:
    """Usage-only chunk: choices=[] (no delta at all)."""
    return SimpleNamespace(choices=[])


def _chunk_delta_none() -> Any:
    """Final-chunk variant: choices=[{delta: None}]."""
    choice = SimpleNamespace(delta=None)
    return SimpleNamespace(choices=[choice])


def _response_event_delta(content: str) -> Any:
    return SimpleNamespace(type="response.output_text.delta", delta=content)


def _response_event_completed() -> Any:
    usage = SimpleNamespace(input_tokens=4, output_tokens=2)
    response = SimpleNamespace(status="completed", usage=usage)
    return SimpleNamespace(type="response.completed", response=response)


async def _fake_stream(chunks: list[Any]) -> AsyncIterator[Any]:
    """Yield each chunk in turn as an async iterator."""
    for chunk in chunks:
        yield chunk


# ---------------------------------------------------------------------------
# Fixture: patch the openai client on a fresh adapter instance
# ---------------------------------------------------------------------------


def _make_adapter(chunks: list[Any]) -> Any:
    """Return an OpenAIAdapter whose underlying client streams *chunks*."""
    from services.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "gpt-4o"
    adapter._request_policy = {"adapter_api": "chat_completions"}

    mock_create = AsyncMock()
    mock_create.return_value = _fake_stream(chunks)

    mock_completions = MagicMock()
    mock_completions.create = mock_create

    mock_chat = MagicMock()
    mock_chat.completions = mock_completions

    mock_client = MagicMock()
    mock_client.chat = mock_chat
    adapter._client = mock_client

    return adapter


def _make_responses_adapter(events: list[Any]) -> Any:
    from services.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "gpt-5.5"
    adapter._request_policy = {
        "adapter_api": "responses",
        "reasoning_effort": "high",
    }

    mock_create = AsyncMock()
    mock_create.return_value = _fake_stream(events)

    mock_responses = MagicMock()
    mock_responses.create = mock_create

    mock_client = MagicMock()
    mock_client.responses = mock_responses
    adapter._client = mock_client

    return adapter


# ---------------------------------------------------------------------------
# OA-1: usage-only chunks (choices=[]) are skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_choices_chunk_yields_liveness_sentinel() -> None:
    """OA-1 — choices=[] chunks must not raise IndexError and must yield an
    empty liveness sentinel so the stream watchdog sees a healthy stream."""
    adapter = _make_adapter([_chunk_empty_choices(), _chunk("hello")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["", "hello"], (
        "Usage-only chunk (choices=[]) must yield a liveness sentinel. "
        f"Got tokens: {tokens!r}"
    )


# ---------------------------------------------------------------------------
# OA-2: delta=None chunks are skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_none_chunk_yields_liveness_sentinel() -> None:
    """OA-2 — chunks where choices[0].delta is None must yield an empty
    liveness sentinel without raising."""
    adapter = _make_adapter([_chunk_delta_none(), _chunk("world")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["", "world"], (
        "Chunk with delta=None must yield a liveness sentinel without raising. "
        f"Got tokens: {tokens!r}"
    )


# ---------------------------------------------------------------------------
# OA-3: delta.content=None chunks are skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_content_none_chunk_yields_liveness_sentinel() -> None:
    """OA-3 — chunks where delta.content is None must yield an empty
    liveness sentinel without raising."""
    adapter = _make_adapter([_chunk(content=None), _chunk("end")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["", "end"], (
        "Chunk with delta.content=None must yield a liveness sentinel "
        f"without raising. Got tokens: {tokens!r}"
    )


# ---------------------------------------------------------------------------
# OA-4: normal content chunks are yielded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_chunks_are_yielded() -> None:
    """OA-4 — chunks with non-None delta.content must be yielded as-is."""
    adapter = _make_adapter([_chunk("Hello"), _chunk(", "), _chunk("world!")])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == ["Hello", ", ", "world!"]


# ---------------------------------------------------------------------------
# OA-5: mixed stream — usage chunk + real content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_stream_yields_only_content() -> None:
    """OA-5 — a real-world stream mix must yield only the content tokens."""
    chunks = [
        _chunk("The "),
        _chunk_empty_choices(),  # usage-only chunk mid-stream
        _chunk("answer"),
        _chunk_delta_none(),  # final stop chunk
        _chunk(content=None),  # tool-use stub
    ]
    adapter = _make_adapter(chunks)

    result = ""
    async for token in adapter.stream("sys", "user", 200):
        result += token

    assert (
        result == "The answer"
    ), f"Mixed stream must concatenate only real content. Got: {result!r}"


# ---------------------------------------------------------------------------
# OA-6: entirely empty stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entirely_empty_stream_yields_nothing() -> None:
    """OA-6 — a stream with zero chunks must yield nothing and not raise."""
    adapter = _make_adapter([])

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 100):
        tokens.append(token)

    assert tokens == []


# ---------------------------------------------------------------------------
# OA-7: OpenAIError is re-raised as ProviderError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_error_is_wrapped_as_provider_error() -> None:
    """OA-7 — openai.OpenAIError raised during streaming must become ProviderError."""
    from services.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "gpt-4o"
    adapter._request_policy = {"adapter_api": "chat_completions"}

    async def _raising_stream(*_a: Any, **_kw: Any) -> Any:
        raise openai.APIError("upstream error", request=MagicMock(), body=None)

    mock_completions = MagicMock()
    mock_completions.create = AsyncMock(side_effect=_raising_stream)
    mock_chat = MagicMock()
    mock_chat.completions = mock_completions
    mock_client = MagicMock()
    mock_client.chat = mock_chat
    adapter._client = mock_client

    with pytest.raises(ProviderError):
        async for _ in adapter.stream("sys", "user", 100):
            pass


@pytest.mark.asyncio
async def test_incomplete_chunked_read_is_wrapped_as_provider_error() -> None:
    """A response body cut off mid-stream must enter pipeline cleanup."""

    async def _truncated_stream() -> AsyncIterator[Any]:
        yield _chunk("partial")
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body"
        )

    adapter = _make_adapter([])
    adapter._client.chat.completions.create = AsyncMock(
        return_value=_truncated_stream()
    )

    tokens: list[str] = []
    with pytest.raises(ProviderError) as raised:
        async for token in adapter.stream("sys", "user", 100):
            tokens.append(token)

    assert tokens == ["partial"]
    assert raised.value.provider == "openai"


@pytest.mark.asyncio
async def test_gpt5_stream_uses_responses_api_with_reasoning_effort() -> None:
    adapter = _make_responses_adapter(
        [_response_event_delta("new "), _response_event_delta("model")]
    )

    tokens: list[str] = []
    async for token in adapter.stream("sys", "user", 8192):
        tokens.append(token)

    assert tokens == ["new ", "model"]
    adapter._client.responses.create.assert_awaited_once()
    kwargs = adapter._client.responses.create.await_args.kwargs
    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["max_output_tokens"] == 8192
    assert kwargs["stream"] is True
    # summary="auto" keeps reasoning-phase stream events flowing (liveness
    # for the watchdog and the HTTP read timeout) — issue #19.
    assert kwargs["reasoning"] == {"effort": "high", "summary": "auto"}
    assert kwargs["instructions"] == "sys"
    assert kwargs["input"] == "user"


@pytest.mark.asyncio
async def test_gpt5_complete_extracts_responses_output_text() -> None:
    from services.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "gpt-5.5"
    adapter._request_policy = {
        "adapter_api": "responses",
        "reasoning_effort": "high",
    }
    response = SimpleNamespace(
        output_text="Done",
        status="completed",
        usage=SimpleNamespace(input_tokens=10, output_tokens=3),
    )
    mock_responses = MagicMock()
    mock_responses.create = AsyncMock(return_value=response)
    mock_client = MagicMock()
    mock_client.responses = mock_responses
    adapter._client = mock_client

    result = await adapter.complete("sys", "user", 4096)

    assert result == "Done"
    mock_responses.create.assert_awaited_once()
    kwargs = mock_responses.create.await_args.kwargs
    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["max_output_tokens"] == 4096
    assert kwargs["stream"] is False
    assert adapter.last_completion is not None
    assert adapter.last_completion.usage == {
        "input_tokens": 10,
        "output_tokens": 3,
    }
