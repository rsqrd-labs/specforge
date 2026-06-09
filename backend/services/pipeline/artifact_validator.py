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
_AC_ID_RE = re.compile(r"\bAC-\d{3}\b")
_TASK_HEADER_RE = re.compile(r"^###\s+T-\d{3}:", re.MULTILINE)
_TASK_DEP_RE = re.compile(r"\bT-(\d{3})\b")
_TASK_FIELD_RE = re.compile(r"^\*\*(?P<field>[^*]+):\*\*\s*(?P<value>.*)$")
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
    if stage_type == "spec":
        issues.extend(_spec_issues(stripped))
    if stage_type == "plan":
        issues.extend(_plan_issues(stripped, deps))
    if stage_type == "harness":
        issues.extend(_harness_issues(stripped))
    if stage_type == "tasks":
        issues.extend(_task_issues(stripped, deps))
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
    issues: list[CompletenessIssue] = []
    tasks: list[tuple[int, str]] = []
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
        if deps_value:
            future = [
                int(dep)
                for dep in _TASK_DEP_RE.findall(deps_value)
                if int(dep) >= task_num
            ]
            if future:
                issues.append(
                    CompletenessIssue(
                        code="invalid_task_dependency_order",
                        detail=(
                            f"T-{task_num:03d} depends on a same or later task: "
                            f"{', '.join(f'T-{n:03d}' for n in future[:10])}."
                        ),
                        reference=f"T-{task_num:03d}",
                    )
                )
    issues.extend(_effort_summary_issues(artifact_md, tasks))
    issues.extend(_task_harness_ref_issues(artifact_md, deps))
    return issues


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
