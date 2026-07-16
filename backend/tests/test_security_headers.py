from __future__ import annotations

from unittest.mock import patch

from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from config import settings
from main import create_app

_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
_REAL_ENCRYPTION_KEY = "cmVhbC1rZXktZm9yLXRlc3RpbmctbXVzdC1iZS1sb25n"

_PRODUCTION_PATCHES = {
    "environment": "production",
    "metrics_token": "metrics-token",
    "frontend_url": "https://app.example.com",
    "jwt_private_key": _FAKE_PEM,
    "encryption_master_key": _REAL_ENCRYPTION_KEY,
}


class _NoopPipeline:
    def zremrangebyscore(self, *args):
        return self

    def zadd(self, *args):
        return self

    def zcard(self, *args):
        return self

    def expire(self, *args):
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _NoopRedis:
    async def eval(self, *args, **kwargs) -> int:
        return 1

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


def test_security_headers_are_set_on_api_responses() -> None:
    with patch.object(settings, "environment", "development"):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health")

    assert response.status_code in {200, 503}
    assert response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in response.headers
    assert "Strict-Transport-Security" not in response.headers


def test_oversized_request_body_is_rejected_before_route_parsing() -> None:
    with (
        patch.object(settings, "environment", "development"),
        patch.object(settings, "max_request_body_bytes", 16),
    ):
        app = create_app(redis_client=_NoopRedis())

        @app.post("/echo")
        async def echo(payload: dict) -> dict:
            return payload

        client = TestClient(app)
        response = client.post("/echo", content=b"x" * 17)

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


def test_hsts_is_set_in_production() -> None:
    with (
        patch.object(settings, "environment", _PRODUCTION_PATCHES["environment"]),
        patch.object(settings, "metrics_token", _PRODUCTION_PATCHES["metrics_token"]),
        patch.object(settings, "frontend_url", _PRODUCTION_PATCHES["frontend_url"]),
        patch.object(
            settings,
            "jwt_private_key",
            _PRODUCTION_PATCHES["jwt_private_key"],
        ),
        patch.object(
            settings,
            "encryption_master_key",
            _PRODUCTION_PATCHES["encryption_master_key"],
        ),
    ):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health")

    assert response.status_code in {200, 503}
    assert response.headers["Strict-Transport-Security"].startswith("max-age=31536000")


def test_security_headers_are_set_on_unhandled_500_responses() -> None:
    app = create_app(redis_client=_NoopRedis())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("sensitive internal detail")

    with patch.object(settings, "environment", "development"):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_authenticated_response_is_marked_no_store() -> None:
    # F1: any request carrying an Authorization: Bearer header (all signed-in JSON
    # reads) must come back uncacheable so a shared cache / bfcache never retains it.
    app = create_app(redis_client=_NoopRedis())

    @app.get("/whoami")
    async def whoami() -> dict:
        return {"ok": True}

    with patch.object(settings, "environment", "development"):
        client = TestClient(app)
        response = client.get("/whoami", headers={"Authorization": "Bearer x.y.z"})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_unauthenticated_response_is_not_forced_no_store() -> None:
    # A public GET with no Authorization is left cacheable (public share / templates
    # opt into their own caching); the middleware must not blanket every response.
    app = create_app(redis_client=_NoopRedis())

    @app.get("/public-thing")
    async def public_thing() -> dict:
        return {"ok": True}

    with patch.object(settings, "environment", "development"):
        client = TestClient(app)
        response = client.get("/public-thing")

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") != "no-store"


def test_no_store_does_not_override_explicit_cache_control() -> None:
    # setdefault: an endpoint that deliberately opts into caching keeps its header
    # even when the request is authenticated.
    app = create_app(redis_client=_NoopRedis())

    @app.get("/cached")
    async def cached() -> Response:
        return JSONResponse({"ok": True}, headers={"Cache-Control": "max-age=60"})

    with patch.object(settings, "environment", "development"):
        client = TestClient(app)
        response = client.get("/cached", headers={"Authorization": "Bearer x.y.z"})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "max-age=60"


def test_token_issuing_paths_are_no_store_without_authorization() -> None:
    # /auth/callback and /auth/refresh return credentials in the body but carry no
    # Authorization header, so they're covered by the path list, not the header rule.
    app = create_app(redis_client=_NoopRedis())
    with patch.object(settings, "environment", "development"):
        client = TestClient(app)
        # Missing refresh cookie → 401, but the no-store header is applied regardless.
        response = client.post("/auth/refresh")

    assert response.headers.get("Cache-Control") == "no-store"


def test_docs_are_disabled_in_production() -> None:
    with (
        patch.object(settings, "environment", _PRODUCTION_PATCHES["environment"]),
        patch.object(settings, "metrics_token", _PRODUCTION_PATCHES["metrics_token"]),
        patch.object(settings, "frontend_url", _PRODUCTION_PATCHES["frontend_url"]),
        patch.object(
            settings,
            "jwt_private_key",
            _PRODUCTION_PATCHES["jwt_private_key"],
        ),
        patch.object(
            settings,
            "encryption_master_key",
            _PRODUCTION_PATCHES["encryption_master_key"],
        ),
    ):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_docs_are_accessible_in_development() -> None:
    with patch.object(settings, "environment", "development"):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        assert client.get("/openapi.json").status_code == 200


def test_health_hides_dependency_detail_in_production() -> None:
    with (
        patch.object(settings, "environment", _PRODUCTION_PATCHES["environment"]),
        patch.object(settings, "metrics_token", _PRODUCTION_PATCHES["metrics_token"]),
        patch.object(settings, "frontend_url", _PRODUCTION_PATCHES["frontend_url"]),
        patch.object(
            settings,
            "jwt_private_key",
            _PRODUCTION_PATCHES["jwt_private_key"],
        ),
        patch.object(
            settings,
            "encryption_master_key",
            _PRODUCTION_PATCHES["encryption_master_key"],
        ),
        patch("main.check_database", return_value="ok"),
        patch("main.check_redis", return_value="ok"),
    ):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}
