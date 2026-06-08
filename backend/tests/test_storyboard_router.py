"""Router contract tests for the Storyboard API (Phase 20 — T-251).

These exercise the contract: auth requirement, CSRF protection on mutations,
owner IDOR → 404, public unknown-slug → 404 with privacy headers, and download
streaming with an attachment Content-Disposition. Generation (T-254), rendered
downloads (T-255), and public sharing / allow-list view (T-256) are all wired;
the router's delegation, typed-error mapping, and public privacy posture are
asserted here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import middleware.csrf as csrf_module
from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import Storyboard, User

_USER_ID = uuid4()
_WORKSPACE_ID = uuid4()
_STORYBOARD_ID = uuid4()

_USER = User(
    id=_USER_ID,
    email="owner@example.com",
    google_id="google-owner",
    name="Owner",
    avatar_url=None,
    created_at=datetime.now(UTC),
)


class _NoopPipeline:
    def zremrangebyscore(self, *args: Any) -> "_NoopPipeline":
        return self

    def zadd(self, *args: Any) -> "_NoopPipeline":
        return self

    def zcard(self, *args: Any) -> "_NoopPipeline":
        return self

    def expire(self, *args: Any) -> "_NoopPipeline":
        return self

    async def execute(self) -> list[int]:
        return [0, 1, 1, 1]


class _NoopRedis:
    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def scalars(self) -> "_FakeScalars":
        items = (
            self._value
            if isinstance(self._value, list)
            else ([] if self._value is None else [self._value])
        )
        return _FakeScalars(items)


class _FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return self._items


class _FakeDB:
    """Returns a fixed result for every query — enough for the router's reads.

    A ``select(Workspace.name)`` (used by download endpoints to slug the
    filename) is detected by its FROM clause and answered with a plain name
    string so the storyboard value isn't mistaken for a workspace name.
    """

    def __init__(
        self, value: Any = None, workspace_name: str = "Demo Workspace"
    ) -> None:
        self._value = value
        self._workspace_name = workspace_name

    async def execute(self, statement: Any) -> _FakeResult:
        try:
            froms = (
                statement.get_final_froms()
                if hasattr(statement, "get_final_froms")
                else statement.froms
            )
            if any(getattr(f, "name", None) == "workspaces" for f in froms):
                return _FakeResult(self._workspace_name)
        except Exception:
            # Statement shape isn't FROM-introspectable; fall through to the
            # default result below.
            pass
        return _FakeResult(self._value)


def _storyboard(
    *,
    status: str = "ready",
    public_share_enabled: bool = False,
    public_share_slug: str | None = None,
) -> Storyboard:
    now = datetime.now(UTC)
    return Storyboard(
        id=_STORYBOARD_ID,
        workspace_id=_WORKSPACE_ID,
        user_id=_USER_ID,
        version=1,
        status=status,
        title="Launch Keynote",
        theme="indica",
        content_json={"title": "Launch Keynote", "notes": {"s1": {"talk_track": "hi"}}},
        speaker_notes_md="# Speaker Notes\n\nTalk track.",
        demo_script_md="# Demo Script\n\nStep 1.",
        technical_appendix_md="# Appendix\n\nDetails.",
        source_map_json={
            "s1": [{"source": "SPEC", "source_id": "SPEC:overview", "excerpt": "x"}]
        },
        source_stage_version_ids={"spec": str(uuid4())},
        public_share_enabled=public_share_enabled,
        public_share_slug=public_share_slug,
        allow_pdf_download=True,
        allow_notes_download=False,
        allow_appendix_download=False,
        allow_source_layer=False,
        created_at=now,
        updated_at=now,
    )


def _app(db_value: Any = None, *, override_user: bool = True):
    app = create_app(redis_client=_NoopRedis())

    async def _fake_db():
        yield _FakeDB(db_value)

    app.dependency_overrides[get_db] = _fake_db
    if override_user:
        app.dependency_overrides[get_current_user] = lambda: _USER
    return app


async def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_route_requires_authentication() -> None:
    app = _app(db_value=None, override_user=False)
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# CSRF required on mutations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mutating_route_without_csrf_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        csrf_module,
        "decode_access_token_claims",
        lambda t: (
            {"sub": str(_USER_ID), "type": "access"} if t == "valid-token" else None
        ),
    )
    app = _app(db_value=_storyboard())
    async with await _client(app) as client:
        response = await client.post(
            f"/storyboards/{_STORYBOARD_ID}/regenerate",
            headers={"Authorization": "Bearer valid-token"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Owner IDOR → 404 (never confirm existence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_owned_storyboard_returns_404() -> None:
    # Fake DB yields no row for this user's scoped query → 404.
    app = _app(db_value=None)
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Public unknown slug → 404 with privacy headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_unknown_slug_returns_404_with_headers() -> None:
    app = _app(db_value=None, override_user=False)
    async with await _client(app) as client:
        response = await client.get("/storyboards/public/does-not-exist")
    assert response.status_code == 404
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'none'" in csp
    assert response.headers["Cache-Control"] == "no-store, private"


@pytest.mark.asyncio
async def test_public_route_does_not_require_auth() -> None:
    # No Authorization header and no user override: a 404 (not 401) proves the
    # public route is unauthenticated.
    app = _app(db_value=None, override_user=False)
    async with await _client(app) as client:
        response = await client.get("/storyboards/public/whatever")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Downloads stream bytes with attachment Content-Disposition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demo_script_download_streams_attachment() -> None:
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(
            f"/storyboards/{_STORYBOARD_ID}/download/demo-script"
        )
    assert response.status_code == 200
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert ".md" in disposition
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Demo Script" in response.text


@pytest.mark.asyncio
async def test_notes_download_returns_markdown() -> None:
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}/download/notes")
    assert response.status_code == 200
    assert "Speaker Notes" in response.text
    assert response.headers["Content-Disposition"].startswith("attachment;")


@pytest.mark.asyncio
async def test_download_on_non_ready_storyboard_conflicts() -> None:
    app = _app(db_value=_storyboard(status="generating"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}/download/appendix")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_html_download_is_attachment_with_csp() -> None:
    # The HTML deck renders with no native deps, so this exercises the real
    # renderer end-to-end through the endpoint.
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}/download/html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert disposition.endswith('.html"')
    assert "Demo-Workspace" in disposition  # slug from the workspace name
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    # Trusted deck markup with no executable script tag.
    assert "<script" not in response.text.lower()


@pytest.mark.asyncio
async def test_html_download_on_non_ready_conflicts() -> None:
    app = _app(db_value=_storyboard(status="generating"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}/download/html")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_pdf_download_streams_pdf(monkeypatch) -> None:
    # PDF rendering needs WeasyPrint native libs; mock the renderer so the
    # endpoint wiring (content-type, attachment, filename) is asserted without
    # them. The renderer's own no-network behaviour is covered in its unit tests.
    import routers.storyboards as storyboards_router

    async def _fake_pdf(content, workspace_name):
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(
        storyboards_router.storyboard_renderer, "render_deck_pdf", _fake_pdf
    )
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}/download/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert disposition.endswith('.pdf"')
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_notes_pdf_renders_attachment(monkeypatch) -> None:
    import routers.storyboards as storyboards_router

    async def _fake_notes_pdf(notes_md, workspace_name):
        return b"%PDF-1.7 notes"

    monkeypatch.setattr(
        storyboards_router.storyboard_renderer, "render_notes_pdf", _fake_notes_pdf
    )
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(
            f"/storyboards/{_STORYBOARD_ID}/download/notes?format=pdf"
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert "speaker-notes" in disposition
    assert disposition.endswith('.pdf"')


# ---------------------------------------------------------------------------
# Owner reads serialize correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_storyboard_returns_detail() -> None:
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(_STORYBOARD_ID)
    assert body["status"] == "ready"
    assert body["permissions"]["allow_pdf_download"] is True
    # Privacy: owner detail must not leak the immutable source version ids.
    assert "source_stage_version_ids" not in body


@pytest.mark.asyncio
async def test_presenter_returns_notes_map() -> None:
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(f"/storyboards/{_STORYBOARD_ID}/presenter")
    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == {"s1": {"talk_track": "hi"}}
    assert body["demo_script_md"].startswith("# Demo Script")


# ---------------------------------------------------------------------------
# Generation endpoints are wired to the T-254 service: the router delegates and
# maps the result/typed errors.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regenerate_invokes_service_and_returns_detail(monkeypatch) -> None:
    import routers.storyboards as storyboards_router

    async def _fake_regenerate(db, redis, storyboard_id, user_id):
        return _storyboard(status="ready")

    monkeypatch.setattr(
        storyboards_router, "_service_regenerate_storyboard", _fake_regenerate
    )
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.post(f"/storyboards/{_STORYBOARD_ID}/regenerate")
    assert response.status_code == 200
    assert response.json()["id"] == str(_STORYBOARD_ID)


@pytest.mark.asyncio
async def test_regenerate_maps_generation_failure_to_502(monkeypatch) -> None:
    import routers.storyboards as storyboards_router
    from services.pipeline.storyboard_service import StoryboardGenerationError

    async def _fail(db, redis, storyboard_id, user_id):
        raise StoryboardGenerationError("payload_schema", "bad shape")

    monkeypatch.setattr(storyboards_router, "_service_regenerate_storyboard", _fail)
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.post(f"/storyboards/{_STORYBOARD_ID}/regenerate")
    assert response.status_code == 502
    body = response.json()["detail"]
    assert body["code"] == "storyboard_generation_failed"
    assert body["error_type"] == "payload_schema"


@pytest.mark.asyncio
async def test_generate_maps_stages_not_finalised_to_409(monkeypatch) -> None:
    import routers.storyboards as storyboards_router
    from services.pipeline.storyboard_source import (
        StoryboardStagesNotFinalisedError,
    )

    async def _not_finalised(db, redis, workspace_id, user_id):
        raise StoryboardStagesNotFinalisedError({"plan": "draft"})

    monkeypatch.setattr(
        storyboards_router, "_service_generate_storyboard", _not_finalised
    )
    # workspace_service.get must succeed (ownership) before the service runs.
    monkeypatch.setattr(
        storyboards_router.workspace_service,
        "get",
        lambda *args, **kwargs: _async_none(),
    )
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.post(f"/workspaces/{_WORKSPACE_ID}/storyboards")
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == "storyboard_stages_not_finalised"
    assert body["stages"] == {"plan": "draft"}


async def _async_none() -> None:
    return None


# ---------------------------------------------------------------------------
# Public sharing (T-256): allow-list view, privacy headers, download gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_view_returns_allow_list_with_privacy_headers() -> None:
    sb = _storyboard(status="ready", public_share_enabled=True, public_share_slug="x")
    app = _app(db_value=sb, override_user=False)
    async with await _client(app) as client:
        response = await client.get("/storyboards/public/abcdefghij")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "title",
        "presentation",
        "permissions",
        "downloads",
        "shared_at",
    }
    # Privacy headers on the public surface.
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store, private"
    # Forbidden identifiers never appear.
    blob = response.text
    assert str(_WORKSPACE_ID) not in blob
    assert str(_USER_ID) not in blob
    assert "source_stage_version_ids" not in blob
    # Notes are off by default, so the private talk track is redacted (replaced,
    # not the original "hi").
    assert body["presentation"]["notes"].get("s1", {}).get("talk_track") != "hi"


@pytest.mark.asyncio
async def test_public_download_pdf_allowed(monkeypatch) -> None:
    import routers.storyboards as storyboards_router

    async def _fake_pdf(content, name):
        return b"%PDF-1.7 public"

    monkeypatch.setattr(
        storyboards_router.storyboard_renderer, "render_deck_pdf", _fake_pdf
    )
    sb = _storyboard(
        status="ready", public_share_enabled=True, public_share_slug="x"
    )  # allow_pdf_download defaults True
    app = _app(db_value=sb, override_user=False)
    async with await _client(app) as client:
        response = await client.get("/storyboards/public/abcdefghij/download/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


@pytest.mark.asyncio
async def test_public_download_notes_forbidden_returns_404() -> None:
    # allow_notes_download defaults False → 404 (never 403).
    sb = _storyboard(status="ready", public_share_enabled=True, public_share_slug="x")
    app = _app(db_value=sb, override_user=False)
    async with await _client(app) as client:
        response = await client.get("/storyboards/public/abcdefghij/download/notes")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_download_html_is_never_public() -> None:
    sb = _storyboard(status="ready", public_share_enabled=True, public_share_slug="x")
    app = _app(db_value=sb, override_user=False)
    async with await _client(app) as client:
        response = await client.get("/storyboards/public/abcdefghij/download/html")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_download_demo_script_allowed_when_shared() -> None:
    sb = _storyboard(status="ready", public_share_enabled=True, public_share_slug="x")
    app = _app(db_value=sb, override_user=False)
    async with await _client(app) as client:
        response = await client.get(
            "/storyboards/public/abcdefghij/download/demo-script"
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["Content-Disposition"].startswith("attachment;")


@pytest.mark.asyncio
async def test_enable_share_returns_slug_and_url(monkeypatch) -> None:
    import routers.storyboards as storyboards_router

    sb = _storyboard(
        status="ready", public_share_enabled=True, public_share_slug="sharetoken1"
    )

    async def _fake_enable(db, storyboard_id, user_id, request):
        return sb

    monkeypatch.setattr(
        storyboards_router.storyboard_public_service, "enable_share", _fake_enable
    )
    app = _app(db_value=sb)
    async with await _client(app) as client:
        response = await client.post(f"/storyboards/{_STORYBOARD_ID}/share")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "sharetoken1"
    assert body["url"].endswith("/sb/sharetoken1")
    assert body["enabled"] is True
    assert body["permissions"]["allow_pdf_download"] is True
