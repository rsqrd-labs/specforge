"""T-247 — critic quality-gate tests.

Two layers:
- Security/contract unit tests on the critic module itself (schema cannot carry
  artifact bytes; prompt template is held in code; fail-open on judge failure).
- Behavioral tests that drive StageManager.generate() with a stubbed
  critic_review to exercise the regenerate loop, the credit-refund and
  reset-to-draft cleanup, the quality_gate_failed SSE event, and the
  disable_critic escape hatch.  The harness-level contract tests are pure
  greps; these are where the loop's real correctness is checked.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY
from pydantic import ValidationError

from models import CreditLedger, Stage, StageVersion, Workspace
from services.pipeline import critic as critic_module
from services.pipeline.artifact_validator import SECTION_CONTRACTS
from services.pipeline.critic import (
    AUDIT_EVENT_CRITIC_DISABLED,
    CriticFinding,
    StageCriticResult,
    StageQualityGateError,
    critic_review,
)
from services.pipeline.stage_manager import StageManager

_REGEN_METRIC = "specforge_billing_credits_critic_regen_total"

# A spec artifact containing every required section heading so the zero-LLM
# section validator (which runs BEFORE the critic in generate()) passes and the
# stubbed critic_review is actually reached.  Also well past the critic's
# 500-char gradable floor so the direct critic_review unit tests do real work.
_LONG_ARTIFACT = "\n\n".join(
    f"{heading}\nDetailed content for this section covering the requirement.\n"
    for heading in SECTION_CONTRACTS["spec"]
)


# ---------------------------------------------------------------------------
# Fakes (mirror of the test_stage_manager harness, kept self-contained).
# ---------------------------------------------------------------------------
class _FakePipeline:
    def zremrangebyscore(self, *a, **kw) -> "_FakePipeline":
        return self

    def zadd(self, *a, **kw) -> "_FakePipeline":
        return self

    def zcard(self, *a, **kw) -> "_FakePipeline":
        return self

    def expire(self, *a, **kw) -> "_FakePipeline":
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def eval(self, *args, **kwargs) -> int:
        return 1

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline()

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)


class _FakeResult:
    def __init__(self, value: Any = None, many: list | None = None) -> None:
        self._value = value
        self._many = many or []

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> "_FakeResult":
        return self

    def __iter__(self):
        yield from self._many


class _MultiQueryDB:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = iter(responses)
        self.added: list[Any] = []
        self._committed = False

    async def execute(self, statement: Any) -> _FakeResult:
        try:
            val = next(self._responses)
        except StopIteration:
            val = None
        if isinstance(val, list):
            return _FakeResult(many=val)
        return _FakeResult(val)

    def add(self, instance: Any) -> None:
        if isinstance(instance, (StageVersion, CreditLedger)) and (
            getattr(instance, "id", None) is None
        ):
            instance.id = uuid4()
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self._committed = True

    async def refresh(self, instance: Any) -> None:
        pass


def _make_stage(workspace_id, stage_type="spec", status="draft") -> Stage:
    return Stage(
        id=uuid4(),
        workspace_id=workspace_id,
        type=stage_type,
        status=status,
        content=None,
        current_version=0,
        review_gate_acknowledged=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_workspace(stages: list[Stage], *, disable_critic: bool = False) -> Workspace:
    w = Workspace(
        id=uuid4(),
        user_id=uuid4(),
        name="WS",
        problem_statement=(
            "I want to build a todo app for teams to create tasks, assign owners, "
            "track project status, and authenticate users."
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
        public_share_enabled=False,
        disable_critic=disable_critic,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    w.stages = stages
    return w


def _make_user():
    user = MagicMock()
    user.id = uuid4()
    return user


async def _fake_stream(*args, **kwargs) -> AsyncGenerator[str, None]:
    # Emit the long artifact in two chunks so it streams like a real generation.
    half = len(_LONG_ARTIFACT) // 2
    yield _LONG_ARTIFACT[:half]
    yield _LONG_ARTIFACT[half:]


def _build_generate_env(*, disable_critic: bool = False):
    workspace_id = uuid4()
    spec_stage = _make_stage(workspace_id, "spec")
    workspace = _make_workspace([spec_stage], disable_critic=disable_critic)
    user = _make_user()
    deduction = CreditLedger(id=uuid4(), user_id=user.id, amount=-10, reason="generate")
    db = _MultiQueryDB([spec_stage, workspace, [], deduction])
    svc = StageManager(redis_client=_FakeRedis())
    return svc, spec_stage, workspace, user, deduction, db


# ---------------------------------------------------------------------------
# Security / contract unit tests on the critic module.
# ---------------------------------------------------------------------------
def test_critic_result_schema_excludes_artifact_bytes() -> None:
    """The critic verdict can carry only a pass flag + structured findings."""
    assert set(StageCriticResult.model_fields) == {"passed", "findings"}
    # extra="forbid": a malicious judge response cannot smuggle a rewrite back
    # through an unexpected key.
    for forbidden in ("artifact_md", "artifact_content", "rewritten", "new_artifact"):
        with pytest.raises(ValidationError):
            StageCriticResult.model_validate({"passed": True, forbidden: "x" * 1000})


def test_critic_prompt_template_held_in_code() -> None:
    """The critic prompt must be an in-code constant, never load_prompt()."""
    src = Path(critic_module.__file__).read_text()
    assert "load_prompt(" not in src
    assert isinstance(critic_module._CRITIC_SYSTEM_PROMPT, str)
    assert len(critic_module._CRITIC_SYSTEM_PROMPT) > 200


@pytest.mark.asyncio
async def test_critic_review_fail_open_on_judge_error() -> None:
    """A judge call that raises must not brick generation — return passed=True."""
    with patch(
        "services.pipeline.critic.call_judge_model",
        new_callable=AsyncMock,
        side_effect=RuntimeError("judge down"),
    ):
        result = await critic_review("plan", _LONG_ARTIFACT, {})
    assert result.passed is True
    assert result.findings == []


@pytest.mark.asyncio
async def test_critic_review_fail_open_on_unparseable_verdict() -> None:
    """A non-JSON judge response must fail open rather than raise."""
    with patch(
        "services.pipeline.critic.call_judge_model",
        new_callable=AsyncMock,
        return_value="I think this looks fine, honestly.",
    ):
        result = await critic_review("plan", _LONG_ARTIFACT, {})
    assert result.passed is True


@pytest.mark.asyncio
async def test_critic_review_parses_fenced_findings() -> None:
    """A fenced JSON verdict with findings is parsed into the result model."""
    verdict = (
        "```json\n"
        '{"passed": false, "findings": [{"kind": "MissingSection", '
        '"detail": "No Security Architecture section", "reference": "Security"}]}\n'
        "```"
    )
    with patch(
        "services.pipeline.critic.call_judge_model",
        new_callable=AsyncMock,
        return_value=verdict,
    ):
        result = await critic_review("plan", _LONG_ARTIFACT, {})
    assert result.passed is False
    assert result.findings[0].kind == "MissingSection"


@pytest.mark.asyncio
async def test_critic_review_short_artifact_skips_judge() -> None:
    """Artifacts under the gradable threshold pass without a judge call."""
    judge = AsyncMock()
    with patch("services.pipeline.critic.call_judge_model", judge):
        result = await critic_review("spec", "too short", {})
    assert result.passed is True
    judge.assert_not_called()


# ---------------------------------------------------------------------------
# Behavioral tests driving StageManager.generate() with a stubbed critic.
# ---------------------------------------------------------------------------
def _generate_patches(svc: StageManager, *, complete_return: str | None = None):
    """Common patch set for generate(): credits, prompt, validate, adapter."""
    deduct = patch(
        "services.pipeline.stage_manager.credit_service.deduct",
        new_callable=AsyncMock,
    )
    refund = patch(
        "services.pipeline.stage_manager.credit_service.refund",
        new_callable=AsyncMock,
    )
    invalidate = patch(
        "services.pipeline.stage_manager.credit_service.invalidate",
        new_callable=AsyncMock,
    )
    build = patch(
        "services.pipeline.stage_manager.build_prompt",
        new_callable=AsyncMock,
        return_value=("sys", "user"),
    )
    validate = patch(
        "services.pipeline.stage_manager.validate",
        return_value=MagicMock(is_safe=True, reason=""),
    )
    set_cache = patch(
        "services.pipeline.stage_manager.set_cached_generation",
        new_callable=AsyncMock,
    )
    adapter = MagicMock()
    adapter.stream = _fake_stream
    if complete_return is not None:
        adapter.complete = AsyncMock(return_value=complete_return)
    get_llm = patch("services.pipeline.stage_manager.get_llm", return_value=adapter)
    return deduct, refund, invalidate, build, validate, set_cache, get_llm


@pytest.mark.asyncio
async def test_critic_pass_persists_artifact() -> None:
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    with (
        deduct as md,
        refund as mr,
        invalidate,
        build,
        validate,
        set_cache as mc,
        get_llm,
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=StageCriticResult(passed=True),
        ) as mock_critic,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    mock_critic.assert_awaited_once()
    assert any("done" in t for t in tokens)
    assert stage.status == "draft"
    assert stage.content == _LONG_ARTIFACT.strip()
    assert any(isinstance(a, StageVersion) for a in db.added)
    mc.assert_awaited_once()  # passed artifact is cached
    mr.assert_not_awaited()  # no refund on success


@pytest.mark.asyncio
async def test_critic_one_regenerate_cap() -> None:
    """Second consecutive failure: refund once, reset to draft, raise + SSE."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=_LONG_ARTIFACT
    )
    fail = StageCriticResult(
        passed=False,
        findings=[CriticFinding(kind="MissingSection", detail="missing ADR")],
    )
    before = REGISTRY.get_sample_value(_REGEN_METRIC, {"stage": "spec"}) or 0.0

    with (
        deduct as md,
        refund as mr,
        invalidate as mi,
        build,
        validate,
        set_cache as mc,
        get_llm,
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=fail,
        ) as mock_critic,
    ):
        md.return_value = deduction
        tokens: list[str] = []
        with pytest.raises(StageQualityGateError):
            async for t in svc.generate(stage.id, user, db):
                tokens.append(t)

    # Critic consulted twice (initial + after the one regenerate).
    assert mock_critic.await_count == 2
    # Exactly one regenerate happened and was attributed.
    after = REGISTRY.get_sample_value(_REGEN_METRIC, {"stage": "spec"}) or 0.0
    assert after - before == 1.0
    # Refund happened exactly once; credit cache invalidated.
    mr.assert_awaited_once()
    mi.assert_awaited()
    # Stage reset to a regeneratable draft; failed artifact never cached/persisted.
    assert stage.status == "draft"
    mc.assert_not_awaited()
    assert not any(isinstance(a, StageVersion) for a in db.added)
    # The frontend gets the structured failure event.
    assert any("quality_gate_failed" in t for t in tokens)


@pytest.mark.asyncio
async def test_critic_fail_then_pass_regenerates_once() -> None:
    """First fail then pass: regenerate once, persist the corrected artifact."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    regenerated = "## Corrected\n" + _LONG_ARTIFACT
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=regenerated
    )
    results = [
        StageCriticResult(
            passed=False,
            findings=[CriticFinding(kind="CoverageGap", detail="FR-002 uncovered")],
        ),
        StageCriticResult(passed=True),
    ]
    before = REGISTRY.get_sample_value(_REGEN_METRIC, {"stage": "spec"}) or 0.0

    with (
        deduct as md,
        refund as mr,
        invalidate,
        build,
        validate,
        set_cache,
        get_llm,
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            side_effect=results,
        ) as mock_critic,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    assert mock_critic.await_count == 2
    after = REGISTRY.get_sample_value(_REGEN_METRIC, {"stage": "spec"}) or 0.0
    assert after - before == 1.0
    assert stage.content == regenerated.strip()  # corrected artifact persisted
    assert any("done" in t for t in tokens)
    assert not any("quality_gate_failed" in t for t in tokens)
    mr.assert_not_awaited()  # success after regenerate — no refund


@pytest.mark.asyncio
async def test_disable_critic_skips_gate() -> None:
    """disable_critic=True bypasses the critic entirely."""
    svc, stage, workspace, user, deduction, db = _build_generate_env(
        disable_critic=True
    )
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    with (
        deduct as md,
        refund,
        invalidate,
        build,
        validate,
        set_cache,
        get_llm,
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
        ) as mock_critic,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    mock_critic.assert_not_awaited()
    assert any("done" in t for t in tokens)
    assert stage.content == _LONG_ARTIFACT.strip()


# ---------------------------------------------------------------------------
# Audit-event test for the owner-only disable_critic toggle.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_disable_critic_writes_audit_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from routers.workspace import set_workspace_critic
    from schemas.workspace import WorkspaceCriticToggle

    workspace = _make_workspace([], disable_critic=False)
    user = _make_user()
    db = _MultiQueryDB([])

    with (
        patch(
            "routers.workspace.workspace_service.get",
            new_callable=AsyncMock,
            return_value=workspace,
        ),
        patch(
            "routers.workspace.derive_coverage_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        caplog.at_level(logging.INFO, logger="routers.workspace"),
    ):
        await set_workspace_critic(
            workspace.id,
            WorkspaceCriticToggle(disable_critic=True),
            user=user,
            db=db,
        )

    assert workspace.disable_critic is True
    audit_records = [
        r for r in caplog.records if r.getMessage() == AUDIT_EVENT_CRITIC_DISABLED
    ]
    assert len(audit_records) == 1
    record = audit_records[0]
    assert record.actor_id == str(user.id)
    assert record.workspace_id == str(workspace.id)
    assert record.disable_critic is True


@pytest.mark.asyncio
async def test_disable_critic_no_change_skips_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A no-op toggle (same value) writes no audit row."""
    from routers.workspace import set_workspace_critic
    from schemas.workspace import WorkspaceCriticToggle

    workspace = _make_workspace([], disable_critic=False)
    user = _make_user()
    db = _MultiQueryDB([])

    with (
        patch(
            "routers.workspace.workspace_service.get",
            new_callable=AsyncMock,
            return_value=workspace,
        ),
        patch(
            "routers.workspace.derive_coverage_summary",
            new_callable=AsyncMock,
            return_value=None,
        ),
        caplog.at_level(logging.INFO, logger="routers.workspace"),
    ):
        await set_workspace_critic(
            workspace.id,
            WorkspaceCriticToggle(disable_critic=False),
            user=user,
            db=db,
        )

    assert not [
        r for r in caplog.records if r.getMessage() == AUDIT_EVENT_CRITIC_DISABLED
    ]
