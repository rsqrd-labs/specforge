"""Offline tests for scripts/check_openrouter_catalog_drift.py (issue #152).

The script itself needs live network access, so CI cannot run it (and should
not: on a private repo a scheduled job bills ~1 minute per firing regardless of
runtime). These cover its pure decision logic against recorded payload shapes,
so a regression in the comparison rules is caught without a network call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_openrouter_catalog_drift as drift  # noqa: E402

from services.llm.model_catalog import model_entry  # noqa: E402


def _endpoint(**overrides):
    """A DeepSeek-host endpoint payload, shaped like the live API response."""
    payload = {
        "provider_name": "DeepSeek",
        "supports_implicit_caching": True,
        "max_completion_tokens": 384_000,
        "supported_parameters": ["max_tokens", "reasoning", "reasoning_effort"],
        "pricing": {
            "prompt": "0.00000014",
            "completion": "0.00000028",
            "input_cache_read": "0.0000000028",
        },
    }
    payload.update(overrides)
    return payload


def test_per_million_converts_per_token_decimal_strings() -> None:
    assert drift._per_million("0.00000014") == pytest.approx(0.14)
    assert drift._per_million("0.0000000028") == pytest.approx(0.0028)
    assert drift._per_million(None) is None
    assert drift._per_million("") is None
    assert drift._per_million("not-a-number") is None


def test_rates_agree_tolerates_float_representation_only() -> None:
    # Round-trip noise on a per-token string must not read as a price change...
    assert drift._rates_agree(0.14, 0.14000000000000001)
    # ...but a real change must.
    assert not drift._rates_agree(1.536, 2.52)
    assert not drift._rates_agree(0.14, 0.28)
    # None is only equal to None — a rate appearing or disappearing is drift.
    assert drift._rates_agree(None, None)
    assert not drift._rates_agree(None, 0.14)
    assert not drift._rates_agree(0.14, None)


def test_pinned_endpoint_matches_display_name_against_the_routing_slug() -> None:
    """The endpoints payload names hosts in display form ("DeepSeek") while the
    routing allowlist takes slugs ("deepseek")."""
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    payload = {"endpoints": [_endpoint(provider_name="Fireworks"), _endpoint()]}

    matched = drift._pinned_endpoint(payload, entry)

    assert matched is not None
    assert matched["provider_name"] == "DeepSeek"


def test_pinned_endpoint_returns_none_when_the_host_stopped_serving_the_slug() -> None:
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    payload = {"endpoints": [_endpoint(provider_name="Fireworks")]}

    assert drift._pinned_endpoint(payload, entry) is None


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:  # pragma: no cover - never non-200 here
        return None

    def json(self) -> dict:
        return {"data": self._payload}


class _FakeClient:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code

    def get(self, _url: str) -> _FakeResponse:
        return _FakeResponse(self._payload, self._status_code)


def test_matching_live_payload_reports_no_drift() -> None:
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    client = _FakeClient({"endpoints": [_endpoint()]})

    assert (
        drift._check_entry(
            entry,
            client,
            model_metadata={
                "reasoning": {
                    "mandatory": False,
                    "supported_efforts": ["xhigh", "high"],
                }
            },
        ).issues
        == []
    )


@pytest.mark.parametrize(
    ("overrides", "expected_fragment"),
    [
        (
            {"pricing": {"prompt": "0.0000005", "completion": "0.00000028"}},
            "input_cost_per_million",
        ),
        ({"supports_implicit_caching": False}, "supports_implicit_caching"),
        ({"max_completion_tokens": 32_768}, "below the catalog ceiling"),
        (
            {"supported_parameters": ["max_tokens"]},
            "does not accept that parameter",
        ),
    ],
)
def test_each_drift_class_is_detected(overrides: dict, expected_fragment: str) -> None:
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    client = _FakeClient({"endpoints": [_endpoint(**overrides)]})

    issues = drift._check_entry(entry, client).issues

    assert any(expected_fragment in issue for issue in issues), issues


def test_a_disappeared_pinned_host_is_reported_as_a_503_risk() -> None:
    """Pinning removes the fallback, so losing the pinned host is a permanent
    503 on every request rather than a silent reroute."""
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    client = _FakeClient({"endpoints": [_endpoint(provider_name="Novita")]})

    issues = drift._check_entry(entry, client).issues

    assert any("503" in issue for issue in issues), issues


def test_a_cache_write_premium_appearing_is_drift() -> None:
    """The catalog sets cache_write_5m to base input for DeepSeek (no premium).
    If the pinned host starts charging one, the ledger silently under-reports —
    exactly the trap the retired qwen entry carried ($2.50 write vs $2.00 base).
    """
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    pricing = dict(_endpoint()["pricing"], input_cache_write="0.00000035")
    client = _FakeClient({"endpoints": [_endpoint(pricing=pricing)]})

    issues = drift._check_entry(entry, client).issues

    assert any("cache_write_5m_cost_per_million" in issue for issue in issues), issues


def test_unsupported_reasoning_effort_is_detected_from_model_metadata() -> None:
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    client = _FakeClient({"endpoints": [_endpoint()]})

    issues = drift._check_entry(
        entry,
        client,
        model_metadata={
            "reasoning": {
                "mandatory": False,
                "supported_efforts": ["medium"],
            }
        },
    ).issues

    assert any("supported_efforts" in issue for issue in issues), issues


def test_mandatory_reasoning_is_a_non_core_and_health_probe_drift() -> None:
    entry = model_entry("openrouter", "deepseek/deepseek-v4-flash")
    client = _FakeClient({"endpoints": [_endpoint()]})

    issues = drift._check_entry(
        entry,
        client,
        model_metadata={
            "reasoning": {
                "mandatory": True,
                "supported_efforts": ["high"],
            }
        },
    ).issues

    assert any("mandatory=true" in issue for issue in issues), issues
