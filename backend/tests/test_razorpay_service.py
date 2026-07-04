"""Unit tests for RazorpayService (issue #44 — Step 3, Plan §4).

Uses ``httpx.MockTransport`` so no real Razorpay calls are made and the tests
are fully deterministic. Covers the payment-link request shape (Basic auth,
amount/currency snapshot, accept_partial off, reference_id = attempt id,
callback, expiry, the seven allow-listed notes), the bounded retry policy
(transient-only, exhaustion raises), ``get_payment`` normalisation + 429
surfacing, and the log-safety contract (keys / nonce / URLs never logged).

Structure mirrors ``test_lemonsqueezy_service.py``.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from services import razorpay_service as rzp_mod
from services.razorpay_service import (
    RazorpayError,
    RazorpayPayment,
    RazorpayRateLimitError,
    RazorpayService,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_KEY_ID = "rzp_test_abc123"
_KEY_SECRET = "s3cr3t_key_value"


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
        price_cents=79900,
        currency="INR",
        expires_at=datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc),
    )


def _user() -> SimpleNamespace:
    return SimpleNamespace(email="buyer@example.com")


@pytest.fixture(autouse=True)
def _razorpay_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the Razorpay config the service reads at call time."""
    monkeypatch.setattr(rzp_mod.settings, "razorpay_key_id", _KEY_ID, False)
    monkeypatch.setattr(rzp_mod.settings, "razorpay_key_secret", _KEY_SECRET, False)
    monkeypatch.setattr(
        rzp_mod.settings,
        "razorpay_success_url",
        "https://app.specforge.dev/billing",
        False,
    )
    monkeypatch.setattr(
        rzp_mod.settings,
        "razorpay_api_base",
        "https://api.razorpay.com",
        False,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instant + deterministic."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(rzp_mod.asyncio, "sleep", _instant)
    monkeypatch.setattr(rzp_mod.random, "uniform", lambda _a, _b: 0.0)


def _client(handler: Any) -> httpx.AsyncClient:
    """An AsyncClient backed by a MockTransport, base_url like prod.

    No auth is set on the client — the service passes Basic auth per request,
    so the handler can assert the Authorization header regardless of how the
    client was built (matching production, where the owned client carries no
    ambient credentials either).
    """
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=rzp_mod.settings.razorpay_api_base,
    )


def _expected_basic_auth() -> str:
    token = base64.b64encode(f"{_KEY_ID}:{_KEY_SECRET}".encode()).decode()
    return f"Basic {token}"


def _link_response(link_id: str = "plink_1", url: str = "https://rzp.io/i/x") -> dict:
    return {"id": link_id, "short_url": url, "status": "created"}


# ---------------------------------------------------------------------------
# create_payment_link — request shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_payment_link_request_shape() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json=_link_response("plink_999", "https://rzp.io/i/pay")
        )

    attempt = _attempt()
    async with _client(handler) as client:
        cid, url = await RazorpayService().create_payment_link(
            attempt, _user(), checkout_nonce="raw-nonce", client=client
        )

    assert (cid, url) == ("plink_999", "https://rzp.io/i/pay")
    assert captured["url"].endswith("/v1/payment_links")

    # HTTP Basic auth from the configured key pair (D5 — no SDK).
    assert captured["headers"]["authorization"] == _expected_basic_auth()

    body = captured["body"]
    # Economics snapshot — the attempt's paise amount, not live config (D8).
    assert body["amount"] == attempt.price_cents
    assert body["currency"] == "INR"
    # Full payment only — grant validation compares the full amount (D10).
    assert body["accept_partial"] is False
    # reference_id is the attempt UUID (36 chars — Razorpay caps at 40, D9).
    assert body["reference_id"] == str(attempt.id)
    assert body["description"] == "SpecForge — 200 credits"
    # Email is UX prefill only; the signed notes block is the trusted channel.
    assert body["customer"] == {"email": "buyer@example.com"}
    # SpecForge owns buyer communication.
    assert body["notify"] == {"sms": False, "email": False}
    assert body["reminder_enable"] is False
    # Link expiry rides the attempt TTL.
    assert body["expire_by"] == int(attempt.expires_at.timestamp())
    # Browser return carries the polling ref; Razorpay appends razorpay_* with &.
    assert (
        body["callback_url"]
        == "https://app.specforge.dev/billing?checkout_ref=ref_abc123"
    )
    assert body["callback_method"] == "get"
    # The seven allow-listed notes, all strings (Lemon custom-data parity).
    assert body["notes"] == {
        "user_id": str(attempt.user_id),
        "checkout_ref": "ref_abc123",
        "checkout_nonce": "raw-nonce",
        "environment": "test",
        "credits": "200",
        "price_cents": "79900",
        "currency": "INR",
    }


@pytest.mark.asyncio
async def test_create_payment_link_environment_live_with_live_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rzp_mod.settings, "razorpay_key_id", "rzp_live_realkey", False)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_link_response())

    async with _client(handler) as client:
        await RazorpayService().create_payment_link(
            _attempt(), _user(), checkout_nonce="n", client=client
        )

    # Razorpay has no test-mode flag on events — the key prefix IS the
    # environment marker the webhook handler validates.
    assert captured["body"]["notes"]["environment"] == "live"


@pytest.mark.asyncio
async def test_create_payment_link_accepts_201() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, json=_link_response("plink_201", "https://rzp.io/i/c")
        )

    async with _client(handler) as client:
        cid, url = await RazorpayService().create_payment_link(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert (cid, url) == ("plink_201", "https://rzp.io/i/c")


@pytest.mark.asyncio
async def test_create_payment_link_malformed_response_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "plink_1"})  # no short_url

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().create_payment_link(
                _attempt(), _user(), checkout_nonce="n", client=client
            )


# ---------------------------------------------------------------------------
# create_payment_link — retry policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_payment_link_retries_then_succeeds_on_429() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {}})
        return httpx.Response(200, json=_link_response("plink_ok"))

    async with _client(handler) as client:
        cid, _url = await RazorpayService().create_payment_link(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert cid == "plink_ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_create_payment_link_retries_then_succeeds_on_5xx() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, json={"error": {}})
        return httpx.Response(200, json=_link_response("plink_ok"))

    async with _client(handler) as client:
        cid, _url = await RazorpayService().create_payment_link(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert cid == "plink_ok"
    assert calls["n"] == 3  # two transient failures + success = bounded by 2 retries


@pytest.mark.asyncio
async def test_create_payment_link_exhausts_retries_then_raises() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": {}})

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().create_payment_link(
                _attempt(), _user(), checkout_nonce="n", client=client
            )
    # 1 initial attempt + 2 retries = 3 calls, then it gives up.
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_create_payment_link_does_not_retry_4xx() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            400, json={"error": {"description": "amount less than minimum"}}
        )

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().create_payment_link(
                _attempt(), _user(), checkout_nonce="n", client=client
            )
    assert calls["n"] == 1  # a 4xx contract error is never retried


@pytest.mark.asyncio
async def test_create_payment_link_retries_network_error_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().create_payment_link(
                _attempt(), _user(), checkout_nonce="n", client=client
            )
    assert calls["n"] == 3  # transient network error retried up to the bound


@pytest.mark.asyncio
async def test_create_payment_link_network_error_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=_link_response("plink_net"))

    async with _client(handler) as client:
        cid, _url = await RazorpayService().create_payment_link(
            _attempt(), _user(), checkout_nonce="n", client=client
        )
    assert cid == "plink_net"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# get_payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_parses_status_and_refund_totals() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/payments/pay_1"
        assert request.headers["authorization"] == _expected_basic_auth()
        return httpx.Response(
            200,
            json={
                "id": "pay_1",
                "status": "refunded",
                "amount": 79900,
                "amount_refunded": 30000,
                "refund_status": "partial",
            },
        )

    async with _client(handler) as client:
        payment = await RazorpayService().get_payment("pay_1", client=client)

    assert payment == RazorpayPayment(
        payment_id="pay_1",
        status="refunded",
        amount_cents=79900,
        amount_refunded_cents=30000,
        refund_status="partial",
    )


@pytest.mark.asyncio
async def test_get_payment_normalises_null_refund_status() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "pay_2",
                "status": "captured",
                "amount": 79900,
                "amount_refunded": 0,
                "refund_status": None,  # Razorpay sends null when never refunded
            },
        )

    async with _client(handler) as client:
        payment = await RazorpayService().get_payment("pay_2", client=client)

    assert payment.status == "captured"
    assert payment.refund_status == ""  # normalised — lane 2 checks membership
    assert payment.amount_refunded_cents == 0


@pytest.mark.asyncio
async def test_get_payment_defaults_missing_fields() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "pay_3"})

    async with _client(handler) as client:
        payment = await RazorpayService().get_payment("pay_3", client=client)

    assert payment.payment_id == "pay_3"
    assert payment.status == ""
    assert payment.amount_cents == 0
    assert payment.amount_refunded_cents == 0
    assert payment.refund_status == ""


@pytest.mark.asyncio
async def test_get_payment_malformed_response_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "captured"})  # no id

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().get_payment("pay_bad", client=client)


@pytest.mark.asyncio
async def test_get_payment_surfaces_429_with_retry_after() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "42"}, json={"error": {}})

    async with _client(handler) as client:
        with pytest.raises(RazorpayRateLimitError) as exc_info:
            await RazorpayService().get_payment("pay_4", client=client)
    assert exc_info.value.retry_after == 42.0


@pytest.mark.asyncio
async def test_get_payment_429_with_malformed_retry_after_defaults() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "soon"}, json={"error": {}})

    async with _client(handler) as client:
        with pytest.raises(RazorpayRateLimitError) as exc_info:
            await RazorpayService().get_payment("pay_4b", client=client)
    assert exc_info.value.retry_after == 1.0


@pytest.mark.asyncio
async def test_get_payment_429_without_header_defers_at_least_a_second() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {}})

    async with _client(handler) as client:
        with pytest.raises(RazorpayRateLimitError) as exc_info:
            await RazorpayService().get_payment("pay_5", client=client)
    assert exc_info.value.retry_after == 1.0


@pytest.mark.asyncio
async def test_get_payment_raises_on_other_non_2xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {}})

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().get_payment("pay_6", client=client)


@pytest.mark.asyncio
async def test_get_payment_network_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _client(handler) as client:
        with pytest.raises(RazorpayError):
            await RazorpayService().get_payment("pay_7", client=client)


# ---------------------------------------------------------------------------
# Log safety — keys / nonce / URLs never logged (Plan §4 security contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_logs_never_carry_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every logged failure path carries structured fields only.

    Exercises the 4xx-rejected, retries-exhausted, and malformed-response log
    lines and asserts the key pair, the raw nonce, the hosted link URL, and the
    success URL never appear — even when the provider echoes them in its
    response body.
    """
    echo = {"error": {"description": f"nonce=raw-nonce key={_KEY_SECRET}"}}

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=echo)

    def exhausted(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json=echo)

    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"short_url": "https://rzp.io/i/leak"})

    with caplog.at_level("ERROR", logger="services.razorpay_service"):
        for handler in (rejected, exhausted, malformed):
            async with _client(handler) as client:
                with pytest.raises(RazorpayError):
                    await RazorpayService().create_payment_link(
                        _attempt(), _user(), checkout_nonce="raw-nonce", client=client
                    )

    assert caplog.records, "expected failure log lines"
    for secret in (_KEY_ID, _KEY_SECRET, "raw-nonce", "rzp.io", "app.specforge.dev"):
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_payment_read_failure_log_carries_only_id_and_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"description": _KEY_SECRET}})

    with caplog.at_level("ERROR", logger="services.razorpay_service"):
        async with _client(handler) as client:
            with pytest.raises(RazorpayError):
                await RazorpayService().get_payment("pay_gone", client=client)

    assert "pay_gone" in caplog.text
    assert _KEY_SECRET not in caplog.text
    assert _KEY_ID not in caplog.text
