"""GitHub App install + lifecycle helpers (Phase 21 — T-270).

Owns the v2 (GitHub **App**) connection lifecycle, replacing the Phase-13
per-user OAuth *connect* step (which is retained, behind a flag, for migration —
``github_auth_service`` is untouched). Responsibilities:

  - build the install URL with a one-time, user-bound state (reuses the Phase-13
    Redis state pattern);
  - complete the install callback by upserting a :class:`GitHubInstallation`
    (account/login/type/repository_selection learned from GitHub via the App
    JWT — no second OAuth flow);
  - list a user's installations and whether they are still on the legacy OAuth
    path (migration prompt);
  - revoke an installation locally;
  - apply lifecycle webhook events (``installation`` suspend/unsuspend/deleted,
    ``installation_repositories`` added/removed), marking affected pushes
    ``stale`` so the UI can surface "sync paused" and re-export re-binds the row.

The install row is the source of truth for which repositories the App may act
on — it feeds the confused-deputy guard (T-272). Tokens, the App private key,
and raw payloads are never logged or persisted here.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import GitHubInstallation, IntegrationPush, UserIntegration
from services.integrations.github_api_client import (
    GITHUB_API_BASE,
    make_shared_async_client,
)
from services.integrations.github_app_auth import GitHubAppAuth
from services.observability import (
    GITHUB_AUDIT_INSTALLED,
    GITHUB_AUDIT_SYNC_PAUSED,
    GITHUB_AUDIT_UNINSTALLED,
    github_audit,
)

logger = logging.getLogger(__name__)

GITHUB_PROVIDER = "github"

# One-time install state, bound to the initiating user in Redis (10-min TTL),
# mirroring the Phase-13 OAuth state pattern (github_auth_service).
INSTALL_STATE_PREFIX = "github_app_install_state:"
INSTALL_STATE_TTL_SECONDS = 600

# One-time identity-verification state for the second OAuth hop (audit #1). It
# binds {user_id, installation_id} so the verify callback knows *which* install
# the returning ``code`` is meant to confirm. Same TTL as the install state.
IDENTITY_STATE_PREFIX = "github_app_identity_state:"
IDENTITY_STATE_TTL_SECONDS = 600

_GITHUB_ACCEPT = "application/vnd.github+json"
_GITHUB_API_VERSION = "2022-11-28"
_INSTALL_FETCH_TIMEOUT_SECONDS = 15.0

# GitHub user-to-server (identity) OAuth endpoints. The App's own client
# id/secret authenticate these — never the App JWT or an installation token.
_GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"  # nosec B105
# /user/installations is paginated; an installer realistically has a handful of
# installations, but bound the scan so a hostile/huge response cannot loop us.
_IDENTITY_MAX_PAGES = 10


class AppNotConfiguredError(Exception):
    """The GitHub App is not configured (no slug/id) — install flow disabled."""


class InstallStateError(Exception):
    """The install callback state is missing, expired, or tampered with."""


class InstallVerificationError(Exception):
    """The installer could not be verified as an admin of the installation.

    Raised by the identity-OAuth verification path (audit #1) on any failure to
    prove the caller administers the installation's account: a code-exchange
    failure, an unreadable installation list, or the installation simply not
    appearing among the user's installations. The message is intentionally
    generic — it never carries the user token or the raw GitHub response.
    """


@dataclass(frozen=True)
class InstallationAccount:
    """The account facts learned from GitHub for an installation."""

    account_login: str
    account_type: str
    repository_selection: str


def app_install_enabled() -> bool:
    """True when the GitHub App is configured enough to offer the install flow."""
    return settings.github_app_enabled


def app_identity_enabled() -> bool:
    """True when the App's user-to-server identity OAuth is configured (audit #1).

    The install callback can only bind an installation to a user after verifying,
    via this identity OAuth, that the user administers the installation's account.
    When it is not configured the callback refuses to bind (fails closed).
    """
    return settings.github_app_identity_enabled


# ---------------------------------------------------------------------------
# Install URL + state
# ---------------------------------------------------------------------------


async def build_install_url(user_id: UUID, redis: Any) -> str:
    """Return the App install URL with a fresh user-bound state.

    Raises :class:`AppNotConfiguredError` when the App is not configured so the
    router can return 503 and the UI can render a "feature disabled" state.
    """
    if not app_install_enabled():
        raise AppNotConfiguredError("GitHub App is not configured")
    state = secrets.token_urlsafe(32)
    await redis.set(
        f"{INSTALL_STATE_PREFIX}{state}",
        str(user_id),
        ex=INSTALL_STATE_TTL_SECONDS,
    )
    return (
        f"https://github.com/apps/{settings.github_app_slug}"
        f"/installations/new?state={state}"
    )


async def consume_install_state(state: str | None, redis: Any) -> UUID:
    """Validate + consume the install state, returning the bound user id.

    Single-use: the key is deleted on read. A missing/expired/tampered state
    raises :class:`InstallStateError` so the callback rejects it (the state
    binding is the install-callback's CSRF protection).
    """
    if not state:
        raise InstallStateError("missing install state")
    key = f"{INSTALL_STATE_PREFIX}{state}"
    raw = await redis.get(key)
    if not raw:
        raise InstallStateError("invalid or expired install state")
    try:
        await redis.delete(key)
    except Exception:  # pragma: no cover — TTL reaps it anyway
        logger.warning("github_install.state_delete_failed")
    try:
        return UUID(raw)
    except (ValueError, TypeError) as exc:
        raise InstallStateError("malformed install state") from exc


# ---------------------------------------------------------------------------
# Identity verification (audit #1) — prove the installer administers the install
# ---------------------------------------------------------------------------


async def build_identity_verify_url(
    user_id: UUID, installation_id: int, redis: Any
) -> str:
    """Return the user-to-server authorize URL for the second (verify) hop.

    Used only when GitHub did *not* already include an OAuth ``code`` in the
    install redirect (i.e. "Request user authorization (OAuth) during
    installation" is off). Mints a one-time state binding
    ``{user_id, installation_id}`` so the verify callback can confirm the
    returning ``code`` is for this installation, then sends the browser to
    GitHub's authorize endpoint. GitHub redirects back to the App's configured
    callback URL (the setup endpoint) with a ``code``.
    """
    state = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"user_id": str(user_id), "installation_id": int(installation_id)}
    )
    await redis.set(
        f"{IDENTITY_STATE_PREFIX}{state}",
        payload,
        ex=IDENTITY_STATE_TTL_SECONDS,
    )
    query = urlencode(
        {
            "client_id": settings.github_app_client_id,
            "state": state,
            # Force a fresh authorization so a stale cached grant can't satisfy
            # the proof-of-control check for an installation the user no longer
            # administers.
            "allow_signup": "false",
        }
    )
    return f"{_GITHUB_OAUTH_AUTHORIZE_URL}?{query}"


async def consume_identity_state(
    state: str | None, redis: Any
) -> tuple[UUID, int] | None:
    """Validate + consume a verify-hop state, returning ``(user_id, install_id)``.

    Single-use (deleted on read). Returns ``None`` — never raises — when the
    state is absent, expired, or not an identity-verify state, so the setup
    callback can cleanly fall through to treating the request as a first-hop
    install redirect instead.
    """
    if not state:
        return None
    key = f"{IDENTITY_STATE_PREFIX}{state}"
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        await redis.delete(key)
    except Exception:  # pragma: no cover — TTL reaps it anyway
        logger.warning("github_install.identity_state_delete_failed")
    try:
        data = json.loads(raw)
        return UUID(data["user_id"]), int(data["installation_id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


async def exchange_identity_code(
    code: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Exchange an install/identity ``code`` for a user-to-server access token.

    Authenticated with the App's own client id/secret (never the App JWT). The
    returned token is a short-lived user credential used *only* to confirm the
    installer's access; it is never persisted or logged. Raises
    :class:`InstallVerificationError` on any failure, without leaking the code,
    the token, or the raw GitHub body.
    """
    owns_client = client is None
    http = client or make_shared_async_client()
    try:
        response = await http.post(
            _GITHUB_OAUTH_TOKEN_URL,
            data={
                "client_id": settings.github_app_client_id,
                "client_secret": settings.github_app_client_secret,
                "code": code,
            },
            # The OAuth token endpoint (github.com, NOT the api.github.com REST
            # API) defaults to a form-encoded body and only returns JSON when
            # asked with ``application/json`` — matching the legacy OAuth path
            # (github_auth_service). The REST ``vnd.github+json`` accept type here
            # would yield a form body that ``response.json()`` cannot parse.
            headers={"Accept": "application/json"},
            timeout=_INSTALL_FETCH_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise InstallVerificationError("identity code exchange failed") from exc
    finally:
        if owns_client:
            await http.aclose()
    if response.status_code != 200:
        raise InstallVerificationError("identity code exchange returned non-200")
    try:
        body = response.json()
    except ValueError as exc:
        msg = "identity code exchange returned non-JSON"
        raise InstallVerificationError(msg) from exc
    if not isinstance(body, dict) or body.get("error"):
        raise InstallVerificationError("identity code exchange returned an error")
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        raise InstallVerificationError("identity code exchange returned no token")
    return token


async def user_can_access_installation(
    user_token: str,
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """True iff ``installation_id`` is among the user's accessible installations.

    Calls ``GET /user/installations`` with the user-to-server token. GitHub only
    returns an installation here for an account the user **participates in** — their
    own personal account, or an organization where they are a member the
    installation is visible to (owners, and members granted access to a covered
    repository). That participation is the proof-of-control gate that closes the
    install-callback IDOR (audit #1): an external attacker holding only the
    enumerable numeric id is excluded. It is an *access* check, not strictly an
    *ownership/admin* check — the residual (an org member rebinding an
    installation to repos they already reach) is a minor in-org escalation, not
    the cross-tenant hijack the audit flagged. Paginated and bounded. Raises
    :class:`InstallVerificationError` if the list cannot be read (fail closed —
    an unreadable list must never be treated as "verified").
    """
    owns_client = client is None
    http = client or make_shared_async_client()
    try:
        for page in range(1, _IDENTITY_MAX_PAGES + 1):
            response = await http.get(
                f"{GITHUB_API_BASE}/user/installations?per_page=100&page={page}",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": _GITHUB_ACCEPT,
                    "X-GitHub-Api-Version": _GITHUB_API_VERSION,
                },
                timeout=_INSTALL_FETCH_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                raise InstallVerificationError("could not list user installations")
            payload = response.json()
            installations = (
                payload.get("installations") if isinstance(payload, dict) else None
            )
            if not isinstance(installations, list) or not installations:
                break
            for inst in installations:
                if isinstance(inst, dict) and inst.get("id") == installation_id:
                    return True
            if len(installations) < 100:
                break
    except httpx.HTTPError as exc:
        raise InstallVerificationError("could not list user installations") from exc
    finally:
        if owns_client:
            await http.aclose()
    return False


async def verify_installer_can_access(
    code: str,
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Exchange ``code`` and confirm the installer participates in the install.

    The composite proof-of-control check (audit #1): a single ``True`` here is
    the only thing that authorises (re)binding the installation row to a user.
    Returns ``False`` on a clean "no access" verdict; re-raises
    :class:`InstallVerificationError` on any inability to *determine* the verdict
    (both are treated as "do not bind" by the caller, but the distinction is kept
    for observability). See :func:`user_can_access_installation` for the exact
    (access, not strict-admin) semantics of the gate.
    """
    token = await exchange_identity_code(code, client=client)
    return await user_can_access_installation(token, installation_id, client=client)


# ---------------------------------------------------------------------------
# Install completion (callback) + GitHub account lookup
# ---------------------------------------------------------------------------


async def fetch_installation_account(
    installation_id: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> InstallationAccount:
    """Fetch account facts for an installation from GitHub (App-JWT auth).

    ``GET /app/installations/{id}`` returns the account login/type and
    repository_selection. No identity OAuth is needed. Injectable ``client`` for
    tests; production builds the bounded shared client.
    """
    owns_client = client is None
    http = client or make_shared_async_client()
    try:
        auth = GitHubAppAuth.from_settings(http)
        response = await http.get(
            f"{GITHUB_API_BASE}/app/installations/{installation_id}",
            headers={
                "Authorization": f"Bearer {auth.app_jwt()}",
                "Accept": _GITHUB_ACCEPT,
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            },
            timeout=_INSTALL_FETCH_TIMEOUT_SECONDS,
        )
    finally:
        if owns_client:
            await http.aclose()
    if response.status_code != 200:
        raise InstallStateError(
            f"could not read installation {installation_id} from GitHub"
        )
    payload = response.json()
    account = payload.get("account") or {}
    return InstallationAccount(
        account_login=str(account.get("login") or ""),
        account_type=str(account.get("type") or "User"),
        repository_selection=str(payload.get("repository_selection") or "all"),
    )


async def upsert_installation(
    db: AsyncSession,
    *,
    installation_id: int,
    user_id: UUID,
    account: InstallationAccount,
) -> GitHubInstallation:
    """Insert or update the installation row, (re)binding it to ``user_id``.

    Keyed on GitHub's unique numeric ``installation_id``; a re-install clears any
    prior ``suspended_at`` so a previously-disconnected install becomes live
    again.
    """
    result = await db.execute(
        select(GitHubInstallation).where(
            GitHubInstallation.installation_id == installation_id
        )
    )
    row = result.scalar_one_or_none()
    created = row is None
    if row is None:
        row = GitHubInstallation(
            installation_id=installation_id,
            account_login=account.account_login,
            account_type=account.account_type,
            repository_selection=account.repository_selection,
            user_id=user_id,
        )
        db.add(row)
    else:
        row.account_login = account.account_login
        row.account_type = account.account_type
        row.repository_selection = account.repository_selection
        row.user_id = user_id
        row.suspended_at = None
    await db.commit()
    await db.refresh(row)
    github_audit(
        GITHUB_AUDIT_INSTALLED,
        installation_id=installation_id,
        action="created" if created else "updated",
        status="active",
    )
    return row


# ---------------------------------------------------------------------------
# Listing / revoke
# ---------------------------------------------------------------------------


async def list_installations(
    db: AsyncSession, user_id: UUID
) -> list[GitHubInstallation]:
    """Return the user's installations (org + personal), newest first."""
    result = await db.execute(
        select(GitHubInstallation)
        .where(GitHubInstallation.user_id == user_id)
        .order_by(GitHubInstallation.created_at.desc())
    )
    return list(result.scalars())


async def user_on_legacy_oauth(db: AsyncSession, user_id: UUID) -> bool:
    """True when the user still holds a v1 OAuth token (offer migration)."""
    result = await db.execute(
        select(UserIntegration.id).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider == GITHUB_PROVIDER,
        )
    )
    return result.scalar_one_or_none() is not None


async def revoke_installation(
    db: AsyncSession, installation_row_id: UUID, user_id: UUID
) -> bool:
    """Locally revoke (delete) an installation the user owns.

    GitHub repos/issues are unaffected — this only forgets the install on our
    side. Dependent pushes are detached and marked ``stale`` first so the FK
    permits the delete and the UI shows "sync paused". Returns False when the
    install does not exist or is not owned by the caller (confused-deputy guard).
    """
    result = await db.execute(
        select(GitHubInstallation).where(GitHubInstallation.id == installation_row_id)
    )
    row = result.scalar_one_or_none()
    if row is None or row.user_id != user_id:
        return False
    await _detach_and_stale_pushes(db, row.id)
    await db.delete(row)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Lifecycle webhook application (dispatched from T-271's reconcile path)
# ---------------------------------------------------------------------------


async def apply_installation_event(
    db: AsyncSession,
    *,
    action: str,
    installation_id: int,
) -> None:
    """Apply an ``installation`` lifecycle action to the stored install row.

    ``suspend`` → set ``suspended_at`` and mark the install's pushes ``stale``;
    ``unsuspend`` → clear ``suspended_at``; ``deleted`` → detach + ``stale`` the
    pushes and remove the row. Unknown installs are ignored (we never installed
    them). ``stale`` (not ``failed``) keeps the push "live" so the repo slot and
    its row survive for re-sync on re-install.
    """
    row = await _load_installation_by_number(db, installation_id)
    if row is None:
        return
    if action == "suspend":
        row.suspended_at = datetime.now(UTC)
        await _mark_pushes_stale(db, row.id)
        await db.commit()
        github_audit(
            GITHUB_AUDIT_SYNC_PAUSED,
            installation_id=installation_id,
            action="suspend",
            status="suspended",
        )
    elif action == "unsuspend":
        row.suspended_at = None
        await db.commit()
    elif action == "deleted":
        await _detach_and_stale_pushes(db, row.id)
        await db.delete(row)
        await db.commit()
        github_audit(
            GITHUB_AUDIT_UNINSTALLED,
            installation_id=installation_id,
            action="deleted",
        )


async def apply_installation_repositories_event(
    db: AsyncSession,
    *,
    action: str,
    installation_id: int,
    removed_repo_ids: list[int] | None = None,
) -> None:
    """Apply an ``installation_repositories`` action (``added``/``removed``).

    On ``removed`` the App can no longer touch those repos, so any push for a
    removed ``repo_id`` is marked ``stale`` (sync paused). ``added`` needs no
    action — the repos simply become reachable for a future export.
    """
    if action != "removed" or not removed_repo_ids:
        return
    row = await _load_installation_by_number(db, installation_id)
    if row is None:
        return
    await db.execute(
        update(IntegrationPush)
        .where(
            IntegrationPush.installation_id == row.id,
            IntegrationPush.repo_id.in_(removed_repo_ids),
            IntegrationPush.status != "failed",
        )
        .values(status="stale")
    )
    await db.commit()
    github_audit(
        GITHUB_AUDIT_SYNC_PAUSED,
        installation_id=installation_id,
        action="repositories_removed",
        status="stale",
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _load_installation_by_number(
    db: AsyncSession, installation_id: int
) -> GitHubInstallation | None:
    result = await db.execute(
        select(GitHubInstallation).where(
            GitHubInstallation.installation_id == installation_id
        )
    )
    return result.scalar_one_or_none()


async def _mark_pushes_stale(db: AsyncSession, installation_row_id: UUID) -> None:
    """Mark every live (non-``failed``) push for an install ``stale``."""
    await db.execute(
        update(IntegrationPush)
        .where(
            IntegrationPush.installation_id == installation_row_id,
            IntegrationPush.status != "failed",
        )
        .values(status="stale")
    )


async def _detach_and_stale_pushes(db: AsyncSession, installation_row_id: UUID) -> None:
    """Stale + detach pushes so the install row can be deleted (no FK cascade).

    ``integration_pushes.installation_id`` has no ON DELETE rule, so the rows are
    set ``stale`` and their ``installation_id`` cleared before the install row is
    removed. drift/reconcile still works via the immutable ``repo_id``.
    """
    await db.execute(
        update(IntegrationPush)
        .where(
            IntegrationPush.installation_id == installation_row_id,
            IntegrationPush.status != "failed",
        )
        .values(status="stale", installation_id=None)
    )
    await db.execute(
        update(IntegrationPush)
        .where(IntegrationPush.installation_id == installation_row_id)
        .values(installation_id=None)
    )
