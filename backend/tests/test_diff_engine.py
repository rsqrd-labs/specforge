from services.pipeline.diff_engine import apply_diff, compute_diff


def test_compute_diff_returns_unified_diff() -> None:
    diff = compute_diff("hello world", "hello there")
    assert "---" in diff
    assert "+++" in diff
    assert "-hello world" in diff
    assert "+hello there" in diff


def test_apply_diff_replaces_selected_text() -> None:
    original = "The quick brown fox jumps over the lazy dog"
    result = apply_diff(original, "brown fox", "red cat")
    assert result == "The quick red cat jumps over the lazy dog"


def test_apply_diff_multiline() -> None:
    original = "line one\nline two\nline three"
    result = apply_diff(original, "line two", "line TWO")
    assert result == "line one\nline TWO\nline three"


def test_apply_diff_selection_not_found_returns_original() -> None:
    original = "hello world"
    result = apply_diff(original, "does not exist", "replacement")
    assert result == original
