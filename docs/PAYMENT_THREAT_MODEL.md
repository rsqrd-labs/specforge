# Payment Threat Model (Issue #35, step 5)

**Scope:** the Lemon Squeezy credit-purchase flow only — checkout, the webhook
grant path, `/status` polling, refund reversal, and the admin-correction support
path. Architecture is **not** re-described here; see `CLAUDE.md` (Phase 22) for the
design and `docs/RUNBOOK.md` §9 / §3 / §2 for the operational procedures. This doc
records, per attack surface: **vector → existing mitigation (file:line) → residual
risk.** Mitigations were verified during the issue-#35 audit (see
`docs/PAYMENT_AUDIT_PLAN.md` §2).

**Trust boundary.** The signed webhook is the *sole* credit-grant authority. The
HTTP path never grants inline — it verifies → sanitises → commits an inbox row →
enqueues; all money mutation happens on the arq worker, idempotently. The only
other grant path is the admin correction, behind an allowlist. Everything below is
framed against those two paths.

---

## 1. Forged webhook (fabricated `order_created` → free credits)

- **Vector:** attacker POSTs a crafted order payload to `POST /billing/webhook` to
  mint credits without paying.
- **Mitigation:** `_verify_lemon_signature` computes HMAC-SHA256 over the **raw
  request bytes read before any parse**, compares with `hmac.compare_digest`
  (constant-time), and **fails closed** — an empty `X-Signature` header or an empty
  secret list returns `False`
  ([billing.py:585–596](../backend/routers/billing.py#L585-L596),
  [billing.py:732–750](../backend/routers/billing.py#L732-L750)). No DB or queue
  mutation occurs before the signature check passes (verify-before-work). The
  `X-Event-Name` header must also match the signed body's `meta.event_name`
  ([billing.py:617–622](../backend/routers/billing.py#L617-L622)).
- **Residual risk:** the webhook secret is a **user-defined HMAC string**, so CI
  TruffleHog `--only-verified` cannot detect it if it leaks (it is not a
  provider-verifiable credential); `.gitignore` is the primary control and rotation
  is RUNBOOK §9.8. Anyone who obtains the secret can forge deliveries — secret
  custody is the whole game. Bounded by the test/live guard (§4) and idempotency
  (§2).

## 2. Replay / double-delivery (same paid order counted twice)

- **Vector:** a legitimately signed delivery is replayed, or Lemon redelivers, to
  grant the same order's credits more than once.
- **Mitigation:** two independent barriers. (a) The inbox has a 4-part **unique**
  identity `(provider, event_name, provider_object_id, payload_hash)`; a
  byte-identical redelivery raises `IntegrityError` inside a savepoint →
  `already_processed`, no second enqueue
  ([billing.py:683–707](../backend/routers/billing.py#L683-L707)). (b) Even if a
  row reaches the worker twice, the grant is idempotent on
  `(provider, provider_order_id)` plus the `billing_purchase:lemonsqueezy:{order}`
  ledger reason, so a concurrent double-flush grants nothing
  (`handle_order_created`,
  [billing_worker.py](../backend/services/billing_worker.py) pack/ledger conflict
  branches; covered by `test_billing_order_created.py`).
- **Residual risk:** low. A *mutated* replay (different payload) yields a different
  `payload_hash` and a new inbox row, but the worker's `(provider, order_id)` grant
  uniqueness still blocks a second grant for the same order.

## 3. Nonce theft / checkout hijack (claim another user's payment)

- **Vector:** steal a `checkout_ref` or the one-time `checkout_nonce` to attach a
  payment to the wrong user, or replay a nonce.
- **Mitigation:** the `checkout_ref` and `checkout_nonce` are **separate**
  high-entropy `secrets.token_urlsafe` values; only `sha256(checkout_nonce)` is ever
  persisted ([billing.py:172–177](../backend/routers/billing.py#L172-L177)). The
  webhook proves the nonce back only via the signed body; the raw nonce is hashed
  and the raw value is **dropped** before the inbox row is built
  ([billing.py:659–672](../backend/routers/billing.py#L659-L672)). `order_created`
  is rejected without a nonce ([billing.py:661–667](../backend/routers/billing.py#L661-L667)).
- **Residual risk:** a `checkout_ref` is returned to the client and stored
  plaintext, but it is only a polling key — `/status` is scoped by `user_id` (§5),
  so a stolen ref reveals nothing cross-user. The nonce only ever travels inside
  Lemon's signed webhook, never to the browser after mint.

## 4. Test/live confusion (test-store event settles against live config)

- **Vector:** a test-mode order is delivered to the production endpoint to grant
  real credits.
- **Mitigation:** the handler rejects any event whose `attributes.test_mode` does
  not match `settings.lemonsqueezy_test_mode`
  ([billing.py:639–645](../backend/routers/billing.py#L639-L645)); production config
  additionally requires `test_mode is False`
  ([config.py:459–484](../backend/config.py#L459-L484)).
- **Residual risk:** none material — the guard is a strict equality check on a
  signed-body field.

## 5. IDOR on `/status` (read another user's purchase state)

- **Vector:** enumerate or guess a `checkout_ref` to learn another user's billing
  state.
- **Mitigation:** a single query scoped by **both** `checkout_ref` AND `user_id`;
  any mismatch returns **404, never 403** (403 would confirm the ref exists for
  another user). 200 is returned only when the attempt is `completed` AND the
  granted pack row exists; unknown / not-yet-granted / expired / failed all return
  the same 404 — no resource-existence leak
  ([billing.py:284–337](../backend/routers/billing.py#L284-L337)).
- **Residual risk:** none material; refs are high-entropy and the response is
  uniform across all not-granted states.

## 6. Double-grant race (concurrent webhook + reconcile, or two workers)

- **Vector:** the webhook path and the reconcile lane, or two worker replicas, race
  to grant the same order.
- **Mitigation:** the grant's database-level uniqueness on `(provider, order_id)`
  (pack) and the unique ledger reason make the second writer's flush raise
  `IntegrityError` → grant nothing, not an error to the user
  ([billing_worker.py](../backend/services/billing_worker.py); concurrency branches
  covered by `test_concurrent_pack_flush_conflict_grants_nothing` /
  `test_concurrent_ledger_reason_conflict_grants_nothing`). The 3-lane reconcile
  **never auto-grants** — lane 2 only *revokes* on a re-read
  ([billing_worker.py:283–609](../backend/services/billing_worker.py#L283-L609)).
- **Residual risk:** none material — correctness rests on DB unique constraints, not
  on application-level locking.

## 7. Refund evasion (spend credits, then refund, keep the value)

- **Vector:** buy credits, spend them, then refund the order to extract value for
  free.
- **Mitigation:** `order_refunded` / fraud routes to `apply_refund_reversal`,
  idempotent on `refund:billing:{pack}:{cents}`; it revokes remaining credits and
  turns over-spent value into **recoverable billing debt** (expired value is never
  debt), and a subsequent purchase repays debt before any usable surplus
  ([billing_worker.py:516–557](../backend/services/billing_worker.py#L516-L557),
  `credit_service.apply_refund_reversal`). Lane 2 reconcile catches a missed refund
  webhook.
- **Residual risk:** debt recovery is **eventual and detective** — a user who
  refunds after spending and never returns leaves unrecovered debt (a business
  write-off, not a security hole; `BillingCreditDebtCreated` is the alert, RUNBOOK
  §9.1). As MoR, Lemon absorbs the chargeback/dispute liability itself.

## 8. Admin-correction abuse (privileged manual grant)

- **Vector:** misuse of `POST /billing/admin/correction` to mint credits.
- **Mitigation:** authorised **only** by the `admin_user_emails` allowlist
  (`require_admin`; the `User` model has no role column, an empty allowlist
  authorises no one), plus auth + CSRF + rate limit
  ([billing.py:105–120](../backend/routers/billing.py#L105-L120)). Idempotent on
  `(provider, provider_order_id)` via a triple barrier (existing-pack/correction
  pre-check + pack and audit unique indexes + ledger-reason index), runs debt
  recovery, and writes an **immutable** `billing_admin_corrections` audit row
  ([billing.py:361–444](../backend/routers/billing.py#L361-L444)).
- **Residual risk:** the audit row is **detective, not preventive** — an
  allowlisted admin *can* grant credits; the control is restricting and recording
  who, not preventing the action. `BillingAdminCorrection` alerts on every use
  (RUNBOOK §9.1) so each grant is visible. Allowlist custody (`ADMIN_USER_EMAILS`)
  is the trust anchor.

---

## Cross-cutting residuals (named honestly)

- **Secret custody is the root trust.** The webhook HMAC secret and the admin
  allowlist are env-sourced with no hardcoded default; their leakage, not a code
  flaw, is the realistic break. Rotation: RUNBOOK §9.8.
- **Reconcile is detective, eventual — not preventive.** The orphaned-commit path
  (checkout created at Lemon but the local `provider_created` commit failed) never
  exposes the URL and is settled later from the signed webhook / lane 2; it is
  correct but not instantaneous ([billing.py:226–253](../backend/routers/billing.py#L226-L253)).
- **No card data anywhere.** Lemon is Merchant of Record; Thought2Build never sees,
  stores, or transmits a PAN — so the entire on-prem cardholder-data attack class is
  out of scope (see `docs/PAYMENT_COMPLIANCE.md`).
