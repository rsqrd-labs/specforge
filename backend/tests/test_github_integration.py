"""End-to-end contract suite for Phase 13 GitHub integration (T-154).

Four test classes cover the full backend contract:

- TestGitHubAuth — OAuth init + callback routes (state-based CSRF).
- TestIntegrationsRouter — /integrations/github GET/DELETE.
- TestGitHubExport — POST/GET /workspaces/{id}/export/github, including
  the full error → HTTP mapping table.
- TestGitHubRateLimit — 3 GitHub exports per user per hour tier, and
  confirms the ZIP export is NOT covered by this tier.

The tests run against the real FastAPI app with stubbed dependencies:
- Redis: in-memory _FakeRedis with the sliding-window Lua semantics.
- DB: in-memory _FakeDB session that records inserts and returns
  pre-programmed rows.
- github_export_service.push_to_github: patched per test to raise the
  specific exception we want to assert maps to a given HTTP status.

These tests are the "Phase 13 backend done" gate — every error→HTTP
mapping from Plan §4.5 is covered here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from database import get_db, get_redis
from main import create_app
from middleware.auth import get_current_user
from models import User
from models.integration_push import IntegrationPush
from services.integrations import github_auth_service
from services.integrations.github_api_client import (
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubRateLimitError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
)
from services.pipeline import github_export_service
from services.pipeline.export_service import ExportNotReadyError
from services.security.csrf import generate_csrf_token

# ---------------------------------------------------------------------------
# Module-level fixtures (sharable across all four test classes)
# ---------------------------------------------------------------------------


_USER_ID = uuid4()
_USER = User(
    id=_USER_ID,
    email="user@example.com",
    google_id="google-id",
    name="Test User",
    avatar_url=None,
    credit_balance=0,
    created_at=datetime.now(UTC),
)


class _FakeRedis:
    """In-memory Redis stub.

    Implements just enough of the redis.asyncio interface for the auth
    state flow and the sliding-window Lua check in rate_limit.py.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        # ZSET storage for the sliding-window check
        self._zsets: dict[str, list[tuple[float, str]]] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)
            self._zsets.pop(key, None)

    async def aclose(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        now_str: str,
        window_start_str: str,
        limit_str: str,
        member: str,
        ttl_str: str,
    ) -> int:
        now = float(now_str)
        window_start = float(window_start_str)
        limit = int(limit_str)

        bucket = self._zsets.setdefault(key, [])
        # Drop expired members
        bucket[:] = [(score, m) for (score, m) in bucket if score > window_start]
        if len(bucket) >= limit:
            return 0
        bucket.append((now, member))
        return 1


class _FakeSession:
    """Minimal AsyncSession stand-in.

    Tests inject pre-programmed query results via the `query_results`
    attribute. Mutations (insert/update/delete) are recorded but no-op.
    """

    def __init__(self) -> None:
        self.executions: list[Any] = []
        self.query_results: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> Any:
        self.executions.append(statement)
        if self.query_results:
            return self.query_results.pop(0)
        return _EmptyResult()

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        return None

    def add(self, obj: Any) -> None:
        self.executions.append(("add", obj))


class _EmptyResult:
    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> "_EmptyResult":
        return self

    def all(self) -> list:
        return []


def _result_with_scalar(value: Any) -> Any:
    class _R:
        def scalar_one_or_none(self) -> Any:
            return value

        def scalar_one(self) -> Any:
            return value

    return _R()


async def _fake_get_db():
    yield _FakeSession()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(settings, "github_client_id", "test_client_id")
    monkeypatch.setattr(settings, "github_client_secret", "test_secret")

    fake_redis = _FakeRedis()
    application = create_app(redis_client=fake_redis)
    # The AsyncClient does not trigger the lifespan, so app.state.redis is not
    # set automatically.  Manually inject the fake so Depends(get_redis) works.
    application.state.redis = fake_redis
    application.dependency_overrides[get_db] = _fake_get_db
    application.dependency_overrides[get_redis] = lambda: fake_redis
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def authed_app(app: Any) -> Any:
    """An app with the JWT auth dependency override to the canonical _USER."""
    app.dependency_overrides[get_current_user] = lambda: _USER
    return app


def _client(app: Any, follow_redirects: bool = False) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=follow_redirects,
    )


def _real_jwt_for_user() -> str:
    """Build a real RS256-signed access token for _USER_ID.

    Required for tests that exercise the rate-limit middleware, which
    extracts user_id directly from the Authorization header (not from
    the dependency override).
    """
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4 as _uuid4

    from jose import jwt as _jwt

    now = datetime.now(UTC)
    claims = {
        "sub": str(_USER_ID),
        "jti": str(_uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return _jwt.encode(claims, settings.jwt_private_key, algorithm="RS256")


def _auth_headers(*, real_jwt: bool = False) -> dict[str, str]:
    token = _real_jwt_for_user() if real_jwt else "test_token"
    return {
        "Authorization": f"Bearer {token}",
        "X-CSRF-Token": generate_csrf_token(str(_USER_ID)),
    }


def _workspace_id() -> UUID:
    return uuid4()


# ---------------------------------------------------------------------------
# TestGitHubAuth
# ---------------------------------------------------------------------------


class TestGitHubAuth:
    """Cover /auth/github init + /auth/github/callback CSRF + 503 disabled."""

    @pytest.mark.asyncio
    async def test_get_auth_github_without_jwt_returns_401(self, app: Any) -> None:
        async with _client(app) as client:
            response = await client.get("/auth/github")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_auth_github_returns_503_when_client_id_empty(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "github_client_id", "")
        async with _client(authed_app) as client:
            response = await client.get("/auth/github")
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_get_auth_github_with_jwt_redirects_to_github(
        self, authed_app: Any
    ) -> None:
        async with _client(authed_app) as client:
            response = await client.get("/auth/github")
        assert response.status_code in (302, 307)
        location = response.headers["location"]
        assert "github.com/login/oauth/authorize" in location
        assert "client_id=test_client_id" in location
        assert "state=" in location

    @pytest.mark.asyncio
    async def test_callback_missing_state_returns_400(self, app: Any) -> None:
        async with _client(app) as client:
            response = await client.get("/auth/github/callback?code=abc")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_tampered_state_returns_400(self, app: Any) -> None:
        async with _client(app) as client:
            response = await client.get(
                "/auth/github/callback?code=abc&state=not-in-redis"
            )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# TestIntegrationsRouter
# ---------------------------------------------------------------------------


class TestIntegrationsRouter:
    """Cover GET / DELETE /integrations/github."""

    @pytest.mark.asyncio
    async def test_get_unconnected_returns_disconnected_shape(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_get(user_id: Any, db: Any) -> None:
            return None

        monkeypatch.setattr(github_auth_service, "get_integration", fake_get)

        async with _client(authed_app) as client:
            response = await client.get("/integrations/github")

        assert response.status_code == 200
        assert response.json() == {"connected": False, "github_username": None}

    @pytest.mark.asyncio
    async def test_get_connected_returns_username(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from models.user_integration import UserIntegration

        integration = UserIntegration(
            id=uuid4(),
            user_id=_USER_ID,
            provider="github",
            encrypted_token="enc",
            github_username="testuser",
            connected_at=datetime.now(UTC),
            last_used_at=None,
        )

        async def fake_get(user_id: Any, db: Any) -> UserIntegration:
            return integration

        monkeypatch.setattr(github_auth_service, "get_integration", fake_get)

        async with _client(authed_app) as client:
            response = await client.get("/integrations/github")

        assert response.status_code == 200
        assert response.json() == {
            "connected": True,
            "github_username": "testuser",
        }

    @pytest.mark.asyncio
    async def test_delete_when_unconnected_returns_204_idempotent(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_disconnect(user_id: Any, db: Any) -> None:
            return None

        monkeypatch.setattr(github_auth_service, "disconnect_github", fake_disconnect)

        async with _client(authed_app) as client:
            response = await client.delete(
                "/integrations/github", headers=_auth_headers()
            )
        assert response.status_code == 204


# ---------------------------------------------------------------------------
# TestGitHubExport
# ---------------------------------------------------------------------------


def _make_push_row(*, status: str, repo: str = "octocat/x", count: int = 5) -> Any:
    """Build a stub IntegrationPush with attached issue_count."""
    push = IntegrationPush(
        id=uuid4(),
        workspace_id=uuid4(),
        user_id=_USER_ID,
        provider="github",
        repo_full_name=repo,
        repo_url=f"https://github.com/{repo}",
        status=status,
        pushed_at=datetime.now(UTC) if status == "success" else None,
        created_at=datetime.now(UTC),
    )
    push.issue_count = count  # type: ignore[attr-defined]
    return push


class TestGitHubExport:
    """Cover POST and GET /workspaces/{id}/export/github + error mapping."""

    @pytest.mark.asyncio
    async def test_post_export_without_auth_returns_401(self, app: Any) -> None:
        async with _client(app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "x", "visibility": "public"},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_post_export_success_returns_202_with_response_shape(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        push = _make_push_row(status="success", repo="octocat/proj", count=12)

        async def fake_push(**kwargs: Any) -> Any:
            return push

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "proj", "visibility": "private"},
                headers=_auth_headers(),
            )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "success"
        assert body["repo_full_name"] == "octocat/proj"
        assert body["issue_count"] == 12
        assert "push_id" in body

    @pytest.mark.asyncio
    async def test_post_export_not_connected_maps_to_403(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_push(**kwargs: Any) -> Any:
            raise GitHubNotConnectedError()

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "x", "visibility": "public"},
                headers=_auth_headers(),
            )
        assert response.status_code == 403
        assert "Connect from Settings" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_post_export_token_expired_maps_to_403(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_push(**kwargs: Any) -> Any:
            raise GitHubTokenExpiredError()

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "x", "visibility": "public"},
                headers=_auth_headers(),
            )
        assert response.status_code == 403
        assert "Reconnect" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_post_export_repo_exists_maps_to_409(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_push(**kwargs: Any) -> Any:
            raise GitHubRepoExistsError()

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "dup", "visibility": "public"},
                headers=_auth_headers(),
            )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_post_export_not_ready_maps_to_409(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_push(**kwargs: Any) -> Any:
            raise ExportNotReadyError("Stage 'tasks' is not finalised")

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "x", "visibility": "public"},
                headers=_auth_headers(),
            )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_post_export_rate_limit_error_maps_to_429(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_push(**kwargs: Any) -> Any:
            raise GitHubRateLimitError()

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "x", "visibility": "public"},
                headers=_auth_headers(),
            )
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_post_export_api_error_maps_to_502(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_push(**kwargs: Any) -> Any:
            raise GitHubAPIError(500, "boom")

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        async with _client(authed_app) as client:
            response = await client.post(
                f"/workspaces/{_workspace_id()}/export/github",
                json={"repo_name": "x", "visibility": "public"},
                headers=_auth_headers(),
            )
        assert response.status_code == 502
        assert "unexpected" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_export_no_prior_push_returns_404(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_get(workspace_id: Any, user_id: Any, db: Any) -> None:
            return None

        monkeypatch.setattr(github_export_service, "get_push", fake_get)

        async with _client(authed_app) as client:
            response = await client.get(f"/workspaces/{_workspace_id()}/export/github")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_export_returns_push_when_present(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        push = _make_push_row(status="success", count=42)

        async def fake_get(workspace_id: Any, user_id: Any, db: Any) -> Any:
            return push

        monkeypatch.setattr(github_export_service, "get_push", fake_get)

        async with _client(authed_app) as client:
            response = await client.get(f"/workspaces/{_workspace_id()}/export/github")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["repo_full_name"] == "octocat/x"
        assert body["issue_count"] == 42


# ---------------------------------------------------------------------------
# TestGitHubRateLimit
# ---------------------------------------------------------------------------


class TestGitHubRateLimit:
    """Cover the 3 exports/user/hour tier and confirm ZIP is unaffected."""

    @pytest.mark.asyncio
    async def test_fourth_post_returns_429_with_rate_limit_detail(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        push = _make_push_row(status="success", count=0)

        async def fake_push(**kwargs: Any) -> Any:
            return push

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)

        ws_id = _workspace_id()
        headers = _auth_headers(real_jwt=True)
        async with _client(authed_app) as client:
            # 3 successful calls
            for _ in range(3):
                response = await client.post(
                    f"/workspaces/{ws_id}/export/github",
                    json={"repo_name": "x", "visibility": "public"},
                    headers=headers,
                )
                assert response.status_code == 202

            # 4th call hits the rate limit before reaching the service
            response = await client.post(
                f"/workspaces/{ws_id}/export/github",
                json={"repo_name": "x", "visibility": "public"},
                headers=headers,
            )
        assert response.status_code == 429
        assert "Maximum 3 exports" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_zip_export_is_not_covered_by_github_tier(
        self, authed_app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ZIP /export and GitHub /export/github use independent buckets.

        Exhausting the GitHub tier must not lock the user out of ZIP
        downloads.
        """
        push = _make_push_row(status="success", count=0)

        async def fake_push(**kwargs: Any) -> Any:
            return push

        async def fake_build_export(*args: Any, **kwargs: Any) -> bytes:
            return b"PK\x03\x04 fake zip bytes"

        monkeypatch.setattr(github_export_service, "push_to_github", fake_push)
        monkeypatch.setattr(
            "services.pipeline.export_service.build_export", fake_build_export
        )
        monkeypatch.setattr("routers.workspace.build_export", fake_build_export)

        ws_id = _workspace_id()
        headers = _auth_headers(real_jwt=True)
        async with _client(authed_app) as client:
            # Exhaust the GitHub tier
            for _ in range(3):
                await client.post(
                    f"/workspaces/{ws_id}/export/github",
                    json={"repo_name": "x", "visibility": "public"},
                    headers=headers,
                )
            # ZIP export must still succeed
            zip_response = await client.post(
                f"/workspaces/{ws_id}/export",
                headers=headers,
            )
        assert zip_response.status_code == 200
        assert zip_response.headers["content-type"] == "application/zip"
