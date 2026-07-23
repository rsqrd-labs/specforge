"""GitHub App config + production-guard tests (Phase 21 — T-283).

Covers the consolidated config surface: the ``github_app_enabled`` /
``github_app_webhook_secrets`` derivations and the production startup guard that
refuses to boot an App-enabled production deployment whose signing key or webhook
secret is missing (AC#2: an empty private key fails startup).
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

    Every non-GitHub production check (metrics token, HTTPS frontend, real JWT
    PEM, non-CI encryption key, Langfuse disabled, no Stripe test key) is
    satisfied, so a raised error can only come from the GitHub App guard under
    test — not an unrelated check.
    """
    base: dict[str, object] = {
        "environment": "production",
        "allowed_hosts": "app.example.com",
        "metrics_token": "metrics-token",
        "frontend_url": "https://app.thought2build.com",
        "jwt_private_key": _FAKE_PEM,
        "encryption_master_key": "a-real-non-ci-encryption-key",
        "langfuse_secret_key": "",
        # GitHub App fully disabled by default.
        "github_app_id": "",
        "github_app_slug": "",
        "github_app_private_key": "",
        "github_app_webhook_secret": "",
        "github_app_webhook_secret_prev": "",
        "github_app_client_id": "",
        "github_app_client_secret": "",
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


# ---------------------------------------------------------------------------
# Derived properties
# ---------------------------------------------------------------------------


def test_github_app_enabled_requires_id_and_slug() -> None:
    with (
        patch.object(config.settings, "github_app_id", "12345"),
        patch.object(config.settings, "github_app_slug", "thought2build"),
    ):
        assert config.settings.github_app_enabled is True
    with (
        patch.object(config.settings, "github_app_id", "12345"),
        patch.object(config.settings, "github_app_slug", ""),
    ):
        assert config.settings.github_app_enabled is False
    with (
        patch.object(config.settings, "github_app_id", ""),
        patch.object(config.settings, "github_app_slug", "thought2build"),
    ):
        assert config.settings.github_app_enabled is False


def test_github_app_webhook_secrets_filters_empty_current_first() -> None:
    with (
        patch.object(config.settings, "github_app_webhook_secret", "cur"),
        patch.object(config.settings, "github_app_webhook_secret_prev", "prev"),
    ):
        assert config.settings.github_app_webhook_secrets == ["cur", "prev"]
    with (
        patch.object(config.settings, "github_app_webhook_secret", "cur"),
        patch.object(config.settings, "github_app_webhook_secret_prev", ""),
    ):
        assert config.settings.github_app_webhook_secrets == ["cur"]
    with (
        patch.object(config.settings, "github_app_webhook_secret", ""),
        patch.object(config.settings, "github_app_webhook_secret_prev", ""),
    ):
        assert config.settings.github_app_webhook_secrets == []


# ---------------------------------------------------------------------------
# Production guard
# ---------------------------------------------------------------------------


def test_prod_guard_passes_when_app_disabled() -> None:
    """A production deploy with the App off must boot (App is opt-in)."""
    patches = _valid_production()
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise
    finally:
        _undo(patches)


def test_prod_guard_fails_on_empty_private_key_when_app_enabled() -> None:
    """AC#2: an empty private key in production fails startup — and the error
    names the private key, not some unrelated check."""
    patches = _valid_production(
        github_app_id="12345",
        github_app_slug="thought2build",
        github_app_webhook_secret="whsec-value",
        github_app_private_key="",
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "GITHUB_APP_PRIVATE_KEY" in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_fails_on_empty_webhook_secret_when_app_enabled() -> None:
    patches = _valid_production(
        github_app_id="12345",
        github_app_slug="thought2build",
        github_app_private_key=_FAKE_PEM,
        github_app_webhook_secret="",
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "GITHUB_APP_WEBHOOK_SECRET" in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_fails_on_missing_identity_oauth_when_app_enabled() -> None:
    """Audit #1: identity OAuth is the install-callback's proof-of-control, so an
    App-enabled production deploy without it must fail startup loudly rather than
    silently refuse every install."""
    patches = _valid_production(
        github_app_id="12345",
        github_app_slug="thought2build",
        github_app_private_key=_FAKE_PEM,
        github_app_webhook_secret="whsec-value",
        github_app_client_id="",
        github_app_client_secret="",
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "GITHUB_APP_CLIENT_ID" in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_passes_when_app_fully_configured() -> None:
    patches = _valid_production(
        github_app_id="12345",
        github_app_slug="thought2build",
        github_app_private_key=_FAKE_PEM,
        github_app_webhook_secret="whsec-value",
        github_app_client_id="iv1.appclient",
        github_app_client_secret="app-client-secret",
    )
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise
    finally:
        _undo(patches)


def test_dev_environment_ignores_app_guard() -> None:
    """Outside production the guard is a no-op even with the App half-configured."""
    patches = _valid_production(
        environment="development",
        github_app_id="12345",
        github_app_slug="thought2build",
        github_app_private_key="",
        github_app_webhook_secret="",
    )
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise in development
    finally:
        _undo(patches)
