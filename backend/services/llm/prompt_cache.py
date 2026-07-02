from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

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
