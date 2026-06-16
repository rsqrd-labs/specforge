"""Issue #12 (Phase 3) — wiring Brave research into generation + the opt-in API.

Two layers:
- ``StageManager._fetch_research_context``: the fail-open gate that decides
  whether the generate() preflight even asks research_service for a block — the
  free-run skip and the surplus guard that guarantee research can never starve
  or block the generation it enriches.
- ``PATCH /workspaces/{id}/research``: the owner-only opt-in toggle that writes
  the auditable third-party-egress consent decision.

research_service.fetch_context itself (cache/quota/billing/sanitisation) and the
prompt threading are covered by test_research_service.py and test_prompt_builder.py;
these tests pin only the new Phase-3 seams.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import Workspace
from routers.workspace import set_workspace_research
from schemas.workspace import WorkspaceResearchToggle
from services.pipeline.critic import StageCriticResult
from services.pipeline.stage_manager import StageManager

_FETCH = "services.pipeline.stage_manager.research_service.fetch_context"


def _user(balance: int | None = 100):
    return SimpleNamespace(id=uuid4(), credit_balance=balance)


def _workspace():
    return SimpleNamespace(
        id=uuid4(),
        name="WS",
        problem_statement="Build a collaborative tracker for teams.",
        brave_research_enabled=True,
    )


def _orm_workspace(*, enabled: bool) -> Workspace:
    """A fully-populated ORM workspace so WorkspaceResponse.model_validate
    succeeds in the endpoint tests."""
    ws = Workspace(
        id=uuid4(),
        user_id=uuid4(),
        name="WS",
        problem_statement="Build a collaborative tracker for teams over time.",
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
        public_share_enabled=False,
        disable_critic=False,
        brave_research_enabled=enabled,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    ws.stages = []
    return ws


# ---------------------------------------------------------------------------
# StageManager._fetch_research_context — the preflight gate.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_free_run_skips_research_entirely() -> None:
    """A free / platform-funded run never spends a Brave credit."""
    svc = StageManager(redis_client=MagicMock())
    with patch(_FETCH, new_callable=AsyncMock) as fetch:
        out = await svc._fetch_research_context(
            _workspace(),
            "spec",
            _user(),
            MagicMock(),
            credit_cost=10,
            free=True,
        )
    assert out == ""
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_insufficient_surplus_skips_research() -> None:
    """Research is skipped when the balance can't cover BOTH the generation
    charge and the research charge — it must never starve the generation."""
    svc = StageManager(redis_client=MagicMock())
    # credit_cost 10 + research charge 1 = 11 needed; balance 10 is short.
    user = _user(balance=10)
    with patch(_FETCH, new_callable=AsyncMock) as fetch:
        out = await svc._fetch_research_context(
            _workspace(),
            "spec",
            user,
            MagicMock(),
            credit_cost=10,
            free=False,
        )
    assert out == ""
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_sufficient_surplus_delegates_and_returns_block() -> None:
    """With surplus, the gate delegates to fetch_context and returns its block."""
    svc = StageManager(redis_client=MagicMock())
    user = _user(balance=100)
    ws = _workspace()
    redis = MagicMock()
    with patch(_FETCH, new_callable=AsyncMock, return_value="BLOCK") as fetch:
        out = await svc._fetch_research_context(
            ws,
            "spec",
            user,
            redis,
            credit_cost=10,
            free=False,
        )
    assert out == "BLOCK"
    # fetch_context receives a DEDICATED session (not the preflight's db) so the
    # brave charge commit can't release the stage's FOR UPDATE lock early.
    fetch.assert_awaited_once()
    call_args = fetch.await_args.args
    assert call_args[0] is ws
    assert call_args[1] == "spec"
    assert isinstance(call_args[2], AsyncSession)
    assert call_args[3] is redis
    assert call_args[4] == user.id


@pytest.mark.asyncio
async def test_unknown_balance_is_permissive() -> None:
    """A non-int balance (unknown) defers to fetch_context's own pre-check
    rather than blocking enrichment outright."""
    svc = StageManager(redis_client=MagicMock())
    with patch(_FETCH, new_callable=AsyncMock, return_value="BLOCK") as fetch:
        out = await svc._fetch_research_context(
            _workspace(),
            "spec",
            _user(balance=None),
            MagicMock(),
            credit_cost=10,
            free=False,
        )
    assert out == "BLOCK"
    fetch.assert_awaited_once()


# ---------------------------------------------------------------------------
# PATCH /workspaces/{id}/research — owner-only opt-in toggle.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enable_research_sets_flag_commits_and_audits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ws = _orm_workspace(enabled=False)
    user = _user()
    db = AsyncMock()
    with (
        patch(
            "routers.workspace.workspace_service.get",
            new_callable=AsyncMock,
            return_value=ws,
        ),
        patch(
            "routers.workspace.derive_coverage_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        caplog.at_level(logging.INFO),
    ):
        resp = await set_workspace_research(
            ws.id, WorkspaceResearchToggle(brave_research_enabled=True), user, db
        )
    assert ws.brave_research_enabled is True
    assert resp.brave_research_enabled is True
    db.commit.assert_awaited_once()
    assert any(r.message == "brave_research_toggled" for r in caplog.records)


@pytest.mark.asyncio
async def test_toggle_is_noop_when_unchanged() -> None:
    """Setting the flag to its current value writes nothing (no commit/audit)."""
    ws = _orm_workspace(enabled=True)
    db = AsyncMock()
    with (
        patch(
            "routers.workspace.workspace_service.get",
            new_callable=AsyncMock,
            return_value=ws,
        ),
        patch(
            "routers.workspace.derive_coverage_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await set_workspace_research(
            ws.id, WorkspaceResearchToggle(brave_research_enabled=True), _user(), db
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_gets_404() -> None:
    """workspace_service.get filters by user_id, so a non-owner 404s and can
    never flip another user's flag."""
    with patch(
        "routers.workspace.workspace_service.get",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=404, detail="Workspace not found"),
    ):
        with pytest.raises(HTTPException) as exc:
            await set_workspace_research(
                uuid4(),
                WorkspaceResearchToggle(brave_research_enabled=True),
                _user(),
                AsyncMock(),
            )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# generate() end-to-end: the fetched block actually reaches build_prompt.
# Reuses the test_critic harness rather than re-deriving the generate() env.
# ---------------------------------------------------------------------------
from test_critic import _build_generate_env, _generate_patches  # noqa: E402


def _enable_brave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip the global flag + key on so brave_search_enabled is True; the
    per-workspace opt-in is still the gate the tests vary."""
    monkeypatch.setattr(settings, "brave_search_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "brave_search_flag", True, raising=False)


@pytest.mark.asyncio
async def test_generate_injects_block_for_opted_in_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opted-in spec generation threads the fetched block into build_prompt."""
    _enable_brave(monkeypatch)
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    workspace.brave_research_enabled = True
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    with (
        deduct as md,
        refund,
        invalidate,
        build as mock_build,
        validate,
        set_cache,
        get_llm,
        patch(
            "services.pipeline.stage_manager.research_service.fetch_context",
            new_callable=AsyncMock,
            return_value="## External Research Context\nSENTINEL",
        ) as mock_fetch,
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=StageCriticResult(passed=True),
        ),
    ):
        md.return_value = deduction
        [t async for t in svc.generate(stage.id, user, db)]

    mock_fetch.assert_awaited_once()
    assert (
        mock_build.await_args.kwargs["research_context"]
        == "## External Research Context\nSENTINEL"
    )


@pytest.mark.asyncio
async def test_generate_passes_empty_context_when_not_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A not-opted-in workspace gets research_context='' — fetch_context runs
    (real) but short-circuits on the opt-in gate, never calling Brave."""
    _enable_brave(monkeypatch)
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    workspace.brave_research_enabled = False
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    with (
        deduct as md,
        refund,
        invalidate,
        build as mock_build,
        validate,
        set_cache,
        get_llm,
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=StageCriticResult(passed=True),
        ),
    ):
        md.return_value = deduction
        [t async for t in svc.generate(stage.id, user, db)]

    assert mock_build.await_args.kwargs["research_context"] == ""
