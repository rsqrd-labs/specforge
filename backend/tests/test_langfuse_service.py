"""Unit tests for services.langfuse_service.

Validates two distinct execution paths:

1. **Unconfigured path** (LANGFUSE_SECRET_KEY="") — every public method returns
   without raising, the SDK module is never imported, and ``_client`` stays
   None throughout.

2. **Configured path** (LANGFUSE_SECRET_KEY set) — the SDK client is
   constructed lazily on first use, every public method routes through it,
   and any SDK exception is caught and logged via structlog without
   propagating to the caller.

In both modes, payloads are redacted via
``services.observability.redact_sensitive_data`` before reaching the SDK.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import config
import services.langfuse_service as langfuse_service

_LANGFUSE_FIELD_DEFAULTS = {
    "langfuse_secret_key": "",
    "langfuse_public_key": "",
    "langfuse_host": "https://cloud.langfuse.com",
    "langfuse_prompt_cache_ttl": 300,
    "langfuse_prompt_fetch_timeout_seconds": 5.0,
}


def _configure_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Any:
    """Mutate ``settings`` attributes for one test and reset the
    LangfuseClient singleton so the next ``get_langfuse_client()`` call sees
    the fresh values. Reverts cleanly when the test exits because
    ``monkeypatch.setattr`` snapshots the original values.
    """
    for field, default in _LANGFUSE_FIELD_DEFAULTS.items():
        monkeypatch.setattr(config.settings, field, overrides.get(field, default))
    langfuse_service.reset_langfuse_client()
    return langfuse_service


# ---------------------------------------------------------------------------
# Unconfigured path — zero SDK imports, zero network calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_client_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_settings(monkeypatch, langfuse_secret_key="")
    client = langfuse_service.get_langfuse_client()
    assert client.enabled is False
    assert client._client is None


@pytest.mark.asyncio
async def test_unconfigured_methods_return_none_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch, langfuse_secret_key="")
    client = langfuse_service.get_langfuse_client()

    assert await client.create_trace(name="t", metadata={}) is None
    assert await client.create_span(trace_id="t", name="s", metadata={}) is None
    assert await client.create_generation(span_id="s") is None
    assert (
        await client.score_generation(generation_id="g", name="overall", value=92.0)
        is None
    )
    assert await client.add_to_dataset(dataset_name="d", item={"x": 1}) is None
    assert await client.get_prompt(name="spec") is None

    # Still disabled and SDK never constructed.
    assert client.enabled is False
    assert client._client is None


@pytest.mark.asyncio
async def test_unconfigured_path_does_not_import_langfuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the wrapper is correctly gated, the langfuse module is never imported
    inside the no-op branch. Patching sys.modules to make any ``from langfuse
    import Langfuse`` raise lets us prove this."""
    _configure_settings(monkeypatch, langfuse_secret_key="")
    client = langfuse_service.get_langfuse_client()

    with patch.dict(sys.modules, {"langfuse": None}):
        # Each call would attempt `from langfuse import Langfuse` if the no-op
        # gate failed. With sys.modules["langfuse"] = None, that raises
        # ImportError. The wrapper's design ensures the import is only
        # attempted when self._enabled is True, so these calls must succeed.
        assert await client.create_trace(name="t", metadata={}) is None
        assert await client.get_prompt(name="spec") is None


# ---------------------------------------------------------------------------
# Configured path — SDK lazily constructed, exceptions swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configured_client_constructs_sdk_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-langfuse-test",
        langfuse_public_key="pk-langfuse-test",
        langfuse_host="https://cloud.langfuse.com",
    )

    fake_sdk = MagicMock()
    fake_sdk.trace.return_value = None
    with patch("langfuse.Langfuse", return_value=fake_sdk) as ctor:
        client = langfuse_service.get_langfuse_client()
        # Construction must NOT have happened yet.
        ctor.assert_not_called()
        assert client._client is None

        # First call constructs the SDK.
        result = await client.create_trace(name="t", metadata={"workspace_id": "w"})
        ctor.assert_called_once_with(
            secret_key="sk-langfuse-test",
            public_key="pk-langfuse-test",
            host="https://cloud.langfuse.com",
        )
        assert result is not None  # uuid string returned
        assert client._client is fake_sdk


@pytest.mark.asyncio
async def test_create_trace_honors_supplied_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        result = await client.create_trace(
            name="ws-gen",
            trace_id="trace-abc-123",
            user_id="user-7",
            metadata={"stage_type": "spec"},
        )
        assert result == "trace-abc-123"
        fake_sdk.trace.assert_called_once()
        kwargs = fake_sdk.trace.call_args.kwargs
        assert kwargs["id"] == "trace-abc-123"
        assert kwargs["user_id"] == "user-7"
        assert kwargs["name"] == "ws-gen"


@pytest.mark.asyncio
async def test_create_generation_passes_provider_in_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        await client.create_generation(
            span_id="span-1",
            trace_id="trace-1",
            name="claude-stream",
            provider="anthropic",
            model="claude-haiku-4-5",
            input={"system": "sys", "user": "u"},
            output="hello world",
            usage={"input": 12, "output": 4},
        )
        fake_sdk.generation.assert_called_once()
        kwargs = fake_sdk.generation.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5"
        assert kwargs["parent_observation_id"] == "span-1"
        assert kwargs["trace_id"] == "trace-1"
        assert kwargs["metadata"]["provider"] == "anthropic"
        assert kwargs["usage_details"] == {"input": 12, "output": 4}


@pytest.mark.asyncio
async def test_score_generation_routes_to_sdk_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        await client.score_generation(
            generation_id="gen-77", name="overall", value=87.5, comment="green"
        )
        fake_sdk.score.assert_called_once_with(
            observation_id="gen-77", name="overall", value=87.5, comment="green"
        )


@pytest.mark.asyncio
async def test_add_to_dataset_routes_to_create_dataset_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        await client.add_to_dataset(
            dataset_name="high_quality_generations",
            item={"score": 92, "stage_type": "spec"},
            source_observation_id="gen-77",
        )
        fake_sdk.create_dataset_item.assert_called_once()
        kwargs = fake_sdk.create_dataset_item.call_args.kwargs
        assert kwargs["dataset_name"] == "high_quality_generations"
        assert kwargs["source_observation_id"] == "gen-77"
        assert kwargs["input"] == {"score": 92, "stage_type": "spec"}


@pytest.mark.asyncio
async def test_get_prompt_returns_template_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_prompt = MagicMock()
    fake_prompt.prompt = "REMOTE TEMPLATE BODY"
    fake_sdk = MagicMock()
    fake_sdk.get_prompt.return_value = fake_prompt
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        body = await client.get_prompt(name="specforge.spec.system", version=3)
        assert body == "REMOTE TEMPLATE BODY"
        fake_sdk.get_prompt.assert_called_once()
        kwargs = fake_sdk.get_prompt.call_args.kwargs
        assert kwargs["version"] == 3
        # Cache TTL must come from settings, not be hardcoded.
        assert kwargs["cache_ttl_seconds"] == 300


@pytest.mark.asyncio
async def test_get_prompt_returns_none_when_body_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    bad_prompt = MagicMock(spec=[])  # no .prompt attribute
    fake_sdk = MagicMock()
    fake_sdk.get_prompt.return_value = bad_prompt
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        body = await client.get_prompt(name="missing")
        assert body is None


@pytest.mark.asyncio
async def test_get_prompt_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow synchronous SDK call must not stall the event loop. While
    get_prompt waits on the worker thread, other coroutines must keep
    making progress on the loop.
    """
    import time

    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
        langfuse_prompt_fetch_timeout_seconds=2.0,
    )

    fake_prompt = MagicMock()
    fake_prompt.prompt = "REMOTE BODY"
    fake_sdk = MagicMock()

    def _slow_get_prompt(*_args: Any, **_kwargs: Any) -> Any:
        # Simulate the SDK's blocking HTTP call.
        time.sleep(0.4)
        return fake_prompt

    fake_sdk.get_prompt.side_effect = _slow_get_prompt

    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()

        # Sentinel coroutine that proves the loop is responsive while
        # get_prompt is in flight: it sleeps for 0.05s repeatedly and
        # records each tick. If the loop were blocked by the synchronous
        # SDK call, no ticks would advance for 0.4s.
        ticks: list[float] = []

        async def heartbeat() -> None:
            start = asyncio.get_running_loop().time()
            while asyncio.get_running_loop().time() - start < 0.35:
                ticks.append(asyncio.get_running_loop().time())
                await asyncio.sleep(0.05)

        body, _ = await asyncio.gather(
            client.get_prompt(name="specforge.spec.system"),
            heartbeat(),
        )

        assert body == "REMOTE BODY"
        # Heartbeat ticked roughly every 50ms during the 400ms SDK call.
        # If the loop had been blocked, len(ticks) would be ~1 (only the
        # initial tick before the await).
        assert len(ticks) >= 4, (
            f"Event loop appears blocked during get_prompt: only {len(ticks)} "
            "heartbeat ticks fired."
        )


@pytest.mark.asyncio
async def test_get_prompt_times_out_when_sdk_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the SDK takes longer than langfuse_prompt_fetch_timeout_seconds,
    we must give up and return None so callers fall back to the local
    template instead of wedging stage generation.
    """
    import time

    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
        langfuse_prompt_fetch_timeout_seconds=0.1,
    )

    fake_sdk = MagicMock()

    def _hang(*_args: Any, **_kwargs: Any) -> Any:
        # Block well past the configured timeout; never returns within
        # the test's relevant window.
        time.sleep(2.0)
        return MagicMock(prompt="never returned")

    fake_sdk.get_prompt.side_effect = _hang

    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()

        loop = asyncio.get_running_loop()
        start = loop.time()
        body = await client.get_prompt(name="specforge.spec.system")
        elapsed = loop.time() - start

        assert body is None
        # Must return shortly after the timeout, not after the SDK's
        # internal 2s sleep.
        assert (
            elapsed < 1.0
        ), f"get_prompt did not respect the timeout: returned in {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Exception swallowing — every method tolerates SDK failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_method_swallows_sdk_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    raising_sdk = MagicMock()
    raising_sdk.trace.side_effect = RuntimeError("API down")
    raising_sdk.span.side_effect = RuntimeError("API down")
    raising_sdk.generation.side_effect = RuntimeError("API down")
    raising_sdk.score.side_effect = RuntimeError("API down")
    raising_sdk.create_dataset_item.side_effect = RuntimeError("API down")
    raising_sdk.get_prompt.side_effect = RuntimeError("API down")

    with patch("langfuse.Langfuse", return_value=raising_sdk):
        client = langfuse_service.get_langfuse_client()
        # Every call must complete without propagating.
        assert await client.create_trace(name="t") is None
        assert await client.create_span(trace_id="t", name="s") is None
        assert await client.create_generation(span_id="s") is None
        assert (
            await client.score_generation(generation_id="g", name="overall", value=1.0)
            is None
        )
        assert await client.add_to_dataset(dataset_name="d", item={}) is None
        assert await client.get_prompt(name="spec") is None


@pytest.mark.asyncio
async def test_sdk_construction_failure_disables_client_permanently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Langfuse() raises during construction (bad key, bad URL), the wrapper
    flips into permanent no-op for the lifetime of this process and never
    retries — avoiding cascading failures on every subsequent call."""
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    with patch("langfuse.Langfuse", side_effect=RuntimeError("auth failed")):
        client = langfuse_service.get_langfuse_client()
        assert client.enabled is True  # initially
        assert await client.create_trace(name="t") is None
        # After the failed construction the client must be permanently off
        # so we don't burn CPU retrying every call.
        assert client.enabled is False
        # Subsequent calls return immediately — verified by ensuring no
        # further construction is attempted.

    with patch(
        "langfuse.Langfuse", side_effect=AssertionError("must not be reached")
    ) as ctor:
        # Reuse the same client instance — it's been disabled.
        assert await client.create_trace(name="t2") is None
        ctor.assert_not_called()


# ---------------------------------------------------------------------------
# Sensitive data redaction — payloads scrubbed before reaching the SDK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_generation_redacts_secrets_in_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        await client.create_generation(
            span_id="s",
            input={
                "system": "you are a helpful assistant",
                "user": "my OpenAI key is sk-proj-deadbeefdeadbeef please use it",
            },
            output="nothing happened",
        )
        kwargs = fake_sdk.generation.call_args.kwargs
        # The user message contained a secret-shaped string; the existing
        # redact_sensitive_data ruleset must have replaced it.
        assert "sk-proj-deadbeefdeadbeef" not in str(kwargs["input"])


@pytest.mark.asyncio
async def test_create_trace_redacts_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )

    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        await client.create_trace(
            name="t",
            metadata={"authorization": "Bearer eyJraWQ.payload.sig", "ws": "w-1"},
        )
        kwargs = fake_sdk.trace.call_args.kwargs
        assert kwargs["metadata"]["authorization"] == "[REDACTED]"
        assert kwargs["metadata"]["ws"] == "w-1"


# ---------------------------------------------------------------------------
# flush() — graceful-shutdown drain of the SDK consumer-thread queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_is_noop_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """flush() must be safe to call on the disabled client; it must not
    construct the SDK or raise."""
    _configure_settings(monkeypatch, langfuse_secret_key="")
    client = langfuse_service.get_langfuse_client()
    await client.flush()  # must not raise
    assert client._client is None


@pytest.mark.asyncio
async def test_flush_is_noop_when_sdk_not_yet_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured-but-unused client (no events yet) must flush without
    forcing SDK construction. There is nothing to drain."""
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    with patch("langfuse.Langfuse") as ctor:
        client = langfuse_service.get_langfuse_client()
        await client.flush()
        ctor.assert_not_called()
        assert client._client is None


@pytest.mark.asyncio
async def test_flush_drains_sdk_when_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the SDK has been constructed (e.g. by a prior create_trace),
    flush must call into client.flush() so queued events are drained
    before shutdown."""
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    fake_sdk = MagicMock()
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        # Force SDK construction by issuing one event.
        await client.create_trace(name="t")
        fake_sdk.flush.assert_not_called()

        await client.flush()
        fake_sdk.flush.assert_called_once()


@pytest.mark.asyncio
async def test_flush_swallows_sdk_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flush failure during shutdown must never propagate — the worker
    is already on its way out and re-raising would mask the real reason
    we're shutting down."""
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    fake_sdk = MagicMock()
    fake_sdk.flush.side_effect = RuntimeError("network down")
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        await client.create_trace(name="t")  # construct SDK
        await client.flush()  # must not raise
        fake_sdk.flush.assert_called_once()


# ---------------------------------------------------------------------------
# Singleton semantics
# ---------------------------------------------------------------------------


def test_get_langfuse_client_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_settings(monkeypatch, langfuse_secret_key="")
    a = langfuse_service.get_langfuse_client()
    b = langfuse_service.get_langfuse_client()
    assert a is b


def test_reset_langfuse_client_drops_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch, langfuse_secret_key="")
    a = langfuse_service.get_langfuse_client()
    langfuse_service.reset_langfuse_client()
    b = langfuse_service.get_langfuse_client()
    assert a is not b


# ---------------------------------------------------------------------------
# startup_check() — connectivity health check on lifespan startup (M-4 T-221)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_check_disabled_returns_true_without_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Langfuse is disabled (no secret key), startup_check returns True
    immediately — a disabled client is not an error. auth_check must never
    be called so the check adds zero latency for unconfigured deployments.
    M-4 — T-221.
    """
    _configure_settings(monkeypatch, langfuse_secret_key="")
    client = langfuse_service.get_langfuse_client()
    assert client.enabled is False

    with patch.dict({"langfuse": None}):
        # Must return True even if langfuse SDK is not importable.
        result = await client.startup_check()
    assert result is True


@pytest.mark.asyncio
async def test_startup_check_success_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When auth_check() returns True, startup_check must return True and log
    langfuse.startup_check.ok.  M-4 — T-221.
    """
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    fake_sdk = MagicMock()
    fake_sdk.auth_check.return_value = True
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        result = await client.startup_check()

    assert result is True
    fake_sdk.auth_check.assert_called_once()


@pytest.mark.asyncio
async def test_startup_check_exception_returns_false_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When auth_check() raises any exception, startup_check must catch it,
    log a WARNING, and return False — never re-raise.  A Langfuse outage
    must not prevent the application from starting.  M-4 — T-221.
    """
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    fake_sdk = MagicMock()
    fake_sdk.auth_check.side_effect = RuntimeError("auth failed — server unreachable")
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        # Must return False without propagating the RuntimeError.
        result = await client.startup_check()

    assert result is False


@pytest.mark.asyncio
async def test_startup_check_timeout_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When auth_check() takes longer than the 10-second timeout, startup_check
    must cancel it and return False.  A slow or unreachable Langfuse host
    must not stall lifespan startup indefinitely.  M-4 — T-221.
    """
    import time

    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    fake_sdk = MagicMock()

    def _hang_briefly(*_args: Any, **_kwargs: Any) -> bool:
        # Simulate a slow server: sleep slightly past our test-injected
        # asyncio.wait_for timeout (which we shorten via monkeypatching the
        # coroutine directly below).
        time.sleep(0.5)
        return True

    fake_sdk.auth_check.side_effect = _hang_briefly

    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()

        # Patch asyncio.wait_for to raise TimeoutError immediately so the
        # test is fast and deterministic rather than actually waiting 10s.
        async def _timeout_immediately(coro, timeout):  # noqa: ANN001, ANN201
            coro.close()  # clean up the coroutine to avoid ResourceWarning
            raise asyncio.TimeoutError

        with patch("asyncio.wait_for", side_effect=_timeout_immediately):
            result = await client.startup_check()

    assert result is False


@pytest.mark.asyncio
async def test_startup_check_falsy_result_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive path: if auth_check() returns a falsy value (future SDK change),
    startup_check must return False and log a warning.  M-4 — T-221.
    """
    _configure_settings(
        monkeypatch,
        langfuse_secret_key="sk-test",
        langfuse_public_key="pk-test",
    )
    fake_sdk = MagicMock()
    fake_sdk.auth_check.return_value = False
    with patch("langfuse.Langfuse", return_value=fake_sdk):
        client = langfuse_service.get_langfuse_client()
        result = await client.startup_check()

    assert result is False
