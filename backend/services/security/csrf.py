"""CSRF token generation and verification with per-nonce Redis replay tracking.

Token format: ``{timestamp}.{nonce}.{signature}``

- *timestamp* — Unix epoch seconds (expiry check on verify)
- *nonce* — ``secrets.token_hex(16)`` (32 hex chars) — ensures each token is
  unique even for the same session_id within the same second.  M-3 — T-185.
- *signature* — HMAC-SHA256 of ``{session_id}.{timestamp}.{nonce}``

Replay protection (HF-6 — T-203): after successful HMAC + timestamp
validation, ``verify_csrf_token`` atomically claims the nonce in Redis via
SETNX.  A second call with the same token finds the nonce already stored and
raises ``HTTPException(403)``.  If Redis is unavailable, verification degrades
gracefully (fail-open with a WARNING log) so a Redis outage never takes the
service down.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from hashlib import sha256

from fastapi import HTTPException, status

from config import settings
from services.observability import CSRF_REPLAY_REJECTIONS

logger = logging.getLogger(__name__)


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


async def verify_csrf_token(
    token: str,
    session_id: str,
    redis: object,
    max_age_seconds: int = 3600,
) -> bool:
    """Verify a CSRF token and atomically consume its nonce via Redis SETNX.

    Steps:
    1. Parse and validate the three-part token format.
    2. Reject tokens with an invalid or expired timestamp.
    3. Verify the HMAC-SHA256 signature.
    4. Atomically claim the nonce in Redis (SETNX) with the token's remaining
       TTL.  A second call with the same token finds the nonce already stored
       and raises HTTPException(403, "CSRF token already used").
    5. If Redis is unavailable, log a WARNING and fail **open** so a transient
       Redis outage does not take the service down.

    Returns True on success; False for structurally invalid or expired tokens;
    raises HTTPException(403) only for detected replay attacks.

    HF-6 — T-203.
    """
    try:
        timestamp, nonce, signature = token.split(".", 2)
        issued_at = int(timestamp)
    except (ValueError, TypeError):
        return False

    now = int(time.time())
    if issued_at > now or now - issued_at > max_age_seconds:
        # Reject before any Redis round-trip — no unnecessary network call on
        # tokens that are already structurally invalid.
        return False

    expected = _sign(session_id, timestamp, nonce)
    if not hmac.compare_digest(signature, expected):
        return False

    # HMAC and timestamp are valid.  Now atomically claim the nonce so the
    # same token cannot be replayed within its remaining TTL.
    #
    # `remaining_ttl` is clamped to at least 1 second because redis-py
    # rejects ex=0 as invalid.
    remaining_ttl = max(1, max_age_seconds - (now - issued_at))
    nonce_key = f"csrf:nonce:{nonce}"

    if redis is None:
        logger.warning(
            "csrf.nonce_tracking.redis_not_available nonce_key=%s "
            "— replay protection bypassed (fail-open)",
            nonce_key,
        )
        return True

    try:
        # SETNX (SET if Not eXists) — atomic claim of the nonce key.  Returns
        # None when the key already exists, which we treat as replay detection.
        stored = await redis.set(nonce_key, "1", nx=True, ex=remaining_ttl)
    except Exception:
        logger.warning(
            "csrf.nonce_tracking.redis_error nonce_key=%s "
            "— replay protection bypassed (fail-open)",
            nonce_key,
            exc_info=True,
        )
        return True

    if stored is None:
        # SETNX returned None → key already existed → token replayed.
        CSRF_REPLAY_REJECTIONS.inc()
        logger.warning(
            "csrf.replay_detected nonce_key=%s session_id=%.8s",
            nonce_key,
            session_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token already used",
        )

    return True


def _sign(session_id: str, timestamp: str, nonce: str) -> str:
    message = f"{session_id}.{timestamp}.{nonce}".encode()
    secret = settings.csrf_secret.encode()
    return hmac.new(secret, message, sha256).hexdigest()
