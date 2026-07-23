"""Integration tests for the Storyboard orchestration service (T-254).

These exercise the real reliability contract — credit deduction/refund,
idempotency under concurrency, versioning, failure isolation, stale
propagation, and stuck-job recovery — against a live PostgreSQL instance
(``FOR UPDATE`` locking, the unique ``(workspace_id, version)`` backstop, and
the JSONB columns cannot be faithfully faked) and a live Redis (the ``SET NX``
reserve lock). The LLM is mocked via monkeypatch so both the success and
typed-failure paths are deterministic.

Requires TEST_DATABASE_URL; skipped otherwise (CI injects it). Set
TEST_REDIS_URL to point at a live Redis (defaults to db 1 on localhost).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database
from models import Base, CreditLedger, Stage, StageVersion, Storyboard, User, Workspace
from prompts.storyboard import REQUIRED_SECTION_TITLES, StoryboardPayload
from services.credit_service import credit_service
from services.pipeline import storyboard_service
from services.pipeline.storyboard_service import (
    generate_storyboard,
    mark_workspace_storyboards_stale,
    recover_stuck_storyboards,
    regenerate_section,
    regenerate_storyboard,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — integration test skipped.",
)

_ARTIFACTS = {
    "spec": "# Spec\n\n## Overview\nFinalised spec overview content for the keynote.\n",
    "plan": (
        "# Plan\n\n## Architecture\nFastAPI + PostgreSQL + Redis; React SPA.\n\n"
        "## Security Architecture\nCSRF + Fernet-encrypted keys.\n\n"
        "## Capacity Model\n10k DAU, 50 RPS peak.\n\n"
        "## STRIDE\nSpoofing mitigated by OAuth.\n\n"
        "## SLO\n99.9% availability.\n\n"
        "## FMEA\nProvider outage -> circuit breaker.\n"
    ),
    "harness": "# Harness\n\n## Coverage\n40 tests cover 40 requirements.\n",
    "tasks": "# Tasks\n\n## Must-have\n- T-1 MUST ship auth.\n",
}

# The eight architecture planes every architecture_reveal diagram must layer.
_ARCH_LAYER_KINDS = (
    "client",
    "frontend",
    "api",
    "data",
    "llm",
    "integrations",
    "trust",
    "recovery",
)


# ---------------------------------------------------------------------------
# Valid-payload builder (kept aligned with prompts/storyboard.py constraints)
# ---------------------------------------------------------------------------


# One slide type per act, so the two slides an act carries take a coherent type.
_ACT_SLIDE_TYPES = (
    "thesis",
    "product",
    "walkthrough",
    "architecture",
    "trust",
    "closing",
)


def _slide(section_idx: int, slide_idx: int, headline: str, slide_type: str) -> dict:
    sid = f"s{section_idx}-{slide_idx}"
    # Slide 0 of each act is a bullets visual with points; slide 1 is a metric
    # visual. That gives the deck >= 2 distinct visual kinds and a substance
    # descriptor on every slide, so both the P3.4 slide floor and the P3.5 deck
    # quality gate (interior-act substance, monotone-visual check) pass.
    if slide_idx == 0:
        visual = {
            "kind": "bullets",
            "points": ["Concrete point", "Second point", "Third point"],
        }
    else:
        visual = {"kind": "metric", "value": "4 stages", "label": "Pipeline"}
    return {
        "id": sid,
        "type": slide_type,
        "headline": headline,
        "visible_text": "Sparse supporting line.",
        "visual": visual,
        "speaker_notes_ref": sid,
        "sources": ["SPEC", "PLAN"],
    }


def _note(slide_id: str) -> dict:
    return {
        "slide_id": slide_id,
        # >= 120 chars and >= 2 backup points to clear the v1.4 note-depth floor,
        # and distinct from the slide's visible_text so the P3.5 echo check passes.
        "talk_track": (
            "Open on the slide's single idea, then name the concrete product "
            "capability drawn from the finalised sources, explain why it matters "
            "to this audience, and land the takeaway before moving on to the next "
            "beat of the story."
        ),
        "transition": "Move to the next idea.",
        "timing_seconds": 45,
        "pause_cue": "Pause for emphasis.",
        "demo_cue": "",
        "backup_points": ["Backup talking point.", "A second backup point."],
    }


def _payload_dict(
    *, title: str = "Thought2Build Launch Keynote", first_headline: str | None = None
):
    """Build a strict-schema-valid, quality-gate-clean Storyboard payload.

    Two slides per act (12 total, inside the 8-24 quality band) with varied
    visual kinds and per-slide substance, so it validates under the strict schema
    AND clears the deterministic deck quality gate (P3.5).
    """

    sections = []
    notes: dict[str, dict] = {}
    for idx, section_title in enumerate(REQUIRED_SECTION_TITLES):
        slides = []
        for slide_idx in range(2):
            if idx == 0 and slide_idx == 0 and first_headline is not None:
                headline = first_headline
            else:
                headline = f"Act {idx} slide {slide_idx} distinct headline"
            slide = _slide(idx, slide_idx, headline, _ACT_SLIDE_TYPES[idx])
            slides.append(slide)
            notes[slide["id"]] = _note(slide["id"])
        sections.append(
            {
                "id": f"act-{idx}",
                "title": section_title,
                "slides": slides,
            }
        )

    spec_excerpt = "Finalised spec overview content for the keynote."
    plan_excerpt = "FastAPI + PostgreSQL + Redis; React SPA."
    arch_layers = [
        {
            "id": f"layer-{kind}",
            "kind": kind,
            "label": f"{kind.title()} plane",
            "summary": "Plane summary.",
            "source_refs": [
                {
                    "source": "PLAN",
                    "source_id": "PLAN:architecture",
                    "excerpt": plan_excerpt,
                }
            ],
        }
        for kind in _ARCH_LAYER_KINDS
    ]

    return {
        "title": title,
        "theme": {
            "palette": ["#101418", "#1FB6FF", "#F5A623"],
            "typography": "Geometric sans",
            "motif": "Indica glassmorphism",
            "transition_style": "Cinematic fade",
            "diagram_style": "Layered planes",
        },
        "sections": sections,
        "diagrams": [
            {
                "id": "arch-reveal",
                "type": "architecture_reveal",
                "layers": arch_layers,
            }
        ],
        "source_map": {
            slide["id"]: [
                {
                    "source": "SPEC",
                    "source_id": "SPEC:overview",
                    "excerpt": spec_excerpt,
                }
            ]
            for section in sections
            for slide in section["slides"]
        },
        "notes": notes,
        "demo_script_md": "## Walkthrough\n1. Show the editor.\n",
        "technical_appendix_md": "## Appendix\nArchitecture details.\n",
    }


def _fake_llm_returning(payload_obj):
    """A ``complete_with_timeout`` replacement that returns a fixed payload."""

    raw = json.dumps(payload_obj) if not isinstance(payload_obj, str) else payload_obj

    async def _fake(provider, model, system, user, max_tokens, **kwargs):
        return raw

    return _fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    # Wire the credit_service singleton to the same Redis so its cache
    # invalidation hits the store the test inspects. conftest restores the
    # original shared client after the test.
    database._initialize_redis(client)
    # The credit_service singleton memoises its Redis client in ``_redis`` on
    # first use; clear it so each (function-scoped) test rebinds to this loop's
    # fresh client rather than reusing one whose event loop has closed.
    credit_service._redis = None
    yield client
    credit_service._redis = None
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def seed(db_engine):
    """A user (balance 100) + workspace with four finalised stages at v1."""

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"u-{user_id}@x.com",
                google_id=str(user_id),
                credit_balance=100,
            )
        )
        session.add(
            Workspace(
                id=workspace_id,
                user_id=user_id,
                name="Keynote WS",
                problem_statement=(
                    "Build a structured engineering spec generator for teams."
                ),
                provider="anthropic",
                model="claude-sonnet-4-6",
                status="active",
            )
        )
        for stage_type, content in _ARTIFACTS.items():
            stage_id = uuid.uuid4()
            session.add(
                Stage(
                    id=stage_id,
                    workspace_id=workspace_id,
                    type=stage_type,
                    content=content,
                    status="finalised",
                    current_version=1,
                )
            )
            session.add(
                StageVersion(
                    id=uuid.uuid4(),
                    stage_id=stage_id,
                    version=1,
                    content=content,
                    created_by="ai",
                )
            )
        await session.commit()
    return user_id, workspace_id


async def _balance(factory, user_id) -> int:
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return int(result.scalar_one().credit_balance)


async def _ledger(factory, user_id) -> list[CreditLedger]:
    async with factory() as session:
        result = await session.execute(
            select(CreditLedger)
            .where(CreditLedger.user_id == user_id)
            .order_by(CreditLedger.created_at)
        )
        return list(result.scalars())


async def _storyboards(factory, workspace_id) -> list[Storyboard]:
    async with factory() as session:
        result = await session.execute(
            select(Storyboard)
            .where(Storyboard.workspace_id == workspace_id)
            .order_by(Storyboard.version)
        )
        return list(result.scalars())


async def _reload(factory, storyboard_id) -> Storyboard:
    """Re-read a Storyboard from a fresh session.

    Generation now returns the ``generating`` placeholder synchronously and the
    LLM run + finalise happen in a background task with its own session, so the
    object the entrypoint returns reflects the *reserve* state. Tests reload the
    row to observe the settled (``ready``/``failed``) terminal state.
    """

    async with factory() as session:
        result = await session.execute(
            select(Storyboard).where(Storyboard.id == storyboard_id)
        )
        return result.scalar_one()


@pytest_asyncio.fixture
async def inline_generation(db_engine, monkeypatch):
    """Run the background generation inline, against the test engine.

    Production detaches the run onto the event loop with its own
    ``AsyncSessionLocal`` session; here we await it inline and point the
    session-factory seam at the test engine so a generation settles
    deterministically before the test asserts.
    """

    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _await_inline(coro):
        # Run the would-be background coroutine inline. Use `return await` (not
        # a bare `await` expression statement) to avoid a static-analysis false
        # positive such as CodeQL `py/ineffectual-statement` while preserving
        # the intended side effects of awaiting the coroutine; callers ignore
        # the returned value.
        return await coro

    monkeypatch.setattr(storyboard_service, "_spawn_background", _await_inline)
    monkeypatch.setattr(
        storyboard_service, "_session_factory_provider", lambda: factory
    )
    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storyboard_generation_deducts_25_credits(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict()),
    )

    async with factory() as session:
        placeholder = await generate_storyboard(
            session, redis_client, workspace_id, user_id
        )
    # The request returns the generating placeholder; the background run settles it.
    assert placeholder.status == "generating"
    sb = await _reload(factory, placeholder.id)

    assert sb.status == "ready"
    assert sb.version == 1
    assert sb.credit_ledger_id is not None
    assert sb.title == "Thought2Build Launch Keynote"
    # The full validated payload is persisted, plus the typed columns the router
    # and downloads read.
    assert sb.content_json["sections"][0]["title"] == REQUIRED_SECTION_TITLES[0]
    assert "Speaker Notes" in sb.speaker_notes_md
    assert sb.demo_script_md.startswith("## Walkthrough")
    assert sb.source_map_json  # non-empty
    assert set(sb.source_stage_version_ids) == {"spec", "plan", "harness", "tasks"}

    assert await _balance(factory, user_id) == 75
    ledger = await _ledger(factory, user_id)
    assert len(ledger) == 1
    assert ledger[0].amount == -25
    assert ledger[0].reason == f"storyboard_generate:{sb.id}"


@pytest.mark.asyncio
async def test_storyboard_generation_runs_as_a_real_detached_background_task(
    db_engine, redis_client, seed, monkeypatch
):
    """The production path: the request returns ``generating`` and the LLM run is
    detached via ``asyncio.create_task``.

    Deliberately does NOT patch ``_spawn_background`` — only the session-factory
    seam — so the real detachment mechanism (create_task + the strong-ref set) is
    exercised. We then drain ``_BACKGROUND_TASKS`` to await the detached run
    deterministically before asserting it settled the row to ``ready``.
    """

    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(
        storyboard_service, "_session_factory_provider", lambda: factory
    )
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict()),
    )

    async with factory() as session:
        placeholder = await generate_storyboard(
            session, redis_client, workspace_id, user_id
        )
    # The request did not block on the LLM: it returned the generating placeholder
    # and a real detached task was registered.
    assert placeholder.status == "generating"
    assert len(storyboard_service._BACKGROUND_TASKS) == 1

    # Drain the detached task (this is what would otherwise run after the
    # response on the shared event loop).
    await asyncio.gather(*storyboard_service._BACKGROUND_TASKS)
    # Let the done-callback (scheduled via call_soon) run to clear the strong ref.
    await asyncio.sleep(0)

    settled = await _reload(factory, placeholder.id)
    assert settled.status == "ready"
    assert await _balance(factory, user_id) == 75
    # The strong-ref set is cleaned up by the done-callback once the task ends.
    assert len(storyboard_service._BACKGROUND_TASKS) == 0


@pytest.mark.asyncio
async def test_storyboard_generation_refunds_on_llm_failure(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    # Invalid output on the first call and on every repair attempt.
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning("this is not valid json"),
    )

    # The request accepts the job (returns the placeholder); the background run
    # fails, marks the row failed, and refunds. The typed error is swallowed by
    # the background guard, so the entrypoint does not raise.
    async with factory() as session:
        placeholder = await generate_storyboard(
            session, redis_client, workspace_id, user_id
        )
    assert placeholder.status == "generating"

    sbs = await _storyboards(factory, workspace_id)
    assert len(sbs) == 1
    assert sbs[0].status == "failed"
    # Debit -25 then refund +25 => net zero, balance restored.
    assert await _balance(factory, user_id) == 100
    ledger = await _ledger(factory, user_id)
    assert len(ledger) == 2
    assert {e.amount for e in ledger} == {-25, 25}


@pytest.mark.asyncio
async def test_storyboard_background_unexpected_error_fails_and_refunds(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    """An unexpected (non-typed) error in the background run must not strand the
    paid row in ``generating`` — the guard fails + refunds it immediately."""

    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _boom(source):
        raise RuntimeError("unexpected provider/runtime explosion")

    # Raise a non-StoryboardPayloadError from inside the run so it escapes the
    # typed fail+refund path and hits the background guard's generic handler.
    monkeypatch.setattr(storyboard_service, "_complete_and_validate", _boom)

    async with factory() as session:
        placeholder = await generate_storyboard(
            session, redis_client, workspace_id, user_id
        )
    assert placeholder.status == "generating"

    sbs = await _storyboards(factory, workspace_id)
    assert len(sbs) == 1
    assert sbs[0].status == "failed"  # never left hanging in 'generating'
    assert await _balance(factory, user_id) == 100  # debit refunded


@pytest.mark.asyncio
async def test_storyboard_duplicate_generate_does_not_double_charge(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # Slow the LLM so the two concurrent reserves genuinely contend on the
    # workspace row lock and the in-flight-row guard.
    raw = json.dumps(_payload_dict())

    async def _slow_llm(provider, model, system, user, max_tokens, **kwargs):
        await asyncio.sleep(0.2)
        return raw

    monkeypatch.setattr(storyboard_service, "complete_with_timeout", _slow_llm)

    async def _run():
        async with factory() as session:
            return await generate_storyboard(
                session, redis_client, workspace_id, user_id
            )

    results = await asyncio.gather(_run(), _run(), return_exceptions=True)
    assert all(not isinstance(r, Exception) for r in results), results

    sbs = await _storyboards(factory, workspace_id)
    assert len(sbs) == 1  # exactly one Storyboard row
    # Exactly one debit of 25 credits.
    assert await _balance(factory, user_id) == 75
    ledger = await _ledger(factory, user_id)
    debits = [e for e in ledger if e.amount < 0]
    assert len(debits) == 1
    assert debits[0].amount == -25


@pytest.mark.asyncio
async def test_storyboard_duplicate_generate_existing_inflight_row(
    db_engine, redis_client, seed, monkeypatch
):
    """A pre-existing generating row short-circuits a new generate (no charge)."""

    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Storyboard(
                workspace_id=workspace_id,
                user_id=user_id,
                version=1,
                status="generating",
                title="Generating…",
                theme="",
                content_json={},
                speaker_notes_md="",
                demo_script_md="",
                technical_appendix_md="",
                source_map_json={},
                source_stage_version_ids={},
            )
        )
        await session.commit()

    called = {"n": 0}

    async def _counting_llm(*args, **kwargs):
        called["n"] += 1
        return json.dumps(_payload_dict())

    monkeypatch.setattr(storyboard_service, "complete_with_timeout", _counting_llm)

    async with factory() as session:
        sb = await generate_storyboard(session, redis_client, workspace_id, user_id)

    assert sb.status == "generating"  # returned the existing in-flight row
    assert called["n"] == 0  # no LLM call
    assert await _balance(factory, user_id) == 100  # no charge
    assert len(await _storyboards(factory, workspace_id)) == 1


@pytest.mark.asyncio
async def test_storyboard_full_regeneration_preserves_previous_ready_version_on_failure(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # v1: succeeds.
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict(title="V1 Keynote")),
    )
    async with factory() as session:
        v1 = await generate_storyboard(session, redis_client, workspace_id, user_id)
    assert (await _reload(factory, v1.id)).status == "ready"

    # v2 full regeneration: LLM fails. The background run fails + refunds; the
    # entrypoint returns the placeholder rather than raising.
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning("broken output"),
    )
    async with factory() as session:
        await regenerate_storyboard(session, redis_client, v1.id, user_id)

    sbs = await _storyboards(factory, workspace_id)
    assert len(sbs) == 2
    by_version = {sb.version: sb for sb in sbs}
    # The previous ready version is intact and unchanged.
    assert by_version[1].status == "ready"
    assert by_version[1].title == "V1 Keynote"
    # The failed regeneration is its own version row.
    assert by_version[2].status == "failed"
    # 25 (v1) charged; v2 debited 25 then refunded 25 (net zero) => balance 75.
    assert await _balance(factory, user_id) == 75


@pytest.mark.asyncio
async def test_storyboard_section_regeneration_costs_5_credits(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict(first_headline="Original opening headline")),
    )
    async with factory() as session:
        v1_placeholder = await generate_storyboard(
            session, redis_client, workspace_id, user_id
        )
    v1 = await _reload(factory, v1_placeholder.id)
    target_section_id = v1.content_json["sections"][0]["id"]
    v1_second_act = v1.content_json["sections"][1]

    # Section regen returns a full payload with a changed first-act headline.
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict(first_headline="Regenerated opening line")),
    )
    async with factory() as session:
        v2_placeholder = await regenerate_section(
            session, redis_client, v1.id, target_section_id, user_id
        )
    v2 = await _reload(factory, v2_placeholder.id)

    assert v2.status == "ready"
    assert v2.version == 2
    # Only the selected act changed; its id is preserved for stability.
    assert v2.content_json["sections"][0]["id"] == target_section_id
    assert (
        v2.content_json["sections"][0]["slides"][0]["headline"]
        == "Regenerated opening line"
    )
    # A non-target act is carried over verbatim from the base version.
    assert v2.content_json["sections"][1] == v1_second_act
    # 25 (v1) + 5 (section regen) = 30 debited => balance 70.
    assert await _balance(factory, user_id) == 70
    ledger = await _ledger(factory, user_id)
    section_debits = [
        e for e in ledger if e.reason.startswith("storyboard_regenerate_section:")
    ]
    assert len(section_debits) == 1
    assert section_debits[0].amount == -5


@pytest.mark.asyncio
async def test_storyboard_marks_stale_when_source_stage_refinalised(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict()),
    )
    async with factory() as session:
        v1 = await generate_storyboard(session, redis_client, workspace_id, user_id)
    assert (await _reload(factory, v1.id)).status == "ready"

    # Refinalising a source stage marks the ready keynote stale. Drive it through
    # the same helper StageManager.finalise() calls inside its transaction.
    async with factory() as session:
        await mark_workspace_storyboards_stale(session, workspace_id)
        await session.commit()

    sbs = await _storyboards(factory, workspace_id)
    assert len(sbs) == 1
    assert sbs[0].status == "stale"


@pytest.mark.asyncio
async def test_storyboard_finalise_marks_ready_storyboards_stale(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    """End-to-end: StageManager.finalise() propagates stale in one transaction."""

    from services.pipeline.stage_manager import StageManager

    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(
        storyboard_service,
        "complete_with_timeout",
        _fake_llm_returning(_payload_dict()),
    )
    async with factory() as session:
        v1 = await generate_storyboard(session, redis_client, workspace_id, user_id)
    assert (await _reload(factory, v1.id)).status == "ready"

    # Reset the 'tasks' stage to draft so finalise() has a draft to advance.
    async with factory() as session:
        result = await session.execute(
            select(Stage).where(
                Stage.workspace_id == workspace_id, Stage.type == "tasks"
            )
        )
        stage = result.scalar_one()
        stage.status = "draft"
        await session.commit()
        stage_id = stage.id

    class _U:
        id = user_id

    manager = StageManager(redis_client=redis_client)
    async with factory() as session:
        await manager.finalise(stage_id, _U(), session)

    sbs = await _storyboards(factory, workspace_id)
    assert sbs[0].status == "stale"


@pytest.mark.asyncio
async def test_storyboard_recovery_fails_and_refunds_stuck_generating(
    db_engine, redis_client, seed
):
    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # A stuck 'generating' row with a real debit ledger entry, aged past the
    # threshold.
    from datetime import UTC, datetime, timedelta

    async with factory() as session:
        deduction = await credit_service.deduct(
            session, user_id, 25, "storyboard_generate:stuck"
        )
        old = datetime.now(UTC) - timedelta(minutes=31)
        sb = Storyboard(
            workspace_id=workspace_id,
            user_id=user_id,
            version=1,
            status="generating",
            title="Generating…",
            theme="",
            content_json={},
            speaker_notes_md="",
            demo_script_md="",
            technical_appendix_md="",
            source_map_json={},
            source_stage_version_ids={},
            credit_ledger_id=deduction.id,
            created_at=old,
            updated_at=old,
        )
        session.add(sb)
        await session.commit()
        sb_id = sb.id

    assert await _balance(factory, user_id) == 75

    async with factory() as session:
        recovered = await recover_stuck_storyboards(session)
    assert recovered == 1

    async with factory() as session:
        result = await session.execute(select(Storyboard).where(Storyboard.id == sb_id))
        assert result.scalar_one().status == "failed"
    # Refunded back to 100.
    assert await _balance(factory, user_id) == 100

    # Idempotent: a second recovery pass finds nothing and does not double-refund.
    async with factory() as session:
        assert await recover_stuck_storyboards(session) == 0
    assert await _balance(factory, user_id) == 100


@pytest.mark.asyncio
async def test_storyboard_generation_requires_all_stages_finalised(
    db_engine, redis_client, seed, monkeypatch
):
    """Unfinalised sources fail closed before any debit or placeholder row."""

    from services.pipeline.storyboard_source import StoryboardStagesNotFinalisedError

    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # Knock one source stage out of 'finalised'.
    async with factory() as session:
        result = await session.execute(
            select(Stage).where(
                Stage.workspace_id == workspace_id, Stage.type == "plan"
            )
        )
        result.scalar_one().status = "draft"
        await session.commit()

    async def _should_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("LLM must not be called when stages are not finalised")

    monkeypatch.setattr(
        storyboard_service, "complete_with_timeout", _should_not_be_called
    )

    async with factory() as session:
        with pytest.raises(StoryboardStagesNotFinalisedError):
            await generate_storyboard(session, redis_client, workspace_id, user_id)

    assert await _balance(factory, user_id) == 100
    assert len(await _storyboards(factory, workspace_id)) == 0


@pytest.mark.asyncio
async def test_storyboard_validates_spliced_section_payload(
    db_engine, redis_client, seed, monkeypatch, inline_generation
):
    """Section regen re-validates the whole payload after the splice."""

    user_id, workspace_id = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    valid = _payload_dict()
    monkeypatch.setattr(
        storyboard_service, "complete_with_timeout", _fake_llm_returning(valid)
    )
    async with factory() as session:
        v1_placeholder = await generate_storyboard(
            session, redis_client, workspace_id, user_id
        )
    v1 = await _reload(factory, v1_placeholder.id)
    target = v1.content_json["sections"][0]["id"]

    # Whole-payload validity is asserted independently so the splice contract is
    # explicit: the persisted v1 content must itself validate.
    StoryboardPayload.model_validate(v1.content_json)

    # Section regen with a payload missing a required act -> fails validation,
    # refunds, leaves v1 intact. The background run swallows the typed error after
    # marking the row failed, so the entrypoint returns the placeholder.
    broken = _payload_dict()
    broken["sections"] = broken["sections"][:5]  # only 5 acts
    monkeypatch.setattr(
        storyboard_service, "complete_with_timeout", _fake_llm_returning(broken)
    )
    async with factory() as session:
        await regenerate_section(session, redis_client, v1.id, target, user_id)

    sbs = await _storyboards(factory, workspace_id)
    by_version = {sb.version: sb for sb in sbs}
    assert by_version[1].status == "ready"
    assert by_version[2].status == "failed"
    # 25 (v1) + 5 (failed section) - 5 refund = 75.
    assert await _balance(factory, user_id) == 75
