"""Shared chunk-aware artifact fixtures for stage-generation tests.

Chunked generation always runs every chunk (there is no early return), so a
faithful fake adapter must answer each chunk prompt with that chunk's own
section group and chunk sentinel.  The joined chunks then reproduce the full
artifact exactly, which keeps `stage.content == VALID_SPEC`-style equality
assertions meaningful.

The fixture artifacts also satisfy the depth contract enforced by
validate_artifact_completeness: per-section minimum body lengths, the spec's
minimum distinct FR/NFR/AC identifier floors, and (for plans generated against
a spec dependency) full RTM coverage of every upstream requirement ID.
"""

from __future__ import annotations

import re

from services.pipeline.artifact_validator import (
    SECTION_CONTRACTS,
    chunk_completion_sentinel,
)

# ---------------------------------------------------------------------------
# Spec fixture — clears the FR>=5 / NFR>=3 / AC>=3 identifier floors and the
# 120-char per-section depth floor.  Wording deliberately avoids the plan
# Frontend Architecture sentinel words (UI/web/app/page/screen/dashboard/
# console) so plan fixtures are not conditionally required to add a section.
# ---------------------------------------------------------------------------

SPEC_DEFAULT_BODY = (
    "This section captures the team task-management product contract while "
    "preserving traceability to FR-001, NFR-001, SEC-001, and AC-001 without "
    "choosing implementation internals."
)

_FR_ROWS = "\n".join(
    f"| FR-{n:03d} | {actor} | {req} | {outcome} | {edge} | {evidence} |"
    for n, actor, req, outcome, edge, evidence in [
        (
            1,
            "Team member creates or updates a task",
            "Users can create, assign, and track task status across a team "
            "workspace.",
            "Task state is visible to permitted collaborators after save.",
            "Missing owner, duplicate title, and reopened task flows are handled.",
            "Problem statement asks for teams to create tasks, assign owners, "
            "and track project status.",
        ),
        (
            2,
            "Team member assigns a task owner",
            "Tasks carry exactly one accountable owner at any time.",
            "Ownership changes are recorded and visible to collaborators.",
            "Owner removal, transfers, and departed members are handled.",
            "Problem statement requires assigning owners.",
        ),
        (
            3,
            "Team member filters the task list",
            "Tasks can be filtered by status, owner, and due date.",
            "Filtered results match the stored task state.",
            "Empty results and combined filters are handled.",
            "Problem statement requires tracking project status.",
        ),
        (
            4,
            "Team member comments on a task",
            "Collaborators can attach threaded comments to a task.",
            "Comments persist and render in creation order.",
            "Deleted authors and concurrent comments are handled.",
            "Team collaboration is the product core.",
        ),
        (
            5,
            "Workspace owner archives a completed project",
            "Completed projects can be archived without data loss.",
            "Archived projects are excluded from active views but recoverable.",
            "Archiving with open tasks prompts confirmation.",
            "Project lifecycle management is required for teams.",
        ),
    ]
)

_NFR_ROWS = "\n".join(
    f"| NFR-{n:03d} | {quality} | {req} | {outcome} | {edge} | {evidence} |"
    for n, quality, req, outcome, edge, evidence in [
        (
            1,
            "Reliability",
            "Core task operations remain available and recoverable during "
            "normal tenant usage.",
            "Successful task writes are durable and observable.",
            "Retry, transient outage, and partial save conditions are covered.",
            "Paying users depend on task tracking as the product workflow.",
        ),
        (
            2,
            "Performance",
            "Common task reads and writes complete fast enough for "
            "interactive teamwork.",
            "Typical operations finish within an interactive latency budget.",
            "Large workspaces and cold caches are covered.",
            "Teams use the product continuously during the workday.",
        ),
        (
            3,
            "Auditability",
            "Material task and membership changes are attributable to an actor "
            "and time.",
            "An ordered change history exists for each task.",
            "Clock skew and bulk operations are covered.",
            "Accountability is required for team coordination.",
        ),
    ]
)

_AC_ROWS = "\n".join(
    f"| AC-{n:03d} | {scenario} | {outcome} | {verification} | {evidence} |"
    for n, scenario, outcome, verification, evidence in [
        (
            1,
            "A permitted team member creates and assigns a task",
            "The task is stored with owner and status for authorized "
            "collaborators only.",
            "Executable acceptance test covers create, assign, view, and "
            "denied cross-workspace access.",
            "Derived from FR-001, FR-002, and SEC-001.",
        ),
        (
            2,
            "A collaborator filters tasks by owner and status",
            "Only matching tasks are returned, in a stable order.",
            "Executable acceptance test seeds mixed tasks and asserts the "
            "filtered subset.",
            "Derived from FR-003 and NFR-002.",
        ),
        (
            3,
            "A workspace owner archives a finished project",
            "The project leaves active views and remains restorable with "
            "history intact.",
            "Executable acceptance test archives, lists, and restores the " "project.",
            "Derived from FR-005 and NFR-003.",
        ),
    ]
)

SPEC_SECTION_BODIES = {
    "## Functional Requirements": (
        "| ID | Actor/Trigger | Requirement | Measurable outcome | Edge cases | "
        "Evidence |\n"
        "|---|---|---|---|---|---|\n"
        f"{_FR_ROWS}"
    ),
    "## Non-Functional Requirements": (
        "| ID | Quality | Requirement | Measurable outcome | Edge cases | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        f"{_NFR_ROWS}"
    ),
    "## Security, Privacy, and Abuse Expectations": (
        "| ID | Actor/Trigger | Control | Measurable outcome | Edge cases | "
        "Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| SEC-001 | Authenticated user accesses workspace data | Enforce "
        "workspace-scoped authorization for reads and writes. | A user cannot "
        "view or mutate another tenant's tasks. | Revoked members, stale "
        "sessions, and privilege changes are denied. | Problem statement "
        "requires authenticated team task management. |"
    ),
    "## Acceptance Criteria": (
        "| ID | Scenario | Expected outcome | Verification | Evidence |\n"
        "|---|---|---|---|---|\n"
        f"{_AC_ROWS}"
    ),
}

# Section groups must mirror _chunk_specs_for_stage in stage_manager so the
# joined chunks reproduce SECTION_CONTRACTS order exactly.
SPEC_CHUNK_SECTIONS: dict[str, tuple[str, ...]] = {
    "product-scope": tuple(SECTION_CONTRACTS["spec"][:7]),
    "system-expectations": tuple(SECTION_CONTRACTS["spec"][7:11]),
    "validation-risk": tuple(SECTION_CONTRACTS["spec"][11:]),
}


def spec_chunk_md(key: str) -> str:
    return "\n\n".join(
        f"{heading}\n{SPEC_SECTION_BODIES.get(heading, SPEC_DEFAULT_BODY)}"
        for heading in SPEC_CHUNK_SECTIONS[key]
    )


VALID_SPEC = "\n\n".join(spec_chunk_md(key) for key in SPEC_CHUNK_SECTIONS)

# Every requirement/acceptance ID the spec fixture declares — the plan RTM
# fixture must cover all of them for _plan_issues to pass.
SPEC_UPSTREAM_IDS: tuple[str, ...] = tuple(
    sorted(set(re.findall(r"\b(?:FR|NFR|SEC)-\d{3}\b", VALID_SPEC)))
    + sorted(set(re.findall(r"\bAC-\d{3}\b", VALID_SPEC)))
)

# ---------------------------------------------------------------------------
# Plan fixture — clears the 150-char per-section depth floor and covers every
# upstream spec ID in the RTM.
# ---------------------------------------------------------------------------

PLAN_DEFAULT_BODY = (
    "This plan section sets out the concrete architecture decisions, module "
    "interfaces, data flows, operational controls, and failure handling needed "
    "to satisfy FR-001 through FR-005, NFR-001 through NFR-003, SEC-001, and "
    "AC-001 through AC-003, with implementation-specific depth suitable for "
    "downstream harness and task generation."
)

_RTM_HEADER = (
    "| Upstream ID | Plan coverage | Interface or control | Test intent |\n"
    "|---|---|---|---|"
)


def _rtm_section_body() -> str:
    rows = "\n".join(
        f"| {upstream_id} | Covered by the service design and persistence "
        f"model for {upstream_id}. | Module boundary and policy checks for "
        f"{upstream_id}. | Covered by acceptance and integration tests. |"
        for upstream_id in SPEC_UPSTREAM_IDS
    )
    return f"{_RTM_HEADER}\n{rows}"


PLAN_CHUNK_SECTIONS: dict[str, tuple[str, ...]] = {
    "architecture-foundation": tuple(SECTION_CONTRACTS["plan"][:4]),
    "quality-and-structure": tuple(SECTION_CONTRACTS["plan"][4:9]),
    "data-api-security": tuple(SECTION_CONTRACTS["plan"][9:15]),
    "operations-risk": tuple(SECTION_CONTRACTS["plan"][15:]),
}


def plan_chunk_md(key: str, technology_stack: str) -> str:
    sections: list[str] = []
    for heading in PLAN_CHUNK_SECTIONS[key]:
        if heading == "## Requirement Traceability Matrix":
            sections.append(f"{heading}\n{_rtm_section_body()}")
        elif heading == "## Technology Stack and Rationale":
            sections.append(f"{heading}\n{technology_stack}")
        else:
            sections.append(f"{heading}\n{PLAN_DEFAULT_BODY}")
    return "\n\n".join(sections)


def complete_plan(technology_stack: str) -> str:
    return "\n\n".join(
        plan_chunk_md(key, technology_stack) for key in PLAN_CHUNK_SECTIONS
    )


# ---------------------------------------------------------------------------
# Chunk-aware fake streaming
# ---------------------------------------------------------------------------

_CHUNK_KEY_RE = re.compile(r"Chunk scope for \w+ \[([a-z0-9_-]+)\]")


def chunk_key_from_prompt(user_prompt: str, default: str) -> str:
    match = _CHUNK_KEY_RE.search(user_prompt)
    return match.group(1) if match else default


def spec_stream_payload(user_prompt: str) -> str:
    """The spec chunk the prompt asked for, ending in its chunk sentinel."""
    key = chunk_key_from_prompt(user_prompt, "product-scope")
    return f"{spec_chunk_md(key)}\n{chunk_completion_sentinel('spec', key)}"


def plan_stream_payload(user_prompt: str, technology_stack: str) -> str:
    """The plan chunk the prompt asked for, ending in its chunk sentinel."""
    key = chunk_key_from_prompt(user_prompt, "architecture-foundation")
    return (
        f"{plan_chunk_md(key, technology_stack)}\n"
        f"{chunk_completion_sentinel('plan', key)}"
    )


def make_spec_stream():
    """A fake adapter.stream that answers each spec chunk prompt correctly."""

    async def fake_stream(system: str, user: str, **kwargs):
        yield spec_stream_payload(user)

    return fake_stream


def make_plan_stream(technology_stack: str):
    """A fake adapter.stream that answers each plan chunk prompt correctly."""

    async def fake_stream(system: str, user: str, **kwargs):
        yield plan_stream_payload(user, technology_stack)

    return fake_stream
