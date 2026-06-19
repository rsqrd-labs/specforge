# Payment System Audit — Report (Issue #35)

**Status:** executed audit. This is the deliverable of step 7 in
[docs/PAYMENT_AUDIT_PLAN.md](PAYMENT_AUDIT_PLAN.md) §3 — the plan defined *how*
each checklist item is discharged; this report records *that* it was, with
file:line evidence, and presents the sign-off block. It **references** the
companion artifacts rather than restating them:
[docs/PAYMENT_THREAT_MODEL.md](PAYMENT_THREAT_MODEL.md),
[docs/PAYMENT_COMPLIANCE.md](PAYMENT_COMPLIANCE.md), and `docs/RUNBOOK.md` §9 /
§3 / §2 for operations.

Audit window: 2026-06-05 → 2026-06-19. Codebase at `main` (docs-only commits
since the last test run; see §3 note). Auditor: Claude (Opus 4.8), pair-driven
by the payments owner.

---

## 1. Scope and grounding (unchanged from plan §0)

Three facts bound the audit:

1. **Lemon Squeezy is the Merchant of Record.** No PAN is ever seen, stored,
   tokenized, or transmitted by SpecForge; checkout is a server-minted hosted URL
   the browser redirects to → **PCI-DSS scope is SAQ-A**.
2. **Deploy is Railway (backend + arq worker) + Vercel (frontend).** No
   k8s/LB/mesh/Terraform in repo — those rows are N/A-for-this-repo, platform-owned.
3. **The signed webhook is the sole credit-grant authority.** The HTTP path never
   grants inline (verify → sanitise → inbox → enqueue); all money mutation is on
   the arq worker, idempotently. The only other grant path is the allowlisted
   admin correction; reconcile lane 2 only *revokes*.

---

## 2. Findings by checklist item

Every row from plan §2 with its resolved verdict and evidence. **No unresolved
high/critical findings.** Two real gaps were found and **fixed during the audit**
(observability alerts; concurrent-race tests) — recorded below as found→fixed.

| # | Item | Verdict | Evidence (file:line / artifact) |
|---|---|---|---|
| 1 | Inventory exhaustive | ✅ | Core grant-logic surfaces confirmed (plan §1 table). The `rg` sweep additionally surfaced `services/queue.py` (`BILLING_DEAD_LETTER_KEY`), `middleware/rate_limit.py` (webhook CSRF/rate-limit exemption), `worker.py` (job registration), `main.py` (router wiring), `migrations/0018`, and frontend `api.ts`/`types/billing.ts` — **wiring/registration, not additional grant paths**. No undocumented surface mutates credits. |
| 2 | Webhook signature verify | ✅ | HMAC-SHA256 over raw bytes read before parse, constant-time `compare_digest`, two-secret rotation list, fail-closed on empty header/secret ([billing.py:585–596](../backend/routers/billing.py#L585-L596), [billing.py:732–750](../backend/routers/billing.py#L732-L750)). Threat model §1. |
| 3 | Replay / idempotency | ✅ | 4-part unique inbox identity → `IntegrityError`→`already_processed` ([billing.py:683–707](../backend/routers/billing.py#L683-L707)); grant idempotent on `(provider, provider_order_id)` + `billing_purchase:lemonsqueezy:{order}` ledger reason. Threat model §2. |
| 4 | Verify-before-work | ✅ | No DB/queue mutation precedes the signature check ([billing.py:585–600](../backend/routers/billing.py#L585-L600)). |
| 5 | Test/live guard | ✅ | Rejects `test_mode` mismatch vs `lemonsqueezy_test_mode` ([billing.py:639–645](../backend/routers/billing.py#L639-L645)); prod config requires `test_mode is False` ([config.py:459–484](../backend/config.py#L459-L484)). Threat model §4. |
| 6 | No PII/secret persisted | ✅ | `_build_normalized_payload` allow-list; raw nonce → sha256, dropped; no email/URL/signature stored ([billing.py:753–809](../backend/routers/billing.py#L753-L809)). Compliance §2.1. |
| 7 | Checkout attempt-first integrity | ✅ | Local attempt committed before provider call; economics snapshot frozen; orphaned-commit path never exposes URL ([billing.py:182–253](../backend/routers/billing.py#L182-L253)). |
| 8 | `/status` IDOR safety | ✅ | Query scoped by `checkout_ref` AND `user_id`; 404 (not 403) on mismatch; 200 only when granted ([billing.py:284–337](../backend/routers/billing.py#L284-L337)). Threat model §5. |
| 9 | Refund / reversal idempotency | ✅ | `apply_refund_reversal` idempotent on `refund:billing:{pack}:{cents}`; over-spend → recoverable debt ([billing_worker.py:516–557](../backend/services/billing_worker.py#L516-L557)). Threat model §7. |
| 10 | Reconciliation & monitoring | ✅ | 3-lane `billing_reconcile` (inbox replay / bounded `get_order` re-read / attempt hygiene), **never auto-grants**; 60s pending sweep; pending-age gauge ([billing_worker.py:283–609](../backend/services/billing_worker.py#L283-L609)). RUNBOOK §9.4. |
| 11 | Dead-letter / retry | ✅ | `billing:deadletter` is **separate** from `gh:deadletter` ([worker.py:191](../backend/worker.py#L191)), key `BILLING_DEAD_LETTER_KEY` in `services/queue.py`; bounded by `JOB_MAX_TRIES` ([worker.py:367](../backend/worker.py#L367)) with backoff via the `billing_job` wrapper; replay procedure RUNBOOK §9.3. |
| 12 | Admin manual grant controls | ✅ | `require_admin` allowlist (empty ⇒ no one), CSRF+auth+rate-limit, triple idempotency barrier, immutable audit row ([billing.py:105–120](../backend/routers/billing.py#L105-L120), [billing.py:361–444](../backend/routers/billing.py#L361-L444)). Threat model §8; RUNBOOK §9.5. |
| 13 | Secrets in vault, not repo | ✅ | `.env`/`.envrc` gitignored; `.env.example` ships secret-bearing keys empty; `git log -p -S` pickaxe over full history found **zero** real secret values; CI TruffleHog SHA-pinned, base→head, every push. Caveat: `--only-verified` cannot detect the user-defined HMAC webhook secret — `.gitignore` + rotation (RUNBOOK §9.8) is the control. |
| 14 | Encryption in transit | ✅ | `validate_production_settings()` rejects non-HTTPS success/frontend URLs ([config.py:417](../backend/config.py#L417), [config.py:466–467](../backend/config.py#L466-L467)); Railway/Vercel terminate TLS; outbound API base is `https://` ([config.py:261](../backend/config.py#L261)). |
| 15 | Encryption at rest | N/A→✅ | No PAN at rest (MoR); inbox carries no secret/PII (row 6); Railway-managed default-encrypted Postgres volume. |
| 16 | Production config guard | ✅ | `validate_production_settings()` ([config.py:459–484](../backend/config.py#L459-L484)) fails startup unless webhook secret set, HTTPS success URL, positive price/credits/validity, currency set, `test_mode False`; half-config fails to-disabled (checkout 503s). |
| 17 | Observability: metrics/logs/alerts | ✅ (gap fixed) | All 21 `BILLING_*` metrics confirmed **wired** (`.inc()`, not just defined) against RUNBOOK §9.1. **Two gaps closed during audit:** added `BillingCheckoutApiError` (Warning) and `BillingAdminCorrection` (Info/control-visibility). No-alert metrics documented (health/business/context; retries→dead-letter is the signal). |
| 18 | Static security code review | ✅ | Pass over `routers/billing.py`, `services/billing_worker.py`, `services/lemonsqueezy_service.py`, `services/credit_service.py` (+ `config.py`): **no high/critical**. Two grant paths only; fail-closed constant-time HMAC over raw bytes; env-sourced secrets, no hardcoded default; parameterized SQLAlchemy (no injection); no secrets/PII logged. Re-confirmed by the issue-#35 `/security-review` on the audit-docs branch (docs-only diff → no code findings). |
| 19 | Integration tests | ✅ (gap fixed) | At step 2: **184 passed**; branch coverage `billing.py` 91% · `billing_worker.py` 90% · `credit_service.py` 86% · `lemonsqueezy_service.py` 91%. Named branches covered (refund→debt, orphaned checkout, reconcile lanes 1/2/3, admin races). **One gap closed:** the two *concurrent* double-grant race branches — `test_concurrent_pack_flush_conflict_grants_nothing` / `test_concurrent_ledger_reason_conflict_grants_nothing`. |
| 20 | Threat model review | ✅ | [docs/PAYMENT_THREAT_MODEL.md](PAYMENT_THREAT_MODEL.md) — 8 surfaces as vector → mitigation (file:line) → **residual risk**, honest residuals named. |
| 21 | Compliance (PCI/GDPR) | ✅ | [docs/PAYMENT_COMPLIANCE.md](PAYMENT_COMPLIANCE.md) — PCI SAQ-A justified; GDPR data-flow precise (pseudonymous data, not "PII-free"); retention grounded in `purge_billing_events` 30-day cron + indefinite RESTRICT-guarded audit tables. |
| 22 | Recovery & rollback playbook | ✅ | **Gap-check (resolves the step-6 ☐): no new RUNBOOK section needed** — every payment failure mode already has a documented recovery procedure. Symptom→procedure map in §3 below. |
| 23 | k8s / LB / networking | N/A | Platform-owned (Railway + Vercel); none in repo. |
| 24 | Tokenization / PAN handling | N/A | MoR + redirect-only; no card data touches SpecForge. |
| 25 | Load & chaos testing | N/A (deferred) | Premature pre-scale; worker idempotency + reconcile/dead-letter is the resilience design. Revisit pre-scale — **not a release blocker.** |
| 26 | Third-party SLA / vendor review | N/A (org) | Lemon ToS/MoR coverage is a business/legal artifact, not code. Owner: payments owner. |

---

## 3. Recovery & rollback playbook — gap-check (resolves step 6 ☐)

Step 6 asked whether RUNBOOK §9 needs a dedicated "payment incident" rollback
section. **Conclusion: no — the playbook already exists, distributed across §9.2–9.8,
§3, and §2.** Each payment failure mode maps to an existing procedure:

| Symptom / incident | Recovery procedure |
|---|---|
| Webhook delivery failing / errors | RUNBOOK §9.1 (`BillingWebhookErrorRate`), §9.2 |
| Inbox not draining (pending-age rising) | RUNBOOK §9.4 (60s sweep), §9.6 (scale-out) |
| Billing job stuck in `billing:deadletter` | RUNBOOK §9.3 (find root cause → reconcile/replay) |
| Paid order never granted (unprovable) | RUNBOOK §9.4 (reconcile lane 1) → §9.5 (admin correction) |
| Missed refund / fraud reversal | RUNBOOK §9.4 (reconcile lane 2), §3 (manual refund) |
| Double-charged / double-grant | RUNBOOK §2 (double-finalise rollback) — backed by DB-level grant idempotency |
| User account deletion / GDPR erasure | RUNBOOK §9.7 (settle debt → retain RESTRICT-guarded audit) |
| Secret/key compromise | RUNBOOK §9.8 (two-secret rotation window) |

This is a **resolve-and-cite** conclusion, not a RUNBOOK edit: the step-6 *action*
(adding a section) was correctly skipped because the gap-check found no gap. Were a
gap found, it would have been flagged for the owner rather than silently filled.

> **Note on test/coverage figures.** The 184-passed run and coverage percentages
> in row 19 were measured at step 2. They are anchored here, not re-asserted as
> freshly re-run — every commit since has been docs-only, so no payment code
> changed.

---

## 4. Sign-off

Step 7 records that **every acceptance criterion in plan §4 is satisfied**; the
human approval block below is **pending** the named owners (this report cannot
itself sign off — approval is a human accountability act).

| Acceptance criterion (plan §4) | Met? | Evidence |
|---|---|---|
| `/security-review` — no unresolved high/critical in payment paths | ✅ | §2 row 18 |
| Billing suite green; idempotency/refund/reconcile branches covered | ✅ | §2 row 19 |
| Threat model + compliance (SAQ-A/GDPR) docs exist and reviewed | ✅ | §2 rows 20–21 |
| Secrets vault-only; production-config guard verified | ✅ | §2 rows 13, 16 |
| Every payment failure mode has a metric + documented alert | ✅ | §2 row 17 |

**Approval block — awaiting named approvers (plan §4):**

- [ ] Security reviewer — confirms §2 rows 18, 20 and no unresolved high/critical.
- [ ] Infra / secrets owner — confirms §2 rows 13, 14, 16 (vault-only secrets, TLS, prod guard).
- [ ] Payments owner (@Arv-ind-s) — confirms the GDPR lawful basis & retention
      periods in the compliance doc match current finance/legal policy, and
      authorizes release.

Audit is **complete and ready for sign-off**; no remaining ☐ in the plan's
execution order.
