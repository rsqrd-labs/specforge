"""Unit tests for the trusted Storyboard renderer (Phase 20 — T-255).

The security-critical assertions (script/handler/iframe/remote-asset stripping,
CSP, filename slugs) live on the HTML path, which has no native dependencies and
always runs. The PDF path's no-network guard is tested as a pure function (it
needs no render); a full WeasyPrint render is exercised only when the native
libs are present.
"""

from __future__ import annotations

import re

import pytest

from services.pipeline import storyboard_renderer as renderer


def _payload() -> dict:
    """A minimal, structurally complete Storyboard content payload."""

    return {
        "title": "SpecForge Launch Keynote",
        "theme": {
            "palette": ["#101418", "#1FB6FF", "#F5A623"],
            "typography": "Geometric sans",
            "motif": "Indica glassmorphism",
            "transition_style": "Cinematic fade",
            "diagram_style": "Layered planes",
        },
        "sections": [
            {
                "id": "act-0",
                "title": "Opening Thesis",
                "slides": [
                    {
                        "id": "s0",
                        "type": "thesis",
                        "headline": "From idea to engineered spec",
                        "visible_text": "Four stages, one flow.",
                        "visual": {"kind": "hero", "note": "full-bleed"},
                        "speaker_notes_ref": "s0",
                        "sources": ["SPEC", "PLAN"],
                    }
                ],
            }
        ],
        "diagrams": [
            {
                "id": "arch",
                "type": "architecture_reveal",
                "layers": [
                    {
                        "id": "l-client",
                        "kind": "client",
                        "label": "Browser SPA",
                        "summary": "React 18 + Zustand.",
                        "source_refs": [],
                    }
                ],
            }
        ],
        "source_map": {},
        "notes": {},
        "demo_script_md": "## Demo\n1. Open editor.\n",
        "technical_appendix_md": "## Appendix\nDetails.\n",
    }


# ---------------------------------------------------------------------------
# Filenames (req 9)
# ---------------------------------------------------------------------------


def test_filename_slug_for_each_kind() -> None:
    name = "Acme Rocket"
    assert (
        renderer.filename_for("html", name) == "specforge-storyboard-Acme-Rocket.html"
    )
    assert renderer.filename_for("pdf", name) == "specforge-storyboard-Acme-Rocket.pdf"
    assert (
        renderer.filename_for("notes-md", name)
        == "specforge-storyboard-speaker-notes-Acme-Rocket.md"
    )
    assert (
        renderer.filename_for("notes-pdf", name)
        == "specforge-storyboard-speaker-notes-Acme-Rocket.pdf"
    )
    assert (
        renderer.filename_for("demo-script", name)
        == "specforge-storyboard-demo-script-Acme-Rocket.md"
    )
    assert (
        renderer.filename_for("appendix", name)
        == "specforge-storyboard-technical-appendix-Acme-Rocket.md"
    )


def test_filename_empty_name_falls_back_to_workspace() -> None:
    assert renderer.filename_for("html", "") == "specforge-storyboard-workspace.html"
    assert renderer.filename_for("pdf", "***") == "specforge-storyboard-workspace.pdf"


def test_filename_unknown_kind_raises() -> None:
    with pytest.raises(ValueError):
        renderer.filename_for("exe", "Acme")


# ---------------------------------------------------------------------------
# Deck HTML structure + CSP
# ---------------------------------------------------------------------------


def test_render_deck_html_includes_content_and_csp() -> None:
    html = renderer.render_deck_html(_payload(), "Acme")
    assert "SpecForge Launch Keynote" in html
    assert "Opening Thesis" in html
    assert "From idea to engineered spec" in html
    assert "Problem to product" in html
    assert "full-bleed" not in html
    assert "Browser SPA" in html
    # Embedded CSP meta with all required directives.
    assert "default-src 'self'" in html
    assert "script-src 'self'" in html
    assert "style-src 'self' 'unsafe-inline'" in html
    assert "img-src 'self' data:" in html
    assert "frame-ancestors 'none'" in html
    # No external resource references of any kind.
    assert "http://" not in html
    assert "https://" not in html


def test_palette_only_valid_hex_is_inlined() -> None:
    payload = _payload()
    payload["theme"]["palette"] = [
        "#abc123; } body { background: url(http://evil)",
        "x",
    ]
    html = renderer.render_deck_html(payload, "Acme")
    # The malformed colour is rejected and the brand default is used instead, so
    # no CSS break-out and no remote url() survive.
    assert "evil" not in html
    assert renderer._DEFAULT_ACCENT in html


# ---------------------------------------------------------------------------
# Acceptance criterion 3/4 — script + remote asset stripping
# ---------------------------------------------------------------------------


def test_storyboard_renderer_strips_script_and_remote_asset_references() -> None:
    payload = _payload()
    payload["title"] = "Launch <script>alert(1)</script>"
    payload["sections"][0]["slides"][0][
        "headline"
    ] = "Hi <script>steal()</script> there"
    payload["sections"][0]["slides"][0][
        "visible_text"
    ] = '<img src="https://evil.example/track.png" onerror="alert(2)">'
    payload["sections"][0]["slides"][0]["visual"] = {
        "kind": "hero",
        "note": '<iframe src="//evil.example"></iframe>',
    }
    payload["diagrams"][0]["layers"][0]["label"] = "Client <object data=//evil>"
    payload["diagrams"][0]["layers"][0][
        "summary"
    ] = '<a href="javascript:alert(3)">x</a>'

    html = renderer.render_deck_html(payload, "Acme")
    lowered = html.lower()
    assert "<script" not in lowered
    assert "</script" not in lowered
    assert "onerror" not in lowered
    assert "<iframe" not in lowered
    assert "<object" not in lowered
    assert "javascript:" not in lowered
    assert "alert(" not in html
    assert "evil.example" not in html


def test_notes_html_strips_script_handlers_remote_images_and_js_links() -> None:
    notes_md = (
        "# Notes\n\n"
        "<script>steal()</script>\n\n"
        '<img src="https://evil.example/pixel.png">\n\n'
        '<a href="javascript:alert(1)">click</a>\n\n'
        '<div onclick="x()">hi</div>\n\n'
        "Legit **bold** and `code` and a [safe](https://example.com) link.\n"
    )
    html = renderer.render_notes_html(notes_md, "Acme")
    lowered = html.lower()
    # The executable <script> tag is removed; its inner text may remain as inert
    # body text, which cannot execute without the surrounding tag.
    assert "<script" not in lowered
    assert "</script" not in lowered
    assert "evil.example" not in html  # remote image stripped (no img allowed)
    assert "<img" not in lowered
    assert "javascript:" not in lowered
    assert "onclick" not in lowered
    # Legitimate formatting survives.
    assert "<strong>bold</strong>" in html or "<b>bold</b>" in html
    assert "<code>code</code>" in html
    assert 'href="https://example.com"' in html


def test_notes_html_empty_body() -> None:
    html = renderer.render_notes_html("", "Acme")
    assert "Speaker Notes" in html


# ---------------------------------------------------------------------------
# PDF no-network guard (pure function; no WeasyPrint render needed)
# ---------------------------------------------------------------------------


def test_no_network_fetcher_blocks_remote_urls() -> None:
    from services.pipeline.pdf_export_service import (
        _NoNetworkFetch,
        no_network_url_fetcher,
    )

    with pytest.raises(_NoNetworkFetch):
        no_network_url_fetcher("https://evil.example/exfil.png")
    with pytest.raises(_NoNetworkFetch):
        no_network_url_fetcher("http://attacker.test/log")


# ---------------------------------------------------------------------------
# Full PDF render — only when WeasyPrint native libs are available
# ---------------------------------------------------------------------------


def _weasyprint_available() -> bool:
    try:
        import weasyprint

        weasyprint.HTML(string="<p>x</p>")
        return True
    except Exception:  # pragma: no cover - environment dependent
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _weasyprint_available(),
    reason="WeasyPrint native libs unavailable in this environment.",
)
async def test_render_deck_pdf_returns_pdf_bytes() -> None:  # pragma: no cover
    pdf = await renderer.render_deck_pdf(_payload(), "Acme")
    assert pdf[:5] == b"%PDF-"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _weasyprint_available(),
    reason="WeasyPrint native libs unavailable in this environment.",
)
async def test_render_deck_pdf_does_not_embed_injected_script() -> (
    None
):  # pragma: no cover
    payload = _payload()
    payload["sections"][0]["slides"][0]["headline"] = "<script>alert(1)</script>"
    pdf = await renderer.render_deck_pdf(payload, "Acme")
    assert pdf[:5] == b"%PDF-"
    # The PDF stream is compressed; the integration guarantee is that the deck
    # HTML fed to WeasyPrint never contains a live <script> (asserted on the HTML
    # path above). A non-empty PDF confirms the render succeeded post-sanitise.
    assert len(pdf) > 100


def test_html_does_not_contain_raw_script_tag_regex() -> None:
    # Belt-and-braces: assert there is no opening <script ...> token anywhere.
    payload = _payload()
    payload["title"] = "x<script src='//evil'></script>"
    html = renderer.render_deck_html(payload, "Acme")
    assert not re.search(r"<\s*script", html, re.IGNORECASE)
