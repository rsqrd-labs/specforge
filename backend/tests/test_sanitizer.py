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
