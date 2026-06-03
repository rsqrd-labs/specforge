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

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
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

logger = logging.getLogger(__name__)

GITHUB_PROVIDER = "github"

# One-time install state, bound to the initiating user in Redis (10-min TTL),
# mirroring the Phase-13 OAuth state pattern (github_auth_service).
INSTALL_STATE_PREFIX = "github_app_install_state:"
INSTALL_STATE_TTL_SECONDS = 600

_GITHUB_ACCEPT = "application/vnd.github+json"
_GITHUB_API_VERSION = "2022-11-28"
_INSTALL_FETCH_TIMEOUT_SECONDS = 15.0


class AppNotConfiguredError(Exception):
    """The GitHub App is not configured (no slug/id) — install flow disabled."""


class InstallStateError(Exception):
    """The install callback state is missing, expired, or tampered with."""


@dataclass(frozen=True)
class InstallationAccount:
    """The account facts learned from GitHub for an installation."""

    account_login: str
    account_type: str
    repository_selection: str


def app_install_enabled() -> bool:
    """True when the GitHub App is configured enough to offer the install flow."""
    return bool(settings.github_app_slug and settings.github_app_id)


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
    elif action == "unsuspend":
        row.suspended_at = None
        await db.commit()
    elif action == "deleted":
        await _detach_and_stale_pushes(db, row.id)
        await db.delete(row)
        await db.commit()


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
