# SpecForge Observability Runbook

Use this runbook when validating, operating, or troubleshooting SpecForge
observability. It covers the three observability paths used by the application:
Prometheus metrics, Sentry, and Langfuse.

## Scope

| System | Purpose | Default behavior |
|---|---|---|
| Prometheus metrics | Health, request, auth, rate-limit, credit, and LLM operation metrics from `/metrics` | Enabled; protected by token or localhost-only access |
| Sentry | Backend and frontend exception reporting | Disabled when DSNs are blank |
| Langfuse | Optional LLM traces, prompt lookup, eval score links, and dataset collection | Disabled when `LANGFUSE_SECRET_KEY` is blank |

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
- Prompt/output telemetry export has been approved before enabling Langfuse in
  production.

No-go:

- Production startup validation fails.
- `/metrics` is exposed without the intended protection.
- Langfuse failure breaks generation, refine, eval, credits, or prompt fallback.
- Prompt or model output telemetry is enabled in production without approval.
- Secrets appear in logs, traces, Sentry events, or Langfuse payloads.
