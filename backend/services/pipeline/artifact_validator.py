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
