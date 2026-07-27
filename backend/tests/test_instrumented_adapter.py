"""Unit tests for services.llm.instrumented_adapter.InstrumentedAdapter.

Verifies:
* Pass-through behaviour: stream() yields identical tokens, complete()
  returns the identical value and forwards args unchanged.
* Single recording per call: a stream of N tokens results in exactly ONE
  create_generation call with the full accumulated output, never per-token.
* Provider, model, stage_type, action, span_id, trace_id are all forwarded
  to LangfuseClient.create_generation.
* last_generation_id is set after each call so callers (eval-score linking
  in T-127) can attach scores to the originating generation.
* Exceptions inside create_generation do not propagate to the caller —
  the streaming/completion contract is preserved even when Langfuse fails.
* Wrapped-adapter exceptions still propagate (the wrapper does not eat
  upstream errors), but a generation is still recorded with the partial
  output captured up to the point of failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import generate_latest

from services import langfuse_service
from services.llm.base import BaseLLMAdapter
from services.llm.completion import LLMCompletionInfo
from services.llm.instrumented_adapter import InstrumentedAdapter
from services.llm.usage import estimate_cost_usd, estimated_usage_from_text


class _FakeAdapter(BaseLLMAdapter):
    def __init__(
        self,
        stream_tokens: list[str] | None = None,
        complete_response: str = "complete-result",
        raise_during_stream: Exception | None = None,
        raise_during_complete: Exception | None = None,
    ) -> None:
        self._tokens = stream_tokens or ["alpha", "beta", "gamma"]
        self._complete_response = complete_response
        self._raise_during_stream = raise_during_stream
        self._raise_during_complete = raise_during_complete
        self.complete_calls: list[tuple[str, str, int]] = []
        self.stream_calls: list[tuple[str, str, int]] = []

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_policy=None,
    ):
        self.stream_calls.append((system, user, max_tokens))
        self.last_completion = LLMCompletionInfo.started(
            provider="fake",
            model="fake-model",
            max_tokens=max_tokens,
        )
        for token in self._tokens:
            if self._raise_during_stream is not None and token == self._tokens[-1]:
                raise self._raise_during_stream
            yield token

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_policy=None,
    ) -> str:
        self.complete_calls.append((system, user, max_tokens))
        self.last_completion = LLMCompletionInfo.started(
            provider="fake",
            model="fake-model",
            max_tokens=max_tokens,
        )
        if self._raise_during_complete is not None:
            raise self._raise_during_complete
        return self._complete_response


def _mock_langfuse() -> MagicMock:
    client = MagicMock()
    client.create_generation = AsyncMock(return_value="gen-id-from-test")
    return client


def test_completion_info_maps_limit_finish_reasons() -> None:
    info = LLMCompletionInfo.started(
        provider="openai",
        model="gpt-4o",
        max_tokens=100,
    )
    info.apply_finish_reason("length")

    assert info.finish_reason == "length"
    assert info.stopped_by_limit is True


@pytest.mark.asyncio
async def test_stream_passes_tokens_through_unchanged() -> None:
    adapter = _FakeAdapter(stream_tokens=["one", "two", "three"])
    wrapped = InstrumentedAdapter(
        adapter,
        span_id="span-1",
        provider="anthropic",
        model="claude-haiku-4-5",
        stage_type="spec",
        action="generate",
    )

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=_mock_langfuse()
    ):
        collected: list[str] = []
        async for token in wrapped.stream("sys", "user", 100):
            collected.append(token)

    assert collected == ["one", "two", "three"]
    assert adapter.stream_calls == [("sys", "user", 100)]
    assert wrapped.last_completion is adapter.last_completion


@pytest.mark.asyncio
async def test_complete_passes_args_and_returns_unchanged() -> None:
    adapter = _FakeAdapter(complete_response="returned-string")
    wrapped = InstrumentedAdapter(
        adapter,
        span_id="span-1",
        provider="openai",
        model="gpt-4o",
        stage_type="plan",
        action="refine",
    )

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=_mock_langfuse()
    ):
        result = await wrapped.complete("sys-c", "user-c", 50)

    assert result == "returned-string"
    assert adapter.complete_calls == [("sys-c", "user-c", 50)]


@pytest.mark.asyncio
async def test_stream_records_exactly_one_generation_with_full_output() -> None:
    adapter = _FakeAdapter(stream_tokens=["foo", "bar", "baz"])
    wrapped = InstrumentedAdapter(
        adapter,
        span_id="span-X",
        trace_id="trace-Y",
        provider="google",
        model="gemini-3.6-flash",
        stage_type="harness",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        async for _ in wrapped.stream("sys", "user", 100):
            pass

    mock_client.create_generation.assert_awaited_once()
    kwargs = mock_client.create_generation.await_args.kwargs
    assert kwargs["output"] == "foobarbaz"
    assert kwargs["span_id"] == "span-X"
    assert kwargs["trace_id"] == "trace-Y"
    assert kwargs["provider"] == "google"
    assert kwargs["model"] == "gemini-3.6-flash"
    assert kwargs["metadata"]["stage_type"] == "harness"
    assert kwargs["metadata"]["action"] == "generate"
    assert "latency_ms" in kwargs["metadata"]


@pytest.mark.asyncio
async def test_complete_records_one_generation_with_returned_value() -> None:
    adapter = _FakeAdapter(complete_response="abc-123")
    wrapped = InstrumentedAdapter(
        adapter,
        span_id="s",
        provider="anthropic",
        model="claude",
        stage_type="tasks",
        action="refine",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        await wrapped.complete("sys", "user", 100)

    mock_client.create_generation.assert_awaited_once()
    kwargs = mock_client.create_generation.await_args.kwargs
    assert kwargs["output"] == "abc-123"
    assert kwargs["input"] == {"system": "sys", "user": "user"}
    assert kwargs["model"] == "claude"


@pytest.mark.asyncio
async def test_last_generation_id_is_set_after_recording() -> None:
    adapter = _FakeAdapter(complete_response="r")
    wrapped = InstrumentedAdapter(
        adapter,
        provider="anthropic",
        model="claude",
        stage_type="spec",
        action="generate",
    )
    mock_client = MagicMock()
    mock_client.create_generation = AsyncMock(return_value="gen-77")

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        assert wrapped.last_generation_id is None
        await wrapped.complete("sys", "user", 10)

    assert wrapped.last_generation_id == "gen-77"


@pytest.mark.asyncio
async def test_redaction_applied_to_input_before_recording() -> None:
    adapter = _FakeAdapter(complete_response="ok")
    wrapped = InstrumentedAdapter(
        adapter,
        provider="anthropic",
        model="claude",
        stage_type="spec",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        await wrapped.complete(
            "system instructions",
            "my key is sk-ant-deadbeefdeadbeefdeadbeefdead and please use it",
            10,
        )

    kwargs = mock_client.create_generation.await_args.kwargs
    # The redact_sensitive_data ruleset must have stripped the secret-shaped
    # token before it reached the LangfuseClient.
    assert "sk-ant-deadbeefdeadbeefdeadbeefdead" not in str(kwargs["input"])


@pytest.mark.asyncio
async def test_create_generation_failure_does_not_break_stream() -> None:
    adapter = _FakeAdapter(stream_tokens=["x", "y", "z"])
    wrapped = InstrumentedAdapter(
        adapter,
        provider="anthropic",
        model="claude",
        stage_type="spec",
        action="generate",
    )
    mock_client = MagicMock()
    mock_client.create_generation = AsyncMock(side_effect=RuntimeError("langfuse down"))

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        collected: list[str] = []
        async for token in wrapped.stream("sys", "user", 100):
            collected.append(token)

    # Stream completed normally — Langfuse failure was swallowed.
    assert collected == ["x", "y", "z"]


@pytest.mark.asyncio
async def test_create_generation_failure_does_not_break_complete() -> None:
    adapter = _FakeAdapter(complete_response="value")
    wrapped = InstrumentedAdapter(
        adapter,
        provider="anthropic",
        model="claude",
        stage_type="spec",
        action="generate",
    )
    mock_client = MagicMock()
    mock_client.create_generation = AsyncMock(side_effect=RuntimeError("langfuse down"))

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        result = await wrapped.complete("sys", "user", 10)

    assert result == "value"


@pytest.mark.asyncio
async def test_wrapped_stream_exception_still_records_partial_output() -> None:
    """If the wrapped adapter raises mid-stream, the wrapper still records a
    generation with the tokens captured so far. The original exception
    propagates to the caller (we do not eat upstream errors)."""
    err = RuntimeError("provider blew up")
    adapter = _FakeAdapter(
        stream_tokens=["partial-1", "partial-2", "would-have-been-3"],
        raise_during_stream=err,
    )
    wrapped = InstrumentedAdapter(
        adapter,
        provider="anthropic",
        model="claude",
        stage_type="spec",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        collected: list[str] = []
        with pytest.raises(RuntimeError, match="provider blew up"):
            async for token in wrapped.stream("sys", "user", 100):
                collected.append(token)

    # Only partial tokens reached the consumer (the third token was the one
    # the fake raises on, so it never yielded).
    assert collected == ["partial-1", "partial-2"]
    # But the generation was still recorded with whatever accumulated.
    mock_client.create_generation.assert_awaited_once()
    kwargs = mock_client.create_generation.await_args.kwargs
    assert kwargs["output"] == "partial-1partial-2"


@pytest.mark.asyncio
async def test_wrapped_complete_exception_still_records_empty_output() -> None:
    err = RuntimeError("provider down")
    adapter = _FakeAdapter(raise_during_complete=err)
    wrapped = InstrumentedAdapter(
        adapter,
        provider="openai",
        model="gpt-4o",
        stage_type="spec",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        with pytest.raises(RuntimeError, match="provider down"):
            await wrapped.complete("sys", "user", 10)

    # Generation still recorded — output is "" since the wrapped call raised.
    mock_client.create_generation.assert_awaited_once()
    kwargs = mock_client.create_generation.await_args.kwargs
    assert kwargs["output"] == ""


# ---------------------------------------------------------------------------
# A throttled call is never billed by the provider, so it must not book cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_throttled_stream_books_no_cost() -> None:
    """Regression: a 429 rejected before any token arrived was still recorded as
    a tokenizer-estimated generation, inflating llm_cost_events with spend that
    the provider never charged (a throttled 4-chunk tasks stage logged ~$0.48)."""
    from services.llm.base import ProviderRateLimitError

    err = ProviderRateLimitError("google", RuntimeError("429"), retry_after=40.0)
    adapter = _FakeAdapter(stream_tokens=["never"], raise_during_stream=err)
    wrapped = InstrumentedAdapter(
        adapter,
        provider="google",
        model="gemini-3.6-flash",
        stage_type="tasks",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        with pytest.raises(ProviderRateLimitError):
            async for _ in wrapped.stream("sys", "user", 100):
                pass

    mock_client.create_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_throttled_complete_books_no_cost() -> None:
    from services.llm.base import ProviderRateLimitError

    err = ProviderRateLimitError("google", RuntimeError("429"), retry_after=40.0)
    adapter = _FakeAdapter(raise_during_complete=err)
    wrapped = InstrumentedAdapter(
        adapter,
        provider="google",
        model="gemini-3.5-flash-lite",
        stage_type="spec",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        with pytest.raises(ProviderRateLimitError):
            await wrapped.complete("sys", "user", 10)

    mock_client.create_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_throttle_after_partial_stream_still_books_the_consumed_tokens() -> None:
    """Tokens that did arrive were generated and billed, so a mid-stream throttle
    must still record them — only a rejection with nothing received is free."""
    from services.llm.base import ProviderRateLimitError

    err = ProviderRateLimitError("google", RuntimeError("429"))
    adapter = _FakeAdapter(
        stream_tokens=["real-1", "real-2", "boom"], raise_during_stream=err
    )
    wrapped = InstrumentedAdapter(
        adapter,
        provider="google",
        model="gemini-3.6-flash",
        stage_type="tasks",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        with pytest.raises(ProviderRateLimitError):
            async for _ in wrapped.stream("sys", "user", 100):
                pass

    mock_client.create_generation.assert_awaited_once()
    assert mock_client.create_generation.await_args.kwargs["output"] == "real-1real-2"


@pytest.mark.asyncio
async def test_span_id_and_trace_id_optional_default_none() -> None:
    adapter = _FakeAdapter(complete_response="x")
    wrapped = InstrumentedAdapter(
        adapter,
        provider="anthropic",
        model="claude",
        stage_type="spec",
        action="generate",
    )
    mock_client = _mock_langfuse()

    with patch.object(
        langfuse_service, "get_langfuse_client", return_value=mock_client
    ):
        await wrapped.complete("sys", "user", 10)

    kwargs = mock_client.create_generation.await_args.kwargs
    assert kwargs["span_id"] is None
    assert kwargs["trace_id"] is None


@pytest.mark.asyncio
async def test_cost_metrics_and_logs_exclude_prompt_and_output_content() -> None:
    system_prompt = "SYSTEM-CONTENT-NEVER-LOG"
    user_prompt = "USER-CONTENT-NEVER-LOG"
    output = "MODEL-OUTPUT-NEVER-LOG"
    adapter = _FakeAdapter(complete_response=output)
    wrapped = InstrumentedAdapter(
        adapter,
        provider="openai",
        model="gpt-4o-mini",
        stage_type="spec",
        action="refine",
        model_tier="mini",
        operation="refine.focused",
        prompt_version="test-cost-metrics-v1",
        cache_hit=True,
        cross_provider_fallback=True,
    )
    mock_client = _mock_langfuse()

    with (
        patch.object(langfuse_service, "get_langfuse_client", return_value=mock_client),
        patch("services.llm.instrumented_adapter.logger.info") as mock_log,
    ):
        await wrapped.complete(system_prompt, user_prompt, 50)

    usage = estimated_usage_from_text(
        provider="openai",
        model="gpt-4o-mini",
        system=system_prompt,
        user=user_prompt,
        output=output,
    )
    expected_cost = estimate_cost_usd("openai", "gpt-4o-mini", usage)
    assert mock_log.call_count == 3
    logs_by_event = {call.args[0]: call for call in mock_log.call_args_list}
    assert set(logs_by_event) == {
        "llm.request_started",
        "llm.request_finished",
        "llm.cost_recorded",
    }
    started_fields = logs_by_event["llm.request_started"].kwargs
    finished_fields = logs_by_event["llm.request_finished"].kwargs
    assert started_fields["provider_request_id"]
    assert (
        finished_fields["provider_request_id"] == started_fields["provider_request_id"]
    )
    assert finished_fields["outcome"] == "succeeded"
    assert finished_fields["elapsed_ms"] >= 0

    log_fields = logs_by_event["llm.cost_recorded"].kwargs
    assert log_fields["provider"] == "openai"
    assert log_fields["model_tier"] == "mini"
    assert log_fields["operation"] == "refine.focused"
    assert log_fields["stage_type"] == "spec"
    assert log_fields["cache_hit"] is True
    assert log_fields["cross_provider_fallback"] is True
    assert log_fields["input_tokens"] == usage.input_tokens
    assert log_fields["output_tokens"] == usage.output_tokens
    assert log_fields["cached_input_tokens"] == usage.cached_input_tokens
    assert log_fields["estimated_cost_usd"] == float(expected_cost)

    serialized_log = str(mock_log.call_args_list)
    assert system_prompt not in serialized_log
    assert user_prompt not in serialized_log
    assert output not in serialized_log

    metrics = generate_latest().decode("utf-8")
    assert "llm_request_total" in metrics
    assert "llm_estimated_cost_usd_total" in metrics
    assert "llm_input_tokens_total" in metrics
    assert "llm_output_tokens_total" in metrics
    assert "llm_cached_input_tokens_total" in metrics
    assert "llm_latency_seconds_bucket" in metrics
    assert "llm_cross_provider_fallback_total" in metrics
    assert 'provider="openai"' in metrics
    assert 'model_tier="mini"' in metrics
    assert 'operation="refine.focused"' in metrics
    assert 'stage_type="spec"' in metrics
    assert 'cache_hit="true"' in metrics
    assert system_prompt not in metrics
    assert user_prompt not in metrics
    assert output not in metrics
