"""Tests for the GitHub webhook ingress (Phase 21 — T-271).

Mirrors the audited Stripe webhook test shape: signed fixtures exercise the
verify → dedup → dispatch → 2xx contract and every reject branch. The HMAC
helper is unit-tested directly; the route is exercised through the full ASGI
stack (so the body-size cap and middleware exemptions are real) with ``enqueue``
patched to a fake so no real Redis is touched.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from database import get_db
from main import create_app
from models import GitHubWebhookEvent
from routers import integrations as integrations_router
from services.integrations.github_app_auth import verify_webhook_signature

pytestmark = pytest.mark.asyncio

_SECRET = "ghsecret_current"
_PREV = "ghsecret_previous"
_WEBHOOK_PATH = "/integrations/github/webhook"


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# HMAC helper (unit)
# ---------------------------------------------------------------------------


async def test_verify_accepts_current_and_previous_secret() -> None:
    body = b'{"action":"opened"}'
    assert verify_webhook_signature(body, _sign(body, _SECRET), [_SECRET, _PREV])
    # Signed with the previous secret → still accepted during rotation.
    assert verify_webhook_signature(body, _sign(body, _PREV), [_SECRET, _PREV])


async def test_verify_rejects_bad_signature_and_malformed_header() -> None:
    body = b"payload"
    assert verify_webhook_signature(body, _sign(body, "wrong"), [_SECRET]) is False
    assert verify_webhook_signature(body, None, [_SECRET]) is False
    assert verify_webhook_signature(body, "deadbeef", [_SECRET]) is False  # no sha256=
    # A tampered body invalidates a once-valid signature.
    assert (
        verify_webhook_signature(b"tampered", _sign(body, _SECRET), [_SECRET]) is False
    )


async def test_verify_ignores_empty_secrets() -> None:
    body = b"x"
    assert verify_webhook_signature(body, _sign(body, ""), ["", None]) is False  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Route — DB-backed fakes + patched enqueue (full ASGI stack)
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def eval(self, *args: Any) -> int:
        return 1  # rate-limit Lua: under limit (route is bypass-listed anyway)


class _Nested:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    async def __aenter__(self) -> "_Nested":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _FakeDB:
    """Records inserts; raises IntegrityError on a duplicate delivery_id."""

    def __init__(self, seen_deliveries: set[str]) -> None:
        self._seen = seen_deliveries
        self.added: list[Any] = []
        self.committed = False
        self._pending: Any = None

    def begin_nested(self) -> _Nested:
        return _Nested(self)

    def add(self, obj: Any) -> None:
        self._pending = obj
        self.added.append(obj)

    async def flush(self) -> None:
        delivery = getattr(self._pending, "delivery_id", None)
        if delivery in self._seen:
            raise IntegrityError("dup", {}, Exception("unique"))
        if delivery is not None:
            self._seen.add(delivery)

    async def commit(self) -> None:
        self.committed = True


def _app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    seen: set[str] | None = None,
    enqueue_error: Exception | None = None,
) -> tuple[Any, list[tuple[Any, ...]], _FakeDB]:
    monkeypatch.setattr(settings, "github_app_webhook_secret", _SECRET)
    monkeypatch.setattr(settings, "github_app_webhook_secret_prev", _PREV)

    fake_db = _FakeDB(seen if seen is not None else set())
    enqueued: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> str:
        if enqueue_error is not None:
            raise enqueue_error
        enqueued.append((job, *args))
        return "job-id"

    monkeypatch.setattr(integrations_router, "enqueue", fake_enqueue)

    redis = _FakeRedis()
    app = create_app(redis_client=redis)
    app.state.redis = redis

    async def _get_db():
        yield fake_db

    app.dependency_overrides[get_db] = _get_db
    return app, enqueued, fake_db


def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _headers(body: bytes, secret: str, *, delivery: str, event: str = "issues") -> dict:
    return {
        "X-Hub-Signature-256": _sign(body, secret),
        "X-GitHub-Delivery": delivery,
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


async def test_valid_signed_delivery_enqueues_and_returns_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, enqueued, fake_db = _app(monkeypatch)
    body = b'{"action":"closed","number":1}'
    async with _client(app) as client:
        resp = await client.post(
            _WEBHOOK_PATH, content=body, headers=_headers(body, _SECRET, delivery="d1")
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}
    # Dispatched the dumb reconcile_event delivery with the raw bytes.
    assert enqueued and enqueued[0][0] == "reconcile_event"
    assert enqueued[0][1] == "d1" and enqueued[0][2] == "issues"
    # Committed only after the successful handoff.
    assert fake_db.committed is True


async def test_webhook_accepts_either_rotation_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, enqueued, _ = _app(monkeypatch)
    body = b'{"action":"opened"}'
    async with _client(app) as client:
        resp = await client.post(
            _WEBHOOK_PATH,
            content=body,
            headers=_headers(body, _PREV, delivery="d-prev", event="pull_request"),
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}
    assert enqueued[0][0] == "reconcile_event"


async def test_webhook_rejects_bad_signature_before_any_db_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, enqueued, fake_db = _app(monkeypatch)
    body = b'{"action":"opened"}'
    headers = _headers(body, "attacker-secret", delivery="d-bad")
    async with _client(app) as client:
        resp = await client.post(_WEBHOOK_PATH, content=body, headers=headers)
    assert resp.status_code == 400
    # Verify-before-work: nothing was inserted, dispatched, or committed.
    assert fake_db.added == []
    assert fake_db.committed is False
    assert enqueued == []


async def test_missing_delivery_headers_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, enqueued, _ = _app(monkeypatch)
    body = b"{}"
    async with _client(app) as client:
        resp = await client.post(
            _WEBHOOK_PATH,
            content=body,
            headers={"X-Hub-Signature-256": _sign(body, _SECRET)},  # no delivery/event
        )
    assert resp.status_code == 400
    assert enqueued == []


async def test_webhook_duplicate_delivery_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: set[str] = set()
    app, enqueued, _ = _app(monkeypatch, seen=seen)
    body = b'{"action":"closed"}'
    headers = _headers(body, _SECRET, delivery="dup-1")
    async with _client(app) as client:
        first = await client.post(_WEBHOOK_PATH, content=body, headers=headers)
        second = await client.post(_WEBHOOK_PATH, content=body, headers=headers)
    assert first.status_code == 200 and first.json() == {"status": "queued"}
    # The retried delivery is idempotently skipped — not dispatched twice.
    assert second.status_code == 200 and second.json() == {"status": "duplicate"}
    assert len(enqueued) == 1


async def test_enqueue_unavailable_fails_closed_without_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.queue import QueueUnavailableError

    app, enqueued, fake_db = _app(monkeypatch, enqueue_error=QueueUnavailableError("x"))
    body = b'{"action":"opened"}'
    async with _client(app) as client:
        resp = await client.post(
            _WEBHOOK_PATH,
            content=body,
            headers=_headers(body, _SECRET, delivery="d-503"),
        )
    # 5xx so GitHub retries; the dedup row was never committed (at-least-once).
    assert resp.status_code == 503
    assert fake_db.committed is False
    assert enqueued == []


async def test_webhook_404_when_app_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, _ = _app(monkeypatch)
    monkeypatch.setattr(settings, "github_app_webhook_secret", "")
    monkeypatch.setattr(settings, "github_app_webhook_secret_prev", "")
    body = b"{}"
    async with _client(app) as client:
        resp = await client.post(
            _WEBHOOK_PATH, content=body, headers=_headers(body, _SECRET, delivery="d-x")
        )
    assert resp.status_code == 404


async def test_oversized_body_capped_by_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The cap is read when the app (middleware) is built, so set it first.
    monkeypatch.setattr(settings, "max_request_body_bytes", 1000)
    app, enqueued, _ = _app(monkeypatch)
    big = b"x" * 5000
    async with _client(app) as client:
        resp = await client.post(
            _WEBHOOK_PATH, content=big, headers=_headers(big, _SECRET, delivery="d-big")
        )
    # The global body-size middleware rejects before the handler runs.
    assert resp.status_code == 413
    assert enqueued == []


async def test_webhook_dedup_real_db_commits_once_and_skips_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The idempotency guarantee against a real Postgres unique index.

    The fakes above prove the handler's control flow; this proves the actual
    promise (acceptance #3, "a replayed POST never mutates state"): the real
    delivery_id unique constraint raises on the second insert, the savepoint
    rolls back cleanly, the first delivery commits exactly one row, and the
    worker is dispatched once.
    """
    monkeypatch.setattr(settings, "github_app_webhook_secret", _SECRET)
    monkeypatch.setattr(settings, "github_app_webhook_secret_prev", _PREV)

    enqueued: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> str:
        enqueued.append((job, *args))
        return "job-id"

    monkeypatch.setattr(integrations_router, "enqueue", fake_enqueue)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as db:
            yield db

    redis = _FakeRedis()
    app = create_app(redis_client=redis)
    app.state.redis = redis
    app.dependency_overrides[get_db] = _get_db

    delivery = f"real-{uuid4()}"
    body = b'{"action":"closed","number":7}'
    headers = _headers(body, _SECRET, delivery=delivery)
    try:
        async with _client(app) as client:
            first = await client.post(_WEBHOOK_PATH, content=body, headers=headers)
            second = await client.post(_WEBHOOK_PATH, content=body, headers=headers)
        assert first.json() == {"status": "queued"}
        assert second.json() == {"status": "duplicate"}
        assert len(enqueued) == 1  # dispatched exactly once

        async with maker() as db:
            rows = (
                (
                    await db.execute(
                        select(GitHubWebhookEvent).where(
                            GitHubWebhookEvent.delivery_id == delivery
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1  # exactly one committed row for the delivery
    finally:
        async with maker() as db:
            await db.execute(
                delete(GitHubWebhookEvent).where(
                    GitHubWebhookEvent.delivery_id == delivery
                )
            )
            await db.commit()
        await engine.dispose()
