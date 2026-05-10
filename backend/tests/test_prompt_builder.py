from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from prompts import harness, plan, spec, tasks
from prompts.base import (
    ASDD_PROMPT_VERSION,
    ASDD_METHODOLOGY_OVERVIEW,
    PROFESSIONAL_OUTPUT_RULES,
    SECURITY_AND_PRIVACY_RULES,
    STAGE_PROMPT_VERSIONS,
)
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


def _make_workspace(
    problem: str = (
        "I want to build a task management web app for teams to create projects, "
        "assign tasks, track status, and notify users."
    ),
) -> Workspace:
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
    assert '<untrusted_content source="problem_statement">' in user_prompt
    assert "BEGIN_UNTRUSTED_CONTENT:problem_statement" in user_prompt
    assert "END_UNTRUSTED_CONTENT:problem_statement" in user_prompt


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
    assert '<untrusted_content source="spec_content">' in user_prompt
    assert "BEGIN_UNTRUSTED_CONTENT:spec_content" in user_prompt
    assert "END_UNTRUSTED_CONTENT:spec_content" in user_prompt


@pytest.mark.asyncio
async def test_build_prompt_truncates_long_upstream_content() -> None:
    workspace = _make_workspace()
    long_content = "\n".join(
        [
            "# Requirements",
            "FR-001 The system stores projects.",
            "SEC-001 The system validates prompt injection.",
            "GET /projects",
            "x" * (_MAX_UPSTREAM_CHARS + 1000),
        ]
    )
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
    assert "## Downstream Constraints" in user_prompt
    assert "FR-001" in user_prompt
    assert "SEC-001" in user_prompt
    assert "GET /projects" in user_prompt
    assert "x" * 1000 not in user_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage_name", "module"),
    [
        ("spec", spec),
        ("plan", plan),
        ("harness", harness),
        ("tasks", tasks),
    ],
)
async def test_stage_system_prompt_has_stable_static_prefix(
    stage_name: str,
    module,
) -> None:
    system_prompt = await module.get_system_prompt()

    assert STAGE_PROMPT_VERSIONS[stage_name].startswith(ASDD_PROMPT_VERSION)
    assert ASDD_METHODOLOGY_OVERVIEW in system_prompt
    assert SECURITY_AND_PRIVACY_RULES in system_prompt
    assert PROFESSIONAL_OUTPUT_RULES in system_prompt
    assert system_prompt.index(ASDD_METHODOLOGY_OVERVIEW) < system_prompt.index(
        SECURITY_AND_PRIVACY_RULES
    )
    assert system_prompt.index(SECURITY_AND_PRIVACY_RULES) < system_prompt.index(
        PROFESSIONAL_OUTPUT_RULES
    )


def test_dynamic_content_stays_in_user_prompts() -> None:
    problem = "Build a provider-agnostic cost dashboard for LLM usage."
    spec_text = "SPEC_DYNAMIC_CONTENT"
    plan_text = "PLAN_DYNAMIC_CONTENT"
    harness_text = "HARNESS_DYNAMIC_CONTENT"

    assert problem in spec.build_user_prompt({"problem_statement": problem})
    assert problem not in spec.SYSTEM_PROMPT

    plan_user = plan.build_user_prompt({"spec": spec_text})
    assert spec_text in plan_user
    assert spec_text not in plan.SYSTEM_PROMPT

    harness_user = harness.build_user_prompt({"spec": spec_text, "plan": plan_text})
    assert spec_text in harness_user
    assert plan_text in harness_user
    assert spec_text not in harness.SYSTEM_PROMPT
    assert plan_text not in harness.SYSTEM_PROMPT

    tasks_user = tasks.build_user_prompt(
        {"spec": spec_text, "plan": plan_text, "harness": harness_text}
    )
    assert spec_text in tasks_user
    assert plan_text in tasks_user
    assert harness_text in tasks_user
    assert harness_text not in tasks.SYSTEM_PROMPT
