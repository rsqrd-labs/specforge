from __future__ import annotations

import re

from prompt_eval.graders.common import make_result

_EXPECTED_H2 = {
    "spec": [
        "## Overview",
        "## Functional Requirements",
        "## Non-Functional Requirements",
        "## Security, Privacy, and Abuse Expectations",
        "## Acceptance Criteria",
    ],
    "plan": [
        "## Planning Summary",
        "## Architecture Overview",
        "## Requirement Traceability Matrix",
        "## Technology Stack and Rationale",
        "## Data Model and Persistence",
        "## API Design",
        "## Security Architecture",
        "## Architecture Decision Records",
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


def _h2s(text: str) -> list[str]:
    return re.findall(r"^##\s+.+$", text, flags=re.MULTILINE)


def heading_order_match(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """format: required H2 headings appear in the canonical order."""

    expected = _EXPECTED_H2.get(stage_type, [])
    headings = _h2s(artifact_md)
    if not expected:
        return make_result(name="heading_order_match", axis="format", score=1.0)
    last_index = -1
    matched = 0
    findings: list[str] = []
    for heading in expected:
        try:
            index = headings.index(heading)
        except ValueError:
            findings.append(f"Missing heading: {heading}")
            continue
        if index < last_index:
            findings.append(f"Heading out of order: {heading}")
            continue
        last_index = index
        matched += 1
    return make_result(
        name="heading_order_match",
        axis="format",
        score=matched / len(expected),
        findings=findings,
        metadata={"expected": len(expected), "matched": matched},
    )


def code_fence_balance(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """format: markdown code fences are balanced."""

    count = artifact_md.count("```")
    return make_result(
        name="code_fence_balance",
        axis="format",
        score=1.0 if count % 2 == 0 else 0.0,
        findings=[] if count % 2 == 0 else ["Unbalanced markdown code fence."],
        metadata={"fence_count": count},
    )


def mermaid_validity(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """format: Mermaid fences contain a recognized diagram directive."""

    blocks = re.findall(r"```mermaid\s*\n(.*?)```", artifact_md, flags=re.DOTALL)
    if not blocks:
        return make_result(name="mermaid_validity", axis="format", score=1.0)
    valid_prefixes = ("graph ", "flowchart ", "sequenceDiagram", "erDiagram")
    failures: list[str] = []
    for index, block in enumerate(blocks, start=1):
        first_line = next(
            (line.strip() for line in block.splitlines() if line.strip()),
            "",
        )
        if not first_line.startswith(valid_prefixes):
            failures.append(
                f"Mermaid block {index} has invalid directive: {first_line}"
            )
    return make_result(
        name="mermaid_validity",
        axis="format",
        score=(len(blocks) - len(failures)) / len(blocks),
        findings=failures,
        metadata={"mermaid_blocks": len(blocks)},
    )


def table_column_counts(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """format: markdown tables keep consistent column counts."""

    table_blocks: list[list[str]] = []
    current: list[str] = []
    for line in artifact_md.splitlines():
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current.append(line.strip())
        elif current:
            table_blocks.append(current)
            current = []
    if current:
        table_blocks.append(current)
    if not table_blocks:
        return make_result(
            name="table_column_counts",
            axis="format",
            score=0.5,
            findings=["No markdown tables found."],
        )

    failures: list[str] = []
    for index, table in enumerate(table_blocks, start=1):
        counts = [len([cell for cell in row.split("|")[1:-1]]) for row in table]
        if len(set(counts)) != 1:
            failures.append(f"Table {index} column counts differ: {counts}")
    return make_result(
        name="table_column_counts",
        axis="format",
        score=(len(table_blocks) - len(failures)) / len(table_blocks),
        findings=failures,
        metadata={"tables": len(table_blocks), "invalid": len(failures)},
    )


def id_format_consistency(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """format: requirement IDs use FR-001/NFR-001/SEC-001 style."""

    malformed = re.findall(r"\b(?:FR|NFR|SEC)-\d{1,2}\b", artifact_md)
    lowercase = re.findall(r"\b(?:fr|nfr|sec)-\d+\b", artifact_md)
    findings = [*malformed[:10], *lowercase[:10]]
    return make_result(
        name="id_format_consistency",
        axis="format",
        score=1.0 / (1 + len(malformed) + len(lowercase)),
        findings=[f"Malformed requirement ID: {item}" for item in findings],
        metadata={"malformed": len(malformed), "lowercase": len(lowercase)},
    )


def trailing_newline_policy(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """format: committed artifacts end with exactly one newline-friendly terminator."""

    return make_result(
        name="trailing_newline_policy",
        axis="format",
        score=1.0 if artifact_md.endswith("\n") else 0.0,
        findings=(
            [] if artifact_md.endswith("\n") else ["Artifact lacks trailing newline."]
        ),
    )
