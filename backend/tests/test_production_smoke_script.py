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
        "https://api.specforge.example",
        "https://api.specforge.example/base",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)
def test_validate_api_url_accepts_https_and_loopback(url: str) -> None:
    assert production_smoke.validate_api_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.specforge.example",
        "https://user:pass@api.specforge.example",
        "https://api.specforge.example?target=evil",
        "https://api.specforge.example/#fragment",
    ],
)
def test_validate_api_url_rejects_unsafe_origins(url: str) -> None:
    with pytest.raises(production_smoke.SmokeFailure):
        production_smoke.validate_api_url(url)


def test_redirect_handler_rejects_cross_origin() -> None:
    request = production_smoke.Request("https://api.specforge.example/health")
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
