from services.pipeline.diff_engine import (
    apply_diff,
    compute_diff,
    markdown_fences_balanced,
    normalize_refine_replacement,
)


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


def test_normalize_refine_replacement_strips_model_markdown_wrapper() -> None:
    replacement = "```markdown\n## Better heading\n\n- Item\n```"

    assert (
        normalize_refine_replacement("## Old heading", replacement)
        == "## Better heading\n\n- Item"
    )


def test_normalize_refine_replacement_preserves_selected_boundary_whitespace() -> None:
    selected = "\n- old bullet\n"
    replacement = " - improved bullet "

    assert (
        normalize_refine_replacement(selected, replacement) == "\n- improved bullet\n"
    )


def test_markdown_fences_balanced_detects_broken_patch() -> None:
    assert markdown_fences_balanced("before\n```python\nprint('ok')\n```\nafter")
    assert not markdown_fences_balanced("before\n```python\nprint('oops')\nafter")


# ---------------------------------------------------------------------------
# F7 (scalability audit P2): compute_diff_async parity — offloading difflib
# must be byte-identical to the sync path for any input.
# ---------------------------------------------------------------------------


async def test_compute_diff_async_matches_sync_on_pool_path(monkeypatch) -> None:
    from config import settings
    from services.pipeline.diff_engine import compute_diff, compute_diff_async

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    original = "\n".join(f"line {i}" for i in range(400))
    proposed = original.replace("line 200", "changed 200")
    assert await compute_diff_async(original, proposed) == compute_diff(
        original, proposed
    )


async def test_compute_diff_async_matches_sync_when_inline() -> None:
    from services.pipeline.diff_engine import compute_diff, compute_diff_async

    assert await compute_diff_async("a", "b") == compute_diff("a", "b")
