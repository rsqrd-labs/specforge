"""Unit tests for LemonSqueezyService (Phase 22 — T-295).

Uses ``httpx.MockTransport`` so no real Lemon Squeezy calls are made and the
tests are fully deterministic. Covers the JSON:API request shape (headers,
relationships, custom_price, enabled variant, discount-off, redirect, custom
data, expiry), the bounded retry policy (transient-only, exhaustion raises), and
``get_order`` normalisation + 429 surfacing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from services import lemonsqueezy_service as lemon_mod
from services.lemonsqueezy_service import (
    LemonOrder,
    LemonSqueezyError,
    LemonSqueezyRateLimitError,
    LemonSqueezyService,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeAttempt:
    id: UUID
    checkout_ref: str
    user_id: UUID
    credits: int
    price_cents: int
    currency: str
    expires_at: datetime


def _attempt() -> _FakeAttempt:
    return _FakeAttempt(
        id=uuid4(),
        checkout_ref="ref_abc123",
        user_id=uuid4(),
        credits=200,
        price_cents=900,
        currency="USD",
        expires_at=datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
    )


def _user() -> SimpleNamespace:
    return SimpleNamespace(email="buyer@example.com")


@pytest.fixture(autouse=True)
def _lemon_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the Lemon config the service reads at call time."""
    monkeypatch.setattr(lemon_mod.settings, "lemonsqueezy_api_key", "lemon_key", False)
    monkeypatch.setattr(lemon_mod.settings, "lemonsqueezy_store_id", "12345", False)
    monkeypatch.setattr(lemon_mod.settings, "lemonsqueezy_variant_id", "67890", False)
    monkeypatch.setattr(
        lemon_mod.settings,
        "lemonsqueezy_success_url",
        "https://app.specforge.dev/billing",
        False,
    )
    monkeypatch.setattr(lemon_mod.settings, "lemonsqueezy_test_mode", True, False)
    monkeypatch.setattr(
        lemon_mod.settings,
        "lemonsqueezy_api_base",
        "https://api.lemonsqueezy.com",
        False,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instant + deterministic."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(lemon_mod.asyncio, "sleep", _instant)
    monkeypatch.setattr(lemon_mod.random, "uniform", lambda _a, _b: 0.0)


def _client(handler: Any) -> httpx.AsyncClient:
    """An AsyncClient backed by a MockTransport, base_url + headers like prod."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=lemon_mod.settings.lemonsqueezy_api_base,
        headers=LemonSqueezyService._headers(),
    )


# ---------------------------------------------------------------------------
# create_checkout — JSON:API request shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_checkout_jsonapi_request_shape() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "co_999",
                    "attributes": {
                        "url": "https://specforge.lemonsqueezy.com/checkout/x"
                    },
                }
            },
        )

    attempt = _attempt()
    async with _client(handler) as client:
        cid, url = await LemonSqueezyService().create_checkout(
            attempt, _user(), checkout_nonce="raw-nonce", client=client
        )

    assert (cid, url) == ("co_999", "https://specforge.lemonsqueezy.com/checkout/x")
    assert captured["url"].endswith("/v1/checkouts")

    headers = captured["headers"]
    assert headers["accept"] == "application/vnd.api+json"
    assert headers["content-type"] == "application/vnd.api+json"
    assert headers["authorization"] == "Bearer lemon_key"

    data = captured["body"]["data"]
    assert data["type"] == "checkouts"
    attrs = data["attributes"]
    # Economics snapshot — the attempt's price, not live config.
    assert attrs["custom_price"] == attempt.price_cents
    assert attrs["test_mode"] is True
    assert attrs["expires_at"] == attempt.expires_at.isoformat()
    # Variant locked; redirect carries the polling ref.
    assert attrs["product_options"]["enabled_variants"] == ["67890"]
    assert (
        attrs["product_options"]["redirect_url"]
        == "https://app.specforge.dev/billing?checkout_ref=ref_abc123"
    )
    # Discount UI off — a coupon cannot change the paid amount.
    assert attrs["checkout_options"]["discount"] is False
    # Email is UX-only; the signed custom data is the trusted channel.
    assert attrs["checkout_data"]["email"] == "buyer@example.com"
    custom = attrs["checkout_data"]["custom"]
    assert custom == {
        "user_id": str(attempt.user_id),
        "checkout_ref": "ref_abc123",
        "checkout_nonce": "raw-nonce",
        "environment": "test",
        "credits": "200",
        "price_cents": "900",
        "currency": "USD",
    }
    # Relationships carry STRING ids.
    rels = data["relationships"]
    assert rels["store"]["data"] == {"type": "stores", "id": "12345"}
    assert rels["variant"]["data"] == {"type": "variants", "id": "67890"}


@pytest.mark.asyncio
async def test_create_checkout_environment_live_when_not_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lemon_mod.settings, "lemonsqueezy_test_mode", False, False)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "co_1",
                    "attributes": {
                        "url": "https://specforge.lemonsqueezy.com/checkout/y"
                    },
                }
            },
        )

    async with _client(handler) as client:
        await LemonSqueezyService().create_checkout(
            _attempt(), _user(), checkout_nonce="n", client=client
        )

    attrs = captured["body"]["data"]["attributes"]
    assert attrs["test_mode"] is False
    assert attrs["checkout_data"]["custom"]["environment"] == "live"


@pytest.mark.asyncio
async def test_create_checkout_accepts_200() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "co_200",
                    "attributes": {
                        "url": "https://specforge.lemonsqueezy.com/checkout/z"
                    },
                }
            },
        )

    async with _client(handler) as client:
        cid, url = await LemonSqueezyService().create_checkout(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert (cid, url) == ("co_200", "https://specforge.lemonsqueezy.com/checkout/z")


@pytest.mark.asyncio
async def test_create_checkout_malformed_response_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"data": {"id": "co_1"}})  # no attributes.url

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyError):
            await LemonSqueezyService().create_checkout(
                _attempt(), _user(), checkout_nonce="n", client=client
            )


# ---------------------------------------------------------------------------
# create_checkout — retry policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_checkout_retries_then_succeeds_on_429() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"errors": []})
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "co_ok",
                    "attributes": {
                        "url": "https://specforge.lemonsqueezy.com/checkout/ok"
                    },
                }
            },
        )

    async with _client(handler) as client:
        cid, _url = await LemonSqueezyService().create_checkout(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert cid == "co_ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_create_checkout_retries_then_succeeds_on_5xx() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, json={"errors": []})
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "co_ok",
                    "attributes": {
                        "url": "https://specforge.lemonsqueezy.com/checkout/ok"
                    },
                }
            },
        )

    async with _client(handler) as client:
        cid, _url = await LemonSqueezyService().create_checkout(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert cid == "co_ok"
    assert calls["n"] == 3  # two transient failures + success = bounded by 2 retries


@pytest.mark.asyncio
async def test_create_checkout_exhausts_retries_then_raises() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"errors": []})

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyError):
            await LemonSqueezyService().create_checkout(
                _attempt(), _user(), checkout_nonce="n", client=client
            )
    # 1 initial attempt + 2 retries = 3 calls, then it gives up.
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_create_checkout_does_not_retry_4xx() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(422, json={"errors": [{"detail": "bad variant"}]})

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyError):
            await LemonSqueezyService().create_checkout(
                _attempt(), _user(), checkout_nonce="n", client=client
            )
    assert calls["n"] == 1  # a 4xx contract error is never retried


@pytest.mark.asyncio
async def test_create_checkout_retries_network_error_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyError):
            await LemonSqueezyService().create_checkout(
                _attempt(), _user(), checkout_nonce="n", client=client
            )
    assert calls["n"] == 3  # transient network error retried up to the bound


@pytest.mark.asyncio
async def test_create_checkout_network_error_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "co_net",
                    "attributes": {
                        "url": "https://specforge.lemonsqueezy.com/checkout/n"
                    },
                }
            },
        )

    async with _client(handler) as client:
        cid, _url = await LemonSqueezyService().create_checkout(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert cid == "co_net"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# get_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_parses_status_and_refund_totals() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/orders/ord_1"
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "ord_1",
                    "attributes": {
                        "status": "partial_refund",
                        "refunded": True,
                        "refunded_amount": 300,
                        "total": 900,
                    },
                }
            },
        )

    async with _client(handler) as client:
        order = await LemonSqueezyService().get_order("ord_1", client=client)

    assert order == LemonOrder(
        provider_order_id="ord_1",
        status="partial_refund",
        refunded=True,
        refunded_amount_cents=300,
        total_cents=900,
    )


@pytest.mark.asyncio
async def test_get_order_defaults_missing_refund_fields() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"id": "ord_2", "attributes": {"status": "paid"}}},
        )

    async with _client(handler) as client:
        order = await LemonSqueezyService().get_order("ord_2", client=client)

    assert order.status == "paid"
    assert order.refunded is False
    assert order.refunded_amount_cents == 0
    assert order.total_cents == 0


@pytest.mark.asyncio
async def test_get_order_surfaces_429_with_retry_after() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "42"}, json={"errors": []})

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyRateLimitError) as exc_info:
            await LemonSqueezyService().get_order("ord_3", client=client)
    assert exc_info.value.retry_after == 42.0


@pytest.mark.asyncio
async def test_get_order_raises_on_other_non_2xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": []})

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyError):
            await LemonSqueezyService().get_order("ord_4", client=client)


@pytest.mark.asyncio
async def test_get_order_network_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _client(handler) as client:
        with pytest.raises(LemonSqueezyError):
            await LemonSqueezyService().get_order("ord_5", client=client)
