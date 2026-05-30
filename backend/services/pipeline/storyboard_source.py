"""Deterministic source extraction for Storyboard generation (Phase 20 — T-252).

A Storyboard must be grounded in a workspace's *finalised* SPEC, PLAN, HARNESS,
and TASKS artifacts and must never be built from draft, stale, or in-progress
content. This module loads the exact immutable ``StageVersion`` rows behind the
four finalised stages, scrubs them of anything resembling a secret, and slices
them into citeable, bounded excerpts (``SPEC:overview``, ``PLAN:architecture``,
``PLAN:stride`` …) that the prompt builder (T-253) and generation service
(T-254) consume.

Design guarantees:

* **Finalised-only.** All four stages must be ``finalised`` and we read the
  ``StageVersion`` pinned by ``Stage.current_version`` — never the mutable
  ``Stage.content`` — so a later edit cannot silently change an existing
  Storyboard. The pinned version ids are surfaced as ``source_stage_version_ids``
  and persisted by T-254.
* **No secrets / no account data.** The package is built only from stage content
  plus workspace name / problem statement / provider / model. It never touches
  account email, credit data, billing data, JWTs, API keys, API_KEY values,
  OAuth tokens, refresh tokens, or other secrets, and every string that reaches
  the LLM is additionally run through the central redactor as defence-in-depth.
  Draft content is excluded structurally (finalised versions only).
* **Deterministic.** Extraction is a pure function of the finalised content, so
  idempotent generation retries produce an identical source package.
* **Honest about gaps.** When an expected section cannot be located we record a
  structured ``MissingSourceSection`` finding instead of inventing content; T-262
  increments ``specforge_storyboard_source_missing_total`` from these findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Stage, StageVersion, Workspace
from schemas.stage import StageType
from services.observability import (
    record_storyboard_source_missing,
    redact_sensitive_data,
)

# Hard cap on every excerpt fed to the prompt. Keeps the prompt bounded and
# prevents a single huge section from dominating the source map.
_MAX_EXCERPT_CHARS = 1200

_STAGE_ORDER: tuple[StageType, ...] = ("spec", "plan", "harness", "tasks")

# Extra scrubbing patterns layered on top of the central redactor. The central
# ``redact_sensitive_data`` already covers Bearer/Basic auth, ``sk-`` / ``AIza``
# / Stripe keys, PEM private keys, and refresh/authorization assignments; here we
# add bare email addresses and bare JWTs that can appear inside free-form spec
# text a user may have pasted.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


# ---------------------------------------------------------------------------
# Typed errors (consumed by the router / T-254 generation service)
# ---------------------------------------------------------------------------


class StoryboardSourceError(Exception):
    """Base class for source-builder failures."""


class StoryboardWorkspaceNotFoundError(StoryboardSourceError):
    """The workspace does not exist or is not owned by the caller."""


class StoryboardStagesNotFinalisedError(StoryboardSourceError):
    """One or more source stages are not finalised.

    ``not_ready`` maps each offending stage to a short reason (missing, the
    current status, or a data-integrity problem). The generation service must
    raise this *before* deducting any credit.
    """

    def __init__(self, not_ready: dict[str, str]) -> None:
        self.not_ready = dict(not_ready)
        detail = ", ".join(f"{stage}: {reason}" for stage, reason in not_ready.items())
        super().__init__(f"Storyboard source stages not finalised — {detail}")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceExcerpt:
    """A bounded, citeable excerpt extracted from a finalised stage."""

    source_id: str  # e.g. "PLAN:architecture"
    stage: StageType  # "plan"
    heading: str  # the matched markdown heading text
    excerpt: str  # scrubbed, <= 1200 chars


@dataclass(frozen=True)
class MissingSourceSection:
    """A section the Storyboard wanted but could not extract.

    Recorded instead of inventing content. T-262 emits
    ``specforge_storyboard_source_missing_total`` from these findings.
    """

    source_id: str
    stage: StageType
    reason: str


@dataclass(frozen=True)
class StoryboardSourcePackage:
    """Immutable, deterministic source bundle for one Storyboard generation."""

    workspace_id: UUID
    workspace_name: str
    problem_statement: str
    provider: str
    model: str
    stage_versions: dict[StageType, UUID]
    artifacts: dict[StageType, str]
    excerpts: dict[str, SourceExcerpt]
    missing_source_sections: list[MissingSourceSection] = field(default_factory=list)

    @property
    def source_stage_version_ids(self) -> dict[str, str]:
        """The ``{stage: StageVersion.id}`` map T-254 persists on the Storyboard.

        Stringified so it is JSON-serialisable into the ``source_stage_version_ids``
        JSONB column. Immutable: pins the exact source versions this Storyboard
        was generated from.
        """

        return {
            stage: str(version_id) for stage, version_id in self.stage_versions.items()
        }


# ---------------------------------------------------------------------------
# Section extraction config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SectionSpec:
    source_id: str
    stage: StageType
    include_any: tuple[str, ...]
    exclude_any: tuple[str, ...] = ()
    lead_fallback: bool = False


# Citeable source sections. PLAN architecture / security / capacity / STRIDE /
# SLO / FMEA evidence is prioritised because it backs the architecture reveal and
# the Trust, Security, Reliability act. HARNESS coverage and TASKS must-ship
# evidence inform demo cues, appendix, and Q&A backup — never a top-level
# Validation or Execution Plan act.
_SECTION_SPECS: tuple[_SectionSpec, ...] = (
    _SectionSpec(
        "SPEC:overview",
        "spec",
        ("overview", "introduction", "summary", "vision", "problem"),
        lead_fallback=True,
    ),
    _SectionSpec(
        "PLAN:architecture",
        "plan",
        ("architecture", "system design", "components"),
        exclude_any=("security", "data architecture"),
    ),
    _SectionSpec(
        "PLAN:security-architecture",
        "plan",
        (
            "security architecture",
            "security model",
            "security &",
            "security and",
            "security",
        ),
    ),
    _SectionSpec(
        "PLAN:capacity-model",
        "plan",
        (
            "capacity",
            "scaling",
            "scalability",
            "performance",
            "throughput",
            "load model",
            "load",
        ),
    ),
    _SectionSpec(
        "PLAN:stride",
        "plan",
        ("stride", "threat model", "threat modeling", "threat modelling"),
    ),
    _SectionSpec(
        "PLAN:slo",
        "plan",
        (
            "slo",
            "service level",
            "availability target",
            "availability",
            "error budget",
            "observability",
            "operations",
            "monitoring",
        ),
    ),
    _SectionSpec(
        "PLAN:fmea",
        "plan",
        (
            "fmea",
            "failure mode",
            "failure-mode",
            "error handling",
            "recovery",
            "risks and mitigations",
            "risk mitigation",
        ),
    ),
    _SectionSpec(
        "HARNESS:coverage",
        "harness",
        ("coverage", "requirements coverage", "traceability"),
    ),
    _SectionSpec(
        "TASKS:must",
        "tasks",
        (
            "must",
            "must-have",
            "p0",
            "critical path",
            "mvp",
            "phase",
            "foundation",
            "execution",
        ),
        lead_fallback=True,
    ),
)


# ---------------------------------------------------------------------------
# Scrubbing + markdown helpers (pure)
# ---------------------------------------------------------------------------


def _scrub(text: str) -> str:
    """Defence-in-depth redaction of anything that resembles a secret/PII."""

    scrubbed = redact_sensitive_data(text)
    if not isinstance(scrubbed, str):  # redact_sensitive_data is identity on str
        scrubbed = str(scrubbed)
    scrubbed = _EMAIL_RE.sub("[redacted-email]", scrubbed)
    scrubbed = _JWT_RE.sub("[redacted-token]", scrubbed)
    return scrubbed


def _bound(text: str) -> str:
    """Trim to at most ``_MAX_EXCERPT_CHARS``, on a word boundary when truncating."""

    text = text.strip()
    if len(text) <= _MAX_EXCERPT_CHARS:
        return text
    clipped = text[:_MAX_EXCERPT_CHARS]
    # Avoid cutting mid-word: drop the trailing partial token when there is a
    # safe whitespace boundary reasonably close to the cap.
    pivot = clipped.rfind(" ")
    if pivot >= _MAX_EXCERPT_CHARS - 120:
        clipped = clipped[:pivot]
    return clipped.rstrip()


def _iter_sections(md: str) -> list[tuple[int, str, str]]:
    """Split markdown into ``(level, heading, body)`` tuples in document order.

    A section's body runs from just after its heading to the next heading whose
    level is the same or higher (smaller ``#`` count), so nested subsections stay
    attached to their parent.
    """

    lines = md.splitlines()
    headings: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append((idx, len(m.group(1)), m.group(2).strip()))

    sections: list[tuple[int, str, str]] = []
    for pos, (line_no, level, heading) in enumerate(headings):
        end = len(lines)
        for nxt_line, nxt_level, _ in headings[pos + 1 :]:
            if nxt_level <= level:
                end = nxt_line
                break
        body = "\n".join(lines[line_no + 1 : end]).strip()
        sections.append((level, heading, body))
    return sections


def _document_lead(md: str) -> str:
    """Content before the first heading; falls back to the first section body."""

    lines = md.splitlines()
    first_heading = next(
        (i for i, line in enumerate(lines) if _HEADING_RE.match(line)),
        len(lines),
    )
    lead = "\n".join(lines[:first_heading]).strip()
    if lead:
        return lead
    sections = _iter_sections(md)
    return sections[0][2] if sections else ""


def _match_section(md: str, spec: _SectionSpec) -> tuple[str, str] | None:
    """Return ``(heading, body)`` for the first section matching ``spec``."""

    for _level, heading, body in _iter_sections(md):
        lowered = heading.lower()
        if any(token in lowered for token in spec.exclude_any):
            continue
        if any(token in lowered for token in spec.include_any) and body.strip():
            return heading, body
    if spec.lead_fallback:
        lead = _document_lead(md)
        if lead:
            return "(document lead)", lead
    return None


def _extract_excerpts(
    artifacts: dict[StageType, str],
) -> tuple[dict[str, SourceExcerpt], list[MissingSourceSection]]:
    excerpts: dict[str, SourceExcerpt] = {}
    missing: list[MissingSourceSection] = []
    for spec in _SECTION_SPECS:
        content = artifacts.get(spec.stage, "")
        matched = _match_section(content, spec) if content else None
        if matched is None:
            missing.append(
                MissingSourceSection(
                    source_id=spec.source_id,
                    stage=spec.stage,
                    reason="section_not_found",
                )
            )
            continue
        heading, body = matched
        excerpts[spec.source_id] = SourceExcerpt(
            source_id=spec.source_id,
            stage=spec.stage,
            heading=heading,
            excerpt=_bound(body),
        )
    return excerpts, missing


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def build_storyboard_source(
    db: AsyncSession, workspace_id: UUID, user_id: UUID
) -> StoryboardSourcePackage:
    """Build the immutable Storyboard source package for a workspace.

    Raises ``StoryboardWorkspaceNotFoundError`` if the workspace is not owned by
    the caller, and ``StoryboardStagesNotFinalisedError`` if any of the four
    source stages is not finalised — both before any credit is charged.
    """

    workspace = await _load_owned_workspace(db, workspace_id, user_id)
    stages = await _load_stages(db, workspace_id)

    not_ready: dict[str, str] = {}
    for stage_type in _STAGE_ORDER:
        stage = stages.get(stage_type)
        if stage is None:
            not_ready[stage_type] = "missing"
        elif stage.status != "finalised":
            not_ready[stage_type] = stage.status
    if not_ready:
        raise StoryboardStagesNotFinalisedError(not_ready)

    # Load the exact StageVersion pinned by current_version for each stage. This
    # is the immutable source of truth — not Stage.content.
    versions = await _load_current_versions(db, stages)
    for stage_type in _STAGE_ORDER:
        if stage_type not in versions:
            not_ready[stage_type] = "finalised_version_missing"
    if not_ready:
        raise StoryboardStagesNotFinalisedError(not_ready)

    stage_versions: dict[StageType, UUID] = {
        stage_type: versions[stage_type].id for stage_type in _STAGE_ORDER
    }
    artifacts: dict[StageType, str] = {
        stage_type: _scrub(versions[stage_type].content or "")
        for stage_type in _STAGE_ORDER
    }

    excerpts, missing = _extract_excerpts(artifacts)
    for item in missing:
        record_storyboard_source_missing(item.stage, item.source_id)

    return StoryboardSourcePackage(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        problem_statement=_scrub(workspace.problem_statement or ""),
        provider=workspace.provider,
        model=workspace.model,
        stage_versions=stage_versions,
        artifacts=artifacts,
        excerpts=excerpts,
        missing_source_sections=missing,
    )


async def _load_owned_workspace(
    db: AsyncSession, workspace_id: UUID, user_id: UUID
) -> Workspace:
    result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.user_id == user_id,
        )
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise StoryboardWorkspaceNotFoundError(str(workspace_id))
    return workspace


async def _load_stages(db: AsyncSession, workspace_id: UUID) -> dict[str, Stage]:
    result = await db.execute(select(Stage).where(Stage.workspace_id == workspace_id))
    return {stage.type: stage for stage in result.scalars()}


async def _load_current_versions(
    db: AsyncSession, stages: dict[str, Stage]
) -> dict[StageType, StageVersion]:
    """Load the ``StageVersion`` row pinned by each stage's ``current_version``."""

    stage_ids = [stages[stage_type].id for stage_type in _STAGE_ORDER]
    result = await db.execute(
        select(StageVersion).where(StageVersion.stage_id.in_(stage_ids))
    )
    by_stage_id: dict[UUID, list[StageVersion]] = {}
    for version in result.scalars():
        by_stage_id.setdefault(version.stage_id, []).append(version)

    current: dict[StageType, StageVersion] = {}
    for stage_type in _STAGE_ORDER:
        stage = stages[stage_type]
        for version in by_stage_id.get(stage.id, ()):
            if version.version == stage.current_version:
                current[stage_type] = version
                break
    return current
