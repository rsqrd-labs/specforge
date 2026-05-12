from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


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
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...
