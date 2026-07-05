"""Tests for the Lemon Squeezy webhook receiver (Phase 22 — T-297).

App-level tests over ``POST /billing/webhook`` — the durable, verify-before-work
trust boundary. They stub the DB session (no real Postgres) and patch the queue
``enqueue`` so no Redis is needed, mirroring the in-process style of the other
billing tests.

Coverage:
  * Signature matrix: valid (current + previous secret) → 200; missing / wrong /
    mutated-body / non-hex → 400; empty-secret config → 400 (fail closed).
  * X-Event-Name must equal meta.event_name; data.type must be "orders";
    test/live mismatch → 400.
  * order_created requires checkout_nonce → 400 when absent; the raw nonce is
    hashed to checkout_nonce_hash_from_webhook and NEVER stored.
  * Sanitisation: PII (email/name/urls), the signature, and unknown custom fields
    never reach normalized_payload; the seven allow-listed custom keys do.
  * Duplicate identity (IntegrityError) → 200 without a second row.
  * Enqueue failure → still 200 (the sweep recovers); job_id is billing_wh:{id}.
  * order_refunded with no custom data is processed (not rejected).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import routers.billing as billing_module
from config import settings
from database import get_db
from main import create_app
from models import BillingWebhookEvent

_SECRET = "lemonsec_current"
_PREV_SECRET = "lemonsec_previous"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FakeRedisPipeline:
    def zremrangebyscore(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    def zadd(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    def zcard(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    def expire(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _NoopRedis:
    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline()


class _InboxSession:
    """Session stub recording the committed BillingWebhookEvent row.

    ``flush`` assigns the server-default UUID (the real DB populates it from
    RETURNING) so the router can build ``billing_wh:{id}``. ``fail_flush_with``
    forces the savepoint flush to raise (duplicate-identity simulation).
    """

    def __init__(self, *, fail_flush_with: Exception | None = None) -> None:
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self._fail_flush_with = fail_flush_with

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        if self._fail_flush_with is not None:
            raise self._fail_flush_with
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    def begin_nested(self) -> "_Savepoint":
        return _Savepoint()

    @property
    def stored_event(self) -> BillingWebhookEvent | None:
        for obj in self.added:
            if isinstance(obj, BillingWebhookEvent):
                return obj
        return None


class _Savepoint:
    async def __aenter__(self) -> "_Savepoint":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False  # never suppress — IntegrityError propagates to the caller


def _make_app(session: _InboxSession):
    app = create_app(redis_client=_NoopRedis())

    async def _fake_db():
        yield session

    app.dependency_overrides[get_db] = _fake_db
    return app


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _order_event(
    *,
    event_name: str = "order_created",
    order_id: str = "order-123",
    nonce: str | None = "raw-nonce-xyz",
    test_mode: bool = True,
    extra_custom: dict[str, Any] | None = None,
    extra_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a realistic Lemon order webhook body (incl. PII to be stripped)."""
    custom: dict[str, Any] = {
        "user_id": str(uuid4()),
        "checkout_ref": "ref_abc",
        "environment": "test",
        "credits": "200",
        "price_cents": "900",
        "currency": "USD",
    }
    if nonce is not None:
        custom["checkout_nonce"] = nonce
    if extra_custom:
        custom.update(extra_custom)
    attributes: dict[str, Any] = {
        "store_id": 42,
        "customer_id": 7,
        "identifier": "ord-ident",
        "order_number": 1001,
        "user_name": "Jane Buyer",  # PII — must be excluded
        "user_email": "jane@example.com",  # PII — must be excluded
        "currency": "USD",
        "subtotal": 900,
        "discount_total": 0,
        "total": 900,
        "status": "paid",
        "refunded": False,
        "refunded_amount": 0,
        "test_mode": test_mode,
        "first_order_item": {
            "id": 555,
            "order_id": 123,
            "product_id": 88,
            "variant_id": 99,
            "price": 900,
            "product_name": "SpecForge Credits",  # PII-ish name — excluded
        },
        "urls": {"receipt": "https://app.lemonsqueezy.com/my-orders/abc"},  # excluded
        "created_at": "2026-06-05T12:00:00.000000Z",
        "updated_at": "2026-06-05T12:00:01.000000Z",
    }
    if extra_attributes:
        attributes.update(extra_attributes)
    return {
        "meta": {"event_name": event_name, "custom_data": custom},
        "data": {"type": "orders", "id": order_id, "attributes": attributes},
    }


def _post(
    client: AsyncClient,
    body: dict[str, Any],
    *,
    signature: str | None = None,
    event_name: str | None = None,
    raw_override: bytes | None = None,
):
    raw = raw_override if raw_override is not None else json.dumps(body).encode("utf-8")
    sig = signature if signature is not None else _sign(raw)
    ev = event_name if event_name is not None else body["meta"]["event_name"]
    return client.post(
        "/billing/webhook",
        content=raw,
        headers={"X-Signature": sig, "X-Event-Name": ev},
    )


@pytest.fixture(autouse=True)
def _webhook_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "lemonsqueezy_webhook_secret", _SECRET, False)
    monkeypatch.setattr(
        settings, "lemonsqueezy_webhook_secret_prev", _PREV_SECRET, False
    )
    monkeypatch.setattr(settings, "lemonsqueezy_test_mode", True, False)


# ---------------------------------------------------------------------------
# Signature matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_signature_current_secret_accepts() -> None:
    session = _InboxSession()
    app = _make_app(session)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock) as enq:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _order_event())
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert session.committed is True
    # Enqueue is by inbox row id with the deterministic dedup job_id.
    row_id = str(session.stored_event.id)
    enq.assert_awaited_once()
    assert enq.await_args.args == ("billing_process_webhook", row_id)
    assert enq.await_args.kwargs["job_id"] == f"billing_wh:{row_id}"


@pytest.mark.asyncio
async def test_valid_signature_previous_secret_accepts() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _order_event()
    raw = json.dumps(body).encode("utf-8")
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body, signature=_sign(raw, _PREV_SECRET))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_signature_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _order_event(), signature="")
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_wrong_secret_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _order_event()
    raw = json.dumps(body).encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body, signature=_sign(raw, "lemonsec_attacker"))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mutated_body_rejected() -> None:
    """A valid signature over the original body fails once the body is mutated."""
    session = _InboxSession()
    app = _make_app(session)
    body = _order_event()
    original = json.dumps(body).encode("utf-8")
    good_sig = _sign(original)
    tampered = json.dumps({**body, "data": {**body["data"], "id": "evil"}}).encode(
        "utf-8"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body, signature=good_sig, raw_override=tampered)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_non_hex_signature_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _order_event(), signature="not-a-hex-signature")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_empty_secret_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No secret configured → lemonsqueezy_webhook_secrets is empty → reject.
    monkeypatch.setattr(settings, "lemonsqueezy_webhook_secret", "", False)
    monkeypatch.setattr(settings, "lemonsqueezy_webhook_secret_prev", "", False)
    session = _InboxSession()
    app = _make_app(session)
    body = _order_event()
    raw = json.dumps(body).encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Even a "correctly" computed signature against an empty secret is rejected.
        resp = await _post(client, body, signature=_sign(raw, ""))
    assert resp.status_code == 400
    assert session.committed is False


# ---------------------------------------------------------------------------
# Parse-time validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_name_header_must_match_meta() -> None:
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _order_event(), event_name="order_refunded")
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_non_order_object_type_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _order_event()
    body["data"]["type"] = "subscriptions"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_test_live_mismatch_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    # Server is test_mode=True (fixture); a live (test_mode=False) event mismatches.
    body = _order_event(test_mode=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_non_order_event_acknowledged_without_storing() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = {
        "meta": {"event_name": "subscription_created", "custom_data": {}},
        "data": {"type": "subscriptions", "id": "sub-1", "attributes": {}},
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert session.committed is False
    assert session.stored_event is None


# ---------------------------------------------------------------------------
# Nonce handling + sanitisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_created_without_nonce_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _order_event(nonce=None))
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_order_created_hashes_nonce_and_drops_raw() -> None:
    session = _InboxSession()
    app = _make_app(session)
    nonce = "super-secret-nonce"
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _order_event(nonce=nonce))
    assert resp.status_code == 200
    stored = session.stored_event
    expected_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    assert (
        stored.normalized_payload["custom"]["checkout_nonce_hash_from_webhook"]
        == expected_hash
    )
    # The raw nonce must NEVER appear anywhere in the stored payload.
    blob = json.dumps(stored.normalized_payload)
    assert nonce not in blob
    assert "checkout_nonce" not in stored.normalized_payload["custom"]


@pytest.mark.asyncio
async def test_sanitisation_excludes_pii_and_unknown_custom() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _order_event(
        extra_custom={"is_admin": "true", "injected": "evil"},
    )
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    payload = session.stored_event.normalized_payload
    blob = json.dumps(payload)

    # Excluded: PII, names, receipt URL, signature, raw nonce.
    for forbidden in (
        "jane@example.com",
        "Jane Buyer",
        "SpecForge Credits",
        "lemonsqueezy.com/my-orders",
        "raw-nonce-xyz",
    ):
        assert forbidden not in blob, f"{forbidden!r} must not be stored"

    # Excluded: every unrecognised custom field (allow-list only).
    assert set(payload["custom"].keys()) == {
        "user_id",
        "checkout_ref",
        "checkout_nonce_hash_from_webhook",
        "environment",
        "credits",
        "price_cents",
        "currency",
    }
    assert "is_admin" not in payload["custom"]
    assert "injected" not in payload["custom"]

    # Included: the allow-listed economic fields downstream tasks consume.
    assert payload["order_id"] == "order-123"
    assert payload["store_id"] == 42
    assert payload["variant_id"] == 99
    assert payload["item_price_cents"] == 900
    assert payload["order_subtotal_cents"] == 900
    assert payload["order_total_cents"] == 900
    assert payload["status"] == "paid"
    assert payload["currency"] == "USD"
    assert payload["created_at"] == "2026-06-05T12:00:00.000000Z"


@pytest.mark.asyncio
async def test_order_refunded_without_custom_data_is_processed() -> None:
    session = _InboxSession()
    app = _make_app(session)
    # A signed refund with no custom_data at all must NOT be rejected.
    body = {
        "meta": {"event_name": "order_refunded", "custom_data": {}},
        "data": {
            "type": "orders",
            "id": "order-refund-1",
            "attributes": {
                "status": "refunded",
                "refunded": True,
                "refunded_amount": 900,
                "total": 900,
                "currency": "USD",
                "test_mode": True,
            },
        },
    }
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    stored = session.stored_event
    assert stored.event_name == "order_refunded"
    assert (
        stored.normalized_payload["custom"]["checkout_nonce_hash_from_webhook"] is None
    )
    assert stored.normalized_payload["refunded_amount_cents"] == 900


# ---------------------------------------------------------------------------
# Idempotency + enqueue resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_identity_returns_200_without_second_row() -> None:
    from sqlalchemy.exc import IntegrityError

    session = _InboxSession(
        fail_flush_with=IntegrityError(None, None, Exception("uq_billing_webhook"))
    )
    app = _make_app(session)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock) as enq:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _order_event())
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_processed"
    assert session.committed is False  # no second row committed
    assert session.rolled_back is True
    enq.assert_not_awaited()  # nothing to enqueue for a duplicate


@pytest.mark.asyncio
async def test_enqueue_failure_still_returns_200() -> None:
    session = _InboxSession()
    app = _make_app(session)
    with patch.object(
        billing_module,
        "enqueue",
        new_callable=AsyncMock,
        side_effect=RuntimeError("redis down"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _order_event())
    # The inbox row is durably committed; the 60s sweep re-enqueues it.
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert session.committed is True


@pytest.mark.asyncio
async def test_row_id_is_uuid_for_enqueue() -> None:
    """The enqueued id is the real inbox row UUID (flush populated it)."""
    session = _InboxSession()
    app = _make_app(session)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock) as enq:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _post(client, _order_event())
    enqueued_id = enq.await_args.args[1]
    # Must parse as a UUID — never "None".
    UUID(enqueued_id)


# ---------------------------------------------------------------------------
# Feature-flag independence (issue #44 D3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lemon_webhook_processes_while_razorpay_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Lemon webhook keeps settling old orders after a provider switch.

    ``payments_enabled``/``payment_provider`` gate checkout creation ONLY (D3):
    with the kill switch off and Razorpay selected, a signed Lemon refund/order
    delivery is still verified, stored, and enqueued.
    """
    monkeypatch.setattr(settings, "payments_enabled", False, False)
    monkeypatch.setattr(settings, "payment_provider", "razorpay", False)
    session = _InboxSession()
    app = _make_app(session)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _order_event(event_name="order_refunded"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert session.committed is True
    assert session.stored_event.provider == "lemonsqueezy"
