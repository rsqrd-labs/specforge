from __future__ import annotations

from unittest.mock import patch

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
        response = client.get("/providers")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in response.headers
    assert "Strict-Transport-Security" not in response.headers


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
        response = client.get("/providers")

    assert response.status_code == 200
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
