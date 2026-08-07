from __future__ import annotations


def test_google_gemini3_config_includes_thinking_level() -> None:
    from services.llm.google_adapter import GoogleAdapter

    adapter = GoogleAdapter.__new__(GoogleAdapter)
    adapter.model = "gemini-3.6-flash"
    adapter._request_policy = {
        "adapter_api": "generate_content",
        "thinking_level": "high",
    }

    config = adapter._config("sys", 8192)

    assert config.system_instruction == "sys"
    assert config.max_output_tokens == 8192
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level.value == "HIGH"


def test_anthropic_opus48_request_includes_effort() -> None:
    from services.llm.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model = "claude-opus-4-8"
    adapter._request_policy = {
        "adapter_api": "messages",
        "reasoning_effort": "high",
    }

    request = adapter._messages_request(system="sys", user="user", max_tokens=8192)

    assert request["model"] == "claude-opus-4-8"
    assert request["system"] == "sys"
    assert request["messages"] == [{"role": "user", "content": "user"}]
    assert request["max_tokens"] == 8192
    assert request["output_config"] == {"effort": "high"}


def test_opus_5_core_stage_request_sends_effort_not_a_thinking_block() -> None:
    """Opus 5 does NOT support extended thinking (`thinking.type: "enabled"`) —
    it uses adaptive thinking plus the `effort` parameter. The Anthropic adapter
    must therefore keep emitting the effort for it; sending a thinking block
    instead would 400 every core-stage generation.

    `effort` is nested under the `output_config` body param. It was previously
    sent top-level via `extra_body`, which 400s with "effort: Extra inputs are
    not permitted" — that hard-failed every Anthropic call, core stages included.

    The effort is `high` (since 2026-08-06 — a deliberate quality-over-margin
    trade after a production spec generation was judged not up to the mark at
    the previous `medium`; see the claude-opus-5 catalog entry). Core stages
    are bound by a locked interactive deadline (a single provider stream is
    capped at `stage_provider_call_timeout_seconds`, 270s as of the same
    change; the stage itself at a validator-pinned 300s), and high-effort
    reasoning tokens are spent before any visible output — this pairing has not
    been re-measured at high effort the way `medium` was.
    """
    from services.llm.anthropic_adapter import AnthropicAdapter
    from services.llm.model_catalog import model_request_policy

    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model = "claude-opus-5"
    adapter._request_policy = model_request_policy(
        "anthropic", adapter.model, "spec.generate"
    )

    request = adapter._messages_request(system="sys", user="user", max_tokens=49152)

    assert request["model"] == "claude-opus-5"
    assert request["output_config"] == {"effort": "high"}
    assert "extra_body" not in request
    assert "thinking" not in request


def test_haiku_45_request_omits_the_unsupported_effort_parameter() -> None:
    """Haiku 4.5 rejects `effort` outright ("This model does not support the
    effort parameter"), so its request must carry no effort at all — not a
    lowered one. This model serves every cheap path (judge/eval/summary,
    focused+section refine, storyboard, increment), so emitting it 400s them all.
    """
    from services.llm.anthropic_adapter import AnthropicAdapter
    from services.llm.model_catalog import model_request_policy

    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model = "claude-haiku-4-5-20251001"
    adapter._request_policy = model_request_policy(
        "anthropic", adapter.model, "eval.score"
    )

    request = adapter._messages_request(system="sys", user="user", max_tokens=8192)

    assert "output_config" not in request
    assert "extra_body" not in request


def test_core_stage_low_reasoning_reaches_provider_payloads(monkeypatch) -> None:
    from config import settings
    from services.llm.anthropic_adapter import AnthropicAdapter
    from services.llm.google_adapter import GoogleAdapter
    from services.llm.model_catalog import model_request_policy
    from services.llm.openai_adapter import OpenAIAdapter

    monkeypatch.setattr(settings, "core_generation_low_reasoning", True)

    anthropic_adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    anthropic_adapter.model = "claude-haiku-4-5-20251001"
    anthropic_adapter._request_policy = model_request_policy(
        "anthropic",
        anthropic_adapter.model,
        "spec.generate",
    )
    anthropic_request = anthropic_adapter._messages_request(
        system="sys", user="user", max_tokens=49152
    )
    # The low-reasoning override LOWERS an effort the model accepts; it must not
    # introduce one on Haiku 4.5, which rejects the parameter entirely.
    assert "output_config" not in anthropic_request

    openai_adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    openai_adapter.model = "gpt-5.4-mini"
    openai_adapter._request_policy = model_request_policy(
        "openai",
        openai_adapter.model,
        "tasks.generate",
    )
    openai_request = openai_adapter._responses_request(
        system="sys", user="user", max_tokens=49152, stream=True
    )
    assert openai_request["reasoning"] == {"effort": "low", "summary": "auto"}

    google_adapter = GoogleAdapter.__new__(GoogleAdapter)
    google_adapter.model = "gemini-3.6-flash"
    google_adapter._request_policy = model_request_policy(
        "google",
        google_adapter.model,
        "harness.generate",
    )
    google_config = google_adapter._config("sys", 49152)
    assert google_config.thinking_config is not None
    assert google_config.thinking_config.thinking_level.value == "LOW"
