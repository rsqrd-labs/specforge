"""User-facing integration management endpoints.

Phase 13 (legacy OAuth, retained behind a flag) routes:

- ``GET /integrations/github`` — legacy connection status (connected + username).
- ``DELETE /integrations/github`` — idempotently removes the user's v1 OAuth
  integration. Always returns 204.

Phase 21 GitHub **App** install routes (T-270):

- ``GET /integrations/github/install`` — returns the App installation URL
  (``/apps/{slug}/installations/new``) with a one-time, user-bound state.
- ``GET /integrations/github/setup`` — the install callback. Authenticated
  solely by the state parameter (no bearer token on GitHub's browser redirect);
  upserts the installation and redirects to ``/settings?github_installed=true``.
- ``GET /integrations/github/installations`` — the user's installations
  (org + personal) plus ``on_legacy_oauth`` for the migration prompt and the
  export picker.
- ``DELETE /integrations/github/{installation_id}`` — locally revoke one
  installation (CSRF-protected by the global middleware; GitHub is unaffected).
- ``POST /integrations/github/webhook`` — the public GitHub event ingress
  (HMAC-verified, CSRF/rate-limit exempt). Verifies, dedups, hands the delivery
  to the worker, and returns a fast 2xx. All routing happens on the worker.

OAuth initiation/callback routes live in ``routers/auth.py``. Lifecycle webhook
events are dispatched from T-271's reconcile path via
:func:`handle_lifecycle_event`.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, get_redis
from middleware.auth import get_current_user
from models import GitHubWebhookEvent, User
from schemas.github import InstallationList, InstallationOption
from schemas.integration import GitHubStatusResponse
from services.integrations import github_auth_service, github_install_service
from services.integrations.github_app_auth import verify_webhook_signature
from services.integrations.github_install_service import (
    AppNotConfiguredError,
    InstallStateError,
)
from services.observability import (
    GITHUB_WEBHOOK_DEDUPED_TOTAL,
    GITHUB_WEBHOOK_FAILED_TOTAL,
    GITHUB_WEBHOOK_RECEIVED_TOTAL,
    GITHUB_WEBHOOK_VERIFIED_TOTAL,
)
from services.queue import QueueUnavailableError, enqueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


# ---------------------------------------------------------------------------
# Phase 13 — legacy OAuth status/disconnect (retained, unchanged)
# ---------------------------------------------------------------------------


@router.get("/github", response_model=GitHubStatusResponse)
async def get_github_integration(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GitHubStatusResponse:
    integration = await github_auth_service.get_integration(user.id, db)
    if integration is None:
        return GitHubStatusResponse(connected=False, github_username=None)
    return GitHubStatusResponse(
        connected=True,
        github_username=integration.github_username,
    )


@router.delete("/github", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_github(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await github_auth_service.disconnect_github(user.id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Phase 21 — GitHub App install flow (T-270)
# ---------------------------------------------------------------------------


@router.get("/github/install")
async def github_app_install_url(
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> dict[str, str]:
    """Return the App installation URL for the signed-in user.

    503 when the App is not configured so Settings can render a clear
    "feature disabled" state.
    """
    try:
        url = await github_install_service.build_install_url(user.id, redis)
    except AppNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App is not configured.",
        ) from exc
    return {"url": url}


@router.get("/github/setup")
async def github_app_setup(
    request: Request,
    installation_id: int | None = None,
    setup_action: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """GitHub App install callback.

    Authenticated solely by the one-time ``state`` (the browser redirect from
    GitHub carries no bearer token) — the state binding recovers the installing
    user. Validates state, learns the account from GitHub (App JWT), upserts the
    installation, and redirects to Settings. ``setup_action`` may be
    ``install`` / ``update`` / ``request``; only a real install id is persisted.
    """
    try:
        user_id = await github_install_service.consume_install_state(state, redis)
    except InstallStateError:
        return _settings_redirect(installed=False)

    if installation_id is None or setup_action == "request":
        # No install completed (e.g. an org admin approval request) — nothing to
        # persist; bounce back to Settings without an error.
        return _settings_redirect(installed=False)

    try:
        account = await github_install_service.fetch_installation_account(
            installation_id
        )
        await github_install_service.upsert_installation(
            db,
            installation_id=installation_id,
            user_id=user_id,
            account=account,
        )
    except InstallStateError:
        return _settings_redirect(installed=False)

    return _settings_redirect(installed=True)


@router.get("/github/installations", response_model=InstallationList)
async def list_github_installations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InstallationList:
    """List the user's App installations + the legacy-OAuth migration flag."""
    rows = await github_install_service.list_installations(db, user.id)
    on_legacy = await github_install_service.user_on_legacy_oauth(db, user.id)
    return InstallationList(
        installations=[
            InstallationOption(
                id=row.id,
                installation_id=row.installation_id,
                account_login=row.account_login,
                account_type=row.account_type,
                repository_selection=row.repository_selection,
                suspended=row.suspended_at is not None,
            )
            for row in rows
        ],
        on_legacy_oauth=on_legacy,
    )


@router.delete("/github/{installation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_github_installation(
    installation_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Locally revoke one installation the caller owns (CSRF-protected).

    Idempotent: a missing/unowned install also returns 204 so the endpoint never
    leaks which installations exist. GitHub repos/issues are untouched.
    """
    await github_install_service.revoke_installation(db, installation_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Webhook ingress (T-271) — verify → dedup → dispatch → fast 2xx
# ---------------------------------------------------------------------------


@router.post("/github/webhook")
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Public ingress for GitHub App webhook deliveries.

    Mirrors the audited Stripe receiver. Ordering is a hard security contract:
    the raw bytes are read first, the HMAC-SHA256 signature is verified
    (constant-time, against the current and previous secret for rotation) and a
    mismatch is rejected with 400 *before* any database or background work, the
    delivery is recorded for idempotency (a retry is skipped), and the event is
    handed to the worker for routing. The handler stays O(1) and never branches
    on event type — all fan-out happens on the worker (``reconcile_event``,
    T-272). No GitHub or LLM I/O on the request path; the body size is capped by
    the global middleware.
    """
    secrets = [
        settings.github_app_webhook_secret,
        settings.github_app_webhook_secret_prev,
    ]
    if not any(secrets):
        # App webhook not configured → the route is effectively disabled.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_webhook_signature(raw_body, signature, secrets):
        GITHUB_WEBHOOK_FAILED_TOTAL.labels(error_type="bad_signature").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid signature"
        )

    delivery_id = request.headers.get("X-GitHub-Delivery")
    event_type = request.headers.get("X-GitHub-Event")
    if not delivery_id or not event_type:
        GITHUB_WEBHOOK_FAILED_TOTAL.labels(error_type="missing_headers").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing delivery headers",
        )

    GITHUB_WEBHOOK_VERIFIED_TOTAL.inc()
    GITHUB_WEBHOOK_RECEIVED_TOTAL.labels(event_type=event_type).inc()

    # Idempotency: record the delivery before dispatch. A unique violation on
    # delivery_id means GitHub re-delivered this event — skip it.
    try:
        async with db.begin_nested():
            db.add(GitHubWebhookEvent(delivery_id=delivery_id, event_type=event_type))
            await db.flush()
    except IntegrityError:
        GITHUB_WEBHOOK_DEDUPED_TOTAL.labels(event_type=event_type).inc()
        return {"status": "duplicate"}

    # Hand off to the worker, THEN commit (at-least-once). If the handoff fails
    # the dedup row is never committed, so GitHub's retry re-delivers and
    # reconcile_event (idempotent by delivery_id, T-272) runs once. This
    # deliberately reorders the Plan §24.4 sketch (commit-then-handoff), which
    # would silently drop an event on a transient broker failure. The worker is
    # the single dumb dispatcher: the raw bytes are passed so it re-parses and
    # fans out by (event_type, action).
    try:
        await enqueue("reconcile_event", delivery_id, event_type, raw_body)
    except QueueUnavailableError as exc:
        GITHUB_WEBHOOK_FAILED_TOTAL.labels(error_type="enqueue_unavailable").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="background processing temporarily unavailable",
        ) from exc
    await db.commit()
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Lifecycle webhook dispatch (called from T-271 reconcile path)
# ---------------------------------------------------------------------------


async def handle_lifecycle_event(
    db: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Apply an installation-lifecycle webhook to the stored install row.

    ``installation`` (``suspend`` / ``unsuspend`` / ``deleted``) sets/clears
    ``suspended_at`` and marks the install's pushes ``stale`` (sync paused);
    ``installation_repositories`` (``added`` / ``removed``) stales pushes for
    repos the App can no longer touch. Unknown event types are ignored.
    """
    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    if not isinstance(installation_id, int):
        return
    action = payload.get("action")

    if event_type == "installation":
        if action in ("suspend", "unsuspend", "deleted"):
            await github_install_service.apply_installation_event(
                db, action=action, installation_id=installation_id
            )
    elif event_type == "installation_repositories":
        removed = payload.get("repositories_removed") or []
        removed_repo_ids = [
            r.get("id") for r in removed if isinstance(r.get("id"), int)
        ]
        await github_install_service.apply_installation_repositories_event(
            db,
            action=action or "",
            installation_id=installation_id,
            removed_repo_ids=removed_repo_ids,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_redirect(*, installed: bool) -> RedirectResponse:
    base = settings.frontend_url.rstrip("/")
    flag = "true" if installed else "false"
    return RedirectResponse(
        url=f"{base}/settings?github_installed={flag}",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
