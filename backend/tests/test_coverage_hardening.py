"""Coverage/harness detection hardening (issue: false test-coverage gaps).

Regression pins for the false-positive fixes AND the paired "still catches the
real hole" cases, so a future loosening of matching cannot silently start hiding
genuine coverage gaps. Groups map to the fix prongs:

* canonicaliser consistency across call sites
* uncovered_requirements matrix→file integrity (FP-5 `::`, FP-6 case, multi-file
  cell, post-patch 2-hash heading, the `_section_body` heading-level trap)
* span-based ref extraction (FP-1 prose-before-fence, FP-2 fence info string,
  Go/RSpec/it.each, over-long close fence)
* the UNVERIFIED_COVERAGE file-level fallback (FP-3) and its non-flagging invariant
* the completeness-aware patch merge + round-trip idempotence (D-2/D-3)
* missing_harness_files (the Prong-A trigger predicate) and the auto-complete pass
"""

from __future__ import annotations

import pytest

from services.evals.online_eval import (
    _harness_ref_index,
    _ref_matches_harness,
    _validate_task_references,
    validate_stage_findings,
)
from services.pipeline.artifact_validator import (
    _canonical_test_path,
    _harness_issues,
    _looks_like_test_file_path,
    harness_file_tree_paths,
    missing_harness_files,
    uncovered_requirements,
)
from services.pipeline.stage_manager import (
    _file_block_is_complete,
    _merge_harness_patch,
)


def _matrix_harness(cell: str, *, file_hashes: str = "###", matrix_hashes: str = "##"):
    return f"""{matrix_hashes} Requirement-to-Test Matrix

| Source ID | Behaviour | Test file | Type | Status |
|---|---|---|---|---|
| FR-001 | login | {cell} | unit | fail-first |

## Files

{file_hashes} File: tests/unit/test_auth.py
```python
# Tests: FR-001
def test_login_ok():
    assert False, "not implemented: FR-001"
```
"""


def _gaps(issues):
    return [(i["task_number"], i["gap_type"]) for i in issues]


def _task(refs: str, num: int = 1) -> str:
    return f"""### T-{num:03d}: Do the thing

**Harness refs:** {refs}

**Priority:** MUST
**Estimate:** S
"""


class TestCanonicalTestPath:
    def test_strips_harness_prefix_and_casefolds(self) -> None:
        assert _canonical_test_path("Harness/Tests/Auth.py") == "tests/auth.py"

    def test_strips_dot_slash_and_leading_slash(self) -> None:
        assert _canonical_test_path("./tests/x.py") == "tests/x.py"
        assert _canonical_test_path("/tests/x.py") == "tests/x.py"

    def test_takes_file_part_before_double_colon(self) -> None:
        assert _canonical_test_path("tests/x.py::TestC::test_m") == "tests/x.py"

    def test_backslashes_and_backticks_normalised(self) -> None:
        assert _canonical_test_path("`tests\\unit\\x.py`") == "tests/unit/x.py"

    def test_case_and_prefix_combination(self) -> None:
        # The exact combination that broke the first draft (prefix strip ran
        # before casefold, so a capitalised Harness/ was never removed).
        assert _canonical_test_path("./Harness/Tests/X.PY::test_a") == "tests/x.py"


class TestUncoveredRequirementsHardening:
    def test_fp5_file_and_test_in_one_cell_is_not_a_false_gap(self) -> None:
        assert (
            uncovered_requirements(
                _matrix_harness("`tests/unit/test_auth.py::test_login_ok`")
            )
            == []
        )

    def test_fp6_case_mismatch_is_not_a_false_gap(self) -> None:
        assert (
            uncovered_requirements(_matrix_harness("`tests/Unit/test_auth.py`")) == []
        )

    def test_multi_file_cell_with_one_emitted_is_covered(self) -> None:
        cell = "`tests/unit/test_auth.py`, `tests/unit/test_extra.py`"
        assert uncovered_requirements(_matrix_harness(cell)) == []

    def test_post_patch_two_hash_heading_is_counted(self) -> None:
        # A gap patch historically merged `## File:` (two hashes); the coverage
        # deriver must now count it, or a paid patch never clears the panel.
        assert (
            uncovered_requirements(
                _matrix_harness("`tests/unit/test_auth.py`", file_hashes="##")
            )
            == []
        )

    def test_genuine_gap_is_still_reported(self) -> None:
        assert uncovered_requirements(
            _matrix_harness("`tests/unit/test_missing.py`")
        ) == ["FR-001"]

    def test_section_body_trap_matrix_at_h3_is_not_silently_disabled(self) -> None:
        # `### Requirement-to-Test Matrix` passes the substring section gate; the
        # body reader must still find it or detection silently returns [].
        harness = _matrix_harness("`tests/unit/test_missing.py`", matrix_hashes="###")
        assert uncovered_requirements(harness) == ["FR-001"]

    def test_no_matrix_returns_empty(self) -> None:
        assert uncovered_requirements("## Files\n\n### File: x.py\n```\n```") == []


class TestSpanBasedRefExtraction:
    def test_fp1_prose_between_heading_and_fence(self) -> None:
        harness = """## Files

### File: tests/unit/test_auth.py

This file verifies the auth flows.

```python
# Tests: FR-001
def test_login_ok():
    assert False
```
"""
        refs = _harness_ref_index(harness)
        assert _ref_matches_harness(
            "tests/unit/test_auth.py::test_login_ok", refs.known_refs
        )
        assert _canonical_test_path("tests/unit/test_auth.py") in refs.files_with_tests

    def test_fp2_fence_info_string(self) -> None:
        harness = """## Files

### File: tests/unit/auth.test.ts
```ts title="auth.test.ts"
// Tests: FR-001
it("logs in ok", () => { expect(false).toBe(true) })
```
"""
        refs = _harness_ref_index(harness).known_refs
        assert _ref_matches_harness("tests/unit/auth.test.ts::logs in ok", refs)

    def test_go_test_functions(self) -> None:
        harness = """## Files

### File: internal/auth/auth_test.go
```go
// Tests: FR-001
func TestLoginOK(t *testing.T) { t.Fatal("nope") }
```
"""
        refs = _harness_ref_index(harness).known_refs
        assert _ref_matches_harness("internal/auth/auth_test.go::TestLoginOK", refs)

    def test_rspec_it_do_blocks(self) -> None:
        harness = """## Files

### File: spec/auth_spec.rb
```ruby
describe "Auth" do
  it "logs in ok" do
    expect(false).to be true
  end
end
```
"""
        refs = _harness_ref_index(harness).known_refs
        assert _ref_matches_harness("spec/auth_spec.rb::logs in ok", refs)

    def test_ts_each_parametrised(self) -> None:
        harness = """## Files

### File: tests/unit/math.test.ts
```ts
it.each([[1, 2], [3, 4]])("adds %i and %i", (a, b) => { expect(a).toBe(b) })
```
"""
        refs = _harness_ref_index(harness).known_refs
        assert _ref_matches_harness("tests/unit/math.test.ts::adds %i and %i", refs)

    def test_over_long_close_fence_does_not_swallow_next_file(self) -> None:
        # A closing fence longer than the opener still closes (CommonMark), so the
        # scanner does not run away past every subsequent ### File: heading.
        harness = """## Files

### File: tests/a.py
```python
def test_a():
    assert False
````

### File: tests/b.py
```python
def test_b():
    assert False
```
"""
        refs = _harness_ref_index(harness)
        assert _canonical_test_path("tests/b.py") in refs.known_files
        assert _ref_matches_harness("tests/b.py::test_b", refs.known_refs)


class TestUnverifiedCoverageFallback:
    def test_bodied_nonpython_file_downgrades_to_unverified(self) -> None:
        # A Java file whose @Test methods our parser cannot read: the file exists
        # and HAS a body, so absence is unproven -> quiet UNVERIFIED, not a scary
        # GENUINE_GAP (Fable #4: only genuinely-blind parses demote).
        harness = """## Files

### File: tests/AuthTest.java
```java
@Test public void testLogin() { assertTrue(true); }
```
"""
        assert _gaps(
            _validate_task_references(
                _task("`tests/AuthTest.java::testRefresh`"), harness
            )
        ) == [(1, "UNVERIFIED_COVERAGE")]

    def test_empty_python_file_is_genuine_not_unverified(self) -> None:
        # A readable .py file with zero test defs is POSITIVE evidence of absence
        # (we parse pytest/unittest completely) -> GENUINE, never hidden as
        # unverified (Fable #4 — the over-suppression that hid real gaps).
        harness = """## Files

### File: tests/unit/test_weird.py
```python
import os
```
"""
        assert _gaps(
            _validate_task_references(
                _task("`tests/unit/test_weird.py::test_thing`"), harness
            )
        ) == [(1, "GENUINE_GAP")]

    def test_promised_empty_file_no_body_is_genuine(self) -> None:
        # A file heading with NO fenced body at all (promised but left empty) is
        # the strongest, language-agnostic gap signal -> GENUINE regardless of
        # extension.
        harness = "## Files\n\n### File: tests/AuthTest.java\n\n"
        assert _gaps(
            _validate_task_references(
                _task("`tests/AuthTest.java::testLogin`"), harness
            )
        ) == [(1, "GENUINE_GAP")]

    def test_genuine_gap_kept_when_file_has_parsed_tests(self) -> None:
        harness = """## Files

### File: tests/unit/test_auth.py
```python
def test_login_ok():
    assert False
```
"""
        assert _gaps(
            _validate_task_references(
                _task("`tests/unit/test_auth.py::test_absent`"), harness
            )
        ) == [(1, "GENUINE_GAP")]

    def test_nonexistent_file_is_genuine(self) -> None:
        # Use a test name that exists nowhere, so the (intentional, pre-existing)
        # bare-name fallback in _ref_matches_harness cannot match it elsewhere.
        harness = (
            "## Files\n\n### File: tests/unit/test_auth.py\n"
            "```python\ndef test_login(): assert False\n```"
        )
        refs = "`tests/unit/test_nope.py::test_unique_absent`"
        assert _gaps(_validate_task_references(_task(refs), harness)) == [
            (1, "GENUINE_GAP")
        ]

    def test_genuine_wins_over_unverified_on_mixed_task(self) -> None:
        harness = """## Files

### File: tests/unit/test_real.py
```python
def test_present():
    assert False
```

### File: tests/unit/test_empty.py
```python
```
"""
        refs = (
            "`tests/unit/test_empty.py::test_a`, `tests/unit/test_real.py::test_absent`"
        )
        assert _gaps(_validate_task_references(_task(refs), harness)) == [
            (1, "GENUINE_GAP")
        ]

    def test_unverified_does_not_flag(self) -> None:
        # A bodied non-.py file we cannot parse stays UNVERIFIED (non-flagging).
        harness = (
            "## Files\n\n### File: tests/AuthTest.java\n"
            "```java\n@Test void testLogin() {}\n```"
        )
        _issues, flagged = validate_stage_findings(
            "tasks", _task("`tests/AuthTest.java::testRefresh`"), harness
        )
        assert flagged is False


class TestPatchMergeCompleteness:
    def test_round_trip_clears_the_gap(self) -> None:
        existing = _matrix_harness("`tests/unit/test_missing.py`")
        assert uncovered_requirements(existing) == ["FR-001"]
        patch = """### File: tests/unit/test_missing.py
```python
# Tests: FR-001
def test_missing():
    assert False
```
"""
        merged = _merge_harness_patch(existing, patch)
        assert uncovered_requirements(merged) == []

    def test_truncated_trailing_block_is_dropped(self) -> None:
        existing = (
            "## Files\n\n### File: tests/a.py\n```python\ndef test_a(): pass\n```"
        )
        patch = """### File: tests/b.py
```python
def test_b():
    assert False
```

### File: tests/c.py
```python
def test_c(): assert Fal"""
        merged = _merge_harness_patch(existing, patch, source="patch")
        assert "tests/b.py" in merged
        assert "tests/c.py" not in merged

    def test_canonical_dedup_never_readds_existing_file(self) -> None:
        existing = (
            "## Files\n\n### File: tests/a.py\n"
            "```python\ndef test_a(): assert False\n```"
        )
        patch = (
            "### File: harness/Tests/A.py\n```python\ndef test_a(): assert False\n```"
        )
        assert _merge_harness_patch(existing, patch) == existing

    def test_file_block_completeness_helper(self) -> None:
        assert _file_block_is_complete("### File: x\n```py\ncode\n```") is True
        assert _file_block_is_complete("### File: x\n```py\ncode") is False
        assert _file_block_is_complete("### File: x\n(no fence at all)") is False


class TestMissingHarnessFiles:
    def test_union_of_tree_and_matrix_minus_emitted(self) -> None:
        harness = """## Requirement-to-Test Matrix

| ID | B | Test | T | S |
|---|---|---|---|---|
| FR-001 | a | `tests/unit/test_a.py` | unit | fail |
| FR-002 | b | `tests/unit/test_b.py` | unit | fail |

## File Tree
```
tests/unit/test_a.py
tests/unit/test_b.py
tests/conftest.py
```

## Files

### File: tests/unit/test_a.py
```python
def test_a(): assert False
```
"""
        missing, total = missing_harness_files(harness)
        assert missing == ["tests/conftest.py", "tests/unit/test_b.py"]
        assert total == 3

    def test_zero_heading_files_section_still_reports_missing(self) -> None:
        # The whole Files chunk fell over — every promised file is missing. This
        # must NOT be silenced by a "needs >=1 emitted heading" guard.
        harness = """## File Tree
```
tests/unit/test_a.py
tests/unit/test_b.py
```

## Files
"""
        missing, total = missing_harness_files(harness)
        assert missing == ["tests/unit/test_a.py", "tests/unit/test_b.py"]
        assert total == 2

    def test_complete_harness_reports_nothing(self) -> None:
        harness = """## File Tree
```
tests/unit/test_a.py
```

## Files

### File: tests/unit/test_a.py
```python
def test_a(): assert False
```
"""
        assert missing_harness_files(harness) == ([], 1)

    def test_file_tree_paths_helper(self) -> None:
        harness = "## File Tree\n```\ntests/a.py\ntests/b.py\n```\n\n## Files\n"
        assert harness_file_tree_paths(harness) == ["tests/a.py", "tests/b.py"]


class _FakeAdapter:
    """Minimal async-streaming adapter for the auto-complete unit test."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.last_generation_id = "gen-fake"

    async def stream(self, system: str, user: str, *, max_tokens: int):  # noqa: ARG002
        yield self._text


def _route():
    from services.llm.routing import LLMRoute

    return LLMRoute(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        model_tier="cheap",
        operation="harness.generate",
        latency_class="interactive",
        cross_provider_fallback=False,
        reason="test",
        requested_tier="cheap",
        fallback_tier=None,
        selection_reason="test",
    )


class TestHarnessAutocomplete:
    @pytest.mark.asyncio
    async def test_fills_missing_promised_file(self) -> None:
        from services.pipeline.stage_manager import StageManager

        harness = """## File Tree
```
tests/unit/test_a.py
tests/unit/test_b.py
```

## Files

### File: tests/unit/test_a.py
```python
def test_a(): assert False
```
"""
        patch = (
            "### File: tests/unit/test_b.py\n```python\ndef test_b(): assert False\n```"
        )
        result = await StageManager()._autocomplete_missing_harness_files(
            artifact=harness, adapter=_FakeAdapter(patch), route=_route()
        )
        assert "### File: tests/unit/test_b.py" in result
        assert missing_harness_files(result) == ([], 2)

    @pytest.mark.asyncio
    async def test_complete_harness_makes_no_llm_call(self) -> None:
        from services.pipeline.stage_manager import StageManager

        harness = """## File Tree
```
tests/unit/test_a.py
```

## Files

### File: tests/unit/test_a.py
```python
def test_a(): assert False
```
"""

        class _ExplodingAdapter:
            last_generation_id = "x"

            async def stream(self, *a, **k):  # noqa: ANN002, ANN003
                raise AssertionError("must not call the LLM for a complete harness")
                yield ""  # pragma: no cover

        result = await StageManager()._autocomplete_missing_harness_files(
            artifact=harness, adapter=_ExplodingAdapter(), route=_route()
        )
        assert result == harness

    @pytest.mark.asyncio
    async def test_too_many_missing_files_skips(self) -> None:
        from services.pipeline.stage_manager import StageManager

        tree = "\n".join(f"tests/unit/test_{i}.py" for i in range(20))
        harness = f"## File Tree\n```\n{tree}\n```\n\n## Files\n"

        class _ExplodingAdapter:
            last_generation_id = "x"

            async def stream(self, *a, **k):  # noqa: ANN002, ANN003
                raise AssertionError("must not call the LLM when over the cap")
                yield ""  # pragma: no cover

        result = await StageManager()._autocomplete_missing_harness_files(
            artifact=harness, adapter=_ExplodingAdapter(), route=_route()
        )
        assert result == harness


class TestDroppedCategoryFullPath:
    def test_category_in_directory_now_reclassifies_as_deferred(self) -> None:
        # `accessibility` lives in the directory, not the filename stem — the
        # stem-only match missed it, so a deferred category read as a genuine gap.
        harness = """## Coverage Plan

TestCategoryGap: category=accessibility reason=token_budget reqs=FR-001

## Files

### File: tests/unit/test_auth.py
```python
def test_login(): assert False
```
"""
        task = _task("`tests/accessibility/nav.test.ts::renders`")
        assert _gaps(_validate_task_references(task, harness)) == [
            (1, "DEFERRED_COVERAGE")
        ]


class TestFableReviewRound2:
    """Regression pins for the second adversarial review's confirmed findings."""

    def test_indented_close_fence_is_content_not_a_close(self) -> None:
        # Fable #1: a ``` indented >3 spaces inside a string literal is fence
        # CONTENT (CommonMark), not a close. The old scanner closed on it and
        # every test defined AFTER it went invisible -> false GENUINE_GAP.
        harness = '''## Files

### File: tests/unit/test_docs.py
```python
def test_render():
    md = """
        ```
        # heading
        ```
    """
    assert md


def test_toc():
    assert True
```
'''
        refs = _harness_ref_index(harness)
        assert _ref_matches_harness(
            "tests/unit/test_docs.py::test_toc", refs.known_refs
        )
        # A task referencing the later test must NOT read as a gap.
        assert (
            _validate_task_references(
                _task("`tests/unit/test_docs.py::test_toc`"), harness
            )
            == []
        )

    @pytest.mark.parametrize(
        "ref",
        [
            "./tests/unit/test_auth.py",
            "/tests/unit/test_auth.py",
            "Tests/Unit/Test_Auth.py",
            "harness/tests/unit/test_auth.py",
        ],
    )
    def test_file_only_ref_matches_across_cosmetic_differences(self, ref: str) -> None:
        # Fable #2: a whole-file ref differing only by ./, leading /, case, or a
        # harness/ prefix must resolve, not manufacture a phantom GENUINE_GAP.
        harness = (
            "## Files\n\n### File: tests/unit/test_auth.py\n"
            "```python\ndef test_login(): assert False\n```"
        )
        assert _gaps(_validate_task_references(_task(f"`{ref}`"), harness)) == []

    def test_file_qualified_ref_still_flags_missing_test_in_present_file(self) -> None:
        # The #2 canonical fallback must NOT wave through a file::test ref just
        # because the file exists — a genuinely missing test inside a present file
        # stays GENUINE (the over-suppression guard).
        harness = (
            "## Files\n\n### File: tests/unit/test_auth.py\n"
            "```python\ndef test_login(): assert False\n```"
        )
        assert _gaps(
            _validate_task_references(
                _task("`tests/unit/test_auth.py::test_absent`"), harness
            )
        ) == [(1, "GENUINE_GAP")]

    def test_go_testify_receiver_method_is_parsed(self) -> None:
        # Fable #11: testify `func (s *Suite) TestX()` must register as a test.
        harness = (
            "## Files\n\n### File: tests/auth_test.go\n"
            "```go\nfunc (s *AuthSuite) TestRefresh(t *testing.T) {}\n```"
        )
        refs = _harness_ref_index(harness)
        assert "TestRefresh" in refs.known_refs
        assert _canonical_test_path("tests/auth_test.go") in refs.files_with_tests
        assert (
            _validate_task_references(
                _task("`tests/auth_test.go::TestRefresh`"), harness
            )
            == []
        )

    def test_pytest_class_name_is_registered_as_ref(self) -> None:
        harness = (
            "## Files\n\n### File: tests/test_auth.py\n"
            "```python\nclass TestLogin:\n    def test_ok(self): assert False\n```"
        )
        refs = _harness_ref_index(harness)
        assert "TestLogin" in refs.known_refs
        assert (
            _validate_task_references(_task("`tests/test_auth.py::TestLogin`"), harness)
            == []
        )

    def test_community_does_not_mask_a_unit_gap(self) -> None:
        # Fable #9: `unit` is a substring of `comm-unit-y` but must not reclassify
        # an unrelated real gap as deferred.
        harness = """## Coverage Plan

TestCategoryGap: category=unit reason=token_budget reqs=FR-001

## Files

### File: tests/community/test_forum.py
```python
def test_present(): assert False
```
"""
        task = _task("`tests/community/test_forum.py::test_absent`")
        assert _gaps(_validate_task_references(task, harness)) == [(1, "GENUINE_GAP")]

    def test_matrix_mixed_cell_keeps_both_files(self) -> None:
        # Fable #3: a `a.py::test`, `b.py` cell must decompose to BOTH files; when
        # a.py is emitted the requirement is covered even though b.py is absent.
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | `tests/unit/test_a.py::test_x`, `tests/unit/test_b.py` |

## Files

### File: tests/unit/test_a.py
```python
def test_x(): assert False
```
"""
        assert uncovered_requirements(harness) == []

    def test_matrix_unbackticked_comma_list_strips_punctuation(self) -> None:
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | tests/unit/test_a.py, tests/unit/test_b.py |

## Files

### File: tests/unit/test_a.py
```python
def test_x(): assert False
```
"""
        assert uncovered_requirements(harness) == []

    def test_h4_matrix_heading_still_parses(self) -> None:
        # Fable #10: `#### Requirement-to-Test Matrix` passes the substring section
        # gate; the body extractor must find it too (not silently disable).
        harness = _matrix_harness("`tests/unit/test_missing.py`", matrix_hashes="####")
        assert uncovered_requirements(harness) == ["FR-001"]

    def test_bare_matrix_filename_surfaces_a_genuine_hole(self) -> None:
        # Fable #5: a bare (dir-less) matrix filename that is never emitted is a
        # real gap and must surface (it showed nowhere before).
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | `test_billing.py` |

## Files
"""
        assert uncovered_requirements(harness) == ["FR-001"]

    def test_bare_matrix_filename_matches_dir_qualified_emission(self) -> None:
        # ...but the same bare filename, when emitted under a directory, is COVERED
        # (basename match) — never a phantom gap.
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | `test_billing.py` |

## Files

### File: tests/unit/test_billing.py
```python
def test_charge(): assert False
```
"""
        assert uncovered_requirements(harness) == []

    def test_nested_tree_leaf_is_promised_and_basename_matched(self) -> None:
        # Fable #8: a nested tree renders leaves as bare names once branch glyphs
        # are stripped. They must be picked up (promised) AND basename-matched to
        # emitted headings so Prong-A never regenerates an existing file.
        harness = """## File Tree
```
tests/
├── unit/
│   ├── test_billing.py
│   └── conftest.py
```

## Files

### File: tests/unit/test_billing.py
```python
def test_charge(): assert False
```
"""
        assert "test_billing.py" in harness_file_tree_paths(harness)
        assert "conftest.py" in harness_file_tree_paths(harness)
        # test_billing.py is emitted (basename) -> only conftest.py is missing.
        missing, total = missing_harness_files(harness)
        assert missing == ["conftest.py"]
        assert total == 2

    def test_tree_prose_line_is_not_a_path(self) -> None:
        harness = """## File Tree
```
tests/unit/test_a.py
see the notes.md file for details
```

## Files
"""
        paths = harness_file_tree_paths(harness)
        assert "tests/unit/test_a.py" in paths
        assert all(" " not in p for p in paths)

    def test_noop_merge_returns_existing_unchanged(self) -> None:
        # Fable #7 (unit half): a patch of only already-present / truncated blocks
        # merges nothing, so the caller can detect the no-op and refund.
        existing = (
            "## Files\n\n### File: tests/unit/test_a.py\n"
            "```python\ndef test_x(): assert False\n```"
        )
        # Re-emitting the same file (dup) -> nothing new.
        dup_patch = (
            "### File: tests/unit/test_a.py\n"
            "```python\ndef test_x(): assert True\n```"
        )
        assert _merge_harness_patch(existing, dup_patch) == existing
        # A truncated (unbalanced fence) trailing block -> rejected -> nothing new.
        truncated = "### File: tests/unit/test_b.py\n```python\ndef test_y():"
        assert _merge_harness_patch(existing, truncated) == existing


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


class TestFableVerifyRound3:
    """Regression pins for the Round-2 (verify) adversarial review's findings.

    Numbered V1..V7 to match the verify report. The over-suppression cases (V1,
    V2) and the false-positive cases (V3, V4) are the load-bearing ones — they
    protect the primary directive (minimise genuine lack of tests, never a paid
    false alarm).
    """

    def test_v2_empty_fenced_file_is_genuine_not_unverified(self) -> None:
        # V2: files_with_body is recorded on the first CONTENT line inside the
        # fence, not at the opener. An empty ```lang```` block is positive
        # evidence the promised file has no body -> GENUINE regardless of a
        # non-.py extension, never the reassuring UNVERIFIED.
        harness = "## Files\n\n### File: tests/auth.spec.ts\n```ts\n```\n"
        assert _gaps(
            _validate_task_references(
                _task("`tests/auth.spec.ts::loginRedirect`"), harness
            )
        ) == [(1, "GENUINE_GAP")]

    def test_v2_bodied_nonpython_fence_still_unverified(self) -> None:
        # The other side of V2: a NON-empty non-.py fence stays UNVERIFIED — the
        # empty-fence fix must not turn every bodied file we can't parse into a
        # loud gap.
        # A body with no test construct our parser recognises (no it/describe/
        # def test), so files_with_tests excludes it but files_with_body includes
        # it -> parser-blind -> quiet UNVERIFIED, not a loud gap.
        harness = (
            "## Files\n\n### File: tests/auth.spec.ts\n"
            "```ts\nimport { setup } from './setup';\nconst base = 1;\n```\n"
        )
        assert _gaps(
            _validate_task_references(
                _task("`tests/auth.spec.ts::loginRedirect`"), harness
            )
        ) == [(1, "UNVERIFIED_COVERAGE")]

    def test_v3_pytest_default_naming_matches_dropped_category(self) -> None:
        # V3: `performance_budget` category must match the pytest-default
        # `test_performance_budget.py` (the fix #9 stem token was
        # `testperformancebudget`; contiguous sub-word joins now yield
        # `performancebudget`). A regressed match here loudly re-flags a category
        # the harness explicitly recorded as deferred.
        harness = """## Coverage Plan

TestCategoryGap: category=performance_budget reason=token_budget reqs=FR-001

## Files

### File: tests/unit/test_auth.py
```python
def test_login(): assert False
```
"""
        task = _task("`tests/test_performance_budget.py::test_p95`")
        assert _gaps(_validate_task_references(task, harness)) == [
            (1, "DEFERRED_COVERAGE")
        ]

    def test_v3_go_suffix_naming_matches_dropped_category(self) -> None:
        harness = """## Coverage Plan

TestCategoryGap: category=performance_budget reason=token_budget reqs=FR-001

## Files

### File: tests/unit/test_auth.py
```python
def test_login(): assert False
```
"""
        task = _task("`tests/performance_budget_test.go::TestP95`")
        assert _gaps(_validate_task_references(task, harness)) == [
            (1, "DEFERRED_COVERAGE")
        ]

    def test_v3_community_still_does_not_mask_a_unit_gap(self) -> None:
        # The contiguous-join widening must NOT re-introduce the substring bug:
        # no join of {community, test} equals `unit`.
        harness = """## Coverage Plan

TestCategoryGap: category=unit reason=token_budget reqs=FR-001

## Files

### File: tests/community/test_forum.py
```python
def test_present(): assert False
```
"""
        task = _task("`tests/community/test_forum.py::test_absent`")
        assert _gaps(_validate_task_references(task, harness)) == [(1, "GENUINE_GAP")]

    @pytest.mark.parametrize(
        "token",
        ["pytest.mark.slow", "pytest==7.4.0", "latest.md", "pytest.mark.perf"],
    )
    def test_v4_non_file_prose_tokens_rejected(self, token: str) -> None:
        # V4: matrix prose that merely CONTAINS "test" is not a file path. Before
        # the extension allowlist these armed the paid patch AND fed Prong-A a
        # junk filename to synthesise.
        assert _looks_like_test_file_path(token) is False

    @pytest.mark.parametrize(
        "token",
        [
            "tests/unit/auth_test.py",
            "auth_test.py",
            "login.spec.ts",
            "tests/auth_test.py::test_login",
            "internal/handler_test.go",
        ],
    )
    def test_v4_real_test_files_still_accepted(self, token: str) -> None:
        assert _looks_like_test_file_path(token) is True

    def test_v4_prose_matrix_cell_is_not_a_phantom_uncovered(self) -> None:
        # End-to-end: a deferred-note cell naming no real file must not invent an
        # uncovered requirement (which would arm the 10-credit patch).
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file | Status |
|---|---|---|---|
| NFR-002 | load | `pytest.mark.perf` deferred | (deferred) |

## Files
"""
        assert uncovered_requirements(harness) == []
        # ...and Prong-A sees no junk file to regenerate.
        missing, _total = missing_harness_files(harness)
        assert missing == []

    def test_v1_prose_only_requirement_surfaces_as_advisory(self) -> None:
        # V1: a requirement that survives traceability (its id appears in the
        # harness) but is mapped to NO test — only mentioned in a deferred prose
        # note — was invisible on every deterministic surface. Now a CoverageGap
        # advisory (`harness_requirement_not_test_mapped`).
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | `tests/test_a.py` |
| FR-002 | logout | `tests/test_b.py` |

## Coverage Plan

FR-003 is deferred to a follow-up increment.

## Files

### File: tests/test_a.py
```python
# Tests: FR-001
def test_a(): assert False
```

### File: tests/test_b.py
```python
# Tests: FR-002
def test_b(): assert False
```
"""
        deps = {"spec": "FR-001 FR-002 FR-003"}
        issues = _harness_issues(harness, deps)
        mapped_issue = next(
            i for i in issues if i.code == "harness_requirement_not_test_mapped"
        )
        assert mapped_issue.reference == "FR-003"

    def test_v1_test_present_without_matrix_row_is_not_flagged(self) -> None:
        # The V1 false-positive guard: an id mapped via a File block's `# Tests:`
        # comment (a real test) but absent from the matrix must NOT be flagged —
        # a missing matrix row is not a missing test.
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | `tests/test_a.py` |

## Files

### File: tests/test_a.py
```python
# Tests: FR-001
def test_a(): assert False
```

### File: tests/test_b.py
```python
# Tests: FR-002
def test_b(): assert False
```
"""
        deps = {"spec": "FR-001 FR-002"}
        assert "harness_requirement_not_test_mapped" not in _codes(
            _harness_issues(harness, deps)
        )

    def test_v1_absent_id_not_double_reported(self) -> None:
        # An id absent ENTIRELY is `_traceability_issues`' job; the new advisory
        # must not also fire (it keys on present-but-unmapped only).
        harness = """## Requirement-to-Test Matrix

| Source ID | Behaviour | Test file |
|---|---|---|
| FR-001 | login | `tests/test_a.py` |

## Files

### File: tests/test_a.py
```python
# Tests: FR-001
def test_a(): assert False
```
"""
        deps = {"spec": "FR-001 FR-002"}
        assert "harness_requirement_not_test_mapped" not in _codes(
            _harness_issues(harness, deps)
        )

    def test_v1_missing_matrix_section_does_not_false_positive(self) -> None:
        # The guard against section-name fragility: if the matrix section did not
        # parse (empty), the advisory is skipped rather than flagging every id.
        harness = """## Test Plan

FR-001 and FR-002 are covered.

## Files

### File: tests/test_a.py
```python
def test_a(): assert False
```
"""
        deps = {"spec": "FR-001 FR-002"}
        assert "harness_requirement_not_test_mapped" not in _codes(
            _harness_issues(harness, deps)
        )

    def test_v5_tab_indented_backticks_do_not_close_fence(self) -> None:
        # V5: a tab-indented ``` (Go's convention inside a tab-indented raw
        # string) is 4 columns of indent -> fence CONTENT, not a close. Before the
        # fix it truncated the scan and `TestAfter` (defined later) went invisible.
        harness = (
            "## Files\n\n"
            "### File: tests/doc_test.go\n"
            "```go\n"
            "func TestBefore(t *testing.T) {\n"
            "\tmd := `\n"
            "\t```\n"
            "\theading\n"
            "\t```\n"
            "\t`\n"
            "\t_ = md\n"
            "}\n\n"
            "func TestAfter(t *testing.T) {}\n"
            "```\n"
        )
        refs = _harness_ref_index(harness)
        assert "TestAfter" in refs.known_refs
        assert (
            _validate_task_references(_task("`tests/doc_test.go::TestAfter`"), harness)
            == []
        )

    @pytest.mark.asyncio
    async def test_v7_repair_pass_runs_under_repair_operation(self) -> None:
        # V7: the Prong-A repair stream must attribute its cost to
        # harness.repair_files (not the passed adapter's harness.generate) and
        # restore the label afterward, so harness.generate percentiles stay clean.
        from services.pipeline.stage_manager import StageManager

        seen: dict[str, str | None] = {}

        class _OpAdapter:
            _operation = "harness.generate"
            last_generation_id = "gen-fake"

            async def stream(self, system, user, *, max_tokens):  # noqa: ANN001, ARG002
                seen["during"] = self._operation
                yield (
                    "### File: tests/unit/test_b.py\n"
                    "```python\ndef test_b(): assert False\n```\n"
                )

        harness = (
            "## File Tree\n```\ntests/unit/test_a.py\ntests/unit/test_b.py\n```\n\n"
            "## Files\n\n### File: tests/unit/test_a.py\n"
            "```python\ndef test_a(): assert False\n```\n"
        )
        adapter = _OpAdapter()
        await StageManager()._autocomplete_missing_harness_files(
            artifact=harness, adapter=adapter, route=_route()
        )
        assert seen["during"] == "harness.repair_files"
        assert adapter._operation == "harness.generate"
