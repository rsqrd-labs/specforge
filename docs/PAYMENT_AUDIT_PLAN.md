# Payment System Audit — Plan of Action (Issue #35)

**Status:** ✅ executed (all 7 steps complete, 2026-06-19). This document maps the
generic enterprise audit checklist in issue #35 to *this* codebase's reality and
defines how each item gets discharged. The executed-audit deliverable is
[docs/PAYMENT_AUDIT_REPORT.md](PAYMENT_AUDIT_REPORT.md) (with
[PAYMENT_THREAT_MODEL.md](PAYMENT_THREAT_MODEL.md) +
[PAYMENT_COMPLIANCE.md](PAYMENT_COMPLIANCE.md)); the §2 rows below are resolved with
evidence and the report's §4 carries the sign-off block awaiting the named approvers.

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
| Inventory | all services/endpoints/components | ✅ | Resolved 2026-06-19 ([PAYMENT_AUDIT_REPORT.md](PAYMENT_AUDIT_REPORT.md) §2 row 1). `rg` sweep ran; core grant surfaces in §1 confirmed. Sweep also surfaced `services/queue.py` (`BILLING_DEAD_LETTER_KEY`), `middleware/rate_limit.py` (webhook exemption), `worker.py` (job registration), `main.py`, `migrations/0018`, frontend `api.ts`/`types/billing.ts` — **wiring/registration, not additional grant paths.** |
| Webhook: signature verify | ✅ | `_verify_lemon_signature` — HMAC-SHA256 over **raw bytes read before parse**, constant-time `compare_digest`, two-secret rotation list, **fail-closed** on empty header/secret (billing.py:587–750) |
| Webhook: replay / idempotency | ✅ | 4-part unique inbox identity `(provider, event_name, object_id, payload_hash)` → `IntegrityError`→`already_processed` (billing.py:683–707); grant idempotent on `(provider, provider_order_id)` + `billing_purchase:lemonsqueezy:{order}` ledger reason |
| Webhook: verify-before-work | ✅ | no DB/queue mutation before signature check; parse only after verify (billing.py:585–600) |
| Webhook: test/live guard | ✅ | rejects test_mode mismatch vs `lemonsqueezy_test_mode` (billing.py:639–645) |
| Webhook: no PII/secret persisted | ✅ | `_build_normalized_payload` is an explicit allow-list; raw nonce → sha256, dropped; no email/URL/signature stored (billing.py:753–809) |
| Checkout: attempt-first integrity | ✅ | local attempt committed **before** provider call; economics snapshot frozen on attempt; orphaned-commit path never exposes URL (billing.py:182–253) |
| `/status`: IDOR safety | ✅ | single query scoped by `checkout_ref` AND `user_id`; 404 (not 403) on any mismatch; 200 only when granted (billing.py:284–337) |
| Idempotency: refund/reversal | ✅ | `apply_refund_reversal` idempotent on `refund:billing:{pack}:{cents}`; over-spend → recoverable debt (worker.py:516–560; credit_service) |
| Reconciliation & monitoring | ✅ | 3-lane `billing_reconcile` (inbox replay / bounded `get_order` re-read / attempt hygiene), **never auto-grants**; 60s pending sweep; pending-age gauge (worker.py:283–609) |
| Dead-letter / retry | ✅ | Verified 2026-06-19. `billing:deadletter` is **separate** from `gh:deadletter` (worker.py:191; key `BILLING_DEAD_LETTER_KEY` in `services/queue.py`); bounded by `JOB_MAX_TRIES` (worker.py:367) with backoff via the `billing_job` wrapper; replay procedure RUNBOOK §9.3. |
| Admin manual grant controls | ✅ | `require_admin` allowlist, CSRF+auth+rate-limit, triple idempotency barrier, immutable audit row (billing.py:105–540) |
| Secrets in vault, not repo | ✅ | Verified 2026-06-19. `.env`/`.envrc` gitignored (.gitignore:152–153); the only tracked env file `backend/.env.example` ships the five secret-bearing keys (`API_KEY`, `WEBHOOK_SECRET`, `_PREV`, `STORE_ID`, `VARIANT_ID`) **empty** — only non-secret config populated (.env.example:89–102). `git log -p --all -S` pickaxe over full history surfaced **zero** real secret values (only doc placeholders `<new_secret>`/`<new>`, runbook rotation text, and the dummy test fixture `"lsq-whsec"`). CI TruffleHog job runs on every push, SHA-pinned v3.95.2, `fetch-depth:0`, base→head diff (ci.yml:13–29). Caveat: TruffleHog `--only-verified` would catch a leaked Lemon **API key** but not the user-defined HMAC **webhook secret** (unverifiable string); the `.gitignore` is the primary control there. |
| Encryption in transit | ✅ | Verified 2026-06-19. `validate_production_settings()` rejects a non-`https://` `lemonsqueezy_success_url` (config.py:466–467) and a non-HTTPS `FRONTEND_URL` (config.py:417). Railway (backend/worker) + Vercel (frontend) terminate TLS at the platform edge (§0.2). Outbound `lemonsqueezy_api_base` defaults to `https://api.lemonsqueezy.com` (config.py:261). |
| Encryption at rest | N/A→✅ | Verified 2026-06-19. No PAN at rest (MoR, §0.1). Webhook inbox carries no secret/PII — `_build_normalized_payload` allow-list, raw nonce → sha256 then dropped (✅ "no PII/secret persisted" row above). DB is the Railway-managed Postgres default-encrypted volume (platform-owned, §0.2). |
| Production config guard | ✅ | Verified 2026-06-19. `validate_production_settings()` (config.py:459–484): when `lemonsqueezy_enabled` AND `environment=="production"`, accumulates errors unless webhook secret set, `success_url` starts `https://`, price/credits/validity all `>0`, currency non-empty, and `test_mode is False`. api key/store id/variant id guaranteed non-empty by the `lemonsqueezy_enabled` gate (config.py:332–346), so a half-configured Lemon fails to-disabled (checkout 503s) rather than silently broken. |
| Observability: metrics/logs/alerts | ✅ | Gap-check done 2026-06-19. Enumerated all 21 payment-flow `BILLING_*` metrics in `observability.py` against RUNBOOK §9.1 and confirmed each is **wired** (`.inc()` in `routers/billing.py` / `billing_worker.py` / `queue.py`, not just defined). 10 failure-mode counters already had alerts (webhook error/pending-age/duplicate, checkout dropped, reversal spike, unprovable-paid, debt created, reconcile mismatch, expiry spike, job deadlettered=Critical). **Two real gaps closed** — added `BillingCheckoutApiError` (Warning; `checkout_api_error_total` provider_error/orphaned_commit had no alert) and `BillingAdminCorrection` (Info/control-visibility; privileged manual grant, aligns with the threat-model admin-abuse surface). Documented the deliberately no-alert metrics (health/business/context counters; `job_retries_total` → dead-letter is the signal, matching the §12 GitHub pattern; critic-regen/brave-research are platform-funded, not payment-flow). |
| Static security code review | ✅ | Code pass done 2026-06-19 over `routers/billing.py`, `services/billing_worker.py`, `services/lemonsqueezy_service.py`, `services/credit_service.py` (+ `config.py` trust anchors): **no high/critical findings**. Only two credit-grant paths exist (HMAC-signed webhook→inbox→`handle_order_created`; `admin_correction` behind `require_admin`); reconcile lane 2 only revokes. Confirmed: fail-closed constant-time HMAC over raw bytes (billing.py:732–750), env-sourced webhook secret + admin allowlist with no hardcoded default (config.py:246–374), economics from attempt snapshot not live config, ownership bound by server-minted nonce hash, parameterized SQLAlchemy throughout (no raw SQL/injection), no secrets/PII logged. Scope caveat: webhook CSRF/rate-limit exemption lives in `middleware/` (verified-elsewhere, not in these 4 files). |
| Integration tests (success/fail/retry/idempotency) | ✅ | Gap-check done 2026-06-19 against migrated Postgres+Redis (CI parity): **184 passed**, branch coverage of the four payment modules `routers/billing.py` 91% · `billing_worker.py` 90% · `credit_service.py` 86% · `lemonsqueezy_service.py` 91%. Confirmed the named branches are already covered — refund→debt (`test_phase25_money_math::test_spend_then_reversal_creates_debt_then_repurchase_recovers_first`), orphaned checkout (`test_billing_router::test_checkout_orphaned_commit_failure_502_no_url`, `…_lemon_failure_marks_attempt_failed_502`), reconcile lanes 1/2/3 (12 tests in `test_billing_reconcile`), admin-correction races (11 tests in `test_billing_admin_correction`). **One real gap closed:** the two *concurrent* double-grant race branches in `handle_order_created` (the sequential duplicate tests only reach the `_find_existing_pack` pre-check) — added `test_concurrent_pack_flush_conflict_grants_nothing` (pack-flush `IntegrityError`, worker.py:1045–1055) and `test_concurrent_ledger_reason_conflict_grants_nothing` (grant `granted is None` ledger-reason rejection, worker.py:1061–1068) in `test_billing_order_created.py`; both verified to drop those line ranges out of the coverage Missing list. Run `TEST_DATABASE_URL=… uv run pytest tests/test_billing*.py tests/test_lemon*.py tests/test_phase25*.py tests/test_credit_service.py -q`. Residual ~10% misses are defensive error/edge paths outside the audit's named branch set. |
| Threat model review | ✅ | Authored 2026-06-19: [docs/PAYMENT_THREAT_MODEL.md](PAYMENT_THREAT_MODEL.md). All 7 surfaces (forged webhook, replay, nonce theft, test/live confusion, IDOR on /status, double-grant race, refund evasion, admin-correction abuse) documented as vector → mitigation (file:line) → **residual risk**. Honest residuals named: HMAC secret is a user-defined string `--only-verified` can't catch (`.gitignore`/rotation is the control); admin-correction audit row is detective-not-preventive; reconcile/orphaned-commit recovery is eventual-not-preventive. |
| Compliance checklist (PCI/GDPR) | ✅ | Authored 2026-06-19: [docs/PAYMENT_COMPLIANCE.md](PAYMENT_COMPLIANCE.md). **PCI SAQ-A** justified (MoR + redirect-only, no PAN; SAQ-A obligations SpecForge still owns tabulated). **GDPR data-flow** stated precisely — direct identifiers (email/name/receipt URL/raw nonce) excluded by the allow-list, but `customer_id` + `user_id`→`User.email` retained as **pseudonymous** personal data (not overclaimed as "PII-free"). **Retention** grounded in code: inbox + terminal attempts purged at 30 days (`purge_billing_events`, `_RETENTION_DAYS`); financial audit tables retained indefinitely behind `RESTRICT` FKs; erasure is the manual RUNBOOK §9.7 procedure. |
| Recovery & rollback playbook | ✅ | Gap-check done 2026-06-19 ([PAYMENT_AUDIT_REPORT.md](PAYMENT_AUDIT_REPORT.md) §3): **no new RUNBOOK section needed** — every payment failure mode already maps to an existing procedure (RUNBOOK §9.2–9.8 + §3 + §2). Symptom→procedure table in the report. The step-6 *action* (adding a section) was correctly skipped because the gap-check found no gap. |
| k8s / load balancer / networking | N/A | no k8s/LB in repo; Railway+Vercel platform-owned (§0.2) |
| Tokenization / PAN handling | N/A | MoR + redirect-only checkout; no card data touches SpecForge (§0.1) |
| Load & chaos / failure-injection testing | N/A (defer) | premature for current stage; worker idempotency + reconcile/dead-letter are the resilience design. Revisit pre-scale; capture as a deferred item, not a release blocker |
| Third-party SLA / vendor contract review | N/A (org) | Lemon Squeezy ToS/MoR coverage is a business/legal artifact, not code; note owner |
| Sign-off criteria | ✅ | Recorded 2026-06-19 ([PAYMENT_AUDIT_REPORT.md](PAYMENT_AUDIT_REPORT.md) §4): all five §4 acceptance criteria shown satisfied with evidence; human approval block (security reviewer + infra/secrets owner + payments owner) presented **awaiting** the named approvers. The report cannot itself sign off — approval is a human act. |

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
