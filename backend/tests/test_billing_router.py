"""Integration tests for the Lemon-only billing router (Phase 22 — T-296).

App-level tests over the attempt-first checkout flow and ``checkout_ref`` polling.
They stub the DB session (no real Postgres) and monkeypatch the
``lemonsqueezy_service`` singleton, mirroring the in-process style of
``test_stripe_payments.py``.

Coverage:
  * GET /package returns the Lemon economics (incl. currency).
  * POST /checkout: 503 when disabled; commits ``created`` BEFORE Lemon and
    ``provider_created`` AFTER; returns ``checkout_ref`` (never the raw nonce);
    Lemon failure marks the attempt ``failed`` → 502; a failed post-Lemon commit
    is an orphaned 502 that never leaks the checkout URL; rate-limited at 6/hour;
    increments the checkout-created metric.
  * GET /status: 200 only when completed + pack exists; 404 for pending; IDOR
    (cross-user) → 404 on the ``checkout_ref`` path; legacy ``session_id`` works
    only during the Stripe grace window (key set) and 404s post-grace.
  * GET /history reads ``billing_credit_packs``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import BillingCheckoutAttempt, BillingCreditPack, User
from services.lemonsqueezy_service import LemonSqueezyError, lemonsqueezy_service

_USER_ID = uuid4()
_USER = User(
    id=_USER_ID,
    email="buyer@example.com",
    google_id="google-buyer",
    name="Buyer",
    avatar_url=None,
    credit_balance=0,
    created_at=datetime.now(timezone.utc),
)


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
    """Redis stub that always allows every rate-limit check."""

    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline()


class _CountingRedis:
    """Redis stub enforcing the sliding-window rate-limit semantics in-process."""

    def __init__(self) -> None:
        self._sets: dict[str, dict[str, float]] = {}

    async def eval(self, script: str, num_keys: int, *args: Any) -> int:
        key = args[0]
        now_score = float(args[1])
        window_start = float(args[2])
        limit = int(args[3])
        member = args[4]
        ss = self._sets.setdefault(key, {})
        for m in [m for m, s in ss.items() if s <= window_start]:
            del ss[m]
        if len(ss) >= limit:
            return 0
        ss[member] = now_score
        return 1

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline()


class _FakeSession:
    """Async session stub: ordered ``scalar`` results + commit snapshots.

    ``scalars_seq`` feeds successive ``db.scalar(...)`` calls; ``history`` backs
    the ``GET /history`` ``execute().scalars().all()`` read. Each ``commit()``
    records the tracked attempt's status so a test can assert the
    ``created`` → ``provider_created`` lifecycle. ``fail_commit_on`` (1-based)
    forces one commit to raise, simulating the orphaned-checkout path.
    """

    def __init__(
        self,
        *,
        scalars_seq: list[Any] | None = None,
        history: list[Any] | None = None,
        fail_commit_on: int | None = None,
    ) -> None:
        self._scalars = list(scalars_seq or [])
        self._history = list(history or [])
        self.added: list[Any] = []
        self.commit_statuses: list[str | None] = []
        self.commit_count = 0
        self.rollback_count = 0
        self._fail_commit_on = fail_commit_on
        self._attempt: BillingCheckoutAttempt | None = None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, BillingCheckoutAttempt):
            self._attempt = obj

    async def commit(self) -> None:
        self.commit_count += 1
        if self._fail_commit_on == self.commit_count:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("commit failed", None, Exception("boom"))
        self.commit_statuses.append(getattr(self._attempt, "status", None))

    async def refresh(self, obj: Any) -> None:
        return None

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def scalar(self, statement: Any) -> Any:
        return self._scalars.pop(0) if self._scalars else None

    async def execute(self, statement: Any) -> Any:
        class _Result:
            def __init__(self, rows: list[Any]) -> None:
                self._rows = rows

            def scalars(self) -> "_Result":
                return self

            def all(self) -> list[Any]:
                return self._rows

        return _Result(self._history)


def _make_app(session: _FakeSession, *, redis: Any | None = None):
    app = create_app(redis_client=redis or _NoopRedis())

    async def _fake_user() -> User:
        return _USER

    async def _fake_db():
        yield session

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_db] = _fake_db
    return app


def _enable_lemon():
    """Patch settings so ``lemonsqueezy_enabled`` is True with known economics."""
    return [
        patch.object(settings, "lemonsqueezy_api_key", "lemon_key"),
        patch.object(settings, "lemonsqueezy_store_id", "store_1"),
        patch.object(settings, "lemonsqueezy_variant_id", "variant_1"),
        patch.object(settings, "lemonsqueezy_credits_per_purchase", 200),
        patch.object(settings, "lemonsqueezy_price_cents", 900),
        patch.object(settings, "lemonsqueezy_currency", "USD"),
        patch.object(settings, "lemonsqueezy_credit_validity_days", 30),
        patch.object(settings, "lemonsqueezy_checkout_ttl_minutes", 30),
    ]


class _Patches:
    """Apply a list of patch objects as one context manager."""

    def __init__(self, patches: list[Any]) -> None:
        self._patches = patches

    def __enter__(self) -> None:
        for p in self._patches:
            p.start()

    def __exit__(self, *exc: Any) -> None:
        for p in self._patches:
            p.stop()


def _completed_attempt() -> BillingCheckoutAttempt:
    return BillingCheckoutAttempt(
        checkout_ref="ref_done",
        user_id=_USER_ID,
        provider="lemonsqueezy",
        checkout_nonce_hash="hash",
        credits=200,
        price_cents=900,
        currency="USD",
        validity_days=30,
        status="completed",
        provider_order_id="ord_1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


def _active_pack() -> BillingCreditPack:
    now = datetime.now(timezone.utc)
    return BillingCreditPack(
        id=uuid4(),
        user_id=_USER_ID,
        provider="lemonsqueezy",
        provider_order_id="ord_1",
        credits_purchased=200,
        credits_remaining=200,
        price_cents=900,
        currency="USD",
        paid_item_amount_cents=900,
        status="active",
        purchased_at=now,
        expires_at=now + timedelta(days=30),
    )


# ---------------------------------------------------------------------------
# GET /package
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_package_returns_lemon_config() -> None:
    app = _make_app(_FakeSession())
    with _Patches(_enable_lemon()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/billing/package")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "credits": 200,
        "price_cents": 900,
        "validity_days": 30,
        "currency": "USD",
    }


# ---------------------------------------------------------------------------
# POST /checkout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_disabled_returns_503() -> None:
    session = _FakeSession()
    app = _make_app(session)
    # Lemon disabled (empty api key) → 503, and no attempt is ever committed.
    with _Patches([patch.object(settings, "lemonsqueezy_api_key", "")]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/billing/checkout")
    assert resp.status_code == 503
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_checkout_attempt_lifecycle_created_then_provider_created() -> None:
    session = _FakeSession()
    app = _make_app(session)

    captured: dict[str, Any] = {}

    async def _fake_create_checkout(attempt, user, *, checkout_nonce):  # type: ignore[no-untyped-def]
        # The attempt must already be committed as 'created' before Lemon is called.
        captured["status_at_call"] = attempt.status
        captured["commits_before_lemon"] = session.commit_count
        captured["nonce"] = checkout_nonce
        captured["nonce_hash"] = attempt.checkout_nonce_hash
        captured["checkout_ref"] = attempt.checkout_ref
        return "co_123", "https://pay.lemonsqueezy.com/abc"

    with _Patches(_enable_lemon()):
        with patch.object(
            lemonsqueezy_service, "create_checkout", _fake_create_checkout
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post("/billing/checkout")

    assert resp.status_code == 200
    body = resp.json()
    assert body["checkout_url"] == "https://pay.lemonsqueezy.com/abc"
    checkout_ref = body["checkout_ref"]
    assert checkout_ref and checkout_ref == captured["checkout_ref"]

    # Committed 'created' before Lemon, 'provider_created' after.
    assert captured["status_at_call"] == "created"
    assert captured["commits_before_lemon"] == 1
    assert session.commit_statuses == ["created", "provider_created"]

    # Only the sha256 hash is persisted — the raw nonce is never returned.
    import hashlib

    assert (
        captured["nonce_hash"]
        == hashlib.sha256(captured["nonce"].encode("utf-8")).hexdigest()
    )
    assert captured["nonce"] not in resp.text
    assert captured["nonce_hash"] not in resp.text

    attempt = session.added[0]
    assert isinstance(attempt, BillingCheckoutAttempt)
    assert attempt.provider == "lemonsqueezy"
    assert attempt.provider_checkout_id == "co_123"
    assert attempt.status == "provider_created"


@pytest.mark.asyncio
async def test_checkout_lemon_failure_marks_attempt_failed_502() -> None:
    session = _FakeSession()
    app = _make_app(session)

    async def _boom(attempt, user, *, checkout_nonce):  # type: ignore[no-untyped-def]
        raise LemonSqueezyError("provider down")

    with _Patches(_enable_lemon()):
        with patch.object(lemonsqueezy_service, "create_checkout", _boom):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post("/billing/checkout")

    assert resp.status_code == 502
    # Committed 'created', then re-committed 'failed' after the provider error.
    assert session.commit_statuses == ["created", "failed"]
    assert session.added[0].status == "failed"


@pytest.mark.asyncio
async def test_checkout_orphaned_commit_failure_502_no_url() -> None:
    # Fail the SECOND commit (the provider_created transition) — Lemon already
    # minted the checkout, but SpecForge cannot record it.
    session = _FakeSession(fail_commit_on=2)
    app = _make_app(session)

    async def _ok(attempt, user, *, checkout_nonce):  # type: ignore[no-untyped-def]
        return "co_orphan", "https://pay.lemonsqueezy.com/secret-url"

    with _Patches(_enable_lemon()):
        with patch.object(lemonsqueezy_service, "create_checkout", _ok):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post("/billing/checkout")

    assert resp.status_code == 502
    # The orphaned path must NEVER expose the checkout URL.
    assert "secret-url" not in resp.text
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_checkout_rate_limit_sixth_returns_429() -> None:
    session = _FakeSession()
    app = _make_app(session, redis=_CountingRedis())

    async def _ok(attempt, user, *, checkout_nonce):  # type: ignore[no-untyped-def]
        return "co_x", "https://pay.lemonsqueezy.com/x"

    # The rate-limit middleware needs decodable claims to scope per-user; the
    # CSRF middleware uses its own (unpatched) decoder, so it still sees no
    # session for the fake token and lets the request through.
    with _Patches(_enable_lemon()):
        with (
            patch(
                "middleware.rate_limit.decode_access_token_claims",
                return_value={"sub": str(_USER_ID)},
            ),
            patch.object(lemonsqueezy_service, "create_checkout", _ok),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                statuses = []
                for _ in range(6):
                    resp = await client.post(
                        "/billing/checkout",
                        headers={"Authorization": "Bearer fake-token"},
                    )
                    statuses.append(resp.status_code)

    assert statuses[:5] == [200] * 5, statuses
    assert statuses[5] == 429


@pytest.mark.asyncio
async def test_checkout_created_metric_increments() -> None:
    from services.observability import BILLING_CHECKOUT_CREATED

    session = _FakeSession()
    app = _make_app(session)

    async def _ok(attempt, user, *, checkout_nonce):  # type: ignore[no-untyped-def]
        return "co_x", "https://pay.lemonsqueezy.com/x"

    created = BILLING_CHECKOUT_CREATED.labels(provider="lemonsqueezy")
    before = created._value.get()
    with _Patches(_enable_lemon()):
        with patch.object(lemonsqueezy_service, "create_checkout", _ok):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post("/billing/checkout")

    assert resp.status_code == 200
    assert created._value.get() == before + 1


# ---------------------------------------------------------------------------
# GET /status — checkout_ref path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_checkout_ref_completed_returns_200() -> None:
    attempt = _completed_attempt()
    pack = _active_pack()
    session = _FakeSession(scalars_seq=[attempt, pack])
    app = _make_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/billing/status", params={"checkout_ref": "ref_done"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["credits_added"] == 200
    # First-touch telemetry was stamped + committed.
    assert attempt.success_redirect_seen_at is not None
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_status_checkout_ref_pending_returns_404() -> None:
    attempt = _completed_attempt()
    attempt.status = "provider_created"  # not yet granted
    attempt.provider_order_id = None
    session = _FakeSession(scalars_seq=[attempt])
    app = _make_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/billing/status", params={"checkout_ref": "ref_done"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_checkout_ref_cross_user_returns_404_idor() -> None:
    # The user-scoped query yields nothing for someone else's ref → 404 (not 403).
    session = _FakeSession(scalars_seq=[None])
    app = _make_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/billing/status", params={"checkout_ref": "someone_elses_ref"}
        )

    assert resp.status_code == 404
    assert session.commit_count == 0  # nothing to stamp for a non-matching ref


# ---------------------------------------------------------------------------
# GET /status — legacy session_id grace path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_legacy_session_id_ignored_after_decommission() -> None:
    # T-308: the legacy Stripe ``session_id`` polling path is gone. A request with
    # only session_id has no usable identifier and is answered 404 (the StripeCreditPack
    # table is never queried — a pack present in the session is not returned).
    session = _FakeSession(scalars_seq=[_active_pack()])
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/billing/status", params={"session_id": "cs_legacy"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_no_identifier_returns_404() -> None:
    session = _FakeSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/billing/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_reads_billing_credit_packs() -> None:
    pack = _active_pack()
    session = _FakeSession(history=[pack])
    app = _make_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/billing/history")

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["credits_purchased"] == 200
    assert rows[0]["status"] == "active"


# ---------------------------------------------------------------------------
# POST /admin/correction — wired require_admin authorization (T-302)
# ---------------------------------------------------------------------------
#
# These drive the real Depends(require_admin) chain through the ASGI app to prove
# the endpoint is wired and CSRF lets an authenticated request reach authz. The
# grant/idempotency/debt money-path correctness is covered against a real Postgres
# in test_billing_admin_correction.py.

_ADMIN_CORRECTION_BODY = {
    "provider": "lemonsqueezy",
    "provider_order_id": "ord_admin_http",
    "target_user_id": str(uuid4()),
    "credits": 200,
    "price_cents": 900,
    "currency": "USD",
    "reason": "paid order, webhook never arrived",
    "evidence_url": "https://support.specforge.dev/tickets/1",
}


@pytest.mark.asyncio
async def test_admin_correction_forbidden_for_non_admin() -> None:
    session = _FakeSession()
    app = _make_app(session)  # _USER (buyer@example.com) is the authenticated user
    with _Patches([patch.object(settings, "admin_user_emails", "admin@specforge.dev")]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/billing/admin/correction", json=_ADMIN_CORRECTION_BODY
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_correction_forbidden_when_allowlist_empty() -> None:
    session = _FakeSession()
    app = _make_app(session)
    # Empty allowlist authorises no one — not even an otherwise-plausible admin.
    with _Patches([patch.object(settings, "admin_user_emails", "")]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/billing/admin/correction", json=_ADMIN_CORRECTION_BODY
            )
    assert resp.status_code == 403
