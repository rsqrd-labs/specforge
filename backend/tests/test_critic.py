"""T-247 — critic quality-gate tests.

Two layers:
- Security/contract unit tests on the critic module itself (schema cannot carry
  artifact bytes; prompt template is held in code; fail-open on judge failure).
- Behavioral tests that drive StageManager.generate() with a stubbed
  critic_review to exercise the regenerate loop, the persisted blocked-draft
  cleanup, the quality_gate_failed SSE event, and the disable_critic escape
  hatch.  The harness-level contract tests are pure
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

import artifact_fixtures
import pytest
from prometheus_client import REGISTRY
from pydantic import ValidationError

from models import CreditLedger, EvalResult, Stage, StageVersion, Workspace
from services.pipeline import critic as critic_module
from services.pipeline.artifact_validator import (
    MissingSectionError,
    final_completion_sentinel,
)
from services.pipeline.critic import (
    AUDIT_EVENT_CRITIC_DISABLED,
    CriticFinding,
    StageCriticResult,
    critic_review,
)
from services.pipeline.stage_manager import StageManager

_REGEN_METRIC = "specforge_billing_credits_critic_regen_total"

# A spec artifact containing every required section heading and the v1.9
# evidence fields so the deterministic validator passes before the critic is
# reached.  Also well past the critic's 500-char gradable floor so the direct
# critic_review unit tests do real work.
_LONG_ARTIFACT = artifact_fixtures.VALID_SPEC


def _with_final_sentinel(content: str, stage: str = "spec") -> str:
    return f"{content}\n{final_completion_sentinel(stage)}"


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


def _is_eval_result_select(statement: Any) -> bool:
    """True when a SQLAlchemy statement is a SELECT against EvalResult."""
    try:
        return any(
            cd.get("entity") is EvalResult for cd in statement.column_descriptions
        )
    except Exception:
        return False


def _select_entity(statement: Any) -> Any:
    """The primary ORM entity of a SELECT, or None for non-ORM statements."""
    try:
        for cd in statement.column_descriptions:
            entity = cd.get("entity")
            if entity is not None:
                return entity
    except Exception:
        return None
    return None


def _is_by_id_select(statement: Any, table: str) -> bool:
    """True for a single-row ``WHERE <table>.id = :id`` SELECT."""
    return f"{table}.id =" in str(statement)


# The fake DB the active generate()-driving test is exercising; the autouse
# ``_patch_pipeline_session`` fixture points ``database.AsyncSessionLocal`` at
# it so the pipeline's own-session stage/workspace re-load (and the detached
# critic) transparently see the seeded rows (docs/REFRESH_DURING_GENERATION
# _PLAN.md).
_ACTIVE_MULTI_QUERY_DB: "_MultiQueryDB | None" = None


class _MultiQueryDB:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = iter(responses)
        self.added: list[Any] = []
        self._committed = False
        # First-seen Stage/Workspace rows, replayed for later by-id reads so the
        # pipeline's re-load on its own session returns the same seeded object a
        # real DB's identity map would.
        self._captured_stage: Stage | None = None
        self._captured_workspace: Workspace | None = None
        global _ACTIVE_MULTI_QUERY_DB
        _ACTIVE_MULTI_QUERY_DB = self

    async def __aenter__(self) -> "_MultiQueryDB":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def close(self) -> None:
        pass

    async def execute(self, statement: Any) -> _FakeResult:
        # The inline structural eval (issue #27 Phase 1) looks up the version's
        # existing EvalResult.  Model an empty eval_results table without
        # consuming a seeded response, so the ordered generate-flow responses
        # below are unaffected.
        if _is_eval_result_select(statement):
            return _FakeResult(None)
        # A by-id re-load of a previously-seen Stage/Workspace replays that row
        # without consuming a response, mirroring a real DB across sessions.
        if (
            self._captured_stage is not None
            and _select_entity(statement) is Stage
            and _is_by_id_select(statement, "stages")
        ):
            return _FakeResult(self._captured_stage)
        if (
            self._captured_workspace is not None
            and _select_entity(statement) is Workspace
            and _is_by_id_select(statement, "workspaces")
        ):
            return _FakeResult(self._captured_workspace)
        try:
            val = next(self._responses)
        except StopIteration:
            val = None
        if isinstance(val, Stage) and self._captured_stage is None:
            self._captured_stage = val
        elif isinstance(val, Workspace) and self._captured_workspace is None:
            self._captured_workspace = val
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

    async def rollback(self) -> None:
        pass

    async def refresh(self, instance: Any) -> None:
        # Mirror the DB server defaults a real refresh populates so a freshly
        # inserted EvalResult is serialisable by _eval_to_dict.
        if isinstance(instance, EvalResult):
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            if getattr(instance, "created_at", None) is None:
                instance.created_at = datetime.now(UTC)
            if getattr(instance, "flagged", None) is None:
                instance.flagged = False


def install_pipeline_session_patch(monkeypatch):
    """Point ``database.AsyncSessionLocal`` at the active seeded ``_MultiQueryDB``.

    generate() now runs its pipeline on a session it opens itself (so a client
    disconnect can no longer kill an in-flight generation) and re-loads the
    stage/workspace on it (docs/REFRESH_DURING_GENERATION_PLAN.md).  In tests the
    pipeline-owned session must be the seeded ``_MultiQueryDB``.  Reused by
    test_research_wiring, which drives generate() through this module's
    ``_build_generate_env``.  A test that needs a different session installs its
    own narrower ``patch("database.AsyncSessionLocal")``, which wins inside its
    block.
    """
    import database

    global _ACTIVE_MULTI_QUERY_DB
    _ACTIVE_MULTI_QUERY_DB = None

    def _factory():
        if _ACTIVE_MULTI_QUERY_DB is None:
            raise RuntimeError(
                "AsyncSessionLocal() called with no active _MultiQueryDB; "
                "patch database.AsyncSessionLocal explicitly in this test."
            )
        return _ACTIVE_MULTI_QUERY_DB

    monkeypatch.setattr(database, "AsyncSessionLocal", _factory)


@pytest.fixture(autouse=True)
def _patch_pipeline_session(monkeypatch):
    global _ACTIVE_MULTI_QUERY_DB
    install_pipeline_session_patch(monkeypatch)
    yield
    _ACTIVE_MULTI_QUERY_DB = None


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
        brave_research_enabled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    w.stages = stages
    return w


def _make_user():
    user = MagicMock()
    user.id = uuid4()
    return user


@pytest.fixture
def legacy_inline_critic(monkeypatch):
    """Pin the synchronous inline critic+regenerate path.

    docs/CRITIC_ASYNC_ADVISORY_PLAN.md makes the async-advisory critic the
    default (the judge runs off the critical path after `done`).  The legacy
    inline regenerate loop is retained behind ``critic_async_advisory=False`` for
    one release; the behavioural tests below exercise exactly that loop, so they
    pin the flag rather than racing the detached background task.
    """
    from services.pipeline import stage_manager as stage_manager_module

    monkeypatch.setattr(stage_manager_module.settings, "critic_async_advisory", False)


class _FakeAdvisoryResult:
    def __init__(self, obj) -> None:
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


def _fake_session_local_for(stage):
    """A patchable ``database.AsyncSessionLocal`` that yields *stage* on lookup.

    Returns (session_local_factory, session) so a test can both inject the
    factory and assert ``commit`` on the session the detached critic used.
    """
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeAdvisoryResult(stage))
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session), session


async def _fake_stream(
    system, user, max_tokens=0, **kwargs
) -> AsyncGenerator[str, None]:
    # Answer each chunk prompt with its own section group and sentinel,
    # split in two so it streams like a real generation.
    payload = artifact_fixtures.spec_stream_payload(user)
    half = len(payload) // 2
    yield payload[:half]
    yield payload[half:]


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
        return_value=("sys", "user", "0"),
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
async def test_critic_pass_persists_artifact(legacy_inline_critic) -> None:
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
async def test_critic_one_regenerate_then_advisory(legacy_inline_critic) -> None:
    """Issue #34: after the one regenerate the critic is advisory, not blocking.

    A still-failing artifact is DELIVERED (status draft, finalisable) with the
    findings attached as non-blocking suggestions (quality_gate_status=advisory),
    never refunded, never a quality_gate_failed event.
    """
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=_with_final_sentinel(_LONG_ARTIFACT)
    )
    fail = StageCriticResult(
        passed=False,
        findings=[CriticFinding(kind="MissingSection", detail="missing ADR")],
    )
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
            return_value=fail,
        ) as mock_critic,
    ):
        md.return_value = deduction
        tokens: list[str] = []
        async for t in svc.generate(stage.id, user, db):
            tokens.append(t)

    # Critic consulted twice (initial + after the one regenerate).
    assert mock_critic.await_count == 2
    # Exactly one regenerate happened and was attributed.
    after = REGISTRY.get_sample_value(_REGEN_METRIC, {"stage": "spec"}) or 0.0
    assert after - before == 1.0
    # The user received a usable artifact, so the generation remains billed.
    mr.assert_not_awaited()
    # Stage is a finalisable draft carrying advisory suggestions.
    assert stage.status == "draft"
    assert stage.content == _LONG_ARTIFACT.strip()
    assert stage.quality_gate_status == "advisory"
    assert stage.quality_gate_kind == "critic_findings"
    assert stage.quality_gate_version == stage.current_version
    assert stage.quality_gate_payload["findings"][0]["kind"] == "MissingSection"
    # Advisory carries no recovery contract (nothing to recover — it's finalisable).
    assert stage.quality_gate is not None
    assert "recovery" not in stage.quality_gate
    assert any(
        isinstance(a, StageVersion) and a.content == _LONG_ARTIFACT.strip()
        for a in db.added
    )
    # The generation completes normally — no blocking event.
    assert any("done" in t for t in tokens)
    assert not any("quality_gate_failed" in t for t in tokens)


@pytest.mark.asyncio
async def test_missing_section_gate_persists_blocked_draft() -> None:
    """Zero-LLM section gate failures follow the same blocked-draft contract."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    missing = ["## Acceptance Criteria"]

    with (
        deduct as md,
        refund as mr,
        invalidate,
        build,
        validate,
        set_cache as mc,
        get_llm,
        patch(
            "services.pipeline.stage_manager.validate_sections",
            side_effect=MissingSectionError("spec", missing),
        ),
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
        ) as mock_critic,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    mock_critic.assert_not_awaited()
    mr.assert_not_awaited()
    mc.assert_not_awaited()
    assert stage.status == "draft"
    assert stage.quality_gate_status == "blocked"
    assert stage.quality_gate_kind == "missing_sections"
    assert stage.quality_gate_payload["missing"] == missing
    # This gate path does not refund; the contract must report that honestly.
    assert stage.quality_gate_payload["refunded_prior_attempt"] is False
    assert stage.quality_gate["recovery"]["refunded_prior_attempt"] is False
    assert any(isinstance(a, StageVersion) for a in db.added)
    assert any("quality_gate_failed" in t for t in tokens)


@pytest.mark.asyncio
async def test_critic_fail_then_pass_regenerates_once(legacy_inline_critic) -> None:
    """First fail then pass: regenerate once, persist the corrected artifact."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    regenerated = "## Corrected\n" + _LONG_ARTIFACT
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=_with_final_sentinel(regenerated)
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


_ESCALATION_METRIC = "specforge_pipeline_quality_escalations_total"


@pytest.mark.asyncio
async def test_critic_failure_escalates_regen_to_mid_tier(legacy_inline_critic) -> None:
    """Phase 5.1: a critic failure on the cheap primary escalates the funded
    regenerate to the mid tier instead of repeating on the same cheap model."""
    from services.pipeline import stage_manager as sm_module

    svc, stage, workspace, user, deduction, db = _build_generate_env()
    regenerated = "## Corrected\n" + _LONG_ARTIFACT
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=_with_final_sentinel(regenerated)
    )
    fail_then_pass = [
        StageCriticResult(
            passed=False,
            findings=[CriticFinding(kind="MissingSection", detail="FR-001 gap")],
        ),
        StageCriticResult(passed=True),
    ]
    before = (
        REGISTRY.get_sample_value(
            _ESCALATION_METRIC, {"stage_type": "spec", "provider": "anthropic"}
        )
        or 0.0
    )

    captured_routes: list = []

    original_regen = svc._regenerate_with_findings

    async def spy_regen(**kwargs):
        captured_routes.append(kwargs["route"])
        return await original_regen(**kwargs)

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
            side_effect=fail_then_pass,
        ),
        patch.object(svc, "_regenerate_with_findings", side_effect=spy_regen),
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    after = (
        REGISTRY.get_sample_value(
            _ESCALATION_METRIC, {"stage_type": "spec", "provider": "anthropic"}
        )
        or 0.0
    )
    assert after - before == 1.0, "escalation counter must increment exactly once"
    assert len(captured_routes) == 1
    _, escalation_tier = sm_module._core_generation_tier_policy("anthropic")
    assert (
        captured_routes[0].model_tier == escalation_tier
    ), "regenerate must use the escalation (mid) tier, not the cheap primary"
    assert any("done" in t for t in tokens)
    mr.assert_not_awaited()


@pytest.mark.asyncio
async def test_critic_failure_no_escalation_when_already_mid(
    legacy_inline_critic,
) -> None:
    """Phase 5.1: if the route is already at/above the escalation tier (e.g.
    Google Flash which has no cheaper distinct tier), no escalation happens and
    the counter stays flat."""

    svc, stage, workspace, user, deduction, db = _build_generate_env()
    # Switch workspace to google so the cheap primary IS the mid (no cheaper tier).
    workspace.provider = "google"
    workspace.model = "gemini-3.5-flash"

    regenerated = "## Corrected\n" + _LONG_ARTIFACT
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=_with_final_sentinel(regenerated)
    )
    fail_then_pass = [
        StageCriticResult(
            passed=False,
            findings=[CriticFinding(kind="ShallowSection", detail="thin plan")],
        ),
        StageCriticResult(passed=True),
    ]
    before = (
        REGISTRY.get_sample_value(
            _ESCALATION_METRIC, {"stage_type": "spec", "provider": "google"}
        )
        or 0.0
    )

    captured_routes: list = []
    original_regen = svc._regenerate_with_findings

    async def spy_regen(**kwargs):
        captured_routes.append(kwargs["route"])
        return await original_regen(**kwargs)

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
            side_effect=fail_then_pass,
        ),
        patch.object(svc, "_regenerate_with_findings", side_effect=spy_regen),
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    after = (
        REGISTRY.get_sample_value(
            _ESCALATION_METRIC, {"stage_type": "spec", "provider": "google"}
        )
        or 0.0
    )
    assert after - before == 0.0, "no escalation when already at/above escalation tier"
    assert len(captured_routes) == 1
    assert captured_routes[0].provider == "google"
    assert any("done" in t for t in tokens)
    mr.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_condensed_problem_statement_surfaces_advisory_notice() -> None:
    """Phase D: a lossily-condensed problem statement is surfaced as a non-blocking
    advisory notice on the delivered draft, even when the critic is clean."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    with (
        deduct as md,
        refund as mr,
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
        mock_build.return_value = ("sys", "user", "3")  # deterministic clamp
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    assert any("done" in t for t in tokens)
    assert stage.status == "draft"  # finalisable — never blocked
    assert stage.quality_gate_status == "advisory"
    kinds = [f["kind"] for f in stage.quality_gate_payload["findings"]]
    assert kinds == ["ProblemStatementCondensed"]
    mr.assert_not_awaited()  # informational notice never refunds
    # The generation completes normally — no blocking event.
    assert not any("quality_gate_failed" in t for t in tokens)


@pytest.mark.asyncio
async def test_condensed_notice_coexists_with_critic_findings(
    legacy_inline_critic,
) -> None:
    """Phase D: when the critic is advisory AND the statement was condensed, both
    findings ride the single advisory bucket (notice appended after critic ones)."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc, complete_return=_with_final_sentinel(_LONG_ARTIFACT)
    )
    fail = StageCriticResult(
        passed=False,
        findings=[CriticFinding(kind="MissingSection", detail="missing ADR")],
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
            return_value=fail,  # fails twice ⇒ advisory after the one regenerate
        ),
    ):
        md.return_value = deduction
        mock_build.return_value = ("sys", "user", "2")  # abstractive summary
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    assert any("done" in t for t in tokens)
    assert stage.quality_gate_status == "advisory"
    kinds = [f["kind"] for f in stage.quality_gate_payload["findings"]]
    assert kinds == ["MissingSection", "ProblemStatementCondensed"]


@pytest.mark.asyncio
async def test_uncondensed_clean_generation_stays_clear() -> None:
    """Phase D regression: rung "0" (no condensation) + clean critic ⇒ no advisory."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    with (
        deduct as md,
        refund,
        invalidate,
        build,  # _generate_patches default return rung "0"
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

    assert stage.quality_gate_status == "clear"


# ---------------------------------------------------------------------------
# Async-advisory critic (docs/CRITIC_ASYNC_ADVISORY_PLAN.md) — the default path:
# the judge runs OFF the critical path after `done`.
# ---------------------------------------------------------------------------
_ADVISORY_METRIC = "specforge_pipeline_critic_advisory_findings_total"


@pytest.mark.asyncio
async def test_async_advisory_done_before_judge_and_schedules_critic() -> None:
    """Default path: `done` is emitted WITHOUT awaiting the judge inline, and the
    critic is scheduled as a detached background task instead."""
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
        ) as mock_critic,
        patch.object(svc, "_schedule_critic_review") as mock_schedule,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    # The judge never runs on the critical path — only the detached scheduler is
    # invoked, once, pinned to the just-persisted version.
    mock_critic.assert_not_awaited()
    mock_schedule.assert_called_once()
    kwargs = mock_schedule.call_args.kwargs
    assert kwargs["stage_id"] == stage.id
    assert kwargs["version"] == stage.current_version
    assert kwargs["stage_type"] == "spec"
    assert kwargs["content"] == _LONG_ARTIFACT.strip()
    assert kwargs["provider"] == "anthropic"
    # The usable draft is delivered, persisted clean, cached; nothing refunded.
    assert any("done" in t for t in tokens)
    assert not any("quality_gate_failed" in t for t in tokens)
    assert stage.status == "draft"
    assert stage.content == _LONG_ARTIFACT.strip()
    assert stage.quality_gate_status == "clear"
    mc.assert_awaited_once()
    mr.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_advisory_section_gate_still_blocks_inline() -> None:
    """The zero-LLM section gate stays terminal on the critical path: a miss
    blocks the draft and the background critic is never scheduled."""
    svc, stage, workspace, user, deduction, db = _build_generate_env()
    deduct, refund, invalidate, build, validate, set_cache, get_llm = _generate_patches(
        svc
    )
    missing = ["## Acceptance Criteria"]
    with (
        deduct as md,
        refund,
        invalidate,
        build,
        validate,
        set_cache,
        get_llm,
        patch(
            "services.pipeline.stage_manager.validate_sections",
            side_effect=MissingSectionError("spec", missing),
        ),
        patch.object(svc, "_schedule_critic_review") as mock_schedule,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    mock_schedule.assert_not_called()
    assert stage.quality_gate_status == "blocked"
    assert stage.quality_gate_kind == "missing_sections"
    assert any("quality_gate_failed" in t for t in tokens)


@pytest.mark.asyncio
async def test_async_advisory_disable_critic_skips_schedule() -> None:
    """disable_critic bypasses the whole gate, including the background critic."""
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
        patch.object(svc, "_schedule_critic_review") as mock_schedule,
    ):
        md.return_value = deduction
        tokens = [t async for t in svc.generate(stage.id, user, db)]

    mock_schedule.assert_not_called()
    assert any("done" in t for t in tokens)
    assert stage.content == _LONG_ARTIFACT.strip()


@pytest.mark.asyncio
async def test_dispatch_critic_review_failing_marks_advisory() -> None:
    """A failing background verdict attaches advisory findings, bumps the counter,
    and records the critic_advisory cost outcome — all off the critical path."""
    workspace_id = uuid4()
    stage = _make_stage(workspace_id, "spec")
    stage.current_version = 3
    svc = StageManager(redis_client=_FakeRedis())
    session_local, session = _fake_session_local_for(stage)
    fail = StageCriticResult(
        passed=False,
        findings=[CriticFinding(kind="MissingSection", detail="missing ADR")],
    )
    before = REGISTRY.get_sample_value(_ADVISORY_METRIC, {"stage": "spec"}) or 0.0

    with (
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=fail,
        ),
        patch("database.AsyncSessionLocal", session_local),
        patch(
            "services.pipeline.stage_manager.update_cost_event_quality_outcome",
            new_callable=AsyncMock,
        ) as mock_cost,
    ):
        await svc._dispatch_critic_review(
            stage_id=stage.id,
            version=3,
            stage_type="spec",
            content=_LONG_ARTIFACT,
            critic_deps={},
            provider="anthropic",
            content_generation_id="gen-1",
        )

    session.commit.assert_awaited_once()
    assert stage.quality_gate_status == "advisory"
    assert stage.quality_gate_kind == "critic_findings"
    assert stage.quality_gate_version == 3
    kinds = [f["kind"] for f in stage.quality_gate_payload["findings"]]
    assert kinds == ["MissingSection"]
    after = REGISTRY.get_sample_value(_ADVISORY_METRIC, {"stage": "spec"}) or 0.0
    assert after - before == 1.0
    mock_cost.assert_awaited_once_with("gen-1", "critic_advisory")


@pytest.mark.asyncio
async def test_dispatch_critic_review_merges_with_condensed_notice() -> None:
    """The background critic preserves an advisory notice already attached at
    persist (the Phase-D condensed-statement notice) rather than overwriting."""
    workspace_id = uuid4()
    stage = _make_stage(workspace_id, "spec")
    stage.current_version = 2
    # Persist already attached the condensed-statement notice.
    stage.quality_gate_status = "advisory"
    stage.quality_gate_kind = "critic_findings"
    stage.quality_gate_payload = {
        "stage": "spec",
        "kind": "critic_findings",
        "findings": [{"kind": "ProblemStatementCondensed", "detail": "x"}],
    }
    svc = StageManager(redis_client=_FakeRedis())
    session_local, _ = _fake_session_local_for(stage)
    fail = StageCriticResult(
        passed=False,
        findings=[CriticFinding(kind="MissingSection", detail="missing ADR")],
    )
    with (
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=fail,
        ),
        patch("database.AsyncSessionLocal", session_local),
        patch(
            "services.pipeline.stage_manager.update_cost_event_quality_outcome",
            new_callable=AsyncMock,
        ),
    ):
        await svc._dispatch_critic_review(
            stage_id=stage.id,
            version=2,
            stage_type="spec",
            content=_LONG_ARTIFACT,
            critic_deps={},
            provider="anthropic",
            content_generation_id="gen-1",
        )

    kinds = {f["kind"] for f in stage.quality_gate_payload["findings"]}
    assert kinds == {"ProblemStatementCondensed", "MissingSection"}


@pytest.mark.asyncio
async def test_dispatch_critic_review_passing_makes_no_change() -> None:
    """A clean background verdict never opens a session or writes anything."""
    workspace_id = uuid4()
    stage = _make_stage(workspace_id, "spec")
    stage.current_version = 1
    svc = StageManager(redis_client=_FakeRedis())
    session_local, session = _fake_session_local_for(stage)
    with (
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=StageCriticResult(passed=True),
        ),
        patch("database.AsyncSessionLocal", session_local),
        patch(
            "services.pipeline.stage_manager.update_cost_event_quality_outcome",
            new_callable=AsyncMock,
        ) as mock_cost,
    ):
        await svc._dispatch_critic_review(
            stage_id=stage.id,
            version=1,
            stage_type="spec",
            content=_LONG_ARTIFACT,
            critic_deps={},
            provider="anthropic",
            content_generation_id="gen-1",
        )

    session_local.assert_not_called()  # no session opened on a passing verdict
    session.commit.assert_not_awaited()
    mock_cost.assert_not_awaited()
    assert stage.quality_gate_status is None or stage.quality_gate_status != "advisory"


@pytest.mark.asyncio
async def test_dispatch_critic_review_version_mismatch_no_write() -> None:
    """Staleness guard: a version bump since scheduling means a newer draft
    superseded the one judged — findings must not be stamped on the wrong one."""
    workspace_id = uuid4()
    stage = _make_stage(workspace_id, "spec")
    stage.current_version = 5  # newer than the scheduled version below
    svc = StageManager(redis_client=_FakeRedis())
    session_local, session = _fake_session_local_for(stage)
    fail = StageCriticResult(
        passed=False,
        findings=[CriticFinding(kind="MissingSection", detail="missing ADR")],
    )
    with (
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            return_value=fail,
        ),
        patch("database.AsyncSessionLocal", session_local),
        patch(
            "services.pipeline.stage_manager.update_cost_event_quality_outcome",
            new_callable=AsyncMock,
        ) as mock_cost,
    ):
        await svc._dispatch_critic_review(
            stage_id=stage.id,
            version=3,
            stage_type="spec",
            content=_LONG_ARTIFACT,
            critic_deps={},
            provider="anthropic",
            content_generation_id="gen-1",
        )

    session.commit.assert_not_awaited()
    mock_cost.assert_not_awaited()
    assert stage.quality_gate_status != "advisory"


@pytest.mark.asyncio
async def test_dispatch_critic_review_judge_error_swallowed() -> None:
    """Fail-open: a judge error never raises out of the detached task and never
    touches the already-delivered draft."""
    workspace_id = uuid4()
    stage = _make_stage(workspace_id, "spec")
    stage.current_version = 1
    svc = StageManager(redis_client=_FakeRedis())
    session_local, session = _fake_session_local_for(stage)
    with (
        patch(
            "services.pipeline.stage_manager.critic_review",
            new_callable=AsyncMock,
            side_effect=RuntimeError("judge down"),
        ),
        patch("database.AsyncSessionLocal", session_local),
    ):
        # Must not raise.
        await svc._dispatch_critic_review(
            stage_id=stage.id,
            version=1,
            stage_type="spec",
            content=_LONG_ARTIFACT,
            critic_deps={},
            provider="anthropic",
            content_generation_id="gen-1",
        )

    session_local.assert_not_called()
    session.commit.assert_not_awaited()
    assert stage.quality_gate_status != "advisory"
