"""Golden pins for the judgment layer (prompt-quality audit theme 4).

The audit named three frequently-exercised surfaces with no golden-corpus or
grader coverage: the harness gap-patch, increment generation, and the judges
themselves. The fixtures in ``harness/prompt_eval/golden_judgment/`` pin all
three deterministically — no LLM call:

- ``harness_patch/`` and ``increment/`` hold a good/bad artifact pair each,
  scored by the non-stage-shaped graders in ``prompt_eval.graders.judgment``
  (deliberately not ``ALL_GRADERS`` members — their inputs are not the
  ``(stage_type, artifact_md, deps)`` triple).
- ``judges/`` holds raw judge *responses* exhibiting the wrapping misbehaviour
  the parse layers exist to absorb (preamble prose, markdown fences,
  out-of-range and non-numeric scores), pinned against the deterministic
  parse/normalise layers of the online-eval judge and the critic. The
  pr-evaluator's deterministic layer (``_truncate_diff_by_hunk``) is already
  pinned in ``backend/tests/test_pr_evaluator.py``.

These are byte-golden fixtures: a change to a grader's scoring or a judge's
normalisation that alters any pinned value must update the fixture in the same
commit, which is exactly the review moment the audit asked for.
"""

from __future__ import annotations

import json
import sys

from harness_utils import REPO_ROOT, import_backend

# Same pattern as test_prompt_eval_anonymization.py: CI invokes these tests
# from the backend cwd (`uv run pytest ../harness/tests/backend/...`), so the
# harness root is not implicitly importable.
_HARNESS_ROOT = REPO_ROOT / "harness"
if str(_HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(_HARNESS_ROOT))

from prompt_eval.graders.judgment import (  # noqa: E402
    harness_patch_covers_targets,
    harness_patch_is_additive,
    increment_growth_is_monotonic,
)

_GOLDEN = REPO_ROOT / "harness" / "prompt_eval" / "golden_judgment"


def _fixture(*parts: str) -> str:
    return _GOLDEN.joinpath(*parts).read_text(encoding="utf-8")


# --- harness gap-patch (P06) --------------------------------------------------


def test_good_patch_covers_every_target() -> None:
    result = harness_patch_covers_targets(
        _fixture("harness_patch", "patch_good.md"), ["FR-009", "FR-010"]
    )
    assert result.score == 1.0
    assert result.findings == ()


def test_bad_patch_leaves_a_target_uncovered() -> None:
    result = harness_patch_covers_targets(
        _fixture("harness_patch", "patch_bad.md"), ["FR-009", "FR-010"]
    )
    assert result.score == 0.5
    assert result.findings == ("No tagged test for FR-010",)


def test_good_patch_is_additive() -> None:
    result = harness_patch_is_additive(
        _fixture("harness_patch", "patch_good.md"),
        _fixture("harness_patch", "existing_harness.md"),
    )
    assert result.score == 1.0
    assert result.findings == ()
    assert result.metadata["files"] == 1


def test_bad_patch_trips_every_additive_violation() -> None:
    result = harness_patch_is_additive(
        _fixture("harness_patch", "patch_bad.md"),
        _fixture("harness_patch", "existing_harness.md"),
    )
    assert result.score == 0.0
    # The bad fixture exhibits all three violation classes the grader exists
    # to catch: clobbering an existing file, conversational preamble, and a
    # stub-only body.
    assert result.findings == (
        "Patch re-emits existing file tests/integration/test_invoices.py",
        "Patch carries preamble/commentary before the first file.",
        "tests/performance/test_budget_patch.py: fenced body is a stub.",
    )


# --- increment generation (P13) -----------------------------------------------


def test_good_increment_appends_without_mutation() -> None:
    result = increment_growth_is_monotonic(
        _fixture("increment", "baseline_tasks.md"),
        _fixture("increment", "increment_good.md"),
    )
    assert result.score == 1.0
    assert result.findings == ()
    assert result.metadata == {
        "baseline_tasks": 2,
        "new_tasks": 2,
        "violations": 0,
    }


def test_bad_increment_trips_every_monotonicity_violation() -> None:
    result = increment_growth_is_monotonic(
        _fixture("increment", "baseline_tasks.md"),
        _fixture("increment", "increment_bad.md"),
    )
    assert result.score == 0.0
    # All four violation classes: a mutated historical task (already-exported
    # GitHub issues get silently rewritten), a vanished task, a numbering gap,
    # and a new task with no harness join key.
    assert result.findings == (
        "Baseline task T-001 was mutated.",
        "Baseline task T-002 disappeared.",
        "New task numbers [5] do not continue the sequence (expected [3]).",
        "New task T-005 has no Harness refs field.",
    )


# --- the judges' deterministic parse layers ------------------------------------


def test_eval_judge_normalises_a_wrapped_response() -> None:
    # A realistic misbehaving judge response: preamble prose, a markdown fence,
    # an out-of-range score (clamped), a non-numeric score (dropped from the
    # weighted average), and a stringly-typed task_number. The parse +
    # normalise pipeline must land on exactly the pinned payload.
    online_eval = import_backend("services.evals.online_eval")
    raw_response = _fixture("judges", "eval_response_wrapped.txt")
    parsed = online_eval._parse_eval_json(raw_response)
    assert parsed is not None
    normalised = online_eval._normalise_eval_payload("plan", parsed)
    assert normalised == json.loads(_fixture("judges", "eval_expected.json"))


def test_critic_extracts_verdict_from_fenced_response() -> None:
    critic = import_backend("services.pipeline.critic")
    extracted = critic._extract_json_object(
        _fixture("judges", "critic_response_fenced.txt")
    )
    verdict = critic.StageCriticResult.model_validate_json(extracted)
    assert verdict.passed is False
    assert [finding.kind for finding in verdict.findings] == ["ShallowSection"]
    assert verdict.findings[0].reference == "## Security"
