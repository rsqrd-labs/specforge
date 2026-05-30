"""Storyboard service orchestration, credits, idempotency, and recovery (T-254).

This is the reliability core of the Storyboard feature. It owns the full
lifecycle of a generated keynote: source extraction, the LLM call, strict
payload validation, credit deduction/refund, versioning, idempotency, stale
propagation, and stuck-job recovery.

Transaction boundaries (the heart of the design — see req 8 of T-254)
---------------------------------------------------------------------
A slow LLM call must never be wrapped in an open DB transaction. So generation
is split across two committed transactions with the LLM call in between:

* **Tx1 — reserve.** Lock the workspace row ``FOR UPDATE`` (serialises version
  assignment), insert a ``generating`` placeholder at the next version, debit
  the credits, store the ledger id, and commit. If the debit raises
  ``InsufficientCreditsError`` the whole transaction rolls back, so no orphan
  placeholder and no charge survive. The committed ``generating`` row is the
  durable marker the recovery loop keys off.
* **(no transaction) — generate.** Release the Redis idempotency lock, then run
  the LLM completion and strict validation. Nothing is held open here.
* **Tx2 — finalise.** Reload the placeholder ``FOR UPDATE``. On success persist
  the validated payload and flip to ``ready``; on failure flip to ``failed``,
  refund exactly once (the credit ledger refund path is itself idempotent), and
  commit. A failure therefore never mutates a previously ``ready`` version —
  each generation is a brand-new version row.

Idempotency is defended in three composed layers so a flaky Redis can never
cause a double charge:

1. a short-TTL Redis ``SET NX`` lock around *only* the reserve section,
2. an "is there already a ``generating`` row for this (workspace, user)?" check
   that returns the in-flight row without charging (covers a retry after the
   lock TTL lapses), and
3. the ``unique (workspace_id, version)`` constraint as the final DB backstop.

Privacy: no raw generated payload, source excerpt, speaker note, demo script,
or appendix text is ever logged. Failure reasons are coarse, content-free
labels.
"""

from __future__ import annotations

import copy
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import CreditLedger, Storyboard, Workspace
from prompts.storyboard import (
    SYSTEM_PROMPT,
    StoryboardPayload,
    StoryboardPayloadError,
    build_repair_user_prompt,
    build_user_prompt,
    parse_and_validate_payload,
)
from services.credit_service import InsufficientCreditsError, credit_service
from services.llm.base import ProviderError
from services.llm.gateway import complete_with_timeout
from services.observability import (
    get_structured_logger,
    record_storyboard_credits_deducted,
    record_storyboard_credits_refunded,
    record_storyboard_generation_completed,
    record_storyboard_generation_duration,
    record_storyboard_generation_failed,
    record_storyboard_generation_started,
    record_storyboard_section_regenerated,
)
from services.pipeline.storyboard_source import (
    StoryboardSourcePackage,
    build_storyboard_source,
)

logger = get_structured_logger(__name__)

# Credit costs (Storyboard Delivery Directive §2).
COST_FULL_GENERATION = 25
COST_SECTION_REGENERATION = 5

# Action labels for metrics, log events, and credit ledger reasons.
ACTION_GENERATE = "generate"
ACTION_REGENERATE = "regenerate"
ACTION_REGENERATE_SECTION = "regenerate_section"
_CREDIT_COST_BY_ACTION = {
    ACTION_GENERATE: COST_FULL_GENERATION,
    ACTION_REGENERATE: COST_FULL_GENERATION,
    ACTION_REGENERATE_SECTION: COST_SECTION_REGENERATION,
}

# Short TTL on the per-(workspace, user) reserve lock. It only needs to span the
# reserve transaction; it is always released before the slow LLM call, and a
# crash that strands it expires within this window. The DB ``generating`` row is
# the real long-window guard, so this is deliberately short.
_RESERVE_LOCK_TTL_SECONDS = 30

# Generated keynote payloads are large (six acts, slides, per-slide notes, demo
# script, technical appendix). Sized above the largest stage budget; the gateway
# still applies its hard wall-clock timeout on top.
_OUTPUT_TOKEN_BUDGET = 12288

# A ``generating`` Storyboard older than this is considered stuck and is failed +
# refunded by the recovery loop (T-254 req 7). Distinct from the 3-minute stage
# threshold: keynote generation is a single long completion, not a stream.
STUCK_THRESHOLD_MINUTES = 30

_PRESENTABLE = frozenset({"ready", "stale"})
_FORBIDDEN_VIDEO_DEMO_RE = re.compile(
    r"\b(video|recorded|recording)\s+(demo|demonstration|walkthrough)\b|"
    r"\b(demo|demonstration|walkthrough)\s+video\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Typed errors (consumed by the router for HTTP mapping; the persisted row only
# records ``status='failed'`` — there is no error column, so the typed reason is
# carried to the synchronous caller via these exceptions, never logged raw).
# ---------------------------------------------------------------------------


class StoryboardServiceError(Exception):
    """Base class for Storyboard service failures."""


class StoryboardGenerationError(StoryboardServiceError):
    """Generation failed after the credit debit; the credit has been refunded.

    ``error_type`` is a coarse, content-free reason ('payload_parse',
    'payload_schema', 'provider', 'timeout', 'unexpected'). ``detail`` is a
    redaction-safe summary (field locations/messages only) suitable for the UI.
    """

    def __init__(self, error_type: str, detail: str) -> None:
        self.error_type = error_type
        self.detail = detail
        super().__init__(f"storyboard generation failed ({error_type}): {detail}")


class StoryboardNotFoundError(StoryboardServiceError):
    """The Storyboard does not exist or is not owned by the caller."""


class StoryboardSectionNotFoundError(StoryboardServiceError):
    """The requested section id is not present in the base Storyboard payload."""


class StoryboardNotPresentableError(StoryboardServiceError):
    """Section regeneration was requested against a non-ready base version."""


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def generate_storyboard(
    db: AsyncSession,
    redis: Redis,
    workspace_id: UUID,
    user_id: UUID,
) -> Storyboard:
    """Generate a brand-new Storyboard from a workspace's finalised stages."""

    return await _generate_full(
        db, redis, workspace_id, user_id, action=ACTION_GENERATE
    )


async def regenerate_storyboard(
    db: AsyncSession,
    redis: Redis,
    storyboard_id: UUID,
    user_id: UUID,
) -> Storyboard:
    """Full regeneration into a new version (25 credits).

    Resolves the workspace from the owner-scoped Storyboard, then runs the same
    flow as ``generate_storyboard``: a new version row is created so the previous
    ``ready`` version is never mutated and remains the latest presentable
    version if this regeneration fails.
    """

    base = await _load_owned_storyboard(db, storyboard_id, user_id)
    return await _generate_full(
        db, redis, base.workspace_id, user_id, action=ACTION_REGENERATE
    )


async def regenerate_section(
    db: AsyncSession,
    redis: Redis,
    storyboard_id: UUID,
    section_id: str,
    user_id: UUID,
) -> Storyboard:
    """Regenerate a single act into a new version (5 credits).

    Only the selected section's slides and their speaker notes are replaced; the
    title, theme, diagrams, demo script, appendix, source map, and every other
    act are carried over verbatim from the base version. The fully spliced
    payload is re-validated against the strict schema before persistence. If the
    LLM call or validation fails, the previous ready version's section remains
    active (this is a separate, ``failed`` version row).
    """

    base = await _load_owned_storyboard(db, storyboard_id, user_id)
    if base.status not in _PRESENTABLE:
        raise StoryboardNotPresentableError(
            f"storyboard {storyboard_id} is not presentable (status={base.status})"
        )
    base_payload = copy.deepcopy(base.content_json or {})
    if not _section_exists(base_payload, section_id):
        raise StoryboardSectionNotFoundError(section_id)
    workspace_id = base.workspace_id

    source = await build_storyboard_source(db, workspace_id, user_id)

    sb, created = await _reserve(
        db,
        redis,
        workspace_id,
        user_id,
        source,
        cost=COST_SECTION_REGENERATION,
        action=ACTION_REGENERATE_SECTION,
        reason="storyboard_regenerate_section:{id}",
    )
    if not created:
        # An in-flight generation for this workspace/user already exists; do not
        # double-charge — return it untouched (idempotent retry).
        return sb

    return await _run_section_generation(
        db, sb.id, user_id, source, base_payload, section_id
    )


async def mark_workspace_storyboards_stale(
    db: AsyncSession, workspace_id: UUID
) -> None:
    """Mark every ``ready`` Storyboard of a workspace ``stale``.

    Called from ``StageManager.finalise()`` inside the finalise transaction so
    that refinalising any source stage atomically marks dependent keynotes
    stale. ``stale`` versions stay presentable (the directive keeps a previously
    ready keynote usable); the owner is signalled to regenerate against the new
    sources. ``generating`` rows are left alone — their own finalise transaction
    will set the correct terminal state.

    No ``db.commit()`` here: the update participates in the caller's transaction.
    """

    result = await db.execute(
        select(Storyboard).where(
            Storyboard.workspace_id == workspace_id,
            Storyboard.status == "ready",
        )
    )
    storyboards = list(result.scalars())
    now = datetime.now(UTC)
    for sb in storyboards:
        sb.status = "stale"
        sb.updated_at = now
        logger.info(
            "storyboard.marked_stale",
            **_storyboard_event_fields(
                sb,
                user_id=sb.user_id,
                action="mark_stale",
                status="stale",
                include_credit_ledger=False,
            ),
        )
    if storyboards:
        logger.info(
            "storyboard.stale_propagated",
            workspace_id=str(workspace_id),
            count=len(storyboards),
        )


async def recover_stuck_storyboards(db: AsyncSession) -> int:
    """Fail + refund Storyboards stuck in ``generating`` beyond the threshold.

    Invoked by the shared recovery loop under the leader lock. A stuck keynote is
    one whose own finalise transaction never ran (worker crash, lost connection)
    so it is still ``generating`` past ``STUCK_THRESHOLD_MINUTES``. The credit
    ledger refund path is idempotent, so we call it unconditionally when a ledger
    id exists rather than tracking refund state ourselves. Commits once at the
    end. Returns the number recovered.
    """

    cutoff = datetime.now(UTC) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    result = await db.execute(
        select(Storyboard).where(
            Storyboard.status == "generating",
            Storyboard.updated_at < cutoff,
        )
    )
    stuck = list(result.scalars())

    recovered = 0
    refunded_users: set[UUID] = set()
    for sb in stuck:
        if sb.credit_ledger_id is not None:
            action, refund_amount = await _ledger_action_and_amount(
                db, sb.credit_ledger_id
            )
            await credit_service.refund(db, sb.credit_ledger_id, user_id=sb.user_id)
            record_storyboard_credits_refunded(
                action, "stuck_recovery", refund_amount
            )
            refunded_users.add(sb.user_id)
        sb.status = "failed"
        sb.updated_at = datetime.now(UTC)
        logger.warning(
            "storyboard.recovery",
            storyboard_id=str(sb.id),
            workspace_id=str(sb.workspace_id),
            version=sb.version,
            status=sb.status,
            refunded=sb.credit_ledger_id is not None,
        )
        recovered += 1

    if recovered > 0:
        await db.commit()
        # Credit cache must reflect post-refund balances on the next read.
        for user_id in refunded_users:
            await invalidate_user_cache(user_id)
    return recovered


# ---------------------------------------------------------------------------
# Full generation / regeneration (shared flow)
# ---------------------------------------------------------------------------


async def _generate_full(
    db: AsyncSession,
    redis: Redis,
    workspace_id: UUID,
    user_id: UUID,
    *,
    action: str,
) -> Storyboard:
    # Source extraction runs BEFORE any charge so the dominant failure mode
    # (stages not finalised) never debits a credit or leaves an orphan
    # placeholder. This intentionally reorders the T-254 req-3 bullet list: the
    # T-252 source builder's contract requires raising before any debit, and the
    # security requirement is to fail closed on source validation. LLM-failure
    # refunds still happen post-charge in Tx2 as specified.
    source = await build_storyboard_source(db, workspace_id, user_id)

    reason = (
        "storyboard_generate:{id}"
        if action == ACTION_GENERATE
        else "storyboard_regenerate:{id}"
    )
    sb, created = await _reserve(
        db,
        redis,
        workspace_id,
        user_id,
        source,
        cost=COST_FULL_GENERATION,
        action=action,
        reason=reason,
    )
    if not created:
        # Duplicate request: an in-flight generation already exists. Return it
        # without charging or re-running.
        return sb

    return await _run_full_generation(db, sb.id, user_id, source, action)


async def _reserve(
    db: AsyncSession,
    redis: Redis,
    workspace_id: UUID,
    user_id: UUID,
    source: StoryboardSourcePackage,
    *,
    cost: int,
    action: str,
    reason: str,
) -> tuple[Storyboard, bool]:
    """Tx1: lock workspace, insert placeholder, debit, commit.

    Returns ``(storyboard, created)``. ``created`` is True only when a fresh
    ``generating`` placeholder was inserted and charged; it is False when an
    existing in-flight generation was detected (duplicate request) so the caller
    returns it without re-running or re-charging. Both rows have status
    ``generating``, so this flag — not the status — is the authoritative signal.
    """

    lock_key = f"storyboard:generate:{workspace_id}:{user_id}"
    acquired = await _acquire_lock(redis, lock_key)
    try:
        # Fast path: an in-flight generation is already visible, so skip the
        # workspace lock entirely and return it without charging.
        existing = await _find_in_flight(db, workspace_id, user_id)
        if existing is not None:
            return existing, False

        # Lock the workspace row to serialise version assignment AND duplicate
        # detection across workers. A concurrent reserve that lost the Redis lock
        # blocks here until the winner commits its placeholder.
        ws = await db.execute(
            select(Workspace)
            .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            .with_for_update()
        )
        workspace = ws.scalar_one_or_none()
        if workspace is None:
            # build_storyboard_source already proved ownership; a disappearance
            # here means a concurrent delete. Treat as not-found.
            raise StoryboardNotFoundError(str(workspace_id))

        # Authoritative recheck under the workspace lock: the winner of a
        # concurrent reserve may have committed its ``generating`` placeholder
        # while we waited for this lock. If so, the loser must NOT create a
        # second row or debit again — release the lock and return the in-flight
        # row. This, not the Redis lock, is what guarantees one debit per click.
        existing = await _find_in_flight(db, workspace_id, user_id)
        if existing is not None:
            await db.rollback()  # release the workspace FOR UPDATE lock
            return existing, False

        next_version = await _next_version(db, workspace_id)
        sb = Storyboard(
            workspace_id=workspace_id,
            user_id=user_id,
            version=next_version,
            status="generating",
            # Safe placeholders: NOT NULL columns get inert empty values until
            # Tx2 fills them. source_stage_version_ids is already known and is
            # pinned now so recovery and audit can see the exact sources.
            title="Generating…",
            theme="",
            content_json={},
            speaker_notes_md="",
            demo_script_md="",
            technical_appendix_md="",
            source_map_json={},
            source_stage_version_ids=source.source_stage_version_ids,
        )
        db.add(sb)
        try:
            await db.flush()
        except IntegrityError:
            # The unique (workspace_id, version) backstop tripped: a concurrent
            # reserve won the race and committed this version. Roll back and
            # return the in-flight row — no second charge.
            await db.rollback()
            existing = await _find_in_flight(db, workspace_id, user_id)
            if existing is not None:
                return existing, False
            raise

        # Debit AFTER the placeholder id exists so the ledger reason pins the
        # storyboard. If the balance is insufficient, deduct() raises and the
        # whole transaction (placeholder included) rolls back below.
        deduction = await credit_service.deduct(
            db, user_id, cost, reason.format(id=sb.id)
        )
        sb.credit_ledger_id = deduction.id
        await db.commit()
    except InsufficientCreditsError:
        await db.rollback()
        raise
    finally:
        # Always release the reserve lock before the slow LLM call so a single
        # user is never blocked for the generation's full duration.
        if acquired:
            await _release_lock(redis, lock_key)

    await db.refresh(sb)
    # Credit cache invalidation after the debit commit (req 10).
    await invalidate_user_cache(user_id)

    record_storyboard_generation_started(action)
    record_storyboard_credits_deducted(action, cost)
    logger.info(
        "storyboard.generate_started",
        **_storyboard_event_fields(
            sb,
            user_id=user_id,
            action=action,
            status=sb.status,
            include_credit_ledger=True,
        ),
    )
    return sb, True


async def _run_full_generation(
    db: AsyncSession,
    storyboard_id: UUID,
    user_id: UUID,
    source: StoryboardSourcePackage,
    action: str,
) -> Storyboard:
    start = time.monotonic()
    try:
        payload = await _complete_and_validate(source)
    except StoryboardPayloadError as exc:
        record_storyboard_generation_duration(action, time.monotonic() - start)
        # Failure after the debit: mark failed + refund exactly once, then
        # surface the typed reason. The previous ready version (a different
        # version row) is untouched and remains the latest presentable one.
        await _fail_and_refund(db, storyboard_id, user_id, action, exc)
        error_type = _payload_error_type(exc)
        raise StoryboardGenerationError(error_type, exc.summary) from exc
    record_storyboard_generation_duration(action, time.monotonic() - start)

    return await _finalise_ready(db, storyboard_id, user_id, payload, source, action)


async def _run_section_generation(
    db: AsyncSession,
    storyboard_id: UUID,
    user_id: UUID,
    source: StoryboardSourcePackage,
    base_payload: dict,
    section_id: str,
) -> Storyboard:
    action = ACTION_REGENERATE_SECTION
    start = time.monotonic()
    try:
        new_payload = await _complete_and_validate(source)
        # The section was proven present before the debit, so the splice cannot
        # raise not-found here; the spliced result must still satisfy the whole
        # six-act contract, so re-validate it and treat any miss as a schema
        # failure (fail closed → refund → base section stays active).
        spliced = _splice_section(base_payload, new_payload, section_id)
        try:
            payload = StoryboardPayload.model_validate(spliced)
        except Exception as exc:  # noqa: BLE001 — converted to typed failure below
            raise StoryboardPayloadError(
                "schema", "spliced section payload failed validation"
            ) from exc
    except StoryboardPayloadError as exc:
        record_storyboard_generation_duration(action, time.monotonic() - start)
        await _fail_and_refund(db, storyboard_id, user_id, action, exc)
        error_type = _payload_error_type(exc)
        raise StoryboardGenerationError(error_type, exc.summary) from exc
    record_storyboard_generation_duration(action, time.monotonic() - start)

    sb = await _finalise_ready(db, storyboard_id, user_id, payload, source, action)
    record_storyboard_section_regenerated()
    logger.info(
        "storyboard.section_regenerated",
        **_storyboard_event_fields(
            sb,
            user_id=user_id,
            action=action,
            status=sb.status,
            include_credit_ledger=True,
        ),
    )
    return sb


async def _complete_and_validate(
    source: StoryboardSourcePackage,
) -> StoryboardPayload:
    """Run the LLM completion + strict validation (with one repair attempt).

    Maps every failure to a typed, content-free outcome. ``StoryboardPayloadError``
    is propagated for the caller's fail+refund path; transport failures are
    converted into the same typed error family so the caller has a single
    fail-closed contract.
    """

    user_prompt = build_user_prompt(source)

    async def _repair(repair_prompt: str) -> str:
        try:
            return await complete_with_timeout(
                source.provider,
                source.model,
                SYSTEM_PROMPT,
                repair_prompt,
                _OUTPUT_TOKEN_BUDGET,
            )
        except TimeoutError as exc:
            raise StoryboardPayloadError("parse", "llm repair timed out") from exc
        except ProviderError as exc:
            raise StoryboardPayloadError("parse", "llm repair provider error") from exc

    try:
        raw = await complete_with_timeout(
            source.provider,
            source.model,
            SYSTEM_PROMPT,
            user_prompt,
            _OUTPUT_TOKEN_BUDGET,
        )
    except TimeoutError as exc:
        raise StoryboardPayloadError("parse", "llm completion timed out") from exc
    except ProviderError as exc:
        raise StoryboardPayloadError("parse", "llm provider error") from exc

    return await _parse_validate_and_ground(raw, source, repair=_repair)


async def _parse_validate_and_ground(
    raw: str,
    source: StoryboardSourcePackage,
    *,
    repair,
) -> StoryboardPayload:
    """Validate schema + source grounding, allowing one total repair attempt."""

    try:
        payload = await parse_and_validate_payload(raw)
        _validate_payload_against_source(payload, source)
        return payload
    except StoryboardPayloadError as first_error:
        allowed_ids = ", ".join(sorted(source.excerpts)) or "none"
        repair_prompt = build_repair_user_prompt(
            raw,
            f"{first_error.summary}; allowed source ids: {allowed_ids}",
        )
        repaired = await repair(repair_prompt)
        payload = await parse_and_validate_payload(repaired)
        _validate_payload_against_source(payload, source)
        return payload


def _validate_payload_against_source(
    payload: StoryboardPayload, source: StoryboardSourcePackage
) -> None:
    """Fail closed when generated citations or media cues are not render-safe.

    Pydantic validates the payload shape. This source-aware pass validates the
    dynamic part the static schema cannot know: every citation id must be one of
    the exact finalised excerpts in this source package, and the source enum must
    match that excerpt's stage. The summary is intentionally source-free; it
    names only invalid fields and allowed ids so logs/repair prompts stay safe.
    """

    available = source.excerpts
    errors: list[str] = []

    def check_ref(ref: Any, context: str) -> None:
        source_id = getattr(ref, "source_id", "")
        source_enum = getattr(ref, "source", "")
        excerpt = available.get(source_id)
        if excerpt is None:
            errors.append(f"{context} uses unavailable source_id {source_id!r}")
            return
        expected_source = excerpt.stage.upper()
        if source_enum != expected_source:
            errors.append(
                f"{context} source {source_enum!r} does not match {source_id!r}"
            )

    for claim_key, refs in payload.source_map.items():
        for idx, ref in enumerate(refs):
            check_ref(ref, f"source_map[{claim_key!r}][{idx}]")

    for diagram in payload.diagrams:
        for layer in diagram.layers:
            for idx, ref in enumerate(layer.source_refs):
                check_ref(ref, f"diagram[{diagram.id!r}].layer[{layer.id!r}][{idx}]")

    for key, note in payload.notes.items():
        if _FORBIDDEN_VIDEO_DEMO_RE.search(note.demo_cue):
            errors.append(f"notes[{key!r}].demo_cue requests a video demo")

    if _FORBIDDEN_VIDEO_DEMO_RE.search(payload.demo_script_md):
        errors.append("demo_script_md requests a video demo")

    if errors:
        allowed = ", ".join(sorted(available)) or "none"
        summary = "; ".join(errors[:20])
        if len(errors) > 20:
            summary += f"; +{len(errors) - 20} more"
        raise StoryboardPayloadError(
            "schema", f"{summary}; allowed source ids: {allowed}"
        )


async def _finalise_ready(
    db: AsyncSession,
    storyboard_id: UUID,
    user_id: UUID,
    payload: StoryboardPayload,
    source: StoryboardSourcePackage,
    action: str,
) -> Storyboard:
    """Tx2 (success): reload the placeholder FOR UPDATE and persist as ready."""

    sb = await _load_for_update(db, storyboard_id)
    if sb is None:
        # Recovery (or a concurrent failure) already terminated this row. Do not
        # resurrect it; the credit was handled by whoever terminated it.
        raise StoryboardGenerationError(
            "row_missing", "placeholder no longer present at finalise"
        )

    payload_dict = payload.model_dump()
    sb.title = payload.title
    sb.theme = _theme_label(payload)
    sb.content_json = payload_dict
    sb.speaker_notes_md = _render_speaker_notes_md(payload)
    sb.demo_script_md = payload.demo_script_md
    sb.technical_appendix_md = payload.technical_appendix_md
    sb.source_map_json = payload_dict["source_map"]
    sb.source_stage_version_ids = source.source_stage_version_ids
    sb.status = "ready"
    sb.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(sb)

    record_storyboard_generation_completed(action)
    logger.info(
        "storyboard.generate_completed",
        **_storyboard_event_fields(
            sb,
            user_id=user_id,
            action=action,
            status=sb.status,
            include_credit_ledger=True,
        ),
    )
    return sb


async def _fail_and_refund(
    db: AsyncSession,
    storyboard_id: UUID,
    user_id: UUID,
    action: str,
    exc: StoryboardPayloadError,
) -> None:
    """Tx2 (failure): mark the placeholder failed and refund exactly once."""

    sb = await _load_for_update(db, storyboard_id)
    if sb is None:
        # Already terminated (e.g. by recovery). Nothing to do — refund, if any,
        # was handled by the terminator and is idempotent regardless.
        return

    sb.status = "failed"
    sb.updated_at = datetime.now(UTC)
    refunded = False
    if sb.credit_ledger_id is not None:
        # The credit ledger refund path is idempotent and race-safe (a duplicate
        # refund is a no-op), so calling it exactly here is sufficient.
        await credit_service.refund(db, sb.credit_ledger_id, user_id=user_id)
        refunded = True
    await db.commit()
    await db.refresh(sb)

    if refunded:
        await invalidate_user_cache(user_id)
        record_storyboard_credits_refunded(
            action, "generation_failed", _credit_cost_for_action(action)
        )

    error_type = _payload_error_type(exc)
    record_storyboard_generation_failed(action, error_type)
    logger.warning(
        "storyboard.generate_failed",
        **_storyboard_event_fields(
            sb,
            user_id=user_id,
            action=action,
            status=sb.status,
            include_credit_ledger=True,
            error_type=error_type,
            refunded=refunded,
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def invalidate_user_cache(user_id: UUID) -> None:
    await credit_service.invalidate(user_id)


def _storyboard_event_fields(
    sb: Storyboard,
    *,
    user_id: UUID | None,
    action: str,
    status: str | None = None,
    include_credit_ledger: bool,
    **extra: Any,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "storyboard_id": str(sb.id),
        "workspace_id": str(sb.workspace_id),
        "version": sb.version,
        "action": action,
        "status": status or sb.status,
    }
    if user_id is not None:
        fields["user_id"] = str(user_id)
    if include_credit_ledger and sb.credit_ledger_id is not None:
        fields["credit_ledger_id"] = str(sb.credit_ledger_id)
    fields.update(extra)
    return fields


def _payload_error_type(exc: StoryboardPayloadError) -> str:
    summary = (exc.summary or "").lower()
    if "timed out" in summary or "timeout" in summary:
        return "timeout"
    if "provider" in summary:
        return "provider"
    return "payload_parse" if exc.stage == "parse" else "payload_schema"


def _credit_cost_for_action(action: str) -> int:
    return _CREDIT_COST_BY_ACTION.get(action, COST_FULL_GENERATION)


async def _ledger_action_and_amount(
    db: AsyncSession, ledger_id: UUID
) -> tuple[str, int]:
    ledger = await db.get(CreditLedger, ledger_id)
    if ledger is None:
        return ACTION_GENERATE, COST_FULL_GENERATION

    reason = ledger.reason or ""
    if reason.startswith("storyboard_regenerate_section:"):
        action = ACTION_REGENERATE_SECTION
    elif reason.startswith("storyboard_regenerate:"):
        action = ACTION_REGENERATE
    else:
        action = ACTION_GENERATE

    amount = abs(int(ledger.amount or 0)) or _credit_cost_for_action(action)
    return action, amount


async def _acquire_lock(redis: Redis, key: str) -> bool:
    """Best-effort ``SET NX`` reserve lock.

    Returns True if acquired. A Redis outage degrades to ``False`` (lock not
    held) rather than failing the request — the DB ``generating``-row guard and
    the unique-version constraint still prevent a double charge, so correctness
    does not depend on Redis being up. Fail-safe, not fail-open on billing.
    """

    try:
        return bool(await redis.set(key, "1", nx=True, ex=_RESERVE_LOCK_TTL_SECONDS))
    except RedisError:
        logger.warning("storyboard.reserve_lock_unavailable", key=key)
        return False


async def _release_lock(redis: Redis, key: str) -> None:
    try:
        release_command = redis.delete
        await release_command(key)
    except RedisError:
        logger.warning("storyboard.reserve_lock_release_failed", key=key)


async def _find_in_flight(
    db: AsyncSession, workspace_id: UUID, user_id: UUID
) -> Storyboard | None:
    result = await db.execute(
        select(Storyboard)
        .where(
            Storyboard.workspace_id == workspace_id,
            Storyboard.user_id == user_id,
            Storyboard.status == "generating",
        )
        .order_by(Storyboard.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _next_version(db: AsyncSession, workspace_id: UUID) -> int:
    result = await db.execute(
        select(func.max(Storyboard.version)).where(
            Storyboard.workspace_id == workspace_id
        )
    )
    current_max = result.scalar_one_or_none()
    return (current_max or 0) + 1


async def _load_for_update(db: AsyncSession, storyboard_id: UUID) -> Storyboard | None:
    result = await db.execute(
        select(Storyboard).where(Storyboard.id == storyboard_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def _load_owned_storyboard(
    db: AsyncSession, storyboard_id: UUID, user_id: UUID
) -> Storyboard:
    result = await db.execute(
        select(Storyboard).where(
            Storyboard.id == storyboard_id,
            Storyboard.user_id == user_id,
        )
    )
    sb = result.scalar_one_or_none()
    if sb is None:
        raise StoryboardNotFoundError(str(storyboard_id))
    return sb


def _theme_label(payload: StoryboardPayload) -> str:
    """Short human-readable label for the ``theme`` TEXT column.

    The full structured theme (palette, typography, motif, transitions) lives in
    ``content_json['theme']`` for the renderer; the column holds only the motif
    as a display label, bounded to the column's 200-char check constraint.
    """

    return payload.theme.motif.strip()[:200]


def _section_exists(payload: dict, section_id: str) -> bool:
    return any(
        isinstance(s, dict) and s.get("id") == section_id
        for s in payload.get("sections", [])
    )


def _splice_section(
    base_payload: dict, new_payload: StoryboardPayload, section_id: str
) -> dict:
    """Replace one act in ``base_payload`` with the matching act from a freshly
    generated full payload, carrying everything else over verbatim.

    Matching is by the fixed act title (the six acts are a closed, ordered set)
    so the replacement is the same act even if the new payload assigned it a
    different id; the base section's id is preserved for URL/id stability. Only
    the target act's slides and their speaker notes change — title, theme,
    diagrams, demo script, appendix, source map, and every other act are kept.
    """

    result = copy.deepcopy(base_payload)
    sections = result.get("sections", [])
    idx = next(
        (i for i, s in enumerate(sections) if s.get("id") == section_id),
        None,
    )
    if idx is None:
        raise StoryboardSectionNotFoundError(section_id)
    old_section = sections[idx]

    new_dump = new_payload.model_dump()
    new_section = next(
        (s for s in new_dump["sections"] if s["title"] == old_section.get("title")),
        None,
    )
    if new_section is None:  # pragma: no cover - validated six-act set guarantees it
        raise StoryboardSectionNotFoundError(section_id)

    new_section = copy.deepcopy(new_section)
    new_section["id"] = section_id  # keep the section id stable across regen
    sections[idx] = new_section

    # Notes are keyed by slide id / speaker_notes_ref. Drop the replaced act's
    # old note entries and add the new act's, leaving all other acts' notes
    # untouched so the splice is truly local.
    notes = dict(result.get("notes", {}))
    for slide in old_section.get("slides", []):
        notes.pop(slide.get("id"), None)
        notes.pop(slide.get("speaker_notes_ref"), None)
    new_notes = new_dump["notes"]
    for slide in new_section["slides"]:
        for key in (slide.get("id"), slide.get("speaker_notes_ref")):
            if key in new_notes:
                notes[key] = new_notes[key]
    result["notes"] = notes
    return result


def _render_speaker_notes_md(payload: StoryboardPayload) -> str:
    """Serialise the structured per-slide speaker notes into a markdown document.

    Stored in the ``speaker_notes_md`` column and streamed by the notes download
    endpoint. The renderer (T-255) owns escaping for any rendered surface; this
    is plain markdown text built from already-validated structured data.
    """

    lines: list[str] = [f"# Speaker Notes — {payload.title}", ""]
    notes = payload.notes
    for section in payload.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for slide in section.slides:
            note = notes.get(slide.speaker_notes_ref) or notes.get(slide.id)
            lines.append(f"### {slide.headline}")
            if note is None:
                lines.append("")
                lines.append("_No speaker note._")
                lines.append("")
                continue
            lines.append("")
            lines.append(f"- **Talk track:** {note.talk_track}")
            lines.append(f"- **Transition:** {note.transition}")
            lines.append(f"- **Timing:** {note.timing_seconds}s")
            lines.append(f"- **Pause cue:** {note.pause_cue}")
            if note.demo_cue:
                lines.append(f"- **Demo cue:** {note.demo_cue}")
            for point in note.backup_points:
                lines.append(f"- **Backup:** {point}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
