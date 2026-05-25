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
