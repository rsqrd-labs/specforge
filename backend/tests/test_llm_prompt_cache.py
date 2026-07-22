"""Unit tests for Phase 2: provider prompt/context caching (issue #26).

Coverage:
  PC-1  AnthropicAdapter with cache_system=True emits a structured system block
        with cache_control in the outbound messages request.
  PC-2  AnthropicAdapter with cache_system=False keeps the plain-string system
        field (back-compat).
  PC-3  The llm_prompt_cache_enabled kill-switch overrides cache_system=True and
        reverts to the plain-string path.
  PC-4  AnthropicAdapter.stream() forwards cache_system to _messages_request.
  PC-5  OpenAIAdapter accepts cache_system without error (automatic caching).
  PC-6  GoogleAdapter accepts cache_system without error (explicit caching deferred).
  PC-7  InstrumentedAdapter forwards cache_system to the wrapped adapter.
  PC-8  complete_with_timeout forwards cache_system to the adapter.
  PC-9  Anthropic cache tokens (cache_read + cache_creation) normalise to
        cached_input_tokens so they feed the cost estimator.

All tests are unit-level (no DB, no Redis, no live HTTP calls).
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.llm.anthropic_adapter import AnthropicAdapter
from services.llm.base import BaseLLMAdapter
from services.llm.google_adapter import GoogleAdapter
from services.llm.instrumented_adapter import InstrumentedAdapter
from services.llm.openai_adapter import OpenAIAdapter
from services.llm.prompt_cache import user_prefix_cache_hint
from services.llm.usage import normalize_provider_usage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYSTEM = "You are a helpful assistant."
_USER = "Hello world."
_MAX_TOKENS = 128


def _make_anthropic_adapter() -> AnthropicAdapter:
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model = "claude-haiku-4-5-20251001"
    adapter.last_completion = None
    from services.llm.model_catalog import model_request_policy

    adapter._request_policy = model_request_policy("anthropic", adapter.model)
    adapter._client = MagicMock()
    return adapter


def _make_openai_adapter() -> OpenAIAdapter:
    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "gpt-5.4-mini"
    adapter.last_completion = None
    from services.llm.model_catalog import model_request_policy

    adapter._request_policy = model_request_policy("openai", adapter.model)
    adapter._client = MagicMock()
    return adapter


def _make_google_adapter() -> GoogleAdapter:
    adapter = GoogleAdapter.__new__(GoogleAdapter)
    adapter.model = "gemini-3.5-flash"
    adapter.last_completion = None
    from services.llm.model_catalog import model_request_policy

    adapter._request_policy = model_request_policy("google", adapter.model)
    adapter._client = MagicMock()
    return adapter


# ---------------------------------------------------------------------------
# PC-1: Anthropic complete — cache_system=True emits structured block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_complete_cache_system_structured_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cache_system=True must wrap the system string in a list with cache_control."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(
            anthropic_api_key="test",
            llm_prompt_cache_enabled=True,
        ),
    )

    captured_kwargs: dict = {}

    async def _fake_create(**kwargs) -> MagicMock:
        captured_kwargs.update(kwargs)
        msg = MagicMock()
        msg.stop_reason = "end_turn"
        msg.usage = MagicMock(input_tokens=10, output_tokens=5)
        msg.content = [SimpleNamespace(text="result")]
        return msg

    adapter._client.messages.create = _fake_create

    result = await adapter.complete(_SYSTEM, _USER, _MAX_TOKENS, cache_system=True)

    assert result == "result"
    system_field = captured_kwargs["system"]
    assert isinstance(
        system_field, list
    ), "system must be a list when cache_system=True"
    assert len(system_field) == 1
    block = system_field[0]
    assert block["type"] == "text"
    assert block["text"] == _SYSTEM
    assert block["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# PC-2: Anthropic complete — cache_system=False keeps plain string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_complete_no_cache_plain_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cache_system=False (default) must leave system as a plain string."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(
            anthropic_api_key="test",
            llm_prompt_cache_enabled=True,
        ),
    )

    captured_kwargs: dict = {}

    async def _fake_create(**kwargs) -> MagicMock:
        captured_kwargs.update(kwargs)
        msg = MagicMock()
        msg.stop_reason = "end_turn"
        msg.usage = None
        msg.content = [SimpleNamespace(text="ok")]
        return msg

    adapter._client.messages.create = _fake_create

    await adapter.complete(_SYSTEM, _USER, _MAX_TOKENS)  # default cache_system=False

    assert captured_kwargs["system"] == _SYSTEM


# ---------------------------------------------------------------------------
# PC-3: Kill-switch — llm_prompt_cache_enabled=False overrides cache_system=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_complete_kill_switch_disables_caching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """llm_prompt_cache_enabled=False must revert to plain string even when
    cache_system=True is passed."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(
            anthropic_api_key="test",
            llm_prompt_cache_enabled=False,  # kill-switch OFF
        ),
    )

    captured_kwargs: dict = {}

    async def _fake_create(**kwargs) -> MagicMock:
        captured_kwargs.update(kwargs)
        msg = MagicMock()
        msg.stop_reason = "end_turn"
        msg.usage = None
        msg.content = [SimpleNamespace(text="ok")]
        return msg

    adapter._client.messages.create = _fake_create

    await adapter.complete(_SYSTEM, _USER, _MAX_TOKENS, cache_system=True)

    assert (
        captured_kwargs["system"] == _SYSTEM
    ), "system must remain a plain string when llm_prompt_cache_enabled=False"


# ---------------------------------------------------------------------------
# PC-4: Anthropic stream — cache_system=True forwarded to _messages_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_stream_cache_system_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stream() must forward cache_system to _messages_request."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(
            anthropic_api_key="test",
            llm_prompt_cache_enabled=True,
        ),
    )

    captured_request: dict = {}

    async def _fake_events():
        yield SimpleNamespace(type="text", text="hello")

    class _FakeStream:
        def __aiter__(self):
            return _fake_events()

        get_final_message = AsyncMock(
            return_value=MagicMock(
                stop_reason="end_turn",
                usage=MagicMock(input_tokens=5, output_tokens=2),
            )
        )

    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=_FakeStream())
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    def _fake_stream(**kwargs):
        captured_request.update(kwargs)
        return fake_ctx

    adapter._client.messages.stream = _fake_stream

    tokens = [
        t async for t in adapter.stream(_SYSTEM, _USER, _MAX_TOKENS, cache_system=True)
    ]

    assert "hello" in tokens
    system_field = captured_request["system"]
    assert isinstance(system_field, list), "stream must pass structured system block"
    assert system_field[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# PC-5: OpenAI accepts cache_system without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_adapter_accepts_cache_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI automatic prefix caching: cache_system is accepted, no error."""
    adapter = _make_openai_adapter()

    async def _fake_complete(**kwargs) -> MagicMock:
        response = MagicMock()
        response.output_text = "result"
        response.status = "completed"
        response.usage = MagicMock(
            input_tokens=10,
            output_tokens=5,
            prompt_tokens_details=MagicMock(cached_tokens=0),
        )
        return response

    responses_mock = MagicMock()
    responses_mock.create = _fake_complete
    adapter._client.responses = responses_mock

    result = await adapter.complete(_SYSTEM, _USER, _MAX_TOKENS, cache_system=True)
    assert result == "result"


# ---------------------------------------------------------------------------
# PC-6: Google accepts cache_system without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_adapter_accepts_cache_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google explicit caching deferred; cache_system is accepted, no error."""
    adapter = _make_google_adapter()

    response = MagicMock()
    response.text = "result"
    response.candidates = []
    response.usage_metadata = None

    adapter._client.aio = MagicMock()
    adapter._client.aio.models = MagicMock()
    adapter._client.aio.models.generate_content = AsyncMock(return_value=response)

    result = await adapter.complete(_SYSTEM, _USER, _MAX_TOKENS, cache_system=True)
    assert result == "result"


# ---------------------------------------------------------------------------
# PC-7: InstrumentedAdapter forwards cache_system to wrapped adapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_cls",
    [
        BaseLLMAdapter,
        InstrumentedAdapter,
        AnthropicAdapter,
        OpenAIAdapter,
        GoogleAdapter,
    ],
)
def test_llm_adapter_public_cache_signature(adapter_cls: type) -> None:
    """Only the issue-#26 cache_system flag is part of the public call surface."""
    for method_name in ("stream", "complete"):
        signature = inspect.signature(getattr(adapter_cls, method_name))
        kwonly = [
            name
            for name, param in signature.parameters.items()
            if param.kind is inspect.Parameter.KEYWORD_ONLY
        ]
        assert kwonly == ["cache_system", "cache_policy"]


@pytest.mark.asyncio
async def test_instrumented_adapter_forwards_cache_system() -> None:
    """InstrumentedAdapter must forward cache_system to the wrapped adapter."""

    class _RecordingAdapter(BaseLLMAdapter):
        def __init__(self) -> None:
            self.last_completion = None
            self.seen_cache_system: list[bool] = []

        async def stream(
            self,
            system: str,
            user: str,
            max_tokens: int,
            *,
            cache_system: bool = False,
        ) -> AsyncGenerator[str, None]:
            self.seen_cache_system.append(cache_system)
            yield "tok"

        async def complete(
            self,
            system: str,
            user: str,
            max_tokens: int,
            *,
            cache_system: bool = False,
        ) -> str:
            self.seen_cache_system.append(cache_system)
            return "ok"

    inner = _RecordingAdapter()
    with (
        patch("services.llm.instrumented_adapter.langfuse_service"),
        patch("services.llm.instrumented_adapter.record_llm_cost_event"),
        patch("services.llm.instrumented_adapter.persist_cost_event", new=AsyncMock()),
        patch("services.llm.instrumented_adapter.record_provider_success"),
        patch("services.llm.instrumented_adapter.record_provider_failure"),
    ):
        adapter = InstrumentedAdapter(
            inner,
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            stage_type="spec",
            action="generate",
        )

        await adapter.complete("sys", "user", 100, cache_system=True)
        tokens = [
            t async for t in adapter.stream("sys", "user", 100, cache_system=True)
        ]

    assert inner.seen_cache_system == [
        True,
        True,
    ], "InstrumentedAdapter must forward cache_system=True to the wrapped adapter"
    assert "tok" in tokens


# ---------------------------------------------------------------------------
# PC-8: complete_with_timeout forwards cache_system
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_with_timeout_forwards_cache_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """complete_with_timeout must pass cache_system to adapter.complete."""
    seen_cache_system: list[bool] = []

    class _FakeAdapter(BaseLLMAdapter):
        def __init__(self) -> None:
            self.last_completion = None

        async def stream(self, s, u, m, *, cache_system=False):  # pragma: no cover
            yield ""

        async def complete(self, s, u, m, *, cache_system=False) -> str:
            seen_cache_system.append(cache_system)
            return "done"

    monkeypatch.setattr(
        "services.llm.gateway.get_llm", lambda provider, model: _FakeAdapter()
    )

    from services.llm.gateway import complete_with_timeout

    result = await complete_with_timeout(
        "anthropic",
        "claude-haiku-4-5-20251001",
        "sys",
        "user",
        128,
        cache_system=True,
    )
    assert result == "done"
    assert seen_cache_system == [
        True
    ], "complete_with_timeout must forward cache_system"


# ---------------------------------------------------------------------------
# PC-9: Anthropic cache tokens normalise to cached_input_tokens
# ---------------------------------------------------------------------------


def test_anthropic_cache_tokens_normalised() -> None:
    """cache_read_input_tokens surfaces as cached_input_tokens (read-discount
    rate) while cache_creation_input_tokens surfaces separately as
    cache_write_input_tokens (premium write rate) — writes must never receive
    the read discount (issue #82). input_tokens is normalised to the full
    prompt total (base + read + write)."""
    raw = {
        "input_tokens": 500,
        "cache_read_input_tokens": 400,
        "cache_creation_input_tokens": 0,
        "output_tokens": 100,
    }
    usage = normalize_provider_usage("anthropic", raw)
    assert usage.input_tokens == 900
    assert usage.cached_input_tokens == 400
    assert usage.cache_write_input_tokens is None

    raw_write = {
        "input_tokens": 500,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 300,
        "output_tokens": 80,
    }
    usage_write = normalize_provider_usage("anthropic", raw_write)
    assert usage_write.input_tokens == 800
    assert usage_write.cached_input_tokens is None
    assert usage_write.cache_write_input_tokens == 300


# ---------------------------------------------------------------------------
# PC-10..PC-15: issue #39 (Lever A) — caching the stable user-prompt prefix
# ---------------------------------------------------------------------------

# Comfortably above _MIN_CACHEABLE_PREFIX_CHARS (8192) — the input-heavy stages
# whose upstream artifacts Lever A targets always clear it.
_PREFIX = "BASE PROMPT: " + ("x" * 9000)  # the stable base_user_prompt
_SUFFIX = "\n\nChunk scope: generate only section A."
_FULL_USER = _PREFIX + _SUFFIX


def _messages_request_user_content(
    adapter: AnthropicAdapter, *, cache_user_prefix: str | None
) -> object:
    return adapter._messages_request(
        system=_SYSTEM,
        user=_FULL_USER,
        max_tokens=_MAX_TOKENS,
        cache_user_prefix=cache_user_prefix,
    )["messages"][0]["content"]


def test_user_prefix_cached_splits_into_two_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC-10: a valid prefix splits the user message into a cached prefix block
    plus a variable suffix block; concatenated they reproduce the input byte
    for byte (the model sees identical text)."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(anthropic_api_key="test", llm_prompt_cache_enabled=True),
    )

    content = _messages_request_user_content(adapter, cache_user_prefix=_PREFIX)

    assert isinstance(content, list) and len(content) == 2
    prefix_block, suffix_block = content
    assert prefix_block["text"] == _PREFIX
    assert prefix_block["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in suffix_block
    assert suffix_block["text"] == _SUFFIX
    assert prefix_block["text"] + suffix_block["text"] == _FULL_USER


def test_user_prefix_kill_switch_keeps_plain_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC-11: llm_prompt_cache_enabled=False reverts to the plain-string user
    message even when a prefix is supplied (the regression pin)."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(anthropic_api_key="test", llm_prompt_cache_enabled=False),
    )

    content = _messages_request_user_content(adapter, cache_user_prefix=_PREFIX)

    assert content == _FULL_USER


def test_user_prefix_none_keeps_plain_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC-12: no prefix supplied → plain-string user message (default callers)."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(anthropic_api_key="test", llm_prompt_cache_enabled=True),
    )

    content = _messages_request_user_content(adapter, cache_user_prefix=None)

    assert content == _FULL_USER


def test_user_prefix_not_a_prefix_or_empty_suffix_stays_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC-13: a string that is not a proper prefix of user, or one equal to the
    whole user (empty suffix), is never split — the API rejects empty text
    blocks, so we fall back to the plain string."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(anthropic_api_key="test", llm_prompt_cache_enabled=True),
    )

    not_a_prefix = "totally different text"
    assert (
        _messages_request_user_content(adapter, cache_user_prefix=not_a_prefix)
        == _FULL_USER
    )
    # prefix == full user ⇒ empty suffix ⇒ stay plain
    assert (
        _messages_request_user_content(adapter, cache_user_prefix=_FULL_USER)
        == _FULL_USER
    )


def test_user_prefix_below_min_cacheable_stays_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC-15: a prefix below Anthropic's minimum cacheable length is not marked
    cacheable (Anthropic would ignore the marker anyway) — e.g. the compressed
    spec problem statement.  Returns the plain string so no breakpoint is wasted
    and the sub-minimum edge is never exercised."""
    from services.llm.anthropic_adapter import _MIN_CACHEABLE_PREFIX_CHARS

    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(anthropic_api_key="test", llm_prompt_cache_enabled=True),
    )

    small_prefix = "x" * (_MIN_CACHEABLE_PREFIX_CHARS - 1)
    user = small_prefix + "\n\nChunk scope: section A."
    content = adapter._messages_request(
        system=_SYSTEM,
        user=user,
        max_tokens=_MAX_TOKENS,
        cache_user_prefix=small_prefix,
    )["messages"][0]["content"]

    assert content == user


@pytest.mark.asyncio
async def test_anthropic_stream_uses_scoped_user_prefix_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PC-14: stream() reads the scoped user-prefix hint for _messages_request
    without growing the BaseLLMAdapter method signature."""
    adapter = _make_anthropic_adapter()
    monkeypatch.setattr(
        "services.llm.anthropic_adapter.settings",
        SimpleNamespace(anthropic_api_key="test", llm_prompt_cache_enabled=True),
    )

    seen: dict = {}
    original = adapter._messages_request

    def _spy(**kwargs):
        seen.update(kwargs)
        return original(**kwargs)

    adapter._messages_request = _spy  # type: ignore[method-assign]

    async def _fake_events():
        if False:  # pragma: no cover - empty async generator
            yield ""

    class _Ctx:
        async def __aenter__(self):
            stream = MagicMock()
            stream.__aiter__ = lambda _self: _fake_events()
            stream.get_final_message = AsyncMock(
                return_value=SimpleNamespace(stop_reason="end_turn", usage=None)
            )
            return stream

        async def __aexit__(self, *exc):
            return False

    adapter._client.messages.stream = MagicMock(return_value=_Ctx())

    with user_prefix_cache_hint(_PREFIX):
        async for _ in adapter.stream(
            _SYSTEM,
            _FULL_USER,
            _MAX_TOKENS,
            cache_system=True,
        ):
            pass

    assert seen.get("cache_user_prefix") == _PREFIX
