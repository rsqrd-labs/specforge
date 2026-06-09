from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_LIMIT_FINISH_REASONS = {
    "length",
    "max_tokens",
    "max_output_tokens",
    "max_token",
    "max_tokens_reached",
    "token_limit",
    "MAX_TOKENS",
}


@dataclass
class LLMCompletionInfo:
    provider: str
    model: str
    max_tokens: int
    finish_reason: str | None = None
    stopped_by_limit: bool = False
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def started(
        cls,
        *,
        provider: str,
        model: str,
        max_tokens: int,
    ) -> "LLMCompletionInfo":
        return cls(provider=provider, model=model, max_tokens=max_tokens)

    def apply_finish_reason(self, reason: Any) -> None:
        if reason is None:
            return
        value = _normalise_finish_reason(reason)
        if not value:
            return
        self.finish_reason = value
        self.stopped_by_limit = (
            value in _LIMIT_FINISH_REASONS
            or value.upper() in _LIMIT_FINISH_REASONS
        )


def _normalise_finish_reason(reason: Any) -> str:
    value = getattr(reason, "name", None) or getattr(reason, "value", None) or reason
    return str(value).strip()
