from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.llm.base import BaseLLMAdapter

_REGISTRY: dict[str, type] = {}
# Adapter instances are cached for the lifetime of each gunicorn worker. After
# rotating ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY, restart all API
# workers so every cached provider client is rebuilt with the new secret.
_INSTANCES: dict[tuple[str, str], "BaseLLMAdapter"] = {}


def _register(provider: str, cls: type) -> None:
    _REGISTRY[provider] = cls


def get_llm(provider: str, model: str) -> "BaseLLMAdapter":
    if provider not in _REGISTRY:
        raise ValueError(f"Unknown LLM provider: {provider!r}")
    key = (provider, model)
    if key not in _INSTANCES:
        _INSTANCES[key] = _REGISTRY[provider](model)
    return _INSTANCES[key]


def _load_adapters() -> None:
    from services.llm.anthropic_adapter import AnthropicAdapter
    from services.llm.google_adapter import GoogleAdapter
    from services.llm.openai_adapter import OpenAIAdapter

    _register("anthropic", AnthropicAdapter)
    _register("openai", OpenAIAdapter)
    _register("google", GoogleAdapter)


_load_adapters()
