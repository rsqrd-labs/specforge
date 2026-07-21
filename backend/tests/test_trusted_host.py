"""TrustedHostMiddleware enforcement (F3 — issue #42).

The Host allowlist is enforced in production only. Dev/CI leave ALLOWED_HOSTS
empty so the middleware is not added and local/compose flows on arbitrary hosts
keep working; production requires a non-empty list (validate_production_settings).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from config import settings
from main import create_app

_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
_REAL_ENCRYPTION_KEY = "cmVhbC1rZXktZm9yLXRlc3RpbmctbXVzdC1iZS1sb25n"

_PROD_PATCHES = {
    "environment": "production",
    "metrics_token": "metrics-token",
    "frontend_url": "https://app.example.com",
    "jwt_private_key": _FAKE_PEM,
    "encryption_master_key": _REAL_ENCRYPTION_KEY,
    "allowed_hosts": "app.example.com,*.internal.railway.app",
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


def _prod_ctx():
    return patch.multiple(settings, **_PROD_PATCHES)


def test_production_rejects_untrusted_host() -> None:
    """A Host outside ALLOWED_HOSTS is rejected with 400 in production."""
    with _prod_ctx():
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health", headers={"Host": "evil.example.com"})
    assert response.status_code == 400


def test_production_allows_trusted_host() -> None:
    """The configured app host passes TrustedHost in production."""
    with _prod_ctx():
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health", headers={"Host": "app.example.com"})
    assert response.status_code in {200, 503}


def test_production_allows_subdomain_wildcard_host() -> None:
    """A leading-dot allowlist entry matches subdomains (Railway healthcheck)."""
    with _prod_ctx():
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health", headers={"Host": "web.internal.railway.app"})
    assert response.status_code in {200, 503}


def test_development_does_not_enforce_host_allowlist() -> None:
    """In development the middleware is not added — arbitrary hosts pass."""
    with patch.object(settings, "environment", "development"):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/health", headers={"Host": "anything.local"})
    assert response.status_code in {200, 503}
