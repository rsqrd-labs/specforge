"""Unit tests for the Storyboard source builder (Phase 20 — T-252).

Covers: finalised-only gating before any credit charge, immutable StageVersion
pinning (all four version ids), excerpt bounding + secret/PII scrubbing, and the
structured missing-section finding. Uses a fake DB so the pure extraction and the
gating logic are exercised without a live database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from models import Stage, StageVersion, Workspace
from services.pipeline.storyboard_source import (
    MissingSourceSection,
    StoryboardStagesNotFinalisedError,
    StoryboardWorkspaceNotFoundError,
    _bound,
    _extract_excerpts,
    _scrub,
    build_storyboard_source,
)

_USER_ID = uuid4()
_WORKSPACE_ID = uuid4()


# ---------------------------------------------------------------------------
# Sample finalised artifacts
# ---------------------------------------------------------------------------

_SPEC_MD = """# Product Spec

## Overview
SpecForge turns an idea into a structured engineering spec. The product helps
teams move from a problem statement to a shippable plan.

## Requirements
- R1 must do X
"""

_PLAN_MD = """# Engineering Plan

## Architecture
A FastAPI backend talks to PostgreSQL and Redis. The frontend is a React SPA.

### Data flow
Requests stream over SSE.

## Security Architecture
CSRF tokens guard mutations; keys are Fernet-encrypted at rest.

## Capacity Model
Sized for 10k DAU and 50 RPS peak with headroom.

## STRIDE
Spoofing mitigated by OAuth; tampering by CSRF.

## SLO
99.9% availability target with a monthly error budget.

## FMEA
Failure mode: provider outage -> circuit breaker opens.
"""

_HARNESS_MD = """# Harness

## Coverage
Requirements coverage is tracked per task; 42 tests map to 40 requirements.
"""

_TASKS_MD = """# Tasks

## Must-have
- T-1 MUST implement auth
- T-2 MUST implement billing
"""

_ARTIFACTS = {
    "spec": _SPEC_MD,
    "plan": _PLAN_MD,
    "harness": _HARNESS_MD,
    "tasks": _TASKS_MD,
}


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> "_Result":
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    """Dispatches on the queried entity to return workspace / stages / versions."""

    def __init__(
        self,
        workspace: Workspace | None,
        stages: list[Stage],
        versions: list[StageVersion],
    ) -> None:
        self._workspace = workspace
        self._stages = stages
        self._versions = versions

    async def execute(self, statement: Any) -> _Result:
        entity = statement.column_descriptions[0]["entity"]
        if entity is Workspace:
            return _Result([self._workspace] if self._workspace else [])
        if entity is Stage:
            return _Result(list(self._stages))
        if entity is StageVersion:
            return _Result(list(self._versions))
        raise AssertionError(f"unexpected query entity: {entity}")


def _workspace() -> Workspace:
    return Workspace(
        id=_WORKSPACE_ID,
        user_id=_USER_ID,
        name="SpecForge",
        problem_statement="Build a spec generator. Contact me at owner@example.com.",
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )


def _stage(
    stage_type: str, *, status: str = "finalised", current_version: int = 3
) -> Stage:
    return Stage(
        id=uuid4(),
        workspace_id=_WORKSPACE_ID,
        type=stage_type,
        content="DRAFT CONTENT — must never be used",
        status=status,
        current_version=current_version,
    )


def _version(stage: Stage, content: str, *, version: int | None = None) -> StageVersion:
    return StageVersion(
        id=uuid4(),
        stage_id=stage.id,
        version=stage.current_version if version is None else version,
        content=content,
        created_by="ai",
        created_at=datetime.now(UTC),
    )


def _finalised_fixture() -> tuple[_FakeDB, dict[str, Stage], dict[str, StageVersion]]:
    stages = {t: _stage(t) for t in ("spec", "plan", "harness", "tasks")}
    versions = {t: _version(stages[t], _ARTIFACTS[t]) for t in stages}
    # Add an older, stale version per stage to prove current_version pinning.
    older = [_version(stages[t], "OLD STALE CONTENT", version=1) for t in stages]
    db = _FakeDB(_workspace(), list(stages.values()), list(versions.values()) + older)
    return db, stages, versions


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_bound_caps_excerpt_at_1200_chars() -> None:
    long_text = "word " * 600  # 3000 chars
    bounded = _bound(long_text)
    assert len(bounded) <= 1200


def test_scrub_removes_email_and_tokens() -> None:
    raw = (
        "Reach me at alice@example.com with Authorization: Bearer abcDEF123456 "
        "and api key sk-livedeadbeefdeadbeef0000 plus "
        "eyJhbGciOi.eyJzdWIiOiJ123.sigVALUE_here"
    )
    scrubbed = _scrub(raw)
    assert "alice@example.com" not in scrubbed
    assert "sk-livedeadbeefdeadbeef0000" not in scrubbed
    assert "eyJhbGciOi.eyJzdWIiOiJ123.sigVALUE_here" not in scrubbed
    assert "Bearer abcDEF123456" not in scrubbed


def test_extract_excerpts_finds_all_priority_sections() -> None:
    excerpts, missing = _extract_excerpts(_ARTIFACTS)  # type: ignore[arg-type]
    assert missing == []
    for source_id in (
        "SPEC:overview",
        "PLAN:architecture",
        "PLAN:security-architecture",
        "PLAN:capacity-model",
        "PLAN:stride",
        "PLAN:slo",
        "PLAN:fmea",
        "HARNESS:coverage",
        "TASKS:must",
    ):
        assert source_id in excerpts, f"missing {source_id}"
        assert len(excerpts[source_id].excerpt) <= 1200


def test_architecture_excerpt_is_not_the_security_section() -> None:
    excerpts, _ = _extract_excerpts(_ARTIFACTS)  # type: ignore[arg-type]
    arch = excerpts["PLAN:architecture"]
    assert arch.heading.lower() == "architecture"
    assert "FastAPI backend" in arch.excerpt
    # The dedicated security excerpt is distinct.
    assert (
        excerpts["PLAN:security-architecture"].heading.lower()
        == "security architecture"
    )


def test_missing_section_recorded_not_invented() -> None:
    artifacts = dict(_ARTIFACTS)
    artifacts["plan"] = "# Plan\n\n## Architecture\nOnly architecture here.\n"
    excerpts, missing = _extract_excerpts(artifacts)  # type: ignore[arg-type]
    missing_ids = {m.source_id for m in missing}
    assert "PLAN:stride" in missing_ids
    assert "PLAN:fmea" in missing_ids
    assert all(isinstance(m, MissingSourceSection) for m in missing)
    assert "PLAN:stride" not in excerpts


def test_extract_excerpts_handles_common_plan_heading_variants() -> None:
    artifacts = dict(_ARTIFACTS)
    artifacts["plan"] = """# Plan

## System Design
React, FastAPI, PostgreSQL, Redis, and provider integrations.

## Security Architecture
CSRF and encrypted provider credentials.

## Scalability and Performance
Queueing, cache boundaries, and rate limits keep generation responsive.

## Error Handling and Recovery
Provider failures are retried, refunded, and surfaced without corrupting state.

## Observability and Operations
SLOs are monitored through structured metrics and failure alerts.
"""
    artifacts["tasks"] = """# Tasks

## Phase 1: Infrastructure and Foundations
- T-001 ship the database, cache, and API foundations.
"""

    excerpts, missing = _extract_excerpts(artifacts)  # type: ignore[arg-type]
    missing_ids = {item.source_id for item in missing}

    assert "PLAN:capacity-model" in excerpts
    assert "PLAN:fmea" in excerpts
    assert "PLAN:slo" in excerpts
    assert "TASKS:must" in excerpts
    assert "PLAN:capacity-model" not in missing_ids
    assert "TASKS:must" not in missing_ids


# ---------------------------------------------------------------------------
# build_storyboard_source — gating + pinning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_requires_all_stages_finalised() -> None:
    """Non-finalised stages block generation before any credit deduction."""
    stages = {t: _stage(t) for t in ("spec", "plan", "harness", "tasks")}
    stages["harness"].status = "draft"
    versions = [_version(stages[t], _ARTIFACTS[t]) for t in stages]
    db = _FakeDB(_workspace(), list(stages.values()), versions)

    with pytest.raises(StoryboardStagesNotFinalisedError) as exc:
        await build_storyboard_source(db, _WORKSPACE_ID, _USER_ID)
    assert exc.value.not_ready == {"harness": "draft"}


@pytest.mark.asyncio
async def test_build_blocks_when_a_stage_is_missing() -> None:
    stages = {t: _stage(t) for t in ("spec", "plan", "tasks")}  # no harness
    versions = [_version(stages[t], _ARTIFACTS[t]) for t in stages]
    db = _FakeDB(_workspace(), list(stages.values()), versions)

    with pytest.raises(StoryboardStagesNotFinalisedError) as exc:
        await build_storyboard_source(db, _WORKSPACE_ID, _USER_ID)
    assert exc.value.not_ready.get("harness") == "missing"


@pytest.mark.asyncio
async def test_build_unknown_workspace_raises() -> None:
    db = _FakeDB(None, [], [])
    with pytest.raises(StoryboardWorkspaceNotFoundError):
        await build_storyboard_source(db, _WORKSPACE_ID, _USER_ID)


@pytest.mark.asyncio
async def test_storyboard_source_map_contains_only_finalised_versions() -> None:
    db, stages, versions = _finalised_fixture()
    pkg = await build_storyboard_source(db, _WORKSPACE_ID, _USER_ID)

    assert set(pkg.stage_versions.keys()) == {"spec", "plan", "harness", "tasks"}
    for stage_type in ("spec", "plan", "harness", "tasks"):
        # Pins the current_version row, never the stale v1.
        assert pkg.stage_versions[stage_type] == versions[stage_type].id
    # source_stage_version_ids is the stringified, JSON-serialisable map.
    assert pkg.source_stage_version_ids == {
        t: str(versions[t].id) for t in ("spec", "plan", "harness", "tasks")
    }


@pytest.mark.asyncio
async def test_build_scrubs_problem_statement_and_excludes_draft() -> None:
    db, _stages, _versions = _finalised_fixture()
    pkg = await build_storyboard_source(db, _WORKSPACE_ID, _USER_ID)

    assert "owner@example.com" not in pkg.problem_statement
    # Artifacts come from the finalised StageVersion, never Stage.content.
    for content in pkg.artifacts.values():
        assert "DRAFT CONTENT" not in content
        assert "OLD STALE CONTENT" not in content
    assert pkg.provider == "anthropic"
    assert pkg.model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_build_is_deterministic() -> None:
    db1, _s1, _v1 = _finalised_fixture()
    pkg1 = await build_storyboard_source(db1, _WORKSPACE_ID, _USER_ID)
    # Re-run against an identical fixture: excerpts must be byte-identical.
    db2 = _FakeDB(
        _workspace(),
        list(_s1.values()),
        # same version rows
        [v for v in _v1.values()],
    )
    pkg2 = await build_storyboard_source(db2, _WORKSPACE_ID, _USER_ID)
    assert {k: v.excerpt for k, v in pkg1.excerpts.items()} == {
        k: v.excerpt for k, v in pkg2.excerpts.items()
    }
