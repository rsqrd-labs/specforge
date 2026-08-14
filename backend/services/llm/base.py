from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass

from services.llm.prompt_cache import PromptCachePolicy

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
    """Provider-neutral error with stable retry/observability metadata."""

    def __init__(
        self,
        provider: str,
        original: Exception,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
        provider_code: str | None = None,
        retryable: bool = True,
        failover_allowed: bool | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.provider = provider
        self.original = original
        self.status_code = (
            status_code
            if status_code is not None
            else classify_provider_status(original)
        )
        self.error_type = error_type or type(original).__name__
        self.provider_code = provider_code
        self.retryable = retryable
        self.failover_allowed = (
            retryable if failover_allowed is None else failover_allowed
        )
        self.retry_after = retry_after
        self.error_code = _provider_error_code(
            provider,
            self.status_code,
            self.error_type,
            retryable=retryable,
        )
        super().__init__(f"{provider} error: {original}")


class ProviderTimeoutError(ProviderError):
    def __init__(self, provider: str, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(
            provider,
            TimeoutError(f"generation exceeded {timeout_seconds:g} seconds"),
            error_type="timeout",
            retryable=True,
        )


class ProviderRateLimitError(ProviderError):
    """A provider throttled the call (HTTP 429) or is overloaded (529/503).

    A distinct subclass of ``ProviderError`` (scalability audit F2): a rate-limit
    is a *throughput* failure, not a *quality* or *availability* failure, so the
    generation pipeline must treat it differently — retry in place on the SAME
    tier honoring ``retry_after``/backoff, and NEVER escalate within the same
    throttled provider. After bounded local retries are exhausted, a different
    configured provider is still a safe recovery route.
    Because it subclasses ``ProviderError``, every existing ``except
    ProviderError`` still catches it, so the only behaviour change is at the call
    sites that opt into the distinct handling.

    ``retry_after`` is the provider's ``Retry-After`` hint in seconds when one was
    supplied, else ``None`` (the caller falls back to exponential backoff).
    """

    def __init__(
        self,
        provider: str,
        original: Exception,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
        error_type: str | None = None,
        provider_code: str | None = None,
        failover_allowed: bool = True,
    ) -> None:
        super().__init__(
            provider,
            original,
            status_code=status_code,
            error_type=error_type or "rate_limit",
            provider_code=provider_code,
            retryable=True,
            failover_allowed=failover_allowed,
            retry_after=retry_after,
        )


class ProviderUnavailableError(ProviderError):
    """Transient model/upstream unavailability (for example OpenRouter 502)."""


class ProviderTerminalError(ProviderError):
    """A request/configuration failure that retrying unchanged cannot repair."""

    def __init__(
        self,
        provider: str,
        original: Exception,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
        provider_code: str | None = None,
        failover_allowed: bool = False,
    ) -> None:
        super().__init__(
            provider,
            original,
            status_code=status_code,
            error_type=error_type,
            provider_code=provider_code,
            retryable=False,
            failover_allowed=failover_allowed,
        )


def _provider_error_code(
    provider: str,
    status_code: int | None,
    error_type: str | None,
    *,
    retryable: bool,
) -> str:
    """Bounded terminal code suitable for DB rows, metrics, and SSE."""

    raw = (error_type or "error").strip().lower()
    safe = "".join(character if character.isalnum() else "_" for character in raw)
    safe = "_".join(part for part in safe.split("_") if part)[:64] or "error"
    status = f"_{status_code}" if status_code is not None else ""
    disposition = "transient" if retryable else "terminal"
    return f"{provider}_{disposition}{status}_{safe}"


# HTTP status codes that mean "you are being throttled / the provider is
# transiently overloaded", shared by every adapter's error classifier so the
# distinction is defined once. 429 = rate limited; 529 = Anthropic overloaded;
# 503 = service unavailable (Google ResourceExhausted/Unavailable maps here).
RATE_LIMIT_STATUS_CODES = frozenset({429, 529, 503})


def classify_provider_status(exc: Exception) -> int | None:
    """Best-effort HTTP status code for a provider SDK exception.

    Reads the common ``status_code`` (Anthropic/OpenAI) and ``code`` (Google
    genai) attributes without importing any provider SDK, so it stays usable from
    provider-neutral code. Returns ``None`` when no status can be determined.
    """
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):  # guard: bools are ints in Python
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def extract_retry_after(exc: Exception) -> float | None:
    """Best-effort ``Retry-After`` (seconds) from a provider SDK exception.

    Provider SDK errors carry the originating ``httpx.Response`` on ``.response``;
    the ``Retry-After`` header is either a delta-seconds integer or an HTTP date.
    Only the numeric form is honored (the common provider case); a non-numeric or
    absent header returns ``None`` and the caller falls back to backoff. Never
    raises — header parsing is purely advisory.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        seconds = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


class BaseLLMAdapter(ABC):
    @abstractmethod
    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
        cache_policy: PromptCachePolicy | None = None,
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
        cache_policy: PromptCachePolicy | None = None,
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
