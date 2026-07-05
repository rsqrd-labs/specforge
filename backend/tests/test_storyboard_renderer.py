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
            },
            {
                "id": "act-3",
                "title": "Technical Architecture",
                "slides": [
                    {
                        "id": "s-arch",
                        "type": "architecture",
                        "headline": "System architecture",
                        "visible_text": "Eight planes, one stack.",
                        "visual": {"kind": "architecture"},
                        "speaker_notes_ref": "s-arch",
                        "sources": ["PLAN", "TASKS"],
                    }
                ],
            },
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
        "source_map": {
            "s0": [
                {
                    "source": "SPEC",
                    "source_id": "SPEC:overview",
                    "excerpt": "Four stages, one flow.",
                }
            ]
        },
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
    assert "squirrel-brand-mark" in html
    assert "Opening Thesis" in html
    assert "From idea to engineered spec" in html
    # The visual is drawn from the slide's own visual.kind (a hero -> "Vision"
    # label), never from raw source ids or arbitrary descriptor text dumped onto
    # the slide. Source evidence lives in the live deck's SourceLayer overlay
    # and the technical appendix, never on the printed pages.
    assert "Vision" in html
    assert "SPEC:overview" not in html
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


def test_visual_descriptors_drive_the_slide_panel() -> None:
    payload = _payload()
    payload["sections"][0]["slides"][0]["visual"] = {
        "kind": "metric",
        "value": "4 stages",
        "label": "Spec to Tasks",
    }
    html = renderer.render_deck_html(payload, "Acme")
    assert "Key metric" in html  # metric visual label
    assert "4 stages" in html
    assert "Spec to Tasks" in html

    payload["sections"][0]["slides"][0]["visual"] = {
        "kind": "bullets",
        "points": ["Stream every stage", "Diff and version", "Human review gate"],
    }
    html = renderer.render_deck_html(payload, "Acme")
    assert "Highlights" in html  # bullets visual label
    assert "Stream every stage" in html
    assert "Human review gate" in html


def test_arch_slide_renders_full_svg_topology() -> None:
    html = renderer.render_deck_html(_payload(), "Acme")
    # The architecture slide draws an inline SVG topology graph, not a card grid.
    assert '<svg class="arch-topology"' in html
    assert 'viewBox="0 0 960 600"' in html
    # All six connectable planes are drawn as box nodes (kind labels, uppercased).
    for kind in renderer._ARCH_BOX_KINDS:
        assert f">{kind.upper()}<" in html
    # The emitted client layer keeps its model label; omitted planes fall back to
    # their canonical copy so the system diagram is complete (eight planes total).
    assert "Browser SPA" in html
    assert "Trust boundaries" in html  # trust region (not emitted -> canonical)
    assert "Failure and recovery paths" in html  # recovery region (canonical)
    # Five directed edges, each with an arrowhead polygon.
    assert html.count("<polygon points=") == len(renderer._ARCH_EDGES) == 5
    # Static topology: no animation, no remote/script refs.
    assert "http://" not in html
    assert "https://" not in html


def test_arch_topology_mirrors_the_frontend_constants() -> None:
    # Parity guard: the offline topology must match the live deck's node/edge set
    # (ArchitectureReveal.tsx). These are the closed enum and canonical edges.
    assert renderer._ARCH_BOX_KINDS == (
        "client",
        "frontend",
        "api",
        "data",
        "llm",
        "integrations",
    )
    assert renderer._ARCH_EDGES == (
        ("client", "frontend"),
        ("frontend", "api"),
        ("api", "data"),
        ("api", "llm"),
        ("api", "integrations"),
    )


def test_arch_topology_tolerates_unknown_group_kind() -> None:
    payload = _payload()
    payload["diagrams"][0]["layers"].append(
        {
            "id": "l-group",
            "kind": "group",
            "label": "Billing subsystem",
            "summary": "Lemon Squeezy worker.",
            "source_refs": [],
        }
    )
    html = renderer.render_deck_html(payload, "Acme")
    # The unknown kind renders as an unconnected annotation, never crashing, and
    # never adds a sixth box-node kind or an extra edge.
    assert "Billing subsystem" in html
    assert html.count("<polygon points=") == 5


def test_arch_topology_absent_without_architecture_diagram() -> None:
    payload = _payload()
    payload["diagrams"] = []
    html = renderer.render_deck_html(payload, "Acme")
    # With no architecture_reveal diagram the arch slide falls back to the normal
    # visual panel — no topology SVG is emitted.
    assert '<svg class="arch-topology"' not in html


def test_wrap_label_caps_lines_and_truncates_overflow() -> None:
    assert renderer._wrap_label("Browser SPA") == ["Browser SPA"]
    assert renderer._wrap_label("") == []
    wrapped = renderer._wrap_label(
        "API gateway and backend services orchestration layer everywhere"
    )
    assert len(wrapped) <= 2
    assert wrapped[-1].endswith("…")
    assert all(len(line) <= 20 for line in wrapped)


def test_each_act_inlines_a_distinct_palette_accent() -> None:
    payload = _payload()
    palette = ["#112233", "#445566", "#778899"]
    payload["theme"]["palette"] = palette
    # Two acts so per-act rotation picks up two different palette colours.
    payload["sections"].append(
        {
            "id": "act-1",
            "title": "Product Vision",
            "slides": [
                {
                    "id": "s1",
                    "type": "product",
                    "headline": "Second act",
                    "visible_text": "",
                    "visual": {"kind": "product"},
                    "speaker_notes_ref": "s1",
                    "sources": ["SPEC"],
                }
            ],
        }
    )
    html = renderer.render_deck_html(payload, "Acme")
    assert "--a: #112233" in html  # act 1 accent
    assert "--a: #445566" in html  # act 2 accent rotated forward


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
# Citations stay off presentation surfaces (output-quality plan P1.1)
# ---------------------------------------------------------------------------


def test_no_source_citations_on_any_printed_page() -> None:
    # The payload carries slide `sources` (they feed SourceLayer and grounding
    # validation), but the printed deck must never show the audit trail: no
    # chip markup and no SPEC/PLAN/HARNESS/TASKS badge text on any page.
    html = renderer.render_deck_html(_payload(), "Acme")
    assert "chip" not in html
    assert not re.search(r">\s*(SPEC|PLAN|HARNESS|TASKS)\s*<", html)


# ---------------------------------------------------------------------------
# Max-cap fixture + render clamps (output-quality plan P1.3 / P1.4)
# ---------------------------------------------------------------------------

# 18 words / 140 characters — both headline maxima (15×7 + 3×6 chars + 17
# spaces). Mirrors MAX_CAP_HEADLINE in frontend testPayload.ts.
_MAX_CAP_HEADLINE = " ".join(["maximal"] * 15 + ["stress"] * 3)
# 45 words / 359 characters (≤ the 360-char visible_text cap).
_MAX_CAP_VISIBLE_TEXT = " ".join(["connect"] * 45)
# Five points of eight words each.
_MAX_CAP_POINTS = [" ".join([f"signal{i}"] * 8) for i in range(5)]
# 120 characters — the diagram-layer label maximum.
_MAX_CAP_LAYER_LABEL = " ".join(["maximal"] * 15)
# 139 characters — at the 140-char title render cap, distinct from the headline
# so the headline-clamp assertions cannot be satisfied by the cover title.
_MAX_CAP_TITLE = " ".join(["titleword"] * 14)

_MAX_CAP_ACTS = (
    "Opening Thesis",
    "Product Vision",
    "Product Walkthrough",
    "Technical Architecture",
    "Trust, Security, Reliability",
    "Launch Close",
)
_MAX_CAP_LAYER_KINDS = (
    "client",
    "frontend",
    "api",
    "data",
    "llm",
    "integrations",
    "trust",
    "recovery",
)


def _max_cap_payload() -> dict:
    """A deck at the generation-schema maxima — the layout regression anchor."""

    sections = []
    for index, title in enumerate(_MAX_CAP_ACTS):
        act_id = f"act-{index}"
        is_arch = title == "Technical Architecture"
        sections.append(
            {
                "id": act_id,
                "title": title,
                "slides": [
                    {
                        "id": f"{act_id}-a",
                        "type": "architecture" if is_arch else "hero",
                        "headline": _MAX_CAP_HEADLINE,
                        "visible_text": _MAX_CAP_VISIBLE_TEXT,
                        "visual": {"kind": "bullets", "points": _MAX_CAP_POINTS},
                        "speaker_notes_ref": f"{act_id}-a",
                        "sources": ["SPEC", "PLAN", "HARNESS", "TASKS"],
                    },
                    {
                        "id": f"{act_id}-b",
                        "type": "product",
                        "headline": _MAX_CAP_HEADLINE,
                        "visible_text": _MAX_CAP_VISIBLE_TEXT,
                        "visual": {
                            "kind": "metric",
                            "value": "99.999%",
                            "label": _MAX_CAP_POINTS[0],
                        },
                        "speaker_notes_ref": f"{act_id}-b",
                        "sources": ["SPEC", "PLAN"],
                    },
                ],
            }
        )
    payload = _payload()
    payload["title"] = _MAX_CAP_TITLE
    payload["sections"] = sections
    payload["diagrams"] = [
        {
            "id": "arch",
            "type": "architecture_reveal",
            "layers": [
                {
                    "id": f"l-{kind}",
                    "kind": kind,
                    "label": _MAX_CAP_LAYER_LABEL,
                    "summary": f"{kind} summary",
                    "source_refs": [],
                }
                for kind in _MAX_CAP_LAYER_KINDS
            ],
        }
    ]
    return payload


def test_max_cap_fixture_sits_at_the_schema_maxima() -> None:
    assert len(_MAX_CAP_HEADLINE) == 140
    assert len(_MAX_CAP_HEADLINE.split()) == 18
    assert len(_MAX_CAP_VISIBLE_TEXT) <= 360
    assert len(_MAX_CAP_VISIBLE_TEXT.split()) == 45
    assert len(_MAX_CAP_LAYER_LABEL) <= 120


def test_max_cap_deck_renders_every_page_with_render_clamps() -> None:
    html = renderer.render_deck_html(_max_cap_payload(), "Acme")

    # All twelve slides render, plus the cover.
    assert html.count('class="page ') == 13
    # The 140-char headline is clamped to the 120-char render cap + ellipsis so
    # it can never overrun the fixed page; the stored payload is untouched.
    assert _MAX_CAP_HEADLINE not in html
    clamped = _MAX_CAP_HEADLINE[:120].rstrip() + "…"
    assert clamped in html
    # visible_text sits at the schema max and renders whole, and so does the
    # cover title (139 chars, at the 140-char title render cap).
    assert _MAX_CAP_VISIBLE_TEXT in html
    assert _MAX_CAP_TITLE in html
    # No citation chips anywhere at the caps either.
    assert not re.search(r">\s*(SPEC|PLAN|HARNESS|TASKS)\s*<", html)


def test_render_clamps_bound_title_points_and_historical_overlong_text() -> None:
    payload = _max_cap_payload()
    # Historical payloads may pre-date the schema caps: a 500-char headline, a
    # 600-char visible_text, and a 300-char point must all be clamped for
    # rendering (invariant: every already-persisted Storyboard keeps rendering).
    payload["sections"][0]["slides"][0]["headline"] = "H" * 500
    payload["sections"][0]["slides"][0]["visible_text"] = "V" * 600
    payload["sections"][0]["slides"][0]["visual"] = {
        "kind": "bullets",
        "points": ["P" * 300],
    }
    html = renderer.render_deck_html(payload, "Acme")

    assert "H" * 121 not in html
    assert ("H" * 120 + "…") in html
    assert "V" * 361 not in html
    assert ("V" * 360 + "…") in html
    assert "P" * 91 not in html
    assert ("P" * 90 + "…") in html

    payload["title"] = "T" * 200
    html = renderer.render_deck_html(payload, "Acme")
    assert "T" * 141 not in html
    assert ("T" * 140 + "…") in html


def test_clamp_text_boundaries() -> None:
    assert renderer._clamp_text("short", 10) == "short"
    assert renderer._clamp_text("x" * 10, 10) == "x" * 10
    assert renderer._clamp_text("x" * 11, 10) == "x" * 10 + "…"
    # Trailing whitespace before the ellipsis is trimmed.
    assert renderer._clamp_text("word " + "y" * 10, 5) == "word…"


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
    assert "squirrel-brand-mark" in html


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
