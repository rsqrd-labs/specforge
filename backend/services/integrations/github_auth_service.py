"""GitHub OAuth flow.

Provides three async entry points:

- ``get_github_oauth_url(user_id, redis)`` — generates a CSRF state bound to
  the authenticated user and returns the GitHub authorize URL.
- ``handle_github_callback(code, state, db, redis)`` — validates state,
  exchanges code for an access token, encrypts it with the existing Fernet
  key vault, and upserts a UserIntegration row.
- ``disconnect_github(user_id, db)`` — removes the user's GitHub integration.

Design notes:

- The OAuth callback is authenticated solely by the state parameter (looked
  up in Redis), not by a JWT. A redirect from GitHub cannot carry the
  in-memory access token, and the state binding is the canonical OAuth CSRF
  protection.
- All HTTP traffic uses httpx.AsyncClient with a 10-second timeout. Network
  failures raise ``AuthError`` so the router can return a clean 502.
- The Fernet key vault is reused (same master key as user LLM keys) — there
  is no separate secret for GitHub tokens.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.user_integration import UserIntegration
from services.auth_service import AuthError
from services.security import key_vault

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"  # nosec B105
GITHUB_USER_URL = "https://api.github.com/user"

OAUTH_STATE_PREFIX = "oauth_github_state:"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes
GITHUB_PROVIDER = "github"
GITHUB_OAUTH_SCOPES = "repo,read:user"

_HTTP_TIMEOUT_SECONDS = 10.0


async def get_github_oauth_url(user_id: UUID, redis: Any) -> str:
    """Generate the GitHub authorize URL with a fresh CSRF state.

    The state is bound to ``user_id`` in Redis with a 10-minute TTL. The
    callback handler validates this binding before accepting any code.
    """
    if not settings.github_client_id:
        raise AuthError("GitHub integration disabled")

    state = secrets.token_urlsafe(32)
    redirect_uri = _redirect_uri()

    payload = json.dumps({"user_id": str(user_id)})
    await redis.set(
        f"{OAUTH_STATE_PREFIX}{state}",
        payload,
        ex=OAUTH_STATE_TTL_SECONDS,
    )

    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": redirect_uri,
            "scope": GITHUB_OAUTH_SCOPES,
            "state": state,
            "allow_signup": "false",
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


async def handle_github_callback(
    code: str,
    state: str,
    db: AsyncSession,
    redis: Any,
) -> UserIntegration:
    """Complete the OAuth flow: validate state, exchange code, store token.

    State validation is constant-time-equivalent in practice because Redis
    looks up by the full key. A missing key or a key whose payload does not
    decode raises ``AuthError("invalid_state")`` so the router returns 400.
    """
    if not code or not state:
        raise AuthError("invalid_state")

    user_id = await _consume_state(state, redis)

    access_token = await _exchange_code_for_token(code)
    github_username = await _fetch_github_username(access_token)

    encrypted_token = key_vault.encrypt(access_token)
    return await _upsert_integration(
        db,
        user_id=user_id,
        encrypted_token=encrypted_token,
        github_username=github_username,
    )


async def disconnect_github(user_id: UUID, db: AsyncSession) -> None:
    """Delete the user's GitHub integration row. Idempotent."""
    await db.execute(
        delete(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider == GITHUB_PROVIDER,
        )
    )
    await db.commit()


async def begin_oauth(user_id: UUID, redis: Any) -> str:
    """Compatibility alias for the Phase-13 OAuth entry point."""
    return await get_github_oauth_url(user_id, redis)


async def complete_oauth(
    code: str,
    state: str,
    db: AsyncSession,
    redis: Any,
) -> UserIntegration:
    """Compatibility alias for the Phase-13 OAuth callback entry point."""
    return await handle_github_callback(code, state, db, redis)


async def revoke(user_id: UUID, db: AsyncSession) -> None:
    """Compatibility alias for the Phase-13 disconnect entry point."""
    await disconnect_github(user_id, db)


async def get_integration(
    user_id: UUID,
    db: AsyncSession,
) -> UserIntegration | None:
    """Return the user's GitHub integration row, or None if absent."""
    result = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider == GITHUB_PROVIDER,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _redirect_uri() -> str:
    """Resolve the OAuth callback URL.

    The frontend hits ``GET /auth/github`` to initiate, but the callback URL
    registered with the GitHub OAuth App must be a backend URL because the
    backend is the only party with the client_secret.
    """
    base = settings.frontend_url.rstrip("/")
    # In development the frontend proxies /api to the backend, so the
    # callback flows through Vite to the backend route /auth/github/callback.
    return f"{base}/auth/github/callback"


async def _consume_state(state: str, redis: Any) -> UUID:
    key = f"{OAUTH_STATE_PREFIX}{state}"
    raw = await redis.get(key)
    if raw is None:
        raise AuthError("invalid_state")

    # Best-effort delete; ignore failures since the TTL will clean up anyway.
    try:
        await redis.delete(key)
    except Exception:  # pragma: no cover — defensive
        logger.warning("github_oauth.state_delete_failed", exc_info=True)

    try:
        payload = json.loads(raw)
        user_id = UUID(payload["user_id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise AuthError("invalid_state") from exc

    return user_id


async def _exchange_code_for_token(code: str) -> str:
    """POST the auth code to GitHub and return the access_token string."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": _redirect_uri(),
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise AuthError("github_token_exchange_failed") from exc

    if response.status_code != 200:
        raise AuthError(f"github_token_exchange_failed: status={response.status_code}")

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise AuthError("github_token_exchange_failed") from exc

    if isinstance(body, dict) and body.get("error"):
        raise AuthError(f"github_token_exchange_failed: {body['error']}")

    access_token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise AuthError("github_token_exchange_failed: missing access_token")
    return access_token


async def _fetch_github_username(access_token: str) -> str | None:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
        except httpx.HTTPError as exc:
            raise AuthError("github_user_fetch_failed") from exc

    if response.status_code != 200:
        # Don't leak the token; just propagate a generic failure.
        raise AuthError(f"github_user_fetch_failed: status={response.status_code}")

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise AuthError("github_user_fetch_failed") from exc

    login = body.get("login") if isinstance(body, dict) else None
    if isinstance(login, str) and login:
        return login
    return None


async def _upsert_integration(
    db: AsyncSession,
    *,
    user_id: UUID,
    encrypted_token: str,
    github_username: str | None,
) -> UserIntegration:
    stmt = (
        insert(UserIntegration)
        .values(
            user_id=user_id,
            provider=GITHUB_PROVIDER,
            encrypted_token=encrypted_token,
            github_username=github_username,
        )
        .on_conflict_do_update(
            constraint="uq_user_integration_provider",
            set_={
                "encrypted_token": encrypted_token,
                "github_username": github_username,
            },
        )
        .returning(UserIntegration)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    await db.commit()
    await db.refresh(row)
    return row
