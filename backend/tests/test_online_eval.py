from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from models import EvalResult
from services.evals.online_eval import run_eval


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self._committed = False

    def add(self, instance: Any) -> None:
        if isinstance(instance, EvalResult) and not hasattr(instance, "id"):
            instance.id = uuid4()
        self.added.append(instance)

    async def commit(self) -> None:
        self._committed = True

    async def refresh(self, instance: Any) -> None:
        if not hasattr(instance, "id") or instance.id is None:
            instance.id = uuid4()


class _FakeJudge:
    def __init__(self, response: str | Exception) -> None:
        self.response = response

    async def complete(self, *args: Any, **kwargs: Any) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_run_eval_returns_eval_result_with_scores() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    assert result.overall_score == 85
    assert result.completeness == 90
    assert result.clarity == 80
    assert result.flagged is False
    assert db._committed


@pytest.mark.asyncio
async def test_run_eval_harness_flags_when_coverage_below_80() -> None:
    db = _FakeDB()
    judge_response = (
        '{"overall_score": 60, "completeness": 60, "clarity": 70, '
        '"coverage_percent": 65, "uncovered_reqs": ["auth", "export"]}'
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(uuid4(), "harness", "harness content", "spec", db)

    assert result is not None
    assert result.coverage_percent == 65
    assert result.flagged is True
    assert "auth" in result.uncovered_reqs


@pytest.mark.asyncio
async def test_run_eval_json_parse_failure_returns_none() -> None:
    db = _FakeDB()

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge("not valid json at all"),
    ):
        result = await run_eval(uuid4(), "spec", "content", "", db)

    assert result is None
    assert not db._committed


@pytest.mark.asyncio
async def test_run_eval_judge_exception_returns_none() -> None:
    db = _FakeDB()

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(Exception("network error")),
    ):
        result = await run_eval(uuid4(), "spec", "content", "", db)

    assert result is None
    assert not db._committed


@pytest.mark.asyncio
async def test_run_eval_tasks_flags_tasks_without_ref() -> None:
    db = _FakeDB()
    judge_response = (
        '{"overall_score": 70, "completeness": 75, "clarity": 80, '
        '"tasks_without_ref": [{"task": "T-01", "reason": "no test ref"}]}'
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(uuid4(), "tasks", "tasks content", "spec", db)

    assert result is not None
    assert result.flagged is True
    assert len(result.tasks_without_ref) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "judge_model"),
    [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-4o-mini"),
        ("google", "gemini-1.5-flash"),
    ],
)
async def test_run_eval_uses_provider_specific_judge_model(
    provider: str, judge_model: str
) -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(judge_response),
    ) as get_llm:
        await run_eval(uuid4(), "spec", "content", "", db, provider)

    get_llm.assert_called_once_with(provider, judge_model)
