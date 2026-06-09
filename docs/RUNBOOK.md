# SpecForge Operations Runbook

Operational procedures for SpecForge V1 on-call engineers and SREs.  
Covers: circuit breaker, finalise race incident response, credit refund
procedures, auth cache limitations, dependency version management, Lemon Squeezy
billing alerts and ops, and prompt pipeline quality gates.

---

## Table of Contents

1. [LLM Circuit Breaker](#1-llm-circuit-breaker)
2. [Finalise Race (CF-1) — SELECT FOR UPDATE](#2-finalise-race-cf-1)
3. [Credit Accounting — Refund and Recovery](#3-credit-accounting--refund-and-recovery)
4. [Auth Cache — Multi-Worker Limitations](#4-auth-cache--multi-worker-limitations)
5. [General Health Checks](#5-general-health-checks)
6. [Langfuse Docker Image — Version Management](#6-langfuse-docker-image--version-management)
7. [Database Migrations — Alembic Runbook](#7-database-migrations--alembic-runbook)
8. [Secret Rotation Procedures](#8-secret-rotation-procedures)
9. [Billing Alerts And Lemon Squeezy Ops](#9-billing-alerts-and-lemon-squeezy-ops)
10. [Prompt Pipeline Quality Gates And Eval Workflow](#10-prompt-pipeline-quality-gates-and-eval-workflow)
11. [Storyboard Operations](#11-storyboard-operations)
12. [GitHub Living Integration — App, Worker & Webhook Ops](#12-github-living-integration--app-worker--webhook-ops)

---

## 1. LLM Circuit Breaker

**Reference:** CF-2, T-197, T-215  
**Module:** `backend/services/llm/provider_status.py`, `backend/services/llm/gateway.py`

### What It Is

The LLM circuit breaker tracks consecutive failures per provider using `_FAILURES` (a module-level dict in `provider_status.py`). After `_UNHEALTHY_FAILURE_THRESHOLD` (3) consecutive failures within a 600-second window, `can_route(provider)` returns `False` and `gateway.get_llm()` raises `HTTPException(503)` for all subsequent requests to that provider.

### Detecting a Circuit Activation

**Prometheus metric:** `specforge_llm_circuit_rejections_total{provider="<provider>"}`

> **Alert:** if `specforge_llm_circuit_rejections_total > 0` — a circuit breaker has
> activated. Check provider health via `GET /providers/health` while signed in.

```promql
# Alert: circuit breaker tripped in the last 5 minutes
increase(specforge_llm_circuit_rejections_total[5m]) > 0

# Grafana dashboard: rejection rate per provider (T-215)
rate(specforge_llm_circuit_rejections_total[5m])
# — or grouped to sum across all labels:
sum by (provider) (rate(specforge_llm_circuit_rejections_total[5m]))

# Current open/closed state per provider (0=closed, 1=open): (T-220)
specforge_llm_circuit_state

# Alert when any provider circuit is open:
max by (provider) (specforge_llm_circuit_state) == 1
```

**Log signal:**

```
level=WARNING event="llm.circuit_open" provider="anthropic" model="..."
```

Search Grafana / Loki: `{app="specforge"} |= "llm.circuit_open"`.

### User Impact When the Circuit Is Open

- All generation requests routed to the tripped provider return **HTTP 503** immediately (no LLM call is made).
- Health-check probes (`GET /providers/health`) are **not** blocked — they
  bypass the circuit via `bypass_circuit=True` and can detect recovery for all
  configured providers. The endpoint requires an authenticated user.
- The circuit **auto-resets** when either:
  1. `record_provider_success()` is called (health probe succeeds), or
  2. The last failure is older than 600 seconds (the window expires).

### Manual Reset Procedure

If you need to force-reset the circuit breaker for a provider (e.g. after a deployment that fixes the outage):

```python
# Connect to a running worker (e.g. via kubectl exec or Railway shell):
from services.llm.provider_status import record_provider_success
record_provider_success("anthropic")   # replace with the affected provider
```

Or simply restart the worker processes — `_FAILURES` is in-process memory and resets on restart.

### Disabling the Circuit Breaker for a Provider

For emergency bypass (e.g. during circuit tuning or provider-side investigation):

In `provider_status.py`, temporarily raise `_UNHEALTHY_FAILURE_THRESHOLD` or set it to a very high value, then redeploy. **Revert immediately** after the investigation.

### SLA Impact and Escalation

| Scope | Impact | Action |
|---|---|---|
| One provider tripped | Users on that provider's key receive HTTP 503; platform-key users on other providers unaffected | Check provider status page; wait for auto-reset or call `record_provider_success()` |
| All providers tripped | All generation requests return 503 | **Escalate immediately** to LLM provider engineering contact; consider emergency bypass (raise `_UNHEALTHY_FAILURE_THRESHOLD`) while investigating |
| Circuit never resets | Health probes fail to reach provider | Verify network egress from Railway; check provider status API |

### Multi-Worker Note

`_FAILURES` is **per-worker-process**. In multi-worker deployments (Gunicorn + multiple uvicorn workers) each process maintains an independent failure count. A provider may be circuit-open in one worker and healthy in another. This is an accepted trade-off — a distributed circuit would require a shared Redis counter. Monitor `specforge_llm_circuit_rejections_total` across all instances to detect partial activation.

---

## 2. Finalise Race (CF-1) — SELECT FOR UPDATE

**Reference:** CF-1, T-196  
**Module:** `backend/services/pipeline/stage_manager.py` — `StageManager.finalise()`

### What It Is

`StageManager.finalise()` uses `SELECT FOR UPDATE` (pessimistic locking via SQLAlchemy `.with_for_update()`) to serialise concurrent finalise calls on the same stage. Only one session can hold the row lock at a time; the second caller blocks at the database level, then re-reads the committed status (`READ COMMITTED` isolation — PostgreSQL default) and raises `ValueError("cannot be finalised")`.

### Detecting a Double-Finalise Incident

A double-finalise would appear as two success responses for the same `stage_id` in the API logs with `status='finalised'`. Under normal operation this **cannot happen** because of the `SELECT FOR UPDATE` lock. If you see it, suspect:

1. A bug was introduced that removed `lock=True` from `_load_stage()` in `finalise()`.
2. The database is not PostgreSQL or is running in a non-MVCC mode.
3. A manual DB patch bypassed the application layer.

**Log pattern** (both would appear in the same narrow time window for the same stage_id):

```
event="stage.finalised" stage_id="<uuid>" workspace_id="<uuid>"
```

### Rollback for a Double-Charged User

If a user was double-charged due to a double-finalise bug:

1. Identify the duplicate `CreditLedger` entry via:

```sql
SELECT * FROM credit_ledger
WHERE user_id = '<user_uuid>'
  AND operation = 'finalise'
ORDER BY created_at DESC
LIMIT 10;
```

2. Issue a manual refund via the credit service:

```python
from services.credit_service import CreditService
await CreditService(redis_client=redis).refund(db, user_id, amount, "manual_refund_double_finalise")
```

3. Verify the refund appears in the ledger and the user's `credit_balance` is updated.

### SELECT FOR UPDATE Prerequisites

- Requires PostgreSQL (not SQLite or other non-MVCC databases).
- Requires `READ COMMITTED` isolation or higher (PostgreSQL default is `READ COMMITTED`).
- The lock is released automatically when the transaction commits or rolls back.
- Integration test in `backend/tests/test_finalise_integration.py` verifies this end-to-end with a real PostgreSQL instance (requires `TEST_DATABASE_URL`).

---

## 3. Credit Accounting — Refund and Recovery

**Reference:** MF-3, T-205  
**Module:** `backend/services/credit_service.py`

### Credit Deduction Flow

1. Pre-check: `CreditService.check_balance()` verifies `credit_balance >= cost` before any generation.
2. Deduction: `CreditService.deduct()` creates a `CreditLedger` entry and decrements `User.credit_balance`.
3. On success: the deduction is committed.
4. On failure / disconnect: `CreditService.refund()` is called with a savepoint to reverse the charge.

### Investigating Credit Discrepancies

```sql
-- Sum all ledger entries for a user (positive = credit, negative = deduction)
SELECT SUM(amount) AS ledger_balance, u.credit_balance AS current_balance
FROM credit_ledger cl
JOIN "user" u ON u.id = cl.user_id
WHERE cl.user_id = '<user_uuid>'
GROUP BY u.credit_balance;
```

If `ledger_balance != current_balance`, a write to `credit_ledger` succeeded but `User.credit_balance` was not updated (or vice versa). Investigate recent error logs around the user's last generation.

### Manual Refund

```python
from services.credit_service import CreditService
await CreditService(redis_client=redis).refund(db, user_id, amount, "manual_refund_incident")
```

### Cache Invalidation

`CreditService.deduct()` and `.refund()` both call `_invalidate(user_id)` which:
1. Deletes the Redis key `credits:<user_id>`.
2. Calls `invalidate_user_cache(user_id)` to evict the in-process `_USER_CACHE` entry (H-4 — T-185).

If the credit balance appears stale after a deduction, verify both caches were cleared.

### Escalation Threshold

| Affected Users | Severity | Action |
|---|---|---|
| 1–2 | Low | Issue manual refund; monitor for recurrence |
| 3–9 | Medium | Open incident; assign on-call engineer |
| ≥ 10 | **P1 Incident** | Page on-call lead; escalate to engineering manager; run post-mortem within 48h |

---

## 4. Auth Cache — Multi-Worker Limitations

**Reference:** LF-1, T-210  
**Module:** `backend/middleware/auth.py`

### What It Is

The auth middleware maintains `_USER_CACHE: dict[UUID, tuple[float, dict]]` — an **in-process** LRU-style cache mapping user IDs to their last-fetched user row (including `credit_balance`). Entries are valid for 30 seconds (`_USER_CACHE_TTL_SECONDS = 30`).

### Multi-Worker Incoherence

In multi-worker deployments (Gunicorn + multiple uvicorn workers), each worker process has its own independent `_USER_CACHE`. A `credit_balance` update (deduction, refund, admin adjustment) via worker A is not visible in worker B's cache until worker B's TTL expires (up to 30 seconds).

**Symptom:** A user deducts credits and immediately sees the old balance in the next request if that request is routed to a different worker.

**Mitigation:**
- `invalidate_user_cache(user_id)` is called after every deduction and refund, but only clears the cache **in the same worker process**.
- For single-worker deployments: no issue.
- For multi-worker deployments: users may see a stale `credit_balance` for up to 30 seconds after a deduction on a different worker.

**Long-term fix:** Migrate `_USER_CACHE` to a Redis-backed cache so all workers share the same invalidation signal. Until then, the 30-second TTL bounds the maximum staleness.

### Debugging Stale Cache Readings

```python
# From within the process (e.g. via uvicorn reload or debug endpoint):
from middleware.auth import _USER_CACHE
# Show all cached users and their expiry:
import time
for uid, (exp, data) in _USER_CACHE.items():
    print(uid, "expires_in:", exp - time.time(), "balance:", data.get("credit_balance"))
```

To force-clear the cache for a specific user: `invalidate_user_cache(user_id)` in the affected worker process.

---

## 5. General Health Checks

### Endpoint

```
GET /health
```

Returns HTTP 200 with `{"status":"ok","version":"1.0.0"}` when healthy and
HTTP 503 with `status:"degraded"` on dependency failure. In non-production the
response also includes `db` and `redis`; production omits dependency details.

### LLM Provider Health

```
GET /providers/health
```

Requires authentication. Triggers live health probes for all configured
providers (bypassing the circuit breaker) and returns each provider's health
status, failure count, and circuit state.

### Prometheus Metrics

```
GET /metrics
```

Requires `Authorization: Bearer <METRICS_TOKEN>`.

Key metrics to monitor:

| Metric | Alert Condition |
|---|---|
| `specforge_llm_circuit_rejections_total` | Any increase → circuit tripped |
| `llm_request_total` | Drop in successful requests |
| `http_request_duration_seconds` | P95 > 30s → LLM latency spike |
| `sse_stream_duration_seconds` | P95 > 120s → streaming hung |
| `pdf_export_duration_seconds` | P95 > 10s → PDF rendering slow |
| `eval_failure_total` | Sustained increase → eval service degraded |
| `specforge_billing_webhook_error_total` | Any increase → billing webhook processing error |
| `specforge_billing_webhook_pending_age_seconds` | `> 300` → billing inbox not draining (queue outage / crashed worker) |
| `specforge_billing_checkout_rate_limited_total` | Sustained increase → checkout abuse or broken retry loop |
| `pipeline_validator_failures_total` | Any increase → prompt output missing mandatory sections |
| `pipeline_upstream_section_skipped_total` | Sustained increase → upstream stage lacks required context |
| `specforge_billing_credits_critic_regen_total` | Spike → critic loop is burning extra regeneration credits |

---

## 6. Langfuse Docker Image — Version Management

**Reference:** MF-5, T-209  
**File:** `docker-compose.yml` — `langfuse` service

### Why the Image Is Pinned

`docker-compose.yml` pins the Langfuse image to a specific semver tag (e.g.
`langfuse/langfuse:3.175.0`) instead of `:latest`. A floating `:latest` tag
means **any** `docker compose pull` can silently pull a breaking Langfuse
release, disabling prompt management and telemetry in production without any
code change in this repository.

### Checking for Updates

1. Visit **https://github.com/langfuse/langfuse/releases** and note the latest
   stable semver tag.
2. Review the release notes for:
   - **Breaking changes** to the Langfuse API surface (prompt management
     endpoints, SDK payload shapes).
   - **Database migration requirements** — Langfuse runs its own Postgres
     instance; a major release may require running migrations before the new
     container starts.
   - **Environment variable renames** — check `docker-compose.yml` env block
     against the new release's required vars.
3. If SpecForge integrates with the Langfuse API (`LANGFUSE_PUBLIC_KEY`,
   `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`), verify the SDK version in
   `backend/pyproject.toml` is compatible with the new Langfuse server version.

### Upgrade Procedure

```bash
# 1. Edit docker-compose.yml — update the pinned tag:
#    image: langfuse/langfuse:<new-version>
vim docker-compose.yml

# 2. Pull the new image (validates the tag exists on Docker Hub):
docker compose pull langfuse

# 3. Start the langfuse profile in dev to smoke-test:
docker compose --profile langfuse up -d langfuse langfuse-db

# 4. Verify Langfuse UI is reachable:
curl -s http://localhost:3000/api/public/health | jq .

# 5. Send a test generation request through SpecForge and confirm prompts are
#    fetched from Langfuse (check backend logs for "langfuse.prompt_fetched"):
#    docker compose logs -f backend | grep langfuse

# 6. If everything is healthy, commit the version bump:
git add docker-compose.yml
git commit -m "chore: bump Langfuse image to <new-version>"
git push
```

### Rollback

If the new version causes issues:

```bash
# Revert docker-compose.yml to the previous pinned tag and redeploy:
git revert HEAD  # or manually edit and docker compose up -d
```

Because the image is pinned, rolling back is a single tag change — no data
loss unless Langfuse ran schema migrations (check release notes).

### Langfuse-Specific Breakage Signals

| Symptom | Likely Cause |
|---|---|
| Backend logs `langfuse.prompt_fetch_failed` | SDK/server API version mismatch |
| Langfuse UI blank / 500 on load | DB migration not completed |
| `LANGFUSE_HOST` returns 404 on `/api/public/prompts` | Endpoint path changed in new version |
| Prompts silently falling back to hardcoded defaults | `get_prompt()` returning `None` — check SDK compatibility |

### Current Pinned Version

See `docker-compose.yml` — `langfuse` service `image:` line. Update this
runbook entry when the version is bumped.

---

## 7. Database Migrations — Alembic Runbook

**Reference:** T-213, T-216  
**Files:** `backend/migrations/`, `backend/alembic.ini`

### Running Migrations in Production (Railway)

Migrations run automatically as part of the Railway deploy process via
`backend/entrypoint.sh`:

```bash
alembic upgrade head
```

This is safe to run on every deploy — Alembic tracks applied migrations in the
`alembic_version` table and skips already-applied revisions. Do **not** set
`--sql` (dry-run mode) in production; it generates SQL without executing it.

**Manual trigger** (if needed via Railway shell):

```bash
cd /app
uv run alembic upgrade head
```

### Rolling Back a Migration

```bash
# Roll back the most recent migration:
uv run alembic downgrade -1

# Roll back to a specific revision:
uv run alembic downgrade <revision_id>

# Check current head:
uv run alembic current

# View migration history:
uv run alembic history --verbose
```

> **Warning:** `downgrade -1` is destructive if the migration added columns or
> tables with data. Always check the `downgrade()` function in the migration
> file before running in production. Take a database snapshot first.

### Checking Migration Status

```bash
# Confirm all migrations are applied:
uv run alembic current

# Expected output: <revision_id> (head)
# If a revision shows without "(head)", a migration is pending.
```

```sql
-- Verify from the DB directly:
SELECT version_num FROM alembic_version;
```

### Migration-Specific Notes

#### T-213 — `eval_results` Composite Index (`0012_eval_results_composite_index.py`)

Migration `0012` creates a B-tree composite index on
`eval_results(stage_version_id, created_at DESC)` via a standard
`CREATE INDEX` statement (not `CONCURRENTLY`).

**On small/staging databases:** safe to apply online with no perceptible lock
time. The migration runs in a transaction; if it fails, the table is unchanged.

**On large production tables (millions of eval rows):** the `ShareLock` held
during index build blocks concurrent writes for the full build duration
(typically seconds to minutes depending on table size). Consider a maintenance
window **or** run the index build manually outside this migration:

```sql
-- Run outside a transaction (psql):
\set ON_ERROR_STOP on
CREATE INDEX CONCURRENTLY ix_eval_results_stage_version_created_at
    ON eval_results USING btree (stage_version_id, created_at DESC);
```

Then mark the migration as applied without executing it:

```bash
uv run alembic stamp 0012
```

#### Adding New Migrations

1. Generate a new revision:
   ```bash
   uv run alembic revision --autogenerate -m "describe_the_change"
   ```
2. Review the generated file in `backend/migrations/versions/` — autogenerate
   is not always correct; verify the `upgrade()` and `downgrade()` functions.
3. Test locally: `uv run alembic upgrade head` against a fresh database.
4. Commit the file and let CI/Railway apply it on the next deploy.

### Schema Backup Before a Major Migration

```bash
# Snapshot the schema (not data) before a risky migration:
pg_dump --schema-only $DATABASE_URL > schema_backup_$(date +%Y%m%d).sql
```

Store the backup outside the Railway ephemeral filesystem (e.g. in an S3
bucket or local machine) before triggering the deploy.

---

## 8. Secret Rotation Procedures

SpecForge manages three categories of critical secrets, each with a distinct
rotation impact and procedure.  Rotate proactively on a scheduled cadence or
immediately when a compromise is suspected.

### §8.1 — ENCRYPTION_MASTER_KEY Rotation

**Impact:** `ENCRYPTION_MASTER_KEY` (Fernet symmetric key) encrypts all stored
integration tokens in the `user_integrations` table (`encrypted_token` column).
Rotating without re-encrypting those rows leaves them permanently unreadable
under the new key.

**Pre-rotation check:**

```sql
-- Verify all rows are currently readable (count should be non-negative, no errors):
SELECT COUNT(*) FROM user_integrations WHERE encrypted_token IS NOT NULL;
```

**Rotation steps:**

1. Generate a new Fernet key:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. Add the new key to Railway environment **alongside** the existing one —
   do **not** remove the old key yet:

   ```
   ENCRYPTION_MASTER_KEY=<old_key>        # keep for decryption
   NEW_ENCRYPTION_MASTER_KEY=<new_key>    # new key for re-encryption
   ```

3. Run the rotation script to re-encrypt all rows (idempotent — safe to
   re-run; rows already encrypted under the new key are skipped):

   ```bash
   cd backend
   uv run python scripts/rotate_encryption_key.py \
       --old-key "$ENCRYPTION_MASTER_KEY" \
       --new-key "$NEW_ENCRYPTION_MASTER_KEY" \
       --database-url "$DATABASE_URL"
   ```

   Use `--dry-run` to preview without writing:

   ```bash
   uv run python scripts/rotate_encryption_key.py \
       --old-key "$ENCRYPTION_MASTER_KEY" \
       --new-key "$NEW_ENCRYPTION_MASTER_KEY" \
       --database-url "$DATABASE_URL" \
       --dry-run
   ```

   **Exit codes:** `0` = all rows rotated or already on new key;
   `1` = connection/argument error; `2` = partial failure (some rows
   could not be decrypted — inspect stderr output).

4. Verify the rotation succeeded:

   ```bash
   uv run pytest tests/test_key_vault.py -v
   ```

   Run the tests with `ENCRYPTION_MASTER_KEY` set to the **new** key.

5. Promote the new key in Railway:

   ```
   ENCRYPTION_MASTER_KEY=<new_key>        # replace with new key
   # Remove NEW_ENCRYPTION_MASTER_KEY
   ```

6. Deploy the updated environment.

**Rollback:** Keep the old key in Railway as `OLD_ENCRYPTION_MASTER_KEY` until
the rotation is fully verified.  To roll back, re-run the script with
`--old-key` and `--new-key` swapped.

---

### §8.2 — CSRF_SECRET Rotation

**Impact:** Rotating `CSRF_SECRET` immediately invalidates **all** outstanding
CSRF tokens.  Users will see `403 Forbidden — CSRF token invalid` on their
next mutating request (POST/PUT/DELETE).  They simply need to refresh the page
to obtain a new token — no data loss occurs.

**Best practice:** Rotate during a low-traffic window (e.g., off-peak hours).

**Rotation steps:**

1. Generate a new secret:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Update `CSRF_SECRET` in Railway environment.

3. Deploy — the new secret takes effect immediately on next process start.

4. Monitor `csrf.verify.failed` structured log events; they should return
   to the pre-rotation baseline within **5 minutes** as users refresh and
   receive new tokens.

**No Redis cleanup required** — existing CSRF nonce keys expire naturally on
their existing TTL.

**Rollback:** Restore the previous value of `CSRF_SECRET` in Railway and
redeploy.

---

### §8.3 — JWT Key Rotation

**Impact:** Rotating `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` invalidates **all**
existing access tokens and refresh tokens (RS256 signature verification fails
against the old public key).  Every active user is forced to re-authenticate.

**Best practice:** Rotate only when key compromise is confirmed, or on an
annual schedule.  Announce to users in advance if possible.

**Rotation steps:**

1. Generate a new RS256 key pair:

   ```bash
   openssl genrsa 4096 | tee jwt_private.pem
   openssl rsa -in jwt_private.pem -pubout > jwt_public.pem
   ```

2. Update `JWT_PRIVATE_KEY` (contents of `jwt_private.pem`) and
   `JWT_PUBLIC_KEY` (contents of `jwt_public.pem`) in Railway.

3. Purge all refresh token entries from Redis so stale tokens cannot be
   exchanged:

   ```bash
   redis-cli -u "$REDIS_URL" KEYS "refresh:*" | xargs redis-cli -u "$REDIS_URL" DEL
   ```

4. Deploy.

5. Monitor authentication error rates — they will spike briefly as users
   re-authenticate, then return to baseline within minutes.

**Rollback:** Restore the old `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` in
Railway and redeploy.  Previously-issued tokens (before the rotation) become
valid again, but any tokens issued under the new key will stop working.

---

### §8.4 — Redis Password Rotation (if applicable)

If the Redis instance requires a password (e.g., Railway managed Redis with
auth enabled):

1. Obtain the new Redis password from the Railway dashboard or your Redis
   provider.
2. Update `REDIS_URL` in Railway to include the new password.
3. Redeploy the service — the connection pool is rebuilt on startup.

No data re-encryption is needed; Redis stores session and rate-limit state,
not long-lived secrets.


---

## 9. Billing Alerts And Lemon Squeezy Ops

Billing runs on **Lemon Squeezy** (Phase 22). Lemon is the Merchant of Record,
so it owns tax, chargebacks, and disputes; chargebacks/disputes surface to
SpecForge through `order_refunded`/fraud revocation inputs. The Stripe runtime is
**fully decommissioned** (T-308): there is no Stripe SDK, config, or webhook
processing — `POST /billing/webhook` answers a Stripe-shaped request (a
`Stripe-Signature` header) with `{"status":"ignored_provider_disabled"}` and no
DB write. Only the read-only `stripe_credit_packs` / `stripe_webhook_events`
audit tables (the historical financial record) remain.

Architecture recap (so the procedures below make sense):

- `POST /billing/checkout` is **attempt-first** — a `billing_checkout_attempts`
  row is committed (snapshotting credits/price/currency/validity) before Lemon is
  called; the frontend polls `GET /billing/status?checkout_ref=…`.
- `POST /billing/webhook` verifies the `X-Signature` HMAC (two-secret list),
  commits the event to the durable `billing_webhook_events` **inbox** keyed by the
  Lemon event id, then **enqueues** `billing_process_webhook` on the arq worker.
  The HTTP path never grants credits inline.
- The worker grant is idempotent on `(provider, provider_order_id)` and the
  `billing_purchase:lemonsqueezy:{order}` ledger reason. Refund/fraud revocation
  is idempotent on the `refund:billing:{pack}:{cents}` reason; over-spent value
  becomes **recoverable billing debt** (expired value is never debt).
- Two crons keep the system honest: a **60s pending-sweep**
  (`billing_process_pending_webhooks`) and a **15-minute reconcile**
  (`billing_reconcile`, three lanes).

### 9.1 Grafana Alerts

The following alert rules correspond to the provider-labelled counters defined in
`services/observability.py` (Phase 22 — T-304). `{provider}` is `lemonsqueezy`
(the only runtime emitter; `provider="stripe"` series persist only as historical
audit data after the T-308 decommission).

| Alert | Condition | Severity | Action |
|---|---|---|---|
| BillingWebhookErrorRate | `rate(specforge_billing_webhook_error_total[5m]) > 0` | Warning | Check logs for `billing.webhook.*` / `billing.job.*`; inspect Lemon dashboard delivery logs. Webhook retries are safe — the inbox dedupes on the event id. Delete a `billing_webhook_events` row only with incident-lead approval and only after confirming credits were not granted |
| BillingWebhookPendingAge | `specforge_billing_webhook_pending_age_seconds > 300` | Warning | The inbox is not draining (queue outage or crashed worker). Confirm the worker process is up and Redis is reachable; the 60s sweep re-enqueues stale rows. A sustained breach is the trigger to scale the billing worker out (§9.6) |
| BillingCheckoutDropped | `rate(specforge_billing_checkout_completed_total[30m]) == 0` while `checkout_created` rising; **or** zero `checkout_completed` over 72h | Warning | Verify `/billing/webhook` is reachable and returning 200; check Lemon webhook delivery logs and the inbox; inspect CSRF/rate-limit exemptions |
| BillingReversalSpike | `rate(specforge_billing_credits_revoked_total[1h])` above baseline | Warning | A burst of `order_refunded`/fraud revocations. Review the Lemon dashboard; confirm reversals are legitimate and debt was created where expected |
| BillingUnprovablePaidCheckout | `increase(specforge_billing_unrecoverable_checkout_total[1h]) > 0` | Warning | An `order_created` was rejected while the provider reports the order **paid**. Reconcile cannot auto-grant this — settle via the admin-correction path (§9.5) with evidence |
| BillingDebtCreated | `increase(specforge_billing_credit_debt_created_total[1h]) > 0` | Info | A reversal exceeded remaining balance and created recoverable debt. Expected after refunds on spent credits; investigate if the rate is abnormal |
| BillingReconcileMismatch | `increase(specforge_billing_reconcile_mismatch_total[1h]) > 0` | Warning | Reconcile lane 2 applied a reversal the webhook path missed. Investigate why the webhook was lost (delivery, signature, inbox) |
| BillingExpirySpike | `rate(specforge_billing_credits_expired_total[1h])` above baseline | Info | Unusual volume of credits lazily expiring; correlate with a past purchase cohort, not a fault |
| BillingJobDeadlettered | `increase(specforge_billing_job_deadlettered_total[15m]) > 0` | Critical | A billing job exhausted retries and landed in `billing:deadletter`. Inspect and replay (§9.3) |
| BillingWebhookDuplicate | `rate(specforge_billing_webhook_duplicate_total[1h]) > 100` | Info | Normal if Lemon is retrying; investigate above 100/hour — the endpoint may be failing silently after the `already_processed` return |

### 9.2 Billing Endpoint Recovery

- `GET /billing/package` is public and should keep returning the configured
  package even when checkout is disabled.
- `POST /billing/checkout` requires authentication and is rate limited to five
  attempts per user per hour. A **503** means Lemon billing is not configured
  (one of `LEMONSQUEEZY_API_KEY` / `_STORE_ID` / `_VARIANT_ID` is blank); a
  **502** means Lemon could not create the checkout, or the post-Lemon commit
  failed (the URL is never exposed; reconcile settles the order later).
- `POST /billing/webhook` is exempt from browser CSRF and app rate limits, but
  every event must pass `X-Signature` HMAC verification before any DB/queue work.
  Webhook retries are safe: the `billing_webhook_events` inbox is unique per Lemon
  event id and duplicate deliveries return `already_processed`.
- In production, Lemon enablement requires `LEMONSQUEEZY_WEBHOOK_SECRET`, an HTTPS
  `LEMONSQUEEZY_SUCCESS_URL`, and `LEMONSQUEEZY_TEST_MODE=false` — half-configured
  Lemon fails `validate_production_settings()` at startup.

### 9.3 Dead-Letter Replay (`billing:deadletter`)

Billing jobs that exhaust `JOB_MAX_TRIES` are routed to the Redis list
`billing:deadletter` (the GitHub stream uses the separate `gh:deadletter` — never
mix them). The constants are `BILLING_DEAD_LETTER_KEY` in
`backend/services/queue.py`.

1. Inspect depth and the head record:
   ```bash
   redis-cli -u "$REDIS_URL" LLEN billing:deadletter
   redis-cli -u "$REDIS_URL" LINDEX billing:deadletter 0
   ```
   Each record carries the job function (`billing_process_webhook`) and its args
   (the `billing_webhook_events` row id).
2. **Find root cause first** in the logs (`billing.job.*` / `_persist_failed`)
   before replaying — replaying a poison job just dead-letters it again.
3. The underlying inbox row is still present and idempotent. The safest replay is
   to let the **60s sweep**/**15-minute reconcile lane 1** re-enqueue it: confirm
   the row's status is `received`/retryable `failed` and wait one cron tick.
4. To force it immediately, re-enqueue `billing_process_webhook` with the inbox
   row id (e.g. via an arq enqueue against `WorkerSettings`' Redis), then
   `LREM billing:deadletter 1 <record>` once it processes cleanly. Grants stay
   idempotent on `(provider, provider_order_id)`, so a double replay cannot
   double-credit.

### 9.4 Pending-Row Recovery & Reconcile

- **Pending sweep (60s):** `billing_process_pending_webhooks` reclaims inbox rows
  stuck in `received`/`failed`/stale `processing` (e.g. after a queue outage or a
  crashed worker) and refreshes `specforge_billing_webhook_pending_age_seconds`
  to the age of the oldest non-`processed` row. A rising gauge is the primary
  "lost webhook" signal.
- **Reconcile (15-minute backstop):** `billing_reconcile` holds the single
  `billing_reconciliation_cursors` row under `SELECT … FOR UPDATE NOWAIT` (an
  overlapping tick skips cleanly) and runs three bounded lanes:
  - **Lane 1 — inbox replay:** re-enqueues committed/retryable rows. This is the
    only automatic path that recovers a missed `order_created` (the signed
    `checkout_ref`+nonce row is the proof).
  - **Lane 2 — provider re-read:** for live Lemon packs, `get_order` is called
    (bounded by `LEMONSQUEEZY_RECONCILE_MAX_CALLS_PER_RUN`); a missed
    refund/fraud applies the **same** `apply_refund_reversal` and increments
    `reconcile_mismatch`.
  - **Lane 3 — hygiene:** expires checkout attempts past `expires_at` and emits a
    stale-attempt operator count.
- **Reconcile never auto-grants.** It only re-enqueues signed inbox rows and
  revokes on existing packs — there is no code path that invents a first grant
  from order listing/amount/email. An unprovable paid checkout is settled via the
  admin-correction path (§9.5).

### 9.5 Admin-Correction Runbook (`POST /billing/admin/correction`)

The exceptional, evidence-backed manual grant for an order the automatic pipeline
could not settle (e.g. `BillingUnprovablePaidCheckout`).

- **Authorisation:** the caller's email must be in `ADMIN_USER_EMAILS`
  (comma-separated). An empty allowlist authorises nobody — the path is closed by
  default. There is no role column in V1.
- **Request body:** `provider` (`lemonsqueezy`), `provider_order_id`,
  `target_user_id`, `credits`, `price_cents`, `currency`, a `reason`
  justification, and an `evidence_url` (the support ticket or the Lemon dashboard
  order). The `evidence_url` is **required**.
- **Idempotency:** the write is append-only and unique on
  `(provider, provider_order_id)`. A repeat call returns `applied: false`,
  `credits_granted: 0` — never a second grant. Every call is audited
  (`billing_admin_corrections` row + `specforge_billing_admin_correction_total`).
- **Procedure:** confirm the order is genuinely paid in the Lemon dashboard and
  that no pack already exists for the order id; capture the evidence URL; issue
  the correction; verify the user's balance moved by exactly `credits`.

### 9.6 Optional Dedicated Billing Worker (Scale-Out)

By default, billing jobs run on the shared `WorkerSettings` worker (the same
process that drains the GitHub queue) on the default queue — works out of the box;
never route billing to a queue with no consumer. For scale-out under sustained
load (the trigger is a persistently high `webhook_pending_age_seconds`), a
dedicated `queue_name="billing"` consumed by a separate `BillingWorkerSettings`
worker may be added (its own `Procfile` line + `docker-compose` service, sharing
the backend image and Redis). This is an optional future operational step, not
currently wired — add it only when the shared worker can no longer keep the
pending age low.

### 9.7 Account-Deletion Settlement (RESTRICT FKs)

`billing_credit_debts` and `billing_admin_corrections` hold **`ON DELETE
RESTRICT`** foreign keys to `users` / `billing_credit_packs` so the financial
audit trail can never be silently orphaned. V1 exposes **no** user-deletion
endpoint, so this is a **manual ops procedure**, not a code path:

1. Before removing a user row (a GDPR erasure or support deletion), first settle
   billing state: confirm there is **no open (unrecovered) debt** for the user
   (`billing_credit_debts` where `credits_owed > credits_recovered`); recover or
   write it off per finance policy.
2. The `RESTRICT` FKs will **block** the delete while any debt/correction row
   references the user or their packs. Do not `CASCADE` or hand-delete the audit
   rows to force the delete — that destroys the financial record. Retain the audit
   rows (anonymise the user PII elsewhere if required by the erasure request) and
   record the settlement in the deletion ticket.

### 9.8 Lemon API-Key & Webhook-Secret Rotation

**Webhook secret (two-secret window).** The handler verifies `X-Signature`
against `settings.lemonsqueezy_webhook_secrets` =
`[LEMONSQUEEZY_WEBHOOK_SECRET, LEMONSQUEEZY_WEBHOOK_SECRET_PREV]` (blank entries
ignored), so rotation is zero-downtime:

1. Generate the new secret in the Lemon dashboard (do not save it on the webhook
   yet).
2. Stage both secrets in the backend env — the new one is accepted but signs
   nothing yet:
   ```env
   LEMONSQUEEZY_WEBHOOK_SECRET=<new_secret>       # accepted
   LEMONSQUEEZY_WEBHOOK_SECRET_PREV=<old_secret>  # still accepted during window
   ```
   Redeploy. Both secrets now verify.
3. Update the **Lemon webhook** to sign with `<new_secret>`. Deliveries now sign
   with the new secret and still verify against `LEMONSQUEEZY_WEBHOOK_SECRET`.
4. Watch `specforge_billing_webhook_error_total` and the inbox for one delivery
   cycle. If `bad_signature`/error spikes, set `LEMONSQUEEZY_WEBHOOK_SECRET` back
   to the old value and investigate.
5. Close the window: clear `LEMONSQUEEZY_WEBHOOK_SECRET_PREV=` and redeploy. The
   old secret no longer verifies.

**API key.** `LEMONSQUEEZY_API_KEY` is used only for outbound calls
(`create_checkout`, `get_order`), so there is no two-key acceptance window:
create the new key in Lemon, set `LEMONSQUEEZY_API_KEY=<new>`, redeploy, confirm
a test checkout creates and `get_order` succeeds (reconcile lane 2), then revoke
the old key in Lemon. The key is never logged (redacted by `observability.py`).

## 10. Prompt Pipeline Quality Gates And Eval Workflow

Phase 19 introduced mandatory structure gates before critic regeneration and an
offline prompt eval suite for prompt changes. The relevant files are:

- `backend/prompts/base.py` for `ASDD_PROMPT_VERSION`.
- `backend/services/pipeline/artifact_validator.py` for stage section
  contracts and zero-LLM validation before critic/regeneration.
- `backend/services/pipeline/prompt_builder.py` for upstream section extraction
  and `pipeline_upstream_section_skipped_total`.
- `backend/services/pipeline/critic.py` for the inline critic repair prompt and
  `specforge_billing_credits_critic_regen_total`.
- `harness/prompt_eval/` for golden workspaces, deterministic graders, and the
  local CLI.
- `.github/workflows/prompt-eval.yml` for the PR gate on prompt changes.

### When To Run The Eval Suite

- Any structural change to a stage prompt, including a new mandatory section or
  a changed verification checklist.
- Any change to the critic prompt template in `services/pipeline/critic.py`.
- Any change to `SECTION_CONTRACTS` in `artifact_validator.py`.

### Required Workflow For Prompt Changes

1. Branch from `main`.
2. Change the prompt, critic template, or section contract.
3. Bump `ASDD_PROMPT_VERSION` in `backend/prompts/base.py`. Use a minor bump
   for structural requirements and a patch bump for wording-only changes.
4. Run the eval locally:

   ```bash
   cd harness
   uv run python -m prompt_eval.run \
     --version <new-version> \
     --baseline <old-version> \
     --report report.md
   ```

5. Review `report.md`. Per-grader scores must be at or above baseline. Any
   accepted regression needs an owner and written release approval.
6. Open the PR. The `prompt-eval` GitHub workflow fails if files under
   `backend/prompts/**` changed without an `ASDD_PROMPT_VERSION` bump, then runs
   the same eval suite and posts the Markdown report on the PR.

### Quarterly Rebaseline

Once per quarter, refresh the eval suite so it reflects the current product:

1. Choose one representative recent workspace from production or staging.
2. Anonymize it before it enters `harness/prompt_eval/golden_workspaces/`.
3. Run the anonymization guard:

   ```bash
   cd backend
   uv run pytest ../harness/tests/backend/test_prompt_eval_anonymization.py -q
   ```

4. Run the prompt eval on `main` and save the new baseline scores:

   ```bash
   cd harness
   uv run python -m prompt_eval.run \
     --version "$(grep -oE 'asdd-v[0-9.]+' ../backend/prompts/base.py)" \
     --baseline asdd-v1.8.0 \
     --report prompt_eval_report.md
   ```

5. Attach `prompt_eval_report.md` to the quarterly review and update the
   checked-in baseline score files only after the anonymization and eval checks
   pass.

### Incident Response Signals

| Signal | Meaning | Action |
|---|---|---|
| `pipeline_validator_failures_total` increases | A stage output is missing a mandatory contract section before critic repair | Inspect the affected stage output and prompt version; pause prompt promotion if new |
| `specforge_billing_credits_critic_regen_total` spikes | Critic repair loops are consuming extra regeneration credits | Compare provider latency/errors, recent prompt changes, and validator failures |
| `pipeline_upstream_section_skipped_total` increases | The prompt builder could not find expected upstream context | Inspect the upstream stage for renamed/missing headings; check whether a prompt or parser change caused drift |
| Prompt eval CI fails | New prompt behavior regressed against baseline | Do not merge until the prompt is fixed or the regression has explicit release-owner acceptance |

---

## 11. Storyboard Operations

Storyboard generation creates a paid, versioned keynote artifact from finalised
SPEC, PLAN, HARNESS, and TASKS sources. Operators should treat Storyboard
failures like credit-affecting generation incidents: full generation and full
regeneration cost 25 credits, section regeneration costs 5 credits, and every
failed paid attempt must refund exactly once.

**Primary modules:** `backend/services/pipeline/storyboard_service.py`,
`backend/services/pipeline/storyboard_public_service.py`,
`backend/services/pipeline/storyboard_renderer.py`, and
`backend/routers/storyboards.py`.

### Fast Triage Signals

| Signal | Meaning | First action |
|---|---|---|
| `storyboard.generate_failed` log | Generation failed after a credit debit | Verify the refund ledger entry exists exactly once |
| Storyboard row stuck in `generating` | Worker died or provider call hung after reservation | Run stuck-job recovery checks below |
| `specforge_storyboard_generation_failed_total` spike | Provider, timeout, parser, or schema failures increased | Split by `action` and `error_type`; inspect provider health |
| `specforge_storyboard_credits_refunded_total` spike | Failures are refunding credits | Confirm refunds match failed Storyboard rows one-for-one |
| Ready Storyboard becomes `stale` | A source stage was refinalised | Ask owner to regenerate when they need the latest source versions |
| Public leakage report | A `/sb/` link may expose gated content | Disable, rotate, preserve evidence, and verify default privacy |

### Generation Failure And Refund Verification

Use this when a paid Storyboard attempt fails or a user reports missing credits.

1. Find the failed Storyboard row.

   ```sql
   SELECT id, workspace_id, user_id, version, status, credit_ledger_id,
          created_at, updated_at
   FROM storyboards
   WHERE id = '<storyboard_uuid>';
   ```

   Expected: `status = 'failed'` and `credit_ledger_id` is non-null for a paid
   failed attempt.

2. Confirm the failure metric and content-free log exist.

   ```promql
   increase(specforge_storyboard_generation_failed_total[30m])
   ```

   Search logs for `storyboard.generate_failed` and the `storyboard_id`. Logs
   must not contain `speaker_notes_md`, `technical_appendix_md`,
   `demo_script_md`, `content_json`, raw prompts, or source excerpts.

3. Verify the original debit and exactly one refund.

   ```sql
   WITH failed AS (
     SELECT user_id, credit_ledger_id
     FROM storyboards
     WHERE id = '<storyboard_uuid>'
   )
   SELECT cl.id, cl.amount, cl.reason, cl.created_at
   FROM credit_ledger cl
   JOIN failed f ON cl.user_id = f.user_id
   WHERE cl.id = f.credit_ledger_id
      OR cl.reason = 'refund:' || f.credit_ledger_id::text
   ORDER BY cl.created_at;
   ```

   Expected for full generation/regeneration: one `-25` debit and one `+25`
   refund. Expected for section regeneration: one `-5` debit and one `+5`
   refund.

   ```sql
   SELECT COUNT(*) AS refund_rows
   FROM credit_ledger
   WHERE user_id = '<user_uuid>'
     AND reason = 'refund:<credit_ledger_uuid>';
   ```

   Expected: `refund_rows = 1`. The unique refund reason makes retries
   idempotent; a count above one is a P1 credit-accounting incident.

4. Confirm the refund metric moved by the same credit amount.

   ```promql
   increase(specforge_storyboard_credits_refunded_total[30m])
   ```

   The `reason` label is `generation_failed` for direct LLM/schema/provider
   failures and `stuck_recovery` for recovery of old `generating` rows.

5. If the ledger is correct but the UI balance is stale, clear the user's
   credit cache by restarting the affected worker or by exercising a balance
   read after the service has invalidated `credits:<user_id>`. Do not create a
   manual refund unless the SQL above proves the refund is missing.

### Stuck `generating` Job Recovery

Storyboard reservations intentionally create a placeholder row before the LLM
call. Recovery handles rows left in `generating` for more than 30 minutes.

1. Identify old placeholders.

   ```sql
   SELECT id, workspace_id, user_id, version, credit_ledger_id, created_at,
          updated_at
   FROM storyboards
   WHERE status = 'generating'
     AND updated_at < now() - interval '30 minutes'
   ORDER BY updated_at;
   ```

2. Confirm the recovery loop is running. The normal recovery path invokes
   Storyboard recovery from the backend recovery service; look for
   `storyboard.recovered_stuck` or `storyboard.generate_failed` events.

3. In a one-off staging shell, operators can run the service helper directly:

   ```bash
   cd backend
   uv run python - <<'PY'
   import asyncio
   from database import AsyncSessionLocal
   from services.pipeline.storyboard_service import recover_stuck_storyboards

   async def main() -> None:
       async with AsyncSessionLocal() as db:
           recovered = await recover_stuck_storyboards(db)
           print(recovered)

   asyncio.run(main())
   PY
   ```

4. Re-run the refund verification query for every recovered row. Expected:
   status is `failed`, previous ready Storyboard versions remain presentable,
   and any `credit_ledger_id` has exactly one matching `refund:<ledger_id>` row.

### Stale Storyboard Recovery

When a source stage is refinalised, ready Storyboards for that workspace are
marked `stale`. The stale deck remains presentable because it is pinned to
immutable `source_stage_version_ids`; do not delete or mutate it in place.

1. Confirm the source stage was refinalised after Storyboard generation.

   ```sql
   SELECT id, stage_type, status, updated_at
   FROM stages
   WHERE workspace_id = '<workspace_uuid>'
   ORDER BY stage_type;
   ```

2. Confirm affected Storyboards are stale.

   ```sql
   SELECT id, version, status, source_stage_version_ids, updated_at
   FROM storyboards
   WHERE workspace_id = '<workspace_uuid>'
   ORDER BY version DESC;
   ```

3. Tell the owner the stale Storyboard is still safe to present, but regeneration
   is required to build a new version from the latest SPEC, PLAN, HARNESS, and
   TASKS versions. If regeneration fails, the previous ready/stale version must
   remain the latest presentable deck.

### Public Slug Disable And Rotation

Public Storyboard links are independent from workspace `/p/` public links. The
public route is `/sb/{slug}` in the frontend and `/storyboards/public/{slug}` in
the backend.

To stop a public link without changing the slug:

```bash
export API_URL=https://api.example.com
export OWNER_ACCESS_TOKEN=replace-with-owner-access-token
export STORYBOARD_ID=replace-with-storyboard-uuid
curl -X DELETE \
  -H "Authorization: Bearer $OWNER_ACCESS_TOKEN" \
  "$API_URL/storyboards/$STORYBOARD_ID/share"
```

Expected: `204 No Content`; the old `/sb/{slug}` returns not found.

To retire a known slug permanently and issue a new one:

```bash
curl -X POST \
  -H "Authorization: Bearer $OWNER_ACCESS_TOKEN" \
  "$API_URL/storyboards/$STORYBOARD_ID/share/rotate"
```

Expected: response contains a new `/sb/{slug}` URL; the old slug returns not
found immediately.

To re-enable sharing with explicit permissions:

```bash
curl -X POST \
  -H "Authorization: Bearer $OWNER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "allow_pdf_download": true,
    "allow_notes_download": false,
    "allow_appendix_download": false,
    "allow_source_layer": false
  }' \
  "$API_URL/storyboards/$STORYBOARD_ID/share"
```

Default public privacy is PDF plus demo-script only; speaker notes, appendix,
and source excerpts are hidden until the owner enables the matching permission.

### Public Data Leakage Incident Checklist

1. Disable the public Storyboard share immediately.
2. Rotate the slug so any copied URL is retired permanently.
3. Preserve the suspected slug, Storyboard ID, timestamps, request logs, and
   response samples. Do not paste generated deck content into tickets; attach it
   only in the approved incident store.
4. Verify the public response is allow-list based:

   ```bash
   export API_URL=https://api.example.com
   export STORYBOARD_SLUG=replace-with-public-slug
   curl -s "$API_URL/storyboards/public/$STORYBOARD_SLUG" | \
     python3 -m json.tool
   ```

   The response must not contain account email, user ID, workspace ID, credit
   balance, billing history, previous versions, `credit_ledger_id`, raw prompts,
   or `source_stage_version_ids`.

5. Verify default gates are closed: notes, appendix, and source excerpts are
   redacted unless the owner enabled `allow_notes_download`,
   `allow_appendix_download`, or `allow_source_layer`.
6. Confirm privacy headers on both success and not-found responses:

   ```bash
   curl -i "$API_URL/storyboards/public/$STORYBOARD_SLUG"
   ```

   Expected: `X-Robots-Tag: noindex, nofollow`, `Cache-Control: no-store,
   private`, `X-Content-Type-Options: nosniff`, and a CSP with
   `frame-ancestors 'none'`.
7. File a security incident if any private field or gated content is exposed by
   default. Keep sharing disabled until the fix, tests, and release gate pass.

---

## 12. GitHub Living Integration — App, Worker & Webhook Ops

Operational procedures for the Phase 21 GitHub Living System of Record: the
SpecForge **GitHub App** identity, the durable **arq worker** that runs all
GitHub I/O off the request path, and the signature-verified **webhook** that
flows repository events back into SpecForge.

**Architecture recap (where things run):**

- **API process** (`web` in `Procfile`, `api` in `docker-compose.yml`) accepts
  the export/sync/increment requests, owns migrations, and **enqueues** jobs —
  it never blocks on GitHub.
- **Worker process** (`worker: arq worker.WorkerSettings` in `Procfile`, the
  `worker` service in `docker-compose.yml`) drains the arq queue on the shared
  Redis and performs every GitHub call. Jobs: `export_push`, `reconcile_event`,
  `backfill_repo`, `increment_push`, `projects_sync`, `pr_check`, plus the
  periodic `reconcile_drift` cron.
- **Config:** the App is enabled when `GITHUB_APP_ID` + `GITHUB_APP_SLUG` are
  set. In production, `validate_production_settings()` additionally requires
  `GITHUB_APP_PRIVATE_KEY` and `GITHUB_APP_WEBHOOK_SECRET` (see `config.py`).
  The private key lives in the secret manager — **never** in the DB.

**Endpoints (all on already-registered routers):**

- `POST /integrations/github/webhook` — inbound GitHub deliveries (HMAC-verified,
  CSRF- and rate-limit-exempt).
- `GET /workspaces/{id}/sync` — live task-completion + drift state.
- `POST /workspaces/{id}/sync/resync` — re-push changed tasks' issues (202).
- `POST /workspaces/{id}/sync/backfill` — recover missed events (202).
- `POST /workspaces/{id}/export/github` — enqueue an export (202).
- `GET|POST /workspaces/{id}/increments`, `GET|POST /workspaces/{id}/ideas`.

---

### §12.1 — GitHub App Private-Key Rotation

**Impact:** `GITHUB_APP_PRIVATE_KEY` is the RS256 PEM that signs the short-lived
App JWT (`iss = GITHUB_APP_ID`, `exp ≤ 600s`). The JWT is exchanged for
per-installation access tokens. Rotating it invalidates the old key for **new**
JWT signing immediately; already-minted installation tokens keep working until
their own (short) TTL expires. There is no two-key window for the App private
key — GitHub holds the matching public key, so the new key is live the moment
you generate it on GitHub.

**Rotation steps:**

1. In the GitHub App settings (`https://github.com/settings/apps/<slug>` or the
   org equivalent), generate a **new** private key. GitHub lets multiple keys
   coexist, so generate before deleting.
2. Store the new PEM in the secret manager and update `GITHUB_APP_PRIVATE_KEY`
   in the Railway environment (both the `web` and `worker` services share it).
3. Redeploy. The next App-JWT mint uses the new key. Confirm token mints still
   succeed:

   ```bash
   # specforge_github_token_mint_total should keep incrementing with no rise in
   # webhook_failed / 401-driven re-mints.
   curl -s -H "Authorization: Bearer $METRICS_TOKEN" "$API_URL/metrics" \
     | grep -E 'specforge_github_token_mint_total'
   ```

4. Once mints are healthy, **delete the old key** in the GitHub App settings.

**Verification:** trigger any sync (`POST /workspaces/{id}/sync/backfill`) and
confirm the worker logs `github.token.minted` (never the token value) and the
job completes.

**Rollback:** the old key is still valid on GitHub until you delete it in step 4
— revert `GITHUB_APP_PRIVATE_KEY` to the previous PEM and redeploy.

---

### §12.2 — Webhook Secret Rotation (Two-Secret Window)

**Impact:** `GITHUB_APP_WEBHOOK_SECRET` signs the `X-Hub-Signature-256` HMAC on
every inbound delivery. The webhook handler verifies the signature **before**
any DB/queue work, in constant time, against **both** the current and previous
secret so a rotation never drops deliveries.

The accepted-secrets list is `settings.github_app_webhook_secrets` =
`[GITHUB_APP_WEBHOOK_SECRET, GITHUB_APP_WEBHOOK_SECRET_PREV]` (empty entries are
ignored). This is the two-secret window.

**Rotation steps:**

1. Generate a new secret:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Move the **current** secret into the previous slot and set the new one as
   current, then redeploy `web` (the worker does not verify signatures):

   ```
   GITHUB_APP_WEBHOOK_SECRET=<new_secret>          # signs nothing yet — accepted
   GITHUB_APP_WEBHOOK_SECRET_PREV=<old_secret>     # still accepted during window
   ```

3. Update the **GitHub App's** webhook secret to `<new_secret>`. From this
   moment GitHub signs with the new secret; SpecForge accepts both, so no
   delivery is rejected.
4. Watch the verify/fail metrics through at least one delivery cycle:

   ```bash
   curl -s -H "Authorization: Bearer $METRICS_TOKEN" "$API_URL/metrics" \
     | grep -E 'specforge_github_webhook_(verified|failed)_total'
   ```

   `verified` should keep climbing; `failed` must stay flat. A spike in
   `failed` means GitHub is still signing with the old secret or the env was
   mis-set — do **not** remove `*_PREV` yet.
5. After the window (recommend ≥ 24h, or once you have confirmed deliveries
   verifying against the new secret), clear the previous slot and redeploy:

   ```
   GITHUB_APP_WEBHOOK_SECRET_PREV=
   ```

**Rollback:** if `failed` spikes, set `GITHUB_APP_WEBHOOK_SECRET` back to the
old value and revert the GitHub App secret; the previous slot already accepts
it, so recovery is immediate.

---

### §12.3 — Installation-Token Re-Mint

Installation tokens are short-TTL, namespaced, never logged, and Fernet-encrypted
at rest when Redis is shared. The client resolves a token **per request** via the
Redis-cached `TokenProvider` and **re-mints once on a 401** automatically — no
operator action is needed for the normal expiry path.

**Force a re-mint** (e.g. after a suspected cache poisoning, or a manual GitHub
permission change):

```bash
# The token cache key is namespaced per installation (gh:inst_token:{id}) and
# Fernet-encrypted at rest. Drop it so the next call re-mints. (Never print the
# value — it is an installation credential.)
redis-cli --scan --pattern 'gh:inst_token:*' | xargs -r redis-cli del
```

Then trigger any sync; confirm `specforge_github_token_mint_total` increments
(its `source` label distinguishes a cache hit from a fresh mint) and the job
succeeds. A persistent re-mint storm (many mints per
minute, rising `webhook_failed`/job retries) points at a **revoked installation
or an invalid App private key** — check §12.1 and the install's status on GitHub.

---

### §12.4 — Dead-Letter Inspection & Manual Replay

Every GitHub job runs with bounded retries + exponential backoff + jitter. After
the max-attempt cap it is **dead-lettered** (counted by
`specforge_github_job_deadlettered_total`) and alerts fire. Jobs are idempotent
and checkpointed (inbound keyed by `X-GitHub-Delivery`, outbound by
`push_id`/`increment_id`), so a replay never duplicates side effects.

**Alert trigger:** `increase(specforge_github_job_deadlettered_total[15m]) > 0`.

**Inspect the dead-letter queue (arq stores results/failures in Redis):**

```bash
# List arq result keys; failed jobs carry the exception in their result blob.
redis-cli --scan --pattern 'arq:result:*' | head -50

# Inspect one job's stored result (job_id == push_id for export jobs):
redis-cli get "arq:result:<job_id>"
```

**Manual replay** — re-enqueue the same job by its stable key. Because the job_id
is the `push_id`/`increment_id`/`delivery_id`, re-submitting dedups and resumes
from the last completed checkpoint:

```bash
cd backend
# Re-enqueue an export/resync by push_id:
uv run python -c "
import asyncio
from services.queue import enqueue
asyncio.run(enqueue('export_push', '<push_id>', '<repo_name>', 'private', job_id='<push_id>'))
"
```

For an inbound delivery, prefer **backfill** (§12.6) over replaying a raw webhook
— backfill reconstructs state from the issues API and is out-of-order safe.

**After replay:** confirm the push/issue reaches `completed`/`done` and the
dead-letter counter stops rising.

---

### §12.5 — "Sync Paused" / Circuit-Breaker Recovery

The shared httpx client has bounded timeouts, a bounded pool, and a **circuit
breaker** that trips on a sustained GitHub outage. While open, jobs raise
`GitHubUnavailableError`, the push stays **live** (non-`failed`, so
`find_live_push` still sees it), the worker requeues, and the UI surfaces
**"Sync paused — reconnect GitHub"**. This is *not* a failure state — no push is
marked `failed` and no credit is lost.

**Diagnose:**

```bash
# Throttle/breaker pressure shows up here:
curl -s -H "Authorization: Bearer $METRICS_TOKEN" "$API_URL/metrics" \
  | grep -E 'specforge_github_throttled_total|specforge_github_queue_depth'

# Worker logs the breaker-open event:
#   github.sync.paused  (and the LLM-style breaker open/close transitions)
```

**Recovery is automatic** once GitHub returns: the breaker half-opens, a probe
succeeds, and queued jobs drain. Operator actions:

1. Confirm GitHub itself is healthy (`https://www.githubstatus.com`).
2. If the queue is backing up, confirm the worker process is alive
   (`Procfile` `worker`; `docker compose ps worker`) and Redis is reachable.
3. If a single installation is the cause (its `Retry-After` keeps deferring),
   the per-installation governor is doing its job — fairness/bulkheads keep
   other tenants flowing; no action needed beyond monitoring.

Do **not** manually mark pushes `failed` to "clear" a paused state — that drops
the live push and breaks resume. Let the breaker and requeue recover.

---

### §12.6 — Backfill Trigger (Recover Missed Events)

Backfill reconciles a repo's task states from GitHub's **issues API**
(`issues?state=all&since=`), filtering out rows carrying a `pull_request` key. It
recovers closures/reopens missed while the worker was down and is idempotent with
the webhook path (a webhook-set `pr_merge` is never downgraded to `manual`).
Transitions are gated on event timestamp, so backfill is out-of-order safe.

**Trigger for one workspace (returns 202, runs on the worker):**

```bash
curl -i -X POST "$API_URL/workspaces/$WORKSPACE_ID/sync/backfill" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H "X-CSRF-Token: $CSRF"
```

The periodic `reconcile_drift` cron also enqueues `backfill_repo` for every
`completed` push and **fails stuck `pending` pushes whose arq job no longer
exists** (a crashed export), so the repo becomes re-exportable. To force the
sweep immediately:

```bash
cd backend
uv run python -c "
import asyncio
from services.queue import enqueue
asyncio.run(enqueue('reconcile_drift', job_id='reconcile_drift:manual'))
"
```

**Verify:** `GET /workspaces/{id}/sync` reflects the corrected task states and
`specforge_github_reconcile_lag_seconds` returns to baseline.

---

### §12.7 — Increment-Push Troubleshooting

An increment is an additive delta on top of the shipped baseline. `increment_push`
creates **new issues only** for new tasks (content-derived `task_ref` dedups —
same ref → same issue, no duplicate), updates changed tasks' issues, closes
obsoleted issues with a note, and creates one milestone + one PR per increment.

**Common symptoms & fixes:**

| Symptom | Likely cause | Action |
|---|---|---|
| Increment stuck in `pending` | worker down or job dead-lettered | §12.4 — inspect & replay `increment_push <increment_id>` (idempotent) |
| Duplicate issues for the "same" task | `task_ref` churn (title changed) | Expected if the task content genuinely changed; otherwise check `compute_task_ref` inputs — re-export updates in place by `task_ref` |
| New issues land outside the milestone | milestone create raced/failed | Replay the job; milestone creation is idempotent and re-links existing issues |
| `409` on a content write | concurrent write / stale SHA | Handled automatically (refetch-SHA-and-retry) + per-repo write serialization; a persistent 409 means another writer — confirm only the worker writes |
| `403` on `.github/workflows/*` | App lacks `Workflows: write` | Surfaced as a distinct actionable error; grant the permission on the installation and re-run |

**Inspect an increment's push ledger:**

```sql
SELECT ip.id, ip.status, ip.increment_id, ip.branch_name, ip.pr_number
FROM integration_pushes ip
WHERE ip.increment_id = '<increment_id>';

SELECT task_ref, state, external_issue_number, done_via
FROM integration_push_tasks
WHERE increment_id = '<increment_id>'
ORDER BY external_issue_number;
```

Re-running the push after any fix is always safe — the job resumes from the
ledger and never re-creates an issue already recorded in
`integration_push_tasks`.
