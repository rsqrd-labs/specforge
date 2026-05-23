from __future__ import annotations

import hmac
import secrets
import time
from hashlib import sha256

from config import settings


def generate_csrf_token(session_id: str) -> str:
    """Generate a CSRF token with a random nonce.

    The token format is ``{timestamp}.{nonce}.{signature}`` where:
    - *timestamp* — Unix epoch seconds (expiry check on verify)
    - *nonce* — ``secrets.token_hex(16)`` (32 hex chars) — ensures each
      token is unique even when generated for the same session_id within
      the same second, preventing replay attacks.  M-3 — T-185.
    - *signature* — HMAC-SHA256 of ``{session_id}.{timestamp}.{nonce}``

    Old tokens in the two-part ``{timestamp}.{signature}`` format (no nonce)
    will be rejected by verify_csrf_token; this is intentional because those
    tokens lack replay protection.
    """
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    signature = _sign(session_id, timestamp, nonce)
    return f"{timestamp}.{nonce}.{signature}"


def verify_csrf_token(
    token: str,
    session_id: str,
    max_age_seconds: int = 3600,
) -> bool:
    try:
        timestamp, nonce, signature = token.split(".", 2)
        issued_at = int(timestamp)
    except (ValueError, TypeError):
        return False

    now = int(time.time())
    if issued_at > now or now - issued_at > max_age_seconds:
        return False

    expected = _sign(session_id, timestamp, nonce)
    return hmac.compare_digest(signature, expected)


def _sign(session_id: str, timestamp: str, nonce: str) -> str:
    message = f"{session_id}.{timestamp}.{nonce}".encode()
    secret = settings.csrf_secret.encode()
    return hmac.new(secret, message, sha256).hexdigest()
