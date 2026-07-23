"""Lemon Squeezy integration service for Thought2Build credit purchases.

Phase 22 — T-295 (Plan §25.6). The provider-neutral checkout that supersedes
Stripe at runtime. This module is a thin, pure wrapper over the existing
``httpx`` dependency — **no Lemon SDK** — exposing exactly two operations:

  * :meth:`LemonSqueezyService.create_checkout` — mint a hosted checkout for an
    already-committed ``billing_checkout_attempts`` row (the attempt-first flow,
    T-296). Thought2Build is the authority for the attempt; the checkout is created
    against the attempt's economics **snapshot** (``custom_price`` =
    ``attempt.price_cents``) so an in-flight config price change can never alter
    what the user is charged, and a coupon cannot either (``discount`` UI off).
  * :meth:`LemonSqueezyService.get_order` — re-read a single order Thought2Build
    already has by id, for reconcile lane 2 (T-301). It is **never** used to
    discover or prove an order — the signed ``order_created`` webhook is the sole
    grant authority. It surfaces a 429 / ``Retry-After`` to the caller so lane 2
    backs off rather than hammering the provider.

Security contract (Plan §25 SR / T-304):
  * The API key and the signed checkout URL are **never logged**. Failure logs
    carry only structured fields (checkout_ref, attempt id, HTTP status, attempt
    number) — never response bodies, headers, or the raw nonce.
  * The raw ``checkout_nonce`` is passed in by the caller (the attempt row stores
    only its sha256); it is embedded in the checkout custom data so the signed
    webhook can prove it back, and is never logged.
  * Custom-data scalars are sent as strings — Lemon Squeezy stringifies custom
    data on the webhook round-trip, so T-297 reads them back as strings.

The service is pure (no DB session): on retry exhaustion it raises and the
caller (T-296) marks the attempt failed → 502.
"""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator
from urllib.parse import urlencode, urlparse

import httpx

from config import settings

# Hosted-checkout hosts we will hand to the browser. The URL comes from the
# authenticated Lemon Squeezy API, but we still refuse anything off-domain so a
# compromised/misconfigured API response cannot turn our checkout into an open
# redirect (F6 — issue #42). The frontend also validates (safeCheckoutUrl); this
# is the server-side half.
_LEMON_CHECKOUT_HOST_SUFFIXES = (".lemonsqueezy.com",)


def _assert_allowed_checkout_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = host.endswith(_LEMON_CHECKOUT_HOST_SUFFIXES) or host in (
        "lemonsqueezy.com",
    )
    if parsed.scheme != "https" or not allowed:
        raise LemonSqueezyError(
            "Lemon Squeezy returned a checkout URL off the expected domain"
        )


if TYPE_CHECKING:  # pragma: no cover - typing only
    from models import User
    from models.billing_checkout_attempt import BillingCheckoutAttempt

logger = logging.getLogger(__name__)

# JSON:API media type required on every Lemon Squeezy request/response.
_JSON_API_MEDIA_TYPE = "application/vnd.api+json"

# Per-operation timeouts (Plan §25.6 T-295): connect 10s / read 30s / write 10s
# / pool 5s. A slow provider must not pin a request worker indefinitely.
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# Bounded connection pool — the billing path is low-QPS; cap so a provider stall
# cannot exhaust file descriptors.
_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5)

# Retry policy for create_checkout: at most two retries (three attempts total) on
# transient failures only. 4xx (other than 429) is a contract error — never
# retried. Backoff is exponential with full jitter to avoid a thundering herd.
_MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 0.5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class LemonSqueezyError(Exception):
    """A Lemon Squeezy API call failed (non-2xx after retries, or a parse error)."""


class LemonSqueezyRateLimitError(LemonSqueezyError):
    """Lemon Squeezy returned 429. Carries ``retry_after`` so the caller backs off.

    Raised by :meth:`LemonSqueezyService.get_order` (reconcile lane 2, T-301): the
    re-read lane surfaces the rate limit rather than retrying inline.
    """

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Lemon Squeezy rate limited; retry after {retry_after:.1f}s")
        # Always defer at least a second so a tight loop cannot spin.
        self.retry_after = max(1.0, float(retry_after))


@dataclass(frozen=True)
class LemonOrder:
    """Normalised view of a Lemon Squeezy order (reconcile lane 2, T-301).

    ``status`` is the provider status string (``paid`` / ``refunded`` /
    ``partial_refund`` / ``pending`` / …). Refund totals are normalised to cents.
    """

    provider_order_id: str
    status: str
    refunded: bool
    refunded_amount_cents: int
    total_cents: int


def _environment() -> str:
    """The custom-data environment marker T-297 validates against.

    ``"test"`` while ``lemonsqueezy_test_mode`` is on, ``"live"`` otherwise — kept
    in lockstep with the top-level ``test_mode`` flag on the checkout.
    """
    return "test" if settings.lemonsqueezy_test_mode else "live"


def _retry_after_seconds(response: httpx.Response) -> float:
    """Best-effort backoff from the ``Retry-After`` header (defaults to 1s)."""
    raw = response.headers.get("retry-after")
    if raw is not None:
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            pass
    return 1.0


class LemonSqueezyService:
    """All Lemon Squeezy API interactions for Thought2Build credit purchases.

    Follows the service-singleton pattern: one instance is created at module level
    and imported by name in the billing router and the reconcile worker::

        from services.lemonsqueezy_service import lemonsqueezy_service

    Both public methods accept an optional ``client`` so tests can inject an
    ``httpx.AsyncClient`` backed by a ``MockTransport``; production passes ``None``
    and a configured client is built (and closed) per call.
    """

    # ------------------------------------------------------------------
    # Client / headers
    # ------------------------------------------------------------------

    @staticmethod
    def _headers() -> dict[str, str]:
        """JSON:API headers built per-call (reads the key at call time).

        Building headers lazily keeps the module-level singleton importable when
        billing is disabled (empty ``lemonsqueezy_api_key``) — the key is only
        materialised when an enabled caller actually mints a checkout.
        """
        return {
            "Accept": _JSON_API_MEDIA_TYPE,
            "Content-Type": _JSON_API_MEDIA_TYPE,
            "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
        }

    @asynccontextmanager
    async def _client_ctx(
        self, client: httpx.AsyncClient | None
    ) -> AsyncIterator[httpx.AsyncClient]:
        """Yield the injected client, or build+close a configured one."""
        if client is not None:
            yield client
            return
        async with httpx.AsyncClient(
            base_url=settings.lemonsqueezy_api_base,
            timeout=_TIMEOUT,
            limits=_LIMITS,
            headers=self._headers(),
        ) as owned:
            yield owned

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def create_checkout(
        self,
        attempt: "BillingCheckoutAttempt",
        user: "User",
        *,
        checkout_nonce: str,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[str, str]:
        """Create a hosted checkout for ``attempt`` and return ``(id, url)``.

        ``checkout_nonce`` is the **raw** nonce (the attempt row stores only its
        sha256); it is embedded in the checkout custom data so the signed
        ``order_created`` webhook can prove it back (T-297). The charged amount is
        the attempt's ``price_cents`` snapshot (``custom_price``), the discount UI
        is disabled, and the redirect carries ``?checkout_ref=…`` so the browser
        return can be correlated to the attempt.

        Returns ``(provider_checkout_id, checkout_url)``.

        Raises:
            LemonSqueezyError: a 4xx contract error, or transient failures that
                outlast the bounded retries (caller marks the attempt failed → 502).
        """
        payload = self._build_checkout_payload(attempt, user, checkout_nonce)

        async with self._client_ctx(client) as http:
            for attempt_no in range(_MAX_RETRIES + 1):
                try:
                    response = await http.post(
                        "/v1/checkouts",
                        json=payload,
                        headers=self._headers(),
                    )
                except httpx.RequestError as exc:
                    # Network/timeout — transient. Retry unless exhausted.
                    if attempt_no >= _MAX_RETRIES:
                        logger.error(
                            "billing.lemon_checkout_network_failed "
                            "checkout_ref=%s attempt_id=%s try=%d",
                            attempt.checkout_ref,
                            str(attempt.id),
                            attempt_no,
                        )
                        raise LemonSqueezyError(
                            "Lemon Squeezy checkout creation failed (network)"
                        ) from exc
                    await self._sleep_backoff(attempt_no)
                    continue

                if response.status_code in (200, 201):
                    return self._parse_checkout_response(response, attempt)

                # 4xx (other than 429) is a contract error — never retried.
                if response.status_code not in _RETRYABLE_STATUS:
                    logger.error(
                        "billing.lemon_checkout_rejected "
                        "checkout_ref=%s attempt_id=%s status=%d",
                        attempt.checkout_ref,
                        str(attempt.id),
                        response.status_code,
                    )
                    raise LemonSqueezyError(
                        f"Lemon Squeezy rejected the checkout (HTTP "
                        f"{response.status_code})"
                    )

                # Transient (429/5xx) — retry unless exhausted.
                if attempt_no >= _MAX_RETRIES:
                    logger.error(
                        "billing.lemon_checkout_transient_exhausted "
                        "checkout_ref=%s attempt_id=%s status=%d try=%d",
                        attempt.checkout_ref,
                        str(attempt.id),
                        response.status_code,
                        attempt_no,
                    )
                    raise LemonSqueezyError(
                        f"Lemon Squeezy checkout creation failed after retries "
                        f"(HTTP {response.status_code})"
                    )
                await self._sleep_backoff(attempt_no)

        # Unreachable: the loop either returns or raises on the final attempt.
        raise LemonSqueezyError("Lemon Squeezy checkout creation failed")

    async def get_order(
        self,
        provider_order_id: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> LemonOrder:
        """Re-read one order Thought2Build already has by id (reconcile lane 2, T-301).

        This is a single GET — it is **never** used to discover or prove an order
        (the signed webhook is the grant authority). A 429 is surfaced as
        :class:`LemonSqueezyRateLimitError` (carrying ``Retry-After``) so lane 2
        backs off; any other non-2xx raises :class:`LemonSqueezyError`.
        """
        async with self._client_ctx(client) as http:
            try:
                response = await http.get(
                    f"/v1/orders/{provider_order_id}",
                    headers=self._headers(),
                )
            except httpx.RequestError as exc:
                raise LemonSqueezyError(
                    "Lemon Squeezy order re-read failed (network)"
                ) from exc

        if response.status_code == 429:
            # Surface the rate limit so lane 2 backs off (does NOT retry inline).
            raise LemonSqueezyRateLimitError(_retry_after_seconds(response))

        if response.status_code != 200:
            logger.error(
                "billing.lemon_order_read_failed order_id=%s status=%d",
                provider_order_id,
                response.status_code,
            )
            raise LemonSqueezyError(
                f"Lemon Squeezy order re-read failed (HTTP {response.status_code})"
            )

        return self._parse_order_response(response, provider_order_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_checkout_payload(
        attempt: "BillingCheckoutAttempt",
        user: "User",
        checkout_nonce: str,
    ) -> dict:
        """Assemble the JSON:API ``checkouts`` create body for ``attempt``."""
        variant_id = str(settings.lemonsqueezy_variant_id)
        store_id = str(settings.lemonsqueezy_store_id)
        # ?checkout_ref=… on the success redirect so the browser return correlates.
        redirect_url = (
            f"{settings.lemonsqueezy_success_url}"
            f"?{urlencode({'checkout_ref': attempt.checkout_ref})}"
        )
        return {
            "data": {
                "type": "checkouts",
                "attributes": {
                    # Config-authoritative economics, immune to provider tampering.
                    "custom_price": attempt.price_cents,
                    "test_mode": settings.lemonsqueezy_test_mode,
                    # Attempt TTL — the hosted page expires with the attempt.
                    "expires_at": attempt.expires_at.isoformat(),
                    "product_options": {
                        "enabled_variants": [variant_id],
                        "redirect_url": redirect_url,
                    },
                    "checkout_options": {
                        # No coupon UI — a discount must not change the paid amount.
                        "discount": False,
                    },
                    "checkout_data": {
                        # Pre-fills the hosted form for UX only — never trusted for
                        # user resolution (that is the signed custom data below).
                        "email": user.email,
                        "custom": {
                            # Strings: Lemon stringifies custom data on the webhook
                            # round-trip, so T-297 reads these back as strings.
                            "user_id": str(attempt.user_id),
                            "checkout_ref": attempt.checkout_ref,
                            "checkout_nonce": checkout_nonce,
                            "environment": _environment(),
                            "credits": str(attempt.credits),
                            "price_cents": str(attempt.price_cents),
                            "currency": attempt.currency,
                        },
                    },
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": store_id},
                    },
                    "variant": {
                        "data": {"type": "variants", "id": variant_id},
                    },
                },
            }
        }

    @staticmethod
    def _parse_checkout_response(
        response: httpx.Response,
        attempt: "BillingCheckoutAttempt",
    ) -> tuple[str, str]:
        """Extract ``(provider_checkout_id, checkout_url)`` from a 2xx response."""
        try:
            data = response.json()["data"]
            provider_checkout_id = str(data["id"])
            checkout_url = str(data["attributes"]["url"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.error(
                "billing.lemon_checkout_malformed checkout_ref=%s attempt_id=%s",
                attempt.checkout_ref,
                str(attempt.id),
            )
            raise LemonSqueezyError(
                "Lemon Squeezy returned a malformed checkout response"
            ) from exc
        _assert_allowed_checkout_url(checkout_url)
        return provider_checkout_id, checkout_url

    @staticmethod
    def _parse_order_response(
        response: httpx.Response,
        provider_order_id: str,
    ) -> LemonOrder:
        """Normalise a 2xx order response (status + refund totals)."""
        try:
            attributes = response.json()["data"]["attributes"]
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("billing.lemon_order_malformed order_id=%s", provider_order_id)
            raise LemonSqueezyError(
                "Lemon Squeezy returned a malformed order response"
            ) from exc
        return LemonOrder(
            provider_order_id=provider_order_id,
            status=str(attributes.get("status") or ""),
            refunded=bool(attributes.get("refunded")),
            refunded_amount_cents=int(attributes.get("refunded_amount") or 0),
            total_cents=int(attributes.get("total") or 0),
        )

    @staticmethod
    async def _sleep_backoff(attempt_no: int) -> None:
        """Sleep exponential-backoff-with-full-jitter before the next retry."""
        ceiling = _BACKOFF_BASE_SECONDS * (2**attempt_no)
        delay = random.uniform(0.0, ceiling)  # nosec B311 — jitter, not security
        await asyncio.sleep(delay)


# Module-level singleton — imported by name in the billing router (T-296) and the
# reconcile worker (T-301):
#   from services.lemonsqueezy_service import lemonsqueezy_service
lemonsqueezy_service = LemonSqueezyService()
