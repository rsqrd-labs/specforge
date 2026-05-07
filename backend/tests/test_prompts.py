from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import prompts.base as prompt_base
import prompts.spec as spec_prompts


@pytest.fixture(autouse=True)
def clear_prompt_cache() -> None:
    prompt_base._PROMPT_CACHE.clear()


@pytest.mark.asyncio
async def test_get_system_prompt_falls_back_when_langfuse_unconfigured() -> None:
    client = MagicMock()
    client.get_prompt = AsyncMock(return_value=None)

    with patch.object(
        prompt_base.langfuse_service, "get_langfuse_client", return_value=client
    ):
        assert await spec_prompts.get_system_prompt() == spec_prompts.SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_load_prompt_uses_remote_prompt_when_available() -> None:
    client = MagicMock()
    client.get_prompt = AsyncMock(return_value="REMOTE SYSTEM PROMPT")

    with patch.object(
        prompt_base.langfuse_service, "get_langfuse_client", return_value=client
    ):
        assert (
            await prompt_base.load_prompt("specforge.spec.system", "LOCAL")
            == "REMOTE SYSTEM PROMPT"
        )


@pytest.mark.asyncio
async def test_load_prompt_falls_back_silently_on_langfuse_error() -> None:
    client = MagicMock()
    client.get_prompt = AsyncMock(side_effect=RuntimeError("langfuse 503"))

    with patch.object(
        prompt_base.langfuse_service, "get_langfuse_client", return_value=client
    ):
        assert (
            await prompt_base.load_prompt("specforge.spec.system", "LOCAL") == "LOCAL"
        )


@pytest.mark.asyncio
async def test_load_prompt_uses_ttl_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt_base.settings, "langfuse_prompt_cache_ttl", 300)
    client = MagicMock()
    client.get_prompt = AsyncMock(return_value="REMOTE")

    with patch.object(
        prompt_base.langfuse_service, "get_langfuse_client", return_value=client
    ):
        assert (
            await prompt_base.load_prompt("specforge.spec.system", "LOCAL") == "REMOTE"
        )
        assert (
            await prompt_base.load_prompt("specforge.spec.system", "LOCAL") == "REMOTE"
        )

    client.get_prompt.assert_awaited_once_with("specforge.spec.system")
