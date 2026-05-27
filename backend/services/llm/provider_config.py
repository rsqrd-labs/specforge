# Provider model catalogue and judge model assignments.
# This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
# timeout= enforcement is delegated to each concrete adapter implementation.

PROVIDER_MODELS: dict[str, list[dict[str, str]]] = {
    "anthropic": [
        {"id": "claude-opus-4-7", "name": "Claude Opus 4"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        {"id": "o1-preview", "name": "o1 Preview"},
    ],
    "google": [
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro"},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash"},
        {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash"},
    ],
}

PROVIDER_DISPLAY: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
}

JUDGE_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "google": "gemini-1.5-flash",
}

VALID_MODELS: dict[str, set[str]] = {
    provider: {m["id"] for m in models} for provider, models in PROVIDER_MODELS.items()
}
