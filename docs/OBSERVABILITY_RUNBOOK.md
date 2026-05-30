# SpecForge Observability Runbook

Use this runbook when validating, operating, or troubleshooting SpecForge
observability. It covers the observability paths used by the application:
Prometheus metrics, Sentry, Langfuse, Stripe billing counters, and prompt
pipeline quality counters.

## Scope

| System | Purpose | Default behavior |
|---|---|---|
| Prometheus metrics | Health, request, auth, rate-limit, credit, and LLM operation metrics from `/metrics` | Enabled; protected by token or localhost-only access |
| Sentry | Backend and frontend exception reporting | Disabled when DSNs are blank |
| Langfuse | Optional LLM traces, prompt lookup, eval score links, and dataset collection | Disabled when `LANGFUSE_SECRET_KEY` is blank |
| Stripe billing counters | Checkout, webhook, credit grant, duplicate delivery, dispute, and rate-limit signals | Enabled when the billing router is loaded; billing can still be disabled with blank Stripe keys |
| Prompt quality counters | Validator failures, skipped upstream sections, and critic-regeneration credit usage | Enabled with the pipeline; used by Phase 19 release gates |

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
- If `STRIPE_SECRET_KEY` is set in production, it must not be a `sk_test_*`
  key. Leave it blank to intentionally disable billing.

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

- `specforge_billing_*` for Stripe checkout, webhook, credit grant, duplicate,
  dispute, expiry, consumption, and checkout rate-limit signals.
- `specforge_storyboard_*` for Storyboard generation, public views, downloads,
  missing source sections, credit deduction, and refund behavior. Watch
  `specforge_storyboard_generation_failed_total` for failure spikes and alert
  on refund anomalies through
  `specforge_storyboard_credits_refunded_total{reason="generation_failed"}`.
- `pipeline_validator_failures_total` for mandatory section contract failures.
- `pipeline_upstream_section_skipped_total` for upstream context sections the
  prompt builder could not find.
- `specforge_billing_credits_critic_regen_total` for critic-triggered
  regeneration credit consumption.

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

1. In staging with Stripe test credentials, load `GET /billing/package`.
2. Create a Checkout Session through the billing page.
3. Complete checkout and let the Stripe webhook reach `/billing/webhook`.
4. Confirm `specforge_billing_checkout_created_total`,
   `specforge_billing_checkout_completed_total`, and
   `specforge_billing_credits_granted_total` increment.
5. Replay the same event from Stripe or the Stripe CLI and confirm
   `specforge_billing_webhook_duplicate_total` increments without granting
   credits twice.

Expected result: checkout and webhook counters reflect the Stripe dashboard,
and duplicate delivery is visible but harmless.

### Prompt Quality Metrics

1. Generate SPEC, PLAN, HARNESS, and TASKS on staging.
2. Confirm `pipeline_validator_failures_total` remains at zero.
3. Confirm any `pipeline_upstream_section_skipped_total` labels correspond to
   genuinely absent optional upstream context, not renamed mandatory headings.
4. Confirm `specforge_billing_credits_critic_regen_total` does not spike above
   the normal baseline after prompt changes.

Expected result: prompt gates are quiet during normal generation. Any increase
after a prompt deploy is treated as a release investigation signal.

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

- Verify `STRIPE_WEBHOOK_SECRET` matches the Stripe endpoint.
- Inspect Stripe dashboard delivery logs for `/billing/webhook`.
- Check logs for `billing.webhook_invalid_signature`,
  `billing.webhook_livemode_mismatch`, and `billing.webhook_handle_failed`.
- Confirm `stripe_webhook_events.stripe_event_id` has one row per processed
  event and duplicate deliveries return `already_processed`.
- Confirm production is using live Stripe keys and staging is using test keys.

Decision:

- Roll back or disable billing if multiple successful payments are not granting
  credits.
- Keep the app online but pause checkout promotion if duplicate counters rise
  while grants remain correct.

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

- Inspect `specforge_billing_credits_critic_regen_total{stage=...}`.
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
  - `specforge.spec.system`
  - `specforge.plan.system`
  - `specforge.harness.system`
  - `specforge.tasks.system`
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
- Stripe checkout/webhook metrics match the Stripe dashboard when billing is
  enabled, and duplicate delivery is idempotent.
- Prompt validator and critic-regeneration metrics are at expected baseline.
- Prompt/output telemetry export has been approved before enabling Langfuse in
  production.

No-go:

- Production startup validation fails.
- `/metrics` is exposed without the intended protection.
- Langfuse failure breaks generation, refine, eval, credits, or prompt fallback.
- Stripe checkout completes without credit grants, or webhook HMAC/livemode
  validation is misconfigured.
- Prompt validator failures or critic-regeneration credit usage spike after a
  prompt deploy.
- Prompt or model output telemetry is enabled in production without approval.
- Secrets appear in logs, traces, Sentry events, or Langfuse payloads.
