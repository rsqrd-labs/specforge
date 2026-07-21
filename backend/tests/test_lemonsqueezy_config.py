"""Lemon Squeezy config + production-guard tests (Phase 22 — T-292 / T-308).

Covers the derived properties (``lemonsqueezy_enabled`` /
``lemonsqueezy_webhook_secrets`` / ``admin_emails``) and the production startup
guard, which refuses to boot a Lemon-enabled production deployment whose live
config is incomplete (blank webhook secret, non-HTTPS success URL, non-positive
economics, empty currency, or test_mode left True). The legacy Stripe test-key
startup guard was removed with the Stripe decommission (T-308) — no ``STRIPE_*``
setting is read anymore, so a Lemon-disabled production simply boots with
checkout off.

The harness for t292 is pure substring matching; these unit tests are the real
verification that each guard branch fires for the right reason (asserting the error
message names the offending field, exactly like ``test_github_app_config.py``).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import config

# A syntactically valid PEM head so the JWT-key production check passes; the value
# is never used to sign anything in these tests.
_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"


def _valid_production(**overrides: object):
    """Patch ``config.settings`` to an OTHERWISE-VALID production config.

    Every unrelated production check (metrics token, HTTPS frontend, real JWT PEM,
    non-CI encryption key, Langfuse disabled, GitHub App off) is satisfied, AND a
    complete LIVE Lemon config is set — so a raised error can only come from the
    Lemon branch under test, not an unrelated check.
    """
    base: dict[str, object] = {
        "environment": "production",
        "allowed_hosts": "app.example.com",
        "metrics_token": "metrics-token",
        "frontend_url": "https://app.specforge.dev",
        "jwt_private_key": _FAKE_PEM,
        "encryption_master_key": "a-real-non-ci-encryption-key",
        "langfuse_secret_key": "",
        # GitHub App fully disabled.
        "github_app_id": "",
        "github_app_slug": "",
        "github_app_private_key": "",
        "github_app_webhook_secret": "",
        "github_app_webhook_secret_prev": "",
        # Complete LIVE Lemon config (enabled + passes the production guard).
        "lemonsqueezy_api_key": "lsq-live-key",
        "lemonsqueezy_webhook_secret": "lsq-secret",
        "lemonsqueezy_webhook_secret_prev": "",
        "lemonsqueezy_store_id": "store_1",
        "lemonsqueezy_variant_id": "variant_1",
        "lemonsqueezy_price_cents": 900,
        "lemonsqueezy_currency": "USD",
        "lemonsqueezy_credits_per_purchase": 200,
        "lemonsqueezy_credit_validity_days": 30,
        "lemonsqueezy_success_url": "https://app.specforge.dev/billing",
        "lemonsqueezy_test_mode": False,
    }
    base.update(overrides)
    return [patch.object(config.settings, key, value) for key, value in base.items()]


def _apply(patches: list) -> None:
    for p in patches:
        p.start()


def _undo(patches: list) -> None:
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Derived properties
# ---------------------------------------------------------------------------


def test_lemonsqueezy_enabled_requires_key_store_and_variant() -> None:
    with (
        patch.object(config.settings, "lemonsqueezy_api_key", "k"),
        patch.object(config.settings, "lemonsqueezy_store_id", "s"),
        patch.object(config.settings, "lemonsqueezy_variant_id", "v"),
    ):
        assert config.settings.lemonsqueezy_enabled is True
    # Missing any one of the three disables it.
    for missing in (
        "lemonsqueezy_api_key",
        "lemonsqueezy_store_id",
        "lemonsqueezy_variant_id",
    ):
        with (
            patch.object(config.settings, "lemonsqueezy_api_key", "k"),
            patch.object(config.settings, "lemonsqueezy_store_id", "s"),
            patch.object(config.settings, "lemonsqueezy_variant_id", "v"),
            patch.object(config.settings, missing, ""),
        ):
            assert config.settings.lemonsqueezy_enabled is False


def test_lemonsqueezy_webhook_secrets_current_first_non_empty() -> None:
    with (
        patch.object(config.settings, "lemonsqueezy_webhook_secret", "cur"),
        patch.object(config.settings, "lemonsqueezy_webhook_secret_prev", "prev"),
    ):
        assert config.settings.lemonsqueezy_webhook_secrets == ("cur", "prev")
    with (
        patch.object(config.settings, "lemonsqueezy_webhook_secret", "cur"),
        patch.object(config.settings, "lemonsqueezy_webhook_secret_prev", ""),
    ):
        assert config.settings.lemonsqueezy_webhook_secrets == ("cur",)
    with (
        patch.object(config.settings, "lemonsqueezy_webhook_secret", ""),
        patch.object(config.settings, "lemonsqueezy_webhook_secret_prev", ""),
    ):
        assert config.settings.lemonsqueezy_webhook_secrets == ()


def test_admin_emails_parsed_lowercased_and_empty_default() -> None:
    with patch.object(
        config.settings, "admin_user_emails", "  Ops@Specforge.DEV , founder@x.io ,"
    ):
        assert config.settings.admin_emails == {"ops@specforge.dev", "founder@x.io"}
    with patch.object(config.settings, "admin_user_emails", ""):
        assert config.settings.admin_emails == set()


# ---------------------------------------------------------------------------
# Production guard — Lemon happy path + per-field failures
# ---------------------------------------------------------------------------


def test_prod_guard_passes_with_complete_live_lemon() -> None:
    """A complete live Lemon config in production boots cleanly."""
    patches = _valid_production()
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise
    finally:
        _undo(patches)


def test_dev_environment_ignores_lemon_guard() -> None:
    """Outside production the guard is a no-op even with test_mode on / blank secret."""
    patches = _valid_production(
        environment="development",
        lemonsqueezy_test_mode=True,
        lemonsqueezy_webhook_secret="",
    )
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise in development
    finally:
        _undo(patches)


def test_prod_guard_rejects_test_mode_true() -> None:
    patches = _valid_production(lemonsqueezy_test_mode=True)
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "LEMONSQUEEZY_TEST_MODE" in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_rejects_blank_webhook_secret() -> None:
    patches = _valid_production(lemonsqueezy_webhook_secret="")
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "LEMONSQUEEZY_WEBHOOK_SECRET" in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_rejects_non_https_success_url() -> None:
    patches = _valid_production(
        lemonsqueezy_success_url="http://app.specforge.dev/billing"
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "LEMONSQUEEZY_SUCCESS_URL" in str(exc.value)
    finally:
        _undo(patches)


@pytest.mark.parametrize(
    ("field", "token"),
    [
        ("lemonsqueezy_price_cents", "LEMONSQUEEZY_PRICE_CENTS"),
        ("lemonsqueezy_credits_per_purchase", "LEMONSQUEEZY_CREDITS_PER_PURCHASE"),
        ("lemonsqueezy_credit_validity_days", "LEMONSQUEEZY_CREDIT_VALIDITY_DAYS"),
    ],
)
def test_prod_guard_rejects_non_positive_economics(field: str, token: str) -> None:
    patches = _valid_production(**{field: 0})
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert token in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_rejects_empty_currency() -> None:
    patches = _valid_production(lemonsqueezy_currency="  ")
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "LEMONSQUEEZY_CURRENCY" in str(exc.value)
    finally:
        _undo(patches)


# ---------------------------------------------------------------------------
# Production guard — Lemon disabled (Stripe runtime decommissioned, T-308)
# ---------------------------------------------------------------------------


def test_lemon_disabled_production_boots_without_stripe_guard() -> None:
    """T-308: with Lemon disabled, production boots — there is no Stripe guard.

    The legacy Stripe test-key guard was removed with the Stripe decommission; a
    Lemon-disabled production deployment simply runs with checkout off and must not
    fail startup on any billing check.
    """
    patches = _valid_production(
        lemonsqueezy_api_key="",
        lemonsqueezy_store_id="",
        lemonsqueezy_variant_id="",
    )
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise — billing simply off
    finally:
        _undo(patches)
