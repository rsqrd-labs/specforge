from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from test_storyboard_router import (
    _STORYBOARD_ID,
    _USER_ID,
    _app,
    _client,
    _storyboard,
)

import middleware.csrf as csrf_module
from services.pipeline import storyboard_public_service, storyboard_renderer


def test_public_allow_list_redacts_private_storyboard_material_by_default() -> None:
    sb = _storyboard(status="ready", public_share_enabled=True, public_share_slug="x")
    sb.content_json = {
        "title": "Launch Keynote",
        "theme": {
            "palette": ["#8f4e00", "#a1385f", "#565e74"],
            "typography": "sans",
            "motif": "motif",
            "transition_style": "cut",
            "diagram_style": "cards",
        },
        "sections": [
            {
                "id": "opening-thesis",
                "title": "Opening Thesis",
                "slides": [
                    {
                        "id": "slide-1",
                        "type": "hero",
                        "headline": "Private claim",
                        "visible_text": "Public promise",
                        "visual": {"kind": "hero"},
                        "speaker_notes_ref": "slide-1",
                        "sources": ["SPEC"],
                    }
                ],
            }
        ],
        "diagrams": [
            {
                "id": "diagram-1",
                "type": "architecture_reveal",
                "layers": [
                    {
                        "id": "client",
                        "kind": "client",
                        "label": "Client",
                        "summary": "Client layer",
                        "source_refs": [
                            {
                                "source": "PLAN",
                                "source_id": "PLAN:secret-section",
                                "excerpt": "private architecture excerpt",
                            }
                        ],
                    }
                ],
            }
        ],
        "source_map": {
            "slide-1.claim": [
                {
                    "source": "SPEC",
                    "source_id": "SPEC:secret",
                    "excerpt": "private source excerpt",
                }
            ]
        },
        "notes": {
            "slide-1": {
                "slide_id": "slide-1",
                "talk_track": "private speaker note",
                "transition": "private transition",
                "timing_seconds": 30,
                "pause_cue": "private pause",
                "demo_cue": "private demo",
                "backup_points": ["private backup"],
            }
        },
        "demo_script_md": "public demo script",
        "technical_appendix_md": "private appendix",
    }

    view = storyboard_public_service.build_public_view(sb)
    blob = view.model_dump_json()

    assert set(view.model_dump().keys()) == {
        "title",
        "presentation",
        "permissions",
        "downloads",
        "shared_at",
    }
    assert "private speaker note" not in blob
    assert "private source excerpt" not in blob
    assert "PLAN:secret-section" not in blob
    assert "SPEC:secret" not in blob
    assert "private appendix" not in blob
    assert "source_stage_version_ids" not in blob


@pytest.mark.asyncio
async def test_storyboard_mutations_require_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        csrf_module,
        "decode_access_token_claims",
        lambda token: (
            {"sub": str(_USER_ID), "type": "access"} if token == "valid-token" else None
        ),
    )
    app = _app(db_value=_storyboard(status="ready"))

    async with await _client(app) as client:
        response = await client.delete(
            f"/storyboards/{_STORYBOARD_ID}/share",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_non_owner_storyboard_lookup_is_404() -> None:
    app = _app(db_value=None)

    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_storyboard_routes_are_read_only_and_security_headered() -> None:
    app = _app(db_value=None, override_user=False)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        get_response = await client.get("/storyboards/public/missing")
        post_response = await client.post("/storyboards/public/missing")

    assert get_response.status_code == 404
    assert get_response.headers["X-Robots-Tag"] == "noindex, nofollow"
    csp = get_response.headers["Content-Security-Policy"]
    assert "script-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert post_response.status_code in {404, 405}


@pytest.mark.asyncio
async def test_public_html_download_is_not_exposed() -> None:
    sb = _storyboard(status="ready", public_share_enabled=True, public_share_slug="x")
    app = _app(db_value=sb, override_user=False)

    async with await _client(app) as client:
        response = await client.get("/storyboards/public/x/download/html")

    assert response.status_code == 404
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_storyboard_renderer_defuses_script_and_remote_asset_injection() -> None:
    payload = {
        "title": 'Launch <script>alert("x")</script>',
        "theme": {
            "palette": ["#abc123", "#def456"],
            "motif": '<img src="https://evil.example/pixel.png">',
        },
        "sections": [
            {
                "title": "Opening Thesis",
                "slides": [
                    {
                        "headline": '<iframe src="https://evil.example"></iframe>',
                        "visible_text": '<a href="javascript:alert(1)">bad</a>',
                        "visual": {
                            "kind": "hero",
                            "asset": "https://evil.example/tracker.svg",
                        },
                        "sources": ["SPEC"],
                    }
                ],
            }
        ],
        "diagrams": [
            {
                "type": "architecture_reveal",
                "layers": [
                    {
                        "kind": "client",
                        "label": '<object data="https://evil.example"></object>',
                        "summary": '<script src="https://evil.example/x.js"></script>',
                    }
                ],
            }
        ],
    }

    html = storyboard_renderer.render_deck_html(payload, "Acme")
    lowered = html.lower()

    assert "<script" not in lowered
    assert "<iframe" not in lowered
    assert "<object" not in lowered
    assert "javascript:" not in lowered
    assert "evil.example" not in html


def test_storyboard_logging_does_not_reference_generated_content_fields() -> None:
    service_dir = Path(__file__).resolve().parents[1] / "services" / "pipeline"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            service_dir / "storyboard_service.py",
            service_dir / "storyboard_public_service.py",
            service_dir / "storyboard_renderer.py",
        ]
    )
    lines = source.splitlines()
    log_blocks: list[str] = []
    for index, line in enumerate(lines):
        if "logger." in line or "structlog" in line:
            log_blocks.append("\n".join(lines[index : index + 12]))
    logs = "\n".join(log_blocks)

    for forbidden in [
        "speaker_notes_md",
        "technical_appendix_md",
        "demo_script_md",
        "source_excerpt",
        "content_json",
        "raw_generated",
        "prompt",
        "credit_balance",
    ]:
        assert forbidden not in logs
