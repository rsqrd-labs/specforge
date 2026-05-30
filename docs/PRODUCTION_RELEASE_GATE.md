# SpecForge Production Release Gate

Use this checklist before promoting a staging build to production. It is a
release decision document, not a setup guide. For setup details, use
`docs/INTEGRATION_API_SETUP_HANDBOOK.md`; for manual smoke coverage, use
`docs/SMOKE_TEST_CHECKLIST.md`.

## Release Inputs

Record these before starting the gate:

| Field | Value |
|---|---|
| Release owner | |
| Date | |
| Git commit | |
| Staging URL | |
| Production URL | |
| Backend image/build | |
| Frontend image/build | |
| Database migration required | Yes / No |
| Langfuse enabled in production | Yes / No |
| Stripe billing enabled in production | Yes / No |
| `ASDD_PROMPT_VERSION` | |
| Prompt eval baseline | |

## Automated Gate

Run from the repository root unless noted.

```bash
cd backend
uv run black --check .
uv run ruff check .
uv run pytest tests -q
uv run pytest \
  ../harness/tests/backend/test_security_audit_contract.py \
  ../harness/tests/backend/test_second_pass_security_contract.py \
  ../harness/tests/backend/test_final_hardening_contract.py \
  ../harness/tests/backend/test_production_readiness_contract.py \
  ../harness/tests/backend/test_langfuse_contract.py \
  ../harness/tests/backend/test_langfuse_live_traffic_contract.py \
  ../harness/tests/backend/test_phase21_stripe_payments_contract.py \
  ../harness/tests/backend/test_phase22_prompt_pipeline_contract.py \
  -q
uv run bandit -r config.py database.py main.py middleware models prompts routers schemas services
uv run pip-audit --strict
```

Prompt quality gate:

```bash
cd harness
uv run python -m prompt_eval.run \
  --version "$(grep -oE 'asdd-v[0-9.]+' ../backend/prompts/base.py)" \
  --baseline asdd-v1.7.1 \
  --report ../prompt_eval_report.md
```

Production smoke against staging:

```bash
SPECFORGE_API_URL=https://api.example.com \
SPECFORGE_ACCESS_TOKEN=<short-lived smoke-user access token> \
SPECFORGE_METRICS_TOKEN=<metrics token> \
SPECFORGE_RUN_LLM_SMOKE=1 \
python3 scripts/production_smoke.py
```

Pass criteria:

- Formatting and lint pass.
- Unit tests pass.
- Security and production-readiness harness contracts pass.
- Stripe billing and prompt pipeline harness contracts pass.
- Prompt eval report shows no unapproved per-grader regression against the
  selected baseline.
- Bandit reports no unresolved issues.
- `pip-audit --strict` reports no known vulnerabilities.
- Production smoke passes against staging with live LLM smoke enabled.

## Environment Gate

Production must satisfy these backend requirements:

| Variable | Requirement |
|---|---|
| `ENVIRONMENT` | `production` |
| `FRONTEND_URL` | HTTPS URL |
| `JWT_PRIVATE_KEY` | Real PEM private key |
| `JWT_PUBLIC_KEY` | Matching PEM public key |
| `ENCRYPTION_MASTER_KEY` | Real Fernet key, not the CI placeholder |
| `CSRF_SECRET` | Long random secret |
| `METRICS_TOKEN` | Set |
| `DATABASE_URL` | Production database URL |
| `REDIS_URL` | Production Redis URL |
| Provider API keys | Set only for enabled providers |
| `GITHUB_CLIENT_ID` | Blank to disable GitHub export; set both vars together |
| `GITHUB_CLIENT_SECRET` | Required when `GITHUB_CLIENT_ID` is set |

Stripe billing requirements:

| Variable | Requirement |
|---|---|
| `STRIPE_SECRET_KEY` | Blank to disable billing; `sk_live_*` required when billing is enabled in production |
| `STRIPE_WEBHOOK_SECRET` | Required when billing is enabled |
| `STRIPE_PRICE_CENTS` | Positive integer package price in cents |
| `STRIPE_CREDITS_PER_PURCHASE` | Positive integer credit grant per pack |
| `STRIPE_CREDIT_VALIDITY_DAYS` | Positive integer expiry window |
| `STRIPE_SUCCESS_URL` | HTTPS frontend billing URL, normally `{FRONTEND_URL}/billing` |
| `STRIPE_CANCEL_URL` | HTTPS frontend billing URL, normally `{FRONTEND_URL}/billing` |

Langfuse production requirements:

| Variable | Requirement |
|---|---|
| `LANGFUSE_SECRET_KEY` | Blank to disable; non-empty to enable |
| `LANGFUSE_PUBLIC_KEY` | Required when `LANGFUSE_SECRET_KEY` is set |
| `LANGFUSE_HOST` | HTTPS URL (cloud or approved self-hosted endpoint) |
| `LANGFUSE_PROMPT_CACHE_TTL` | Positive TTL, default `300` |
| `LANGFUSE_CONTENT_CAPTURE_ACK` | Required as `true` when Langfuse is enabled in production |

Pass criteria:

- Application startup validation succeeds in the production-like environment.
- If billing is enabled, Stripe webhooks are configured for the staging backend
  and a test checkout has completed end to end.
- Langfuse is either intentionally disabled or explicitly approved for
  prompt/output telemetry export.
- No development secrets, CI placeholders, or local URLs are present in
  production variables.
- No `sk_test_*` Stripe key is present in production. The backend rejects this
  at startup, but the gate should catch it before deploy.

## Manual Smoke Gate

Complete the staging smoke checklist in `docs/SMOKE_TEST_CHECKLIST.md`.

Minimum release-blocking coverage:

- Google OAuth sign-in works.
- New user receives starting credits.
- Workspace creation works.
- SPEC generation streams tokens and decrements credits.
- Eval badge appears after generation.
- Refine preview works and refunds on reject.
- Stage finalise unlocks downstream stages.
- Full SPEC to TASKS path can complete.
- Export zip downloads and contains expected files.
- Billing package, checkout redirect, status polling, and history work when
  Stripe billing is enabled.
- `/health` and `/metrics` are reachable as expected.
- Prompt pipeline output includes required Phase 19 sections and the eval suite
  report has been reviewed.
- Frontend loads without console errors.

Pass criteria:

- No critical smoke item fails.
- Any non-critical note has an owner and explicit acceptance.

## Observability Gate

Metrics:

- `/metrics` requires the intended token or trusted-source access.
- Staging scrape target is healthy.
- Production scrape target is ready before deploy.
- Billing counters are present: `specforge_billing_checkout_created_total`,
  `specforge_billing_checkout_completed_total`,
  `specforge_billing_webhook_error_total`, and duplicate/rate-limit counters.
- Prompt quality counters are present: `pipeline_validator_failures_total`,
  `pipeline_upstream_section_skipped_total`, and
  `specforge_billing_credits_critic_regen_total`.

Sentry:

- Backend DSN is correct or intentionally blank.
- Frontend DSN is correct or intentionally blank.
- Test events in staging reach the intended project when enabled.

Langfuse:

- Disabled mode has been verified when `LANGFUSE_SECRET_KEY` is blank.
- Enabled mode has been verified in staging before enabling in production.
- Langfuse outages do not break generation, refine, eval, credits, or prompt
  fallback.
- Prompt/output capture has privacy and retention approval before production
  enablement.

Pass criteria:

- Observability is sufficient to detect and investigate production regressions.
- Optional integrations can fail without breaking user-facing flows.

## Security Gate

Confirm:

- No secrets are committed to source.
- `.env` files are not staged or deployed as artifacts.
- Dependency audit has no unresolved vulnerabilities.
- Security harness contracts pass.
- Metrics endpoint is not publicly exposed without protection.
- CORS and frontend URLs match production domains.
- Prompt-injection defenses and output validation remain enabled.
- Prompt changes are versioned through `ASDD_PROMPT_VERSION` and gated by
  `harness/prompt_eval`.
- Stripe webhook HMAC validation, idempotency, livemode guard, CSRF exemption,
  and checkout rate limit are enabled.
- Langfuse payloads go through the shared redaction path.
- Langfuse production enablement has explicit content-capture acknowledgement.

Pass criteria:

- No high or critical security issue is open.
- Medium issues, if any, have explicit release-owner acceptance and a follow-up
  issue.

## Database And Rollback Gate

Before deploy:

- Confirm whether a database migration is required.
- Confirm migration has run against staging.
- Confirm backup/restore procedure is available.
- Confirm rollback target commit/build is known.

Rollback triggers:

- Authentication is unavailable.
- Workspace creation or stage generation is broadly unavailable.
- Credit deductions occur without successful generation and refund paths fail.
- Stripe checkout completes but credits are not granted, or webhook errors
  affect multiple users.
- Prompt validator failures or critic-regeneration credit spikes appear after
  deploy and cannot be mitigated by reverting the prompt/version.
- Production startup validation fails.
- Security controls are disabled or bypassed.
- Langfuse failure propagates into user-facing failures.

Rollback notes:

- If Langfuse causes operational concern but user flows remain healthy, first
  disable it by clearing `LANGFUSE_SECRET_KEY` and redeploying/restarting.
- If a provider outage is isolated to one LLM provider, disable that provider or
  route users to a healthy provider before rolling back application code.

## Final Decision

| Gate | Result | Notes |
|---|---|---|
| Automated tests | Pass / Fail | |
| Production smoke | Pass / Fail | |
| Environment validation | Pass / Fail | |
| Observability | Pass / Fail | |
| Security | Pass / Fail | |
| Database/rollback | Pass / Fail | |

Release decision:

- Go
- No-go
- Go with accepted risk

Approver: ___________________________

Date/time: ___________________________
