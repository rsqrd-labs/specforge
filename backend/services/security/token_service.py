"""Compatibility facade for JWT token handling.

The concrete implementation lives in services.auth_service. It uses RS256,
stores refresh-token session state by jti, and rotates refresh tokens on every
refresh to prevent replay.
"""

from __future__ import annotations

from typing import Any

from services.auth_service import AuthError, auth_service, decode_access_token_claims

ALGORITHM = "RS256"


def verify_access_token(token: str) -> dict[str, Any]:
    return auth_service.verify_access_token(token)


__all__ = [
    "ALGORITHM",
    "AuthError",
    "decode_access_token_claims",
    "verify_access_token",
]
