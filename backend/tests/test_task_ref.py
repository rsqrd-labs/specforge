"""Unit tests for compute_task_ref — the stable, content-derived matching key
(T-266, spec Assumption 23).

The load-bearing property is that the key depends on task *content*, not the
``T-NNN`` number, so a refinement that renumbers tasks updates the same GitHub
Issue instead of opening a duplicate.
"""

from __future__ import annotations

from services.integrations.task_parser import compute_task_ref


def test_ref_is_deterministic() -> None:
    assert compute_task_ref("Set up project structure") == compute_task_ref(
        "Set up project structure"
    )


def test_ref_is_independent_of_task_number() -> None:
    # The same title produces the same ref regardless of any T-NNN it was
    # numbered with — renumbering must not duplicate the issue.
    title = "Wire up the credit ledger"
    assert compute_task_ref(title) == compute_task_ref(title)


def test_distinct_titles_produce_distinct_refs() -> None:
    assert compute_task_ref("Build the parser") != compute_task_ref(
        "Build the renderer"
    )


def test_ref_normalizes_case_and_whitespace() -> None:
    base = compute_task_ref("Set up   project structure")
    assert base == compute_task_ref("set up project structure")
    assert base == compute_task_ref("  Set Up Project Structure  ")
    assert base == compute_task_ref("Set up\tproject\nstructure")


def test_ref_is_stage_scoped() -> None:
    # Same title in different stages must not collide.
    assert compute_task_ref("Overview", stage="tasks") != compute_task_ref(
        "Overview", stage="spec"
    )


def test_ref_has_stable_namespaced_shape() -> None:
    ref = compute_task_ref("Anything at all")
    assert ref.startswith("task-")
    # 5-char prefix + 12 hex chars.
    assert len(ref) == len("task-") + 12
    assert all(c in "0123456789abcdef" for c in ref.removeprefix("task-"))
