"""Stripe runtime-decommission contract (Phase 22 — T-308).

The bounded late-Stripe webhook grace window (T-303) is removed. These tests pin
the post-removal contract:

  * ``POST /billing/webhook`` answers a Stripe-shaped request (one carrying a
    ``Stripe-Signature`` header) with ``{"status": "ignored_provider_disabled"}``
    and performs **no** DB write and **no** signature-verification claim.
  * The ``stripe`` SDK and the Stripe payment-service module are gone; no runtime
    module imports them.
  * The ``STRIPE_*`` settings and the scoped Stripe test-key startup guard are gone.
  * The ``stripe_credit_packs`` / ``stripe_webhook_events`` audit models are
    RETAINED (the historical financial record outlives the code).

These are in-process (no Postgres / no ``stripe`` package required), so they run
in the default ``backend/tests`` suite and in CI.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from database import get_db
from main import create_app

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Webhook: Stripe-shaped request is rejected before any DB write
# ---------------------------------------------------------------------------


class _NoopRedis:
    """Redis stub that always allows every rate-limit check."""

    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1


class _RecordingSession:
    """Async session stub that records any write/read attempt.

    The post-grace webhook must not touch the DB for a Stripe-shaped request, so a
    test asserts none of these were ever called.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commit_count = 0
        self.flush_count = 0
        self.scalar_count = 0
        self.execute_count = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:  # pragma: no cover - not expected
        pass

    async def flush(self) -> None:
        self.flush_count += 1

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        self.scalar_count += 1
        return None

    async def execute(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        self.execute_count += 1
        return None


def _make_app(session: _RecordingSession):
    app = create_app(redis_client=_NoopRedis())

    async def _fake_db():
        yield session

    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_stripe_shaped_webhook_ignored_provider_disabled_no_db_write() -> None:
    """A Stripe-Signature request is answered ignored_provider_disabled, no DB write."""
    session = _RecordingSession()
    app = _make_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/billing/webhook",
            content=b'{"type": "checkout.session.completed", "id": "evt_legacy"}',
            headers={
                "Stripe-Signature": "t=1,v1=deadbeef",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored_provider_disabled"}
    # No DB interaction whatsoever — rejected before any body read or persistence.
    assert session.added == []
    assert session.commit_count == 0
    assert session.flush_count == 0
    assert session.scalar_count == 0
    assert session.execute_count == 0


# ---------------------------------------------------------------------------
# SDK + service removed; no runtime import of stripe
# ---------------------------------------------------------------------------


def test_stripe_sdk_not_installed() -> None:
    """The ``stripe`` package is uninstalled (dependency removed from pyproject)."""
    with pytest.raises(ModuleNotFoundError):
        __import__("stripe")


def test_stripe_payment_service_file_deleted() -> None:
    service_file = _BACKEND_ROOT / "services" / ("stripe_" + "service.py")
    assert (
        not service_file.exists()
    ), "The Stripe payment-service module must be deleted by the decommission. T-308."


def test_no_runtime_module_imports_stripe() -> None:
    """No backend runtime source carries a Stripe runtime token — the T-308 grep.

    The forbidden tokens (the Stripe SDK import forms, the Stripe payment-service
    name, the Stripe test-key prefix, and the Stripe webhook-secret prefix) are
    assembled from fragments at runtime so this guard file is itself grep-clean.
    Retained audit models, migrations, and tests are excluded.
    """
    forbidden = (
        "import " + "stripe",
        "from " + "stripe",
        "stripe_" + "service",
        "sk_" + "test_",
        "wh" + "sec_",
    )
    offenders: list[str] = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(_BACKEND_ROOT)
        parts = rel.parts
        if parts[0] in {"tests", "migrations", ".venv"}:
            continue
        # Retained Stripe audit models are the only allowed home for the name.
        if parts[0] == "models" and parts[-1].startswith("stripe_"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                offenders.append(f"{rel}: {token}")
    assert not offenders, f"Stripe runtime tokens remain after T-308: {offenders}"


def test_stripe_removed_from_dependencies() -> None:
    pyproject = (_BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(pyproject)
    deps = data.get("project", {}).get("dependencies", [])
    assert not any(
        d.lower().startswith("stripe") for d in deps
    ), "stripe must be removed from pyproject dependencies. T-308."
    reqs = (_BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert not any(
        line.strip().lower().startswith("stripe") for line in reqs.splitlines()
    ), "stripe must be removed from requirements.txt. T-308."


# ---------------------------------------------------------------------------
# Config: STRIPE_* settings + scoped guard removed
# ---------------------------------------------------------------------------


def test_stripe_settings_removed_from_config() -> None:
    from config import settings

    for attr in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_price_cents",
        "stripe_credits_per_purchase",
        "stripe_credit_validity_days",
        "stripe_success_url",
        "stripe_cancel_url",
        "stripe_webhook_grace_open",
    ):
        assert not hasattr(
            settings, attr
        ), f"Settings.{attr} must be removed by the Stripe decommission. T-308."


# ---------------------------------------------------------------------------
# RETAINED: the Stripe audit models / tables survive the code removal
# ---------------------------------------------------------------------------


def test_stripe_audit_models_retained() -> None:
    assert (_BACKEND_ROOT / "models" / "stripe_credit_pack.py").exists()
    assert (_BACKEND_ROOT / "models" / "stripe_webhook_event.py").exists()
    from models.stripe_credit_pack import StripeCreditPack
    from models.stripe_webhook_event import StripeWebhookEvent

    assert StripeCreditPack.__tablename__ == "stripe_credit_packs"
    assert StripeWebhookEvent.__tablename__ == "stripe_webhook_events"
