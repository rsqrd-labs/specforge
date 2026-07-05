"""Tests for the Razorpay webhook receiver (issue #44 Plan §5/§8).

App-level tests over ``POST /billing/webhook/razorpay`` — the Razorpay
counterpart of the Lemon receiver, same durable verify-before-work shape. They
stub the DB session (no real Postgres) and patch the queue ``enqueue`` so no
Redis is needed, mirroring ``test_billing_webhook.py`` file-for-file.

Coverage:
  * Signature matrix: valid (current + previous secret) → 200; missing / wrong /
    mutated-body → 400; empty-secret config → 400 (fail closed).
  * Event filtering: only ``payment_link.paid`` / ``refund.processed`` are
    stored; ``payment.captured`` / ``payment.failed`` / ``payment_link.expired``
    are acknowledged-ignored; a missing ``event`` field is 400.
  * ``payment_link.paid`` requires the link ``notes.checkout_nonce`` (hashed to
    ``checkout_nonce_hash_from_webhook``, raw NEVER stored) and a matching
    ``notes.environment``; a missing payment id is 400.
  * ``refund.processed`` carries the payment entity's notes (hashed nonce) and
    cumulative ``amount_refunded``; absent notes never reject a signed refund;
    a present-but-mismatched environment does (Lemon ``test_mode`` parity).
  * Sanitisation: PII (email/contact), the hosted URL, and unknown notes keys
    never reach ``normalized_payload``; the seven allow-listed keys do.
  * ``payload_hash`` excludes the ``x-razorpay-event-id`` header (a dashboard
    resend with a fresh event id still dedups); the id is stored as evidence.
  * Duplicate identity (IntegrityError) → 200 without a second row; enqueue
    failure → still 200; the job is ``billing_process_webhook`` /
    ``billing_wh:{id}`` (same fast-lane job as Lemon).
  * The route processes independently of the checkout feature flags (D3), and
    both Razorpay money events sit in the worker's fail-loud set so a signed
    grant can never be acked as a harmless no-op before the Step-5 handlers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import routers.billing as billing_module
from config import settings
from database import get_db
from main import create_app
from models import BillingWebhookEvent

_SECRET = "rzpsec_current"
_PREV_SECRET = "rzpsec_previous"

_NOTES_ALLOWLIST = {
    "user_id",
    "checkout_ref",
    "checkout_nonce_hash_from_webhook",
    "environment",
    "credits",
    "price_cents",
    "currency",
}


# ---------------------------------------------------------------------------
# Stubs (mirroring test_billing_webhook.py)
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
    """Session stub recording the committed BillingWebhookEvent row."""

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


def _notes(
    *,
    nonce: str | None = "raw-nonce-xyz",
    environment: str | None = "test",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The seven-key notes block a SpecForge payment link round-trips."""
    notes: dict[str, Any] = {
        "user_id": str(uuid4()),
        "checkout_ref": "ref_abc",
        "credits": "200",
        "price_cents": "79900",
        "currency": "INR",
    }
    if nonce is not None:
        notes["checkout_nonce"] = nonce
    if environment is not None:
        notes["environment"] = environment
    if extra:
        notes.update(extra)
    return notes


def _payment_entity(
    notes: dict[str, Any] | None,
    *,
    payment_id: str | None = "pay_123",
    amount_refunded: int = 0,
    refund_status: str | None = None,
) -> dict[str, Any]:
    """A realistic payment entity (incl. PII the receiver must strip)."""
    entity: dict[str, Any] = {
        "id": payment_id,
        "entity": "payment",
        "amount": 79900,
        "currency": "INR",
        "status": "captured",
        "method": "upi",
        "amount_refunded": amount_refunded,
        "refund_status": refund_status,
        "email": "jane@example.com",  # PII — must be excluded
        "contact": "+919999999999",  # PII — must be excluded
        "notes": dict(notes) if notes is not None else {},
    }
    if payment_id is None:
        del entity["id"]
    return entity


def _link_paid_event(
    *,
    nonce: str | None = "raw-nonce-xyz",
    environment: str | None = "test",
    payment_id: str | None = "pay_123",
    extra_notes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A realistic ``payment_link.paid`` webhook body."""
    notes = _notes(nonce=nonce, environment=environment, extra=extra_notes)
    return {
        "entity": "event",
        "account_id": "acc_42",
        "event": "payment_link.paid",
        "contains": ["payment_link", "order", "payment"],
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_1",
                    "entity": "payment_link",
                    "reference_id": str(uuid4()),
                    "amount": 79900,
                    "amount_paid": 79900,
                    "currency": "INR",
                    "status": "paid",
                    "short_url": "https://rzp.io/i/secret-url",  # excluded
                    "customer": {"email": "jane@example.com"},  # PII — excluded
                    "notes": notes,
                }
            },
            "order": {"entity": {"id": "order_x", "amount": 79900}},
            "payment": {"entity": _payment_entity(notes, payment_id=payment_id)},
        },
        "created_at": 1751700000,
    }


def _refund_event(
    *,
    payment_notes: dict[str, Any] | None = None,
    refund_id: str | None = "rfnd_1",
    refund_payment_id: str | None = "pay_123",
    amount: int = 79900,
    amount_refunded: int = 79900,
    refund_status: str = "full",
) -> dict[str, Any]:
    """A realistic ``refund.processed`` webhook body (refund + payment entities)."""
    refund_entity: dict[str, Any] = {
        "id": refund_id,
        "entity": "refund",
        "amount": amount,
        "currency": "INR",
        "payment_id": refund_payment_id,
        "status": "processed",
    }
    if refund_id is None:
        del refund_entity["id"]
    if refund_payment_id is None:
        del refund_entity["payment_id"]
    payment = _payment_entity(
        payment_notes,
        payment_id=refund_payment_id or "pay_123",
        amount_refunded=amount_refunded,
        refund_status=refund_status,
    )
    return {
        "entity": "event",
        "account_id": "acc_42",
        "event": "refund.processed",
        "contains": ["refund", "payment"],
        "payload": {
            "refund": {"entity": refund_entity},
            "payment": {"entity": payment},
        },
        "created_at": 1751700500,
    }


def _post(
    client: AsyncClient,
    body: dict[str, Any],
    *,
    signature: str | None = None,
    raw_override: bytes | None = None,
    event_id: str | None = "evt_delivery_1",
):
    raw = raw_override if raw_override is not None else json.dumps(body).encode("utf-8")
    sig = signature if signature is not None else _sign(raw)
    headers = {"X-Razorpay-Signature": sig}
    if event_id is not None:
        headers["x-razorpay-event-id"] = event_id
    return client.post("/billing/webhook/razorpay", content=raw, headers=headers)


@pytest.fixture(autouse=True)
def _razorpay_webhook_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "razorpay_webhook_secret", _SECRET, False)
    monkeypatch.setattr(settings, "razorpay_webhook_secret_prev", _PREV_SECRET, False)
    # A test key ⇒ the server-side environment marker is "test".
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_abc", False)
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_secret", False)


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
            resp = await _post(client, _link_paid_event())
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert session.committed is True

    stored = session.stored_event
    assert stored.provider == "razorpay"
    assert stored.event_name == "payment_link.paid"
    assert stored.provider_object_type == "payments"
    # The inbox identity is the PAYMENT id (D7 — the money object), not the link.
    assert stored.provider_object_id == "pay_123"

    # Enqueue is by inbox row id with the same fast-lane job + dedup job_id as
    # Lemon — no new queue/job names.
    row_id = str(stored.id)
    enq.assert_awaited_once()
    assert enq.await_args.args == ("billing_process_webhook", row_id)
    assert enq.await_args.kwargs["job_id"] == f"billing_wh:{row_id}"


@pytest.mark.asyncio
async def test_valid_signature_previous_secret_accepts() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event()
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
        resp = await _post(client, _link_paid_event(), signature="")
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_wrong_secret_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event()
    raw = json.dumps(body).encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body, signature=_sign(raw, "rzpsec_attacker"))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mutated_body_rejected() -> None:
    """A valid signature over the original body fails once the body is mutated."""
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event()
    good_sig = _sign(json.dumps(body).encode("utf-8"))
    tampered = json.dumps({**body, "account_id": "acc_evil"}).encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body, signature=good_sig, raw_override=tampered)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_empty_secret_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No secret configured → razorpay_webhook_secrets is empty → reject (D3:
    # an unconfigured provider's webhook path fails closed).
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "", False)
    monkeypatch.setattr(settings, "razorpay_webhook_secret_prev", "", False)
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event()
    raw = json.dumps(body).encode("utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Even a "correctly" computed signature against an empty secret is rejected.
        resp = await _post(client, body, signature=_sign(raw, ""))
    assert resp.status_code == 400
    assert session.committed is False


# ---------------------------------------------------------------------------
# Event filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_name",
    ["payment.captured", "payment.failed", "payment_link.expired"],
)
async def test_non_actionable_event_acknowledged_without_storing(
    event_name: str,
) -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event()
    body["event"] = event_name
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert session.committed is False
    assert session.stored_event is None


@pytest.mark.asyncio
async def test_missing_event_name_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event()
    del body["event"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 400
    assert session.committed is False


# ---------------------------------------------------------------------------
# payment_link.paid — grant-authority validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_paid_without_nonce_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _link_paid_event(nonce=None))
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_link_paid_missing_payment_id_rejected() -> None:
    # The payment is the money object AND the inbox identity — required.
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _link_paid_event(payment_id=None))
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_link_paid_environment_mismatch_rejected() -> None:
    # Server key is rzp_test_… ⇒ "test"; a "live" event must never settle.
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _link_paid_event(environment="live"))
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_link_paid_environment_missing_rejected() -> None:
    # The grant authority requires the round-tripped marker — a link SpecForge
    # minted always carries it (hard requirement, unlike refunds).
    session = _InboxSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, _link_paid_event(environment=None))
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_link_paid_hashes_nonce_and_drops_raw() -> None:
    session = _InboxSession()
    app = _make_app(session)
    nonce = "super-secret-nonce"
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _link_paid_event(nonce=nonce))
    assert resp.status_code == 200
    stored = session.stored_event
    expected_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    assert (
        stored.normalized_payload["notes"]["checkout_nonce_hash_from_webhook"]
        == expected_hash
    )
    # The raw nonce must NEVER appear anywhere in the stored payload.
    blob = json.dumps(stored.normalized_payload)
    assert nonce not in blob
    assert "checkout_nonce" not in stored.normalized_payload["notes"]


@pytest.mark.asyncio
async def test_link_paid_sanitisation_excludes_pii_and_unknown_notes() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _link_paid_event(extra_notes={"is_admin": "true", "injected": "evil"})
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    payload = session.stored_event.normalized_payload
    blob = json.dumps(payload)

    # Excluded: PII (payment email/contact, link customer), the hosted URL, the
    # raw nonce, and every unrecognised notes field.
    for forbidden in (
        "jane@example.com",
        "+919999999999",
        "rzp.io/i/secret-url",
        "raw-nonce-xyz",
        "is_admin",
        "injected",
    ):
        assert forbidden not in blob, f"{forbidden!r} must not be stored"
    assert set(payload["notes"].keys()) == _NOTES_ALLOWLIST

    # Included: the fields the Step-5 worker consumes. The payment entity is the
    # grant anchor (D10); the link is corroboration.
    assert payload["provider"] == "razorpay"
    assert payload["payment_id"] == "pay_123"
    assert payload["payment"]["amount"] == 79900
    assert payload["payment"]["currency"] == "INR"
    assert payload["payment"]["status"] == "captured"
    assert payload["payment"]["method"] == "upi"
    assert payload["payment_link"]["payment_link_id"] == "plink_1"
    assert payload["payment_link"]["amount"] == 79900
    assert payload["payment_link"]["status"] == "paid"
    assert payload["refund"] is None


# ---------------------------------------------------------------------------
# refund.processed — reversal payload + asymmetric proof requirements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refund_stored_with_payment_notes_and_cumulative_amount() -> None:
    session = _InboxSession()
    app = _make_app(session)
    nonce = "refund-proof-nonce"
    body = _refund_event(
        payment_notes=_notes(nonce=nonce),
        amount=30000,
        amount_refunded=30000,
        refund_status="partial",
    )
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    stored = session.stored_event
    assert stored.event_name == "refund.processed"
    assert stored.provider_object_id == "pay_123"
    payload = stored.normalized_payload

    # The refund block + the payment entity's CUMULATIVE amount_refunded — the
    # inputs the Step-5 proportional reversal consumes.
    assert payload["refund"] == {
        "refund_id": "rfnd_1",
        "payment_id": "pay_123",
        "amount": 30000,
    }
    assert payload["payment"]["amount_refunded"] == 30000
    assert payload["payment"]["refund_status"] == "partial"
    assert payload["payment_link"] is None

    # The ownership proof rides the payment entity's notes: hashed, never raw.
    expected_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    assert payload["notes"]["checkout_nonce_hash_from_webhook"] == expected_hash
    assert nonce not in json.dumps(payload)


@pytest.mark.asyncio
async def test_refund_without_notes_is_processed() -> None:
    # A signed refund with no notes at all must NOT be rejected (the asymmetry:
    # the grant requires proof; a reversal never does).
    session = _InboxSession()
    app = _make_app(session)
    body = _refund_event(payment_notes=None)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    stored = session.stored_event
    assert (
        stored.normalized_payload["notes"]["checkout_nonce_hash_from_webhook"] is None
    )


@pytest.mark.asyncio
async def test_refund_environment_mismatch_rejected() -> None:
    # Enforced when present (Lemon test_mode parity): a live-marked refund must
    # not settle against a test-keyed server.
    session = _InboxSession()
    app = _make_app(session)
    body = _refund_event(payment_notes=_notes(environment="live"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_refund_environment_absent_is_processed() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _refund_event(payment_notes=_notes(environment=None))
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    assert session.committed is True


@pytest.mark.asyncio
async def test_refund_missing_identity_rejected() -> None:
    session = _InboxSession()
    app = _make_app(session)
    body = _refund_event(refund_id=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await _post(client, body)
    assert resp.status_code == 400
    assert session.committed is False


@pytest.mark.asyncio
async def test_refund_payment_id_falls_back_to_payment_entity() -> None:
    # refund.entity.payment_id absent but the payment entity present → the
    # payment entity's id still keys the inbox row.
    session = _InboxSession()
    app = _make_app(session)
    body = _refund_event(refund_payment_id=None)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, body)
    assert resp.status_code == 200
    assert session.stored_event.provider_object_id == "pay_123"


# ---------------------------------------------------------------------------
# Dedup identity + enqueue resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payload_hash_excludes_event_id() -> None:
    """A dashboard resend minting a fresh event id must not defeat inbox dedup.

    Two deliveries of the same signed body with different ``x-razorpay-event-id``
    headers hash identically (the id is injected AFTER ``payload_hash`` is
    computed), while the id itself is stored inside the payload as ops evidence.
    """
    body = _link_paid_event()
    hashes: list[str] = []
    event_ids: list[str | None] = []
    for delivery_id in ("evt_first", "evt_dashboard_resend"):
        session = _InboxSession()
        app = _make_app(session)
        with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await _post(client, body, event_id=delivery_id)
        assert resp.status_code == 200
        hashes.append(session.stored_event.payload_hash)
        event_ids.append(session.stored_event.normalized_payload["event_id"])
    assert hashes[0] == hashes[1]
    assert event_ids == ["evt_first", "evt_dashboard_resend"]


@pytest.mark.asyncio
async def test_missing_event_id_header_still_processed() -> None:
    session = _InboxSession()
    app = _make_app(session)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _link_paid_event(), event_id=None)
    assert resp.status_code == 200
    assert session.stored_event.normalized_payload["event_id"] is None


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
            resp = await _post(client, _link_paid_event())
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
            resp = await _post(client, _link_paid_event())
    # The inbox row is durably committed; the 60s sweep re-enqueues it.
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert session.committed is True


# ---------------------------------------------------------------------------
# Feature-flag independence (D3) + fail-loud worker guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_razorpay_webhook_processes_regardless_of_checkout_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kill switch off + Lemon selected: old Razorpay refunds must still settle.
    monkeypatch.setattr(settings, "payments_enabled", False, False)
    monkeypatch.setattr(settings, "payment_provider", "lemonsqueezy", False)
    session = _InboxSession()
    app = _make_app(session)
    with patch.object(billing_module, "enqueue", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, _refund_event(payment_notes=_notes()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert session.committed is True


def test_razorpay_money_events_are_fail_loud_in_worker() -> None:
    """Both Razorpay money events are fail-loud AND have registered handlers.

    They sit in the worker's fail-loud ``_ORDER_EVENTS`` set (so an unhandled
    money event dead-letters loudly via ``_dispatch_claimed`` rather than being
    acked as a harmless no-op — the T-297 precedent for Lemon's order events), and
    Step 5 registered their ``(provider, event_name)`` handlers.
    """
    from services.billing_worker import _EVENT_HANDLERS, _ORDER_EVENTS

    assert {"payment_link.paid", "refund.processed"} <= _ORDER_EVENTS
    for event_name in ("payment_link.paid", "refund.processed"):
        assert callable(_EVENT_HANDLERS.get(("razorpay", event_name)))
