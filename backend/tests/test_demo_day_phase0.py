"""Demo Day mode — Phase 0 (data model + plumbing) tests.

The headline safety test is the §4 regression pin: a standard workspace create is
byte-identical to today, and the new columns default to standard. The Demo-Day
paths are gated behind the ``demo_day_mode_enabled`` config flag.

See docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §0/§4/§12.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas.workspace import WorkspaceCreate, WorkspaceResponse
from services.workspace_service import WorkspaceService
from tests.test_workspace import _FakeDB

_PROBLEM = (
    "I want to build a task management web app for teams to create projects, "
    "assign tasks, track status, and notify users."
)


def _standard_payload(**overrides) -> WorkspaceCreate:
    base = {
        "name": "Test",
        "problem_statement": _PROBLEM,
        "provider": "anthropic",
        "model": None,
    }
    base.update(overrides)
    return WorkspaceCreate(**base)


# ---------------------------------------------------------------------------
# §4 regression pin — standard create is byte-identical / new columns default.
# ---------------------------------------------------------------------------


def test_standard_payload_defaults_to_standard_mode() -> None:
    payload = _standard_payload()
    assert payload.mode == "standard"
    assert payload.target_agent is None
    assert payload.time_budget_minutes is None


@pytest.mark.asyncio
async def test_standard_create_sets_standard_columns() -> None:
    svc = WorkspaceService()
    db = _FakeDB()
    workspace = await svc.create(uuid4(), _standard_payload(), db)
    assert workspace.mode == "standard"
    assert workspace.target_agent is None
    assert workspace.time_budget_minutes is None


@pytest.mark.asyncio
async def test_demo_day_payload_is_forced_standard_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag OFF (the default) ⇒ a demo_day request is forced to standard, so the
    feature stays dark and the create path is byte-identical."""
    monkeypatch.setattr(
        "services.workspace_service.settings.demo_day_mode_enabled", False
    )
    svc = WorkspaceService()
    db = _FakeDB()
    payload = _standard_payload(
        mode="demo_day", target_agent="claude_code", time_budget_minutes=240
    )
    workspace = await svc.create(uuid4(), payload, db)
    assert workspace.mode == "standard"
    assert workspace.target_agent is None
    assert workspace.time_budget_minutes is None


# ---------------------------------------------------------------------------
# Demo Day path (flag ON).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demo_day_create_persists_fields_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.workspace_service.settings.demo_day_mode_enabled", True
    )
    svc = WorkspaceService()
    db = _FakeDB()
    payload = _standard_payload(
        mode="demo_day", target_agent="codex", time_budget_minutes=180
    )
    workspace = await svc.create(uuid4(), payload, db)
    assert workspace.mode == "demo_day"
    assert workspace.target_agent == "codex"
    assert workspace.time_budget_minutes == 180


# ---------------------------------------------------------------------------
# Schema validation.
# ---------------------------------------------------------------------------


def test_demo_day_requires_target_agent() -> None:
    with pytest.raises(ValidationError):
        _standard_payload(mode="demo_day")


def test_standard_mode_drops_demo_day_metadata() -> None:
    payload = _standard_payload(
        mode="standard", target_agent="claude_code", time_budget_minutes=200
    )
    assert payload.target_agent is None
    assert payload.time_budget_minutes is None


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        _standard_payload(mode="turbo")


def test_invalid_target_agent_rejected() -> None:
    with pytest.raises(ValidationError):
        _standard_payload(mode="demo_day", target_agent="cursor")


def test_non_positive_time_budget_rejected() -> None:
    with pytest.raises(ValidationError):
        _standard_payload(mode="demo_day", target_agent="codex", time_budget_minutes=0)


def test_response_defaults_to_standard() -> None:
    """A response constructed from a row without the columns reads as standard."""
    fields = WorkspaceResponse.model_fields
    assert fields["mode"].default == "standard"
    assert fields["target_agent"].default is None
    assert fields["time_budget_minutes"].default is None
