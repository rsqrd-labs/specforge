# Provider display metadata and derived model lists.
#
# Model IDs, rollout status, judge defaults, and adapter policy live in
# services.llm.model_catalog. Keep this module as a compatibility view for
# schema validation and provider health code.

from services.llm.model_catalog import (
    REQUIRED_PROVIDERS,
    default_model_for_operation,
    public_model_list,
    valid_model_ids,
)

PROVIDER_DISPLAY: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "openrouter": "OpenRouter",
}

PROVIDER_MODELS: dict[str, list[dict[str, str]]] = {
    provider: public_model_list(provider) for provider in sorted(REQUIRED_PROVIDERS)
}

JUDGE_MODELS: dict[str, str] = {
    provider: default_model_for_operation(provider, "eval.score")
    for provider in sorted(REQUIRED_PROVIDERS)
}

VALID_MODELS: dict[str, set[str]] = {
    provider: valid_model_ids(provider) for provider in sorted(REQUIRED_PROVIDERS)
}
