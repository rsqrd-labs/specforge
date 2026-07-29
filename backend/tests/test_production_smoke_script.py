from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "production_smoke.py"
_SPEC = importlib.util.spec_from_file_location("production_smoke", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
production_smoke = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = production_smoke
_SPEC.loader.exec_module(production_smoke)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.thought2build.example",
        "https://api.thought2build.example/base",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)
def test_validate_api_url_accepts_https_and_loopback(url: str) -> None:
    assert production_smoke.validate_api_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.thought2build.example",
        "https://user:pass@api.thought2build.example",
        "https://api.thought2build.example?target=evil",
        "https://api.thought2build.example/#fragment",
    ],
)
def test_validate_api_url_rejects_unsafe_origins(url: str) -> None:
    with pytest.raises(production_smoke.SmokeFailure):
        production_smoke.validate_api_url(url)


def test_redirect_handler_rejects_cross_origin() -> None:
    request = production_smoke.Request("https://api.thought2build.example/health")
    handler = production_smoke.SameOriginRedirectHandler()

    with pytest.raises(production_smoke.SmokeFailure):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )


def _config(**overrides) -> object:
    base = {
        "api_url": "https://api.thought2build.example",
        "access_token": "token",
        "metrics_token": None,
        "provider": None,
        "model": None,
        "run_llm_smoke": False,
        "public_only": False,
    }
    base.update(overrides)
    return production_smoke.SmokeConfig(**base)


def _payload(**overrides) -> dict:
    anthropic = {
        "id": "anthropic",
        "name": "Anthropic",
        "configured": True,
        "selectable": True,
        "health": "healthy",
        "message": "No provider issues detected.",
        "probed_model": "claude-opus-5",
    }
    anthropic.update(overrides)
    return {
        "providers": [anthropic],
        "priority": ["anthropic", "openai", "google"],
    }


def test_provider_health_accepts_a_configured_healthy_primary() -> None:
    production_smoke.assert_provider_health(_config(), _payload())


def test_provider_health_rejects_a_placeholder_key() -> None:
    """The live production misconfiguration: the smoke must fail, not pass.

    A ``placeholder-`` prefixed key reads as ``configured: false``, and every
    generation then fails to route while /health still reports ok.
    """
    with pytest.raises(production_smoke.SmokeFailure, match="not configured"):
        production_smoke.assert_provider_health(
            _config(),
            _payload(configured=False, health="not_configured", probed_model=None),
        )


def test_provider_health_rejects_an_unhealthy_primary() -> None:
    with pytest.raises(production_smoke.SmokeFailure, match="unhealthy"):
        production_smoke.assert_provider_health(
            _config(),
            _payload(
                health="unhealthy", message="Recent failures: AuthenticationError."
            ),
        )


def test_provider_health_checks_the_priority_leader_not_the_first_listed() -> None:
    """The provider that matters is the one routing will actually pick."""
    payload = _payload()
    payload["priority"] = ["openai", "anthropic", "google"]

    with pytest.raises(production_smoke.SmokeFailure, match="not in"):
        production_smoke.assert_provider_health(_config(), payload)


def test_provider_health_honours_an_explicit_provider_override() -> None:
    payload = _payload()
    payload["priority"] = ["openai", "anthropic", "google"]

    production_smoke.assert_provider_health(_config(provider="anthropic"), payload)


def test_provider_health_rejects_an_empty_response() -> None:
    with pytest.raises(production_smoke.SmokeFailure):
        production_smoke.assert_provider_health(
            _config(), {"providers": [], "priority": ["anthropic"]}
        )
