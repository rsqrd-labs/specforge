from __future__ import annotations


def test_google_gemini3_config_includes_thinking_level() -> None:
    from services.llm.google_adapter import GoogleAdapter

    adapter = GoogleAdapter.__new__(GoogleAdapter)
    adapter.model = "gemini-3.5-flash"
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
    assert request["extra_body"] == {"effort": "high"}


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
    assert anthropic_request["extra_body"] == {"effort": "low"}

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
    google_adapter.model = "gemini-3.5-flash"
    google_adapter._request_policy = model_request_policy(
        "google",
        google_adapter.model,
        "harness.generate",
    )
    google_config = google_adapter._config("sys", 49152)
    assert google_config.thinking_config is not None
    assert google_config.thinking_config.thinking_level.value == "LOW"
