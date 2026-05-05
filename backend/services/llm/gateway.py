from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from services.llm.base import BaseLLMAdapter

_REGISTRY: dict[str, type] = {}
_PROVIDER_KEY_SETTINGS = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "google": ("GOOGLE_API_KEY", "google_api_key"),
}
# Adapter instances are cached per provider, model, and API-key fingerprint.
# When a provider key changes in the process environment, the fingerprint changes
# and the next get_llm() call builds a fresh provider client automatically.
_INSTANCES: dict[tuple[str, str, str], "BaseLLMAdapter"] = {}


def _register(provider: str, cls: type) -> None:
    _REGISTRY[provider] = cls


def get_llm(provider: str, model: str) -> "BaseLLMAdapter":
    if provider not in _REGISTRY:
        raise ValueError(f"Unknown LLM provider: {provider!r}")
    api_key = _provider_api_key(provider)
    key = (provider, model, _secret_fingerprint(api_key))
    if key not in _INSTANCES:
        _INSTANCES[key] = _REGISTRY[provider](model, api_key=api_key)
    return _INSTANCES[key]


def clear_llm_cache() -> None:
    _INSTANCES.clear()


def _provider_api_key(provider: str) -> str:
    env_name, setting_name = _PROVIDER_KEY_SETTINGS[provider]
    return os.getenv(env_name) or str(getattr(settings, setting_name))


def _secret_fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _load_adapters() -> None:
    from services.llm.anthropic_adapter import AnthropicAdapter
    from services.llm.google_adapter import GoogleAdapter
    from services.llm.openai_adapter import OpenAIAdapter

    _register("anthropic", AnthropicAdapter)
    _register("openai", OpenAIAdapter)
    _register("google", GoogleAdapter)


_load_adapters()
