import pytest

from services.pipeline.diff_engine import apply_diff, compute_diff


def test_compute_diff_returns_unified_diff() -> None:
    diff = compute_diff("hello world", "hello there")
    assert "---" in diff
    assert "+++" in diff
    assert "-hello world" in diff
    assert "+hello there" in diff


def test_apply_diff_replaces_selected_text() -> None:
    original = "The quick brown fox jumps over the lazy dog"
    start = original.index("brown fox")
    end = start + len("brown fox")
    result = apply_diff(original, start, end, "red cat")
    assert result == "The quick red cat jumps over the lazy dog"


def test_apply_diff_multiline() -> None:
    original = "line one\nline two\nline three"
    start = original.index("line two")
    end = start + len("line two")
    result = apply_diff(original, start, end, "line TWO")
    assert result == "line one\nline TWO\nline three"


def test_apply_diff_second_occurrence_with_explicit_positions() -> None:
    original = "foo bar foo bar"
    # Replace the SECOND "foo", not the first
    second_start = original.index("foo", 8)
    second_end = second_start + len("foo")
    result = apply_diff(original, second_start, second_end, "baz")
    assert result == "foo bar baz bar"
