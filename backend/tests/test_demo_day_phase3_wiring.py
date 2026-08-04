"""Demo Day mode — Phase 3 wiring tests (persistence and staleness).

The pure linter (C1–C5) is covered by ``test_demo_day_phase3.py``. These tests
cover the Phase 3 *wiring*: workspace-level verdict persistence and staleness
re-run, advisory-only detached verification, response surfacing, and the export
bundle's ``CONSTRUCTION_REPORT.md``.
"""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from schemas.workspace import WorkspaceResponse
from services.pipeline import construction_verdict_service
from services.pipeline.demo_day_plan_linter import (
    DEMO_DAY_DEFAULT_BUDGET_MINUTES,
    STAGE_TYPES,
    is_verdict_stale,
)

# ---------------------------------------------------------------------------
# Fixtures: a golden, internally-consistent package (mirrors test_demo_day_phase3)
# ---------------------------------------------------------------------------

_SPEC = """# SPEC

## Acceptance Criteria

- AC-001: POST /shorten returns a short code.
- AC-002: GET /{code} redirects.
"""

_HARNESS = """# HARNESS

## Requirement-to-Test Matrix

| ID | Test file |
| --- | --- |
| AC-001 | `tests/test_shorten.py` |
| AC-002 | `tests/e2e/test_smoke.py` |

## End-to-End Smoke Test

The unmockable test `tests/e2e/test_smoke.py` drives the journey.

## File Tree

```
tests/test_shorten.py
tests/e2e/test_smoke.py
```
"""

_TASKS = """# TASKS

## Tasks

### T-001: Skeleton

**Spec refs:** AC-001
**Harness refs:** `tests/test_shorten.py`
**Estimated minutes:** 60
**Precondition:** none

### T-002: Smoke

**Spec refs:** AC-002
**Harness refs:** `tests/e2e/test_smoke.py`
**Estimated minutes:** 60
**Precondition:** T-001
"""


def _stage(stage_type: str, content: str, version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        type=stage_type, content=content, current_version=version, status="finalised"
    )


def _stage_map(*, versions: dict[str, int] | None = None) -> dict[str, Any]:
    versions = versions or {}
    contents = {"spec": _SPEC, "plan": "# PLAN", "harness": _HARNESS, "tasks": _TASKS}
    return {t: _stage(t, contents[t], versions.get(t, 1)) for t in STAGE_TYPES}


def _ws(
    *, mode="demo_day", verdict=None, budget=None, restricted_environment=False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        mode=mode,
        time_budget_minutes=budget,
        construction_verdict=verdict,
        restricted_environment=restricted_environment,
    )


class _FakeSession:
    """Minimal async session: tracks commits, supports rollback (fail-open path)."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# is_verdict_stale
# ---------------------------------------------------------------------------


def test_stale_when_no_verdict() -> None:
    assert is_verdict_stale(None, {"spec": 1, "plan": 1, "harness": 1, "tasks": 1})
    assert is_verdict_stale({}, {"spec": 1})


def test_not_stale_when_versions_match() -> None:
    versions = {"spec": 2, "plan": 1, "harness": 3, "tasks": 1}
    verdict = {"stage_versions": versions}
    assert is_verdict_stale(verdict, versions) is False


def test_stale_when_any_version_moved() -> None:
    stamped = {"spec": 1, "plan": 1, "harness": 1, "tasks": 1}
    live = {"spec": 1, "plan": 1, "harness": 2, "tasks": 1}  # harness refined
    assert is_verdict_stale({"stage_versions": stamped}, live) is True


def test_stale_when_stage_version_missing() -> None:
    # A stamped map lacking a stage is conservatively treated as a mismatch.
    stamped = {"spec": 1, "plan": 1, "harness": 1}
    live = {"spec": 1, "plan": 1, "harness": 1, "tasks": 1}
    assert is_verdict_stale({"stage_versions": stamped}, live) is True


# ---------------------------------------------------------------------------
# construction_verdict_service.compute_verdict / current_versions / all_stages_present
# ---------------------------------------------------------------------------


def test_compute_verdict_stamps_versions_and_passes() -> None:
    stages = _stage_map(versions={"spec": 2, "plan": 1, "harness": 4, "tasks": 3})
    verdict = construction_verdict_service.compute_verdict(_ws(), stages)
    assert verdict.verified is True
    assert verdict.stage_versions == {"spec": 2, "plan": 1, "harness": 4, "tasks": 3}
    assert verdict.time_budget_minutes == DEMO_DAY_DEFAULT_BUDGET_MINUTES


def test_compute_verdict_honours_workspace_budget() -> None:
    verdict = construction_verdict_service.compute_verdict(
        _ws(budget=120), _stage_map()
    )
    assert verdict.time_budget_minutes == 120


def test_compute_verdict_honours_workspace_restricted_environment() -> None:
    docker_plan = "# PLAN\n\nRun `docker compose up` to start the stack.\n"
    stages = _stage_map()
    stages["plan"] = _stage("plan", docker_plan)

    unrestricted = construction_verdict_service.compute_verdict(_ws(), stages)
    assert unrestricted.checks["C8"].passed is True

    restricted = construction_verdict_service.compute_verdict(
        _ws(restricted_environment=True), stages
    )
    assert restricted.checks["C8"].passed is False
    assert restricted.verified is True  # C8 is advisory — never withholds verified


def test_all_stages_present_requires_content() -> None:
    stages = _stage_map()
    assert construction_verdict_service.all_stages_present(stages) is True
    stages["harness"].content = ""
    assert construction_verdict_service.all_stages_present(stages) is False


def test_current_versions_reads_live() -> None:
    stages = _stage_map(versions={"spec": 5, "plan": 1, "harness": 1, "tasks": 2})
    assert construction_verdict_service.current_versions(stages) == {
        "spec": 5,
        "plan": 1,
        "harness": 1,
        "tasks": 2,
    }


# ---------------------------------------------------------------------------
# construction_verdict_service.ensure_fresh_verdict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_now_covers_standard_workspaces() -> None:
    """Standard mode gets a verdict too — it used to be skipped entirely.

    The mode decides WHICH linter runs, not WHETHER one runs: "if you implement
    every task you get a working product" is the same claim in both modes.
    """
    db = _FakeSession()
    ws = _ws(mode="standard")
    result = await construction_verdict_service.ensure_fresh_verdict(
        db, ws, _stage_map()
    )
    assert result is not None
    assert db.commits == 1
    # The standard linter's own check set, not Demo Day's.
    assert result["checks"]["C1"]["name"] == "requirement_coverage"
    # Demo Day's build-time calibration is not a standard-mode concept.
    assert result["estimated_minutes"] is None
    assert result["time_budget_minutes"] is None


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_returns_existing_when_fresh() -> None:
    stages = _stage_map()
    fresh = {
        "verified": True,
        "stage_versions": construction_verdict_service.current_versions(stages),
    }
    ws = _ws(verdict=fresh)
    db = _FakeSession()
    result = await construction_verdict_service.ensure_fresh_verdict(db, ws, stages)
    assert result is fresh  # not recomputed
    assert db.commits == 0


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_recomputes_when_stale() -> None:
    stages = _stage_map(versions={"spec": 1, "plan": 1, "harness": 1, "tasks": 1})
    stale = {
        "verified": False,
        "stage_versions": {"spec": 1, "plan": 1, "harness": 1, "tasks": 0},
    }
    ws = _ws(verdict=stale)
    db = _FakeSession()
    result = await construction_verdict_service.ensure_fresh_verdict(db, ws, stages)
    assert db.commits == 1
    assert result is ws.construction_verdict
    assert result["verified"] is True  # the golden package verifies
    assert result["stage_versions"] == {"spec": 1, "plan": 1, "harness": 1, "tasks": 1}


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_skips_incomplete_package() -> None:
    stages = _stage_map()
    stages["tasks"].content = ""  # tasks not generated yet
    ws = _ws(verdict=None)
    db = _FakeSession()
    result = await construction_verdict_service.ensure_fresh_verdict(db, ws, stages)
    assert result is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_is_fail_open_on_error() -> None:
    # The export-time re-run must never fail a download: a persist error rolls
    # back and returns the last-known verdict rather than raising.
    class _BoomSession(_FakeSession):
        async def commit(self) -> None:
            raise RuntimeError("db down")

    prior = {"verified": False, "stage_versions": {"tasks": 0}}
    ws = _ws(verdict=prior)
    db = _BoomSession()
    result = await construction_verdict_service.ensure_fresh_verdict(
        db, ws, _stage_map()
    )
    assert result is prior  # fell back to the persisted verdict
    assert db.rollbacks == 1


# ---------------------------------------------------------------------------
# WorkspaceResponse surfaces the verdict as an opaque passthrough
# ---------------------------------------------------------------------------


def test_response_passes_through_construction_verdict() -> None:
    verdict = {"verified": True, "checks": {}, "stage_versions": {"tasks": 1}}
    row = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        name="x",
        problem_statement="build a tiny demo for the hackathon today",
        provider="anthropic",
        model="claude-haiku-4-5",
        status="active",
        mode="demo_day",
        target_agent="claude_code",
        time_budget_minutes=240,
        construction_verdict=verdict,
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    resp = WorkspaceResponse.model_validate(row)
    assert resp.construction_verdict == verdict


def test_response_defaults_construction_verdict_to_none() -> None:
    assert WorkspaceResponse.model_fields["construction_verdict"].default is None


# ---------------------------------------------------------------------------
# Export ZIP now ships CONSTRUCTION_REPORT.md from a fresh verdict
# ---------------------------------------------------------------------------


class _ExportFakeDB:
    """Drives build_export: workspace row, then stages; commit is a no-op."""

    def __init__(self, workspace: Any, stages: list[Any]) -> None:
        self._workspace = workspace
        self._stages = stages
        self._calls = 0

    async def execute(self, statement: Any) -> Any:
        self._calls += 1
        result = MagicMock()
        if self._calls == 1:
            result.scalar_one_or_none.return_value = self._workspace
        else:
            result.scalars.return_value = iter(self._stages)
        return result

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:  # pragma: no cover
        pass


@pytest.mark.asyncio
async def test_export_includes_construction_report_from_persisted_verdict() -> None:
    from datetime import UTC, datetime

    from models import Stage, Workspace
    from services.pipeline.export_service import build_export

    uid = uuid4()
    wid = uuid4()
    verdict = {
        "verified": True,
        "checks": {"C1": {"name": "dag_acyclic", "passed": True, "gaps": []}},
        "estimated_minutes": 120,
        "time_budget_minutes": 300,
        "stage_versions": {"spec": 1, "plan": 1, "harness": 1, "tasks": 1},
    }
    ws = Workspace(
        id=wid,
        user_id=uid,
        name="Demo",
        problem_statement="build a tiny url shortener for the demo",
        provider="anthropic",
        model="claude-haiku-4-5",
        status="active",
        mode="demo_day",
        target_agent="claude_code",
        construction_verdict=verdict,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    def _st(t: str, content: str) -> Stage:
        return Stage(
            id=uuid4(),
            workspace_id=wid,
            type=t,
            status="finalised",
            content=content,
            current_version=1,
            review_gate_acknowledged=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    stages = [
        _st("spec", _SPEC),
        _st("plan", "# PLAN\n\n## Technology Stack\n\nSQLite.\n"),
        _st("harness", _HARNESS),
        _st("tasks", _TASKS),
    ]
    db = _ExportFakeDB(ws, stages)
    result = await build_export(wid, uid, db)
    zf = zipfile.ZipFile(io.BytesIO(result))
    names = zf.namelist()
    assert "CONSTRUCTION_REPORT.md" in names
    assert "CLAUDE.md" in names
    report = zf.read("CONSTRUCTION_REPORT.md").decode()
    # The persisted verdict matched the live versions, so it ships as-is.
    assert "Construction-verified" in report


# ---------------------------------------------------------------------------
# Detached verifier: advisory-only, never an out-of-band LLM mutation
# ---------------------------------------------------------------------------


class _DispatchSession:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "_DispatchSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1


def _dispatch_workspace(stages: dict[str, Any], *, verdict=None):
    return SimpleNamespace(
        id=uuid4(),
        mode="demo_day",
        time_budget_minutes=300,
        construction_verdict=verdict,
        stages=list(stages.values()),
    )


async def _run_dispatch(monkeypatch, manager, workspace, *, tasks_version=1):
    import database

    session = _DispatchSession()
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: session)

    async def _load_workspace(_workspace_id, _db):
        return workspace

    monkeypatch.setattr(manager, "_load_workspace", _load_workspace)
    await manager._dispatch_construction_verifier(
        workspace_id=workspace.id,
        tasks_version=tasks_version,
    )
    return session


@pytest.mark.asyncio
async def test_dispatch_verified_package_persists_verdict(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    stages = _stage_map()
    workspace = _dispatch_workspace(stages)
    session = await _run_dispatch(monkeypatch, StageManager(), workspace)

    assert workspace.construction_verdict["verified"] is True
    assert session.commits == 1


@pytest.mark.asyncio
async def test_dispatch_failing_package_never_regenerates_or_mutates(
    monkeypatch,
) -> None:
    import services.pipeline.stage_manager as stage_manager_module
    from services.pipeline.stage_manager import StageManager

    stages = _stage_map()
    tasks = stages["tasks"]
    tasks.content = _TASKS.replace("tests/test_shorten.py", "tests/ghost.py")
    original_content = tasks.content
    original_version = tasks.current_version
    workspace = _dispatch_workspace(stages)

    def _unexpected_llm_call(*_args, **_kwargs):
        raise AssertionError("construction verification must remain zero-LLM")

    monkeypatch.setattr(stage_manager_module, "get_llm", _unexpected_llm_call)
    session = await _run_dispatch(monkeypatch, StageManager(), workspace)

    assert workspace.construction_verdict["verified"] is False
    assert tasks.content == original_content
    assert tasks.current_version == original_version
    assert session.commits == 1


@pytest.mark.asyncio
async def test_dispatch_stale_tasks_version_does_not_persist(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    stages = _stage_map(versions={"spec": 1, "plan": 1, "harness": 1, "tasks": 3})
    workspace = _dispatch_workspace(stages)
    session = await _run_dispatch(
        monkeypatch,
        StageManager(),
        workspace,
        tasks_version=1,
    )

    assert workspace.construction_verdict is None
    assert session.commits == 0


# ---------------------------------------------------------------------------
# F7: async construction-linter offload remains byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_verdict_async_matches_sync_on_pool_path(monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    stages = _stage_map(versions={"spec": 2, "plan": 1, "harness": 4, "tasks": 3})
    sync_verdict = construction_verdict_service.compute_verdict(_ws(), stages)
    async_verdict = await construction_verdict_service.compute_verdict_async(
        _ws(), stages
    )
    assert async_verdict.to_dict() == sync_verdict.to_dict()
