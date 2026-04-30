from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class ProviderError(Exception):
    def __init__(self, provider: str, original: Exception) -> None:
        self.provider = provider
        self.original = original
        super().__init__(f"{provider} error: {original}")


class BaseLLMAdapter(ABC):
    @abstractmethod
    async def stream(
        self, system: str, user: str, max_tokens: int
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...
