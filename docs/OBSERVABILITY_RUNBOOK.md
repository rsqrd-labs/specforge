# Thought2Build Observability Runbook

Use this runbook when validating, operating, or troubleshooting Thought2Build
observability. It covers the observability paths used by the application:
Prometheus metrics, Sentry, Langfuse, Lemon Squeezy billing counters, and prompt
pipeline quality counters.

## Scope

| System | Purpose | Default behavior |
|---|---|---|
| Prometheus metrics | Health, request, auth, rate-limit, credit, and LLM operation metrics from `/metrics` | Enabled; protected by token or localhost-only access |
| Sentry | Backend and frontend exception reporting | Disabled when DSNs are blank |
| Langfuse | Optional LLM traces, prompt lookup, eval score links, and dataset collection | Disabled when `LANGFUSE_SECRET_KEY` is blank |
| Lemon Squeezy billing counters | Provider-labelled checkout, webhook, credit grant/revoke, debt, reconcile, admin-correction, pending-age, and rate-limit signals (Phase 22) | Enabled when the billing router is loaded; checkout can still be disabled with blank Lemon keys |
| Prompt quality counters | Validator failures, skipped upstream sections, and critic-regeneration credit usage | Enabled with the pipeline; used by Phase 19 release gates |
| GitHub integration metrics | Webhook, reconcile-lag, export/PR/check, token-mint, job-retry/dead-letter, and queue-depth signals from the App + worker (Phase 21) | Enabled when the GitHub App is configured; the worker runs `configure_logging()` + Sentry on startup |

Detailed setup steps live in `docs/INTEGRATION_API_SETUP_HANDBOOK.md`. This
runbook is for operations and incident response.

## Configuration Reference

Backend observability variables:

```env
METRICS_TOKEN=
SENTRY_DSN=
GRAFANA_OTLP_ENDPOINT=
GRAFANA_OTLP_TOKEN=

LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PROMPT_CACHE_TTL=300
LANGFUSE_CONTENT_CAPTURE_ACK=false
```

Frontend observability variables:

```env
VITE_SENTRY_DSN=
```

Production startup validation is enforced in `backend/config.py`:

- `METRICS_TOKEN` must be set.
- `FRONTEND_URL` must use HTTPS.
- `JWT_PRIVATE_KEY` must be a real PEM key.
- `ENCRYPTION_MASTER_KEY` must not be the CI placeholder.
- If `LANGFUSE_SECRET_KEY` is set, `LANGFUSE_PUBLIC_KEY` must also be set.
- If Langfuse is enabled in production, `LANGFUSE_HOST` must use HTTPS.
- If Langfuse is enabled in production,
  `LANGFUSE_CONTENT_CAPTURE_ACK=true` is required.
- If Lemon billing is enabled in production, `LEMONSQUEEZY_TEST_MODE` must be
  `false`, `LEMONSQUEEZY_SUCCESS_URL` must be HTTPS, and
  `LEMONSQUEEZY_WEBHOOK_SECRET` must be set. Leave the three core Lemon keys
  blank to intentionally disable checkout.

## Normal Validation

Run these checks before relying on observability during a release.

### Metrics

1. Call `GET /health`.
2. Call `GET /metrics` from an allowed source.
3. Confirm the response is Prometheus text, not JSON.
4. Confirm unauthenticated remote access is rejected when `METRICS_TOKEN` is
   configured.

Expected result: health is `200`, metrics are available only to trusted callers,
and dashboard scrape targets are healthy.

Important metric families:

- `thought2build_billing_*` for Lemon Squeezy checkout, webhook, credit
  grant/revoke, debt created/recovered, reconcile mismatch, admin correction,
  expiry, consumption, the `webhook_pending_age_seconds` gauge, and checkout
  rate-limit signals. Most are labelled `{provider}` (`lemonsqueezy` is the only
  runtime emitter; `provider="stripe"` series persist only as historical audit
  data after the T-308 decommission).
- `thought2build_storyboard_*` for Storyboard generation, public views, downloads,
  missing source sections, credit deduction, and refund behavior. Watch
  `thought2build_storyboard_generation_failed_total` for failure spikes and alert
  on refund anomalies through
  `thought2build_storyboard_credits_refunded_total{reason="generation_failed"}`.
- `pipeline_validator_failures_total` for mandatory section contract failures.
- `pipeline_upstream_section_skipped_total` for upstream context sections the
  prompt builder could not find.
- `thought2build_billing_credits_critic_regen_total` for critic-triggered
  regeneration credit consumption.

### Storyboard Metrics

Storyboard metrics use bounded labels only; no title, slug, generated text,
source excerpt, prompt, email, user ID, workspace ID, or credit ledger ID should
appear in Prometheus labels.

| Metric | Type | Labels | Use |
|---|---|---|---|
| `thought2build_storyboard_generation_started_total` | Counter | `action` | Paid Storyboard attempts that acquired a placeholder row and debited credits |
| `thought2build_storyboard_generation_completed_total` | Counter | `action` | Attempts that validated and reached `ready` |
| `thought2build_storyboard_generation_failed_total` | Counter | `action`, `error_type` | Provider, timeout, parser, schema, row-missing, or unexpected failures |
| `thought2build_storyboard_section_regenerated_total` | Counter | none | Successful single-section regenerations |
| `thought2build_storyboard_generation_duration_seconds` | Histogram | `action` | LLM generation plus payload validation latency |
| `thought2build_storyboard_credits_deducted_total` | Counter | `action` | Credits charged for generation/regeneration |
| `thought2build_storyboard_credits_refunded_total` | Counter | `action`, `reason` | Credits refunded for failed or recovered generations |
| `thought2build_storyboard_public_view_total` | Counter | none | Successful unauthenticated `/sb/` views |
| `thought2build_storyboard_download_total` | Counter | `kind`, `public` | Successful owner/public downloads by artifact kind |
| `thought2build_storyboard_source_missing_total` | Counter | `source`, `section` | Expected source sections absent during source extraction |
| `thought2build_pdf_export_duration_seconds` | Histogram | none | PDF render latency, including Storyboard PDF and notes PDF downloads |

Recommended dashboard panels:

```promql
# Generation failure rate by action over 15 minutes
sum by (action) (rate(thought2build_storyboard_generation_failed_total[15m]))
/
clamp_min(sum by (action) (rate(thought2build_storyboard_generation_started_total[15m])), 1)

# Refund credits issued over the last hour
sum by (action, reason) (increase(thought2build_storyboard_credits_refunded_total[1h]))

# Public view volume
increase(thought2build_storyboard_public_view_total[5m])

# Download volume by artifact and surface
sum by (kind, public) (increase(thought2build_storyboard_download_total[15m]))

# Storyboard generation p95 latency by action
histogram_quantile(
  0.95,
  sum by (le, action) (rate(thought2build_storyboard_generation_duration_seconds_bucket[15m]))
)

# PDF render p95 latency
histogram_quantile(
  0.95,
  sum by (le) (rate(thought2build_pdf_export_duration_seconds_bucket[15m]))
)

# Missing source sections
sum by (source, section) (increase(thought2build_storyboard_source_missing_total[1h]))
```

Recommended alerts:

| Alert | PromQL starter | Response |
|---|---|---|
| Storyboard generation failure rate high | `sum(rate(thought2build_storyboard_generation_failed_total[15m])) / clamp_min(sum(rate(thought2build_storyboard_generation_started_total[15m])), 1) > 0.05` | Check provider health, schema failures, and refund exactness |
| Refund spike | `sum(increase(thought2build_storyboard_credits_refunded_total[1h])) > 100` | Verify every refund maps to one failed Storyboard and one original debit |
| Public view surge | `increase(thought2build_storyboard_public_view_total[5m]) > 1000` | Check abuse/rate-limit dashboards and CDN/referrer context |
| Download failures | `sum(rate(http_requests_total{path=~".*/storyboards/.*/download.*",status_code=~"5.."}[10m])) > 0` | Inspect renderer and storage-free download paths |
| Render latency high | `histogram_quantile(0.95, sum by (le) (rate(thought2build_pdf_export_duration_seconds_bucket[15m]))) > 10` | Inspect PDF worker saturation and renderer exceptions |
| Source-missing count increased | `sum(increase(thought2build_storyboard_source_missing_total[1h])) > 0` | Inspect finalised SPEC/PLAN/HARNESS/TASKS structure before releasing prompt changes |

### Sentry

1. Confirm backend `SENTRY_DSN` is set in the target environment.
2. Confirm frontend `VITE_SENTRY_DSN` is set if frontend error reporting is
   required.
3. Trigger a controlled non-production test event only in staging.
4. Confirm the event appears in the expected Sentry project.

Expected result: errors are captured without leaking secrets. Secret-shaped
values should be redacted before they reach logs or Sentry.

### Langfuse Disabled Mode

1. Leave `LANGFUSE_SECRET_KEY` blank.
2. Start the backend.
3. Generate a SPEC stage.
4. Confirm generation, credits, streaming, and eval behavior are unchanged.
5. Confirm no outbound traffic is sent to a Langfuse host.

Expected result: the Langfuse SDK is not imported and the app behaves as if the
integration does not exist.

### Langfuse Enabled Mode

1. Set `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST`.
2. In production only, set `LANGFUSE_CONTENT_CAPTURE_ACK=true` after privacy
   approval.
3. Generate a SPEC stage.
4. Confirm a Langfuse trace exists with `workspace_id`, `user_id`,
   `stage_type`, and `action` metadata.
5. Confirm one generation exists for the full accumulated LLM response.
6. Wait for eval completion and confirm the `overall` score is attached to the
   same generation.
7. For outputs scoring `>=85` or `<60`, confirm a dataset item is created in
   `high_quality_generations` or `low_quality_generations`.

Expected result: Langfuse provides observability only. User-facing flows must
not depend on Langfuse availability.

### Billing Metrics

1. In staging with Lemon Squeezy test-store credentials, load
   `GET /billing/package`.
2. Create a checkout through the billing page (a `billing_checkout_attempts` row
   is committed before Lemon is called).
3. Complete checkout and let the Lemon `order_created` webhook reach
   `/billing/webhook`.
4. Confirm `thought2build_billing_checkout_created_total{provider="lemonsqueezy"}`,
   `thought2build_billing_checkout_completed_total{provider="lemonsqueezy"}`, and
   `thought2build_billing_credits_granted_total{provider="lemonsqueezy"}` increment.
5. Replay the same Lemon event and confirm
   `thought2build_billing_webhook_duplicate_total{provider="lemonsqueezy"}`
   increments without granting credits twice.

Expected result: checkout and webhook counters reflect the Lemon dashboard, and
duplicate delivery is visible but harmless.

### Prompt Quality Metrics

1. Generate SPEC, PLAN, HARNESS, and TASKS on staging.
2. Confirm `pipeline_validator_failures_total` remains at zero.
3. Confirm any `pipeline_upstream_section_skipped_total` labels correspond to
   genuinely absent optional upstream context, not renamed mandatory headings.
4. Confirm `thought2build_billing_credits_critic_regen_total` does not spike above
   the normal baseline after prompt changes.

Expected result: prompt gates are quiet during normal generation. Any increase
after a prompt deploy is treated as a release investigation signal.

### GitHub Integration Metrics

The Phase 21 living GitHub integration (App identity + durable `arq` worker)
emits the `thought2build_github_*` family. The webhook receiver runs on the API
process; export / increment / PR-check / reconcile metrics are emitted by the
**worker** process, so `/metrics` reflects them only where the worker shares the
registry scrape (operate the worker behind its own scrape target if deployed
separately). A labelled counter has no series until its first observation.

| Metric | Type | Labels | Use |
|---|---|---|---|
| `thought2build_github_webhook_received_total` | Counter | `event_type` | Deliveries that passed the HMAC gate |
| `thought2build_github_webhook_verified_total` | Counter | none | Signatures verified (current or rotation secret) |
| `thought2build_github_webhook_deduped_total` | Counter | `event_type` | Retried deliveries skipped idempotently |
| `thought2build_github_webhook_failed_total` | Counter | `error_type` | Deliveries rejected before dispatch (`bad_signature`, `missing_headers`, `enqueue_unavailable`) |
| `thought2build_github_reconcile_lag_seconds` | Histogram | none | Webhook-receipt → reconcile-completion latency (sync SLO) |
| `thought2build_github_export_total` | Counter | `export_mode`, `outcome` | Worker exports by mode and `completed`/`failed` |
| `thought2build_github_pr_total` | Counter | `outcome` | Pull requests opened by Thought2Build |
| `thought2build_github_check_total` | Counter | `verdict` | PR acceptance checks posted (`success`/`failure`/`neutral`) |
| `thought2build_github_token_mint_total` | Counter | `source` | Installation-token resolutions (`mint` vs `cache`) |
| `thought2build_github_job_retries_total` | Counter | `job` | Worker jobs retried with backoff |
| `thought2build_github_job_deadlettered_total` | Counter | `job` | Worker jobs dead-lettered after the try budget |
| `thought2build_github_queue_depth` | Gauge | none | Approximate queued-job depth (backpressure) |

Structured audit events (`github.installed`, `github.uninstalled`,
`github.webhook.received`, `github.webhook.duplicate_skipped`,
`github.reconcile.task_done`, `github.export.completed`, `github.pr.opened`,
`github.check.posted`, `github.increment.pushed`, `github.sync.paused`) carry
only id-shaped fields (`installation_id`, `workspace_id`, `repo_id`,
`delivery_id`, `event_type`, `action`, `status`, `push_id`). Tokens, the App
private key, raw webhook payloads, and PR diffs are never logged; the worker runs
`configure_logging()` on startup so its rows are structured and pass the same
redaction filter as the API.

#### Recommended Grafana alerts

| Alert | PromQL starter | Response |
|---|---|---|
| Webhook failure rate high | `sum(rate(thought2build_github_webhook_failed_total[15m])) / clamp_min(sum(rate(thought2build_github_webhook_received_total[15m])), 1) > 0.05` | Inspect signature/rotation config and queue health; `bad_signature` spikes can mean a stale `GITHUB_APP_WEBHOOK_SECRET` after rotation |
| Reconcile lag high | `histogram_quantile(0.95, sum by (le) (rate(thought2build_github_reconcile_lag_seconds_bucket[15m]))) > 60` | Worker saturation or GitHub API throttling — check queue depth and the per-installation governor throttle counter |
| Dead-letter rate elevated | `sum(rate(thought2build_github_job_deadlettered_total[1h])) > 0` | A job exhausted its retry budget; inspect the dead-letter records and the failing `job` label |
| Queue depth growing | `max_over_time(thought2build_github_queue_depth[10m]) > 500` | Worker throughput cannot keep up; scale workers or check for a stuck job |
| Token cache-hit ratio low | `sum(rate(thought2build_github_token_mint_total{source="mint"}[15m])) / clamp_min(sum(rate(thought2build_github_token_mint_total[15m])), 1) > 0.5` | The installation-token cache is missing too often — check Redis health and the cache TTL/namespace |
| Check verdict neutral surge | `sum(rate(thought2build_github_check_total{verdict="neutral"}[15m])) / clamp_min(sum(rate(thought2build_github_check_total[15m])), 1) > 0.5` | The fail-open evaluator is degraded (judge model / budget / no linked task), not that PRs are failing — check the judge provider and the per-tenant budget |

## Incident Response

### Metrics Unavailable

Impact: release visibility and alerting may be degraded.

Checks:

- Verify `METRICS_TOKEN` in the backend environment.
- Verify the caller is passing the token expected by `/metrics`.
- Verify trusted proxy configuration if scraping through an ingress.
- Check application logs for startup validation errors.

Decision:

- Do not deploy to production if staging metrics are unavailable.
- If production metrics fail after deploy but user flows are healthy, keep the
  app online and restore scrape access urgently.

### Sentry Not Receiving Events

Impact: exception visibility may be degraded, but user flows should continue.

Checks:

- Verify backend `SENTRY_DSN`.
- Verify frontend `VITE_SENTRY_DSN`.
- Confirm the DSN points to the intended Sentry project.
- Confirm outbound network access to Sentry is allowed.
- Check whether the error path is being swallowed intentionally.

Decision:

- Missing Sentry is not automatically a rollback condition.
- Roll back only if the same deploy also introduced user-facing errors that
  cannot be diagnosed quickly.

### Langfuse Not Receiving Traces

Impact: LLM observability, prompt lookup, eval score linking, or dataset
collection may be degraded. Generation should continue.

Checks:

- Verify `LANGFUSE_SECRET_KEY` is non-empty.
- Verify `LANGFUSE_PUBLIC_KEY` belongs to the same Langfuse project.
- Verify `LANGFUSE_HOST` points to the correct Cloud or self-hosted endpoint.
- In production, verify `LANGFUSE_CONTENT_CAPTURE_ACK=true`.
- Check backend logs for `langfuse.*.failed`.
- Confirm generation routes are passing trace IDs through the stage manager.

Decision:

- Langfuse outage alone is not a rollback condition.
- If generation, refine, credits, or eval fail because of Langfuse, treat that
  as a release blocker; the integration is required to fail open.

### Billing Webhook Errors

Impact: users may pay without receiving credits until webhook delivery or
processing recovers.

Checks:

- Verify `LEMONSQUEEZY_WEBHOOK_SECRET` (and `_PREV` during a rotation window)
  matches the Lemon webhook signing secret.
- Inspect Lemon dashboard delivery logs for `/billing/webhook`.
- Check logs for `billing.webhook.*` failures and `billing.job.*` worker errors.
- Confirm the `billing_webhook_events` inbox has one row per Lemon event id and
  duplicate deliveries return `already_processed`
  (`thought2build_billing_webhook_duplicate_total`).
- Watch `thought2build_billing_webhook_pending_age_seconds` — a value `> 300` means
  the inbox is not draining (queue outage or crashed worker). The 60s sweep
  re-enqueues stale rows; the 15-minute reconcile is the backstop.
- Confirm `LEMONSQUEEZY_TEST_MODE` is `false` in production and `true` in
  staging.

Decision:

- Roll back or disable billing if multiple successful payments are not granting
  credits.
- Keep the app online but pause checkout promotion if duplicate counters rise
  while grants remain correct.
- A sustained high `webhook_pending_age_seconds` is the trigger to scale the
  billing worker out to a dedicated `queue_name="billing"` consumer (see
  `RUNBOOK.md` §9).

### GitHub Worker / Webhook / Sync Errors (Phase 21)

Impact: GitHub events may stop flowing back (issue closes not flipping tasks to
done), exports/increments may queue without completing, or the UI may show
"sync paused". User generation and billing are unaffected — all GitHub I/O is
off the request path.

Checks:

- Inspect the `thought2build_github_*` family and the alerts above:
  `webhook_failed_total{error_type}`, `reconcile_lag_seconds` p95,
  `job_deadlettered_total{job}`, `queue_depth`, and the
  `token_mint_total{source}` cache-hit ratio.
- Confirm the **worker** process is alive (`Procfile` `worker`; `docker compose
  ps worker`) and Redis is reachable — exports/reconciles run there, not on the
  API.
- Check worker logs for `github.sync.paused` (circuit breaker open on a GitHub
  outage) and for rising job retries.
- A `bad_signature` spike right after a webhook-secret change means GitHub is
  still signing with the old secret or `GITHUB_APP_WEBHOOK_SECRET_PREV` was
  cleared too early (RUNBOOK §12.2).
- A re-mint storm (`token_mint_total{source="mint"}` rising sharply) points at a
  revoked installation or an invalid App private key (RUNBOOK §12.1/§12.3).

Decision:

- "Sync paused" / breaker-open is **self-healing** once GitHub recovers — do not
  mark pushes failed; monitor `queue_depth` draining.
- A sustained dead-letter rate is a release/ops signal: inspect and manually
  replay the idempotent job (RUNBOOK §12.4); never re-run a non-idempotent path.
- Webhook ack p99 ≥ 300 ms or reconcile p95 over SLO with healthy GitHub →
  scale the worker / check the per-installation governor throttle counter.
- None of these is a generation/billing rollback condition; they gate the
  GitHub-living release surface only.

### Prompt Validator Failures

Impact: generated artifacts may be missing required architecture, security,
SLO, capacity, FMEA, traceability, or validation sections.

Checks:

- Inspect `pipeline_validator_failures_total{stage=...}` labels.
- Compare the affected stage output with `SECTION_CONTRACTS` in
  `artifact_validator.py`.
- Check recent changes to `backend/prompts/**`, `prompt_builder.py`, and
  `critic.py`.
- Run `harness/prompt_eval` against the deployed `ASDD_PROMPT_VERSION`.

Decision:

- Treat a new sustained increase as a release blocker.
- Revert the prompt/version or disable the promotion until the eval suite and
  manual sample pass.

### Critic Regeneration Spike

Impact: users may see slower generation and extra credit consumption from
repair attempts.

Checks:

- Inspect `thought2build_billing_credits_critic_regen_total{stage=...}`.
- Check whether validator failures increased at the same time.
- Check provider latency/error rates; low-quality partial responses can cause
  repair loops.
- Review the prompt eval report for the current `ASDD_PROMPT_VERSION`.

Decision:

- Roll back a prompt deploy if the spike is new and tied to that version.
- If provider instability is the cause, route users to a healthy provider when
  possible.

### Langfuse Prompt Changes Not Taking Effect

Impact: prompt template updates may not be reflected immediately.

Checks:

- Verify prompt names:
  - `thought2build.spec.system`
  - `thought2build.plan.system`
  - `thought2build.harness.system`
  - `thought2build.tasks.system`
- Verify `LANGFUSE_PROMPT_CACHE_TTL`.
- Wait for the TTL to expire or restart the backend in staging.
- Confirm local prompt fallbacks are still valid.

Decision:

- Continue release if local fallback prompts are acceptable.
- Pause release if a required prompt fix depends on Langfuse and cannot be
  confirmed in staging.

## Data Handling Notes

Langfuse can receive full system prompts, user prompts, model outputs, eval
metadata, and dataset items after secret-shaped redaction. The redaction layer is
designed to remove credentials and token-like values; it is not a full PII
anonymization system.

Production enablement requires an explicit acknowledgement through
`LANGFUSE_CONTENT_CAPTURE_ACK=true`. For sensitive customer data, prefer a
self-hosted or privately managed Langfuse deployment with approved retention and
access controls.

## Go/No-Go Signals

Go:

- Metrics are reachable from the expected scrape path.
- Sentry DSNs are correct or intentionally blank.
- Langfuse disabled mode has no behavioral delta.
- Langfuse enabled mode fails open under outage testing.
- Lemon Squeezy checkout/webhook metrics match the Lemon dashboard when billing
  is enabled, duplicate delivery is idempotent, and
  `webhook_pending_age_seconds` stays well under 300.
- GitHub (when the App is enabled): webhook ack p99 < 300 ms, reconcile lag p95
  within SLO, dead-letter rate at zero, queue depth stable, and the
  installation-token cache-hit ratio healthy.
- Prompt validator and critic-regeneration metrics are at expected baseline.
- Prompt/output telemetry export has been approved before enabling Langfuse in
  production.

No-go:

- Production startup validation fails.
- `/metrics` is exposed without the intended protection.
- Langfuse failure breaks generation, refine, eval, credits, or prompt fallback.
- Lemon checkout completes without credit grants, or the `X-Signature` HMAC
  verification is misconfigured.
- Prompt validator failures or critic-regeneration credit usage spike after a
  prompt deploy.
- Prompt or model output telemetry is enabled in production without approval.
- An installation token, the App private key, a raw webhook payload, or a PR
  diff appears in logs, traces, Sentry events, or Langfuse payloads.
- Secrets appear in logs, traces, Sentry events, or Langfuse payloads.
