"""Behavioural tests for delta-aware increment generation (Phase 21 — T-279).

These run against the real database (migrations applied) so the increment row,
the grown TASKS ``StageVersion``, and credit accounting are exercised end to end.
The only thing stubbed is the LLM call itself.

The load-bearing property under test is ``task_ref`` stability: an increment must
emit the *same* content-derived ``task_ref`` for an unchanged task (so T-280
updates its existing issue instead of duplicating it), pin every baseline task's
ref unchanged, and drop any task the model re-emits from the baseline.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import Increment, Stage, StageVersion, User, Workspace
from schemas.increment import IncrementCreate
from services.credit_service import credit_service
from services.integrations.task_parser import compute_task_ref
from services.pipeline.increment_service import (
    _BASELINE_CONTEXT_LIMITS,
    INCREMENT_COMPLETION_SENTINEL,
    INCREMENT_CREDIT_COST,
    INCREMENT_PROMPT_VERSION,
    INCREMENT_STUCK_THRESHOLD_MINUTES,
    IncrementError,
    IncrementModeNotSupportedError,
    IncrementService,
    _grow_tasks_markdown,
    _highest_task_number,
    _reconcile_delta,
    _strip_increment_sentinel,
    _system_prompt,
    _user_prompt,
    recover_stuck_increments,
)

BASELINE_TASKS = (
    "# Tasks\n\n"
    "### T-001: Set up project structure\n\n"
    "**Description:** Lay out the repository skeleton.\n\n"
    "### T-002: Build the parser\n\n"
    "**Description:** Implement the deterministic parser.\n"
)


class _FakeRedis:
    """In-memory Redis stand-in for the balance-cache + stage-cache deletes.

    pytest-asyncio gives each test a fresh event loop; a real Redis client cached
    on the ``credit_service`` singleton from an earlier test is bound to a closed
    loop and breaks on reuse. Injecting this keeps cache ops loop-safe.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value, ex: int | None = None) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)


@pytest.fixture(autouse=True)
def _isolate_credit_redis():
    """Give ``credit_service`` a loop-safe fake redis for the duration of a test."""
    original = credit_service._redis
    credit_service._redis = _FakeRedis()
    yield
    credit_service._redis = original


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(
        email=f"inc-gen-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="T",
        avatar_url=None,
        credit_balance=100,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    user_id = u.id
    yield u
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


@pytest.fixture
async def workspace(session: AsyncSession, user: User) -> Workspace:
    ws = Workspace(
        user_id=user.id,
        name="Inc Gen WS",
        problem_statement="x" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)
    ws_id = ws.id

    # Four finalised stages, each with a StageVersion at current_version=1 so the
    # baseline is a real, pinnable timeline.
    for stage_type, content in (
        ("spec", "# Spec\n\nThe product does things."),
        ("plan", "# Plan\n\nThe architecture."),
        ("harness", "# Harness\n\ndef test_x(): assert True"),
        ("tasks", BASELINE_TASKS),
    ):
        stage = Stage(
            workspace_id=ws.id,
            type=stage_type,
            content=content,
            status="finalised",
            current_version=1,
            finalised_at=datetime.now(UTC),
        )
        session.add(stage)
        await session.flush()
        session.add(
            StageVersion(stage_id=stage.id, version=1, content=content, created_by="ai")
        )
    await session.commit()

    yield ws

    await session.execute(delete(Increment).where(Increment.workspace_id == ws_id))
    await session.execute(delete(Stage).where(Stage.workspace_id == ws_id))
    await session.execute(delete(Workspace).where(Workspace.id == ws_id))
    await session.commit()


def _service_with_completion(completion: str) -> tuple[IncrementService, MagicMock]:
    adapter = MagicMock()
    adapter.complete = AsyncMock(return_value=completion)
    # A naturally finished response: without this, MagicMock auto-creates a
    # truthy last_completion.stopped_by_limit and the M9 truncation check
    # wrongly fails the increment.
    adapter.last_completion = None
    svc = IncrementService(redis_client=_FakeRedis())
    return svc, adapter


# ---------------------------------------------------------------------------
# Pure-function behaviour (no DB)
# ---------------------------------------------------------------------------


def test_system_prompt_treats_baseline_as_immutable() -> None:
    prompt = _system_prompt()
    assert "IMMUTABLE" in prompt
    assert "MUST NOT rewrite" in prompt
    # An increment must be a delta — the prompt must forbid reproducing baseline
    # tasks (the failure mode that regresses into a full regeneration).
    assert "delta" in prompt.lower()
    assert "reproduce any task it already contains" in prompt


@pytest.mark.asyncio
async def test_increment_generation_records_increment_prompt_version(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """Finding #10 (process): increment_service.py was one of three prompts
    with no version constant, so telemetry recorded the InstrumentedAdapter
    default prompt_version="local" for every call — an edit to _system_prompt
    or _user_prompt was invisible to the cost-ledger/telemetry that every
    other core-gen surface relies on for regression detection.
    """
    completion = "### T-003: Add billing\n\n**Description:** Stripe checkout.\n"
    svc, adapter = _service_with_completion(completion)

    captured: dict[str, object] = {}
    real_adapter = AsyncMock()
    real_adapter.complete = AsyncMock(return_value=completion)
    real_adapter.last_completion = None  # naturally finished (no truncation)

    def _fake_instrumented_adapter(*args, **kwargs):
        captured.update(kwargs)
        return real_adapter

    with (
        patch("services.pipeline.increment_service.get_llm", return_value=adapter),
        patch(
            "services.pipeline.increment_service.InstrumentedAdapter",
            side_effect=_fake_instrumented_adapter,
        ),
    ):
        await svc.generate_increment(workspace.id, "add billing", user, session)

    assert captured["prompt_version"] == INCREMENT_PROMPT_VERSION
    assert captured["prompt_version"] != "local"


def test_highest_task_number_finds_max() -> None:
    assert _highest_task_number(BASELINE_TASKS) == 2
    assert _highest_task_number("no tasks here") == 0


def test_system_prompt_requires_completion_sentinel() -> None:
    """Audit M9: the prompt must demand the versioned completion sentinel as
    the final line so silent truncation is detectable, and must tell the model
    elided baseline regions exist rather than treating them as absent."""
    prompt = _system_prompt()
    assert INCREMENT_COMPLETION_SENTINEL in prompt
    assert "exact sentinel on its own final line" in prompt
    assert "treat elided content as existing, never as absent" in prompt


def test_strip_increment_sentinel_round_trip() -> None:
    body = "### T-003: Add billing\n\n**Description:** Stripe checkout."
    with_sentinel = f"{body}\n{INCREMENT_COMPLETION_SENTINEL}\n"
    stripped, present = _strip_increment_sentinel(with_sentinel)
    assert present is True
    assert stripped == body
    assert INCREMENT_COMPLETION_SENTINEL not in stripped

    # Absent sentinel: content untouched, reported missing.
    unchanged, present = _strip_increment_sentinel(body)
    assert present is False
    assert unchanged == body

    # A sentinel mid-document (e.g. quoted in a task body) is NOT the final
    # line and must not be stripped.
    mid = f"{body}\n{INCREMENT_COMPLETION_SENTINEL}\nmore content"
    unchanged_mid, present = _strip_increment_sentinel(mid)
    assert present is False
    assert unchanged_mid == mid


def _stage_stub(content: str):
    from types import SimpleNamespace

    return SimpleNamespace(content=content)


def test_user_prompt_bounds_oversized_baseline_artifacts() -> None:
    """Audit M9: the baseline previously flowed into the prompt unbounded — a
    mature workspace could exceed the model context and fail the increment
    outright. Each artifact gets its own budget; the tasks tail (the highest
    T-NNN numbers, which numbering continuity depends on) must survive."""
    huge_tasks = "# Tasks\n\n" + "\n\n".join(
        f"### T-{n:03d}: Task number {n}\n\n**Description:** " + "d" * 700
        for n in range(1, 201)
    )
    assert len(huge_tasks) > _BASELINE_CONTEXT_LIMITS["tasks"]
    stages = {
        "spec": _stage_stub("SPEC_HEAD " + "s" * 80_000),
        "plan": _stage_stub("PLAN_HEAD " + "p" * 80_000),
        "harness": _stage_stub("HARNESS_HEAD " + "h" * 60_000),
        "tasks": _stage_stub(huge_tasks),
    }

    prompt = _user_prompt(stages, "add billing to the product", baseline_max=200)

    assert "characters omitted for context budget" in prompt
    # Head of every artifact survives head+tail bounding.
    for marker in ("SPEC_HEAD", "PLAN_HEAD", "HARNESS_HEAD", "# Tasks"):
        assert marker in prompt
    # The tasks TAIL survives: the highest task number is what the model must
    # continue numbering after.
    assert "### T-200: Task number 200" in prompt
    assert "Start numbering at T-201" in prompt
    # Total prompt stays within the summed per-artifact budgets plus fence and
    # instruction overhead — never proportional to the unbounded baseline.
    assert len(prompt) < sum(_BASELINE_CONTEXT_LIMITS.values()) + 5_000


def test_user_prompt_small_baseline_untouched() -> None:
    """Bounding is a no-op for ordinary baselines — no elision markers."""
    stages = {
        "spec": _stage_stub("# Spec\nsmall"),
        "plan": _stage_stub("# Plan\nsmall"),
        "harness": _stage_stub("# Harness\nsmall"),
        "tasks": _stage_stub(BASELINE_TASKS),
    }
    prompt = _user_prompt(stages, "add billing to the product", baseline_max=2)
    assert "characters omitted" not in prompt
    assert "### T-002: Build the parser" in prompt


def test_increment_request_rejects_underspecified_random_words() -> None:
    with pytest.raises(ValidationError, match="at least 4 words and 20 characters"):
        IncrementCreate(feature_request="nest idea")

    request = IncrementCreate(
        feature_request="  Add team invitations for administrators  "
    )
    assert request.feature_request == "Add team invitations for administrators"


def test_reconcile_delta_pins_and_renumbers() -> None:
    pinned = {
        compute_task_ref("Set up project structure"),
        compute_task_ref("Build the parser"),
    }
    completion = (
        "### T-001: Build the parser\n\n"  # re-emitted baseline → must be dropped
        "**Description:** restated.\n\n"
        "### T-002: Add billing\n\n"
        "**Description:** Stripe checkout.\n\n"
        "### T-003: Add billing\n\n"  # intra-delta duplicate → must be dropped
        "**Description:** dup.\n"
    )
    new = _reconcile_delta(completion, pinned, baseline_max=2)
    assert [t.title for t in new] == ["Add billing"]
    # Renumbered to continue after the highest baseline number.
    assert new[0].human_ref == "T-003"
    assert new[0].task_ref == compute_task_ref("Add billing")


def test_grow_tasks_markdown_appends_and_pins_baseline() -> None:
    new = _reconcile_delta(
        "### T-001: Add billing\n\n**Description:** Stripe.\n", set(), baseline_max=2
    )
    grown = _grow_tasks_markdown(BASELINE_TASKS, new)
    # Baseline preserved verbatim ...
    assert "### T-001: Set up project structure" in grown
    assert "### T-002: Build the parser" in grown
    # ... and the new task appended under a continuing number.
    assert "### T-003: Add billing" in grown
    assert grown.index("Set up project structure") < grown.index("Add billing")


def test_increment_generation_uses_cheap_primary_tasks_route(monkeypatch) -> None:
    # Pin the cheap-primary policy on so this test exercises that path
    # explicitly, independent of the product default.
    from services.llm import provider_status, tier_policy

    monkeypatch.setattr(tier_policy.settings, "core_cheap_primary", True)
    monkeypatch.setattr(provider_status, "can_route", lambda *_args: True)
    monkeypatch.setattr(
        provider_status,
        "is_provider_configured",
        lambda provider: provider == "anthropic",
    )
    monkeypatch.setattr(
        "services.pipeline.increment_service.platform_provider_priority",
        lambda: ("anthropic", "openai", "google"),
    )
    monkeypatch.setattr(
        "services.llm.routing.platform_provider_priority",
        lambda: ("anthropic", "openai", "google"),
    )

    workspace = MagicMock()
    workspace.provider = "anthropic"

    route = IncrementService(redis_client=_FakeRedis())._resolve_route(workspace)

    assert route.operation == "tasks.generate"
    assert route.provider in {"anthropic", "openai", "google"}
    # Increment now follows the product-wide cheap-primary→mid policy, like core
    # TASKS generation: the cheap tier (Haiku 4.5) is the primary and mid
    # (Sonnet 4.6) is the one-shot escalation (issue #17 follow-up).
    assert route.model == "claude-haiku-4-5-20251001"
    assert route.model_tier == "small"
    assert route.fallback_tier == "mid"
    assert route.selection_reason == "active_default"


# ---------------------------------------------------------------------------
# End-to-end generation against the DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_generation_pins_existing_task_refs(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """Acceptance criterion 2/3: 'add two features' appends tasks; existing tasks
    keep their refs; regenerating with a re-emitted task keeps a single, stable
    ref instead of duplicating it."""
    completion = (
        "### T-003: Add billing\n\n"
        "**Description:** Stripe checkout and credit packs.\n\n"
        "### T-004: Add dark mode\n\n"
        "**Description:** A theme toggle.\n"
    )
    svc, adapter = _service_with_completion(completion)

    with patch("services.pipeline.increment_service.get_llm", return_value=adapter):
        result = await svc.generate_increment(
            workspace.id, "add billing and dark mode", user, session
        )

    # Two new tasks, renumbered after the baseline, with content-derived refs.
    assert [t.title for t in result.new_tasks] == ["Add billing", "Add dark mode"]
    assert [t.human_ref for t in result.new_tasks] == ["T-003", "T-004"]
    assert result.new_tasks[0].task_ref == compute_task_ref("Add billing")
    assert result.new_tasks[1].task_ref == compute_task_ref("Add dark mode")

    # Every baseline task's ref is pinned, unchanged.
    assert result.pinned_task_refs == [
        compute_task_ref("Set up project structure"),
        compute_task_ref("Build the parser"),
    ]

    # The increment row is ready and pins the baseline versions.
    inc = (
        await session.execute(
            select(Increment).where(Increment.id == result.increment_id)
        )
    ).scalar_one()
    assert inc.status == "ready"
    assert inc.sequence == 1
    assert len(inc.baseline_version_ids) == 4

    # TASKS.md grew by one version and now carries all four tasks.
    tasks_stage = (
        await session.execute(
            select(Stage).where(
                Stage.workspace_id == workspace.id, Stage.type == "tasks"
            )
        )
    ).scalar_one()
    assert tasks_stage.current_version == 2
    assert tasks_stage.status == "finalised"  # additive — never re-gated
    for title in (
        "Set up project structure",
        "Build the parser",
        "Add billing",
        "Add dark mode",
    ):
        assert title in tasks_stage.content

    # Credit was charged exactly the increment price.
    await session.refresh(user)
    assert user.credit_balance == 100 - INCREMENT_CREDIT_COST

    # --- Regenerate: the model re-emits an existing baseline task. Its ref is
    # already pinned, so it is dropped (no duplicate); only the genuinely new
    # task is appended, and the baseline task keeps its original ref.
    second_completion = (
        "### T-001: Set up project structure\n\n"  # re-emitted → dropped
        "**Description:** restated baseline.\n\n"
        "### T-009: Add search\n\n"
        "**Description:** Full-text search.\n"
    )
    svc2, adapter2 = _service_with_completion(second_completion)
    with patch("services.pipeline.increment_service.get_llm", return_value=adapter2):
        result2 = await svc2.generate_increment(
            workspace.id, "add search", user, session
        )

    assert [t.title for t in result2.new_tasks] == ["Add search"]
    # The re-emitted baseline task kept its stable ref and was not duplicated.
    assert compute_task_ref("Set up project structure") in result2.pinned_task_refs
    assert result2.sequence == 2


@pytest.mark.asyncio
async def test_increment_refund_on_validation_failure(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """A failing generation refunds the credit and leaves a retryable draft."""
    # An empty/no-task completion yields no new tasks → IncrementGenerationError.
    svc, adapter = _service_with_completion("No new tasks are needed.")
    with patch("services.pipeline.increment_service.get_llm", return_value=adapter):
        with pytest.raises(Exception):
            await svc.generate_increment(workspace.id, "nothing really", user, session)

    await session.refresh(user)
    assert user.credit_balance == 100  # fully refunded

    # The increment row survives as a retryable draft (not stuck 'generating').
    rows = (
        (
            await session.execute(
                select(Increment).where(Increment.workspace_id == workspace.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(r.status == "draft" for r in rows)


@pytest.mark.asyncio
async def test_increment_truncated_output_fails_and_refunds(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """Audit M9: a provider hard-stop on the output cap means the delta is cut
    mid-task — silently appending it would corrupt the grown TASKS.md. The
    objective stopped_by_limit signal fails the increment, refunds, and leaves
    a retryable draft; the parseable-looking prefix is never persisted."""
    truncated = (
        "### T-003: Add billing\n\n"
        "**Description:** Stripe checkout.\n\n"
        "### T-004: Add dark mo"  # cut mid-title by the cap
    )
    svc, adapter = _service_with_completion(truncated)
    adapter.last_completion = MagicMock(stopped_by_limit=True, usage=None)

    with patch("services.pipeline.increment_service.get_llm", return_value=adapter):
        with pytest.raises(IncrementError, match="output-token cap"):
            await svc.generate_increment(workspace.id, "add billing", user, session)

    await session.refresh(user)
    assert user.credit_balance == 100  # fully refunded

    rows = (
        (
            await session.execute(
                select(Increment).where(Increment.workspace_id == workspace.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(r.status == "draft" for r in rows)

    # The truncated delta never reached TASKS.md.
    tasks_stage = (
        await session.execute(
            select(Stage).where(
                Stage.workspace_id == workspace.id, Stage.type == "tasks"
            )
        )
    ).scalar_one()
    assert tasks_stage.current_version == 1
    assert "Add billing" not in tasks_stage.content


@pytest.mark.asyncio
async def test_increment_sentinel_is_stripped_from_grown_tasks(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """A completion ending with the sentinel succeeds, and the sentinel never
    lands inside the grown TASKS.md (it would sit in the final task's body)."""
    completion = (
        "### T-003: Add billing\n\n"
        "**Description:** Stripe checkout.\n"
        f"{INCREMENT_COMPLETION_SENTINEL}\n"
    )
    svc, adapter = _service_with_completion(completion)

    with patch("services.pipeline.increment_service.get_llm", return_value=adapter):
        result = await svc.generate_increment(
            workspace.id, "add billing please", user, session
        )

    assert [t.title for t in result.new_tasks] == ["Add billing"]
    tasks_stage = (
        await session.execute(
            select(Stage).where(
                Stage.workspace_id == workspace.id, Stage.type == "tasks"
            )
        )
    ).scalar_one()
    assert "### T-003: Add billing" in tasks_stage.content
    assert INCREMENT_COMPLETION_SENTINEL not in tasks_stage.content


@pytest.mark.asyncio
async def test_increment_cancellation_refunds_and_clears_generating_state(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    svc, adapter = _service_with_completion("unused")
    adapter.complete = AsyncMock(side_effect=asyncio.CancelledError)

    with patch("services.pipeline.increment_service.get_llm", return_value=adapter):
        with pytest.raises(asyncio.CancelledError):
            await svc.generate_increment(
                workspace.id,
                "Add team invitations for administrators",
                user,
                session,
            )

    await session.refresh(user)
    assert user.credit_balance == 100
    increment = (
        await session.execute(
            select(Increment).where(Increment.workspace_id == workspace.id)
        )
    ).scalar_one()
    assert increment.status == "draft"


@pytest.mark.asyncio
async def test_recover_stuck_increment_refunds_and_resets(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """A 'generating' increment whose in-request refund never ran (hard death) is
    refunded and reset to a retryable draft by the recovery sweep (finding #7),
    and a second sweep is an idempotent no-op."""
    from datetime import timedelta

    # Charge-then-generate leaves a committed deduction pinned on a 'generating'
    # row; simulate the strand by committing exactly that, aged past the cutoff.
    deduction = await credit_service.deduct(
        session, user.id, INCREMENT_CREDIT_COST, "increment"
    )
    await session.commit()
    await session.refresh(user)
    assert user.credit_balance == 100 - INCREMENT_CREDIT_COST

    stuck = Increment(
        workspace_id=workspace.id,
        sequence=1,
        title="stranded increment",
        status="generating",
        baseline_version_ids=[],
        deduction_ledger_id=deduction.id,
        updated_at=datetime.now(UTC)
        - timedelta(minutes=INCREMENT_STUCK_THRESHOLD_MINUTES + 5),
    )
    session.add(stuck)
    await session.commit()
    stuck_id = stuck.id

    recovered = await recover_stuck_increments(session)
    assert recovered == 1

    refreshed = (
        await session.execute(select(Increment).where(Increment.id == stuck_id))
    ).scalar_one()
    assert refreshed.status == "draft"
    await session.refresh(user)
    assert user.credit_balance == 100  # fully refunded

    # Idempotent: the row is no longer 'generating', so a second sweep is a no-op
    # and the balance is unchanged (refund reason is unique-constrained anyway).
    recovered_again = await recover_stuck_increments(session)
    assert recovered_again == 0
    await session.refresh(user)
    assert user.credit_balance == 100


@pytest.mark.asyncio
async def test_finalise_increment_does_not_resurrect_a_reset_row(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """The Tx2 race guard: if the recovery sweep already reset the increment to
    'draft' (a stall far longer than the LLM timeout), finalise must NOT resurrect
    it into 'ready' or append a TASKS version (audit finding #6/#7 race guard)."""
    from sqlalchemy import func as sa_func

    from services.pipeline.increment_service import IncrementGenerationError

    ws_id = workspace.id
    svc = IncrementService(redis_client=_FakeRedis())
    reset = Increment(
        workspace_id=ws_id,
        sequence=1,
        title="already recovered",
        status="draft",  # the sweep beat us to it
        baseline_version_ids=[],
    )
    session.add(reset)
    await session.commit()
    reset_id = reset.id

    tasks_stage = (
        await session.execute(
            select(Stage).where(Stage.workspace_id == ws_id, Stage.type == "tasks")
        )
    ).scalar_one()
    tasks_stage_id = tasks_stage.id
    versions_before = (
        await session.execute(
            select(sa_func.count())
            .select_from(StageVersion)
            .where(StageVersion.stage_id == tasks_stage_id)
        )
    ).scalar_one()

    with pytest.raises(IncrementGenerationError):
        await svc._finalise_increment(
            session, reset_id, tasks_stage, BASELINE_TASKS + "\n### T-003: New\n"
        )

    await session.rollback()
    # The TASKS stage was never grown — no orphaned version against a reset row.
    versions_after = (
        await session.execute(
            select(sa_func.count())
            .select_from(StageVersion)
            .where(StageVersion.stage_id == tasks_stage_id)
        )
    ).scalar_one()
    assert versions_after == versions_before
    # And the row stays 'draft' — never resurrected to 'ready'.
    status_after = (
        await session.execute(select(Increment.status).where(Increment.id == reset_id))
    ).scalar_one()
    assert status_after == "draft"


@pytest.mark.asyncio
async def test_recover_skips_recent_generating_increment(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """An increment within the stuck threshold (a legitimately in-flight one) is
    never swept — the threshold sits far above the hard LLM timeout."""
    from datetime import timedelta

    fresh = Increment(
        workspace_id=workspace.id,
        sequence=1,
        title="in-flight increment",
        status="generating",
        baseline_version_ids=[],
        deduction_ledger_id=None,
        updated_at=datetime.now(UTC)
        - timedelta(minutes=INCREMENT_STUCK_THRESHOLD_MINUTES - 5),
    )
    session.add(fresh)
    await session.commit()
    fresh_id = fresh.id

    recovered = await recover_stuck_increments(session)
    assert recovered == 0
    refreshed = (
        await session.execute(select(Increment).where(Increment.id == fresh_id))
    ).scalar_one()
    assert refreshed.status == "generating"


@pytest.mark.asyncio
async def test_behaviour_changing_increment_is_gated_off(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    svc = IncrementService(redis_client=_FakeRedis())
    assert settings.increment_blast_radius_enabled is False
    with pytest.raises(IncrementModeNotSupportedError):
        await svc.generate_increment(
            workspace.id,
            "change the auth flow",
            user,
            session,
            mode="behaviour_changing",
        )
    # No credit spent on a rejected mode.
    await session.refresh(user)
    assert user.credit_balance == 100
