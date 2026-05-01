from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from services.security.key_vault import DecryptionError, decrypt, encrypt

# Use a valid Fernet key for all tests
_TEST_KEY = Fernet.generate_key().decode()


def _patched():
    return patch("services.security.key_vault.settings")


def _make_settings():
    s = type("S", (), {"encryption_master_key": _TEST_KEY})()
    return s


def test_encrypt_decrypt_roundtrip() -> None:
    with patch("services.security.key_vault.settings", _make_settings()):
        ciphertext = encrypt("hello world")
        plaintext = decrypt(ciphertext)
    assert plaintext == "hello world"


def test_encrypt_returns_different_ciphertext_each_call() -> None:
    with patch("services.security.key_vault.settings", _make_settings()):
        c1 = encrypt("same text")
        c2 = encrypt("same text")
    # Fernet uses a random IV per call so ciphertexts differ
    assert c1 != c2


def test_decrypt_invalid_ciphertext_raises_decryption_error() -> None:
    with patch("services.security.key_vault.settings", _make_settings()):
        with pytest.raises(DecryptionError):
            decrypt("not-valid-ciphertext")


def test_encrypt_empty_string() -> None:
    with patch("services.security.key_vault.settings", _make_settings()):
        ciphertext = encrypt("")
        assert decrypt(ciphertext) == ""


def test_encrypt_unicode_content() -> None:
    text = "héllo wörld — 日本語"
    with patch("services.security.key_vault.settings", _make_settings()):
        assert decrypt(encrypt(text)) == text
