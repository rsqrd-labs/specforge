from __future__ import annotations

import hmac
import time
from hashlib import sha256

from config import settings


def generate_csrf_token(session_id: str) -> str:
    timestamp = str(int(time.time()))
    signature = _sign(session_id, timestamp)
    return f"{timestamp}.{signature}"


def verify_csrf_token(
    token: str,
    session_id: str,
    max_age_seconds: int = 3600,
) -> bool:
    try:
        timestamp, signature = token.split(".", 1)
        issued_at = int(timestamp)
    except (ValueError, TypeError):
        return False

    now = int(time.time())
    if issued_at > now or now - issued_at > max_age_seconds:
        return False

    expected = _sign(session_id, timestamp)
    return hmac.compare_digest(signature, expected)


def _sign(session_id: str, timestamp: str) -> str:
    message = f"{session_id}.{timestamp}".encode()
    secret = settings.csrf_secret.encode()
    return hmac.new(secret, message, sha256).hexdigest()
