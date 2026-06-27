"""Phase 19 zero-LLM artifact validator.

The validator runs BEFORE the critic (T-247) because section-presence is
the cheapest possible gate — regex/substring match, no LLM call, < 5 ms on a
200K-char artifact.  Section-aware: SECTION_CONTRACTS encodes the required
headings per stage; the conditional sentinels trigger the Frontend
Architecture section only when an upstream artifact mentions a browser-facing
surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Required section headings per stage.  Order is the order they appear in the
# system prompt for each stage; the validator does NOT enforce order (just
# presence), but keeping the list in canonical order makes it easier to audit
# against the system prompt.
SECTION_CONTRACTS: dict[str, list[str]] = {
    "spec": [
        "## Overview",
        "## Product Goals",
        "## User Problems",
        "## Non-Goals",
        "## Users and Personas",
        "## User Journeys",
        "## User Flow Diagrams",
        "## Functional Requirements",
        "## Non-Functional Requirements",
        "## Conceptual Domain Model",
        "## Integrations and External Touchpoints",
        "## Permissions and Access Expectations",
        "## Security, Privacy, and Abuse Expectations",
        "## Error Handling and Recovery",
        "## High-Level System Context",
        "## Feature Interaction Overview",
        "## Acceptance Criteria",
        "## Success Metrics",
        "## Edge Cases",
        "## Constraints",
        "## Risks",
        "## Assumptions and Open Questions",
        "## Out of Scope",
    ],
    "plan": [
        "## Planning Summary",
        "## Architecture Overview",
        "## Requirement Traceability Matrix",
        "## Technology Stack and Rationale",
        "## Architecture Decision Records",  # T-239
        "## Architecture Anti-Patterns",  # T-239
        "## Multi-tenancy Stance",  # T-239
        "## Capacity Model",  # T-240
        "## Threat Model",  # T-240 (STRIDE)
        "## SLOs and Error Budgets",  # T-240
        "## Failure Mode and Effects Analysis",  # T-240
        # Stored as the FULL heading (not the truncated "## Architecture Quality
        # Attribute") so it matches BOTH consumers of this list: the substring
        # check in validate_sections AND the line-anchored regex in _section_body.
        # A truncated entry passes the substring gate but makes _section_body
        # extract an empty body, firing a false `shallow_required_section`
        # advisory on every plan (audit finding #1). Keep contract headings
        # verbatim with the prompt's real heading.
        "## Architecture Quality Attribute Matrix",  # T-240
        "## Directory and File Structure",
        "## Module Boundaries and Interfaces",
        "## Data Model and Persistence",
        "## API Design",
        "## Authentication and Authorization",
        "## Security Architecture",
        "## Privacy and Data Handling",
        "## Error Handling and Recovery",
        "## Observability and Audit Logging",
        "## Testing Strategy",
        "## Deployment and Operations",
        "## Scalability and Performance",
        "## Rollout and Migration Plan",
        "## Risks and Mitigations",
        "## Assumptions and Open Questions",
    ],
    "harness": [
        "## Harness Overview",
        "## Requirement-to-Test Matrix",
        "## Coverage Plan",
        "## File Tree",
        "## Files",
    ],
    "tasks": [
        "## Effort Summary",
        "## Execution Overview",
        "## Traceability Overview",
        "## Dependency Graph",
        "## Task Sizing Legend",
    ],
}

# Demo Day mode contracts (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §6). A
# parallel, mode-keyed structure: leaner than the standard contract and
# re-pointed for a ≤5-hour build, plus the three rubric sections (AI Usage /
# Security Posture / Scalability Story) so the demo-day questions are always
# answered. Selected when ``workspace.mode == "demo_day"``. Standard contracts
# above are untouched (the §4 byte-identical regression-pin contract).
DEMO_DAY_SECTION_CONTRACTS: dict[str, list[str]] = {
    "spec": [
        "## Overview",
        "## Target User and Core Problem",
        "## Demo Day Scope",
        "## Out of Scope",
        "## Functional Requirements",
        "## Acceptance Criteria",
        "## Success Demo",
        "## AI Usage",
        "## Security Posture",
        "## Scalability Story",
        "## Risks and Assumptions",
    ],
    "plan": [
        "## Architecture Overview",
        "## Technology Stack",
        "## Requirement Traceability Matrix",
        "## Interface Contracts",
        "## Data Model and Persistence",
        "## Build Sequence",
        "## Environment and Bootstrap",
        "## Architecture Decision Records",
        "## Scalability and Performance",
        "## Security Architecture",
        "## Risks and Mitigations",
    ],
    "harness": [
        "## Harness Overview",
        "## Frozen Interface Contracts",
        "## Requirement-to-Test Matrix",
        "## End-to-End Smoke Test",
        "## File Tree",
        "## Files",
    ],
    "tasks": [
        "## Effort Summary",
        "## Build Order",
        "## Traceability Overview",
        "## Tasks",
    ],
}


def section_contract(stage_type: str, mode: str = "standard") -> list[str]:
    """The required section headings for a stage, selected by workspace mode.

    ``mode="demo_day"`` returns the lean rubric-aware Demo Day contract; any
    other value (the default) returns the unchanged standard contract.
    """
    if mode == "demo_day":
        return DEMO_DAY_SECTION_CONTRACTS.get(stage_type, [])
    return SECTION_CONTRACTS.get(stage_type, [])


# Conditional sections — keyed by stage, value is a list of (sentinel_regex,
# section_heading) pairs.  When any sentinel matches an upstream artifact, the
# section must appear in the current artifact.
_CONDITIONAL_SECTIONS: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "plan": [
        (
            re.compile(
                r"\b(UI|web|app|page|screen|dashboard|console)\b",
                re.IGNORECASE,
            ),
            "## Frontend Architecture",  # T-242
        ),
    ],
}

COMPLETION_CONTRACT_VERSION = "v2"
FINAL_COMPLETION_SENTINEL_TEMPLATE = "<!-- SPECFORGE_COMPLETE:{stage}:v2 -->"
CHUNK_COMPLETION_SENTINEL_TEMPLATE = (
    "<!-- SPECFORGE_CHUNK_COMPLETE:{stage}:{chunk}:v2 -->"
)
_REQUIREMENT_ID_RE = re.compile(r"\b(?:FR|NFR|SEC)-\d{3}\b")
_AC_ID_RE = re.compile(r"\bAC-\d{3}\b")
_TASK_HEADER_RE = re.compile(r"^###\s+T-\d{3}:", re.MULTILINE)
_TASK_DEP_RE = re.compile(r"\bT-(\d{3})\b")
_TASK_FIELD_RE = re.compile(r"^\*\*(?P<field>[^*]+):\*\*\s*(?P<value>.*)$")
_FILE_BLOCK_RE = re.compile(
    r"^###\s+File:\s+(.+?)\s*\n+```[^\n]*\n.*?\n```",
    re.MULTILINE | re.DOTALL,
)
_INCOMPLETE_TRAILING_RE = re.compile(r"(:|,\s*|\|\s*)$")


def _ends_with_complete_table_row(final_line: str) -> bool:
    """True when the artifact's last line is a complete markdown table row.

    A well-formed table row is pipe-delimited and *legitimately* ends every row
    with ``|`` (``| a | b |``), so a document that closes on a table — e.g. a
    plan's "Open Questions" matrix — naturally has a trailing pipe.  The
    ``_INCOMPLETE_TRAILING_RE`` ``|`` clause exists to catch a row truncated
    mid-cell, but such a cut ends *inside* the cell text (no trailing ``|``), so
    a row that ends with ``|`` and carries an interior separator (``count >= 2``)
    is complete, not dangling.  Genuine mid-table truncation that happens to land
    on a cell boundary is still caught by the provider ``stopped_by_limit`` and
    ``missing_completion_sentinel`` checks; this only removes the false positive
    that flagged every table-closing artifact as truncated.
    """
    return final_line.endswith("|") and final_line.count("|") >= 2


# The ONLY two signals that mean the platform produced genuinely unusable output
# and must refund: the provider hard-stopped on its output-token cap
# (`provider_stopped_by_limit`) or nothing was produced at all (`empty_artifact`).
# These are objective, provider-reported facts — not heuristics — so they alone
# cost the platform a refund (and earn the single budget-doubling repair).
#
# EVERY other completeness code — a missing internal completion sentinel, an
# unbalanced code fence, an incomplete harness file block, a dangling trailing
# line, plus all depth/quality opinions (shallow section, thin requirement count,
# traceability gap) — is delivered as a NON-blocking advisory finding and NEVER
# refunded or re-run.  The artifact is usable and the user owns it (same stance as
# the critic / missing_sections, issue #34).  This is the fix for the false-refund
# + rerun bleed: a model that ends its turn naturally (no `stopped_by_limit`) has
# *finished* — if it merely omitted our magic-comment marker or emitted a stray
# ``` , that is a formatting heuristic, not truncation, and must not burn the
# user's credit or trigger a regenerate cascade.  Genuine structural loss (a
# dropped required section) is still caught independently by `validate_sections`,
# which blocks terminally **without** refunding and is user-overridable — strictly
# better than a refund.  Keeping this discriminator exhaustive over the codes the
# validator emits is the single source of truth for "does this cost a refund".
REFUNDABLE_INCOMPLETE_CODES: frozenset[str] = frozenset(
    {
        "empty_artifact",
        "provider_stopped_by_limit",
    }
)


@dataclass(frozen=True)
class CompletenessIssue:
    code: str
    detail: str
    reference: str | None = None

    @property
    def is_refundable(self) -> bool:
        """True when this issue means genuinely truncated/corrupt output."""
        return self.code in REFUNDABLE_INCOMPLETE_CODES


class IncompleteArtifactError(RuntimeError):
    """Raised when an artifact has the right broad shape but is not complete."""

    def __init__(
        self,
        stage_type: str,
        issues: list[CompletenessIssue],
        *,
        partial_content: str = "",
        repair_attempted: bool = False,
    ) -> None:
        self.stage_type = stage_type
        self.issues = issues
        self.partial_content = partial_content
        self.repair_attempted = repair_attempted
        joined = "; ".join(issue.detail for issue in issues)
        super().__init__(f"Stage {stage_type} artifact is incomplete: {joined}")

    @property
    def truncation_issues(self) -> list[CompletenessIssue]:
        """The refundable (truncated/corrupt) subset of issues."""
        return [issue for issue in self.issues if issue.is_refundable]

    @property
    def depth_issues(self) -> list[CompletenessIssue]:
        """The non-refundable depth/quality subset, attached as advisory."""
        return [issue for issue in self.issues if not issue.is_refundable]


class MissingSectionError(RuntimeError):
    """Raised when a generated artifact omits one or more required headings."""

    def __init__(self, stage_type: str, missing: list[str]) -> None:
        self.stage_type = stage_type
        self.missing = missing
        super().__init__(
            f"Stage {stage_type} is missing required sections: {', '.join(missing)}"
        )


def validate_sections(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str] | None = None,
    mode: str = "standard",
) -> None:
    """Assert every required section heading appears in artifact_md.

    The contract is selected by ``mode`` (standard vs demo_day). Conditional
    sections (T-242 Frontend Architecture) are a standard-mode concept enforced
    only when their sentinel matches in the upstream deps; the lean Demo Day
    contract has no conditional sections.

    Raises MissingSectionError listing all absent headings (does NOT
    short-circuit at the first miss — returning the full list improves UX).
    """
    required = list(section_contract(stage_type, mode))
    deps = deps or {}
    upstream = " ".join(deps.values())
    if mode != "demo_day":
        for sentinel, heading in _CONDITIONAL_SECTIONS.get(stage_type, []):
            if sentinel.search(upstream):
                required.append(heading)

    missing = [heading for heading in required if heading not in artifact_md]
    if missing:
        raise MissingSectionError(stage_type, missing)


def final_completion_sentinel(stage_type: str) -> str:
    return FINAL_COMPLETION_SENTINEL_TEMPLATE.format(stage=stage_type)


def chunk_completion_sentinel(stage_type: str, chunk_key: str) -> str:
    safe_key = re.sub(r"[^a-z0-9_-]+", "-", chunk_key.lower()).strip("-") or "chunk"
    return CHUNK_COMPLETION_SENTINEL_TEMPLATE.format(
        stage=stage_type,
        chunk=safe_key,
    )


def completion_instruction(stage_type: str, *, chunk_key: str | None = None) -> str:
    sentinel = (
        final_completion_sentinel(stage_type)
        if chunk_key is None
        else chunk_completion_sentinel(stage_type, chunk_key)
    )
    final_line = (
        "- End the response with this exact sentinel on its own final line: "
        f"{sentinel}\n"
    )
    return (
        "\n\nCompletion contract:\n"
        f"{final_line}"
        "- Do not put any content after the sentinel.\n"
        "- Every requested heading must have substantive body content; do not emit "
        "placeholder, TODO, TBD, or summary-only sections.\n"
    )


def strip_completion_sentinel(
    stage_type: str,
    artifact_md: str,
    *,
    chunk_key: str | None = None,
) -> str:
    sentinel = (
        final_completion_sentinel(stage_type)
        if chunk_key is None
        else chunk_completion_sentinel(stage_type, chunk_key)
    )
    lines = artifact_md.rstrip().splitlines()
    if lines and lines[-1].strip() == sentinel:
        return "\n".join(lines[:-1]).strip()
    return artifact_md.strip()


def validate_completion_sentinel(
    stage_type: str,
    artifact_md: str,
    *,
    chunk_key: str | None = None,
) -> None:
    sentinel = (
        final_completion_sentinel(stage_type)
        if chunk_key is None
        else chunk_completion_sentinel(stage_type, chunk_key)
    )
    lines = [line.strip() for line in artifact_md.strip().splitlines() if line.strip()]
    if not lines or lines[-1] != sentinel:
        raise IncompleteArtifactError(
            stage_type,
            [
                CompletenessIssue(
                    code="missing_completion_sentinel",
                    detail="The model did not emit the required completion sentinel.",
                    reference=chunk_key,
                )
            ],
            partial_content=artifact_md,
        )


def validate_artifact_completeness(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str] | None = None,
    mode: str = "standard",
) -> None:
    deps = deps or {}
    issues: list[CompletenessIssue] = []
    stripped = artifact_md.strip()
    if not stripped:
        issues.append(
            CompletenessIssue(
                code="empty_artifact",
                detail="The generated artifact is empty.",
            )
        )
    issues.extend(_section_body_issues(stage_type, stripped, deps, mode))
    issues.extend(_markdown_shape_issues(stripped))
    if mode == "demo_day":
        # Lean Demo-Day-appropriate floors (§6.5). NOT the standard 16-field /
        # ≥5-FR rigor — a ≤5-hour build is deliberately smaller.
        if stage_type == "spec":
            issues.extend(_demo_day_spec_issues(stripped))
        if stage_type == "harness":
            issues.extend(_demo_day_harness_issues(stripped))
        if stage_type == "tasks":
            issues.extend(_demo_day_task_issues(stripped))
    else:
        if stage_type == "spec":
            issues.extend(_spec_issues(stripped))
        if stage_type == "plan":
            issues.extend(_plan_issues(stripped, deps))
        if stage_type == "harness":
            issues.extend(_harness_issues(stripped))
        if stage_type == "tasks":
            issues.extend(_task_issues(stripped, deps))
    if stage_type in {"plan", "harness", "tasks"}:
        # Cross-stage ID preservation (every upstream FR/NFR/SEC/AC present) is
        # mode-agnostic and load-bearing for traceability in both modes.
        issues.extend(_traceability_issues(stripped, deps))
    if issues:
        raise IncompleteArtifactError(
            stage_type,
            issues,
            partial_content=artifact_md,
        )


def _required_headings(
    stage_type: str, deps: dict[str, str], mode: str = "standard"
) -> list[str]:
    required = list(section_contract(stage_type, mode))
    if mode == "demo_day":
        return required
    upstream = " ".join(deps.values())
    for sentinel, heading in _CONDITIONAL_SECTIONS.get(stage_type, []):
        if sentinel.search(upstream):
            required.append(heading)
    return required


def _conditional_headings_for_stage(stage_type: str) -> frozenset[str]:
    """The set of headings that are CONDITIONAL (sentinel-gated) for a stage.

    A conditional section may legitimately be answered with the prompt-blessed
    one-line ``Not applicable because <reason>`` declaration when its surface is
    out of scope (e.g. Frontend Architecture on a backend/CLI plan). The depth
    floor must exempt that blessed body for these headings only — never for the
    unconditional sections, which always require substantive content.
    """
    return frozenset(
        heading for _, heading in _CONDITIONAL_SECTIONS.get(stage_type, [])
    )


# Matches the prompt-blessed "Not applicable because <reason>" body a conditional
# section is explicitly authorised to carry when its surface is out of scope
# (prompts/plan.py — Frontend Architecture on a backend-only project). Anchored
# to the start of the *raw* section body so a section that merely mentions the
# phrase deeper in real prose is not mistaken for an out-of-scope declaration.
_NOT_APPLICABLE_RE = re.compile(r"^\s*not\s+applicable\b", re.IGNORECASE)


def _is_not_applicable_body(body: str) -> bool:
    return bool(_NOT_APPLICABLE_RE.match(body))


def _section_body_issues(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
    mode: str = "standard",
) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    conditional = _conditional_headings_for_stage(stage_type)
    for heading in _required_headings(stage_type, deps, mode):
        body = _section_body(artifact_md, heading)
        # A conditional section answered with the blessed "Not applicable …"
        # one-liner is valid even though it is well under the depth floor — the
        # prompt explicitly authorises it for an out-of-scope surface. Honour
        # that contract instead of firing a false shallow advisory (audit
        # finding #2). The exemption is scoped to conditional headings so an
        # unconditional section can never escape the floor by declaring itself
        # not applicable.
        if heading in conditional and _is_not_applicable_body(body):
            continue
        body_text = _normalise_body_for_depth(body)
        if len(body_text) < _min_body_chars(stage_type, mode):
            issues.append(
                CompletenessIssue(
                    code="shallow_required_section",
                    detail=f"{heading} does not contain substantive content.",
                    reference=heading,
                )
            )
    return issues


def _section_body(artifact_md: str, heading: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        re.MULTILINE,
    )
    match = pattern.search(artifact_md)
    if not match:
        return ""
    return match.group(1).strip()


def _normalise_body_for_depth(body: str) -> str:
    # Strip only the fence *markers* (``` and any language tag) and keep the
    # fenced body — a Mermaid/ASCII diagram or code block is real, measurable
    # substance.  Sections like "## User Flow Diagrams" are prompted to be a
    # diagram in a fenced block; discarding the whole block made every such
    # section read as empty and trip a spurious shallow finding (the refund
    # bleed this fix targets).
    body = re.sub(r"(?m)^[ \t]*```[^\n]*$", " ", body)
    # Drop markdown table rules/pipes but keep cell text.
    body = re.sub(r"\|?-+\|[-|\s]*", " ", body)
    body = re.sub(r"[*_`>#\[\]()|-]+", " ", body)
    body = re.sub(r"\b(?:TODO|TBD|placeholder|lorem ipsum)\b", " ", body, flags=re.I)
    return " ".join(body.split())


def _min_body_chars(stage_type: str, mode: str = "standard") -> int:
    """Minimum normalised body characters for a required section to count as
    substantive.

    These floors are deliberately well above "a heading restated as one short
    clause" — the depth failure mode where a token-squeezed model emits every
    required heading with a single throwaway sentence under each.  They stay
    below the size of a genuinely minimal-but-real section so terse legitimate
    artifacts (e.g. a focused Out of Scope list) still pass.

    Demo Day uses a HIGHER floor (not the same as standard, as the v1 plan §6.5
    assumed): the Demo Day section set is lean on breadth, so each retained
    section must carry implementation-grade DEPTH or it gives the coding agent no
    direction. The v1 "shared, low" floor is exactly what let cheap-tier Demo Day
    generations pass with one-liner sections; a mode-scoped floor surfaces a thin
    section as an advisory (non-blocking — issue #34 stance) without touching the
    standard contract (the §4 regression pin).
    """
    if mode == "demo_day":
        return {
            "spec": 160,
            "plan": 180,
            "harness": 90,
            "tasks": 80,
        }.get(stage_type, 80)
    return {
        "spec": 120,
        "plan": 150,
        "harness": 60,
        "tasks": 50,
    }.get(stage_type, 50)


def _markdown_shape_issues(artifact_md: str) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    if artifact_md.count("```") % 2 != 0:
        issues.append(
            CompletenessIssue(
                code="unbalanced_code_fence",
                detail="Markdown code fences are not balanced.",
            )
        )
    final_line = next(
        (line.strip() for line in reversed(artifact_md.splitlines()) if line.strip()),
        "",
    )
    if (
        final_line
        and _INCOMPLETE_TRAILING_RE.search(final_line)
        and not _ends_with_complete_table_row(final_line)
    ):
        issues.append(
            CompletenessIssue(
                code="dangling_trailing_line",
                detail=(
                    "The artifact appears to end mid-table, mid-list, or " "mid-clause."
                ),
            )
        )
    return issues


# Minimum distinct requirement/acceptance IDs a spec must carry.  Degenerate
# floors only: any real product spec clears these easily, but a token-starved
# generation that compresses requirements into prose (no stable IDs, or two
# token FRs) is caught and routed into the repair pass instead of flowing
# downstream where plan/harness/tasks traceability would silently degrade.
_SPEC_MIN_ID_FLOORS: tuple[tuple[str, int], ...] = (
    ("FR", 5),
    ("NFR", 3),
    ("AC", 3),
)


def _spec_issues(artifact_md: str) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    for heading in [
        "## Functional Requirements",
        "## Non-Functional Requirements",
        "## Security, Privacy, and Abuse Expectations",
        "## Acceptance Criteria",
    ]:
        body = _section_body(artifact_md, heading)
        if not _table_or_block_has_evidence(body):
            issues.append(
                CompletenessIssue(
                    code="missing_evidence_contract",
                    detail=(
                        f"{heading} must include an Evidence column or explicit "
                        "evidence lines so generated outputs are objectively "
                        "verifiable."
                    ),
                    reference=heading,
                )
            )
    for prefix, minimum in _SPEC_MIN_ID_FLOORS:
        distinct = set(re.findall(rf"\b{prefix}-\d{{3}}\b", artifact_md))
        if len(distinct) < minimum:
            issues.append(
                CompletenessIssue(
                    code="insufficient_requirement_ids",
                    detail=(
                        f"SPEC must define at least {minimum} distinct "
                        f"{prefix}-NNN identifiers; found {len(distinct)}. "
                        "Shallow or compressed requirement coverage breaks "
                        "downstream traceability."
                    ),
                    reference=prefix,
                )
            )
    return issues


def _table_or_block_has_evidence(body: str) -> bool:
    lower = body.lower()
    if "| evidence" in lower or "| verification" in lower:
        return True
    return bool(re.search(r"(?im)^\s*[-*]?\s*(evidence|verification):\s+\S", body))


def _plan_issues(artifact_md: str, deps: dict[str, str]) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    upstream_ids = _upstream_requirement_ids(deps) | _upstream_acceptance_ids(deps)
    if upstream_ids:
        rtm = _section_body(artifact_md, "## Requirement Traceability Matrix")
        present = set(_REQUIREMENT_ID_RE.findall(rtm))
        present.update(_AC_ID_RE.findall(rtm))
        missing = sorted(upstream_ids - present)
        if missing:
            issues.append(
                CompletenessIssue(
                    code="rtm_missing_upstream_id",
                    detail=(
                        "PLAN Requirement Traceability Matrix is missing upstream "
                        f"requirement or acceptance IDs: {', '.join(missing[:10])}."
                    ),
                    reference=", ".join(missing[:10]),
                )
            )
    return issues


_FILE_HEADING_RE = re.compile(r"^###\s+File:\s+(.+?)\s*$", re.MULTILINE)
# A backticked matrix cell that names a test file: a path with a directory
# component and a file extension whose stem/path reads as a test (``test``,
# ``spec``, or a ``tests/`` directory). Language-agnostic on purpose — the
# previous matrix check keyed on the Python ``test_`` prefix / ``def test_`` and
# silently no-opped on TS/Vitest, Go, Ruby, etc. harnesses.
_MATRIX_TEST_FILE_RE = re.compile(r"`([^`]+?\.[A-Za-z0-9]+)`")


def _normalise_harness_path(path: str) -> str:
    """Strip a leading ``harness/`` segment and surrounding whitespace."""
    cleaned = path.strip().replace("\\", "/")
    if cleaned.startswith("harness/"):
        cleaned = cleaned[len("harness/") :]
    return cleaned


def _looks_like_test_file_path(token: str) -> bool:
    cleaned = token.strip()
    if "/" not in cleaned or "." not in cleaned.rsplit("/", 1)[-1]:
        return False
    lowered = cleaned.lower()
    return "test" in lowered or "spec" in lowered


def dedupe_file_blocks(artifact_md: str) -> tuple[str, int]:
    """Drop duplicate ``### File: <path>`` blocks, keeping the first of each.

    Language-agnostic self-heal for a harness whose ``## Files`` section was
    emitted more than once — the cheap-tier model looping, or a chunk merge
    concatenating overlapping output (observed: a 122 KB harness that was an
    exact doubling of a 61 KB one). Only the ``## Files`` region is touched, so
    the Overview / Matrix / Coverage Plan / File Tree are never altered. Returns
    the deduped artifact and the number of duplicate blocks removed (0 when the
    artifact has no ``## Files`` section or no duplicates — a safe no-op for
    every non-harness stage).
    """
    files_idx = artifact_md.find("\n## Files")
    if files_idx == -1:
        return artifact_md, 0
    head = artifact_md[:files_idx]
    files_region = artifact_md[files_idx:]
    # Split at each File heading; segment[0] is the "## Files" preamble.
    segments = re.split(r"(?m)(?=^###\s+File:\s+)", files_region)
    seen: set[str] = set()
    kept: list[str] = [segments[0]]
    removed = 0
    for segment in segments[1:]:
        match = _FILE_HEADING_RE.match(segment)
        path = _normalise_harness_path(match.group(1)) if match else ""
        if path and path in seen:
            removed += 1
            continue
        if path:
            seen.add(path)
        kept.append(segment)
    if removed == 0:
        return artifact_md, 0
    return head + "".join(kept), removed


_MATRIX_REQ_ID_RE = re.compile(r"^(?:FR|NFR|SEC|AC)-\d+(?:\.\d+)*$")


def uncovered_requirements(harness_content: str) -> list[str]:
    """Requirement IDs whose every mapped matrix test file was never emitted.

    Reads the Requirement-to-Test Matrix as the source of truth for what each
    requirement's test *should* be, then checks the ``## Files`` section for what
    was actually emitted. A requirement is genuinely uncovered only when it maps
    to ≥1 test file and **none** of those files exist as a ``### File:`` block —
    so a requirement with at least one emitted test (even if another of its tiers
    was trimmed) is correctly treated as covered, not a gap.

    This replaces the old "scrape ``TestCategoryGap reqs=``" heuristic, which
    surfaced *category-depth* trims as per-requirement gaps and so listed
    requirements that already had tests. The returned set is the honest input to
    both the coverage panel and the paid harness patch: it collapses to the real
    holes (and to ``[]`` for a fully emitted harness). Order is matrix order;
    duplicates are removed. Conservative by construction: a requirement whose row
    names no parseable test file is never invented as a gap.
    """
    matrix = _section_body(harness_content, "## Requirement-to-Test Matrix")
    if not matrix:
        return []
    emitted = {
        _normalise_harness_path(path)
        for path in _FILE_HEADING_RE.findall(harness_content)
    }
    req_files: dict[str, set[str]] = {}
    order: list[str] = []
    for line in matrix.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [
            cell.strip().strip("`").strip() for cell in stripped.strip("|").split("|")
        ]
        if not cells:
            continue
        req = cells[0].upper()
        if not _MATRIX_REQ_ID_RE.match(req):
            continue
        files = {
            _normalise_harness_path(cell)
            for cell in cells[1:]
            if _looks_like_test_file_path(cell)
        }
        if not files:
            continue
        if req not in req_files:
            req_files[req] = set()
            order.append(req)
        req_files[req] |= files
    return [
        req for req in order if req_files[req] and req_files[req].isdisjoint(emitted)
    ]


def _harness_issues(artifact_md: str) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    tree_paths = _file_tree_paths(_section_body(artifact_md, "## File Tree"))
    file_headings = [
        path.strip()
        for path in re.findall(r"^###\s+File:\s+(.+?)$", artifact_md, re.MULTILINE)
    ]
    if tree_paths:
        missing_blocks = sorted(tree_paths - set(file_headings))
        if missing_blocks:
            issues.append(
                CompletenessIssue(
                    code="harness_file_tree_missing_block",
                    detail=(
                        "HARNESS File Tree lists files that are missing from "
                        f"the ## Files section: {', '.join(missing_blocks[:10])}."
                    ),
                    reference=", ".join(missing_blocks[:10]),
                )
            )
    matrix = _section_body(artifact_md, "## Requirement-to-Test Matrix")
    # Language-agnostic matrix integrity: every test FILE the matrix promises a
    # requirement must exist as a `### File:` block. Catches the silent coverage
    # hole where the matrix maps NFR-001 to `tests/performance/perf.test.ts` but
    # that file is never emitted (and is absent from the File Tree too, so the
    # tree→files check above also misses it). Works on any test framework,
    # unlike the `test_`-prefixed name check below which is pytest-shaped.
    emitted_files = {
        _normalise_harness_path(path) for path in _FILE_HEADING_RE.findall(artifact_md)
    }
    if matrix and emitted_files:
        matrix_files = {
            _normalise_harness_path(token)
            for token in _MATRIX_TEST_FILE_RE.findall(matrix)
            if _looks_like_test_file_path(token)
        }
        missing_files = sorted(matrix_files - emitted_files)
        if missing_files:
            issues.append(
                CompletenessIssue(
                    code="harness_matrix_missing_file",
                    detail=(
                        "HARNESS Requirement-to-Test Matrix maps requirements to "
                        "test files that were never emitted in the ## Files "
                        f"section: {', '.join(missing_files[:10])}."
                    ),
                    reference=", ".join(missing_files[:10]),
                )
            )
    file_body = _section_body(artifact_md, "## Files")
    test_names = set(re.findall(r"\btest_[A-Za-z0-9_]+", file_body))
    matrix_tests = set(re.findall(r"\btest_[A-Za-z0-9_]+", matrix))
    missing_tests = sorted(matrix_tests - test_names)
    if missing_tests:
        issues.append(
            CompletenessIssue(
                code="harness_matrix_missing_test",
                detail=(
                    "HARNESS Requirement-to-Test Matrix references tests absent "
                    f"from file contents: {', '.join(missing_tests[:10])}."
                ),
                reference=", ".join(missing_tests[:10]),
            )
        )
    for test_name in sorted(test_names):
        if not _test_has_traceability_comment(file_body, test_name):
            issues.append(
                CompletenessIssue(
                    code="missing_test_traceability_comment",
                    detail=(
                        f"HARNESS test {test_name} lacks an immediate Tests: "
                        "traceability comment."
                    ),
                    reference=test_name,
                )
            )
            break
    if "## Files" not in artifact_md:
        return issues
    file_blocks = list(_FILE_BLOCK_RE.finditer(artifact_md))
    if not file_blocks:
        issues.append(
            CompletenessIssue(
                code="missing_harness_file_blocks",
                detail=(
                    "HARNESS must include complete fenced code blocks under "
                    "File headings."
                ),
                reference="## Files",
            )
        )
    file_headings = re.findall(r"^###\s+File:\s+(.+?)$", artifact_md, re.MULTILINE)
    complete_paths = {match.group(1).strip() for match in file_blocks}
    for path in file_headings:
        if path.strip() not in complete_paths:
            issues.append(
                CompletenessIssue(
                    code="incomplete_harness_file_block",
                    detail=(
                        f"Harness file {path.strip()} lacks a complete fenced "
                        "code block."
                    ),
                    reference=path.strip(),
                )
            )
    return issues


def _test_has_traceability_comment(file_body: str, test_name: str) -> bool:
    lines = file_body.splitlines()
    for index, line in enumerate(lines):
        if not re.search(rf"\b{re.escape(test_name)}\b", line):
            continue
        previous = [candidate.strip() for candidate in lines[max(0, index - 3) : index]]
        return any(
            re.match(r"^(#|//)\s*Tests:\s*(FR|NFR|SEC|AC)-\d{3}", candidate)
            for candidate in previous
        )
    return False


def _file_tree_paths(body: str) -> set[str]:
    paths: set[str] = set()
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        line = re.sub(r"^[├└│\s`-]+", "", line).strip()
        line = line.split("#", 1)[0].strip()
        if not line or line.endswith("/"):
            continue
        if "/" in line and "." in line.rsplit("/", 1)[-1]:
            paths.add(line)
    return paths


# Degenerate floor for the task inventory: even a trivial product decomposes
# into more than a handful of implementation tasks, so fewer than this many
# blocks signals a compressed, shallow generation rather than a small project.
_MIN_TASK_BLOCKS = 6


def _task_issues(artifact_md: str, deps: dict[str, str]) -> list[CompletenessIssue]:
    task_headers = list(_TASK_HEADER_RE.finditer(artifact_md))
    if not task_headers:
        return [
            CompletenessIssue(
                code="missing_task_blocks",
                detail="TASKS.md must include at least one ### T-NNN task block.",
                reference="tasks",
            )
        ]
    issues_floor: list[CompletenessIssue] = []
    if len(task_headers) < _MIN_TASK_BLOCKS:
        issues_floor.append(
            CompletenessIssue(
                code="insufficient_task_count",
                detail=(
                    f"TASKS.md contains only {len(task_headers)} task blocks; "
                    f"at least {_MIN_TASK_BLOCKS} are required for a "
                    "non-degenerate implementation breakdown."
                ),
                reference="tasks",
            )
        )
    required_fields = [
        "**Phase:**",
        "**Spec refs:**",
        "**Plan refs:**",
        "**Harness refs:**",
        "**Priority:**",
        "**Estimate:**",
        "**Estimated size:**",
        "**Risk:**",
        "**Owner:**",
        "**Description**",
        "**Inputs**",
        "**Outputs**",
        "**Steps**",
        "**Acceptance Criteria**",
        "**Rollback / Recovery**",
        "**Dependencies**",
    ]
    issues: list[CompletenessIssue] = issues_floor
    tasks: list[tuple[int, str]] = []
    # task_num -> the task numbers it declares a dependency on. Built here and
    # checked for *cycles* (not numeric ordering) after the loop — a model may
    # legitimately number tasks by feature area, so a forward reference like
    # T-003 -> T-008 is valid as long as the dependency graph stays acyclic
    # (audit finding #5).
    dep_adjacency: dict[int, set[int]] = {}
    for index, match in enumerate(task_headers):
        end = (
            task_headers[index + 1].start()
            if index + 1 < len(task_headers)
            else len(artifact_md)
        )
        block = artifact_md[match.start() : end]
        task_num = int(match.group(0).split("-")[1].split(":")[0])
        tasks.append((task_num, block))
        missing = [field for field in required_fields if field not in block]
        if missing:
            detail = (
                f"{match.group(0).rstrip(':')} is missing required fields: "
                f"{', '.join(missing[:4])}."
            )
            issues.append(
                CompletenessIssue(
                    code="incomplete_task_block",
                    detail=detail,
                    reference=match.group(0).rstrip(":"),
                )
            )
        deps_value = _task_field_value(block, "Dependencies")
        dep_adjacency[task_num] = {
            int(dep) for dep in _TASK_DEP_RE.findall(deps_value or "")
        }
    issues.extend(_task_dependency_cycle_issues(dep_adjacency))
    issues.extend(_effort_summary_issues(artifact_md, tasks))
    issues.extend(_task_harness_ref_issues(artifact_md, deps))
    return issues


def _task_dependency_cycle_issues(
    dep_adjacency: dict[int, set[int]],
) -> list[CompletenessIssue]:
    """Flag any *circular* task dependency (a genuinely unresolvable order).

    Replaces the old ``dep_num >= task_num`` heuristic, which assumed strict
    topological numbering and so falsely flagged legitimate forward references
    (audit finding #5). Acyclicity is decided by a Kahn's-algorithm topological
    peel over the subgraph of *defined* tasks (edges to undefined task numbers
    cannot close a cycle and are ignored; a self-dependency is a one-node cycle).
    The peel is iterative, so a pathologically deep dependency chain can never
    blow the recursion limit. Emits a single advisory issue naming the tasks that
    participate in a cycle, or none when the graph is acyclic.
    """
    defined = set(dep_adjacency)
    # Restrict edges to defined tasks; a self-loop is kept so it is caught.
    edges: dict[int, set[int]] = {
        num: {dep for dep in deps if dep in defined}
        for num, deps in dep_adjacency.items()
    }
    indegree: dict[int, int] = {num: 0 for num in defined}
    for deps in edges.values():
        for dep in deps:
            indegree[dep] += 1
    queue = [num for num in defined if indegree[num] == 0]
    removed = 0
    while queue:
        num = queue.pop()
        removed += 1
        for dep in edges[num]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                queue.append(dep)
    if removed == len(defined):
        return []
    cyclic = sorted(num for num in defined if indegree[num] > 0)
    return [
        CompletenessIssue(
            code="invalid_task_dependency_order",
            detail=(
                "TASKS.md has a circular task dependency among: "
                f"{', '.join(f'T-{n:03d}' for n in cyclic[:10])}."
            ),
            reference=", ".join(f"T-{n:03d}" for n in cyclic[:10]),
        )
    ]


def _task_field_value(block: str, field_name: str) -> str | None:
    for line in block.splitlines():
        match = _TASK_FIELD_RE.match(line.strip())
        if match and match.group("field").strip().lower() == field_name.lower():
            return match.group("value").strip()
    return None


def _effort_summary_issues(
    artifact_md: str,
    tasks: list[tuple[int, str]],
) -> list[CompletenessIssue]:
    if not tasks:
        return []
    summary = _section_body(artifact_md, "## Effort Summary")
    task_count_match = re.search(r"Tasks:\s*(\d+)\s+total", summary)
    actual = len(tasks)
    issues: list[CompletenessIssue] = []
    if task_count_match and int(task_count_match.group(1)) != actual:
        issues.append(
            CompletenessIssue(
                code="effort_summary_task_count_mismatch",
                detail=(
                    f"Effort Summary says {task_count_match.group(1)} tasks but "
                    f"the artifact contains {actual} task blocks."
                ),
                reference="## Effort Summary",
            )
        )
    priority_counts = {name: 0 for name in ["MUST", "SHOULD", "COULD"]}
    estimate_counts = {name: 0 for name in ["XL", "L", "M", "S"]}
    for _, block in tasks:
        priority = _first_token(_task_field_value(block, "Priority"))
        estimate = _first_token(_task_field_value(block, "Estimate"))
        if priority in priority_counts:
            priority_counts[priority] += 1
        if estimate in estimate_counts:
            estimate_counts[estimate] += 1
    for name, count in priority_counts.items():
        match = re.search(rf"(\d+)\s+{name}\b", summary)
        if match and int(match.group(1)) != count:
            issues.append(
                CompletenessIssue(
                    code="effort_summary_priority_mismatch",
                    detail=(
                        f"Effort Summary says {match.group(1)} {name} tasks but "
                        f"task blocks contain {count}."
                    ),
                    reference=name,
                )
            )
            break
    for name, count in estimate_counts.items():
        match = re.search(rf"(\d+)x{name}\b", summary)
        if match and int(match.group(1)) != count:
            issues.append(
                CompletenessIssue(
                    code="effort_summary_estimate_mismatch",
                    detail=(
                        f"Effort Summary says {match.group(1)}x{name} but task "
                        f"blocks contain {count}."
                    ),
                    reference=name,
                )
            )
            break
    return issues


def _first_token(value: str | None) -> str:
    parts = (value or "").split()
    return parts[0].upper() if parts else ""


def _task_harness_ref_issues(
    artifact_md: str,
    deps: dict[str, str],
) -> list[CompletenessIssue]:
    harness = deps.get("harness", "")
    if not harness:
        return []
    known = _harness_test_refs(harness)
    if not known:
        return []
    task_refs = {
        ref
        for ref in re.findall(r"`([^`]*test_[^`]*)`", artifact_md)
        if "::" in ref or "/" in ref
    }
    missing_refs = sorted(ref for ref in task_refs if not _ref_matches(ref, known))
    if missing_refs:
        return [
            CompletenessIssue(
                code="task_harness_ref_not_found",
                detail=(
                    "TASKS.md references harness tests that are absent from the "
                    f"HARNESS artifact: {', '.join(missing_refs[:10])}."
                ),
                reference=", ".join(missing_refs[:10]),
            )
        ]
    return []


def _harness_test_refs(harness: str) -> set[str]:
    known: set[str] = set()
    current_path: str | None = None
    current_class: str | None = None
    for line in harness.splitlines():
        heading = re.match(r"^###\s+File:\s+(.+?)$", line)
        if heading:
            current_path = heading.group(1).strip()
            if current_path.startswith("harness/"):
                current_path = current_path[len("harness/") :]
            current_class = None
            continue
        class_match = re.match(r"^class\s+(Test\w+)", line)
        if class_match:
            current_class = class_match.group(1)
            continue
        if line and not line.startswith((" ", "\t")):
            current_class = None
        test_match = re.match(r"^\s*def\s+(test_\w+)", line)
        if not test_match:
            continue
        name = test_match.group(1)
        known.add(name)
        if current_path:
            known.add(f"{current_path}::{name}")
        if current_class:
            known.add(f"{current_class}::{name}")
            if current_path:
                known.add(f"{current_path}::{current_class}::{name}")
    return known


def _ref_matches(ref: str, known: set[str]) -> bool:
    normalized = ref.strip().replace("\\", "/")
    if normalized.startswith("harness/"):
        normalized = normalized[len("harness/") :]
    if normalized in known:
        return True
    parts = normalized.split("::")
    return bool(parts) and (parts[-1] in known or "::".join(parts[-2:]) in known)


# ---------------------------------------------------------------------------
# Demo Day mode floors (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §6.5). These
# replace the standard spec/harness/tasks floors for demo_day workspaces: a
# ≤5-hour build is deliberately smaller, and the construction verifier (§7) does
# the heavier structural verification. Every code emitted here is non-refundable
# (not in REFUNDABLE_INCOMPLETE_CODES), so it surfaces as a non-blocking advisory
# finding — the user owns the artifact (issue #34 stance), exactly as the
# standard ``insufficient_task_count`` / ``insufficient_requirement_ids`` floors.
# ---------------------------------------------------------------------------

_DEMO_DAY_MIN_FR = 3
_DEMO_DAY_MIN_AC = 3
_DEMO_DAY_MIN_TASK_BLOCKS = 4
# Per-task fields a Demo Day task block must carry (§6.4). Mirrors the standard
# bold-field style and adds the two Demo-Day fields (Estimated minutes,
# Precondition) the construction verifier joins on (C1/C5).
_DEMO_DAY_TASK_FIELDS: tuple[str, ...] = (
    "**Spec refs:**",
    "**Plan refs:**",
    "**Harness refs:**",
    "**Priority:**",
    "**Estimate:**",
    "**Estimated minutes:**",
    "**Precondition:**",
    "**Steps**",
    "**Acceptance Criteria**",
)


def _demo_day_spec_issues(artifact_md: str) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    distinct_fr = set(re.findall(r"\bFR-\d{3}\b", artifact_md))
    if len(distinct_fr) < _DEMO_DAY_MIN_FR:
        issues.append(
            CompletenessIssue(
                code="insufficient_requirement_ids",
                detail=(
                    f"Demo Day SPEC must define at least {_DEMO_DAY_MIN_FR} "
                    f"distinct FR-NNN identifiers; found {len(distinct_fr)}."
                ),
                reference="FR",
            )
        )
    # The AC ids must live in the ## Acceptance Criteria section so the verifier's
    # C3 (AC → harness RTM → ≥1 task) can join on them (§7.1.1).
    ac_section = _section_body(artifact_md, "## Acceptance Criteria")
    distinct_ac = set(_AC_ID_RE.findall(ac_section))
    if len(distinct_ac) < _DEMO_DAY_MIN_AC:
        issues.append(
            CompletenessIssue(
                code="insufficient_requirement_ids",
                detail=(
                    f"Demo Day SPEC must define at least {_DEMO_DAY_MIN_AC} "
                    "distinct AC-NNN identifiers in the Acceptance Criteria "
                    f"section; found {len(distinct_ac)}."
                ),
                reference="AC",
            )
        )
    return issues


def _e2e_names_a_test(body: str) -> bool:
    """True when the End-to-End Smoke Test section names a concrete test.

    The guarantee-bearing e2e must be cited verbatim by the final task (verifier
    C4), so the section has to name a backticked test file/path or test name —
    not just prose. Conservative: an empty or prose-only section reads as a miss.
    """
    if not body.strip():
        return False
    tokens = re.findall(r"`([^`]+)`", body)
    return any(
        _looks_like_test_file_path(token)
        or "test" in token.lower()
        or "e2e" in token.lower()
        or "smoke" in token.lower()
        for token in tokens
    )


def _demo_day_harness_issues(artifact_md: str) -> list[CompletenessIssue]:
    e2e_body = _section_body(artifact_md, "## End-to-End Smoke Test")
    if not _e2e_names_a_test(e2e_body):
        return [
            CompletenessIssue(
                code="missing_e2e_smoke_test",
                detail=(
                    "Demo Day HARNESS must define at least one End-to-End Smoke "
                    "Test naming the guarantee-bearing test file/path (the "
                    "unmockable test that must be green from the first slice)."
                ),
                reference="## End-to-End Smoke Test",
            )
        ]
    return []


def _demo_day_task_issues(artifact_md: str) -> list[CompletenessIssue]:
    task_headers = list(_TASK_HEADER_RE.finditer(artifact_md))
    if not task_headers:
        return [
            CompletenessIssue(
                code="missing_task_blocks",
                detail="Demo Day TASKS.md must include at least one ### T-NNN block.",
                reference="tasks",
            )
        ]
    issues: list[CompletenessIssue] = []
    if len(task_headers) < _DEMO_DAY_MIN_TASK_BLOCKS:
        issues.append(
            CompletenessIssue(
                code="insufficient_task_count",
                detail=(
                    f"Demo Day TASKS.md contains only {len(task_headers)} task "
                    f"blocks; at least {_DEMO_DAY_MIN_TASK_BLOCKS} are required "
                    "for a verifiable walking-skeleton build."
                ),
                reference="tasks",
            )
        )
    for index, match in enumerate(task_headers):
        end = (
            task_headers[index + 1].start()
            if index + 1 < len(task_headers)
            else len(artifact_md)
        )
        block = artifact_md[match.start() : end]
        missing = [field for field in _DEMO_DAY_TASK_FIELDS if field not in block]
        if missing:
            issues.append(
                CompletenessIssue(
                    code="incomplete_task_fields",
                    detail=(
                        f"{match.group(0).rstrip(':')} is missing required Demo Day "
                        f"task fields: {', '.join(missing[:4])}."
                    ),
                    reference=match.group(0).rstrip(":"),
                )
            )
    return issues


def _upstream_requirement_ids(deps: dict[str, str]) -> set[str]:
    upstream_ids: set[str] = set()
    for content in deps.values():
        upstream_ids.update(_REQUIREMENT_ID_RE.findall(content))
    return upstream_ids


def _upstream_acceptance_ids(deps: dict[str, str]) -> set[str]:
    upstream_ids: set[str] = set()
    for content in deps.values():
        upstream_ids.update(_AC_ID_RE.findall(content))
    return upstream_ids


def _traceability_issues(
    artifact_md: str,
    deps: dict[str, str],
) -> list[CompletenessIssue]:
    upstream_ids = _upstream_requirement_ids(deps)
    if any(key in deps for key in {"spec", "plan", "harness"}):
        upstream_ids.update(_upstream_acceptance_ids(deps))
    if not upstream_ids:
        return []
    present = set(_REQUIREMENT_ID_RE.findall(artifact_md))
    present.update(_AC_ID_RE.findall(artifact_md))
    missing = sorted(upstream_ids - present)
    if not missing:
        return []
    return [
        CompletenessIssue(
            code="insufficient_upstream_traceability",
            detail=(
                "The artifact does not preserve all upstream FR/NFR/SEC/AC IDs "
                f"({len(upstream_ids) - len(missing)}/{len(upstream_ids)} present)."
            ),
            reference=", ".join(missing[:10]),
        )
    ]
