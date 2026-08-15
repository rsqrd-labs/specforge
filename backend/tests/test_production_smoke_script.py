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


def test_wait_until_finalisable_polls_until_quality_gate_settles(monkeypatch) -> None:
    client = production_smoke.SmokeClient(_config())
    responses = iter(
        [
            (200, {"quality_gate": {"status": "checking"}}, {}),
            (200, {"id": "stage-1", "quality_gate": {"status": "advisory"}}, {}),
        ]
    )
    monkeypatch.setattr(client, "request", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _seconds: None)

    stage = client.wait_until_finalisable("stage-1")

    assert stage["id"] == "stage-1"


def test_wait_until_finalisable_has_a_hard_timeout(monkeypatch) -> None:
    client = production_smoke.SmokeClient(_config())
    samples = iter([0.0, 0.0, production_smoke.QUALITY_GATE_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(production_smoke.time, "monotonic", lambda: next(samples))
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        client,
        "request",
        lambda *_args, **_kwargs: (
            200,
            {"quality_gate": {"status": "checking"}},
            {},
        ),
    )

    with pytest.raises(production_smoke.SmokeFailure, match="did not settle"):
        client.wait_until_finalisable("stage-1")


def test_run_archives_workspace_when_a_later_check_fails(monkeypatch) -> None:
    requested: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, _config) -> None:
            pass

        def request(self, method: str, path: str, **_kwargs):
            requested.append((method, path))
            if path == "/health":
                return 200, {"status": "ok"}, {}
            if path == "/auth/me":
                return 200, {"id": "user-1", "email": "smoke@example.com"}, {}
            if path == "/providers/health":
                return 403, {}, {}
            if path == "/credits/balance":
                return 200, {"balance": 100}, {}
            if method == "POST" and path == "/workspaces":
                return (
                    201,
                    {
                        "id": "workspace-1",
                        "stages": [
                            {"type": name}
                            for name in ("spec", "plan", "tasks", "harness")
                        ],
                    },
                    {},
                )
            if method == "GET" and path == "/workspaces/workspace-1":
                raise production_smoke.SmokeFailure("fetch failed")
            if method == "DELETE" and path == "/workspaces/workspace-1":
                return 204, "", {}
            raise AssertionError((method, path))

    monkeypatch.setattr(production_smoke, "load_config", _config)
    monkeypatch.setattr(production_smoke, "SmokeClient", FakeClient)

    with pytest.raises(production_smoke.SmokeFailure, match="fetch failed"):
        production_smoke.run()

    assert ("DELETE", "/workspaces/workspace-1") in requested


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
