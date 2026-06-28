# SpecForge Scalability Audit & Remediation Plan

**Date:** 2026-06-28
**Scope:** End-to-end audit of the ability to serve **many concurrent users and their
generations** without features breaking under real production load.
**Method:** Code-path audit of the process/concurrency model, DB connection lifecycle,
the generation pipeline, Redis usage, the background worker, rate limiting, the data
layer, and a per-feature failure-mode pass. Findings are ordered by **which resource
exhausts first under N concurrent generations and the blast radius when it does.**

> **Audit note (intellectual honesty).** The first hypothesis — that each generation
> pins DB connections across its multi-minute stream — was **investigated and
> disproven** in code (see §1, "Verified sound"). The team already engineered that away.
> The real first-to-fail resources are **provider rate limits** and **unbounded
> admission**, not database connections. The plan reflects the verified reality.

---

## 0. Executive summary

The system is well-engineered for *correctness* under concurrency and, notably, for **DB
connection discipline** — the pipeline deliberately releases its pooled connection during
the LLM stream, so generations do **not** pin connections for their duration. The gaps
are about **admission and external limits**, not internal connection holding.

**What actually fails first under many concurrent generations:**

1. **No admission control** anywhere on the generation path — nothing caps concurrent
   generations per user or per process. Unbounded concurrent generations saturate the
   two event loops, fan out unbounded background tasks (eval + critic + verifier), and
   pile onto the shared provider API key.
2. **The shared platform LLM key has an account-level rate ceiling.** At scale this is
   the *binding* constraint: provider **429s** arrive long before event-loop or DB
   saturation — and the "retry once on the mid tier" behavior **amplifies** load exactly
   when throttled.
3. **Horizontal scale-out is gated by the Postgres connection footprint**, not by
   per-generation holding. Each process keeps up to `pool_size`(20)+`overflow`(10)=**30**
   connections open under load; 2 API workers + 1 worker ≈ **90**, already crowding a
   **default managed-Postgres limit of 100 before any scale-out.** Adding instances
   multiplies it.

**Good news that shapes the plan:** because connections are *not* held across idle
streams (verified below), a **transaction-mode pooler (PgBouncer) is already
compatible** — the usual blocker for it does not exist here. The horizontal-scale-out
path is therefore short.

There is no precise "cliff" number to quote for the DB (the earlier 15-per-worker figure
was based on the disproven holding hypothesis); the binding ceiling is provider
throughput, which **must be measured** (see §6), then enforced as an admission budget.

---

## 1. Verified sound — the connection-discipline path (do **not** change)

This was the prime suspect and is the load-bearing thing to get right, so it's documented
in full rather than just listed:

- **The pipeline releases its DB connection during the stream.** After loading
  `stage`/`workspace`, the pipeline **commits immediately** to return the pooled
  connection *before* the multi-minute LLM stream, with an explicit comment to that
  effect ([stage_manager.py:2827-2840](../backend/services/pipeline/stage_manager.py#L2827-L2840)).
  With `expire_on_commit=False` ([database.py:25](../backend/database.py#L25)) the loaded
  scalars stay readable with no further IO; the next write auto-begins a fresh, short
  transaction. **A generation holds ≈0 connections during its dominant (streaming)
  phase.**
- **The request-scoped session also releases.** `Depends(get_db)` commits during
  preflight ([stage_manager.py:2702](../backend/services/pipeline/stage_manager.py#L2702)),
  returning its connection to the pool; the pump loop afterward only drains an
  asyncio.Queue and reads already-loaded scalars (`stage.type`) — no reacquire.
- **Liveness uses its own short session.** The recovery-sweep heartbeat opens a fresh
  `AsyncSessionLocal` every **30s** (`_STAGE_HEARTBEAT_DB_SECONDS`,
  [stage_manager.py:258,737](../backend/services/pipeline/stage_manager.py#L258)),
  a sub-millisecond `UPDATE … updated_at` + commit — trivial connection churn even at
  hundreds of concurrent generations.

**Implication:** DB connections are consumed in brief bursts (preflight, 30s heartbeats,
final persist), not held for minutes. The pool can absorb **far** more concurrent
generations than the naive `30 / per-gen` arithmetic suggests. This area needs no work;
the residual DB concern is purely the *idle pool footprint × instance count* for
horizontal scale-out (§2, F3).

---

## 2. Tier 1 — First-to-fail under concurrent load (P0)

### F1. The generation path has **no admission control**

**Current behavior.** `POST /stages/{id}/generate` and `/regenerate`
([routers/stage.py:179-206](../backend/routers/stage.py#L179-L206)) are gated only by
credit balance (`require_credits(10)`) and the per-stage `in_progress` status guard. The
`RateLimitMiddleware` has tiers for login, GitHub export/sync/increment, clarify, PDF,
public view, share, billing checkout, and *storyboard* generation
([middleware/rate_limit.py:34-178](../backend/middleware/rate_limit.py#L34-L178)) — but
**no tier for core stage generation.** The only `Semaphore` in the pipeline
([stage_manager.py:2097](../backend/services/pipeline/stage_manager.py#L2097)) bounds
*parallel chunk* concurrency *within a single generation*.

**Failure mode under load.** Unbounded concurrent generations across stages/workspaces.
The cost is **not** DB connections (§1) — it is:
- **Event-loop saturation** on only 2 workers (F4): each generation runs a pipeline
  coroutine + heartbeat, and any inline CPU step (F5) stalls every peer on that worker.
- **Unbounded background fan-out** (F6): each generation, post-`done`, spawns eval +
  critic (+ verifier) tasks held in module-level sets with no global cap.
- **Provider-budget exhaustion** (F10): all generations share one platform key.
There is no backpressure — the system accepts work it cannot serve and degrades globally
instead of shedding the marginal request.

**Fix.**
1. **Per-process generation semaphore** sized from a measured safe concurrency (governed
   primarily by the provider budget, F10). When full, **fast-fail with HTTP 503 +
   `Retry-After`** rather than admitting unbounded work.
2. **Per-user concurrent-generation cap** (Redis counter; incr on start / decr on
   terminal event with a TTL self-heal) — e.g. 2–3 in-flight per user.
3. **Generation rate-limit tier** in `RateLimitMiddleware` (generations/user/minute),
   mirroring the storyboard tier that already exists.

**Blocks horizontal scale-out?** No — it's the safety valve that keeps one instance from
self-immolating and is where the provider budget (F10) is enforced.

---

### F2. The shared platform LLM key is an **un-budgeted rate ceiling** — the true binding constraint

**Current behavior (verified in code, not from CLAUDE.md).** Every LLM call resolves its
key through `gateway._provider_api_key()`, which reads **only** `os.getenv(...)` / `settings`
— i.e. the **single platform key per provider**. There is exactly one
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` and no key pool. Critically,
**the BYO / "users connect their own key" capability described in CLAUDE.md does not
exist in the running code** — this is a doc/reality gap, not a fallback path:
- `services/security/key_vault.py` says verbatim *"user-provided API keys are out of
  scope for V1 … Ready for V2."*
- there is **no `ApiKey` model**, no key-storage endpoint in `routers/providers.py`, and
  **no `decrypt` / `key_vault` call anywhere in `services/pipeline/` or `services/llm/`**.

So **100% of every user's generations funnel through one org account per provider.** There
is no per-user escape valve relieving that ceiling today.

**Three multipliers make the single key hotter than "one call per generation":**
1. **Per-generation fan-out.** Each user generation also drives a **critic judge** call
   and (sampled) an **eval** on the same platform key; storyboard/increment/clarifier add
   more. Moving the critic off the *critical path* (async-advisory) does **not** take it
   off the *rate ceiling* — it still competes for the same org TPM. Effective load is
   several provider calls per generation.
2. **Anthropic is doubly loaded.** `gateway._DEFAULT_JUDGE_PROVIDER = "anthropic"`, so the
   critic/judge lands on Anthropic **even for OpenAI/Google workspaces**. The Anthropic
   org limit is simultaneously a generation provider *and* the universal judge — it will
   hit its ceiling first.
3. **429 → amplification (confirmed in code).** A provider 429 is a `RateLimitError`, a
   subclass of `anthropic.APIError`, which the adapter wraps into a generic
   `ProviderError` (`anthropic_adapter.py:83-84`) — **indistinguishable from any other
   failure.** The stage retry (`stage_manager.py:2980-2992`) then escalates that retry to
   the **mid tier — a bigger, more-token-hungry model — with no backoff and no
   `Retry-After`**, firing a *larger* request at the *same throttled org*. Under load this
   turns throttling into a thundering herd.

**Failure mode under load.** At hundreds of concurrent generations on one key,
Anthropic/OpenAI/Google enforce account-level **RPM/TPM / concurrent-request** caps →
**429/529s**, amplified by (3), surfacing as failed generations — and this bites **before**
CPU or DB limits. For an audit about concurrent generations, **this is the real ceiling.**

**Fix (the key-level scaling levers, ordered cheapest → highest-leverage).**
1. **429-aware retry (cheapest, do first).** Classify rate-limit/overload distinctly from
   other `ProviderError`s; on a 429 **do not escalate tier** — honor `Retry-After`,
   exponential backoff + jitter, bounded retries. Tier escalation is for *quality*
   failures, not throughput failures. This stops the amplification without new infra.
2. **Global provider budget in Redis**, feeding the F1 admission valve so the 503 trips on
   *our* budget, not the provider's 429. **RPM / in-flight-concurrency is the easy first
   step** (count requests — reuse the existing Lua sliding-window). A true **TPM budget is
   harder**: tokens aren't known until after the call, so it needs pre-call estimation
   (from `max_tokens`/output-budget) **plus** post-call reconciliation. (Prompt caching,
   already shipped, is a partial mitigation — it already trims input-token pressure.)
3. **Key pool — but only across separate orgs/projects.** *Adding keys multiplies the
   ceiling only if each key maps to a separate org/project/billing account with its own
   rate bucket.* N keys under the **same** org share **one** limit and buy nothing. The
   gateway is already architected for this: adapters are cached and keyed by
   `_secret_fingerprint(api_key)`, so N keys cleanly yield N adapters/pools — the missing
   piece is a least-loaded/round-robin **selector** + per-key health/budget in Redis.
4. **Cross-provider failover** for the same operation (3 adapters + a `cross_provider_fallback`
   flag already exist): saturated Anthropic → OpenAI → Google multiplies aggregate
   throughput.
5. **BYO keys (V2)** — finish the wiring the vault was built for. A user on their own key
   consumes their *own* org limit, removing them from the shared ceiling entirely;
   highest-leverage long-term lever.
6. **Batch API** for non-interactive work (`batch_executor.py` + `llm_batch_job` exist):
   batch traffic is metered separately from real-time TPM, freeing interactive headroom.

**Key-level scaling ladder (summary).**

| # | Lever | Effort | Multiplies ceiling? | Why / caveat |
|---|-------|--------|---------------------|--------------|
| 1 | 429-aware retry (no tier-escalate on rate-limit) | XS (code) | No — stops *shrinking* it | Kills the amplification; honor `Retry-After` |
| 2 | Redis RPM/in-flight budget → F1 valve | S | No — sheds gracefully | Reuse existing Lua sliding-window |
| 2b | Redis **TPM** budget | M | No — sheds gracefully | Needs pre-call estimate + post-call reconcile |
| 3 | Key pool | M | **Yes, ×N** | **Only if N separate orgs/projects**; same-org = ×1 |
| 4 | Cross-provider failover | S–M | **Yes** | Adapters + flag already exist |
| 5 | BYO keys (V2) | L | **Yes** (off-loads to user orgs) | Highest long-term leverage; vault seam exists |
| 6 | Batch API for evals/critic | M | Frees real-time headroom | Batch metered separately from real-time TPM |

**Must-confirm with ops (not in code):** the actual per-org **RPM / TPM / concurrent-request**
limits for each provider account. Everything above sizes off these — measure, don't guess.

**Blocks horizontal scale-out?** Yes, in effect — more instances don't help if they all
share one throttled key. The budget must be *global* (Redis-coordinated), not per-process
(today's only protection, the circuit breaker, is per-worker-process and purely reactive —
it trips *after* 429s, and needs ~3× the failures to trip across 3 processes).

---

## 3. Tier 2 — Horizontal scale-out & secondary exhaustion (P1)

### F3. Postgres connection footprint × instance count (pooler — now *unblocked*)

**Current behavior.** Under load each process keeps up to **30** connections open
(`db_pool_size=20`+`db_max_overflow=10`, [database.py:14-20](../backend/database.py#L14-L20),
[config.py:62-63](../backend/config.py#L62-L63); QueuePool keeps connections open on
return, `pool_recycle=3600`). 2 API workers + 1 worker ≈ **90**, crowding a **default
`max_connections` of 100 before any scale-out.** Scaling to 4 API instances + worker ⇒
4×30 + 30 = **150 > 100** ⇒ `FATAL: too many connections`.

> ⚠️ **Must-confirm deploy fact (not in code):** the real `max_connections` on the
> Railway/managed Postgres. Size the pool math against it; the *shape* holds regardless.

**Fix.**
1. **PgBouncer transaction pooling** (or the managed pooler) in front of Postgres.
   **This is unblocked** — §1 confirms connections aren't held across idle streams, so
   transaction-mode pooling is compatible today. Sanity-check only that no code relies on
   session-scoped server state across statements; `credit_service`'s `FOR UPDATE` runs
   within a single transaction and is fine
   ([credit_service.py:88-95](../backend/services/credit_service.py#L88-L95)).
2. Make `db_pool_size`/`db_max_overflow`/`pool_timeout` **env-driven**; set a small
   `pool_timeout` (~5s) so a saturated pool **fast-fails** instead of stalling 30s.
3. Add `connect_args` server guards: `statement_timeout` and
   `idle_in_transaction_session_timeout` (defense-in-depth).

**Blocks horizontal scale-out?** This *is* the enabler — and it's a short add given §1.

---

### F4. Only 2 uvicorn workers, hardcoded

`gunicorn ... --workers 2` is a literal, not `WEB_CONCURRENCY`/CPU-derived
([Procfile:1](../backend/Procfile#L1)). Two event loops serve the whole API; any
event-loop stall (F5) halves capacity. **Fix:** drive from `WEB_CONCURRENCY`
(≈`2*cores+1` for I/O-bound async). **Sequence after F3** — more workers × 30 connections
worsens the footprint until the pooler lands.

---

### F5. Single worker process is a shared bottleneck for *all* async work

**Current behavior.** One arq worker (`max_jobs=20`, [worker.py:50](../backend/worker.py#L50))
runs everything off the request path: GitHub export/reconcile/backfill/increment/
projects/PR-check, the **billing webhook inbox** processor, LLM eval-batch submit/collect,
and all crons. A GitHub export can run up to **1800s** ([worker.py:52](../backend/worker.py#L52)).

**Failure mode.** These contend for one process's 20 slots and one DB pool. A spike of
GitHub exports can starve the **billing webhook inbox**, delaying credit grants users
already *paid for*. Queue depth grows unbounded (only the `GITHUB_QUEUE_DEPTH` gauge gives
visibility, [worker.py:303-309](../backend/worker.py#L303-L309)).

**Fix.** (1) Run **N stateless worker replicas** (jobs are idempotent/checkpointed);
verify cron leadership so crons fire once. (2) **Separate live queues** — latency-
sensitive `billing`/`pr_check` vs bulk `export`/`backfill`/`increment` — so an export
storm can't delay a paid grant (dead-letter queues are already separated; extend the same
split to live queues). (3) Alert on per-queue depth + oldest-job age. (4) Implement the
noted per-installation fairness governor (T-274).

---

### F6. Unbounded in-memory background-task fan-out

Four module-level sets retain detached tasks: `_BACKGROUND_PIPELINE_TASKS`,
`_BACKGROUND_EVAL_TASKS`, `_BACKGROUND_CRITIC_TASKS`, `_BACKGROUND_VERIFIER_TASKS`
([stage_manager.py:315-348](../backend/services/pipeline/stage_manager.py#L315-L348)).
They correctly keep detached tasks alive across client disconnect, but are **unbounded**.
A burst spawns an unbounded fan of eval+critic+verifier tasks — each opens its own short
DB session — landing right at peak load and a slow memory-growth vector if a task ever
fails to self-remove. **Fix:** gate pipeline-task creation behind the F1 semaphore, and
give eval+critic their **own bounded** semaphore/executor so post-`done` work can't starve
live streams. Export each set's `len()` as a gauge.

---

## 4. Tier 3 — Tail latency & polish (P2)

### F7. CPU-bound work runs inline on the event loop
On 2 async workers, sync CPU work blocks every peer coroutine on that worker.
**`bleach.clean` runs inline** over LLM output (which can be multi-KB):
`sanitize_text` on persist ([stage_manager.py:4174](../backend/services/pipeline/stage_manager.py#L4174)),
refine ([3796-3797](../backend/services/pipeline/stage_manager.py#L3796-L3797)),
[sanitizer.py:15](../backend/services/security/sanitizer.py#L15); plus full-doc regex
validators (`artifact_validator`, `output_validator`, `prompt_guard`) and difflib in
`diff_engine`. **Already correct (credit):** WeasyPrint PDF is dispatched to a bounded
`ThreadPoolExecutor(max_workers=2)` ([pdf_export_service.py:55-56,309](../backend/services/pipeline/pdf_export_service.py#L49-L56));
Langfuse flush/auth use `asyncio.to_thread`. **Fix:** move sanitize-on-persist (the prime
suspect — every generation, largest payload) and full-doc regex to `asyncio.to_thread`;
measure event-loop lag to prioritize the rest.

### F8. Shared Redis client is unbounded and lacks health/keepalive
`Redis.from_url(..., decode_responses=True)` with no `max_connections`,
`health_check_interval`, or `socket_keepalive` ([database.py:79](../backend/database.py#L79),
[main.py:99-103](../backend/main.py#L99)). Every request touches Redis (rate limiting,
credit/generation cache), so a burst can balloon connections toward Redis `maxclients`,
and stale connections after a failover surface as errors. **Fix:** bound the pool, set
`health_check_interval=30`, `socket_keepalive=True`, small `socket_timeout`.

### F9. No fast-fail / server-side DB timeouts
`pool_timeout` defaults to 30s; no `statement_timeout` / `idle_in_transaction_session_timeout`
([database.py:14-20](../backend/database.py#L14-L20)). A cheap one-line mitigation that
improves blast radius; folded into the F3 fix but worth doing immediately.

---

## 5. Per-feature load-bearing failure-mode pass

Per the brief ("no feature breaks under load"), one explicit pass per feature:

| Feature | Load-bearing failure mode | Status / action |
|---|---|---|
| **Auth / login** | Shares the API DB pool; if the pool footprint (F3) exhausts Postgres, login fails fleet-wide. Login rate limits are Redis-backed and sound. | Mitigated by F3 + pooler. |
| **Billing webhook inbox** | Inbox commit is on the fast HTTP path (correct); processing is on the single worker (F5). A GitHub-job storm **delays paid credit grants**; 60s sweep recovers eventually. | Fix via F5 queue separation. Grant idempotency + reconcile crons are sound. |
| **GitHub sync** | Single-worker queue depth (F5); each export up to 1800s. Idempotent/checkpointed/dead-lettered — correct but not fast under burst. | F5; implement per-installation governor (T-274). |
| **PDF export** | Bounded executor (max_workers=2) + `_PDF_EXPORT_LIMIT=10` tier — CPU contained but **2 slots is low**. | Make executor size env-driven; consider offloading to the worker. |
| **Public share `/p/:slug`** | Unauthenticated; `_PUBLIC_VIEW_LIMIT=120/min`/IP. DB read per hit → shares the pool. | Add a short Redis cache for public payloads to keep scrapers off the pool. |
| **Storyboard generation** | Own rate tier (3/hr) + cheap-primary routing — **best-governed generation path.** Still shares the platform key (F2). | Inherits F1/F2; otherwise sound. |
| **Credits / ledger** | `SELECT … FOR UPDATE`, consistent lock ordering ([credit_service.py:88-95,150,247](../backend/services/credit_service.py#L88-L95)) — race-safe; per-user row locks (low per-user throughput). | Sound. |
| **SSE / proxy** | End-to-end heartbeats keep proxies open ([stage_manager.py:2707-2772](../backend/services/pipeline/stage_manager.py#L2707-L2772)); watchdog liveness on events not tokens; connection released during stream (§1). | Sound — exemplary. |
| **Recovery sweep** | Leader-locked Redis NX ([stage_manager.py:1023](../backend/services/pipeline/stage_manager.py#L1023)); 60s; filters `status='in_progress'` (rare) via `ix_stages_status`. | Sound. Minor: a **partial index** `WHERE status='in_progress'` if `stages` grows large. |

---

## 6. Confirmed-sound — do **not** churn

- **Connection discipline during streaming** (§1) — verified, exemplary.
- **Redis sliding-window rate limiting** — atomic Lua, distributed, local fallback
  ([rate_limit.py:187-313](../backend/middleware/rate_limit.py#L187-L313)).
- **Leader-locked recovery loop** — Redis NX, single-runner across instances.
- **LRU-bounded, TTL-refreshed LLM adapter cache** — HTTP clients reused, bounded
  ([gateway.py:28-112](../backend/services/llm/gateway.py#L28-L112)).
- **Idempotent, checkpointed, dead-lettered jobs** — keyed by delivery/push/increment id.
- **Indexed hot foreign keys** — `ix_stages_workspace_id`, `ix_workspaces_user_id`,
  `ix_stage_versions_stage_id`, `ix_credit_ledger_user_id`, `ix_stages_status`,
  `ix_stages_updated_at` (migration `0002`). Dashboard uses `selectinload(Workspace.stages)`
  + batched coverage summaries — **no N+1.**
- **Charge-on-completion + recovery safety net** — crashed pipeline refunds + resets.
- **Bounded provider HTTP clients** — `httpx.Limits` on GitHub (20) and Lemon (10).

---

## 7. Remediation roadmap (sequenced — order is load-bearing)

> **P0 status: IMPLEMENTED (2026-06-28).** All four P0 items below are shipped and
> tested (`test_admission.py`, `test_provider_rate_limit.py`, generation-tier cases in
> `test_rate_limit.py`). Key implementation facts:
> - **F2 429-aware retry** is live and ON by default: a provider 429/529/503 is wrapped
>   as `ProviderRateLimitError` (`services/llm/base.py`), retried **in place on the same
>   tier** (honor `Retry-After` → exponential backoff + jitter, bounded by
>   `provider_rate_limit_max_retries`), **never escalated** — the amplification (§F2.3) is
>   gone. The circuit breaker explicitly **excludes** rate-limits
>   (`provider_status.record_provider_failure`) so a 429 cannot open the circuit and
>   then hard-fail its own backoff retry. The verified-non-amplifying paths
>   (storyboard/increment/harness-patch, §"per-feature pass") surface 429s directly.
> - **F2 global provider budget** (`provider_max_inflight_generations` /
>   `_per_minute`) ships at **0 (unlimited)** — the real per-org limits must be
>   **measured** first (§6). **Scope:** the budget counts the **core generate/regenerate
>   path only** (the sole callers of `admit_generation`); other generation features are
>   governed by their own rate tiers and are not counted against it.
> - **F1 admission** (`services/pipeline/admission.py`) acquires a slot across
>   per-process → per-user (Redis lease) → per-provider budgets **after the
>   generation-cache miss** (a cache hit consumes no slot) and **before any provider
>   call**; over-budget fast-fails with a `Retry-After`. Redis budgets **fail open**;
>   the per-process limiter still applies. Because admission runs inside the already-200
>   `StreamingResponse`, an over-budget rejection surfaces as the existing
>   `rate_limit_exceeded` **SSE event** (carrying `retry_after`); the **HTTP-native 429**
>   fast-fail is the middleware generation tier, which runs before the stream starts.
> - **F8/F9** are wired through the single Redis factory (`database.build_redis_client`)
>   and the postgres-only `connect_args` guards.
>
> Remaining levers (key pool, cross-provider failover, BYO keys, batch, TPM budget) are
> P1/V2 and intentionally **not** in this P0 cut.

**P0 — survive a burst on the current fleet (days):**
1. **F2** measure the provider RPM/TPM budget; add a global (Redis-coordinated)
   provider concurrency budget + 429-aware backoff; **stop amplifying via mid-retry on
   429**.
2. **F1** admission control wired to the F2 budget: per-process semaphore + per-user cap
   + generation rate tier; 503 + `Retry-After` when over budget.
3. **F9** `pool_timeout=5s` + `statement_timeout` + `idle_in_transaction_session_timeout`.
4. **F8** bound + health-check the Redis pool.

**P1 — horizontal scale-out (1–2 weeks):**
5. **F3** PgBouncer transaction pooling (unblocked by §1); env-driven pool sizing;
   confirm real `max_connections`.
6. **F4** `WEB_CONCURRENCY`-driven worker count (after F3).
7. **F5** scale worker replicas + split fast/bulk live queues; verify cron leadership.
8. **F6** bound the eval/critic background fan-out.

> **P1 status: IMPLEMENTED.** All four P1 items are shipped and tested
> (`test_scalability_p1.py`, `test_background_tasks.py`, plus the queue/worker
> suites). Full ops in `docs/RUNBOOK.md` §15/§16. Key facts:
> - **F3** — env-driven pool sizing already shipped in P0/F9. A
>   `DB_TRANSACTION_POOLER_MODE` flag (default **off** ⇒ byte-identical) makes the
>   asyncpg engine transaction-pooler-safe (disables SQLAlchemy's **and** asyncpg's
>   prepared-statement caches + unique statement names), **validated end-to-end**
>   against a real PgBouncer (`deploy/pgbouncer/`, compose `pgbouncer` profile).
>   Server-side guards (`statement_timeout`/idle) are stripped by the pooler as
>   startup params, so in pooler mode they move to the Postgres ROLE (RUNBOOK §15).
>   SQLAlchemy **pool metrics** (`specforge_db_pool_total_open` etc.) are exported
>   for the capacity gate. `max_connections` remains a must-confirm deploy fact.
> - **F4** — worker count comes from `WEB_CONCURRENCY` via `gunicorn.conf.py`
>   (default **2**, no footprint change until the pooler lands); **no** worker
>   recycling (it would sever in-flight SSE streams).
> - **F5** — the live queue is **split** into a bulk lane (default `arq:queue`:
>   GitHub bulk + LLM batch) and a fast lane (`arq:queue:fast`:
>   `billing_process_webhook` + `pr_check`), each a **separate process**
>   (`WorkerSettings` / `FastWorkerSettings`) so a bulk-export storm can't starve
>   paid grants. Routing is single-sourced in `services.queue.queue_for_job`;
>   global crons sit on exactly one lane (arq dedups per-queue across replicas);
>   per-queue depth + oldest-job-age are sampled by a per-worker cron. **Deploy
>   invariant:** the fast worker must run in every environment (compose
>   `worker-fast`, Procfile `worker_fast`). The per-installation governor (F5 #4 /
>   T-274) already exists.
> - **F6** — the four module-level task sets are unified into one bounded
>   `BoundedTaskRegistry` (strong-ref-until-done preserved, `len()` gauge,
>   high-water warning); advisory eval/critic/verifier work shares a concurrency
>   semaphore (`MAX_CONCURRENT_ADVISORY_TASKS`) so it can't starve live streams.
>   The pipeline registry stays ungated (bounded upstream by F1).

**P2 — tail latency & polish:**
9. **F7** offload inline bleach/regex/diff to threads.
10. Public-payload Redis cache; partial index on `in_progress`; per-installation GitHub
    governor (T-274); env-driven PDF executor size.

---

## 8. Validate it ("nothing breaks under load")

A capacity claim is unproven without a load test. Add to staging/CI:

- **Scenarios (k6/Locust):** (a) N concurrent full generations ramped 1→200 to find the
  **provider-429 ceiling** (F2) and confirm F1 sheds gracefully (503+`Retry-After`, not
  hangs/5xx); (b) mixed traffic — generations + dashboard + login — to prove
  auth/`/health` stay flat during a generation storm; (c) GitHub-export storm concurrent
  with billing webhooks to prove F5 separation; (d) sustained run to watch the idle pool
  footprint vs `max_connections` (F3).
- **Metrics & alerts to add:** provider 429 rate + in-flight provider requests; SQLAlchemy
  pool checked-out/overflow/wait + **total open connections per instance**; **event-loop
  lag** (sampled monotonic drift); per-queue depth + oldest-job age; `len()` of each
  background-task set; Redis pool in-use; 503 admission rejections.
- **Acceptance gate:** at target concurrency, p99 of login/`/health`/dashboard stays flat
  while generations are in flight; over-budget generations return 503+`Retry-After`;
  total Postgres connections stay under the confirmed `max_connections` with margin.

## 9. Capacity model (to refine with the load test)

- **DB connections are *not* the near-term ceiling** (§1) — generations don't hold them.
- **The near-term ceiling is the provider budget (F2)** on the shared key — *measure it*,
  then enforce it as the F1 admission limit. Users with their own keys scale independently.
- **Horizontal scale-out is gated by the idle pool footprint × instances vs
  `max_connections` (F3)** — solved by the pooler, which is **already compatible** here.
- **After F1+F2+F3+F4+F5:** API + worker scale horizontally behind the pooler; Postgres
  connection count stays flat regardless of instance count; generation throughput is
  bounded by (and explicitly governed to) the provider budget + key pool.
