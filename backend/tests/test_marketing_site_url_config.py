"""Marketing-zone SITE_URL config + production-guard tests (issue #18, Phase 7).

The backend mirrors the marketing zone's canonical origin as ``site_url`` for any
server-emitted canonical/sitemap concern. It is deliberately *optional* (empty =
unset, no backend consumer reads it yet) but HTTPS-enforced in production when
set, so a configured-but-insecure (http://) origin fails startup rather than
silently emitting plaintext canonical/OG/sitemap URLs.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import config

# A syntactically valid PEM head so the JWT-key production check passes; the
# value is never used to sign anything in these tests.
_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"


def _valid_production(**overrides: object):
    """Patch ``config.settings`` to an OTHERWISE-VALID production config.

    Every non-SITE_URL production check is satisfied, so a raised error can only
    come from the SITE_URL guard under test — not an unrelated check.
    """
    base: dict[str, object] = {
        "environment": "production",
        "allowed_hosts": "app.example.com",
        "metrics_token": "metrics-token",
        "frontend_url": "https://app.thought2build.com",
        "jwt_private_key": _FAKE_PEM,
        "encryption_master_key": "a-real-non-ci-encryption-key",
        "langfuse_secret_key": "",
        # Marketing SITE_URL unset by default (optional).
        "site_url": "",
    }
    base.update(overrides)
    patches = [patch.object(config.settings, key, value) for key, value in base.items()]
    return patches


def _apply(patches: list):
    for p in patches:
        p.start()


def _undo(patches: list):
    for p in patches:
        p.stop()


def test_site_url_defaults_to_empty() -> None:
    """SITE_URL is optional; the field default is the empty string (unset)."""
    assert isinstance(config.settings.site_url, str)


def test_prod_guard_passes_when_site_url_unset() -> None:
    """A production deploy that has not configured SITE_URL must still boot."""
    patches = _valid_production(site_url="")
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise
    finally:
        _undo(patches)


def test_prod_guard_passes_on_https_site_url() -> None:
    patches = _valid_production(site_url="https://thought2build.com")
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise
    finally:
        _undo(patches)


def test_prod_guard_fails_on_http_site_url() -> None:
    """A configured-but-plaintext SITE_URL fails startup, and the error names
    SITE_URL (not some unrelated check)."""
    patches = _valid_production(site_url="http://thought2build.com")
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "SITE_URL" in str(exc.value)
    finally:
        _undo(patches)


def test_dev_environment_ignores_site_url_guard() -> None:
    """Outside production the guard is a no-op even with an http:// SITE_URL."""
    patches = _valid_production(
        environment="development", site_url="http://localhost:4321"
    )
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise in development
    finally:
        _undo(patches)
