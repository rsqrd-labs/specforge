from __future__ import annotations

from collections.abc import Callable

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.auth_service import decode_access_token_claims
from services.security.csrf import verify_csrf_token

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PATHS = frozenset(
    {
        "/auth/google",
        "/auth/callback",
        "/auth/refresh",
        "/auth/logout",
    }
)


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method in _SAFE_METHODS or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        session_id = _session_id_from_authorization(request)
        csrf_token = request.headers.get("X-CSRF-Token")
        if session_id is None:
            return await call_next(request)

        if not csrf_token:
            return _forbidden()

        if not verify_csrf_token(csrf_token, session_id):
            return _forbidden()

        return await call_next(request)


def _session_id_from_authorization(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.removeprefix("Bearer ").strip()
    claims = decode_access_token_claims(token)
    if claims is None:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) and subject else None


def _forbidden() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": "Invalid or missing CSRF token"},
    )
