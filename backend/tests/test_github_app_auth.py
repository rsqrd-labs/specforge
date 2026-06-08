"""Unit tests for the GitHub App credential core (T-267).

No real network and no real Redis: the mint HTTP call is served by an httpx
``MockTransport`` (or the auth object's mint method is replaced), and the cache
runs against a tiny in-memory async fake. Security-critical, so the tests pin
the load-bearing behaviour: RS256 + short-lived JWT, refresh-ahead caching, and
that failures never leak the token or JWT.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.integrations.github_app_auth import (
    GitHubAppAuth,
    GitHubAppAuthError,
    TokenProvider,
    _cache_key,
)
from services.observability import GITHUB_TOKEN_MINT_TOTAL
from services.security import key_vault

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


class _FakeRedis:
    """Minimal async Redis stand-in: get / set(ex) / delete, decode_responses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ex_calls: list[tuple[str, int]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.ex_calls.append((key, ex))

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _mint_transport(token: str, expires_at: datetime) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/access_tokens")
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            201,
            json={
                "token": token,
                "expires_at": expires_at.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# App JWT
# ---------------------------------------------------------------------------


async def test_app_jwt_is_rs256_and_short_lived(rsa_keypair: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_keypair
    async with httpx.AsyncClient() as client:
        auth = GitHubAppAuth(app_id="987654", private_key=private_pem, client=client)
        token = auth.app_jwt()

    # Header advertises RS256.
    assert jwt.get_unverified_header(token)["alg"] == "RS256"

    # Verifies against the matching public key (round-trip proves a valid JWS).
    claims = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert claims["iss"] == "987654"

    now = int(datetime.now(UTC).timestamp())
    # iat is backdated ~60s for clock skew.
    assert 58 <= now - claims["iat"] <= 62
    # exp is short-lived: ~540s ahead of issue and never more than GitHub's
    # 10-minute (600s) cap.
    assert 535 <= claims["exp"] - now <= 540
    # Full validity window = 540s forward + 60s backdate = 600s (the cap).
    assert claims["exp"] - claims["iat"] == 600


async def test_mint_installation_token_parses_201(
    rsa_keypair: tuple[str, str],
) -> None:
    private_pem, _ = rsa_keypair
    expires = datetime.now(UTC) + timedelta(hours=1)
    transport = _mint_transport("ghs_minted", expires)
    async with httpx.AsyncClient(transport=transport) as client:
        auth = GitHubAppAuth(app_id="1", private_key=private_pem, client=client)
        token, expires_at = await auth.mint_installation_token(42)

    assert token == "ghs_minted"
    assert expires_at.tzinfo is not None
    assert abs((expires_at - expires).total_seconds()) < 1


async def test_mint_failure_raises_without_leaking_secrets(
    rsa_keypair: tuple[str, str],
) -> None:
    private_pem, _ = rsa_keypair

    def handler(request: httpx.Request) -> httpx.Response:
        # A body that, if echoed, would leak the request's bearer JWT context.
        return httpx.Response(403, json={"message": "Bad credentials: ghs_leak"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        auth = GitHubAppAuth(app_id="1", private_key=private_pem, client=client)
        with pytest.raises(GitHubAppAuthError) as exc:
            await auth.mint_installation_token(42)

    message = str(exc.value)
    assert exc.value.status == 403
    assert "ghs_leak" not in message
    assert "Bearer" not in message


# ---------------------------------------------------------------------------
# TokenProvider cache + refresh-ahead
# ---------------------------------------------------------------------------


class _CountingAuth:
    """Stands in for GitHubAppAuth.mint_installation_token, counting calls."""

    def __init__(self, lifetime_seconds: int = 3600) -> None:
        self.calls = 0
        self._lifetime = lifetime_seconds

    async def mint_installation_token(
        self, installation_id: int
    ) -> tuple[str, datetime]:
        self.calls += 1
        expires_at = datetime.now(UTC) + timedelta(seconds=self._lifetime)
        return f"tok-{self.calls}", expires_at


async def test_token_provider_caches_and_refreshes_ahead() -> None:
    auth = _CountingAuth(lifetime_seconds=3600)
    redis = _FakeRedis()
    provider = TokenProvider(auth, redis)  # type: ignore[arg-type]

    mint_before = GITHUB_TOKEN_MINT_TOTAL.labels(source="mint")._value.get()
    cache_before = GITHUB_TOKEN_MINT_TOTAL.labels(source="cache")._value.get()

    # 1) First get → mint exactly once.
    first = await provider.get(101)
    assert first == "tok-1"
    assert auth.calls == 1
    assert GITHUB_TOKEN_MINT_TOTAL.labels(source="mint")._value.get() == mint_before + 1

    # 2) The cache TTL is set refresh-ahead: token lifetime (3600) minus the
    #    300s margin (int() truncation may shave a second off the elapsed time).
    assert len(redis.ex_calls) == 1
    key, ttl = redis.ex_calls[0]
    assert key == _cache_key(101)
    assert 3600 - 300 - 2 <= ttl <= 3600 - 300
    # Stored value is encrypted at rest, not the raw token.
    stored = redis.store[_cache_key(101)]
    assert stored != "tok-1"
    assert key_vault.decrypt(stored) == "tok-1"

    # 3) Second get within TTL → cache hit, no re-mint.
    second = await provider.get(101)
    assert second == "tok-1"
    assert auth.calls == 1
    assert (
        GITHUB_TOKEN_MINT_TOTAL.labels(source="cache")._value.get() == cache_before + 1
    )

    # 4) When the entry expires (refresh-ahead window reached) → re-mint.
    await redis.delete(_cache_key(101))
    third = await provider.get(101)
    assert third == "tok-2"
    assert auth.calls == 2


async def test_near_expiry_token_is_not_cached_past_its_refresh_window() -> None:
    # A token whose whole life is shorter than the refresh-ahead margin must not
    # be cached (TTL would be <= 0): every get re-mints rather than serving a
    # token about to expire.
    auth = _CountingAuth(lifetime_seconds=120)  # < 300s refresh-ahead
    redis = _FakeRedis()
    provider = TokenProvider(auth, redis)  # type: ignore[arg-type]

    await provider.get(202)
    assert auth.calls == 1
    assert redis.ex_calls == []  # nothing cached
    assert _cache_key(202) not in redis.store

    await provider.get(202)
    assert auth.calls == 2


async def test_refresh_invalidates_cache_and_re_mints() -> None:
    # refresh() is the seam the API client uses after a 401: it must drop the
    # cached token and mint a fresh one, even though the cached entry is still
    # within its TTL.
    auth = _CountingAuth(lifetime_seconds=3600)
    redis = _FakeRedis()
    provider = TokenProvider(auth, redis)  # type: ignore[arg-type]

    first = await provider.get(303)
    assert first == "tok-1"
    assert auth.calls == 1
    assert _cache_key(303) in redis.store  # cached and still fresh

    refreshed = await provider.refresh(303)
    assert refreshed == "tok-2"  # a genuinely new mint, not the cached value
    assert auth.calls == 2
    # The new token is what a subsequent get() now serves from cache.
    assert await provider.get(303) == "tok-2"
    assert auth.calls == 2
