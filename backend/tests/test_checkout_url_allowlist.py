"""Backend checkout-URL host allowlist (F6 — issue #42).

Both payment providers hand a hosted-checkout URL to the browser. The URL comes
from the authenticated provider API, but we still refuse anything off-domain so a
compromised/misconfigured API response cannot become an open redirect. These
tests pin the allowlist and that a hostile URL raises the provider error rather
than being returned.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.lemonsqueezy_service import (
    LemonSqueezyError,
    LemonSqueezyService,
)
from services.lemonsqueezy_service import (
    _assert_allowed_checkout_url as lemon_assert,
)
from services.razorpay_service import (
    RazorpayError,
    RazorpayService,
)
from services.razorpay_service import (
    _assert_allowed_checkout_url as razorpay_assert,
)


def _fake_response(payload: dict) -> SimpleNamespace:
    """Minimal stand-in for httpx.Response exposing .json()."""
    return SimpleNamespace(json=lambda: json.loads(json.dumps(payload)))


_ATTEMPT = SimpleNamespace(checkout_ref="ref-1", id="attempt-1")


# --- Lemon Squeezy -----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://specforge.lemonsqueezy.com/checkout/abc",
        "https://store.lemonsqueezy.com/buy/xyz",
        "https://lemonsqueezy.com/checkout/abc",
    ],
)
def test_lemon_allows_provider_hosts(url: str) -> None:
    lemon_assert(url)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/checkout",
        "https://lemonsqueezy.com.evil.com/checkout",
        "http://specforge.lemonsqueezy.com/checkout",  # non-HTTPS
        "javascript:alert(1)",
        "https://phish-lemonsqueezy.com/checkout",
    ],
)
def test_lemon_rejects_offdomain_or_insecure(url: str) -> None:
    with pytest.raises(LemonSqueezyError):
        lemon_assert(url)


def test_lemon_parse_rejects_hostile_url() -> None:
    payload = {
        "data": {"id": "co_1", "attributes": {"url": "https://evil.example.com/x"}}
    }
    with pytest.raises(LemonSqueezyError):
        LemonSqueezyService._parse_checkout_response(_fake_response(payload), _ATTEMPT)


def test_lemon_parse_accepts_valid_url() -> None:
    payload = {
        "data": {
            "id": "co_1",
            "attributes": {"url": "https://specforge.lemonsqueezy.com/checkout/ok"},
        }
    }
    checkout_id, url = LemonSqueezyService._parse_checkout_response(
        _fake_response(payload), _ATTEMPT
    )
    assert checkout_id == "co_1"
    assert url.endswith("/checkout/ok")


# --- Razorpay ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://rzp.io/i/abc123",
        "https://api.razorpay.com/v1/x",
        "https://razorpay.com/pay/abc",
    ],
)
def test_razorpay_allows_provider_hosts(url: str) -> None:
    razorpay_assert(url)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/pay",
        "https://rzp.io.evil.com/i/abc",
        "http://rzp.io/i/abc",  # non-HTTPS
        "data:text/html,<script>alert(1)</script>",
    ],
)
def test_razorpay_rejects_offdomain_or_insecure(url: str) -> None:
    with pytest.raises(RazorpayError):
        razorpay_assert(url)


def test_razorpay_parse_rejects_hostile_url() -> None:
    payload = {"id": "plink_1", "short_url": "https://evil.example.com/pay"}
    with pytest.raises(RazorpayError):
        RazorpayService._parse_payment_link_response(_fake_response(payload), _ATTEMPT)


def test_razorpay_parse_accepts_valid_url() -> None:
    payload = {"id": "plink_1", "short_url": "https://rzp.io/i/ok123"}
    checkout_id, url = RazorpayService._parse_payment_link_response(
        _fake_response(payload), _ATTEMPT
    )
    assert checkout_id == "plink_1"
    assert url == "https://rzp.io/i/ok123"
