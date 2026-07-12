"""Tests for the GitHub App install flow + lifecycle (Phase 21 — T-270).

Two layers:
  - state/URL helpers and routes (FakeRedis, app with dependency overrides);
  - install upsert, listing, revoke, and lifecycle event application against the
    real DB (migration applied), as the rest of the integration suite does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from database import get_db, get_redis
from main import create_app
from middleware.auth import get_current_user
from models import GitHubInstallation, IntegrationPush, User, Workspace
from schemas.github import InstallationList, InstallationOption
from services.integrations import github_install_service as svc
from services.integrations.github_api_client import (
    GitHubAPIError,
    GitHubRateLimitError,
    GitHubTokenExpiredError,
    GitHubUnavailableError,
)
from services.integrations.github_install_service import (
    AppNotConfiguredError,
    InstallationAccount,
    InstallStateError,
)
from services.pipeline import github_export_service as export_svc

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def eval(self, *args: Any) -> int:
        # Sliding-window rate-limit Lua: 1 == under limit (allowed). These tests
        # do not exercise rate limiting.
        return 1


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(
        email=f"test-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Tester",
        avatar_url=None,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    yield u
    await session.execute(delete(User).where(User.id == u.id))
    await session.commit()


@pytest.fixture
async def workspace(session: AsyncSession, user: User) -> Workspace:
    ws = Workspace(
        user_id=user.id,
        name="WS",
        problem_statement="x" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)
    yield ws
    await session.execute(delete(Workspace).where(Workspace.id == ws.id))
    await session.commit()


def _account(login: str = "octo-org") -> InstallationAccount:
    return InstallationAccount(
        account_login=login, account_type="Organization", repository_selection="all"
    )


async def _make_push(
    session: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    installation: GitHubInstallation,
    repo_id: int,
    status: str = "completed",
) -> IntegrationPush:
    push = IntegrationPush(
        workspace_id=workspace.id,
        user_id=user.id,
        provider="github",
        installation_id=installation.id,
        repo_id=repo_id,
        status=status,
    )
    session.add(push)
    await session.commit()
    await session.refresh(push)
    return push


async def _cleanup_install(session: AsyncSession, installation_id: int) -> None:
    rows = (
        (
            await session.execute(
                select(GitHubInstallation).where(
                    GitHubInstallation.installation_id == installation_id
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        await session.execute(
            delete(IntegrationPush).where(IntegrationPush.installation_id == row.id)
        )
        await session.execute(
            delete(GitHubInstallation).where(GitHubInstallation.id == row.id)
        )
    await session.commit()


# ---------------------------------------------------------------------------
# Install URL + state
# ---------------------------------------------------------------------------


async def test_build_install_url_requires_app_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_app_slug", "")
    monkeypatch.setattr(settings, "github_app_id", "")
    with pytest.raises(AppNotConfiguredError):
        await svc.build_install_url(uuid4(), _FakeRedis())


async def test_build_and_consume_state_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_app_slug", "specforge-dev")
    monkeypatch.setattr(settings, "github_app_id", "123")
    redis = _FakeRedis()
    user_id = uuid4()

    url = await svc.build_install_url(user_id, redis)
    assert "github.com/apps/specforge-dev/installations/new?state=" in url
    state = url.split("state=", 1)[1]

    # Valid state resolves to the bound user and is single-use.
    assert await svc.consume_install_state(state, redis) == user_id
    with pytest.raises(InstallStateError):
        await svc.consume_install_state(state, redis)


async def test_consume_missing_state_raises() -> None:
    with pytest.raises(InstallStateError):
        await svc.consume_install_state(None, _FakeRedis())
    with pytest.raises(InstallStateError):
        await svc.consume_install_state("nope", _FakeRedis())


# ---------------------------------------------------------------------------
# Identity verification helpers (audit #1) — the proof-of-control gate
# ---------------------------------------------------------------------------


def _mock_identity_client(handler: Any) -> Any:
    """Build an httpx.AsyncClient backed by a MockTransport handler."""
    import httpx

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_user_can_access_installation_membership_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate is membership in ``GET /user/installations``: present → access,
    absent → no access (this is the property that closes the IDOR)."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/installations"
        return httpx.Response(
            200, json={"total_count": 2, "installations": [{"id": 42}, {"id": 7}]}
        )

    async with _mock_identity_client(handler) as http:
        assert await svc.user_can_access_installation("tok", 42, client=http) is True
        assert await svc.user_can_access_installation("tok", 999, client=http) is False


async def test_user_can_access_installation_fails_closed_on_error() -> None:
    """An unreadable installations list raises (never silently "verified")."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    async with _mock_identity_client(handler) as http:
        with pytest.raises(svc.InstallVerificationError):
            await svc.user_can_access_installation("tok", 42, client=http)


async def test_user_can_access_installation_paginates() -> None:
    """The target installation on a second page is still found (pagination)."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(
                200,
                json={"installations": [{"id": i} for i in range(100)]},
            )
        return httpx.Response(200, json={"installations": [{"id": 4242}]})

    async with _mock_identity_client(handler) as http:
        assert await svc.user_can_access_installation("tok", 4242, client=http) is True


async def test_exchange_identity_code_returns_token() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "github.com"
        assert request.url.path == "/login/oauth/access_token"
        # Must ask for JSON — the OAuth token endpoint returns a form-encoded
        # body otherwise, which response.json() cannot parse (fail-closed bug).
        assert request.headers.get("Accept") == "application/json"
        return httpx.Response(200, json={"access_token": "u2s-token", "scope": ""})

    async with _mock_identity_client(handler) as http:
        token = await svc.exchange_identity_code("code", client=http)
    assert token == "u2s-token"


async def test_exchange_identity_code_rejects_error_body() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code"})

    async with _mock_identity_client(handler) as http:
        with pytest.raises(svc.InstallVerificationError):
            await svc.exchange_identity_code("code", client=http)


async def test_consume_identity_state_roundtrip_and_misses() -> None:
    redis = _FakeRedis()
    user_id = uuid4()
    url = await svc.build_identity_verify_url(user_id, 55, redis)
    assert url.startswith(svc._GITHUB_OAUTH_AUTHORIZE_URL)
    state = url.split("state=", 1)[1].split("&", 1)[0]

    got = await svc.consume_identity_state(state, redis)
    assert got == (user_id, 55)
    # Single-use.
    assert await svc.consume_identity_state(state, redis) is None
    # A non-identity state is a clean miss (None), not an error.
    assert await svc.consume_identity_state("not-a-state", redis) is None
    assert await svc.consume_identity_state(None, redis) is None


# ---------------------------------------------------------------------------
# Upsert / list / legacy flag
# ---------------------------------------------------------------------------


async def test_upsert_installation_inserts_then_updates(
    session: AsyncSession, user: User
) -> None:
    install_id = uuid4().int % 1_000_000_000
    try:
        first = await svc.upsert_installation(
            session, installation_id=install_id, user_id=user.id, account=_account()
        )
        assert first.account_login == "octo-org"
        assert first.suspended_at is None

        # Simulate a prior suspension, then a re-install clears it and updates.
        first.suspended_at = datetime.now(UTC)
        await session.commit()
        second = await svc.upsert_installation(
            session,
            installation_id=install_id,
            user_id=user.id,
            account=_account("octo-renamed"),
        )
        assert second.id == first.id  # same row (unique installation_id)
        assert second.account_login == "octo-renamed"
        assert second.suspended_at is None
    finally:
        await _cleanup_install(session, install_id)


async def test_list_installations_and_legacy_flag(
    session: AsyncSession, user: User
) -> None:
    install_id = uuid4().int % 1_000_000_000
    try:
        await svc.upsert_installation(
            session, installation_id=install_id, user_id=user.id, account=_account()
        )
        rows = await svc.list_installations(session, user.id)
        assert any(r.installation_id == install_id for r in rows)
        # No UserIntegration row → not on legacy OAuth.
        assert await svc.user_on_legacy_oauth(session, user.id) is False

        # The response model serialises the persisted account_type /
        # repository_selection (Literal fields) without a validation 500.
        row = next(r for r in rows if r.installation_id == install_id)
        listing = InstallationList(
            installations=[
                InstallationOption(
                    id=row.id,
                    installation_id=row.installation_id,
                    account_login=row.account_login,
                    account_type=row.account_type,
                    repository_selection=row.repository_selection,
                    suspended=row.suspended_at is not None,
                )
            ],
            on_legacy_oauth=False,
        )
        dumped = listing.model_dump()
        assert dumped["installations"][0]["account_type"] == "Organization"
        assert dumped["installations"][0]["repository_selection"] == "all"
    finally:
        await _cleanup_install(session, install_id)


# ---------------------------------------------------------------------------
# Lifecycle: suspend / unsuspend / deleted / repos removed
# ---------------------------------------------------------------------------


async def test_suspend_marks_pushes_stale_then_unsuspend_clears(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    install_id = uuid4().int % 1_000_000_000
    try:
        inst = await svc.upsert_installation(
            session, installation_id=install_id, user_id=user.id, account=_account()
        )
        push = await _make_push(
            session, workspace=workspace, user=user, installation=inst, repo_id=701
        )

        await svc.apply_installation_event(
            session, action="suspend", installation_id=install_id
        )
        await session.refresh(inst)
        await session.refresh(push)
        assert inst.suspended_at is not None
        assert push.status == "stale"  # sync paused, still "live"

        await svc.apply_installation_event(
            session, action="unsuspend", installation_id=install_id
        )
        await session.refresh(inst)
        assert inst.suspended_at is None
    finally:
        await _cleanup_install(session, install_id)


async def test_deleted_detaches_pushes_and_removes_row(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    install_id = uuid4().int % 1_000_000_000
    inst = await svc.upsert_installation(
        session, installation_id=install_id, user_id=user.id, account=_account()
    )
    push = await _make_push(
        session, workspace=workspace, user=user, installation=inst, repo_id=702
    )

    await svc.apply_installation_event(
        session, action="deleted", installation_id=install_id
    )
    await session.refresh(push)
    # Row removed; push staled and detached so the delete did not FK-violate.
    assert push.status == "stale"
    assert push.installation_id is None
    gone = (
        await session.execute(
            select(GitHubInstallation).where(GitHubInstallation.id == inst.id)
        )
    ).scalar_one_or_none()
    assert gone is None
    # Cleanup the detached push.
    await session.execute(delete(IntegrationPush).where(IntegrationPush.id == push.id))
    await session.commit()


async def test_repos_removed_marks_only_those_pushes_stale(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    install_id = uuid4().int % 1_000_000_000
    try:
        inst = await svc.upsert_installation(
            session, installation_id=install_id, user_id=user.id, account=_account()
        )
        kept = await _make_push(
            session, workspace=workspace, user=user, installation=inst, repo_id=800
        )
        removed = await _make_push(
            session, workspace=workspace, user=user, installation=inst, repo_id=801
        )
        # Two live pushes for one repo are not allowed (partial unique index), so
        # the kept/removed pushes are for different repos — fine.

        await svc.apply_installation_repositories_event(
            session,
            action="removed",
            installation_id=install_id,
            removed_repo_ids=[801],
        )
        await session.refresh(kept)
        await session.refresh(removed)
        assert kept.status == "completed"
        assert removed.status == "stale"
    finally:
        await _cleanup_install(session, install_id)


async def test_revoke_installation_enforces_ownership(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    install_id = uuid4().int % 1_000_000_000
    inst = await svc.upsert_installation(
        session, installation_id=install_id, user_id=user.id, account=_account()
    )
    push = await _make_push(
        session, workspace=workspace, user=user, installation=inst, repo_id=900
    )

    other = User(
        email=f"other-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Other",
        avatar_url=None,
    )
    session.add(other)
    await session.commit()
    await session.refresh(other)
    try:
        # Non-owner cannot revoke.
        assert await svc.revoke_installation(session, inst.id, other.id) is False
        # Owner revokes: row gone, push staled + detached.
        assert await svc.revoke_installation(session, inst.id, user.id) is True
        await session.refresh(push)
        assert push.status == "stale"
        assert push.installation_id is None
        gone = (
            await session.execute(
                select(GitHubInstallation).where(GitHubInstallation.id == inst.id)
            )
        ).scalar_one_or_none()
        assert gone is None
    finally:
        await session.execute(
            delete(IntegrationPush).where(IntegrationPush.id == push.id)
        )
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


_ROUTE_USER = User(
    id=uuid4(),
    email="route@example.com",
    google_id="route-google",
    name="Route User",
    avatar_url=None,
    credit_balance=0,
    created_at=datetime.now(UTC),
)


def _app(monkeypatch: pytest.MonkeyPatch) -> Any:
    redis = _FakeRedis()
    application = create_app(redis_client=redis)
    application.state.redis = redis

    async def _fake_get_db():  # routes that need DB are monkeypatched at the service
        yield None

    application.dependency_overrides[get_db] = _fake_get_db
    application.dependency_overrides[get_redis] = lambda: redis
    application.dependency_overrides[get_current_user] = lambda: _ROUTE_USER
    return application, redis


def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_install_route_503_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_app_slug", "")
    monkeypatch.setattr(settings, "github_app_id", "")
    app, _ = _app(monkeypatch)
    async with _client(app) as client:
        resp = await client.get("/integrations/github/install")
    assert resp.status_code == 503


async def test_install_route_returns_url_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_app_slug", "specforge-dev")
    monkeypatch.setattr(settings, "github_app_id", "123")
    app, _ = _app(monkeypatch)
    async with _client(app) as client:
        resp = await client.get("/integrations/github/install")
    assert resp.status_code == 200
    assert "specforge-dev/installations/new" in resp.json()["url"]


async def test_setup_invalid_state_redirects_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _app(monkeypatch)
    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup?installation_id=5&state=bad",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert "github_installed=false" in resp.headers["location"]


def _enable_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the App's identity OAuth so the verified-bind path is reachable."""
    monkeypatch.setattr(settings, "github_app_client_id", "iv1.appclient")
    monkeypatch.setattr(settings, "github_app_client_secret", "appsecret")


async def test_setup_verified_install_upserts_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-hop: GitHub authorized the user during install (``code`` present),
    verification confirms admin, the install is bound."""
    _enable_identity(monkeypatch)
    app, redis = _app(monkeypatch)
    # Seed a valid install state bound to the route user.
    await redis.set(f"{svc.INSTALL_STATE_PREFIX}good", str(_ROUTE_USER.id), ex=600)

    captured: dict[str, Any] = {}

    async def fake_verify(code: str, installation_id: int, **kw: Any) -> bool:
        captured["verified_code"] = code
        captured["verified_install"] = installation_id
        return True

    async def fake_fetch(installation_id: int, **kw: Any) -> InstallationAccount:
        captured["fetched"] = installation_id
        return _account()

    async def fake_upsert(db: Any, **kwargs: Any) -> Any:
        captured["upserted"] = kwargs["installation_id"]
        captured["bound_user"] = kwargs["user_id"]
        return None

    monkeypatch.setattr(svc, "verify_installer_can_access", fake_verify)
    monkeypatch.setattr(svc, "fetch_installation_account", fake_fetch)
    monkeypatch.setattr(svc, "upsert_installation", fake_upsert)

    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup"
            "?installation_id=42&setup_action=install&code=oauthcode&state=good",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert "github_installed=true" in resp.headers["location"]
    assert captured["fetched"] == 42
    assert captured["upserted"] == 42
    assert captured["bound_user"] == _ROUTE_USER.id
    assert captured["verified_install"] == 42


async def test_setup_install_hijack_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit #1 regression: an attacker's valid ``state`` + a victim's
    ``installation_id`` must NOT bind when verification fails (the attacker does
    not administer the victim's installation). No upsert; redirect false."""
    _enable_identity(monkeypatch)
    app, redis = _app(monkeypatch)
    # Attacker holds a perfectly valid state bound to their own account.
    await redis.set(f"{svc.INSTALL_STATE_PREFIX}attacker", str(_ROUTE_USER.id), ex=600)

    upsert_calls: list[Any] = []

    async def fake_verify(code: str, installation_id: int, **kw: Any) -> bool:
        # /user/installations does not contain the victim's install for the
        # attacker → not an admin.
        return False

    async def fake_upsert(db: Any, **kwargs: Any) -> Any:  # pragma: no cover
        upsert_calls.append(kwargs)
        return None

    monkeypatch.setattr(svc, "verify_installer_can_access", fake_verify)
    monkeypatch.setattr(svc, "upsert_installation", fake_upsert)

    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup"
            "?installation_id=999999&setup_action=install&code=stolen&state=attacker",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert "github_installed=false" in resp.headers["location"]
    assert upsert_calls == []  # the victim's installation was never rebound


async def test_setup_verification_error_refuses_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An *inability* to determine admin status (e.g. GitHub unreachable) fails
    closed — never bind on an unverifiable installer."""
    _enable_identity(monkeypatch)
    app, redis = _app(monkeypatch)
    await redis.set(f"{svc.INSTALL_STATE_PREFIX}good", str(_ROUTE_USER.id), ex=600)

    async def fake_verify(code: str, installation_id: int, **kw: Any) -> bool:
        raise svc.InstallVerificationError("github unreachable")

    async def fake_upsert(db: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("must not bind on a verification error")

    monkeypatch.setattr(svc, "verify_installer_can_access", fake_verify)
    monkeypatch.setattr(svc, "upsert_installation", fake_upsert)

    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup"
            "?installation_id=42&setup_action=install&code=c&state=good",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert "github_installed=false" in resp.headers["location"]


async def test_setup_without_code_redirects_to_authorize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two-hop: no ``code`` in the install redirect → bounce the browser to the
    user-to-server authorize endpoint to obtain proof of control."""
    _enable_identity(monkeypatch)
    app, redis = _app(monkeypatch)
    await redis.set(f"{svc.INSTALL_STATE_PREFIX}good", str(_ROUTE_USER.id), ex=600)

    async def fake_upsert(db: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("must not bind before verification")

    monkeypatch.setattr(svc, "upsert_installation", fake_upsert)

    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup"
            "?installation_id=42&setup_action=install&state=good",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize")
    assert "client_id=iv1.appclient" in location
    assert "state=" in location


async def test_setup_verify_hop_returns_and_binds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second hop: the verify-state round-trip returns with a ``code`` and binds
    the installation captured in the verify state."""
    _enable_identity(monkeypatch)
    app, redis = _app(monkeypatch)
    # Simulate the verify-state minted during hop 1.
    import json as _json

    await redis.set(
        f"{svc.IDENTITY_STATE_PREFIX}verify",
        _json.dumps({"user_id": str(_ROUTE_USER.id), "installation_id": 77}),
        ex=600,
    )

    captured: dict[str, Any] = {}

    async def fake_verify(code: str, installation_id: int, **kw: Any) -> bool:
        captured["install"] = installation_id
        return True

    async def fake_fetch(installation_id: int, **kw: Any) -> InstallationAccount:
        return _account()

    async def fake_upsert(db: Any, **kwargs: Any) -> Any:
        captured["upserted"] = kwargs["installation_id"]
        return None

    monkeypatch.setattr(svc, "verify_installer_can_access", fake_verify)
    monkeypatch.setattr(svc, "fetch_installation_account", fake_fetch)
    monkeypatch.setattr(svc, "upsert_installation", fake_upsert)

    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup?code=returncode&state=verify",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert "github_installed=true" in resp.headers["location"]
    assert captured == {"install": 77, "upserted": 77}


async def test_setup_refuses_when_identity_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed: with identity OAuth off we cannot prove control, so even a
    valid install state must not bind."""
    monkeypatch.setattr(settings, "github_app_client_id", "")
    monkeypatch.setattr(settings, "github_app_client_secret", "")
    app, redis = _app(monkeypatch)
    await redis.set(f"{svc.INSTALL_STATE_PREFIX}good", str(_ROUTE_USER.id), ex=600)

    async def fake_upsert(db: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("must not bind without identity verification")

    monkeypatch.setattr(svc, "upsert_installation", fake_upsert)

    async with _client(app) as client:
        resp = await client.get(
            "/integrations/github/setup"
            "?installation_id=42&setup_action=install&code=c&state=good",
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert "github_installed=false" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Repo-picker listing route (GET /github/installations/{id}/repos)
# ---------------------------------------------------------------------------


def _installation_row(
    *,
    user_id: Any = None,
    account_type: str = "User",
    repository_selection: str = "selected",
    suspended: bool = False,
) -> GitHubInstallation:
    """In-memory installation row for route tests (service is monkeypatched)."""
    return GitHubInstallation(
        id=uuid4(),
        installation_id=4242,
        user_id=user_id or _ROUTE_USER.id,
        account_login="octo",
        account_type=account_type,
        repository_selection=repository_selection,
        suspended_at=datetime.now(UTC) if suspended else None,
    )


async def test_repo_list_route_returns_repos_and_create_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner sees usable rows; malformed rows are dropped, never a 500; the
    create gate comes from the same helper the worker export uses."""
    app, _ = _app(monkeypatch)
    inst = _installation_row(account_type="Organization", repository_selection="all")

    async def fake_load(db: Any, installation_id: Any, user_id: Any) -> Any:
        assert installation_id == inst.id
        assert user_id == _ROUTE_USER.id
        return inst

    async def fake_list(installation: Any, **kwargs: Any) -> Any:
        assert installation is inst
        return (
            [
                {
                    "id": 1,
                    "name": "alpha",
                    "full_name": "octo/alpha",
                    "private": True,
                    "html_url": "https://github.com/octo/alpha",
                },
                {"id": "malformed", "name": None, "full_name": 3},
            ],
            True,
        )

    monkeypatch.setattr(export_svc, "load_owned_installation", fake_load)
    monkeypatch.setattr(export_svc, "list_repos_for_installation", fake_list)

    async with _client(app) as client:
        resp = await client.get(f"/integrations/github/installations/{inst.id}/repos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert body["can_create"] is True
    assert body["repositories"] == [
        {
            "id": 1,
            "name": "alpha",
            "full_name": "octo/alpha",
            "private": True,
            "html_url": "https://github.com/octo/alpha",
        }
    ]


async def test_repo_list_route_personal_account_cannot_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _app(monkeypatch)
    inst = _installation_row(account_type="User", repository_selection="selected")

    async def fake_load(db: Any, installation_id: Any, user_id: Any) -> Any:
        return inst

    async def fake_list(installation: Any, **kwargs: Any) -> Any:
        return ([], False)

    monkeypatch.setattr(export_svc, "load_owned_installation", fake_load)
    monkeypatch.setattr(export_svc, "list_repos_for_installation", fake_list)

    async with _client(app) as client:
        resp = await client.get(f"/integrations/github/installations/{inst.id}/repos")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"repositories": [], "truncated": False, "can_create": False}


async def test_repo_list_route_unowned_installation_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unowned/missing installation is a 403 (mirroring the export route) —
    never a 404, so installation existence is not leaked."""
    app, _ = _app(monkeypatch)

    async def fake_load(db: Any, installation_id: Any, user_id: Any) -> Any:
        return None

    monkeypatch.setattr(export_svc, "load_owned_installation", fake_load)

    async with _client(app) as client:
        resp = await client.get(f"/integrations/github/installations/{uuid4()}/repos")
    assert resp.status_code == 403


async def test_repo_list_route_suspended_installation_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _app(monkeypatch)
    inst = _installation_row(suspended=True)

    async def fake_load(db: Any, installation_id: Any, user_id: Any) -> Any:
        return inst

    async def fake_list(installation: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("suspended installation must never reach GitHub")

    monkeypatch.setattr(export_svc, "load_owned_installation", fake_load)
    monkeypatch.setattr(export_svc, "list_repos_for_installation", fake_list)

    async with _client(app) as client:
        resp = await client.get(f"/integrations/github/installations/{inst.id}/repos")
    assert resp.status_code == 403


@pytest.mark.parametrize(
    ("raised", "expected_status"),
    [
        (GitHubRateLimitError("limited"), 429),
        (GitHubUnavailableError("breaker open"), 503),
        (GitHubTokenExpiredError("401"), 502),
        (GitHubAPIError(500, "boom"), 502),
    ],
)
async def test_repo_list_route_maps_github_errors(
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected_status: int,
) -> None:
    """A GitHub blip surfaces as a typed 4xx/5xx, never an unhandled 500 —
    the interactive path has no worker retry to hide behind."""
    app, _ = _app(monkeypatch)
    inst = _installation_row()

    async def fake_load(db: Any, installation_id: Any, user_id: Any) -> Any:
        return inst

    async def fake_list(installation: Any, **kwargs: Any) -> Any:
        raise raised

    monkeypatch.setattr(export_svc, "load_owned_installation", fake_load)
    monkeypatch.setattr(export_svc, "list_repos_for_installation", fake_list)

    async with _client(app) as client:
        resp = await client.get(f"/integrations/github/installations/{inst.id}/repos")
    assert resp.status_code == expected_status
