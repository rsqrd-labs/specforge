"""AES-256 key vault using Fernet symmetric encryption.

V1 usage: vault is wired and tested but not yet storing per-user keys
(user-provided API keys are out of scope for V1). Ready for V2.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from config import settings


class DecryptionError(Exception):
    pass


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext string, returning base64 ciphertext."""
    f = Fernet(settings.encryption_master_key.encode())
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt ciphertext string. Raises DecryptionError on invalid input."""
    f = Fernet(settings.encryption_master_key.encode())
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception) as exc:
        raise DecryptionError("Failed to decrypt ciphertext") from exc
