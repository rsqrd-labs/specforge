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

import pytest

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
    assert "every promised runnable file" in sm._chunk_length_target(
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
    assert av._manifest_section_issue("## File Tree", tree_body) is None


def test_empty_file_tree_still_reported():
    issue = av._manifest_section_issue("## File Tree", "To be determined.")
    assert issue is not None
    assert issue.code == "shallow_required_section"


# ---------------------------------------------------------------------------
# 4. Mode-aware eval judge.
# ---------------------------------------------------------------------------


def test_demo_day_spec_is_not_scored_on_sections_its_contract_forbids():
    """``user_flow_coverage`` is not asked for or weighted in Demo Day.

    ``DEMO_DAY_SECTION_CONTRACTS["spec"]`` has no User Journeys / User Flow
    Diagrams section — Demo Day specifies exactly ONE happy path (Success Demo) —
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


def test_coverage_is_computed_from_the_artifact_not_the_judge():
    assert av.harness_coverage_ratio(_coverage_harness(emit_pay=True)) == (2, 2)
    assert av.harness_coverage_ratio(_coverage_harness(emit_pay=False)) == (1, 2)
    assert oe._deterministic_coverage_percent(_coverage_harness(emit_pay=False)) == 50
    assert oe._deterministic_coverage_percent(_coverage_harness(emit_pay=True)) == 100


def test_coverage_and_the_gap_list_can_never_disagree():
    """The chip, the CoveragePanel and the paid patch are three views of one
    computation — a 100% chip beside a populated gap list is now impossible."""
    partial = _coverage_harness(emit_pay=False)
    covered, total = av.harness_coverage_ratio(partial)
    assert total - covered == len(av.uncovered_requirements(partial))


def test_unparseable_matrix_reads_as_unknown_not_zero_percent():
    """A harness with no parseable matrix must render NO chip, not 0% coverage —
    the difference between "no data" and a false alarm."""
    assert oe._deterministic_coverage_percent("## Harness Overview\nnothing") is None
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
            _coverage_harness(emit_pay=False)
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
# 5. The single-call length target (Demo Day's whole-document chunks)
#
# A chunk is exactly one provider stream, killed at the
# stage_provider_call_timeout_seconds hard cap (validator-capped at 180s) with
# its partial text discarded. The 80,000-character "document chunk" target is
# written for a SLICE — standard spec/plan/tasks are 3-4 chunks, so no single
# call is asked to fill it. Demo Day runs spec/plan/tasks as ONE whole-document
# chunk, so that same target asked one 180s call to produce ~20K output tokens,
# past the ~15-18K dense-chunk band that fits at effort=medium. Timing out is
# strictly worse than finishing short: the retry lands on the mid tier with less
# time left than the first attempt had.
# ---------------------------------------------------------------------------


_STANDARD_DOCUMENT_TARGET = (
    "Length target: 8,000-80,000 characters for this document chunk."
)


def test_whole_document_chunks_get_a_single_call_length_target():
    """Every Demo Day whole-document chunk is sized for one 180s call."""
    for stage in ("spec", "plan", "tasks"):
        chunks = sm._chunk_specs_for_stage(stage, "demo_day")
        assert len(chunks) == 1, f"{stage} is expected to stay single-pass"
        chunk = chunks[0]
        assert chunk.whole_document is True
        target = sm._chunk_length_target(stage, chunk)
        assert "55,000" in target
        assert target != _STANDARD_DOCUMENT_TARGET
        # The floor is untouched: this trims the unreachable head of the range,
        # it is not a depth reduction.
        assert "8,000" in target


def test_standard_document_chunks_are_unchanged():
    """Byte-identical for every standard multi-chunk stage — the slice target
    is correct there precisely because no single call carries the whole doc."""
    for stage in ("spec", "plan", "tasks"):
        chunks = sm._chunk_specs_for_stage(stage, "standard")
        assert len(chunks) > 1, f"{stage} must stay multi-chunk in standard mode"
        for chunk in chunks:
            assert chunk.whole_document is False
            assert sm._chunk_length_target(stage, chunk) == _STANDARD_DOCUMENT_TARGET


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
        assert "every promised runnable file" in sm._chunk_length_target(
            "harness", files
        )
        assert "contract chunk" in sm._chunk_length_target("harness", contract)


def test_length_target_keys_on_structure_not_the_demo_full_key_string():
    """The discriminator is chunk.whole_document, so a renamed/added
    whole-document chunk in either mode inherits the single-call target — the
    same lesson as _is_harness_files_chunk."""
    renamed = sm.ArtifactChunkSpec(
        "some-other-single-pass-key",
        "Generate the complete artifact.",
        whole_document=True,
    )
    assert "55,000" in sm._chunk_length_target("spec", renamed)


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
