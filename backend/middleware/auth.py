from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from services.auth_service import AuthError, auth_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    token_param: str | None = Query(default=None, alias="token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    resolved = token or token_param
    if not resolved:
        raise _unauthorized()
    token = resolved  # noqa: PLW0621

    try:
        claims = auth_service.verify_access_token(token)
        user_id = UUID(claims["sub"])
    except (AuthError, KeyError, TypeError, ValueError) as exc:
        raise _unauthorized() from exc

    user = await _load_user(db, user_id)
    if user is None:
        raise _unauthorized()

    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    token_param: str | None = Query(default=None, alias="token"),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    resolved = token or token_param
    if not resolved:
        return None

    try:
        return await get_current_user(token=resolved, token_param=None, db=db)
    except HTTPException:
        return None


async def _load_user(db: AsyncSession, user_id: UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
