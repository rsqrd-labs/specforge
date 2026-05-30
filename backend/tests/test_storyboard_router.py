"""Router contract tests for the Storyboard API (Phase 20 — T-251).

These exercise the parts of the contract that are fully owned by T-251: auth
requirement, CSRF protection on mutations, owner IDOR → 404, public unknown-slug
→ 404 with privacy headers, and markdown download streaming with an attachment
Content-Disposition. Generation/render/share/public bodies are delegated to
later tasks and return a typed 503; that boundary is asserted here too.
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
    """Returns a fixed result for every query — enough for the router's reads."""

    def __init__(self, value: Any = None) -> None:
        self._value = value

    async def execute(self, statement: Any) -> _FakeResult:
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
async def test_notes_pdf_format_is_delegated_until_renderer() -> None:
    app = _app(db_value=_storyboard(status="ready"))
    async with await _client(app) as client:
        response = await client.get(
            f"/storyboards/{_STORYBOARD_ID}/download/notes?format=pdf"
        )
    assert response.status_code == 503
    assert response.json()["detail"]["component"] == "renderer"


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
# Delegated endpoints return a typed 503 (boundary until later tasks wire them)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regenerate_is_pipeline_unavailable() -> None:
    monkey_user = _app(db_value=_storyboard(status="ready"))
    async with await _client(monkey_user) as client:
        response = await client.post(f"/storyboards/{_STORYBOARD_ID}/regenerate")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "storyboard_pipeline_unavailable"
    assert response.json()["detail"]["component"] == "generation"
