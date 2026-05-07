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
