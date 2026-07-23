"""Brave research config + production-guard tests (issue #12, Phase 1).

Covers the ``brave_search_enabled`` / ``brave_research_stage_set`` derivations
and the production startup guard that refuses to boot with the flag on but the
subscription key missing (the silent-misconfiguration case).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import config

_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"


def _valid_production(**overrides: object):
    """Patch ``config.settings`` to an OTHERWISE-VALID production config.

    Every non-Brave production check is satisfied, so a raised error can only
    come from the Brave guard under test.
    """
    base: dict[str, object] = {
        "environment": "production",
        "allowed_hosts": "app.example.com",
        "metrics_token": "metrics-token",
        "frontend_url": "https://app.thought2build.com",
        "jwt_private_key": _FAKE_PEM,
        "encryption_master_key": "a-real-non-ci-encryption-key",
        "langfuse_secret_key": "",
        "github_app_id": "",
        "github_app_slug": "",
        "lemonsqueezy_api_key": "",
        "lemonsqueezy_store_id": "",
        "lemonsqueezy_variant_id": "",
        # Brave fully off by default.
        "brave_search_flag": False,
        "brave_search_api_key": "",
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


def test_brave_search_enabled_requires_key_and_flag() -> None:
    with (
        patch.object(config.settings, "brave_search_api_key", "k"),
        patch.object(config.settings, "brave_search_flag", True),
    ):
        assert config.settings.brave_search_enabled is True
    with (
        patch.object(config.settings, "brave_search_api_key", "k"),
        patch.object(config.settings, "brave_search_flag", False),
    ):
        assert config.settings.brave_search_enabled is False
    with (
        patch.object(config.settings, "brave_search_api_key", ""),
        patch.object(config.settings, "brave_search_flag", True),
    ):
        assert config.settings.brave_search_enabled is False


def test_brave_research_stage_set_parses_and_lowercases() -> None:
    with patch.object(config.settings, "brave_research_stages", "Spec, plan ,"):
        assert config.settings.brave_research_stage_set == frozenset({"spec", "plan"})
    with patch.object(config.settings, "brave_research_stages", ""):
        assert config.settings.brave_research_stage_set == frozenset()


def test_default_stage_set_excludes_tasks_and_harness() -> None:
    assert config.settings.brave_research_stage_set == frozenset({"spec", "plan"})


# ---------------------------------------------------------------------------
# Production guard
# ---------------------------------------------------------------------------


def test_prod_guard_passes_when_brave_disabled() -> None:
    patches = _valid_production()
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise (Brave is opt-in)
    finally:
        _undo(patches)


def test_prod_guard_fails_when_flag_on_but_key_missing() -> None:
    patches = _valid_production(brave_search_flag=True, brave_search_api_key="")
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as exc:
            config.validate_production_settings()
        assert "BRAVE_SEARCH_API_KEY" in str(exc.value)
    finally:
        _undo(patches)


def test_prod_guard_passes_when_flag_on_with_key() -> None:
    patches = _valid_production(brave_search_flag=True, brave_search_api_key="brv-key")
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise
    finally:
        _undo(patches)


def test_dev_environment_ignores_brave_guard() -> None:
    patches = _valid_production(
        environment="development",
        brave_search_flag=True,
        brave_search_api_key="",
    )
    _apply(patches)
    try:
        config.validate_production_settings()  # must not raise in development
    finally:
        _undo(patches)
