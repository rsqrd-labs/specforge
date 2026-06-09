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
