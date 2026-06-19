# Payment System Audit — Plan of Action (Issue #35)

**Status:** plan / scoping. This document maps the generic enterprise audit checklist
in issue #35 to *this* codebase's reality and defines how each item gets discharged.
It is the plan, not the executed audit — execution rows are marked ☐.

## 0. Grounding facts (read these first; they decide what applies)

These three facts collapse a large fraction of the generic checklist:

1. **Lemon Squeezy is the Merchant of Record (MoR).** SpecForge never sees, stores,
   transmits, or tokenizes a PAN. Checkout is a server-minted hosted URL that the
   browser redirects to: [Billing.tsx:282](../frontend/src/pages/Billing.tsx#L282)
   (`window.location.href = response.checkout_url`). No card fields are rendered or
   collected client-side. → **PCI-DSS scope is SAQ-A** (redirect/MoR), not a full
   on-prem cardholder-data audit. Tax, chargebacks, and disputes are Lemon's
   liability per the Phase-22 design.
2. **Deploy target is Railway (backend + arq worker) + Vercel (frontend)**, via
   `.github/workflows/ci.yml` and `backend/Procfile`. There is **no Kubernetes,
   load balancer, service mesh, or Terraform in this repo.** Checklist items about
   k8s/LB/networking are N/A-for-this-repo and owned by the Railway/Vercel platform.
3. **The webhook is the sole credit-grant authority and the durable trust boundary.**
   The HTTP path never grants inline; it verifies → sanitises → commits an inbox row
   → enqueues. All money mutation happens on the arq worker, idempotently.

Existing assets to **reference, not re-author**: `docs/RUNBOOK.md` §9 (billing alerts
& Lemon ops), §3 (credit refund/recovery), §2 (finalise race). The migration design
is documented in `CLAUDE.md` (Phase 22).

## 1. Inventory — services, endpoints, components touching payment data

| Surface | Path |
|---|---|
| HTTP router (checkout/status/history/webhook/admin) | [backend/routers/billing.py](../backend/routers/billing.py) |
| Provider adapter (hosted checkout, `get_order`) | [backend/services/lemonsqueezy_service.py](../backend/services/lemonsqueezy_service.py) |
| Worker (process_webhook, pending sweep, 3-lane reconcile, refund reversal) | [backend/services/billing_worker.py](../backend/services/billing_worker.py) |
| Credit ledger / grant / debt recovery / refund reversal | [backend/services/credit_service.py](../backend/services/credit_service.py) |
| Provider-neutral models | `backend/models/billing_*.py` (checkout_attempt, webhook_event, credit_pack, credit_debt, admin_correction, reconciliation_cursor) |
| Schemas | [backend/schemas/billing.py](../backend/schemas/billing.py) |
| Config + production-settings guard | [backend/config.py](../backend/config.py) (`lemonsqueezy_*`, `validate_production_settings`) |
| Frontend purchase page (redirect-only) | [frontend/src/pages/Billing.tsx](../frontend/src/pages/Billing.tsx) |
| Observability counters | [backend/services/observability.py](../backend/services/observability.py) (`BILLING_*`) |

☐ **Action:** confirm the table is exhaustive with one sweep:
`rg -n "lemonsqueezy|billing_|BillingCredit|provider_order_id" backend frontend/src`.

## 2. Checklist → status mapping

Legend: **✅ Verified** (evidence in code, cite on execution) · **☐ To verify** ·
**⚠ Fix-needed** · **N/A** (with justification).

| # | Checklist item | Status | Evidence / Note |
|---|---|---|---|
| Inventory | all services/endpoints/components | ☐ | §1 above; finalize via `rg` sweep |
| Webhook: signature verify | ✅ | `_verify_lemon_signature` — HMAC-SHA256 over **raw bytes read before parse**, constant-time `compare_digest`, two-secret rotation list, **fail-closed** on empty header/secret (billing.py:587–750) |
| Webhook: replay / idempotency | ✅ | 4-part unique inbox identity `(provider, event_name, object_id, payload_hash)` → `IntegrityError`→`already_processed` (billing.py:683–707); grant idempotent on `(provider, provider_order_id)` + `billing_purchase:lemonsqueezy:{order}` ledger reason |
| Webhook: verify-before-work | ✅ | no DB/queue mutation before signature check; parse only after verify (billing.py:585–600) |
| Webhook: test/live guard | ✅ | rejects test_mode mismatch vs `lemonsqueezy_test_mode` (billing.py:639–645) |
| Webhook: no PII/secret persisted | ✅ | `_build_normalized_payload` is an explicit allow-list; raw nonce → sha256, dropped; no email/URL/signature stored (billing.py:753–809) |
| Checkout: attempt-first integrity | ✅ | local attempt committed **before** provider call; economics snapshot frozen on attempt; orphaned-commit path never exposes URL (billing.py:182–253) |
| `/status`: IDOR safety | ✅ | single query scoped by `checkout_ref` AND `user_id`; 404 (not 403) on any mismatch; 200 only when granted (billing.py:284–337) |
| Idempotency: refund/reversal | ✅ | `apply_refund_reversal` idempotent on `refund:billing:{pack}:{cents}`; over-spend → recoverable debt (worker.py:516–560; credit_service) |
| Reconciliation & monitoring | ✅ | 3-lane `billing_reconcile` (inbox replay / bounded `get_order` re-read / attempt hygiene), **never auto-grants**; 60s pending sweep; pending-age gauge (worker.py:283–609) |
| Dead-letter / retry | ☐ | confirm `billing:deadletter` separation from `gh:deadletter`, bounded retries, and replay runbook (RUNBOOK §9) |
| Admin manual grant controls | ✅ | `require_admin` allowlist, CSRF+auth+rate-limit, triple idempotency barrier, immutable audit row (billing.py:105–540) |
| Secrets in vault, not repo | ☐ | confirm `LEMONSQUEEZY_*` only in Railway secret manager; CI runs TruffleHog; grep repo for leaked keys |
| Encryption in transit | ☐ | confirm HTTPS-only success URL enforced by `validate_production_settings`; Railway/Vercel TLS termination |
| Encryption at rest | N/A→☐ | no PAN at rest (MoR). Confirm only that webhook inbox carries no secret (✅ above) and DB is the managed Postgres default-encrypted volume |
| Production config guard | ☐ | verify `validate_production_settings()` requires webhook secret, HTTPS success URL, positive price/credits/validity, `test_mode=false` (config.py) |
| Observability: metrics/logs/alerts | ☐ | confirm `BILLING_*` counters wired + Grafana alerts in RUNBOOK §9 (webhook error, reconcile mismatch, pending-age, debt-created) |
| Static security code review | ✅ | Code pass done 2026-06-19 over `routers/billing.py`, `services/billing_worker.py`, `services/lemonsqueezy_service.py`, `services/credit_service.py` (+ `config.py` trust anchors): **no high/critical findings**. Only two credit-grant paths exist (HMAC-signed webhook→inbox→`handle_order_created`; `admin_correction` behind `require_admin`); reconcile lane 2 only revokes. Confirmed: fail-closed constant-time HMAC over raw bytes (billing.py:732–750), env-sourced webhook secret + admin allowlist with no hardcoded default (config.py:246–374), economics from attempt snapshot not live config, ownership bound by server-minted nonce hash, parameterized SQLAlchemy throughout (no raw SQL/injection), no secrets/PII logged. Scope caveat: webhook CSRF/rate-limit exemption lives in `middleware/` (verified-elsewhere, not in these 4 files). |
| Integration tests (success/fail/retry/idempotency) | ☐ | 14 billing test files exist; gap-check coverage of: duplicate webhook, refund reversal, debt recovery, orphaned checkout, reconcile lanes. Run `uv run pytest tests/test_billing*.py tests/test_lemon*.py tests/test_phase25*.py -q` |
| Threat model review | ⚠ | **no threat-model doc exists** — author `docs/PAYMENT_THREAT_MODEL.md` (attack surfaces: forged webhook, replay, nonce theft, IDOR on /status, double-grant race, refund evasion, admin-correction abuse) with the existing mitigation for each |
| Compliance checklist (PCI/GDPR) | ⚠ | **no compliance statement exists** — author short `docs/PAYMENT_COMPLIANCE.md`: PCI SAQ-A justification (MoR + redirect), GDPR data-flow (what PII the inbox deliberately excludes), data-retention of audit tables |
| Recovery & rollback playbook | ✅(partial)→☐ | RUNBOOK §9 + §3 already cover dead-letter replay, reconcile, admin-correction, manual refund. Gap-check for an explicit "payment incident" rollback section |
| k8s / load balancer / networking | N/A | no k8s/LB in repo; Railway+Vercel platform-owned (§0.2) |
| Tokenization / PAN handling | N/A | MoR + redirect-only checkout; no card data touches SpecForge (§0.1) |
| Load & chaos / failure-injection testing | N/A (defer) | premature for current stage; worker idempotency + reconcile/dead-letter are the resilience design. Revisit pre-scale; capture as a deferred item, not a release blocker |
| Third-party SLA / vendor contract review | N/A (org) | Lemon Squeezy ToS/MoR coverage is a business/legal artifact, not code; note owner |
| Sign-off criteria | ☐ | define approvers (security review pass + infra/secrets confirmation + payments owner) and required evidence below |

## 3. Execution order (when this plan is approved to run)

1. **Code security pass** — `/security-review` on the four core files. Triage any
   high/critical. *(Gates acceptance criterion.)*
2. **Test coverage gap-check** — run the billing suite; add tests for any uncovered
   branch among {duplicate webhook, refund reversal → debt, orphaned checkout,
   reconcile lane 1/2/3, admin-correction races}.
3. **Config/secrets verification** — read `validate_production_settings()`; confirm no
   `LEMONSQUEEZY_*` value in repo/history; confirm CI TruffleHog covers it.
4. **Observability gap-check** — confirm every `BILLING_*` counter has a documented
   alert in RUNBOOK §9; add any missing alert rows.
5. **Author the two missing docs** — `PAYMENT_THREAT_MODEL.md`,
   `PAYMENT_COMPLIANCE.md` (PCI SAQ-A + GDPR data-flow).
6. **Gap-check rollback playbook** — add a "payment incident" section to RUNBOOK §9 if
   not already implied by dead-letter/reconcile/admin-correction ops.
7. **Produce the audit report** — fill the evidence column with file:line for every ✅,
   resolve every ☐, and record sign-off.

## 4. Sign-off criteria (acceptance)

- `/security-review` shows **no unresolved high/critical** in payment paths.
- Billing test suite green; the idempotency/refund/reconcile branches are covered.
- Threat model + compliance (SAQ-A/GDPR) docs exist and are reviewed.
- Secrets confirmed vault-only; production-config guard verified.
- Observability: every payment failure mode has a metric + documented alert.
- Approvers: security reviewer + infra/secrets owner + payments owner (@Arv-ind-s).

## 5. Explicitly out of scope (and why)

k8s/LB/networking hardening (platform-owned), PAN tokenization/at-rest card encryption
(MoR — no card data), full PCI-DSS Level-1 audit (SAQ-A applies), load/chaos testing
(deferred to pre-scale; not a release blocker), vendor SLA/contract negotiation
(business/legal). Each is recorded here so the audit is honest rather than padded.
