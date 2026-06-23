from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass

# HTTP timeout policy (H-6 — T-182): every concrete adapter MUST configure an
# explicit timeout= on its underlying httpx client.  Use httpx.Timeout(
# connect=10.0, read=300.0, write=10.0, pool=5.0) as the project default.


@dataclass(frozen=True)
class BatchRequest:
    """One request inside a provider Message Batches submission (Phase 3)."""

    custom_id: str
    system: str
    user: str
    max_tokens: int


@dataclass(frozen=True)
class BatchResultItem:
    """The normalised outcome of one batch request once the batch has ended.

    ``status`` is the provider-neutral result class (``succeeded`` / ``errored``
    / ``expired`` / ``canceled``); ``text`` is the completion text on success;
    ``usage`` is the raw provider usage mapping (fed through
    ``normalize_provider_usage`` by the collector for cost accounting).
    """

    custom_id: str
    status: str
    text: str | None = None
    usage: dict | None = None
    finish_reason: str | None = None
    error: str | None = None


class BatchUnsupportedError(NotImplementedError):
    """Raised when an adapter has no provider Message Batches implementation.

    Callers catch this to fall back to the synchronous in-process path; it is
    not a failure of a batch that was actually submitted.
    """


class ProviderError(Exception):
    def __init__(self, provider: str, original: Exception) -> None:
        self.provider = provider
        self.original = original
        super().__init__(f"{provider} error: {original}")


class ProviderTimeoutError(ProviderError):
    def __init__(self, provider: str, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(
            provider,
            TimeoutError(f"generation exceeded {timeout_seconds:g} seconds"),
        )


class BaseLLMAdapter(ABC):
    @abstractmethod
    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_user_prefix: str | None = None,
    ) -> AsyncGenerator[str, None]:
        pass

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_user_prefix: str | None = None,
    ) -> str:
        pass

    # --- Message Batches (Phase 3, issue #26) -------------------------------
    # Default implementations raise BatchUnsupportedError so an adapter without
    # a batch API (or a provider whose batch surface is not yet wired) cleanly
    # falls back to the synchronous path. Adapters override all three together.

    async def submit_batch(self, requests: Sequence[BatchRequest]) -> str:
        """Create a provider batch and return its id (durably checkpoint it)."""
        raise BatchUnsupportedError(
            f"{type(self).__name__} does not support Message Batches"
        )

    async def poll_batch(self, provider_batch_id: str) -> str:
        """Return the batch's processing status; ``ended`` means results ready."""
        raise BatchUnsupportedError(
            f"{type(self).__name__} does not support Message Batches"
        )

    async def fetch_batch_results(
        self, provider_batch_id: str
    ) -> dict[str, BatchResultItem]:
        """Return results keyed by custom_id for an ended batch."""
        raise BatchUnsupportedError(
            f"{type(self).__name__} does not support Message Batches"
        )
