# Issue #29 — End-to-End Backend Engineering Review

## Audit baseline

- Audit SHA: `f1941cc0ad92c5dfb0949b97779b0c02b3bbb223`
- Commit date: 2026-07-20 22:11:00 +0530
- Review date: 2026-07-20 (Asia/Kolkata)
- Migration head: `0041`
- Runtime: Python 3.12.13 through uv 0.11.8; PostgreSQL 16; Redis 7
- Scope: 503 tracked files (402 backend, 47 backend harness/schema, 49 frontend contract consumers, four workflows, and `docker-compose.yml`). The complete file ledger is in `BACKEND_REVIEW_ISSUE_29_MANIFEST.md`.
- Method: frozen-tree static review, automated gates, focused runtime reproductions, subsystem boundary review, and a second pass over security, financial, database/concurrency, and async-runtime paths. Historical reports were used only as leads.

## Release recommendation

**Approve with conditions.** The backend passes its selected release gates, migrations, dependency/security scans, and image checks. Before promoting this SHA into a cost-sensitive production workload, remediate `BE29-001` or disable automatic mid-tier fallback for watchdog timeouts. `BE29-002` should be fixed before Anthropic cost telemetry is used for budget policy or margin decisions. The remaining findings are test-governance work rather than demonstrated production failures.

## Severity summary

| ID | Severity | Confidence | Category | Status |
|---|---|---:|---|---|
| BE29-001 | High | High | LLM reliability / cost amplification | Confirmed; remediation #47 |
| BE29-002 | Medium | High | Financial observability | Confirmed |
| BE29-003 | Medium | High | CI / concurrency testing | Confirmed |
| BE29-004 | Low | High | Contract-test governance | Confirmed |

No Critical finding or demonstrated cross-tenant, unauthorized-credit, irreversible-corruption, or fleet-outage path was found at the pinned SHA.

## Findings

### BE29-001 — Watchdog timeouts bypass provider circuit accounting

Remediation: https://github.com/rsqrd-labs/specforge/issues/47

- **Invariant:** repeated provider failures must make an unhealthy route ineligible before retries/fallbacks amplify cost.
- **Execution path:** `_watchdog_stream` creates and then cancels the adapter's pending `anext` task on idle/hard-cap expiry, closes the iterator, and raises `StreamWatchdogTimeout` (`backend/services/pipeline/stage_manager.py:754-846`). `InstrumentedAdapter.stream` records circuit failures only in `except Exception` (`backend/services/llm/instrumented_adapter.py:145-173`). The cancellation unwinding the instrumented iterator is not the subsequently-created watchdog exception, so the circuit never observes the timeout.
- **Reproduction:** a hung instrumented stream with a 20ms idle timeout raised `StreamWatchdogTimeout(kind="idle")`; the provider failure count remained zero and `can_route` remained true.
- **Impact:** repeated hung cheap-tier calls remain routable. Each generation/chunk can repeatedly incur its timeout and then follow the configured mid-tier fallback, increasing latency, capacity pressure, and model spend. This is especially material where GPT-5.4 Mini falls back to GPT-5.4.
- **Remediation:** record the synthesized watchdog timeout exactly once against the provider before raising it. Preserve rate-limit exclusions and avoid double-counting exceptions already observed by the adapter. Consider separating transport health from content-quality fallback policy.
- **Regression tests:** prove that the configured number of consecutive idle and hard-cap timeouts opens the provider circuit; prove success resets it; prove 429/529/503 paths remain excluded; prove one provider event resets only the idle timer.
- **Rollout:** add a counter split by timeout kind and circuit action, canary with fallback-cost dashboards, and retain the one-toggle cheap-primary rollback.

### BE29-002 — Anthropic prompt-cache writes and reads are priced as the same discounted tokens

- **Invariant:** provider-reported usage must produce materially accurate cost telemetry.
- **Execution path:** `_normalize_anthropic_usage` combines `cache_read_input_tokens` and `cache_creation_input_tokens` into one `cached_input_tokens` value (`backend/services/llm/usage.py:166-179`). `estimate_cost_usd` subtracts that combined value from `input_tokens` and prices all of it at the catalog's cached-input rate (`backend/services/llm/usage.py:83-107`). Anthropic reports base input, cache creation, and cache read separately; writes are charged at a premium while reads receive the discount.
- **Impact:** `llm_cost_events.estimated_cost_usd` underreports Anthropic cache-write traffic and can also undercount the base input component. Credit debits are fixed-product credits and are not directly altered, but margin reporting and evidence-based output-budget/model decisions can be wrong.
- **Evidence:** current unit expectations preserve the aggregation, while Anthropic's pricing documentation distinguishes base input, cache writes, and cache reads: https://docs.anthropic.com/en/docs/about-claude/pricing
- **Remediation:** retain separate read/write token fields through normalization and persistence; price each using its provider/model/TTL rate. Backward-compatible alternatives are raw-usage recomputation for Anthropic or an additional cache-write field while preserving the existing aggregate.
- **Regression tests:** official worked pricing examples for no-cache, read hit, 5-minute write, and mixed read/write usage; verify persisted raw usage permits reconciliation.

### BE29-003 — Finalise transaction integration test is excluded and does not run successfully in isolation

- **Invariant:** finalisation's ownership, locking, and stage-transition transaction must have an executable PostgreSQL integration gate.
- **Evidence:** CI explicitly ignores `tests/test_finalise_integration.py` (`.github/workflows/ci.yml:202-217`) and does not re-run it after the database reset. Running it alone against PostgreSQL fails during fixture setup/teardown with an asyncpg future attached to a different event loop and a concurrent-operation teardown error.
- **Impact:** unit tests still provide coverage, but the database-level concurrency/transaction path can regress without blocking CI.
- **Remediation:** make the module own one event-loop-safe engine/session fixture, reset its isolated database before the module, and add a dedicated post-reset CI step like the other schema-owning integration suites.
- **Regression tests:** simultaneous finalise attempts, ownership denial, stale-version conflict, lock rollback after failure, and retry after serialization/deadlock errors.

### BE29-004 — The complete backend harness contains 21 stale failures outside the selected CI subset

- **Invariant:** committed contract tests must either describe a supported contract and run in CI, or be explicitly retired/versioned.
- **Evidence:** the CI-selected backend harness set passes (265 tests). Running all `harness/tests/backend` yields 756 passed and 21 failed. Failures include retired Stripe endpoint literals, renamed gate helpers, old callback/source-shape assumptions, and outdated stage-manager structure. Thirteen JSON schemas parse successfully.
- **Impact:** contributors cannot treat the documented broad harness command as authoritative; real regressions can be obscured by known stale failures. No production defect is inferred solely from these source-shape assertions.
- **Remediation:** classify each failing contract as update, replacement with behavioral coverage, or deletion; make the authoritative harness target explicit and fail CI if unclassified tests appear.
- **Regression tests:** a meta-test or CI inventory that requires every harness module to be selected or explicitly deprecated with an owner and expiry.

## Automated evidence

| Gate | Result |
|---|---|
| Ruff | Pass |
| Black check | Pass; 371 files |
| Bandit | Pass; 45,942 executable lines, zero findings; 22 suppressed checks and one `nosec` reviewed |
| `pip-audit --strict` | Pass; no known vulnerabilities |
| Backend pytest CI-equivalent | 2,321 passed, 3 skipped, 9 warnings |
| Services coverage | 85.73% (80% gate passes) |
| CI-selected harness | 265 passed, 2 warnings |
| Complete backend harness | 756 passed, 21 failed, 3 warnings (`BE29-004`) |
| Harness JSON schemas | 13/13 valid JSON |
| Empty PostgreSQL migration | `base -> 0041` pass |
| Oldest supported migration | `0001 -> 0041` pass |
| Migration downgrade review | destructive downgrades exist as expected; not applied to shared data; production rollback must be forward-fix/restore based |
| Backend image build | Pass |
| API and both worker imports/entrypoints | Pass (`WorkerSettings`, `FastWorkerSettings`) |
| Entrypoint shell parse | Pass |

Warnings/skips requiring ownership: Starlette/httpx deprecations, four synchronous tests marked `asyncio`, and an asyncpg cancellation warning in a security-header test. The three suite skips are recorded in test output and should be periodically re-justified.

Coverage hotspots below 60% are `services/evals/runner.py` (0%), `services/token_service.py` (0%), `services/storyboard_service.py` (42%), `services/github_auth_service.py` (46%), `services/storyboard_public_service.py` (53%), `services/recovery_service.py` (57%), and `services/pdf_export_service.py` (58%). This is risk-based evidence, not a finding by percentage alone.

## Subsystem conclusions

- **Platform/security:** authentication, ownership dependencies, CSRF middleware, webhook signature-before-work ordering, encryption configuration, sanitizer/output guards, public-route controls, logging, health, and metrics were traced. No confirmed authorization bypass or secret disclosure was found.
- **Data/financial:** ledger mutations, refund/debt idempotency, webhook inbox processing, row locks, recovery deductions, migrations, indexes, and cache eviction paths received primary and second passes. `BE29-002` affects telemetry, not ledger authority.
- **API contracts:** routers, Pydantic schemas, SSE terminal/error events, pagination/limits, and TypeScript consumers are represented in the manifest and contract suite. No confirmed incompatible runtime contract was found.
- **LLM pipeline:** routing, prompt-cache policy, token budgets, streaming watchdogs, retries, escalation, output gates, persistence, cancellation, detached advisory work, and admission controls were reviewed. `BE29-001` is the release condition.
- **Integrations/workers:** GitHub and both billing webhook authorities, queues, cron lane ownership, retries/dead letters, HTTP clients, and API/fast/bulk worker parity were reviewed. Both worker entrypoints import from the built image.
- **Operations/tests:** documented CI was reproduced. The selected release gates pass, but `BE29-003` and `BE29-004` are material governance gaps.

## Prioritized remediation queue

- **Release condition:** BE29-001.
- **Next sprint:** BE29-002 and BE29-003; raise focused coverage around recovery, GitHub identity OAuth, storyboard persistence/publication, and token service.
- **Backlog:** BE29-004; deprecation warnings; stale async markers; justify/remove suppressions and skips.

## Acceptance checklist

- [x] Frozen SHA, runtime/dependency baseline, migration head, and CI inventory recorded.
- [x] Every in-scope file appears in the manifest with workstream, status, finding IDs, and coverage evidence.
- [x] Automated release gates, complete harness divergence, skips, warnings, and low-coverage areas recorded reproducibly.
- [x] Runtime boundaries, authorization paths, transactions, external calls, and background jobs received explicit subsystem coverage.
- [x] Security, financial/database-concurrency, and async-runtime paths received a second pass.
- [x] Every High finding has an execution path, focused reproduction, invariant, pinned line references, remediation, and regression tests.
- [x] Performance claims require measured evidence; no intuition-only performance finding was published.
- [x] Report distinguishes exploitable/runtime defects from defense-in-depth and test-governance work.
- [x] Indexed summary and remediation link posted to GitHub issue #29.
