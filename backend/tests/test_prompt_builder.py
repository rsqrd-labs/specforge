from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from models import Stage, Workspace
from services.pipeline.prompt_builder import _MAX_UPSTREAM_CHARS, build_prompt


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self._store[key] = value


class _FakeResult:
    def __init__(self, stage: Stage | None) -> None:
        self._stage = stage

    def scalar_one_or_none(self) -> Stage | None:
        return self._stage


class _FakeDB:
    def __init__(self, stages: dict[str, Stage] | None = None) -> None:
        self._stages = stages or {}

    async def execute(self, statement: Any) -> _FakeResult:
        for stage in self._stages.values():
            return _FakeResult(stage)
        return _FakeResult(None)


def _make_workspace(problem: str = "A" * 60) -> Workspace:
    w = Workspace(
        id=uuid4(),
        user_id=uuid4(),
        name="WS",
        problem_statement=problem,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    w.stages = []
    return w


@pytest.mark.asyncio
async def test_build_prompt_spec_contains_problem_statement() -> None:
    workspace = _make_workspace("Build a todo app with persistence")
    redis = _FakeRedis()
    _, user_prompt = await build_prompt("spec", workspace, _FakeDB(), redis)
    assert "Build a todo app with persistence" in user_prompt


@pytest.mark.asyncio
async def test_build_prompt_plan_contains_spec_content() -> None:
    workspace = _make_workspace()
    spec_stage = Stage(
        id=uuid4(),
        workspace_id=workspace.id,
        type="spec",
        status="finalised",
        content="<spec_content>My spec</spec_content>",
        current_version=1,
        review_gate_acknowledged=False,
    )
    stages = {"spec": spec_stage}
    redis = _FakeRedis()
    _, user_prompt = await build_prompt("plan", workspace, _FakeDB(stages), redis)
    assert "<spec_content>" in user_prompt


@pytest.mark.asyncio
async def test_build_prompt_truncates_long_upstream_content() -> None:
    workspace = _make_workspace()
    long_content = "x" * (_MAX_UPSTREAM_CHARS + 1000)
    spec_stage = Stage(
        id=uuid4(),
        workspace_id=workspace.id,
        type="spec",
        status="finalised",
        content=long_content,
        current_version=1,
        review_gate_acknowledged=False,
    )
    redis = _FakeRedis()
    _, user_prompt = await build_prompt(
        "plan", workspace, _FakeDB({"spec": spec_stage}), redis
    )
    total_spec_in_prompt = user_prompt.count("x")
    assert total_spec_in_prompt <= _MAX_UPSTREAM_CHARS
