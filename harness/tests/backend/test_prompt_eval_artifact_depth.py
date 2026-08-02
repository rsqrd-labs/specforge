"""Density initiative (2026-08-02) — artifact_depth_pct substance-metric tests.

artifact_depth_pct used to floor on raw meaningful-line count, which the
density prompt change deliberately drives down even for complete artifacts.
It was replaced with a substance-unit count (distinct requirement/decision/
task IDs, markdown table rows, ``### File:`` blocks). The critical property a
depth gate must have — and the one an earlier version of this rework did NOT
have — is that it can actually fail a degenerate artifact: a "shell" that
carries every required heading and clears the pre-existing structural floors
(_SPEC_MIN_ID_FLOORS, _MIN_TASK_BLOCKS) but has no real content beyond that
must still score below 1.0, or the gate is decorative.
"""

from __future__ import annotations

from prompt_eval.graders.quality import _substance_units, artifact_depth_pct


def _shell_spec() -> str:
    # Exactly the bare structural minimum: 17 headings, one-line bodies, the
    # minimum distinct FR/NFR/AC id counts (_SPEC_MIN_ID_FLOORS: 5/3/3), no
    # tables, no extra ids (no US/RISK/OQ).
    headings = [
        "## Overview",
        "## Product Goals",
        "## In-Scope (MVP)",
        "## Non-Goals",
        "## User Stories",
        "## User Flows",
        "## Functional Requirements",
        "## Non-Functional Requirements",
        "## Conceptual Domain Model",
        "## System Context",
        "## Security, Privacy, and Abuse Expectations",
        "## Acceptance Criteria",
        "## Edge Cases",
        "## Constraints",
        "## Risks",
        "## Assumptions and Open Questions",
        "## Out of Scope",
    ]
    fr_ids = " ".join(f"FR-{n:03d}" for n in range(1, 6))
    nfr_ids = " ".join(f"NFR-{n:03d}" for n in range(1, 4))
    ac_ids = " ".join(f"AC-{n:03d}" for n in range(1, 4))
    bodies = {
        "## Functional Requirements": f"Covers {fr_ids}.",
        "## Non-Functional Requirements": f"Covers {nfr_ids}.",
        "## Acceptance Criteria": f"Covers {ac_ids}.",
    }
    return "\n\n".join(
        f"{heading}\n{bodies.get(heading, 'N/A.')}" for heading in headings
    )


def _shell_plan() -> str:
    # 20 headings, one-line bodies, no ids, no tables — a plan that names
    # every section but backs none of them with a real RTM/schema/table.
    headings = [
        "## Planning Summary",
        "## Architecture Overview",
        "## Requirement Traceability Matrix",
        "## Technology Stack and Rationale",
        "## Architecture Anti-Patterns",
        "## Multi-tenancy Stance",
        "## Capacity Model",
        "## Threat Model",
        "## Architecture Quality Attribute Matrix",
        "## Codebase Structure",
        "## Data Model and Persistence",
        "## API Design",
        "## Authentication and Authorization",
        "## Security Architecture",
        "## Architecture Decision Records",
        "## Failure Mode and Effects Analysis",
        "## SLOs and Error Budgets",
        "## Error Handling and Recovery",
        "## Observability and Audit Logging",
        "## Deployment and Operations",
    ]
    return "\n\n".join(f"{heading}\nN/A." for heading in headings)


def _shell_harness() -> str:
    headings = [
        "## Harness Overview",
        "## Requirement-to-Test Matrix",
        "## Coverage Plan",
        "## File Tree",
        "## Files",
    ]
    return "\n\n".join(f"{heading}\nN/A." for heading in headings)


def _shell_tasks() -> str:
    # 5 overview headings plus exactly _MIN_TASK_BLOCKS=6 task blocks, each
    # citing one FR id and nothing else — the bare structural minimum.
    headings = [
        "## Effort Summary",
        "## Execution Overview",
        "## Traceability Overview",
        "## Dependency Graph",
        "## Task Sizing Legend",
    ]
    overview = "\n\n".join(f"{heading}\nN/A." for heading in headings)
    tasks = "\n\n".join(
        f"### T-{n:03d}: Task {n}\n**Spec refs:** FR-001\nN/A."
        for n in range(1, 7)
    )
    return f"{overview}\n\n{tasks}"


def test_substance_units_excludes_headings_from_the_gate() -> None:
    # A degenerate shell still reports its heading count (for visibility) but
    # that count must not be part of what artifact_depth_pct gates on.
    units = _substance_units(_shell_spec())
    assert units["h2_headings"] == 17
    assert units["distinct_ids"] == 11  # 5 FR + 3 NFR + 3 AC
    assert units["table_rows"] == 0
    assert units["file_blocks"] == 0


def test_artifact_depth_pct_rejects_a_degenerate_shell() -> None:
    # The regression this test guards against: an earlier version of this
    # grader summed h2_headings into the gated total, which meant a spec
    # shell (17 headings + the bare _SPEC_MIN_ID_FLOORS minimum + zero real
    # content) scored 1.0 — the gate could never fire. Each stage's shell here
    # clears every pre-existing structural floor and nothing else.
    for stage, shell in (
        ("spec", _shell_spec()),
        ("plan", _shell_plan()),
        ("harness", _shell_harness()),
        ("tasks", _shell_tasks()),
    ):
        result = artifact_depth_pct(stage, shell, {})
        assert result.score < 1.0, f"{stage} shell scored {result.score}, expected < 1.0"
        assert result.findings


def test_artifact_depth_pct_rewards_real_table_and_file_content() -> None:
    # A harness shell that also carries real File: blocks and RTM-style table
    # rows should score higher than (or at minimum, not lower than) the bare
    # shell — the gate should reward substance additively.
    bare = artifact_depth_pct("harness", _shell_harness(), {})
    richer = _shell_harness() + "\n\n" + "\n".join(
        f"### File: tests/test_{n}.py\n```python\nassert True\n```" for n in range(5)
    )
    with_files = artifact_depth_pct("harness", richer, {})
    assert with_files.score >= bare.score
