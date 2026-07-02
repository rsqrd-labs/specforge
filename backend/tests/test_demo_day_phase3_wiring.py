"""Demo Day mode — Phase 3 wiring tests (persistence, staleness, regen routing).

The pure linter (C1–C5) is covered by ``test_demo_day_phase3.py``. These tests
cover the Phase 3 *wiring*: the workspace-level verdict persistence + staleness
re-run (``demo_day_verdict``), the regenerate-ownership routing helpers
(``stage_manager``), the response surfacing, and that the export bundle now ships
``CONSTRUCTION_REPORT.md``.
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
from services.pipeline import demo_day_verdict
from services.pipeline.demo_day_plan_linter import (
    DEMO_DAY_DEFAULT_BUDGET_MINUTES,
    STAGE_TYPES,
    CheckResult,
    ConstructionVerdict,
    is_verdict_stale,
)
from services.pipeline.stage_manager import (
    _failing_verdict_checks,
    _verdict_is_tasks_regenerable,
    _verdict_regen_findings,
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


def _ws(*, mode="demo_day", verdict=None, budget=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        mode=mode,
        time_budget_minutes=budget,
        construction_verdict=verdict,
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
# demo_day_verdict.compute_verdict / current_versions / all_stages_present
# ---------------------------------------------------------------------------


def test_compute_verdict_stamps_versions_and_passes() -> None:
    stages = _stage_map(versions={"spec": 2, "plan": 1, "harness": 4, "tasks": 3})
    verdict = demo_day_verdict.compute_verdict(_ws(), stages)
    assert verdict.verified is True
    assert verdict.stage_versions == {"spec": 2, "plan": 1, "harness": 4, "tasks": 3}
    assert verdict.time_budget_minutes == DEMO_DAY_DEFAULT_BUDGET_MINUTES
    assert verdict.regen_attempted is False


def test_compute_verdict_carries_regen_attempted() -> None:
    verdict = demo_day_verdict.compute_verdict(
        _ws(), _stage_map(), regen_attempted=True
    )
    assert verdict.regen_attempted is True


def test_compute_verdict_honours_workspace_budget() -> None:
    verdict = demo_day_verdict.compute_verdict(_ws(budget=120), _stage_map())
    assert verdict.time_budget_minutes == 120


def test_all_stages_present_requires_content() -> None:
    stages = _stage_map()
    assert demo_day_verdict.all_stages_present(stages) is True
    stages["harness"].content = ""
    assert demo_day_verdict.all_stages_present(stages) is False


def test_current_versions_reads_live() -> None:
    stages = _stage_map(versions={"spec": 5, "plan": 1, "harness": 1, "tasks": 2})
    assert demo_day_verdict.current_versions(stages) == {
        "spec": 5,
        "plan": 1,
        "harness": 1,
        "tasks": 2,
    }


# ---------------------------------------------------------------------------
# demo_day_verdict.ensure_fresh_verdict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_skips_standard_workspace() -> None:
    db = _FakeSession()
    result = await demo_day_verdict.ensure_fresh_verdict(
        db, _ws(mode="standard"), _stage_map()
    )
    assert result is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_returns_existing_when_fresh() -> None:
    stages = _stage_map()
    fresh = {
        "verified": True,
        "stage_versions": demo_day_verdict.current_versions(stages),
        "regen_attempted": False,
    }
    ws = _ws(verdict=fresh)
    db = _FakeSession()
    result = await demo_day_verdict.ensure_fresh_verdict(db, ws, stages)
    assert result is fresh  # not recomputed
    assert db.commits == 0


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_recomputes_when_stale() -> None:
    stages = _stage_map(versions={"spec": 1, "plan": 1, "harness": 1, "tasks": 1})
    stale = {
        "verified": False,
        "stage_versions": {"spec": 1, "plan": 1, "harness": 1, "tasks": 0},
        "regen_attempted": True,
    }
    ws = _ws(verdict=stale)
    db = _FakeSession()
    result = await demo_day_verdict.ensure_fresh_verdict(db, ws, stages)
    assert db.commits == 1
    assert result is ws.construction_verdict
    assert result["verified"] is True  # the golden package verifies
    assert result["stage_versions"] == {"spec": 1, "plan": 1, "harness": 1, "tasks": 1}
    # The single funded-regen window is never reopened by a staleness re-run.
    assert result["regen_attempted"] is True


@pytest.mark.asyncio
async def test_ensure_fresh_verdict_skips_incomplete_package() -> None:
    stages = _stage_map()
    stages["tasks"].content = ""  # tasks not generated yet
    ws = _ws(verdict=None)
    db = _FakeSession()
    result = await demo_day_verdict.ensure_fresh_verdict(db, ws, stages)
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
    result = await demo_day_verdict.ensure_fresh_verdict(db, ws, _stage_map())
    assert result is prior  # fell back to the persisted verdict
    assert db.rollbacks == 1


# ---------------------------------------------------------------------------
# Regenerate ownership routing (stage_manager helpers)
# ---------------------------------------------------------------------------


def _mk_verdict(states: dict[str, bool], gaps: dict[str, list[str]] | None = None):
    gaps = gaps or {}
    names = {
        "C1": "dag_acyclic",
        "C2": "task_to_test",
        "C3": "ac_to_test",
        "C4": "e2e_reachable",
        "C5": "time_budget",
    }
    checks = {
        cid: CheckResult(names[cid], passed, gaps.get(cid, [] if passed else ["gap"]))
        for cid, passed in states.items()
    }
    verified = all(checks[c].passed for c in ("C1", "C2", "C3", "C4") if c in checks)
    return ConstructionVerdict(
        verified=verified,
        checks=checks,
        estimated_minutes=None,
        time_budget_minutes=300,
    )


def test_tasks_owned_gaps_are_regenerable() -> None:
    verdict = _mk_verdict(
        {"C1": False, "C2": False, "C3": True, "C4": True, "C5": True}
    )
    assert _failing_verdict_checks(verdict) == {"C1", "C2"}
    assert _verdict_is_tasks_regenerable(verdict) is True


def test_harness_owned_gap_is_not_regenerable() -> None:
    verdict = _mk_verdict({"C1": True, "C2": True, "C3": False, "C4": True, "C5": True})
    assert _verdict_is_tasks_regenerable(verdict) is False


def test_mixed_ownership_is_not_regenerable() -> None:
    # A tasks-owned gap AND a harness-owned gap: regenerating tasks alone cannot
    # close the harness gap, so the package is left advisory.
    verdict = _mk_verdict(
        {"C1": False, "C2": True, "C3": False, "C4": True, "C5": True}
    )
    assert _verdict_is_tasks_regenerable(verdict) is False


def test_verified_verdict_is_not_regenerable() -> None:
    verdict = _mk_verdict({"C1": True, "C2": True, "C3": True, "C4": True, "C5": True})
    assert _verdict_is_tasks_regenerable(verdict) is False


def test_advisory_c5_failure_never_triggers_regen() -> None:
    # C5 (time budget) is advisory and never flips the verdict, so an otherwise
    # clean package with only C5 over budget is verified and not regenerable.
    verdict = _mk_verdict({"C1": True, "C2": True, "C3": True, "C4": True, "C5": False})
    assert verdict.verified is True
    assert _failing_verdict_checks(verdict) == set()
    assert _verdict_is_tasks_regenerable(verdict) is False


def test_regen_findings_only_carry_tasks_owned_gaps() -> None:
    verdict = _mk_verdict(
        {"C1": False, "C2": True, "C3": True, "C4": True, "C5": True},
        gaps={"C1": ["T-002 precondition points forward"]},
    )
    findings = _verdict_regen_findings(verdict)
    assert findings == [
        {
            "kind": "dag_acyclic",
            "detail": "T-002 precondition points forward",
            "reference": "C1",
        }
    ]


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
        "regen_attempted": False,
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
# Dispatch orchestration (_dispatch_construction_verifier)
#
# The dispatch wires the well-tested helpers together; these tests pin the
# load-bearing invariants — idempotency of the one funded regenerate, the
# ownership routing, the staleness guard — with the session and the regen
# stubbed (no Postgres needed).
# ---------------------------------------------------------------------------


class _DispatchSession:
    """Stands in for the dispatch's own ``AsyncSessionLocal`` context."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "_DispatchSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:  # pragma: no cover - fail-open path
        self.rollbacks += 1


def _ws_with_stages(stage_map, *, verdict=None, budget=None):
    ws = SimpleNamespace(
        id=uuid4(),
        mode="demo_day",
        time_budget_minutes=budget,
        construction_verdict=verdict,
        stages=list(stage_map.values()),
    )
    return ws


def _tasks_owned_failing_map():
    """A package where only C2 fails (a task cites a non-existent harness file).

    The tasks stage is a freshly-generated ``draft`` — the state the verifier sees
    post-tasks-generation, and the precondition for the funded regenerate.
    """
    stages = _stage_map()
    stages["tasks"].content = _TASKS.replace("tests/test_shorten.py", "tests/ghost.py")
    stages["tasks"].status = "draft"
    return stages


def _harness_owned_failing_map():
    """A package where C3 fails (an AC is dropped from the harness RTM)."""
    stages = _stage_map()
    stages["harness"].content = _HARNESS.replace(
        "| AC-002 | `tests/e2e/test_smoke.py` |\n", ""
    )
    return stages


async def _run_dispatch(monkeypatch, sm, ws, *, tasks_version=1, regen_ok=True):
    import database

    session = _DispatchSession()
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: session)

    async def _fake_load_ws(workspace_id, db):
        return ws

    monkeypatch.setattr(sm, "_load_workspace", _fake_load_ws)

    regen_calls: list[list[dict]] = []

    async def _fake_regen(*, db, workspace, tasks_stage, findings, user_id):
        regen_calls.append(findings)
        return regen_ok

    monkeypatch.setattr(sm, "_run_construction_regen", _fake_regen)

    await sm._dispatch_construction_verifier(
        workspace_id=ws.id, tasks_version=tasks_version, user_id=uuid4()
    )
    return session, regen_calls


@pytest.mark.asyncio
async def test_dispatch_verified_package_persists_no_regen(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws = _ws_with_stages(_stage_map())
    session, regen_calls = await _run_dispatch(monkeypatch, sm, ws)
    assert ws.construction_verdict["verified"] is True
    assert regen_calls == []  # verified → no regenerate
    assert session.commits >= 1


@pytest.mark.asyncio
async def test_dispatch_tasks_owned_gap_triggers_single_regen(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws = _ws_with_stages(_tasks_owned_failing_map())
    session, regen_calls = await _run_dispatch(monkeypatch, sm, ws, regen_ok=True)
    assert len(regen_calls) == 1  # exactly one funded regenerate
    # Window consumed: the persisted verdict records the attempt.
    assert ws.construction_verdict["regen_attempted"] is True


@pytest.mark.asyncio
async def test_dispatch_idempotency_guard_skips_regen_when_prior_attempted(
    monkeypatch,
) -> None:
    # THE load-bearing invariant: a verdict already marked regen_attempted must
    # never trigger a second platform-funded regenerate (the "fires at most once"
    # guarantee, and the recursion guard for a re-fired verifier).
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws = _ws_with_stages(_tasks_owned_failing_map(), verdict={"regen_attempted": True})
    session, regen_calls = await _run_dispatch(monkeypatch, sm, ws)
    assert regen_calls == []  # prior attempt → no second regenerate
    assert ws.construction_verdict["regen_attempted"] is True


@pytest.mark.asyncio
async def test_dispatch_harness_owned_gap_is_advisory_no_regen(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws = _ws_with_stages(_harness_owned_failing_map())
    session, regen_calls = await _run_dispatch(monkeypatch, sm, ws)
    assert regen_calls == []  # harness-owned gap → not regenerable from here
    assert ws.construction_verdict["verified"] is False
    # The window is not consumed (we never attempted a regen), so a later manual
    # tasks regeneration could still try.
    assert ws.construction_verdict["regen_attempted"] is False


@pytest.mark.asyncio
async def test_dispatch_regen_failure_still_consumes_window(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws = _ws_with_stages(_tasks_owned_failing_map())
    session, regen_calls = await _run_dispatch(monkeypatch, sm, ws, regen_ok=False)
    assert len(regen_calls) == 1
    # Even on a failed regenerate the window is consumed so it fires at most once.
    assert ws.construction_verdict["regen_attempted"] is True


@pytest.mark.asyncio
async def test_dispatch_stale_tasks_version_returns_without_persisting(
    monkeypatch,
) -> None:
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    stages = _stage_map(versions={"spec": 1, "plan": 1, "harness": 1, "tasks": 3})
    ws = _ws_with_stages(stages, verdict=None)
    # The verifier was scheduled against tasks v1, but tasks is now v3.
    session, regen_calls = await _run_dispatch(monkeypatch, sm, ws, tasks_version=1)
    assert ws.construction_verdict is None  # nothing persisted
    assert session.commits == 0
    assert regen_calls == []


# ---------------------------------------------------------------------------
# Regenerate body (_run_construction_regen) — the LLM/prompt/route deps stubbed
# ---------------------------------------------------------------------------


class _RegenSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _patch_regen_deps(monkeypatch, sm, *, regen_output: str):
    import services.pipeline.stage_manager as smmod

    monkeypatch.setattr(smmod, "build_prompt", _async_return(("SYS", "USR", "0")))
    monkeypatch.setattr(
        smmod, "_route_for_stage_generation", lambda *a, **k: SimpleNamespace()
    )
    monkeypatch.setattr(
        smmod, "_workspace_stage_deps", lambda ws, st: {"harness": _HARNESS}
    )

    async def _fake_redis():
        return SimpleNamespace()

    monkeypatch.setattr(sm, "_redis_client", _fake_redis)

    async def _fake_regen_with_findings(**kwargs):
        return regen_output

    monkeypatch.setattr(sm, "_regenerate_with_findings", _fake_regen_with_findings)

    async def _fake_invalidate(workspace_id, stage_type, redis):
        return None

    monkeypatch.setattr(sm, "_invalidate_stage_cache", _fake_invalidate)


def _async_return(value):
    async def _inner(*a, **k):
        return value

    return _inner


def _regen_workspace_and_stage():
    stages = _stage_map()
    ws = _ws_with_stages(stages)
    return ws, stages["tasks"]


# A regenerated tasks doc carrying every required Demo Day section so
# validate_sections passes (the contract is enforced in the regen path).
_FULL_TASKS = """# TASKS

## Effort Summary

Estimated build time: ~2h (target ≤ 5h).

## Build Order

Skeleton first, app green after each task.

## Traceability Overview

AC-001 -> T-001; AC-002 -> T-002.

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


@pytest.mark.asyncio
async def test_run_construction_regen_persists_new_version(monkeypatch) -> None:
    from models import StageVersion
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws, tasks_stage = _regen_workspace_and_stage()
    tasks_stage.id = uuid4()
    start_version = tasks_stage.current_version
    _patch_regen_deps(monkeypatch, sm, regen_output=_FULL_TASKS)
    db = _RegenSession()
    ok = await sm._run_construction_regen(
        db=db,
        workspace=ws,
        tasks_stage=tasks_stage,
        findings=[{"kind": "task_to_test", "detail": "x", "reference": "C2"}],
        user_id=uuid4(),
    )
    assert ok is True
    assert tasks_stage.current_version == start_version + 1
    assert tasks_stage.content == _FULL_TASKS
    assert any(isinstance(o, StageVersion) for o in db.added)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_run_construction_regen_rejects_missing_sections(monkeypatch) -> None:
    from services.pipeline.stage_manager import StageManager

    sm = StageManager()
    ws, tasks_stage = _regen_workspace_and_stage()
    tasks_stage.id = uuid4()
    start_version = tasks_stage.current_version
    # The regenerated doc is missing required Demo Day tasks sections.
    _patch_regen_deps(monkeypatch, sm, regen_output="# TASKS\n\nnothing useful\n")
    db = _RegenSession()
    ok = await sm._run_construction_regen(
        db=db,
        workspace=ws,
        tasks_stage=tasks_stage,
        findings=[],
        user_id=uuid4(),
    )
    assert ok is False
    assert tasks_stage.current_version == start_version  # not persisted
    assert db.commits == 0


# ---------------------------------------------------------------------------
# F7 (scalability audit P2): compute_verdict_async parity. The linter joins all
# four full stage documents (the largest combined CPU payload on the pipeline);
# offloading it to the dedicated pool must not change the verdict.
# ---------------------------------------------------------------------------


async def test_compute_verdict_async_matches_sync_on_pool_path(monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    stages = _stage_map(versions={"spec": 2, "plan": 1, "harness": 4, "tasks": 3})
    sync_verdict = demo_day_verdict.compute_verdict(_ws(), stages)
    async_verdict = await demo_day_verdict.compute_verdict_async(_ws(), stages)
    assert async_verdict.to_dict() == sync_verdict.to_dict()
