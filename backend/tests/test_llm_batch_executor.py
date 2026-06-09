from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.llm.batch_executor import (
    BatchEligibilityError,
    clear_dead_letter_jobs,
    complete_background_llm,
    dead_letter_jobs,
)


@pytest.mark.asyncio
async def test_interactive_operations_reject_batch_path() -> None:
    adapter_factory = MagicMock()

    with pytest.raises(BatchEligibilityError):
        await complete_background_llm(
            operation="spec.generate",
            provider="openai",
            model="gpt-5.5",
            system="sys",
            user="user",
            max_tokens=100,
            stage_type="spec",
            adapter_factory=adapter_factory,
        )

    adapter_factory.assert_not_called()


@pytest.mark.asyncio
async def test_eligible_operation_marks_batch_when_provider_supports_it() -> None:
    adapter = MagicMock()
    adapter_factory = MagicMock(return_value=adapter)
    instrumented = MagicMock()
    instrumented.complete = AsyncMock(return_value='{"overall_score": 90}')

    with patch(
        "services.llm.batch_executor.InstrumentedAdapter",
        return_value=instrumented,
    ) as instrumented_cls:
        result = await complete_background_llm(
            operation="eval.score",
            provider="openai",
            model="gpt-5.4-mini",
            system="sys",
            user="user",
            max_tokens=100,
            stage_type="eval",
            adapter_factory=adapter_factory,
        )

    assert result.output == '{"overall_score": 90}'
    assert result.batch is True
    adapter_factory.assert_called_once_with("openai", "gpt-5.4-mini")
    assert instrumented_cls.call_args.kwargs["batch"] is True
    assert instrumented_cls.call_args.kwargs["operation"] == "eval.score"


@pytest.mark.asyncio
async def test_eligible_operation_falls_back_when_provider_lacks_batch() -> None:
    adapter_factory = MagicMock(return_value=MagicMock())
    instrumented = MagicMock()
    instrumented.complete = AsyncMock(return_value="ok")

    with (
        patch(
            "services.llm.batch_executor.get_provider_capabilities",
            return_value={"supports_batch": False},
        ),
        patch(
            "services.llm.batch_executor.InstrumentedAdapter",
            return_value=instrumented,
        ) as instrumented_cls,
    ):
        result = await complete_background_llm(
            operation="summary.create",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            system="sys",
            user="user",
            max_tokens=100,
            stage_type="summary",
            adapter_factory=adapter_factory,
        )

    assert result.output == "ok"
    assert result.batch is False
    assert instrumented_cls.call_args.kwargs["batch"] is False


@pytest.mark.asyncio
async def test_failed_background_job_is_dead_lettered() -> None:
    clear_dead_letter_jobs()
    adapter_factory = MagicMock(return_value=MagicMock())
    instrumented = MagicMock()
    instrumented.complete = AsyncMock(side_effect=RuntimeError("provider down"))

    with patch(
        "services.llm.batch_executor.InstrumentedAdapter",
        return_value=instrumented,
    ):
        with pytest.raises(RuntimeError, match="provider down"):
            await complete_background_llm(
                operation="eval.score",
                provider="google",
                model="gemini-3.1-flash-lite",
                system="sys",
                user="user",
                max_tokens=100,
                stage_type="eval",
                adapter_factory=adapter_factory,
            )

    jobs = dead_letter_jobs()
    assert jobs[-1]["operation"] == "eval.score"
    assert jobs[-1]["provider"] == "google"
    assert jobs[-1]["batch"] is True
    assert "provider down" in jobs[-1]["error"]
