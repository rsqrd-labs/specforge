"""User-facing integration management endpoints.

Routes:

- ``GET /integrations/github`` — returns connection status and the connected
  GitHub username, or ``{connected: false, github_username: null}``.
- ``DELETE /integrations/github`` — idempotently removes the user's GitHub
  integration. Always returns 204.

OAuth initiation/callback routes live in ``routers/auth.py`` so they sit
under the existing ``/auth`` prefix used for Google OAuth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import User
from schemas.integration import GitHubStatusResponse
from services.integrations import github_auth_service

router = APIRouter(prefix="/integrations", tags=["integrations"])


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
