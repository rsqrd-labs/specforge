"""Standard/Demo-Day parity for the generation budget, the gates, and the judge.

Four defects this pins, all found by auditing the four stages across both modes:

1. The harness ``## Files`` chunk was budgeted by a literal chunk KEY
   (``"harness-files"``), which Demo Day's spec does not use — so the chunk that
   must emit every runnable test file ran on half the output budget and the
   *contract* chunk's length target. A generation-side cause of dropped files.
2. Demo Day ran NO file-emission check: ``_harness_issues`` (and its
   tree/matrix/block triad) is standard-only, and the construction verifier
   accepts a File-Tree entry as proof a file exists. The guarantee-bearing mode
   was the *less* verified one.
3. The eval judge was mode-blind, so Demo Day specs were scored on
   ``user_flow_coverage`` — a dimension their contract has no section for.
4. ``coverage_percent`` came from a judge that sees ~20K chars of a 60-120KB
   harness — the same truncation defect that already disqualified the judge's
   ``uncovered_reqs`` — yet it was the headline coverage figure and carried 0.20
   of the harness score.

The false-alarm tests matter as much as the detection ones: a gate that cries
wolf on a correct artifact is worse than no gate.
"""

from __future__ import annotations

import re

import pytest

from config import settings
from services.evals import online_eval as oe
from services.pipeline import artifact_validator as av
from services.pipeline import stage_manager as sm

PAD = "Substantive prose padding that clears the demo day depth floor comfortably. " * 3

# A nested tree with box-drawing glyphs and bare leaf names — the shape a model
# actually emits, and the one whose prose length is far below the depth floor.
_NESTED_TREE = (
    "tests/\n"
    "├── test_login.py\n"
    "├── test_pay.py\n"
    "└── e2e/\n"
    "    └── test_smoke.py"
)


def _char_figures(target: str) -> list[int]:
    """Every "N,NNN characters"-style figure in a length target, ascending."""
    return sorted(int(m.replace(",", "")) for m in re.findall(r"\d[\d,]{3,}", target))


# The two standard-mode chunks that were shrunk to fit their wave's sequential
# neighbour inside the shared 270s run budget (see _chunk_length_target's
# docstring). Demo Day never reaches either key — its spec/tasks stay
# single-chunk — so this set is standard-mode-only by construction.
_WAVE_BUDGET_CONSTRAINED_CHUNK_KEYS = {"validation-risk", "task-overview"}


def _harness(files_section: str, *, tree: str, matrix: str) -> str:
    return f"""## Harness Overview
{PAD}

## Frozen Interface Contracts
{PAD}

## Requirement-to-Test Matrix
{matrix}

## End-to-End Smoke Test
The guarantee-bearing e2e is `tests/e2e/test_smoke.py`, driving the demo journey
end to end and asserting at each step. {PAD}

## File Tree
```
{tree}
```

## Files
{files_section}
"""


# ---------------------------------------------------------------------------
# 1. Generation budget parity — the content-quality root cause.
# ---------------------------------------------------------------------------


def test_demo_day_files_chunk_gets_the_same_budget_as_standard():
    """The Files chunk is identified structurally, not by its mode-specific key.

    Demo Day names it ``demo-harness-files``; standard names it
    ``harness-files``. Keying the budget on the literal standard key handed Demo
    Day's Files chunk 24,576 tokens instead of 49,152 — half the room for the one
    chunk that must carry every runnable test file — and told it to stay inside
    the *contract* chunk's "6,000-45,000 characters" target.
    """
    std_files = next(
        c
        for c in sm._chunk_specs_for_stage("harness", "standard")
        if c.required_heading == "## Files"
    )
    demo_files = next(
        c
        for c in sm._chunk_specs_for_stage("harness", "demo_day")
        if c.required_heading == "## Files"
    )
    assert std_files.key != demo_files.key, "keys differ; that was the trap"

    assert sm._is_harness_files_chunk("harness", std_files)
    assert sm._is_harness_files_chunk("harness", demo_files)

    # Same length target for both, and it is the every-file one.
    assert sm._chunk_length_target("harness", demo_files) == sm._chunk_length_target(
        "harness", std_files
    )
    assert "Emit EVERY file named in the File Tree" in sm._chunk_length_target(
        "harness", demo_files
    )

    # And the contract chunks keep the smaller target in both modes.
    demo_contract = next(
        c
        for c in sm._chunk_specs_for_stage("harness", "demo_day")
        if c.required_heading != "## Files"
    )
    assert "contract chunk" in sm._chunk_length_target("harness", demo_contract)


def test_non_harness_chunks_are_never_treated_as_the_files_chunk():
    spec_chunks = sm._chunk_specs_for_stage("spec", "standard")
    assert all(not sm._is_harness_files_chunk("spec", c) for c in spec_chunks)


# ---------------------------------------------------------------------------
# 2. Demo Day file-emission gate — detection AND false-alarm safety.
# ---------------------------------------------------------------------------


def test_demo_day_flags_promised_harness_files_that_were_never_emitted():
    harness = _harness(
        "_(none emitted — the Files chunk fell over)_",
        tree="tests/test_login.py\ntests/test_pay.py",
        matrix=(
            "| Req | Test |\n| --- | --- |\n"
            "| AC-001 | `tests/test_login.py::test_login` |\n"
            "| AC-002 | `tests/test_pay.py` |\n"
        ),
    )
    with pytest.raises(av.IncompleteArtifactError) as exc:
        av.validate_artifact_completeness("harness", harness, {}, "demo_day")
    codes = {i.code for i in exc.value.issues}
    assert "harness_file_tree_missing_block" in codes

    issue = next(
        i for i in exc.value.issues if i.code == "harness_file_tree_missing_block"
    )
    # Non-refundable: delivered, finalisable, no refund, no regenerate cascade.
    assert not issue.is_refundable
    assert "test_login.py" in issue.detail and "test_pay.py" in issue.detail


def test_demo_day_file_check_tolerates_path_spelling_differences():
    """No false gaps from ``harness/`` prefixes, casing, ``./`` or bare leaves.

    This is the whole reason the check reuses ``missing_harness_files`` rather
    than comparing raw strings: the File Tree, the matrix and the ``### File:``
    headings routinely spell the same file three different ways.
    """
    harness = _harness(
        """
### File: harness/tests/test_login.py
```python
# Tests: AC-001
def test_login():
    assert True
```

### File: TESTS/Test_Pay.py
```python
# Tests: AC-002
def test_pay():
    assert True
```

### File: tests/e2e/test_smoke.py
```python
# Tests: AC-003
def test_smoke():
    assert True
```
""",
        tree=_NESTED_TREE,
        matrix=(
            "| Req | Test |\n| --- | --- |\n"
            "| AC-001 | `tests/test_login.py::test_login` |\n"
            "| AC-002 | `./tests/test_pay.py` |\n"
            "| AC-003 | `test_smoke.py` |\n"
        ),
    )
    assert av.missing_harness_files(harness)[0] == []
    # No completeness issue at all for a complete Demo Day harness.
    av.validate_artifact_completeness("harness", harness, {}, "demo_day")


def test_a_bodyless_file_heading_is_never_counted_as_emitted_in_either_mode():
    """A ``### File:`` heading with NO code under it is a gap, not a file.

    "Emitted" used to mean the heading matched ``_FILE_HEADING_RE`` — headings
    only — so a harness that listed every promised test file as a bare heading
    with zero code passed every gate and reported 100% coverage. The block-aware
    check existed but lived in ``_harness_issues``, i.e. the ``else`` branch of
    ``validate_artifact_completeness``, so Demo Day — the guarantee-bearing mode
    — ran no file-body check at all. Both modes now read one body-aware index.
    """
    harness = _harness(
        """
### File: tests/test_login.py

### File: tests/test_pay.py
""",
        tree="tests/test_login.py\ntests/test_pay.py",
        matrix=(
            "| Req | Test |\n| --- | --- |\n"
            "| FR-001 | `tests/test_login.py` |\n"
            "| FR-002 | `tests/test_pay.py` |\n"
        ),
    )
    # The headings exist, so a heading-only index reported "nothing missing".
    assert av.missing_harness_files(harness)[0] == [
        "tests/test_login.py",
        "tests/test_pay.py",
    ]
    ids = av.upstream_requirement_ids("FR-001 a. FR-002 b.")
    assert av.harness_coverage_ratio(harness, upstream_ids=ids) == (0, 2)

    for mode in ("standard", "demo_day"):
        with pytest.raises(av.IncompleteArtifactError) as exc:
            av.validate_artifact_completeness("harness", harness, {}, mode)
        codes = {i.code for i in exc.value.issues}
        assert "harness_file_tree_missing_block" in codes, mode


def test_standard_mode_names_every_bodyless_file_individually():
    """Standard mode keeps its per-file ``incomplete_harness_file_block``, and it
    is computed from the shared index rather than a second fence regex — so a
    file with a line of prose between its heading and its fence is no longer
    reported as having no block at all."""
    harness = _harness(
        """
### File: tests/test_login.py

This file verifies the login flow.

```python
def test_login():
    assert True
```

### File: tests/test_pay.py
""",
        tree="tests/test_login.py\ntests/test_pay.py",
        matrix=(
            "| Req | Test |\n| --- | --- |\n"
            "| FR-001 | `tests/test_login.py` |\n"
            "| FR-002 | `tests/test_pay.py` |\n"
        ),
    )
    with pytest.raises(av.IncompleteArtifactError) as exc:
        av.validate_artifact_completeness("harness", harness, {}, "standard")
    bodyless = [
        i.reference
        for i in exc.value.issues
        if i.code == "incomplete_harness_file_block"
    ]
    assert bodyless == ["tests/test_pay.py"]


def test_a_tilde_fenced_file_is_emitted():
    """CommonMark allows ``~~~`` fences. Reading one as bodyless would
    manufacture a coverage gap on a correct harness."""
    harness = _harness(
        """
### File: tests/test_login.py
~~~python
def test_login():
    assert True
~~~
""",
        tree="tests/test_login.py",
        matrix="| Req | Test |\n| --- | --- |\n| FR-001 | `tests/test_login.py` |\n",
    )
    assert av.missing_harness_files(harness)[0] == []
    assert av.harness_coverage_ratio(
        harness, upstream_ids=av.upstream_requirement_ids("FR-001 a.")
    ) == (1, 1)


def test_standard_mode_harness_checks_are_unchanged():
    """The standard triad still fires; this fix added to Demo Day only."""
    harness = _harness(
        "_(none)_",
        tree="tests/test_login.py",
        matrix="| Req | Test |\n| --- | --- |\n| FR-001 | `tests/test_login.py` |\n",
    )
    with pytest.raises(av.IncompleteArtifactError) as exc:
        av.validate_artifact_completeness("harness", harness, {}, "standard")
    codes = {i.code for i in exc.value.issues}
    assert {"harness_file_tree_missing_block", "harness_matrix_missing_file"} <= codes


# ---------------------------------------------------------------------------
# 3. Manifest sections are graded by paths, not prose length.
# ---------------------------------------------------------------------------


def test_complete_file_tree_is_never_reported_as_shallow():
    """A correct 3-file tree normalises to ~71 chars against a 90-char floor.

    Every lean Demo Day harness was therefore told its File Tree "does not
    contain substantive content" while listing exactly the files it was asked
    for — a guaranteed false advisory on the smallest, most correct packages.
    """
    tree_body = _NESTED_TREE
    assert len(av._normalise_body_for_depth(tree_body)) < av._min_body_chars(
        "harness", "demo_day"
    ), "fixture must be shorter than the prose floor or this test proves nothing"
    assert (
        av._structural_section_issue("## File Tree", tree_body, "harness", "demo_day")
        is None
    )


def test_empty_file_tree_still_reported():
    issue = av._structural_section_issue(
        "## File Tree", "To be determined.", "harness", "demo_day"
    )
    assert issue is not None
    assert issue.code == "shallow_required_section"


_CANONICAL_SIZING_LEGEND = (
    "| Size | Effort |\n"
    "|------|--------|\n"
    "| S | < 2h |\n"
    "| M | 2-6h |\n"
    "| L | 6-16h |"
)


def test_canonical_task_sizing_legend_is_never_reported_as_shallow():
    """A 3-row size lookup normalises to 33 chars against a 50-char floor.

    Same defect class as the File Tree above: a fixed-format lookup table graded
    as prose. Adding a "Meaning" column pushes it to 124 normalised chars, so the
    advisory fired on the TIGHTER, more correct artifact.
    """
    assert len(
        av._normalise_body_for_depth(_CANONICAL_SIZING_LEGEND)
    ) < av._min_body_chars(
        "tasks", "standard"
    ), "fixture must be shorter than the prose floor or this test proves nothing"
    assert (
        av._structural_section_issue(
            "## Task Sizing Legend", _CANONICAL_SIZING_LEGEND, "tasks", "standard"
        )
        is None
    )


def test_a_bullet_rendered_sizing_legend_also_passes():
    """The legend is equally correct as a list; the grader measures rows, not
    the delimiter used to draw them."""
    body = "- S: under 2 hours\n- M: 2-6 hours\n- L: 6-16 hours"
    assert (
        av._structural_section_issue("## Task Sizing Legend", body, "tasks", "standard")
        is None
    )


def test_a_one_row_sizing_legend_is_still_reported():
    """The grader must not become an escape hatch: too few rows AND too little
    prose is still a shallow section."""
    issue = av._structural_section_issue(
        "## Task Sizing Legend",
        "| Size | Effort |\n|---|---|\n| S | 2h |",
        "tasks",
        "standard",
    )
    assert issue is not None and issue.code == "shallow_required_section"


def test_small_dependency_graph_is_never_reported_as_shallow():
    body = "```mermaid\ngraph TD\n  T-001 --> T-002\n  T-002 --> T-003\n```"
    assert (
        av._structural_section_issue("## Dependency Graph", body, "tasks", "standard")
        is None
    )


def test_dependency_graph_with_no_tasks_falls_back_to_the_prose_floor():
    issue = av._structural_section_issue(
        "## Dependency Graph", "```mermaid\ngraph TD\n```", "tasks", "standard"
    )
    assert issue is not None and issue.code == "shallow_required_section"


# ---------------------------------------------------------------------------
# 3b. The gates read the bytes we actually ship (deterministic rewrites first).
# ---------------------------------------------------------------------------


def _tasks_with_forecast_summary(claimed: int, blocks: int) -> str:
    body = (
        "## Effort Summary\n"
        f"Tasks: {claimed} total - {claimed} MUST - 0 SHOULD - 0 COULD\n"
        "Sizes: 1xS - 0xM - 0xL\n"
    )
    for n in range(1, blocks + 1):
        body += (
            f"\n### T-{n:03d}: Do thing {n}\n\n"
            "**Spec refs:** FR-001\n\n**Priority:** MUST\n\n**Estimate:** S\n"
        )
    return body


def test_advisories_describe_the_post_rewrite_artifact():
    """The deterministic self-heals must run BEFORE the completeness pass.

    The TASKS Effort Summary is written by the overview chunk before any task
    block exists, so its counts are a forecast that ``reconcile_effort_summary``
    corrects at assembly. Grading the artifact first meant the pipeline silently
    fixed the mismatch and then still attached an
    ``effort_summary_task_count_mismatch`` advisory about it — an advisory
    describing bytes the user never receives.
    """
    raw = _tasks_with_forecast_summary(claimed=12, blocks=7)

    with pytest.raises(av.IncompleteArtifactError) as exc:
        av.validate_artifact_completeness("tasks", raw, {})
    assert "effort_summary_task_count_mismatch" in {i.code for i in exc.value.issues}

    rewritten, counts = sm.apply_deterministic_rewrites("tasks", raw, "standard")
    assert counts.effort_reconciled is True
    try:
        av.validate_artifact_completeness("tasks", rewritten, {})
    except av.IncompleteArtifactError as exc:
        assert "effort_summary_task_count_mismatch" not in {i.code for i in exc.issues}


def test_deterministic_rewrites_are_idempotent():
    """A second application must be a no-op, so a caller that has not been
    migrated can never double-count the dedup metrics."""
    harness = _harness(
        """
### File: tests/test_login.py
```python
def test_login():
    assert True
```

### File: tests/test_login.py
```python
def test_login():
    assert True
```
""",
        tree="tests/test_login.py",
        matrix="| Req | Test |\n| --- | --- |\n| FR-001 | `tests/test_login.py` |\n",
    )
    once, first = sm.apply_deterministic_rewrites("harness", harness, "standard")
    assert first.file_blocks_removed == 1
    twice, second = sm.apply_deterministic_rewrites("harness", once, "standard")
    assert twice == once
    assert second.file_blocks_removed == 0
    assert second.sections_removed == 0


# ---------------------------------------------------------------------------
# 4. Mode-aware eval judge.
# ---------------------------------------------------------------------------


def test_demo_day_spec_is_not_scored_on_sections_its_contract_forbids():
    """``user_flow_coverage`` is not asked for or weighted in Demo Day.

    ``DEMO_DAY_SECTION_CONTRACTS["spec"]`` has no User Flows section (standard's
    merged User Journeys/User Flow Diagrams) — Demo Day specifies exactly ONE
    happy path (Success Demo) —
    so a 0.15-weighted user-flow-coverage score docked every Demo Day spec for
    obeying its own contract.
    """
    demo_dims = oe._stage_score_dimensions("spec", "demo_day")
    std_dims = oe._stage_score_dimensions("spec", "standard")
    assert "user_flow_coverage" in std_dims
    assert "user_flow_coverage" not in demo_dims
    assert "user_flow_coverage" not in oe.score_weights_for("spec", "demo_day")

    # non_functional_coverage is deliberately KEPT — re-pointed at the AI Usage /
    # Security Posture / Scalability Story rubric sections by the Demo Day prompt.
    assert "non_functional_coverage" in demo_dims
    assert "Security Posture" in oe._stage_prompt_template("spec", "demo_day")

    assert sum(oe.score_weights_for("spec", "demo_day").values()) == pytest.approx(1.0)


@pytest.mark.parametrize("stage", ["spec", "plan", "harness", "tasks"])
def test_standard_mode_scoring_is_byte_identical(stage):
    """Regression pin: this change must not move a single standard-mode score."""
    assert oe.score_weights_for(stage, "standard") == oe._SCORE_WEIGHTS[stage]
    assert oe._stage_prompt_template(stage, "standard") == oe._STAGE_PROMPTS[stage]


@pytest.mark.parametrize("stage", ["plan", "harness", "tasks"])
def test_demo_day_reuses_standard_weights_where_dimensions_apply(stage):
    """Only the SPEC weights differ; the rest fall through unchanged."""
    assert oe.score_weights_for(stage, "demo_day") == oe._SCORE_WEIGHTS[stage]


@pytest.mark.parametrize("stage", ["spec", "plan", "harness", "tasks"])
def test_demo_day_prompts_tell_the_judge_it_is_grading_demo_day(stage):
    assert "DEMO DAY" in oe._stage_prompt_template(stage, "demo_day")


def test_demo_day_rubric_only_requests_dimensions_it_scores():
    """A dimension the judge is asked for but never weighted is wasted tokens —
    and worse, invites a low score for a by-design absence."""
    rubric = oe._rubric_for_stage("spec", "demo_day")
    assert '"user_flow_coverage"' not in rubric
    assert '"non_functional_coverage"' in rubric


def test_batch_eval_carries_mode_to_the_completion_side():
    """The batch prompt is baked at enqueue, but the WEIGHTS are re-derived on
    completion — so the mode has to survive the checkpoint round-trip."""
    _, demo_prompt, _ = oe.build_eval_request("spec", "x" * 600, "", None, "demo_day")
    _, std_prompt, _ = oe.build_eval_request("spec", "x" * 600, "", None, "standard")
    assert "DEMO DAY" in demo_prompt
    assert "DEMO DAY" not in std_prompt


# ---------------------------------------------------------------------------
# 5. Deterministic coverage replaces the truncation-poisoned judge estimate.
# ---------------------------------------------------------------------------


def _coverage_harness(*, emit_pay: bool) -> str:
    pay_block = (
        """
### File: tests/test_pay.py
```python
def test_pay():
    assert True
```
"""
        if emit_pay
        else ""
    )
    return _harness(
        """
### File: tests/test_login.py
```python
def test_login():
    assert True
```
""" + pay_block,
        tree="tests/test_login.py",
        matrix=(
            "| Req | Test |\n| --- | --- |\n"
            "| FR-001 | `tests/test_login.py` |\n"
            "| FR-002 | `tests/test_pay.py` |\n"
        ),
    )


# The upstream SPEC is the coverage DENOMINATOR: a requirement the harness's
# matrix never mentioned is a gap, not an absence of evidence. Two requirements
# here, matching the two matrix rows, so the parity assertions below stay exact.
_COVERAGE_SPEC = "FR-001 login must work. FR-002 payment must work."


def test_coverage_is_computed_from_the_artifact_not_the_judge():
    ids = av.upstream_requirement_ids(_COVERAGE_SPEC)
    assert av.harness_coverage_ratio(
        _coverage_harness(emit_pay=True), upstream_ids=ids
    ) == (2, 2)
    assert av.harness_coverage_ratio(
        _coverage_harness(emit_pay=False), upstream_ids=ids
    ) == (1, 2)
    assert (
        oe._deterministic_coverage_percent(
            _coverage_harness(emit_pay=False), _COVERAGE_SPEC
        )
        == 50
    )
    assert (
        oe._deterministic_coverage_percent(
            _coverage_harness(emit_pay=True), _COVERAGE_SPEC
        )
        == 100
    )


def test_coverage_denominator_is_the_spec_not_the_surviving_matrix_rows():
    """A budget-truncated matrix must not read as 100%.

    The contract chunk drops rows when it runs out of output budget; with a
    matrix-derived denominator the numerator and denominator shrank together, so
    a harness covering 1 of 3 spec requirements reported FULL coverage with an
    empty gap list and a paid patch that had nothing to patch.
    """
    spec = "FR-001 a. FR-002 b. NFR-001 c."
    harness = _harness(
        """
### File: tests/test_login.py
```python
def test_login():
    assert True
```
""",
        tree="tests/test_login.py",
        matrix="| Req | Test |\n| --- | --- |\n| FR-001 | `tests/test_login.py` |\n",
    )
    ids = av.upstream_requirement_ids(spec)
    assert av.harness_coverage_ratio(harness, upstream_ids=ids) == (1, 3)
    assert av.uncovered_requirements(harness, upstream_ids=ids) == ["FR-002", "NFR-001"]


def test_a_tagged_patch_file_counts_even_without_a_matrix_row():
    """The paid gap patch writes `# Tests: <id>`-tagged FILES and no matrix row.

    A matrix-only coverage computation could never register the coverage the user
    just paid for, so the chip would sit unchanged after a successful patch.
    """
    spec = "FR-001 a. FR-002 b."
    harness = _harness(
        """
### File: tests/test_login.py
```python
def test_login():
    assert True
```

### File: tests/test_pay_patch.py
```python
# Tests: FR-002
def test_pay():
    assert True
```
""",
        tree="tests/test_login.py",
        matrix="| Req | Test |\n| --- | --- |\n| FR-001 | `tests/test_login.py` |\n",
    )
    ids = av.upstream_requirement_ids(spec)
    assert av.harness_coverage_ratio(harness, upstream_ids=ids) == (2, 2)
    assert av.uncovered_requirements(harness, upstream_ids=ids) == []


def test_a_prose_tests_line_cannot_claim_coverage():
    """The `# Tests:` tag path is the one route that can INFLATE coverage.

    It scans a file's whole `### File:` block — prose between the heading and
    the fence included — so a bare narrative line must not credit requirements
    that no code exists for. The comment marker is required.
    """
    spec = "FR-001 a. FR-002 b. FR-003 c."
    harness = _harness(
        """
### File: tests/test_login.py

Tests: FR-002, FR-003

```python
# Tests: FR-001
def test_login():
    assert True
```
""",
        tree="tests/test_login.py",
        matrix="| Req | Test |\n| --- | --- |\n| FR-001 | `tests/test_login.py` |\n",
    )
    ids = av.upstream_requirement_ids(spec)
    assert av.harness_coverage_ratio(harness, upstream_ids=ids) == (1, 3)
    assert av.uncovered_requirements(harness, upstream_ids=ids) == ["FR-002", "FR-003"]


def test_a_paid_patch_is_batched_to_what_one_call_can_write():
    """A patch is ONE provider call under the same 240s watchdog cap as a
    generation chunk, so the requirement list handed to it is bounded — the same
    "unbounded promise" defect the harness Files chunk had. The endpoint is
    repeatable, so the remainder is patched in the next batch rather than
    charged for and half-written."""
    assert sm._MAX_PATCH_REQUIREMENTS_PER_CALL <= sm._MAX_HARNESS_FILES


def test_coverage_and_the_gap_list_can_never_disagree():
    """The chip, the CoveragePanel and the paid patch are three views of one
    computation — a 100% chip beside a populated gap list is now impossible."""
    partial = _coverage_harness(emit_pay=False)
    ids = av.upstream_requirement_ids(_COVERAGE_SPEC)
    covered, total = av.harness_coverage_ratio(partial, upstream_ids=ids)
    assert total - covered == len(av.uncovered_requirements(partial, upstream_ids=ids))


def test_no_spec_requirements_reads_as_unknown_not_zero_percent():
    """No upstream requirement set means NO chip, not 0% coverage — the
    difference between "no data" and a false alarm.

    There is deliberately no fallback to identifiers scraped from the harness
    itself: a budget-truncated harness drops those requirements from its whole
    body, not just from its matrix, so such a fallback would reproduce the exact
    100%-on-a-half-emitted-harness lie this denominator exists to kill.
    """
    assert oe._deterministic_coverage_percent("## Harness Overview\nnothing") is None
    assert oe._deterministic_coverage_percent(_coverage_harness(emit_pay=False)) is None
    assert av.harness_coverage_ratio("") == (0, 0)


def test_judge_coverage_never_reaches_the_stored_value_or_the_score():
    """The judge can claim 100% on a half-emitted harness; it must be ignored."""
    data = {
        "scores": {
            "requirements_coverage": 90,
            "specificity_testability": 90,
            "traceability": 90,
            "clarity": 90,
        },
        "coverage_percent": 100,
    }
    normalised = oe._normalise_eval_payload(
        "harness",
        data,
        "standard",
        coverage_override=oe._deterministic_coverage_percent(
            _coverage_harness(emit_pay=False), _COVERAGE_SPEC
        ),
        use_coverage_override=True,
    )
    assert normalised["coverage_percent"] == 50

    # And with no coverage data at all the key is dropped, not defaulted to the
    # judge's number: _weighted_score renormalises over the remaining weights.
    dropped = oe._normalise_eval_payload(
        "harness", data, "standard", coverage_override=None, use_coverage_override=True
    )
    assert dropped["coverage_percent"] is None
    assert dropped["overall_score"] == 90


def test_non_harness_stages_keep_the_judge_coverage_field():
    """Only the harness has a matrix to derive coverage from; nothing else
    changes behaviour."""
    data = {"scores": {"clarity": 80}, "coverage_percent": 42}
    normalised = oe._normalise_eval_payload("spec", data, "standard")
    assert normalised["coverage_percent"] == 42


# ---------------------------------------------------------------------------
# 5. The single-call length target (every non-harness chunk)
#
# A chunk is exactly one provider stream, killed at the
# stage_provider_call_timeout_seconds hard cap (240s — the most the 300s
# deadline minus the 30s finalise reserve can grant) with
# its partial text discarded. The old 80,000-character "document chunk" target
# was justified as a SLICE target — standard spec/plan/tasks are 3-4 chunks, so
# no single call was expected to fill it — but the string is appended to the
# prompt of the call actually being made and advertises 80,000 characters for
# THAT call, i.e. ~20K output tokens, past the ~15-18K dense-chunk band that
# fits at effort=medium. Timing out is strictly worse than finishing short: the
# retry lands on the mid tier with less time left than the first attempt had.
# Both shapes therefore carry the same 24,000-character ceiling (25% margin
# under the 240s provider-call cap, down from the ~6%-margin 30,000 figure);
# the whole artifact's length comes from the chunk split, not from a per-call
# ceiling no single call can reach inside the bound.
# ---------------------------------------------------------------------------


def test_whole_document_chunks_get_a_single_call_length_target():
    """Every Demo Day whole-document chunk is sized for one 240s call."""
    for stage in ("spec", "plan", "tasks"):
        chunks = sm._chunk_specs_for_stage(stage, "demo_day")
        assert len(chunks) == 1, f"{stage} is expected to stay single-pass"
        chunk = chunks[0]
        assert chunk.whole_document is True
        target = sm._chunk_length_target(stage, chunk)
        assert "24,000" in target
        # The whole-document FLOOR is 6,000, not the 3,500 of a slice: a Demo
        # Day plan is 13 required sections in ONE chunk against a 180-char depth
        # floor, needing ~4,715 raw chars — a ~0.3% margin against 3,500, so a
        # model obeying its own lower bound tripped shallow_required_section.
        # test_chunk_floors_clear_the_depth_floors pins the relation.
        assert "6,000" in target


def test_standard_document_chunks_fit_one_provider_call():
    """A standard slice is ALSO exactly one 240s call, so it carries the same
    ceiling. The multi-chunk split is what supplies total document length.

    The two chunks in _WAVE_BUDGET_CONSTRAINED_CHUNK_KEYS are the exception:
    each is the smaller, sequential-only leg of a two-wave stage (spec's
    validation-risk, tasks' task-overview) and was deliberately shrunk to
    3,000-13,000 so its wave sums with its sibling wave's 24,000-char ceiling
    inside the shared 270s run budget — see
    test_the_spec_and_task_waves_fit_the_run_budget_together.
    """
    for stage in ("spec", "plan", "tasks"):
        chunks = sm._chunk_specs_for_stage(stage, "standard")
        assert len(chunks) > 1, f"{stage} must stay multi-chunk in standard mode"
        for chunk in chunks:
            assert chunk.whole_document is False
            target = sm._chunk_length_target(stage, chunk)
            if chunk.key in _WAVE_BUDGET_CONSTRAINED_CHUNK_KEYS:
                assert "3,000" in target and "13,000" in target
                continue
            assert "24,000" in target
            # Density initiative (2026-08-02): the floor was lowered from
            # 8,000 to 3,500 — a per-call prose-budget lever, not a depth-floor
            # reduction (_min_body_chars etc. are untouched).
            assert "3,500" in target


def test_no_non_harness_chunk_advertises_a_ceiling_past_the_measured_band():
    """The regression guard. Whatever branch a non-harness chunk takes, it must
    never be told it can spend more than one provider stream can finish — that
    is what times the stream out and de-escalates the retry to the mid tier.

    The wave-budget-constrained chunks (spec's validation-risk, tasks'
    task-overview) advertise a LOWER ceiling (13,000) than the generic 24,000 —
    still well inside the measured band, so the assertion is "at or below
    24,000", not "exactly 24,000"."""
    for mode in ("standard", "demo_day"):
        for stage in ("spec", "plan", "tasks"):
            for chunk in sm._chunk_specs_for_stage(stage, mode):
                target = sm._chunk_length_target(stage, chunk)
                assert max(_char_figures(target)) <= 24_000, (
                    mode,
                    stage,
                    chunk.key,
                    target,
                )
                assert "80,000" not in target, (mode, stage, chunk.key, target)
                assert "30,000" not in target, (mode, stage, chunk.key, target)


def test_harness_length_targets_are_not_affected_by_the_whole_document_rule():
    """The harness keys off _is_harness_files_chunk and is checked FIRST, so the
    every-runnable-file target can never be narrowed by the new branch."""
    for mode in ("standard", "demo_day"):
        files = next(
            c
            for c in sm._chunk_specs_for_stage("harness", mode)
            if c.required_heading == "## Files"
        )
        contract = next(
            c
            for c in sm._chunk_specs_for_stage("harness", mode)
            if c.required_heading != "## Files"
        )
        assert "Emit EVERY file named in the File Tree" in sm._chunk_length_target(
            "harness", files
        )
        assert "contract chunk" in sm._chunk_length_target("harness", contract)
        # The matrix/tree are enumeration, not a prose budget to trim.
        assert "never drop a requirement row" in sm._chunk_length_target(
            "harness", contract
        )


def test_every_chunk_one_ceiling_stays_at_or_below_a_reachable_figure():
    """The regression guard the harness contract chunk should have caught the
    first time: when the spec/plan/tasks ceiling was tightened from 80,000 to
    30,000 to fit inside the 240s provider-call cap, the harness contract chunk
    (also always chunk #1, same watchdog, same cap) was left at 45,000 —
    unreachable by design (~338s of output at measured throughput). This test
    walks every chunk-1-shaped target across both stage sets and both modes
    and pins each to a ceiling that is actually reachable inside the 240s cap.

    The HARNESS is now in scope on both chunks, and the two must add up: they
    are strictly sequential and share ONE run-scoped budget of 270 provider-
    seconds. At ~145 chars/s, 15,000 (contract) + 22,000 (files) is ~255s. The
    Files chunk was previously exempt at 180,000 characters — ~5x what 240s buys
    — on the reasoning that its length is set by the file list rather than prose
    depth; the watchdog kills on wall clock and does not care about the shape of
    the output.
    """
    non_harness_ceiling = 24_000
    for mode in ("standard", "demo_day"):
        for stage in ("spec", "plan", "tasks"):
            for chunk in sm._chunk_specs_for_stage(stage, mode):
                target = sm._chunk_length_target(stage, chunk)
                # Wave-budget-constrained chunks (spec's validation-risk,
                # tasks' task-overview) advertise a lower, still-reachable
                # 13,000 ceiling — see
                # test_the_spec_and_task_waves_fit_the_run_budget_together.
                assert max(_char_figures(target)) <= non_harness_ceiling, (
                    mode,
                    stage,
                    chunk.key,
                    target,
                )
                assert "45,000" not in target, (mode, stage, chunk.key, target)
        contract = next(
            c
            for c in sm._chunk_specs_for_stage("harness", mode)
            if c.required_heading != "## Files"
        )
        target = sm._chunk_length_target("harness", contract)
        assert "15,000" in target, (mode, "harness", contract.key, target)
        assert "45,000" not in target and "30,000" not in target

        files = next(
            c
            for c in sm._chunk_specs_for_stage("harness", mode)
            if c.required_heading == "## Files"
        )
        files_target = sm._chunk_length_target("harness", files)
        assert "22,000" in files_target, (mode, "harness", files.key, files_target)
        assert "180,000" not in files_target


def test_the_two_harness_chunks_fit_the_run_budget_together():
    """The harness is two STRICTLY SEQUENTIAL chunks on ONE 270s run budget.

    Nothing in the code allocated that budget between them, so the contract
    chunk's target could authorise ~207s and leave the chunk carrying every
    runnable test file ~63s. The targets are now sized to add up.
    """
    chars_per_second = 145  # measured: ~38 tok/s at effort=medium, ~3.5 chars/tok
    provider_seconds = (
        settings.stage_generation_deadline_seconds
        - settings.stage_generation_finalise_reserve_seconds
    )
    for mode in ("standard", "demo_day"):
        ceilings = []
        for chunk in sm._chunk_specs_for_stage("harness", mode):
            target = sm._chunk_length_target("harness", chunk)
            ceilings.append(max(_char_figures(target)))
        assert len(ceilings) == 2, mode
        assert sum(ceilings) / chars_per_second <= provider_seconds, (mode, ceilings)
        # And each single chunk still fits one provider call on its own.
        for ceiling in ceilings:
            assert (
                ceiling / chars_per_second
                <= settings.stage_provider_call_timeout_seconds
            ), (mode, ceiling)


def test_the_spec_and_task_waves_fit_the_run_budget_together():
    """Standard spec and tasks have the harness's exact defect: two SEQUENTIAL
    waves (a dependency-bound wave 2 that can only start once wave 1 finishes)
    drawing on the SAME 270s run-scoped budget, with nothing allocating that
    budget between them. Every chunk previously advertised the same generic
    24,000-char ceiling regardless of which wave it was in, so the two waves
    could sum to ~330s and the second wave could be killed by
    GenerationDeadlineExceeded, discarding its partial text and failing the
    whole generation.

    spec: [product-scope, system-expectations] (parallel) -> [validation-risk]
    tasks: [task-overview] ->
        [task-foundation, task-interface, task-hardening] (parallel)

    A wave's own wall-clock cost is bounded by its SLOWEST chunk (parallel
    chunks run concurrently), and waves run one after another, so the budget
    check is: sum over waves of (max ceiling in that wave) <= the run pool.

    Demo Day is exempt by construction: _chunk_waves_for_stage gives each of
    its single whole_document chunks its own wave, so there is only ever one
    wave and no cross-wave sum to overflow.
    """
    chars_per_second = 145  # measured: ~38 tok/s at effort=medium, ~3.5 chars/tok
    provider_seconds = (
        settings.stage_generation_deadline_seconds
        - settings.stage_generation_finalise_reserve_seconds
    )
    for stage in ("spec", "tasks"):
        waves = sm._chunk_waves_for_stage(stage, "standard")
        assert len(waves) == 2, (stage, waves)
        wave_costs = []
        for wave in waves:
            ceilings = [
                max(_char_figures(sm._chunk_length_target(stage, chunk)))
                for chunk in wave
            ]
            wave_costs.append(max(ceilings))
        assert sum(wave_costs) / chars_per_second <= provider_seconds, (
            stage,
            wave_costs,
        )
        # And each individual chunk still fits inside one provider call.
        for wave in waves:
            for chunk in wave:
                ceiling = max(_char_figures(sm._chunk_length_target(stage, chunk)))
                assert (
                    ceiling / chars_per_second
                    <= settings.stage_provider_call_timeout_seconds
                ), (stage, chunk.key, ceiling)

    # Demo Day is untouched: single-chunk waves, so there is nothing to sum.
    for stage in ("spec", "tasks"):
        waves = sm._chunk_waves_for_stage(stage, "demo_day")
        assert all(len(wave) == 1 for wave in waves), (stage, waves)


def test_chunk_floors_clear_the_depth_floors():
    """A stage's prompted length FLOOR must leave room for its own depth floors.

    Demo Day plan is the shape that broke: 13 required sections in ONE chunk at a
    180-char normalised floor needs ~4,715 RAW characters once markdown
    normalisation is accounted for (measured keep-rates: tables 69%, mermaid 54%,
    bullets 79%) — against a 3,500-char advertised floor. ~0.3% margin, on a
    prompt that also says "do not pad toward the upper bound", so a model obeying
    its own instruction tripped shallow_required_section on multiple sections.

    Asserted for every (stage, mode) pair so the next density initiative cannot
    silently re-create it on a different shape.
    """
    keep_rate = 0.70  # conservative blend for table/diagram-heavy contracts
    margin = 1.30
    for mode in ("standard", "demo_day"):
        for stage in ("spec", "plan", "harness", "tasks"):
            headings = av.section_contract(stage, mode)
            floor = av._min_body_chars(stage, mode)
            needed = len(headings) * floor / keep_rate * margin
            needed += sum(len(h) + 2 for h in headings)
            budgeted = 0.0
            for chunk in sm._chunk_specs_for_stage(stage, mode):
                figures = _char_figures(sm._chunk_length_target(stage, chunk))
                # A chunk whose target states only a ceiling (the harness Files
                # chunk) contributes no floor — deliberately conservative.
                budgeted += min(figures) if len(figures) > 1 else 0
            assert budgeted >= needed, (stage, mode, budgeted, needed)


def test_length_target_keys_on_structure_not_the_demo_full_key_string():
    """The discriminator is chunk.whole_document, so a renamed/added
    whole-document chunk in either mode inherits the single-call target — the
    same lesson as _is_harness_files_chunk."""
    renamed = sm.ArtifactChunkSpec(
        "some-other-single-pass-key",
        "Generate the complete artifact.",
        whole_document=True,
    )
    assert "24,000" in sm._chunk_length_target("spec", renamed)


def test_demo_day_single_call_chunks_skip_the_anthropic_cache_write():
    """A Demo Day whole-document chunk is exactly ONE provider call, so an
    Anthropic cache WRITE (billed at 1.25x base input) can never be read back
    and is a pure surcharge. Measured on a real spec: 4,913 tokens written at
    $6.25/M = $0.0307 where plain input would have cost $0.0246.
    """
    for stage in ("spec", "plan", "tasks"):
        chunk = sm._chunk_specs_for_stage(stage, "demo_day")[0]
        assert chunk.whole_document is True
        assert sm._should_cache_system_prompt("demo_day", chunk, "anthropic") is False


def test_cache_write_suppression_is_scoped_to_demo_day_anthropic_whole_document():
    """The suppression must not leak. Each of the three conditions alone keeps
    caching ON, because each implies a reader exists (or no write premium)."""
    demo_chunk = sm._chunk_specs_for_stage("spec", "demo_day")[0]

    # Other providers: cache_system is a no-op there (automatic prefix caching,
    # no write premium), so the answer must stay True rather than silently
    # changing behaviour on a failover route.
    for provider in ("openai", "google"):
        assert sm._should_cache_system_prompt("demo_day", demo_chunk, provider) is True

    # Standard mode is deliberately untouched.
    assert sm._should_cache_system_prompt("standard", demo_chunk, "anthropic") is True

    # Multi-chunk stages have readers: chunk 2+ reads what chunk 1 wrote. Demo
    # Day's harness is TWO chunks, so it must keep caching.
    harness_chunks = sm._chunk_specs_for_stage("harness", "demo_day")
    assert len(harness_chunks) > 1
    for chunk in harness_chunks:
        assert chunk.whole_document is False
        assert sm._should_cache_system_prompt("demo_day", chunk, "anthropic") is True


def test_standard_mode_chunks_always_keep_the_cache_write():
    """Standard multi-chunk stages are the case prefix caching exists for."""
    for stage in ("spec", "plan", "tasks"):
        for chunk in sm._chunk_specs_for_stage(stage, "standard"):
            assert (
                sm._should_cache_system_prompt("standard", chunk, "anthropic") is True
            )
