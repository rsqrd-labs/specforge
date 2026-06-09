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
        "## Architecture Quality Attribute",  # T-240
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
_TASK_HEADER_RE = re.compile(r"^###\s+T-\d{3}:", re.MULTILINE)
_FILE_BLOCK_RE = re.compile(
    r"^###\s+File:\s+(.+?)\s*\n+```[^\n]*\n.*?\n```",
    re.MULTILINE | re.DOTALL,
)
_INCOMPLETE_TRAILING_RE = re.compile(r"(:|,\s*|\|\s*)$")


@dataclass(frozen=True)
class CompletenessIssue:
    code: str
    detail: str
    reference: str | None = None


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
) -> None:
    """Assert every required section heading appears in artifact_md.

    Conditional sections (T-242 Frontend Architecture) are enforced only when
    their sentinel matches in the upstream deps.

    Raises MissingSectionError listing all absent headings (does NOT
    short-circuit at the first miss — returning the full list improves UX).
    """
    required = list(SECTION_CONTRACTS.get(stage_type, []))
    deps = deps or {}
    upstream = " ".join(deps.values())
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
    issues.extend(_section_body_issues(stage_type, stripped, deps))
    issues.extend(_markdown_shape_issues(stripped))
    if stage_type == "harness":
        issues.extend(_harness_issues(stripped))
    if stage_type == "tasks":
        issues.extend(_task_issues(stripped))
    if stage_type in {"plan", "harness", "tasks"}:
        issues.extend(_traceability_issues(stripped, deps))
    if issues:
        raise IncompleteArtifactError(
            stage_type,
            issues,
            partial_content=artifact_md,
        )


def _required_headings(stage_type: str, deps: dict[str, str]) -> list[str]:
    required = list(SECTION_CONTRACTS.get(stage_type, []))
    upstream = " ".join(deps.values())
    for sentinel, heading in _CONDITIONAL_SECTIONS.get(stage_type, []):
        if sentinel.search(upstream):
            required.append(heading)
    return required


def _section_body_issues(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
    for heading in _required_headings(stage_type, deps):
        body = _section_body(artifact_md, heading)
        body_text = _normalise_body_for_depth(body)
        if len(body_text) < _min_body_chars(stage_type):
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
    body = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    body = re.sub(r"\|?-+\|[-|\s]*", " ", body)
    body = re.sub(r"[*_`>#\[\]()-]+", " ", body)
    body = re.sub(r"\b(?:TODO|TBD|placeholder|lorem ipsum)\b", " ", body, flags=re.I)
    return " ".join(body.split())


def _min_body_chars(stage_type: str) -> int:
    return {
        "spec": 35,
        "plan": 45,
        "harness": 30,
        "tasks": 25,
    }.get(stage_type, 25)


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
    if final_line and _INCOMPLETE_TRAILING_RE.search(final_line):
        issues.append(
            CompletenessIssue(
                code="dangling_trailing_line",
                detail=(
                    "The artifact appears to end mid-table, mid-list, or " "mid-clause."
                ),
            )
        )
    return issues


def _harness_issues(artifact_md: str) -> list[CompletenessIssue]:
    issues: list[CompletenessIssue] = []
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


def _task_issues(artifact_md: str) -> list[CompletenessIssue]:
    task_headers = list(_TASK_HEADER_RE.finditer(artifact_md))
    if not task_headers:
        return [
            CompletenessIssue(
                code="missing_task_blocks",
                detail="TASKS.md must include at least one ### T-NNN task block.",
                reference="tasks",
            )
        ]
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
    ]
    issues: list[CompletenessIssue] = []
    for index, match in enumerate(task_headers):
        end = (
            task_headers[index + 1].start()
            if index + 1 < len(task_headers)
            else len(artifact_md)
        )
        block = artifact_md[match.start() : end]
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
    return issues


def _traceability_issues(
    artifact_md: str,
    deps: dict[str, str],
) -> list[CompletenessIssue]:
    upstream_ids: set[str] = set()
    for content in deps.values():
        upstream_ids.update(_REQUIREMENT_ID_RE.findall(content))
    if not upstream_ids:
        return []
    present = set(_REQUIREMENT_ID_RE.findall(artifact_md))
    missing = sorted(upstream_ids - present)
    if not missing:
        return []
    coverage = (len(upstream_ids) - len(missing)) / len(upstream_ids)
    if coverage >= 0.8:
        return []
    return [
        CompletenessIssue(
            code="insufficient_upstream_traceability",
            detail=(
                "The artifact does not preserve enough upstream FR/NFR/SEC IDs "
                f"({len(upstream_ids) - len(missing)}/{len(upstream_ids)} present)."
            ),
            reference=", ".join(missing[:10]),
        )
    ]
