from __future__ import annotations

from services.security.sanitizer import sanitize_text


def test_sanitize_text_strips_script_tags_and_contents() -> None:
    assert sanitize_text("<script>alert('xss')</script>hello") == "hello"


def test_sanitize_text_leaves_plain_text_unchanged() -> None:
    text = "Build a task management SaaS with recurring billing."
    assert sanitize_text(text) == text


def test_sanitize_text_strips_nested_html_tags() -> None:
    assert sanitize_text("<b><i>text</i></b>") == "text"


def test_sanitize_text_strips_attributes() -> None:
    assert sanitize_text('<a href="javascript:alert(1)">link</a>') == "link"


# ---------------------------------------------------------------------------
# F7 (scalability audit P2): sanitize_text_async parity — the offloaded pass
# must be byte-identical to the sync one on both the inline and the pool path.
# ---------------------------------------------------------------------------


async def test_sanitize_text_async_matches_sync_inline_path() -> None:
    from services.security.sanitizer import sanitize_text_async

    text = "<script>alert('x')</script>plain <b>bold</b>"
    assert await sanitize_text_async(text) == sanitize_text(text)


async def test_sanitize_text_async_matches_sync_on_pool_path(monkeypatch) -> None:
    from config import settings
    from services.security.sanitizer import sanitize_text_async

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    text = ("<i>chunk</i> with <script>bad()</script> markup\n" * 500).strip()
    assert await sanitize_text_async(text) == sanitize_text(text)
