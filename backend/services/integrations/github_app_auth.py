"""GitHub App credential core (Phase 21 — T-267, spec §8).

Three distinct credentials, never conflated:

1. **App JWT** — a short-lived RS256 JWT signed with the App private key. It
   authenticates *App-level* calls only (notably minting installation tokens).
   It is *not* a repository credential.
2. **Installation access token** — minted per installation via
   ``POST /app/installations/{id}/access_tokens`` using the App JWT. This is the
   credential that does all repository work (T-268+). It has a ~1-hour TTL.
3. (A user-to-server identity token, used elsewhere only to learn the installer's
   username for display, is out of scope here.)

This module holds **no business logic and performs no DB writes**. The App
private key is read from ``settings.github_app_private_key`` (a secret-manager
value) and is *never* read from or written to the database.

Security invariants:
  - The App private key, the signed App JWT, and any minted installation token
    are credentials: they are never written to logs, exception messages, or
    audit fields. The mint failure path raises status + a generic message only.
  - Installation tokens are cached server-side (Redis key
    ``gh:inst_token:{installation_id}``) Fernet-encrypted at rest. The cache key
    TTL is set to expire ``_REFRESH_AHEAD_SECONDS`` *before* the token itself, so
    a cache hit always yields a token with comfortable life remaining
    (refresh-ahead) and minting — which GitHub itself rate-limits — stays off the
    hot path. This makes the cache mandatory, not optional.

Observability: every resolution increments
``specforge_github_token_mint_total{source="mint"|"cache"}``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from jose import jwt
from redis.asyncio import Redis

from config import settings
from services.observability import GITHUB_TOKEN_MINT_TOTAL
from services.security import key_vault

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
_GITHUB_ACCEPT = "application/vnd.github+json"
_GITHUB_API_VERSION = "2022-11-28"
_MINT_TIMEOUT_SECONDS = 15.0

# App JWT lifetime: GitHub caps it at 10 minutes. We use 9 minutes (540s) for
# margin and backdate ``iat`` 60s to absorb clock skew between us and GitHub.
_JWT_LIFETIME_SECONDS = 540
_JWT_CLOCK_SKEW_SECONDS = 60

# Installation token cache. Tokens live ~1 hour on GitHub's side; we expire the
# cache entry _REFRESH_AHEAD_SECONDS earlier so a hit is always safely fresh.
_CACHE_KEY_PREFIX = "gh:inst_token:"
_REFRESH_AHEAD_SECONDS = 300  # 5 minutes


class GitHubAppAuthError(Exception):
    """An App-level auth operation failed (e.g. token minting returned non-201).

    The message is intentionally generic — it never carries the App JWT, a
    minted token, or the raw GitHub response body.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"GitHub App auth error {status}: {detail}")
        self.status = status


def _cache_key(installation_id: int) -> str:
    return f"{_CACHE_KEY_PREFIX}{installation_id}"


class GitHubAppAuth:
    """Signs the App JWT and mints installation tokens.

    The ``httpx.AsyncClient`` is injected (never constructed here) so the caller
    owns its lifecycle and tests can supply a ``MockTransport``.
    """

    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._client = client

    @classmethod
    def from_settings(cls, client: httpx.AsyncClient) -> "GitHubAppAuth":
        """Build from the configured App id + private key (secret manager)."""
        return cls(
            app_id=settings.github_app_id,
            private_key=settings.github_app_private_key,
            client=client,
        )

    def app_jwt(self) -> str:
        """Return a freshly signed, short-lived RS256 App JWT.

        Claims use integer POSIX timestamps (GitHub requires NumericDate):
        ``iss`` = the App id, ``iat`` = now − 60s (clock skew), ``exp`` = now +
        540s (≤ 10 min). Signed with the App private key from settings — never
        from the database.
        """
        now = datetime.now(UTC)
        claims = {
            "iss": self._app_id,
            "iat": int((now - timedelta(seconds=_JWT_CLOCK_SKEW_SECONDS)).timestamp()),
            "exp": int((now + timedelta(seconds=_JWT_LIFETIME_SECONDS)).timestamp()),
        }
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    async def mint_installation_token(
        self, installation_id: int
    ) -> tuple[str, datetime]:
        """Mint a fresh installation access token for ``installation_id``.

        Authenticated with the App JWT. Returns ``(token, expires_at)`` where
        ``expires_at`` is a timezone-aware UTC datetime. Raises
        :class:`GitHubAppAuthError` on any non-201 response — without leaking the
        JWT or the response body.
        """
        response = await self._client.post(
            f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self.app_jwt()}",
                "Accept": _GITHUB_ACCEPT,
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            },
            timeout=_MINT_TIMEOUT_SECONDS,
        )
        if response.status_code != 201:
            # Never include the response body or the App JWT — it may echo
            # request context. Status + a fixed message only.
            raise GitHubAppAuthError(
                response.status_code,
                "failed to mint installation token",
            )

        payload = response.json()
        token = payload["token"]
        expires_at = _parse_github_timestamp(payload["expires_at"])
        return token, expires_at


def _parse_github_timestamp(value: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp into a tz-aware UTC datetime.

    GitHub returns ``...Z``; normalise it so arithmetic against
    ``datetime.now(UTC)`` is always aware-vs-aware (never raises TypeError).
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class TokenProvider:
    """Resolves installation tokens with a refresh-ahead Redis cache.

    The cache entry is Fernet-encrypted and given a TTL that expires
    ``_REFRESH_AHEAD_SECONDS`` before the token itself, so any cache hit is
    guaranteed to have margin and a near-expiry token is treated as a miss and
    re-minted off the hot path.
    """

    def __init__(self, auth: GitHubAppAuth, redis: Redis) -> None:
        self._auth = auth
        self._redis = redis

    async def get(self, installation_id: int) -> str:
        """Return a valid installation token, minting and caching if needed."""
        key = _cache_key(installation_id)

        cached = await self._read_cache(key)
        if cached is not None:
            # specforge_github_token_mint_total{source="cache"}
            GITHUB_TOKEN_MINT_TOTAL.labels(source="cache").inc()
            return cached

        token, expires_at = await self._auth.mint_installation_token(installation_id)
        # specforge_github_token_mint_total{source="mint"}
        GITHUB_TOKEN_MINT_TOTAL.labels(source="mint").inc()

        ttl = self._cache_ttl(expires_at)
        if ttl > 0:
            await self._write_cache(key, token, ttl)
        return token

    async def refresh(self, installation_id: int) -> str:
        """Force a fresh mint, discarding any cached token.

        Used by the API client after a 401: GitHub may have rotated the
        installation token out from under a still-cached value, so the cache
        entry is invalidated and :meth:`get` re-mints. Bounded to one retry by
        the caller — SpecForge never loops on a known-invalid token.
        """
        await self._invalidate(installation_id)
        return await self.get(installation_id)

    async def _invalidate(self, installation_id: int) -> None:
        """Drop the cached token for an installation (best-effort)."""
        try:
            await self._redis.delete(_cache_key(installation_id))
        except Exception:  # pragma: no cover — Redis transport failure
            logger.warning("github token cache invalidation failed")

    @staticmethod
    def _cache_ttl(expires_at: datetime) -> int:
        """Seconds to cache: token lifetime minus the refresh-ahead margin."""
        lifetime = (expires_at - datetime.now(UTC)).total_seconds()
        return int(lifetime) - _REFRESH_AHEAD_SECONDS

    async def _read_cache(self, key: str) -> str | None:
        """Return the decrypted cached token, or None on miss / unusable entry.

        Cache failures never raise into the caller: on a Redis error we log a
        non-sensitive warning and fall through to minting, so a degraded cache
        cannot brick GitHub operations (it only loses rate-limit protection).
        """
        try:
            ciphertext = await self._redis.get(key)
        except Exception:  # pragma: no cover — Redis transport failure
            logger.warning("github token cache read failed; will mint")
            return None
        if ciphertext is None:
            return None
        try:
            return key_vault.decrypt(ciphertext)
        except key_vault.DecryptionError:
            # Corrupt/rotated-key entry — treat as a miss and re-mint.
            logger.warning("github token cache entry undecryptable; will re-mint")
            return None

    async def _write_cache(self, key: str, token: str, ttl: int) -> None:
        """Encrypt and cache the token with the refresh-ahead TTL (best-effort)."""
        try:
            await self._redis.set(key, key_vault.encrypt(token), ex=ttl)
        except Exception:  # pragma: no cover — Redis transport failure
            logger.warning("github token cache write failed")


def make_token_provider(redis: Redis, client: httpx.AsyncClient) -> TokenProvider:
    """Build a TokenProvider from configured App credentials and shared clients."""
    return TokenProvider(GitHubAppAuth.from_settings(client), redis)
