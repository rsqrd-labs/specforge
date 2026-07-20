"""Boundary-local sanitize of PDF-rendered HTML (stage screens audit F1 / §1.0).

Stage content is stored raw (the at-rest bleach was removed as part of the
content-integrity fix); python-markdown passes inline HTML through verbatim.
These tests pin the PDF boundary's own guard: script/style payloads and event
handlers never reach WeasyPrint, while code spans, fences, codehilite classes,
and table alignment survive intact.

Deliberately a separate module from test_pdf_export_service.py: that suite is
skipped wholesale when the WeasyPrint native libs are absent, but the sanitize
path is pure Python and must be exercised everywhere.
"""

from __future__ import annotations

from services.pipeline.pdf_export_service import (
    _render_markdown_to_html,
    _sanitize_rendered_html,
)


def test_script_block_is_removed_with_its_payload() -> None:
    # bleach strip=True alone keeps a stripped element's text children; the
    # pre-pass must drop script/style with their contents so the payload never
    # appears as visible PDF text either.
    out = _render_markdown_to_html("Before <script>alert(1)</script> after.")
    assert "<script" not in out
    assert "alert(1)" not in out
    assert "Before" in out and "after." in out


def test_style_block_is_removed_with_its_payload() -> None:
    out = _render_markdown_to_html("Text <style>body { display: none; }</style> more.")
    assert "<style" not in out
    assert "display: none" not in out


def test_event_handler_attributes_are_stripped() -> None:
    out = _render_markdown_to_html(
        'Click <b onclick="x()">bold</b> and <img src="https://e/x" onerror="y()">.'
    )
    assert "onclick" not in out
    assert "onerror" not in out


def test_html_comments_are_stripped() -> None:
    out = _render_markdown_to_html("Visible <!-- smuggled directive --> text.")
    assert "smuggled" not in out


def test_javascript_href_is_neutralised() -> None:
    out = _render_markdown_to_html("[click](javascript:alert(1))")
    assert "javascript:" not in out


def test_html_data_url_href_is_removed() -> None:
    out = _sanitize_rendered_html(
        '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">'
        "click</a>"
    )
    assert "data:" not in out
    assert "<a>click</a>" in out


def test_base64_raster_data_image_is_allowed() -> None:
    out = _sanitize_rendered_html(
        '<img src="data:image/png;base64,iVBORw0KGgo=" alt="diagram">'
    )
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in out


def test_active_or_non_image_data_sources_are_removed() -> None:
    for source in (
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "data:text/html;base64,PGgxPmJvb208L2gxPg==",
    ):
        out = _sanitize_rendered_html(f'<img src="{source}" alt="x">')
        assert "data:" not in out


def test_inline_and_fenced_code_survive_exactly() -> None:
    # The whole point of sanitizing the *rendered* HTML instead of the markdown
    # source: by conversion time code is already escaped, so the allowlist
    # clean preserves it. `List<String>` was destroyed by the old at-rest pass.
    out = _render_markdown_to_html(
        "Use `List<String>` here.\n\n```python\na < b and c & d\n```\n"
    )
    assert "List&lt;String&gt;" in out
    assert "&lt;" in out and "&amp;" in out
    assert "codehilite" in out


def test_table_alignment_and_heading_ids_survive() -> None:
    out = _render_markdown_to_html("# Heading\n\n| A | B |\n|:--|--:|\n| 1 | 2 |\n")
    assert 'id="heading"' in out
    assert "text-align: right" in out
    assert "<table>" in out


def test_disallowed_structural_tags_are_stripped() -> None:
    out = _render_markdown_to_html(
        '<iframe src="https://evil.example"></iframe>\n\n'
        '<form action="https://evil.example"><input name="q"></form>\n'
    )
    assert "<iframe" not in out
    assert "<form" not in out
    assert "<input" not in out


def test_empty_input_renders_empty() -> None:
    assert _render_markdown_to_html("") == ""


def test_sanitizer_is_idempotent_on_clean_output() -> None:
    # Running the boundary guard twice must not degrade already-clean HTML —
    # protects against double-encoding of the escaped code content.
    once = _render_markdown_to_html(
        "Use `List<String>` and a fence:\n\n```\nx < y\n```\n"
    )
    assert _sanitize_rendered_html(once) == once
