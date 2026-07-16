import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, get_redis
from middleware.auth import get_current_user
from models import User
from schemas.auth import UserResponse
from services.auth_service import AuthError, auth_service
from services.credit_service import credit_service
from services.integrations import github_auth_service
from services.security.csrf import generate_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_COOKIE_MAX_AGE = 604800  # 7 days
_REFRESH_COOKIE_PATH = "/auth"

# OAuth login-CSRF binding cookie (holds the CSPRNG secret minted by
# get_google_auth_url and echoed back on the callback). In production the cookie
# is Secure, so it carries the __Host- prefix: the browser then refuses any
# Set-Cookie bearing a Domain attribute and requires Secure + Path=/, structurally
# preventing a sibling host under a shared parent domain from planting this cookie
# (cookie-tossing → forced login). __Host- mandates Secure, so dev-HTTP falls back
# to the plain name. Path is "/" in both (required by __Host-; harmless for dev).
_OAUTH_STATE_COOKIE = "sf_oauth_state"
_OAUTH_STATE_COOKIE_HOST = "__Host-sf_oauth_state"
_OAUTH_STATE_MAX_AGE = 600  # mirrors auth_service.OAUTH_STATE_TTL


def _refresh_cookie_secure() -> bool:
    return settings.environment.lower() == "production"


def _refresh_cookie_samesite() -> str:
    if settings.environment.lower() == "production":
        return "none"
    return "lax"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=_refresh_cookie_secure(),
        samesite=_refresh_cookie_samesite(),
        max_age=_COOKIE_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
    )


def _oauth_state_cookie_name() -> str:
    return _OAUTH_STATE_COOKIE_HOST if _refresh_cookie_secure() else _OAUTH_STATE_COOKIE


def _set_oauth_state_cookie(response: Response, binding: str) -> None:
    response.set_cookie(
        key=_oauth_state_cookie_name(),
        value=binding,
        httponly=True,
        secure=_refresh_cookie_secure(),
        samesite=_refresh_cookie_samesite(),
        max_age=_OAUTH_STATE_MAX_AGE,
        path="/",
    )


def _delete_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_oauth_state_cookie_name(),
        path="/",
        secure=_refresh_cookie_secure(),
        samesite=_refresh_cookie_samesite(),
    )


@router.get("/google")
async def google_login() -> RedirectResponse:
    url, binding = await auth_service.get_google_auth_url()
    redirect = RedirectResponse(url)
    _set_oauth_state_cookie(redirect, binding)
    return redirect


@router.get("/callback")
async def google_callback(
    code: str,
    state: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    state_binding = request.cookies.get(_oauth_state_cookie_name())
    try:
        access_token, refresh_token = await auth_service.handle_callback(
            code, state, state_binding, db
        )
    except AuthError as exc:
        # Clear the single-use binding cookie on the failure path too, then surface
        # the same 401 {"detail": …} shape the endpoint returned before. Returning
        # a dict (rather than raising) lets the injected Response carry both the
        # cookie deletion and the 401 status; a raised HTTPException would drop the
        # Set-Cookie header.
        _delete_oauth_state_cookie(response)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"detail": str(exc)}

    _set_refresh_cookie(response, refresh_token)
    _delete_oauth_state_cookie(response)
    return {"access_token": access_token}


@router.post("/refresh")
async def refresh_token(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> dict:
    if not refresh_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )

    try:
        access_token, new_refresh = await auth_service.refresh_tokens(refresh_token, db)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _set_refresh_cookie(response, new_refresh)
    return {"access_token": access_token}


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> dict:
    if refresh_token:
        try:
            await auth_service.revoke(refresh_token)
        except AuthError:
            # Logout is best-effort: an already-invalid or expired token can't
            # be revoked, but we still clear the cookie below regardless.
            pass

    response.delete_cookie(
        key=_REFRESH_COOKIE,
        path=_REFRESH_COOKIE_PATH,
        secure=_refresh_cookie_secure(),
        samesite=_refresh_cookie_samesite(),
    )
    response.delete_cookie(
        key=_REFRESH_COOKIE,
        path="/auth/refresh",
        secure=_refresh_cookie_secure(),
        samesite=_refresh_cookie_samesite(),
    )
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    balance = await credit_service.get_balance(db, user.id)
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        credit_balance=balance,
        created_at=user.created_at,
    )


@router.get("/csrf-token")
async def csrf_token(user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"csrf_token": generate_csrf_token(str(user.id))}


# _get_redis removed — use get_redis from database.py via Depends().
# H-1 — T-177.


@router.get("/github")
async def github_login(
    request: Request,
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """Initiate the GitHub OAuth flow.

    Returns 503 when the GitHub OAuth App is not configured so the frontend
    can render a clear "feature disabled" state in Settings.
    """
    if not settings.github_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub integration is not configured",
        )

    try:
        url = await github_auth_service.get_github_oauth_url(user.id, redis)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """Complete the GitHub OAuth flow.

    Authentication for this endpoint is the OAuth state parameter (Redis
    lookup binds it to the user_id that initiated the flow). The browser
    redirect from GitHub cannot carry the in-memory access token, so a JWT
    requirement would be impossible — the state binding is the correct
    OAuth CSRF protection.
    """
    if error:
        # User denied the GitHub authorization screen.
        return _redirect_to_settings(connected=False, error=error)

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth code or state",
        )

    try:
        await github_auth_service.handle_github_callback(code, state, db, redis)
    except AuthError as exc:
        message = str(exc)
        if "invalid_state" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OAuth state",
            ) from exc
        logger.warning("github_oauth.callback_failed", extra={"error": message})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub OAuth exchange failed",
        ) from exc

    return _redirect_to_settings(connected=True)


def _redirect_to_settings(
    *, connected: bool, error: str | None = None
) -> RedirectResponse:
    base = settings.frontend_url.rstrip("/")
    if connected:
        target = f"{base}/settings?github_connected=true"
    else:
        # Pass through a safe truncated error code for diagnostics.
        safe_error = (error or "denied")[:40].replace("\n", "").replace("\r", "")
        target = f"{base}/settings?github_error={safe_error}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
