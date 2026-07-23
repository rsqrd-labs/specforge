# Issue #44 — Payment Feature Flag + Razorpay Integration Plan

Status: **IMPLEMENTED (code + docs)** — all 7 steps landed on `main` (2026-07-05).
Live rollout (§10 — KYC, dashboard auto-capture, live smoke) is a pre-launch ops
gate outside code; see the AC mapping in §14.
Issue: [#44 — Add feature flag for payment gateway and integrate Razorpay alongside Lemonsqueezy](../../../issues/44)
Prior art: Phase 22 Lemon Squeezy migration (`docs/RUNBOOK.md` §9, migration `0018`, T-291…T-308)

---

## 0. Context & constraints

- The product is **not live yet** — there are no real customers, packs, or in-flight
  checkouts to migrate. We can change defaults freely; no grace windows needed.
- The Razorpay account is an **individual (unregistered business)** account:
  - INR only; domestic UPI / cards / netbanking / wallets. **International cards are
    disabled by default** (separate Razorpay approval required).
  - Razorpay is **not a Merchant of Record** (Lemon Squeezy is). GST/tax invoicing and
    chargeback liability sit with the account holder. This is a launch/ops concern,
    not a code concern — flagged in §11.
- Issue constraint: **exactly one gateway is active at a time** (Razorpay *or* Lemon),
  switchable by configuration, plus a master flag that turns payments off entirely.
- The Phase-22 data model is already provider-neutral (`billing_*` tables key
  everything by `(provider, provider_order_id)`), so **no new tables** are needed —
  only CHECK-constraint widening and a reconcile-cursor seed row.

## 1. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Two env flags: `PAYMENTS_ENABLED` (bool, default **false**) + `PAYMENT_PROVIDER` (`lemonsqueezy` \| `razorpay`) | Matches the codebase's env-flag convention (`core_cheap_primary`, `critic_async_advisory`). Settings are read at request time, so flipping = env change + restart, no code change. A DB-backed runtime flag is out of scope (§12). |
| D2 | Razorpay via **hosted Payment Links** (`POST /v1/payment_links`), *not* the embedded checkout.js modal | Exact parity with the Lemon flow: server mints a hosted URL → frontend `window.location.href` redirect → provider-hosted page → browser returns to `/billing?checkout_ref=…` → signed webhook grants. Zero frontend SDK, zero CSP changes, the attempt-first + poll flow is untouched. |
| D3 | Webhook endpoints are **always registered and always process**, independent of the active-provider flag | Refunds/disputes for old Lemon orders must still settle after switching to Razorpay (and vice versa). The flag gates **checkout creation and package display only**. A provider with no secrets configured fails closed (400) on its webhook path. |
| D4 | Grant authority = **`payment_link.paid`**; reversal = **`refund.processed`** | `payment_link.paid`'s payload carries `payload.payment_link.entity` (with our `notes` — incl. the checkout nonce — and `reference_id`) **and** `payload.payment.entity` (the `pay_…` id used as `provider_order_id`). This avoids depending on notes propagation into `payment.captured`. Verified against Razorpay docs 2026-07-02. |
| D5 | **No Razorpay SDK** — a thin `httpx` wrapper mirroring `services/lemonsqueezy_service.py` | Same reason Lemon has no SDK: the official Razorpay python SDK is sync (would block the event loop), and we need exactly two calls. |
| D6 | Light provider dispatch in the router (a `_checkout_service_for(provider)` selector), **not** a big plugin framework | Two providers, two call sites (`create_checkout`, reconcile lane 2). A registry/Protocol abstraction would be premature. |
| D7 | `provider_order_id` for Razorpay = the **payment id** (`pay_…`); `provider_checkout_id` = the **payment link id** (`plink_…`) | The payment is the money object (refunds reference it via `refund.entity.payment_id`); the link is the checkout object. Mirrors Lemon's order/checkout split exactly. |
| D8 | Amounts stay in the existing `price_cents` columns, interpreted as **minor units** (paise for INR) | Razorpay amounts are integer paise; no schema change. E.g. ₹799 = `79900`. |
| D9 | Razorpay `reference_id` = `str(attempt.id)` (UUID, 36 chars), **not** `checkout_ref` | Razorpay caps `reference_id` at **40 chars**; `checkout_ref` is 43 (`token_urlsafe(32)`). Correlation uses `notes.checkout_ref` (256-char limit) as the authority anyway, same as Lemon `custom_data`. |
| D10 | Grant validation anchors on the **payment entity** (the money object), not just the link | The link's `amount` is a value we set ourselves at creation — checking it alone is near-circular. The grant requires `payment.entity.amount`/`currency` to match the attempt snapshot, `payment.entity.status == "captured"`, and `payment_link.status == "paid"` (the `status_not_paid` analogue). |
| D11 | Reconcile claims **all** configured providers' cursor rows upfront (ordered by provider, `FOR UPDATE NOWAIT`) as the single-active-run lock | Today the mutex is the NOWAIT lock on the single Lemon cursor row, and the provider-neutral lanes 1/3 run under it. Per-provider locking would let two overlapping ticks split the providers and double-run lanes 1/3. Any lock-miss ⇒ the whole tick skips cleanly, exactly like today. |

## 2. Phase 1 — Config & feature flag (`backend/config.py`, `.env.example`)

New settings (all following the Lemon block's shape, `config.py:556`):

```
payments_enabled: bool = False          # master kill switch (issue AC #1)
payment_provider: str = "lemonsqueezy"  # "lemonsqueezy" | "razorpay"

razorpay_key_id: str = ""               # rzp_test_… / rzp_live_…
razorpay_key_secret: str = ""
razorpay_webhook_secret: str = ""
razorpay_webhook_secret_prev: str = ""  # two-secret rotation window, like Lemon
razorpay_price_cents: int = 79900       # paise — ₹799 (pick final price at rollout)
razorpay_currency: str = "INR"
razorpay_credits_per_purchase: int = 200
razorpay_credit_validity_days: int = 30
razorpay_success_url: str = ""          # e.g. https://app.thought2build.com/billing
razorpay_checkout_ttl_minutes: int = 30 # payment-link expire_by; Razorpay minimum ~15m
razorpay_api_base: str = "https://api.razorpay.com"
razorpay_reconcile_max_calls_per_run: int = 200
```

Derived properties (next to `lemonsqueezy_enabled`, `config.py:700`):

- `razorpay_enabled` — `key_id` and `key_secret` both set.
- `razorpay_webhook_secrets` — `(secret, secret_prev)` tuple, mirroring
  `lemonsqueezy_webhook_secrets`.
- `billing_checkout_enabled` — **the** gate for `POST /billing/checkout` and the
  `enabled` field on `GET /billing/package`:
  `payments_enabled and (lemonsqueezy_enabled if payment_provider == "lemonsqueezy" else razorpay_enabled)`.

`validate_production_settings()` additions (after the Lemon guard, `config.py:833`):

- `payment_provider` must be one of `{"lemonsqueezy", "razorpay"}` (fail startup otherwise —
  a typo must not silently disable billing).
- When `payments_enabled` is true, the **active** provider must be fully configured
  (its `*_enabled` property true), else startup fails.
- When `razorpay_enabled` (configured at all, active or not):
  - `RAZORPAY_WEBHOOK_SECRET` non-empty (webhooks are the sole grant authority).
  - `RAZORPAY_SUCCESS_URL` must be HTTPS.
  - positive `price_cents` / `credits_per_purchase` / `credit_validity_days`; non-empty currency.
  - `razorpay_key_id.startswith("rzp_live_")` — the live/test analogue of
    `LEMONSQUEEZY_TEST_MODE must be False` (Razorpay has no test flag on events;
    the key prefix is the environment).
  - `razorpay_checkout_ttl_minutes >= 16` (Razorpay rejects `expire_by` under ~15 min).

Behavioral note: introducing `payments_enabled=false` as the default means checkout is
off everywhere until explicitly enabled — correct for a product that is not live.
Existing Lemon tests that exercise checkout set `payments_enabled=True` in fixtures.

`.env.example`: add the `RAZORPAY_*` block + `PAYMENTS_ENABLED` / `PAYMENT_PROVIDER`
with comments mirroring the Lemon block (`.env.example:203`).

## 3. Phase 2 — Migration `0034_razorpay_provider.py`

(`0032`/`0033` are already taken — `0032_eval_results_created_at_index`,
`0033_workspace_trash` — so this lands as `0034`.)

Additive only:

1. Widen the provider CHECKs on all five billing tables to
   `('lemonsqueezy','stripe','razorpay')`:
   `ck_bca_provider`, `ck_bcp_provider`, `ck_bcd_provider`, `ck_bwe_provider`, and
   `ck_bac_provider` (admin corrections) — drop + re-add constraint; instant on
   Postgres.
2. Seed the reconcile cursor:
   `INSERT INTO billing_reconciliation_cursors(provider) VALUES ('razorpay') ON CONFLICT DO NOTHING`
   (the table's `ck_brc_provider` CHECK currently allows only `'lemonsqueezy'` —
   widen it too).
3. Update the five ORM models' `CheckConstraint` strings to match (defence-in-depth,
   same pattern the models already document).

Downgrade: restore the narrow CHECKs only if no `razorpay` rows exist (raise otherwise),
delete the cursor row. Existing partial-unique indexes
(`uq_billing_credit_packs_provider_order` etc.) already key by provider — no change.

## 4. Phase 3 — `backend/services/razorpay_service.py`

A structural mirror of `lemonsqueezy_service.py` (same timeouts, bounded retries with
full jitter, no logging of keys/URLs/nonce, pure — no DB session):

- `RazorpayError`, `RazorpayRateLimitError(retry_after)` — same semantics as the Lemon pair.
- `create_payment_link(attempt, user, *, checkout_nonce, client=None) -> (provider_checkout_id, checkout_url)`
  - `POST {api_base}/v1/payment_links`, **HTTP Basic auth** (`key_id`, `key_secret`).
  - Body:
    - `amount`: `attempt.price_cents` (paise — the attempt snapshot, immune to config changes)
    - `currency`: `attempt.currency` (`INR`)
    - `accept_partial`: `false` (grant validation compares the full amount)
    - `reference_id`: `str(attempt.id)` (D9 — 40-char cap)
    - `description`: `"Thought2Build — {credits} credits"`
    - `customer`: `{"email": user.email}` (prefill only — never trusted for user resolution)
    - `notify`: `{"sms": false, "email": false}`, `reminder_enable: false`
    - `expire_by`: `int(attempt.expires_at.timestamp())`
    - `callback_url`: `{razorpay_success_url}?checkout_ref={attempt.checkout_ref}`,
      `callback_method: "get"` — Razorpay appends its own `razorpay_*` params with `&`;
      the frontend already reads only `checkout_ref` (browser return is telemetry-only,
      the webhook is the authority — same contract as Lemon).
    - `notes` — the same seven allow-listed keys as Lemon `custom_data`, all strings:
      `user_id`, `checkout_ref`, `checkout_nonce` (raw — proven back hashed by the
      webhook, never persisted raw), `environment` (`"test"`/`"live"` from the key
      prefix), `credits`, `price_cents`, `currency`. Notes limits (15 pairs × 256
      chars) comfortably fit.
  - Response → `(id /* plink_… */, short_url)`.
  - Retry policy identical to Lemon: 2 retries on 429/5xx/network, 4xx = contract error.
- `get_payment(payment_id, client=None) -> RazorpayPayment` — reconcile lane-2 re-read
  (`GET /v1/payments/{id}`), normalising
  `{payment_id, status, amount_cents, amount_refunded_cents, refund_status}`.
  429 → `RazorpayRateLimitError` surfaced to the lane (never retried inline).
- Module-level singleton `razorpay_service`.

## 5. Phase 4 — Router (`backend/routers/billing.py`) + middleware

**`GET /billing/package`** — becomes flag- and provider-aware:

- `PackageResponse` gains `enabled: bool` and `provider: str`
  (`schemas/billing.py:25`). Economics come from the **active** provider's settings.
  When `billing_checkout_enabled` is false, still return the configured numbers but
  `enabled=false` — the frontend gates the Buy button on it (today there is no signal
  and a disabled server 503s on click).

**`POST /billing/checkout`** — provider dispatch:

- Gate on `settings.billing_checkout_enabled` (replaces the bare
  `lemonsqueezy_enabled` check at `billing.py:166`) → 503 unchanged.
- Snapshot the **active provider's** economics into the attempt
  (`provider=settings.payment_provider`, TTL from that provider's
  `*_checkout_ttl_minutes`).
- Dispatch: `_checkout_service_for(provider)` → `lemonsqueezy_service.create_checkout`
  or `razorpay_service.create_payment_link`. Everything else (attempt-first commits,
  orphan handling, 502 mapping, metrics with `provider=` label) is shared and stays
  byte-identical in structure.

**`GET /billing/status`** — fix the hardcoded provider: the pack lookup at
`billing.py:323` uses `provider="lemonsqueezy"`; change to `attempt.provider`.
(Latent bug for any second provider; harmless today.)

**New: `POST /billing/webhook/razorpay`** — separate route, same five-step
verify-before-work shape as `lemon_webhook` (`billing.py:543`):

1. Raw body before any parse.
2. Constant-time HMAC-SHA256 of the raw bytes against `razorpay_webhook_secrets`
   (current + prev), header **`X-Razorpay-Signature`** (hex). Fail closed on empty
   header/secrets.
3. Parse; dispatch on top-level `event`:
   - `payment_link.paid` → actionable (grant).
   - `refund.processed` → actionable (reversal).
   - everything else (incl. `payment.captured`, `payment.failed`,
     `payment_link.expired`) → acknowledge `{"status": "ignored"}` — no inbox row.
4. Build the allow-listed `normalized_payload` (no PII — `contact`/`email` on the
   payment entity are **dropped**; no raw nonce — sha256 only; no signature):
   - From `payload.payment_link.entity`: `payment_link_id`, `reference_id`, `amount`,
     `currency`, `status`, and the seven `notes` keys (nonce hashed → 
     `checkout_nonce_hash_from_webhook`).
   - From `payload.payment.entity`: `payment_id`, `amount`, `status`, `method`,
     `amount_refunded`.
   - For refunds, from `payload.refund.entity`: `refund_id`, `payment_id`, `amount`;
     plus the payment entity's cumulative `amount_refunded` **and the payment
     entity's `notes` block** (same seven allow-listed keys, nonce hashed,
     best-effort — absent notes never reject a signed refund). Without this the
     refund path loses its ownership proof: `_refund_without_pack`'s park-and-retry
     branches (a)/(b) need `checkout_ref` + nonce hash + `user_id` to hold an
     out-of-order refund for the 24h horizon, and the environment guard below has
     no data source on refunds — an early-arriving refund would otherwise degrade
     to a permanent "could not link" no-op, recovered only whenever lane 2 happens
     to re-read that pack.
   - Environment guard: `notes.environment` must match the server's
     (`"live"` iff `razorpay_key_id` starts with `rzp_live_`) — the analogue of
     Lemon's `test_mode` check. Source: the **link** entity's notes on
     `payment_link.paid` (hard requirement), the **payment** entity's notes on
     `refund.processed` (best-effort — enforced when present, never a rejection
     ground for a signed refund). `payment_link.paid` without a nonce in notes → 400
     (grant authority requires proof); a signed refund is never rejected for a
     missing nonce (same asymmetry as Lemon, `billing.py:661`).
5. Inbox row: `provider="razorpay"`, `provider_object_type="payments"`,
   `provider_object_id=payment_id`, same 4-part unique identity → duplicate = 200
   `already_processed`. Also carry the **`x-razorpay-event-id`** header value inside
   `normalized_payload` (belt-and-braces dedup evidence for ops) — but compute
   `payload_hash` **before** injecting it, so the hash input excludes the event id:
   automatic retries keep the id stable, but a manual dashboard resend can mint a
   new one, and that must not defeat the inbox unique index (the pack/ledger
   barriers would still hold, but inbox dedup should not depend on them). Enqueue
   the same `billing_process_webhook` job (`billing_wh:{row.id}`) — **no new
   queue/job names**, so the fast-lane routing, 60s pending sweep, dead-letter, and
   purge all apply unchanged.

**Middleware**: add `/billing/webhook/razorpay` to the CSRF exemptions
(`middleware/csrf.py:29`) and `_WEBHOOK_PATHS` (`middleware/rate_limit.py:33`).

**Admin correction** (`billing.py:361`): widen
`AdminCorrectionRequest.provider` `Literal` to include `"razorpay"`
(`schemas/billing.py:101`), and take `expires_at` from a provider-aware
`credit_validity_days_for(provider)` helper instead of the hardcoded
`lemonsqueezy_credit_validity_days` (`billing.py:426`).

## 6. Phase 5 — Worker (`backend/services/billing_worker.py`)

**Dispatch**: the handler registry keys on `event_name` today. Register the new
events — `payment_link.paid` → `handle_razorpay_link_paid`,
`refund.processed` → `handle_razorpay_refund`. (Event-name collision across
providers is impossible between Lemon's `order_*` and Razorpay's dotted names, but
make the registry key `(provider, event_name)` while touching it — cheap insurance.)
Both events also join the fail-loud money-event set `_ORDER_EVENTS`
(`billing_worker.py:99`) — or its `(provider, event_name)` analogue — so a money
event with no registered handler dead-letters loudly via `_dispatch_claimed`
instead of being acked as a harmless no-op.

**`handle_razorpay_link_paid`** — mirrors `handle_order_created` (`billing_worker.py:927`):

- Rejection checks (the `_order_created_rejection` analogue):
  - `notes.checkout_ref` resolves an attempt; `sha256` nonce match against
    `attempt.checkout_nonce_hash`; `notes.user_id` matches the attempt's user.
  - **Payment-entity anchor (D10)**: `payment.entity.amount == attempt.price_cents`,
    `payment.entity.currency` matches, and `payment.entity.status == "captured"` —
    the payment is the money object. The link is checked too
    (`payment_link.amount == attempt.price_cents`, full payment — `accept_partial`
    is off), but the link's amount is a value we set ourselves at creation, so it
    is corroboration, not the authority.
  - `payment_link.status == "paid"` — the `status_not_paid` analogue.
  - environment matches server config.
- Idempotency (triple barrier, unchanged pattern): pack unique on
  `(provider='razorpay', provider_order_id=pay_…)`, ledger reason
  `billing_purchase:razorpay:{payment_id}`, inbox identity.
- Pack money fields: `paid_item_amount_cents = provider_order_total_cents =
  payment.entity.amount`. The INR price is tax-inclusive — there is no Lemon-style
  tax-on-top, so item and order total coincide. These are the inputs
  `apply_refund_reversal` normalises through (`credit_service.py:389`), so they are
  populated explicitly, not left to inference from the Lemon mirror.
- Grant via the existing `credit_service.grant_credits_with_debt_recovery`; stamp the
  attempt `completed` + `provider_order_id` atomically (same transaction shape as
  T-299). Metrics: the existing provider-labelled counters with `provider="razorpay"`.
- Unrecoverable (no matching attempt / nonce mismatch on a signed event) →
  `BILLING_UNRECOVERABLE_CHECKOUT{provider="razorpay"}` + processed-with-note, exactly
  like Lemon's path — the admin-correction endpoint is the settlement of last resort.
  The "provider says paid" predicate gating that counter is
  `payment_link.status == "paid"` (the analogue of Lemon's `status == "paid"`
  condition), so a benign not-paid rejection never trips the alert.

**`handle_razorpay_refund`** — mirrors `handle_order_refunded` (`billing_worker.py:1119`):

- Look up the pack by `(provider='razorpay', provider_order_id=refund.payment_id)`.
- Feed the payment entity's **cumulative** `amount_refunded` into the existing
  proportional reversal (`apply_refund_reversal`, idempotent on
  `refund:billing:{pack}:{cents}`) — same cumulative semantics as Lemon's
  `refunded_amount`, so partial + full refunds settle correctly and re-deliveries
  are no-ops. (Its kwarg is currently named `lemon_refunded_amount_cents`; rename
  to the provider-neutral `provider_refunded_amount_cents` while touching it.)
- **Razorpay reversal decision** (`_reversal_decision` at `billing_worker.py:351`
  is Lemon-status-specific; write the explicit analogue):
  `full_or_fraud = (payment.refund_status == "full") or (amount_refunded >=
  payment.amount)`; `reason_label` is always `"refund"` — Razorpay payments carry
  **no** fraud/chargeback status (disputes are separate entities, §11). Lane 2's
  `_order_has_reversal` analogue: `amount_refunded > 0 or refund_status in
  ("partial", "full")`.
- Missing pack → the existing `_refund_without_pack` bookkeeping path; its
  park-and-retry proof branches (a)/(b) work for Razorpay because the refund's
  normalized payload carries the payment entity's notes (§5 step 4).

**Reconcile (`billing_reconcile`)** — make lane 2 per-provider:

- **Run lock (D11)**: today the single-active-run mutex is the `FOR UPDATE NOWAIT`
  on the one cursor row, held for the whole run (`billing_worker.py:389`) — and the
  provider-neutral lanes 1/3 run under it. With two cursor rows, claim **all**
  configured providers' rows upfront in one session, ordered by provider ASC,
  `NOWAIT`; any lock-not-available ⇒ the whole tick skips cleanly (same semantics
  as today — never a per-provider split across two concurrent ticks). All locks are
  held to the final commit/rollback; on failure `_persist_reconcile_error`
  (`billing_worker.py:616`) stamps `last_error` on every claimed row.
- Loop over the **configured** providers (not just the active one — D3): for each,
  page its live packs from its cursor row, re-read via
  `lemonsqueezy_service.get_order` / `razorpay_service.get_payment`, and apply that
  provider's reversal decision (the Lemon and Razorpay helpers above). Each
  provider gets its own `*_reconcile_max_calls_per_run` budget and its own 429
  back-off. `_RECONCILE_PROVIDER` (`billing_worker.py:138`) dies; lane-2 metric
  labels come from the cursor row's provider.
- Lane 1 (inbox replay) and lane 3 (attempt hygiene) are already provider-neutral —
  lane 1's labels come from the inbox row's provider; lane 3's
  `BILLING_CHECKOUT_EXPIRED` label comes from each **attempt row's** provider (an
  expired-attempt batch can contain both providers).
- `_find_existing_pack`'s `provider="lemonsqueezy"` default (`billing_worker.py:892`)
  becomes a required argument.

**No `worker.py` changes**: `billing_process_webhook` (fast lane), the 60s sweep, the
15-min reconcile, and the daily purge already cover both providers by construction.

## 7. Phase 6 — Frontend

Deliberately minimal (D2 — no SDK, no CSP change, no new payment UI):

- `types/billing.ts`: `BillingPackage` gains `enabled: boolean` and `provider: string`.
- `pages/Billing.tsx`:
  - Gate the **Buy Credits** button on `billingPackage.enabled`; when false render a
    quiet "Credit purchases aren't available yet" state instead (today the button
    always shows and a disabled backend 503s).
  - **Design spec for the disabled state**: keep the `billing-package-card` intact
    (credits/price/validity still render) and replace only the button with a quiet
    slate note in the established idiom — a semantic `billing-*` class in
    `index.css`, styled like `.billing-debt-note`. The billing page is built from
    semantic `billing-*` classes plus the Modern Indica ambient bands
    (saffron/lotus/slate), not inline Tailwind utilities — do not improvise a raw
    `disabled` button or ad-hoc utility classes.
  - `formatPrice` (`Billing.tsx:47`): the `Intl.NumberFormat` path already renders
    `INR` correctly (₹); fix the fallback branch that hardcodes `$` to use the
    currency code instead.
- **Out-of-credits CTA surfaces** (untouched, but an explicit decision): six places
  deep-link to `/billing` as the "buy more credits" recovery path —
  `CreditConfirmModal.tsx:98`, `CreateStoryboardModal.tsx:216`,
  `CreditMeter.tsx:79`/`:108`, `Workspace.tsx:1176` (insufficient-credits alert),
  `Dashboard.tsx:471`. With `PAYMENTS_ENABLED=false` (the shipping default) they
  all land on the disabled state. Decision: leave them unchanged pre-launch — the
  Billing page is the single surface that explains availability — but the
  disabled-state copy must read coherently for a user arriving from an
  out-of-credits alert (hence "Credit purchases aren't available yet", not just
  "Purchases…"). Revisit (hide/soften those CTAs) only if payments remain off
  after launch.
- **Kill switch mid-flight**: a user returning with `?checkout_ref=` after
  `PAYMENTS_ENABLED` flips false still gets their credits — `PaymentStatusPanel`
  polls regardless of `enabled`, and the webhook still grants (D3). No code
  change; pinned by a test (§8).
- Everything else (redirect via `checkout_url`, `?checkout_ref=` return — the
  frontend reads only `checkout_ref` and ignores the appended `razorpay_*`
  callback params, status polling) is provider-agnostic already.

## 8. Phase 7 — Tests

Backend (mirror the Lemon suites file-for-file):

- `test_razorpay_service.py` — httpx `MockTransport`: payment-link create success /
  4xx contract error / 429+5xx bounded retries / malformed response; `get_payment`
  normalisation + 429 → `RazorpayRateLimitError`; Basic-auth header; nonce/keys never
  in logs (caplog assertion, same as Lemon's).
- `test_billing_router_razorpay.py` — webhook: signature verify (current + prev
  secret, reject empty/missing/forged), event filtering (`payment.captured` ignored,
  `payment_link.paid`/`refund.processed` stored), nonce-required-on-paid /
  nonce-optional-on-refund asymmetry, environment mismatch → 400, PII stripped from
  `normalized_payload`, refund payload carries the payment entity's notes (hashed
  nonce, never raw), `payload_hash` excludes the event id (a dashboard resend with
  a new `x-razorpay-event-id` still dedups), inbox dedup → 200, enqueue failure
  still 200.
- `test_billing_router.py` additions — **feature-flag matrix**:
  `payments_enabled=false` → checkout 503 + `package.enabled=false`;
  `provider=razorpay` → dispatch to `razorpay_service` + attempt row snapshots
  razorpay economics; `provider=lemonsqueezy` unchanged; **Lemon webhook still
  processes while Razorpay is active** (D3); status endpoint uses `attempt.provider`.
- `test_billing_worker_razorpay.py` — grant happy path; nonce/user/environment
  rejection paths; **payment-entity anchor rejections** (payment amount/currency
  mismatch, payment not `captured`, link not `paid` — and only a `paid` link
  status trips `BILLING_UNRECOVERABLE_CHECKOUT`); pack money fields
  (`paid_item_amount_cents` = `provider_order_total_cents` = payment amount);
  duplicate delivery = single grant (all three barriers); refund proportional
  reversal (`refund_status="full"` and cumulative-partial paths) + idempotent
  redelivery; refund-without-pack all three branches (park-and-retry with valid
  notes proof, 24h give-up, no-proof audited no-op); dead-letter on repeated
  failure.
- `test_billing_reconcile.py` additions — razorpay lane 2 with its own cursor +
  budget; both-provider interleave; 429 back-off; **all-rows run lock** (an
  overlapping tick skips when any configured cursor row is held;
  `_persist_reconcile_error` stamps every claimed row); lane-3 expiry metric
  labelled by each attempt's provider.
- `test_billing_migration_0034.py` — CHECKs widened, cursor row seeded, idempotent
  re-run, downgrade guard.
- Config tests — `validate_production_settings` matrix (active-but-unconfigured
  provider fails startup; `rzp_test_` key in prod fails; TTL < 16 fails).

Frontend: `Billing.test.tsx` — `enabled=false` hides Buy, keeps the package card,
and renders the quiet slate note (coherent when arriving from an out-of-credits
alert); a return with `?checkout_ref=` while `enabled=false` still polls to
completion (kill-switch mid-flight); INR renders as ₹ via the Intl path and the
non-Intl fallback no longer hardcodes `$`.

## 9. Phase 8 — Docs

- `docs/RUNBOOK.md` §9: Razorpay webhook-secret rotation (two-secret window —
  dashboard webhooks are per-mode, test and live configured separately), key
  rotation, dead-letter replay (same `billing:deadletter`), reconcile ops,
  provider-switch procedure (flip `PAYMENT_PROVIDER`, restart; old-provider webhooks
  keep settling — D3), admin-correction with `provider=razorpay`.
- `.env.example` (§2), `CLAUDE.md` billing paragraph (flag semantics + Razorpay),
  close out issue #44 acceptance criteria.

## 10. Rollout checklist (ops — mostly dashboard work)

Phase 0 (account, before any code ships to prod):

1. Complete Razorpay KYC for the individual account so **live mode** activates
   (test keys work immediately; live keys only post-KYC).
2. Dashboard → Settings → Payment capture: **auto-capture ON** (a payment stuck in
   `authorized` never fires `payment_link.paid`).
3. Create webhooks in **both test and live modes**: URL
   `https://<api-host>/billing/webhook/razorpay`, events `payment_link.paid` +
   `refund.processed` (optionally `payment.failed` / `payment_link.expired` for
   observability — they're acknowledged-ignored), a strong generated secret per mode.
4. Decide the INR price point (`RAZORPAY_PRICE_CENTS` is paise).

Then:

5. Deploy with `PAYMENTS_ENABLED=false` — the Razorpay webhook route goes live and
   nothing else changes *for a product that is not yet selling*. The new default is
   not free in general: it turns checkout off even where Lemon is configured today.
   If Lemon must stay purchasable through the transition, set
   `PAYMENTS_ENABLED=true` + `PAYMENT_PROVIDER=lemonsqueezy` in the same deploy.
6. Staging/test-mode E2E: `PAYMENT_PROVIDER=razorpay` + `rzp_test_` keys →
   checkout → pay with test UPI/card → webhook → poll shows `completed` → history
   row; dashboard refund → revocation/debt; kill the fast worker mid-flow → 60s
   sweep recovers the grant (the existing `BillingWebhookPendingAge` alert covers
   the regression case).
7. Live smoke: one real minimal-price purchase + refund against `rzp_live_` keys.
8. Flip `PAYMENTS_ENABLED=true` in prod.

## 11. Risks & individual-account notes

- **Merchant-of-record shift**: Lemon absorbed tax/disputes; with Razorpay the
  individual is the merchant. GST registration/invoicing obligations (₹20L services
  threshold, export-of-services rules if any foreign buyers) need a CA's sign-off
  before live enablement. Code ships either way; the flag means Lemon remains one
  restart away.
- **International cards off by default** on individual accounts + single-active-
  gateway constraint ⇒ while Razorpay is active, foreign-card buyers cannot pay.
  Accepted for launch; revisit if/when non-Indian demand appears.
- **Disputes/chargebacks**: no automated dispute handling in v1 — and this is
  **weaker than the Lemon posture**, not the same: Lemon surfaces a chargeback as
  `fraudulent` on `order_refunded` and on lane-2 re-reads, but a Razorpay dispute
  loss does not necessarily flip the payment's `refund_status`, so **reconcile
  lane 2 cannot detect a chargeback at all** — credits stay granted until manual
  action, and on an individual account the money liability is ours. Mitigation:
  subscribe `payment.dispute.*` in the dashboard so deliveries at least hit the
  acknowledged-ignored path's `billing.webhook_ignored_event` log line (zero code,
  log-level visibility); dispute losses settle via dashboard + admin correction.
  Automated dispute reversal stays out of scope (§12).
- **Environment guard is weaker than Lemon's**: Razorpay events carry no `test_mode`
  flag; we rely on the round-tripped `notes.environment` + the `rzp_live_` key-prefix
  startup guard + per-mode webhook secrets. Three layers, but worth stating.
- **Settlement**: INR T+2/T+3 to the linked bank account; refunds take days to hit
  the customer — support expectations, not code.

## 12. Non-goals

- Running both gateways simultaneously / geo-routing by currency (issue explicitly
  says one at a time).
- Embedded checkout.js modal UX.
- Subscriptions/recurring (credit packs only, as today).
- DB-backed runtime feature flag (env + restart matches every other flag here).
- Stripe revival (T-308 decommission stands; audit tables untouched).

## 13. Suggested implementation order & sizing

| Step | Scope | Size |
|------|-------|------|
| 1 | Config + flags + prod validation + `.env.example` | S |
| 2 | Migration 0034 + model CHECK strings | S |
| 3 | `razorpay_service.py` + tests | M |
| 4 | Router: package/checkout dispatch, status fix, razorpay webhook, middleware exemptions, schemas | M |
| 5 | Worker: two handlers + per-provider reconcile + tests | M/L |
| 6 | Frontend gating + currency fallback + tests | S |
| 7 | Docs + RUNBOOK §9 | S |

Steps 1–2 land first (inert), 3–5 are the core PR, 6–7 close the issue. Everything is
additive and default-off, so each step is independently shippable to `main`.

## 14. Acceptance-criteria mapping (issue #44)

All 7 steps are implemented and on `main` (2026-07-05). Mapping the issue's AC to
what shipped:

| # | Acceptance criterion | Status | Where |
|---|----------------------|--------|-------|
| 1 | Feature flag toggles the payment system | ✅ Met | `PAYMENTS_ENABLED` master kill switch + `billing_checkout_enabled` gate (Step 1, `config.py`); frontend gates the Buy button on `package.enabled` (Step 6) |
| 2 | Razorpay integrated as a payment provider | ✅ Met (code) | `razorpay_service.py` (Step 3), router dispatch + `POST /billing/webhook/razorpay` (Step 4), worker handlers + per-provider reconcile (Step 5), migration `0034` (Step 2) |
| 3 | Both gateways functional and configurable | ⚙️ Code complete; **live-functional gated on §10 ops** | Configurable now (env flags); "functional" against real money needs KYC + dashboard auto-capture + live smoke (§10 Phase 0/6–8) — cannot be done pre-launch |
| 4 | Switch between gateways | ✅ Met | `PAYMENT_PROVIDER` (one active at a time), restart; old-provider webhooks keep settling (D3). Runbook: `docs/RUNBOOK.md` §9.9 provider-switch procedure |
| 5 | Tests for the new integration | ✅ Met | `test_razorpay_config.py`, `test_billing_migration_0034.py`, `test_razorpay_service.py`, `test_billing_router_razorpay.py` + router flag-matrix, `test_billing_worker_razorpay.py` + reconcile cases, `Billing.test.tsx` |
| 6 | Documentation updated with Razorpay setup | ✅ Met | This plan, `.env.example` `RAZORPAY_*` block (Step 1), `docs/RUNBOOK.md` §9/§9.9, `CLAUDE.md` billing paragraph (Step 7) |

**5 of 6 criteria are met by code + docs.** #3 is code-complete and configurable;
its live-functional half is the §10 rollout (KYC/dashboard/live smoke), which is
ops work that cannot land before the product goes live. The GitHub issue is left
open deliberately until that rollout closes it — see §10 and §11 (individual-account
tax/dispute caveats requiring CA sign-off before live enablement).
