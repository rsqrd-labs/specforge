# Payment Compliance Statement (Issue #35, step 5)

**Scope:** PCI-DSS and GDPR posture of the Lemon Squeezy credit-purchase flow.
This is a factual statement of *what the code does*, not a legal opinion. It
references the architecture in `CLAUDE.md` (Phase 22) and the operational
procedures in `docs/RUNBOOK.md` §9 rather than restating them. The security
controls behind each claim are enumerated in `docs/PAYMENT_THREAT_MODEL.md`.

---

## 1. PCI-DSS — SAQ-A

**Determination: SAQ-A applies.** Thought2Build qualifies for the shortest
self-assessment questionnaire because it fully outsources cardholder-data handling.

- **Lemon Squeezy is the Merchant of Record (MoR).** It owns the card flow, tax,
  chargebacks, and disputes (Phase-22 design).
- **Redirect-only checkout.** The browser is sent to a Lemon-hosted checkout URL;
  **no card fields are rendered or collected by Thought2Build**
  ([Billing.tsx:282](../frontend/src/pages/Billing.tsx#L282),
  `window.location.href = response.checkout_url`). The server mints the hosted URL
  and never proxies card input
  ([billing.py:139–253](../backend/routers/billing.py#L139-L253)).
- **No PAN at rest or in transit.** Thought2Build never sees, stores, tokenizes, or
  transmits a primary account number. The webhook inbox is an explicit allow-list
  that carries order economics and IDs only — no card data
  ([billing.py:753–809](../backend/routers/billing.py#L753-L809)).

**SAQ-A obligations Thought2Build still owns** (the redirect integration's surface):

| Obligation | How met |
|---|---|
| Serve the redirect/checkout page over TLS | Railway (backend) + Vercel (frontend) terminate TLS at the platform edge; `validate_production_settings()` rejects a non-`https://` success URL / frontend URL ([config.py:417](../backend/config.py#L417), [config.py:466–467](../backend/config.py#L466-L467)) |
| Don't store cardholder data | Allow-list inbox payload; no card fields anywhere ([billing.py:753–809](../backend/routers/billing.py#L753-L809)) |
| Protect the integration's integrity | Webhook HMAC verify-before-work, fail-closed ([billing.py:585–596](../backend/routers/billing.py#L585-L596), [billing.py:732–750](../backend/routers/billing.py#L732-L750)); see threat model §1 |
| Manage credentials | Secrets env-sourced, no hardcoded defaults, rotation runbook (RUNBOOK §9.8); not in repo/history (audit plan §2) |

**Out of scope (and why):** PAN tokenization, at-rest card encryption, full PCI-DSS
Level-1 audit — all N/A under MoR + redirect (audit plan §5).

---

## 2. GDPR — data flow

Thought2Build processes payment-related **personal data**, so this is stated precisely
rather than claiming a "PII-free" system.

### 2.1 What the webhook inbox deliberately **excludes**

`_build_normalized_payload` is an allow-list, so provider PII is structurally
dropped, never persisted ([billing.py:753–809](../backend/routers/billing.py#L753-L809)):

- Customer **email** (`user_email`) and **name** (`user_name`) — not copied.
- Receipt / hosted **URLs** (`urls.receipt`) — not copied.
- The webhook **signature** and any provider **API key** — never in the payload.
- The raw **checkout nonce** — replaced by its `sha256` and the raw value dropped
  ([billing.py:659–672](../backend/routers/billing.py#L659-L672)).
- Any unrecognised `custom_data` field — only the seven Thought2Build-set keys survive.

### 2.2 What it **does** retain (named honestly)

The inbox and pack rows are **not** anonymous. They retain:

- **Provider-side pseudonymous identifiers** — `customer_id`, `store_id`, order/item
  IDs ([billing.py:779–781](../backend/routers/billing.py#L779-L781)).
- **Linkage to the Thought2Build user** — `custom.user_id`
  ([billing.py:801](../backend/routers/billing.py#L801)), and the credit pack's
  `user_id` resolves to `User.email`.

Under GDPR these are **pseudonymous personal data**, retained for the lawful basis
of **contract performance and financial reconciliation** (granting paid credits,
honouring refunds, settling debt). The direct identifiers in §2.1 are excluded
because reconciliation does not need them.

### 2.3 Data retention

| Data | Retention | Mechanism |
|---|---|---|
| Webhook inbox (`billing_webhook_events`, `processed`) | **30 days** | daily `purge_billing_events` cron ([billing_worker.py:738–798](../backend/services/billing_worker.py#L738-L798), `_RETENTION_DAYS=30`) |
| Terminal checkout attempts (`expired`/`failed`/`completed`) | **30 days** | same purge cron |
| Financial audit tables (`billing_credit_packs`, `billing_credit_debts`, `billing_admin_corrections`, `billing_reconciliation_cursors`) | **Retained indefinitely** as the financial audit trail | `ON DELETE RESTRICT` FKs prevent silent orphaning (RUNBOOK §9.7) |
| Retained Stripe audit tables (`stripe_credit_packs`, `stripe_webhook_events`) | **Retained indefinitely**, read-only history | T-308 decommission kept them as audit history (`CLAUDE.md` Phase 22) |

### 2.4 Right to erasure

V1 exposes **no** self-service user-deletion endpoint; erasure is a **manual ops
procedure** (RUNBOOK §9.7). Because the financial audit tables use `ON DELETE
RESTRICT`, an erasure first settles billing state (no open debt), then the operator
**retains the audit rows** (a legitimate-interest / legal-obligation basis for
financial records) and **anonymises the user PII elsewhere** as the erasure request
requires — the audit trail is never `CASCADE`-deleted to force the removal.

---

## 3. Summary

- **PCI-DSS:** SAQ-A — MoR + redirect-only, no PAN touches Thought2Build.
- **GDPR:** direct identifiers excluded by allow-list; provider-side pseudonymous
  IDs + user linkage retained for reconciliation; inbox/attempts purged at 30 days;
  financial audit retained indefinitely with a manual, RESTRICT-guarded erasure
  procedure.
- **Owner sign-off:** payments owner (per audit plan §4) confirms the lawful basis
  and retention periods above match current finance/legal policy.
