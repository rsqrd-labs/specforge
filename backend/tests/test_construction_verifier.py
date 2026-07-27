"""Construction verifier — the plan→tasks join and the standard-mode verdict.

Covers the checks that make "if you implement every task you get a working
thing" mechanically checkable rather than merely asserted in a prompt:

- Demo Day ``C6 plan_coverage`` / ``C7 task_inventory`` (new).
- The whole standard-mode linter (new — standard mode had no verifier at all).
- The design invariants the feature must not violate: no new blocking gate, no
  new mandatory section heading, no new critic vocabulary, no verdict flip before
  the matching prompt release, and pure (settings-free) linters.
"""

from __future__ import annotations

import re

import pytest

from services.pipeline import demo_day_plan_linter, standard_plan_linter
from services.pipeline.artifact_validator import (
    DEMO_DAY_SECTION_CONTRACTS,
    REFUNDABLE_INCOMPLETE_CODES,
    SECTION_CONTRACTS,
)

# ---------------------------------------------------------------------------
# Demo Day fixtures — a package whose plan specifies all four load-bearing
# sections and whose tasks cite each of them.
# ---------------------------------------------------------------------------

_DD_PLAN = """## Data Model and Persistence
runs(id INTEGER PRIMARY KEY, label TEXT NOT NULL). Seed: three rows loaded by
`python seed.py`.

## Environment and Bootstrap
`uv run uvicorn app:app --port 8000`. Demo surface: local, http://127.0.0.1:8000.

## External Integrations and Secrets
Anthropic Messages API, claude-haiku-4-5, credential from ANTHROPIC_API_KEY.
REAL — the demo's headline is the live summary. Timeout 8s, fallback to the
cached canned summary.

## Security Architecture
Auth stance: mocked — a hardcoded demo user; real auth is not demo-critical.

## Build Sequence
1. Walking skeleton.
2. Persistence slice.
"""

_DD_TASKS = """## Tasks

### T-001: Skeleton and persistence

**Spec refs:** FR-001
**Plan refs:** Data Model and Persistence, Environment and Bootstrap
**Harness refs:** `tests/e2e/test_smoke.py`
**Priority:** MUST
**Estimate:** M
**Estimated minutes:** 90
**Precondition:** none

**Steps**
1. Create `app.py`.

**Acceptance Criteria**
1. `pytest tests/e2e/test_smoke.py` passes.

### T-002: Summary integration and auth

**Spec refs:** FR-002
**Plan refs:** External Integrations and Secrets, Security Architecture
**Harness refs:** `tests/test_summary.py`
**Priority:** MUST
**Estimate:** M
**Estimated minutes:** 90
**Precondition:** T-001

**Steps**
1. Create `summary.py`.

**Acceptance Criteria**
1. `pytest tests/test_summary.py` passes.
"""


def _dd_blocks(tasks_md: str = _DD_TASKS):
    return demo_day_plan_linter._task_blocks(tasks_md)


def _dd_gaps(plan_md: str = _DD_PLAN, tasks_md: str = _DD_TASKS) -> list[str]:
    return demo_day_plan_linter._check_plan_coverage(plan_md, _dd_blocks(tasks_md))


# ---------------------------------------------------------------------------
# Demo Day C6 — plan_coverage.
# ---------------------------------------------------------------------------


def test_c6_passes_when_every_load_bearing_section_is_cited() -> None:
    assert _dd_gaps() == []


def test_c6_flags_a_plan_section_no_task_implements() -> None:
    """The gap this whole check exists for: the plan specifies the auth stance
    and the seed data, and the task list quietly implements neither."""
    tasks = _DD_TASKS.replace(
        "**Plan refs:** External Integrations and Secrets, Security Architecture",
        "**Plan refs:** External Integrations and Secrets",
    )
    gaps = _dd_gaps(tasks_md=tasks)
    assert len(gaps) == 1
    assert "## Security Architecture" in gaps[0]


def test_c6_skips_a_section_absent_from_the_plan() -> None:
    """An absent section is already a terminal MissingSectionError — reporting it
    here too would double-charge the user for one defect."""
    plan = _DD_PLAN.replace("## Security Architecture", "## Something Else")
    tasks = _DD_TASKS.replace(", Security Architecture", "")
    assert _dd_gaps(plan_md=plan, tasks_md=tasks) == []


def test_c6_honours_the_none_escape_for_external_integrations() -> None:
    """A build that calls nothing external needs no integration task."""
    plan = re.sub(
        r"## External Integrations and Secrets\n(?:.*\n)*?\n## Security",
        "## External Integrations and Secrets\nNone — the demo runs fully "
        "in-process.\n\n## Security",
        _DD_PLAN,
    )
    tasks = _DD_TASKS.replace("External Integrations and Secrets, ", "")
    assert "None — the demo runs" in plan
    assert _dd_gaps(plan_md=plan, tasks_md=tasks) == []


def test_c6_ignores_prose_mentions_outside_the_plan_refs_field() -> None:
    """Only the **Plan refs:** field value counts. A task that merely talks about
    the security architecture in its Steps has not implemented it."""
    tasks = _DD_TASKS.replace(
        "**Plan refs:** External Integrations and Secrets, Security Architecture",
        "**Plan refs:** External Integrations and Secrets",
    ).replace("1. Create `summary.py`.", "1. Mind the Security Architecture section.")
    gaps = _dd_gaps(tasks_md=tasks)
    assert any("## Security Architecture" in gap for gap in gaps)


def test_c6_accepts_the_abbreviated_citation_shapes_prompts_actually_produce() -> None:
    """Matching is deliberately generous: the worked example in the standard
    tasks prompt cites "Data Model §subscriptions.state", not the full heading.
    A false negative here would mark every real package red."""
    tasks = _DD_TASKS.replace(
        "**Plan refs:** Data Model and Persistence, Environment and Bootstrap",
        "**Plan refs:** `## Data Model` §runs, Bootstrap (run command)",
    )
    assert _dd_gaps(tasks_md=tasks) == []


def test_c6_is_advisory_until_enforced_and_never_flips_a_green_package() -> None:
    tasks = _DD_TASKS.replace(", Security Architecture", "")
    kwargs = dict(spec="", plan=_DD_PLAN, harness="", tasks=tasks)

    unenforced = demo_day_plan_linter.verify_construction(**kwargs)
    assert unenforced.checks["C6"].passed is False
    assert unenforced.checks["C6"].advisory is True

    enforced = demo_day_plan_linter.verify_construction(
        **kwargs, enforce_plan_coverage=True
    )
    assert enforced.checks["C6"].advisory is False
    assert enforced.verified is False


# ---------------------------------------------------------------------------
# Demo Day C7 — task_inventory (advisory only, in every outcome).
# ---------------------------------------------------------------------------


def test_c7_flags_fewer_tasks_than_build_sequence_steps_but_stays_advisory() -> None:
    one_task = _DD_TASKS.split("### T-002")[0]
    verdict = demo_day_plan_linter.verify_construction(
        spec="FR-001 FR-002 FR-003", plan=_DD_PLAN, harness="", tasks=one_task
    )
    c7 = verdict.checks["C7"]
    assert c7.passed is False
    assert c7.advisory is True
    assert any("Build Sequence" in gap for gap in c7.gaps)
    assert any("FR-NNN" in gap for gap in c7.gaps)


def test_c7_never_affects_the_verdict_even_when_failing() -> None:
    """Pinned separately from C7's own logic: a heuristic count must never be the
    reason a package is refused, or users learn to ignore the badge."""
    one_task = _DD_TASKS.split("### T-002")[0]
    checks = demo_day_plan_linter.verify_construction(
        spec="FR-001 FR-002 FR-003",
        plan=_DD_PLAN,
        harness="",
        tasks=one_task,
    ).checks
    assert checks["C7"].passed is False
    assert all(c.advisory for c in (checks["C5"], checks["C7"]))


# ---------------------------------------------------------------------------
# Standard mode fixtures — a small but internally consistent package.
# ---------------------------------------------------------------------------

_STD_SPEC = """## Functional Requirements
FR-001 create a thing. FR-002 list things.
## Non-Functional Requirements
NFR-001 respond within 200ms.
## Security, Privacy, and Abuse Expectations
SEC-001 authenticate every write.
## Acceptance Criteria
AC-001 posting a thing returns 201.
"""

_STD_PLAN = """## API Design
POST /things -> 201; GET /things -> 200.
## Data Model and Persistence
things(id uuid pk, name text not null).
## Authentication and Authorization
Bearer JWT verified in the router dependency.
## Security Architecture
Input validated at the boundary; secrets from env.
## Error Handling and Recovery
Typed errors, bounded retries.
## Observability and Audit Logging
Prometheus counters per endpoint.
## Deployment and Operations
Docker image; migrations run on boot.
"""

_STD_HARNESS = """## Requirement-to-Test Matrix
| FR-001 | creates | tests/integration/test_things.py | test_create_thing |
| FR-002 | lists | tests/integration/test_things.py | test_list_things |

### File: tests/integration/test_things.py
```python
def test_create_thing():
    assert True


def test_list_things():
    assert True
```

### File: tests/e2e/test_journey.py
```python
def test_e2e_full_journey():
    assert True
```
"""

_STD_TASKS = """## Tasks

### T-001: Data layer and API

**Phase:** Data Layer
**Spec refs:** FR-001, FR-002, NFR-001
**Plan refs:** Data Model §things, API Design
**Harness refs:** `tests/integration/test_things.py::test_create_thing`,
  `tests/integration/test_things.py::test_list_things`

**Dependencies**
none

### T-002: Auth, security, error handling

**Phase:** Security Controls
**Spec refs:** SEC-001, AC-001
**Plan refs:** Authentication and Authorization, Security Architecture, Error Handling
**Harness refs:** `test_create_thing`

**Dependencies**
T-001

### T-003: Observability, deploy, end-to-end

**Phase:** Deployment and Operations
**Spec refs:** FR-001
**Plan refs:** Observability and Audit Logging, Deployment and Operations
**Harness refs:** `tests/e2e/test_journey.py::test_e2e_full_journey`

**Dependencies**
T-002
"""


def _std(
    *, spec=_STD_SPEC, plan=_STD_PLAN, harness=_STD_HARNESS, tasks=_STD_TASKS, **kw
):
    return standard_plan_linter.verify_construction(
        spec=spec, plan=plan, harness=harness, tasks=tasks, enforced=True, **kw
    )


# ---------------------------------------------------------------------------
# Standard mode C1–C6.
# ---------------------------------------------------------------------------


def test_standard_golden_package_is_verified() -> None:
    verdict = _std()
    assert verdict.verified is True, {
        cid: c.gaps for cid, c in verdict.checks.items() if not c.passed
    }
    assert verdict.estimated_minutes is None
    assert verdict.time_budget_minutes is None


def test_standard_c1_requires_a_task_to_claim_each_requirement() -> None:
    """The gap `_traceability_issues` could never catch: an id that appears in the
    document (here, a traceability row) but that no task's Spec refs claims."""
    tasks = _STD_TASKS.replace(
        "**Spec refs:** SEC-001, AC-001", "**Spec refs:** AC-001"
    )
    tasks += "\n| SEC-001 | covered somewhere | T-002 |\n"
    verdict = _std(tasks=tasks)
    assert verdict.checks["C1"].passed is False
    assert any("SEC-001" in gap for gap in verdict.checks["C1"].gaps)
    assert verdict.verified is False


def test_standard_c2_flags_a_harness_test_no_task_builds() -> None:
    tasks = _STD_TASKS.replace(
        ",\n  `tests/integration/test_things.py::test_list_things`", ""
    )
    verdict = _std(tasks=tasks)
    assert verdict.checks["C2"].passed is False
    assert any("test_list_things" in gap for gap in verdict.checks["C2"].gaps)


def test_standard_c2_honours_the_setup_only_none_escape() -> None:
    tasks = _STD_TASKS + (
        "\n### T-004: Repo scaffold\n\n"
        "**Spec refs:** FR-001\n"
        "**Plan refs:** Deployment and Operations\n"
        "**Harness refs:** _(none — setup-only scaffold)_\n\n"
        "**Dependencies**\nT-003\n"
    )
    assert _std(tasks=tasks).checks["C2"].passed is True


def test_standard_c3_allows_forward_refs_but_flags_a_real_cycle() -> None:
    """Standard mode numbers tasks by feature area, so a forward reference is
    legitimate; only a genuine cycle is unresolvable."""
    # T-001 -> T-003, T-002 -> T-001, T-003 -> none. Forward reference, acyclic.
    forward = _STD_TASKS.replace(
        "**Dependencies**\nnone", "**Dependencies**\nT-003"
    ).replace("**Dependencies**\nT-002", "**Dependencies**\nnone")
    assert _std(tasks=forward).checks["C3"].passed is True

    # Close the loop: T-003 -> T-002 makes 1 -> 3 -> 2 -> 1.
    cycle = forward.replace("**Dependencies**\nnone\n", "**Dependencies**\nT-002\n", 1)
    result = _std(tasks=cycle).checks["C3"]
    assert result.passed is False
    assert any("circular" in gap for gap in result.gaps)


def test_standard_c4_flags_a_product_nothing_deploys() -> None:
    """The finding this closes: the tasks prompt lists Deployment and Operations
    as a phase that "typically" appears, and no gate ever checked for it."""
    tasks = _STD_TASKS.replace(
        "**Plan refs:** Observability and Audit Logging, Deployment and Operations",
        "**Plan refs:** Observability and Audit Logging",
    )
    verdict = _std(tasks=tasks)
    assert verdict.checks["C4"].passed is False
    assert any(
        "## Deployment and Operations" in gap for gap in verdict.checks["C4"].gaps
    )


def test_standard_c5_requires_a_task_to_cite_an_end_to_end_test() -> None:
    tasks = _STD_TASKS.replace(
        "`tests/e2e/test_journey.py::test_e2e_full_journey`", "`test_create_thing`"
    )
    verdict = _std(tasks=tasks)
    assert verdict.checks["C5"].passed is False
    assert any("end-to-end" in gap for gap in verdict.checks["C5"].gaps)


def test_standard_c5_blames_the_harness_when_it_declares_no_e2e() -> None:
    harness = _STD_HARNESS.replace("tests/e2e/test_journey.py", "tests/unit/test_x.py")
    harness = harness.replace("test_e2e_full_journey", "test_plain_unit")
    gaps = _std(harness=harness).checks["C5"].gaps
    assert any("HARNESS declares no end-to-end test" in gap for gap in gaps)


def test_standard_c6_task_inventory_is_advisory() -> None:
    """The golden package itself trips C6 — 3 task blocks for 4 distinct
    FR/NFR/SEC ids — and is still verified. That is the point: a heuristic count
    reports, it never refuses."""
    verdict = _std()
    assert verdict.checks["C6"].passed is False
    assert verdict.checks["C6"].advisory is True
    assert verdict.verified is True


# ---------------------------------------------------------------------------
# Design invariants (the "don't break the pipeline" contract).
# ---------------------------------------------------------------------------


def test_invariant_no_new_blocking_gate() -> None:
    """Everything added here is advisory. A completeness code becomes blocking
    only by joining this frozenset, and nothing did."""
    assert REFUNDABLE_INCOMPLETE_CODES == frozenset(
        {"empty_artifact", "provider_stopped_by_limit"}
    )


def test_invariant_no_new_mandatory_section_heading() -> None:
    """A new required heading is a new terminal MissingSectionError surface. The
    verifier rides sections and task fields that already exist, so both contracts
    are untouched."""
    assert len(SECTION_CONTRACTS["tasks"]) == 5
    assert DEMO_DAY_SECTION_CONTRACTS["tasks"] == [
        "## Effort Summary",
        "## Build Order",
        "## Traceability Overview",
        "## Tasks",
    ]
    # Every plan section the coverage checks join on is a REAL contract heading —
    # a typo here would make the check silently vacuous rather than loud.
    assert set(demo_day_plan_linter._DEMO_DAY_PLAN_COVERAGE) <= set(
        DEMO_DAY_SECTION_CONTRACTS["plan"]
    )
    assert set(standard_plan_linter._STANDARD_PLAN_COVERAGE) <= set(
        SECTION_CONTRACTS["plan"]
    )


def test_invariant_critic_gains_no_new_finding_vocabulary() -> None:
    """The judge's kind enum is closed; instructing it to emit an unlisted kind
    would produce schema-invalid findings."""
    from services.pipeline import critic

    allowed = set(re.findall(r'^- "(\w+)":', critic._CRITIC_SYSTEM_PROMPT, re.M))
    assert allowed == {
        "CoverageGap",
        "MissingSection",
        "ShallowSection",
        "BannedPhrase",
        "DeprecatedAPI",
        "ADRIncomplete",
        "ImplementationLeak",
        "DependencyCycle",
    }
    for stage in ("spec", "plan", "harness", "tasks"):
        for focus in (
            critic._per_stage_focus(stage),
            critic._demo_day_per_stage_focus(stage),
        ):
            for kind in re.findall(r"\b(?:flag )([A-Z]\w+)", focus):
                assert kind in allowed, f"{stage} focus names unknown kind {kind!r}"


@pytest.mark.parametrize("module", [demo_day_plan_linter, standard_plan_linter])
def test_invariant_linters_stay_pure(module) -> None:
    """No settings/ORM import: the linters run on the CPU-offload pool and must
    stay trivially unit-testable. Enforcement flags arrive as parameters."""
    source = open(module.__file__).read()
    assert "from config import" not in source
    assert "import config" not in source
    assert "from models import" not in source


def test_invariant_unenforced_flags_never_withhold_the_guarantee() -> None:
    """Release-A behaviour: every check computes and reports its gaps, but a
    package that would fail cannot flip to red before the prompts that satisfy
    the checks have landed."""
    broken = standard_plan_linter.verify_construction(
        spec="", plan="", harness="", tasks="", enforced=False
    )
    assert broken.verified is True
    assert any(not c.passed for c in broken.checks.values())

    dd = demo_day_plan_linter.verify_construction(
        spec="", plan=_DD_PLAN, harness="", tasks="### T-001: x\n"
    )
    assert dd.checks["C6"].passed is False
    assert dd.checks["C6"].advisory is True


@pytest.mark.parametrize(
    "verify",
    [
        lambda **kw: demo_day_plan_linter.verify_construction(**kw),
        lambda **kw: standard_plan_linter.verify_construction(**kw),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        "",
        "   \n\n",
        "## Tasks\n### T-001:\n**Plan refs:**\n",
        "```\nunbalanced fence\n",
        "### T-999:   unicode — em dash – en dash\n**Plan refs:** —\n",
    ],
)
def test_invariant_checks_never_raise_on_malformed_input(verify, payload) -> None:
    """The verifier runs detached after the artifact is delivered and charged, and
    again on the export path. A raise there is swallowed by the caller, but it
    would silently cost the user their verdict — so the checks must degrade to
    gaps, never to exceptions."""
    verdict = verify(spec=payload, plan=payload, harness=payload, tasks=payload)
    assert isinstance(verdict.to_dict(), dict)


def test_unenforced_report_never_claims_a_guarantee_it_has_not_earned() -> None:
    """The report must not print "✅ Construction-verified" over a list of FAILs.

    While a check is live but un-enforced, `verified` stays true by design — the
    badge has to describe what the checks FOUND, not what the flag permits, or the
    report overclaims exactly the thing it exists to certify.
    """
    from services.pipeline import agent_manual_service

    verdict = standard_plan_linter.verify_construction(
        spec="FR-001",
        plan="## Deployment and Operations\ndocker image\n",
        harness="",
        tasks="### T-001: x\n\n**Spec refs:** FR-001\n",
        enforced=False,
    )
    payload = verdict.to_dict()
    assert payload["verified"] is True
    report = agent_manual_service.build_construction_report(payload)
    assert "Construction-verified" not in report
    assert "not yet enforced" in report
    assert "## Deployment and Operations" in report

    # A genuinely clean package still gets the plain green badge.
    clean = standard_plan_linter.verify_construction(
        spec=_STD_SPEC, plan=_STD_PLAN, harness=_STD_HARNESS, tasks=_STD_TASKS
    )
    assert "✅ Construction-verified" in agent_manual_service.build_construction_report(
        clean.to_dict()
    )


def test_legacy_verdicts_without_advisory_still_render_the_green_badge() -> None:
    """Verdicts persisted before checks self-described carry no `advisory` key and
    pre-date the un-enforced rollout, so a missing flag must read as
    verdict-bearing rather than silently downgrading an old green package."""
    from services.pipeline import agent_manual_service

    legacy = {
        "verified": True,
        "checks": {"C1": {"name": "dag_acyclic", "passed": True, "gaps": []}},
        "estimated_minutes": 240,
        "time_budget_minutes": 300,
        "stage_versions": {},
    }
    assert "✅ Construction-verified" in agent_manual_service.build_construction_report(
        legacy
    )
