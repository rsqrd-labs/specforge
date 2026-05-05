from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import User
from schemas.auth import UserResponse
from services.auth_service import AuthError, auth_service
from services.credit_service import credit_service
from services.security.csrf import generate_csrf_token

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_COOKIE_MAX_AGE = 604800  # 7 days
_REFRESH_COOKIE_PATH = "/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_COOKIE_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
    )


@router.get("/google")
async def google_login() -> RedirectResponse:
    url = await auth_service.get_google_auth_url()
    return RedirectResponse(url)


@router.get("/callback")
async def google_callback(
    code: str,
    state: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        access_token, refresh_token = await auth_service.handle_callback(
            code, state, db
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _set_refresh_cookie(response, refresh_token)
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
            pass

    response.delete_cookie(key=_REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH)
    response.delete_cookie(key=_REFRESH_COOKIE, path="/auth/refresh")
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
