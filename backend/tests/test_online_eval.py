from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from models import EvalResult
from services.evals.online_eval import run_eval, run_eval_background


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
        self.calls: list[dict[str, Any]] = []

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _FakeSessionContext:
    def __init__(self, db: _FakeDB) -> None:
        self.db = db
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> _FakeDB:
        self.entered = True
        return self.db

    async def __aexit__(self, *args: Any) -> None:
        self.exited = True


@pytest.mark.asyncio
async def test_run_eval_returns_eval_result_with_scores() -> None:
    db = _FakeDB()
    judge_response = (
        '{"scores": {"goal_alignment": 90, "requirements_coverage": 80, '
        '"specificity_testability": 70, "user_flow_coverage": 60, '
        '"non_functional_coverage": 50, "traceability": 65, '
        '"feasibility": 75, "clarity": 70}, "coverage_percent": null, '
        '"uncovered_reqs": [], "tasks_without_ref": [], "risks": []}'
    )
    judge = _FakeJudge(judge_response)

    with patch("services.evals.online_eval.get_llm", return_value=judge):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    assert result.overall_score == 71
    assert result.completeness == 64
    assert result.clarity == 70
    assert result.flagged is False
    assert db._committed
    assert "Do not default to 85" in judge.calls[0]["user"]


@pytest.mark.asyncio
async def test_run_eval_computes_overall_from_rubric_scores_not_claimed_score() -> None:
    db = _FakeDB()
    judge_response = (
        '{"overall_score": 85, "scores": {"goal_alignment": 40, '
        '"requirements_coverage": 50, "specificity_testability": 60, '
        '"user_flow_coverage": 70, "non_functional_coverage": 80, '
        '"traceability": 90, "feasibility": 100, "clarity": 50}, '
        '"coverage_percent": null, "uncovered_reqs": [], '
        '"tasks_without_ref": [], "risks": ["missing acceptance criteria"]}'
    )

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(judge_response),
    ):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    assert result.overall_score == 58
    assert result.overall_score != 85
    assert result.clarity == 50


@pytest.mark.asyncio
async def test_run_eval_scores_langfuse_generation_when_id_present() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )
        await asyncio.sleep(0)

    assert result is not None
    langfuse_client.score_generation.assert_awaited_once_with(
        generation_id="g-123", name="overall", value=85.0
    )
    langfuse_client.add_to_dataset.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_eval_skips_langfuse_score_without_generation_id() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    langfuse_client.score_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_eval_returns_result_when_langfuse_score_fails() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock(
        side_effect=RuntimeError("langfuse down")
    )
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )
        await asyncio.sleep(0)

    assert result is not None
    assert result.overall_score == 85
    assert db._committed
    langfuse_client.add_to_dataset.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "expected_dataset"),
    [
        (90, "high_quality_generations"),
        (59, "low_quality_generations"),
        (60, None),
        (84, None),
    ],
)
async def test_run_eval_collects_datasets_at_score_thresholds(
    score: int, expected_dataset: str | None
) -> None:
    db = _FakeDB()
    judge_response = f'{{"overall_score": {score}, "completeness": 90, "clarity": 80}}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )
        await asyncio.sleep(0)

    assert result is not None
    if expected_dataset is None:
        langfuse_client.add_to_dataset.assert_not_awaited()
    else:
        langfuse_client.add_to_dataset.assert_awaited_once()
        kwargs = langfuse_client.add_to_dataset.await_args.kwargs
        assert kwargs["dataset_name"] == expected_dataset
        assert kwargs["source_observation_id"] == "g-123"


@pytest.mark.asyncio
async def test_run_eval_dataset_write_is_fire_and_forget() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 90, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    fake_task = MagicMock()

    def fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
        patch("services.evals.online_eval.asyncio.create_task", fake_create_task),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )

    assert result is not None
    fake_task.add_done_callback.assert_called_once()


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
async def test_run_eval_extracts_json_from_fenced_judge_response() -> None:
    db = _FakeDB()
    judge_response = (
        "Here is the evaluation:\n"
        "```json\n"
        '{"scores": {"requirements_coverage": 80, '
        '"specificity_testability": 75, "traceability": 70, "clarity": 85}, '
        '"coverage_percent": 78, "uncovered_reqs": ["FR-009"], '
        '"tasks_without_ref": [], "risks": []}'
        "\n```"
    )

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(judge_response),
    ):
        result = await run_eval(uuid4(), "harness", "harness content", "spec", db)

    assert result is not None
    assert result.coverage_percent == 78
    assert result.overall_score == 77
    assert result.flagged is True
    assert db._committed


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
async def test_run_eval_retries_tasks_with_compact_prompt_after_timeout() -> None:
    db = _FakeDB()
    success = SimpleNamespace(
        output='{"overall_score": 72, "completeness": 76, "clarity": 80}'
    )
    content = "Task details.\n" + ("x" * 30_000)
    context = "Specification and harness.\n" + ("h" * 20_000)

    with patch(
        "services.evals.online_eval.complete_background_llm",
        new_callable=AsyncMock,
        side_effect=[TimeoutError(), success],
    ) as complete_background_llm:
        result = await run_eval(uuid4(), "tasks", content, context, db)

    assert result is not None
    assert result.overall_score == 72
    assert complete_background_llm.await_count == 2
    first_prompt = complete_background_llm.await_args_list[0].kwargs["user"]
    retry_prompt = complete_background_llm.await_args_list[1].kwargs["user"]
    assert "[..." in retry_prompt
    assert len(retry_prompt) < len(first_prompt)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "judge_model"),
    [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-5.4-mini"),
        ("google", "gemini-3.1-flash-lite"),
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


@pytest.mark.asyncio
async def test_run_eval_background_opens_its_own_session() -> None:
    db = _FakeDB()
    context = _FakeSessionContext(db)
    stage_version_id = uuid4()

    with (
        patch("services.evals.online_eval.AsyncSessionLocal", return_value=context),
        patch("services.evals.online_eval.run_eval") as run_eval_mock,
    ):
        run_eval_mock.return_value = None
        result = await run_eval_background(
            stage_version_id,
            "spec",
            "content",
            "",
            "openai",
            "gpt-5.4-mini",
        )

    assert result is None
    assert context.entered is True
    assert context.exited is True
    run_eval_mock.assert_awaited_once_with(
        stage_version_id,
        "spec",
        "content",
        "",
        db,
        "openai",
        "gpt-5.4-mini",
        None,
        harness_content=None,
    )
