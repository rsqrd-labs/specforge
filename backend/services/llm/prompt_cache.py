from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

PromptCacheRetention = Literal["memory", "24h"]


@dataclass(frozen=True)
class PromptCachePolicy:
    """Model-independent identity for one reusable prompt prefix.

    ``routing_key`` deliberately excludes provider model/tier and tenant data.
    Providers remain responsible for isolating the underlying model-specific
    cache entries; SpecForge only supplies a stable logical routing bucket.
    """

    namespace: str
    routing_key: str
    retention: PromptCacheRetention
    eligible_prefix_fingerprint: str


def build_prompt_cache_policy(
    *,
    namespace: str,
    stage_type: str,
    mode: str,
    prompt_version: str,
    system_prompt: str,
    base_user_prompt: str,
    retention: PromptCacheRetention = "memory",
) -> PromptCachePolicy:
    """Build a deterministic policy without model, tier, tenant, or artifact IDs."""
    system_fingerprint = _sha256(system_prompt)[:16]
    logical_identity = ":".join(
        (namespace, stage_type, mode, prompt_version, system_fingerprint)
    )
    return PromptCachePolicy(
        namespace=namespace,
        routing_key=f"specforge:{namespace}:{_sha256(logical_identity)[:32]}",
        retention=retention,
        eligible_prefix_fingerprint=_sha256(f"{system_prompt}\0{base_user_prompt}"),
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_USER_PREFIX_CACHE_HINT: ContextVar[str | None] = ContextVar(
    "llm_user_prefix_cache_hint",
    default=None,
)


@contextmanager
def user_prefix_cache_hint(prefix: str | None) -> Iterator[None]:
    """Scope an Anthropic user-prefix cache hint to the current async context."""
    token = _USER_PREFIX_CACHE_HINT.set(prefix)
    try:
        yield
    finally:
        _USER_PREFIX_CACHE_HINT.reset(token)


def current_user_prefix_cache_hint() -> str | None:
    return _USER_PREFIX_CACHE_HINT.get()
