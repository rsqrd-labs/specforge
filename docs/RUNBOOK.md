# SpecForge Operations Runbook

Operational procedures for SpecForge V1 on-call engineers and SREs.  
Covers: circuit breaker, finalise race incident response, credit refund procedures, auth cache limitations, and dependency version management.

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

---

## 1. LLM Circuit Breaker

**Reference:** CF-2, T-197, T-215  
**Module:** `backend/services/llm/provider_status.py`, `backend/services/llm/gateway.py`

### What It Is

The LLM circuit breaker tracks consecutive failures per provider using `_FAILURES` (a module-level dict in `provider_status.py`). After `_UNHEALTHY_FAILURE_THRESHOLD` (3) consecutive failures within a 600-second window, `can_route(provider)` returns `False` and `gateway.get_llm()` raises `HTTPException(503)` for all subsequent requests to that provider.

### Detecting a Circuit Activation

**Prometheus metric:** `specforge_llm_circuit_rejections_total{provider="<provider>"}`

> **Alert:** if `specforge_llm_circuit_rejections_total > 0` — a circuit breaker has
> activated. Check provider health via `GET /providers/{id}/health`.

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
- Health-check probes (`GET /providers/{id}/health`) are **not** blocked — they bypass the circuit via `bypass_circuit=True` and can detect recovery.
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

Returns `{"status": "ok", "db": "ok", "redis": "ok"}` or HTTP 503 with failing components.

### LLM Provider Health

```
GET /providers/{provider_id}/health
```

Triggers a live health probe to the provider (bypasses the circuit breaker). Returns the current health status, failure count, and circuit state.

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

## 9. Billing Alerts

The following Grafana alert rules correspond to the Prometheus counters defined in `services/observability.py` (Phase 18 — T-236).

| Alert | Condition | Severity | Action |
|---|---|---|---|
| BillingWebhookErrorRate | `rate(specforge_billing_webhook_error_total[5m]) > 0` | Warning | Check logs for `billing.webhook_handle_failed`; inspect Stripe dashboard for event details; delete the `stripe_webhook_events` row to replay the event |
| BillingCheckoutDropped | `checkout.session.completed` events stagnant while `checkout_created` rising (5-min window) | Warning | Check Stripe webhook delivery logs; verify `/billing/webhook` is reachable and returning 200; inspect CSRF/rate-limit exemptions |
| BillingDisputeCreated | `specforge_billing_pack_disputed_total` increments | Warning | Review Stripe dispute in the dashboard; contact user if fraudulent; credits already revoked automatically |
| BillingWebhookDuplicate | `rate(specforge_billing_webhook_duplicate_total[1h]) > 10` | Info | Normal if Stripe is retrying; investigate if above 100/hour — may indicate the webhook endpoint is failing silently after `already_processed` return |
