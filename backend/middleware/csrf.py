"""CSRF enforcement middleware.

Every mutating HTTP request (POST / PUT / PATCH / DELETE) that carries a
Bearer token must include a valid ``X-CSRF-Token`` header.  The CSRF token is
verified by ``services.security.csrf.verify_csrf_token``, which now performs a
Redis SETNX round-trip to atomically consume the token's nonce — closing the
1-hour replay window.  HF-6 — T-203.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.auth_service import decode_access_token_claims
from services.security.csrf import verify_csrf_token

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PATHS = frozenset(
    {
        "/auth/google",  # exempt: initiates OAuth redirect — no session exists yet
        "/auth/callback",  # exempt: OAuth provider callback — no auth token yet
        "/auth/refresh",  # exempt: exchanges HTTP-only refresh cookie for a new token
        "/billing/webhook",  # Stripe webhook — no browser session, no CSRF token
        "/integrations/github/webhook",  # GitHub webhook — HMAC-verified, no session
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

        # Read the shared Redis pool injected by the FastAPI lifespan.  If Redis
        # is not yet available (pre-lifespan), verify_csrf_token() degrades
        # gracefully and logs a WARNING rather than blocking the request.
        # HF-5 — T-202.  HF-6 — T-203.
        redis = getattr(request.app.state, "redis", None)

        try:
            valid = await verify_csrf_token(csrf_token, session_id, redis)
        except HTTPException as exc:
            # verify_csrf_token() raises HTTPException(403) when it detects a
            # replayed nonce (SETNX returned None).  BaseHTTPMiddleware runs
            # outside FastAPI's ExceptionMiddleware, so we must convert the
            # exception to a JSONResponse here rather than letting it propagate
            # to ServerErrorMiddleware (which would return 500).  HF-6 — T-203.
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )

        if not valid:
            return _forbidden()

        return await call_next(request)


def _session_id_from_authorization(request: Request) -> str | None:
    claims = getattr(request.state, "jwt_claims", None)
    if claims is None:
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
