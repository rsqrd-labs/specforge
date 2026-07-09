from __future__ import annotations

import re

from prompt_eval.graders.common import make_result

_REQ_RE = re.compile(r"\b(?:FR|NFR|SEC)-\d{3}(?:\.\d+)?\b")
_FR_RE = re.compile(r"\bFR-\d{3}(?:\.\d+)?\b")
_GAP_CATEGORY_RE = re.compile(
    r"TestCategoryGap:\s*category=([A-Za-z0-9_.\-]+)", re.IGNORECASE
)


def _ids(text: str, *, fr_only: bool = False) -> set[str]:
    regex = _FR_RE if fr_only else _REQ_RE
    return set(regex.findall(text or ""))


def _coverage(required: set[str], artifact_md: str) -> tuple[float, list[str]]:
    if not required:
        return 1.0, []
    present = _ids(artifact_md)
    missing = sorted(required - present)
    return (len(required) - len(missing)) / len(required), missing


def rtm_coverage_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """coverage: upstream requirement IDs remain visible downstream."""

    if stage_type == "spec":
        found = _ids(artifact_md)
        return make_result(
            name="rtm_coverage_pct",
            axis="coverage",
            score=1.0 if found else 0.0,
            findings=[] if found else ["SPEC artifact contains no FR/NFR/SEC IDs."],
            metadata={"required_ids": len(found), "missing_ids": 0},
        )

    required = _ids(deps.get("spec", ""))
    score, missing = _coverage(required, artifact_md)
    if stage_type == "plan" and "Requirement Traceability Matrix" not in artifact_md:
        missing = missing + ["## Requirement Traceability Matrix"]
        score = min(score, 0.5)
    return make_result(
        name="rtm_coverage_pct",
        axis="coverage",
        score=score,
        findings=[f"Missing traceability for {item}" for item in missing[:10]],
        metadata={"required_ids": len(required), "missing_ids": len(missing)},
    )


def fr_to_test_coverage_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """coverage: functional requirements map to named tests."""

    if stage_type != "harness":
        return make_result(name="fr_to_test_coverage_pct", axis="coverage", score=1.0)

    required = _ids(deps.get("spec", ""), fr_only=True)
    score, missing = _coverage(required, artifact_md)
    has_tests = bool(re.search(r"\btest_[A-Za-z0-9_]+", artifact_md))
    has_markers = "Tests:" in artifact_md
    if not has_tests:
        score *= 0.75
        missing.append("named test functions")
    if not has_markers:
        score *= 0.75
        missing.append("Tests: traceability comments")
    return make_result(
        name="fr_to_test_coverage_pct",
        axis="coverage",
        score=score,
        findings=[f"Missing FR-to-test coverage for {item}" for item in missing[:10]],
        metadata={
            "required_frs": len(required),
            "missing_frs": len([m for m in missing if m.startswith("FR-")]),
        },
    )


def fr_to_task_coverage_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """coverage: functional requirements map to implementation tasks."""

    if stage_type != "tasks":
        return make_result(name="fr_to_task_coverage_pct", axis="coverage", score=1.0)

    required = _ids(deps.get("spec", ""), fr_only=True)
    score, missing = _coverage(required, artifact_md)
    task_headers = re.findall(r"^###\s+T-\d{3}", artifact_md, flags=re.MULTILINE)
    if not task_headers:
        score *= 0.5
        missing.append("task headers")
    return make_result(
        name="fr_to_task_coverage_pct",
        axis="coverage",
        score=score,
        findings=[f"Missing FR-to-task coverage for {item}" for item in missing[:10]],
        metadata={"required_frs": len(required), "task_count": len(task_headers)},
    )


def plan_section_presence_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """coverage: PLAN includes Phase 19 quality-hardening sections."""

    if stage_type != "plan":
        return make_result(name="plan_section_presence_pct", axis="coverage", score=1.0)

    required_sections = [
        "## Architecture Decision Records",
        "## Architecture Anti-Patterns",
        "## Multi-tenancy Stance",
        "## Capacity Model",
        "## Threat Model",
        "## SLOs and Error Budgets",
        "## Failure Mode and Effects Analysis",
        "## Architecture Quality Attribute Matrix",
    ]
    missing = [section for section in required_sections if section not in artifact_md]
    return make_result(
        name="plan_section_presence_pct",
        axis="coverage",
        score=(len(required_sections) - len(missing)) / len(required_sections),
        findings=[f"Missing plan section: {section}" for section in missing],
        metadata={"required_sections": len(required_sections), "missing": len(missing)},
    )


def test_category_gap_acknowledged_in_tasks(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """coverage: TASKS acknowledges every harness ``TestCategoryGap`` record.

    Audit finding #8: a harness that recorded a deferred test category
    (``TestCategoryGap: category=<name> reason=... reqs=...``) had no defined
    tasks-stage behavior — the task list could silently proceed as if
    coverage were complete, breaking the "no plan artifact is orphaned"
    promise for exactly the artifacts that recorded a shortfall. Scores 1.0
    (not applicable) when the harness has no gap records; otherwise requires
    each dropped category name to appear somewhere in TASKS.md (a task or an
    Open Questions/Assumptions-style entry naming it).
    """
    if stage_type != "tasks":
        return make_result(
            name="test_category_gap_acknowledged_in_tasks", axis="coverage", score=1.0
        )

    categories = sorted(set(_GAP_CATEGORY_RE.findall(deps.get("harness", ""))))
    if not categories:
        return make_result(
            name="test_category_gap_acknowledged_in_tasks",
            axis="coverage",
            score=1.0,
            metadata={"gap_categories": 0},
        )

    lower = artifact_md.lower()
    missing = [category for category in categories if category.lower() not in lower]
    score = (len(categories) - len(missing)) / len(categories)
    return make_result(
        name="test_category_gap_acknowledged_in_tasks",
        axis="coverage",
        score=score,
        findings=[
            f"TASKS.md does not acknowledge deferred category '{category}'"
            for category in missing
        ],
        metadata={"gap_categories": len(categories), "missing": len(missing)},
    )


def harness_file_presence_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """coverage: HARNESS includes the file tree and concrete file contents."""

    if stage_type != "harness":
        return make_result(
            name="harness_file_presence_pct",
            axis="coverage",
            score=1.0,
        )

    checks = {
        "## File Tree": "## File Tree" in artifact_md,
        "## Files": "## Files" in artifact_md,
        "file headings": bool(
            re.search(r"^###\s+File:\s+\S+", artifact_md, flags=re.MULTILINE)
        ),
        "fenced code": artifact_md.count("```") >= 2,
        "named tests": bool(re.search(r"\btest_[A-Za-z0-9_]+", artifact_md)),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return make_result(
        name="harness_file_presence_pct",
        axis="coverage",
        score=sum(1 for passed in checks.values() if passed) / len(checks),
        findings=[f"HARNESS missing {item}" for item in missing],
        metadata={"checks": len(checks), "missing": len(missing)},
    )
