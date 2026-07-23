# Data Retention & Purging — Production Implementation Plan (issue #43)

Status: **proposed** — supersedes the checklist in the issue body; builds on the two
audit comments on issue #43 (2026-07-02) and corrects them where the code says
otherwise. Verified against `main` @ `1e4d973`.

The goal, restated: **steady-state DB size proportional to the *active* corpus, not
to lifetime history** — with user-content deletion gated on user awareness, and
operational telemetry purged on plain TTL with no product surface at all.

---

## 1. Verified ground truth (deltas vs the issue-#43 comments)

Everything below was checked against the live models/migrations. Four findings
**change** the plan in the issue comments; the rest confirm it.

### 1.1 "Archived" already means "user-deleted" — the biggest correction

- The dashboard button is labeled **"Delete workspace"** (`WorkspaceCard.tsx`) and
  calls `DELETE /workspaces/{id}` (`routers/workspace.py:231`), which runs
  `workspace_service.archive()` — it just sets `status='archived'`.
- `list_for_user` filters `status == 'active'` (`workspace_service.py:81-88`):
  **archived workspaces are invisible to the user forever.** There is no
  un-archive endpoint, no archived/trash view, no restore.

Consequence: the issue addendum's design (180-day countdown banner on archived
workspace cards, T−30/−7/−1 email ladder as a hard purge precondition) assumed
"archived" is a passive lifecycle state the user parked and may revisit. In this
product, archival is always an **explicit user delete action** with no surface left
to render a countdown on. Phase 3 therefore switches to a **trash-can model**
(§5): the delete confirmation dialog *is* the notice moment, recorded server-side;
a visible "Recently deleted" section provides the countdown + restore + export.
The email ladder drops from hard-gate to optional hardening — for user-initiated
deletion, prompt purging is what the user asked for (and what GDPR
storage-limitation favors); mailing "we're about to delete the thing you deleted"
serves nobody. If product prefers the passive-archive semantics instead
(un-archive + archived views + long window), the addendum's email gate stands —
that decision is flagged in §5.0.

### 1.2 `integration_pushes` barely grows — purge `failed` rows only

The partial unique index `uq_integration_push_workspace_repo_active`
(`WHERE status <> 'failed'`) enforces **one live push per (workspace, repo)**, and
re-export **reuses** that row (`push_repo.find_live_push`, model docstring). So
`pending`/`completed`/`stale` rows are all *live sync state* — `stale` is a live
push with detected drift, not garbage. Only `failed` rows accumulate.
Tier 1 purges `failed` pushes older than the window, nothing else. (The issue
comment's "superseded completed > 90d" tier is moot — such rows cannot exist per
repo, and completed rows for other repos are live state.)

### 1.3 `llm_batch_jobs` already self-cleans on success

Lifecycle is `pending → submitted → completed (row deleted) | failed`
(`models/llm_batch_job.py`). Only `failed` rows accumulate; purge those at 30 d.

### 1.4 Index reality

- `llm_cost_events.created_at` **already has an index** (`index=True` in the
  model) — no migration needed for its TTL purge.
- `eval_results` has only the composite `(stage_version_id, created_at DESC)`
  (migration 0012) — its TTL purge needs a plain `created_at` index
  (migration 0032).

### 1.5 Confirmed as stated in the issue comments

- **FKs into `stage_versions`** — exactly two: `eval_results.stage_version_id`
  (`ondelete=CASCADE`, so evals die with pruned versions automatically) and
  `integration_pushes.source_stage_version_id` (**no `ondelete` = NO ACTION** —
  the landmine). Version pruning must exclude push-referenced rows via
  `NOT EXISTS`; whole-workspace cascade is safe because both sides die in the
  same statement (NO ACTION checks at statement end).
- **`credit_ledger` survives workspace deletion** — its only FK is
  `user_id → users (CASCADE)`; the `deduction_ledger_id` FKs point *from*
  stages/increments/storyboards *into* the ledger, so deleting the workspace
  subtree never touches ledger rows. `llm_cost_events` FKs are all `SET NULL`.
- **Cron map** (for collision-free scheduling): drift `{0,15,30,45}` min; billing
  reconcile `{7,22,37,52}` min; generation estimates `{3,13,23,33,43,53}` min;
  webhook purge 3:17 (bulk); billing purge 3:42 (**fast lane** — billing's home);
  billing sweep :00 s; batch sweep :30 s; queue sampler :45 s. Global crons
  register on **exactly one lane** (bulk, per the F5 rule) or they double-fire.
- **`workspaces.updated_at` has no `onupdate`** — it cannot be used to backfill
  `archived_at`. Backfill to deploy time (`now()`), so the clock starts at deploy.
- **`scripts/analyze_output_budgets.py` defaults to a 28-day lookback** — the
  180 d `llm_cost_events` window clears the issue-#26 evidence gate with 6×
  headroom.
- No email infrastructure exists anywhere in the backend.

---

## 2. Retention matrix (final)

| Tier | Table | Policy | Hard guards (never delete) |
|---|---|---|---|
| 0 — existing, unchanged | `github_webhook_events`, `stripe_webhook_events`, `billing_webhook_events` (processed), `billing_checkout_attempts` (terminal) | 30 d | — |
| 1 — telemetry TTL | `llm_cost_events` | 180 d | window ≥ output-budget lookback (28 d default) |
| 1 | `eval_results` | 180 d | — (also cascade-deleted by Tier 2) |
| 1 | `llm_batch_jobs` | `failed` > 30 d | non-terminal rows |
| 1 | `integration_pushes` (+`integration_push_tasks` via CASCADE) | `failed` > 90 d | `pending`/`completed`/`stale` (all live sync state, §1.2) |
| 2 — content keep-N | `stage_versions` (+`eval_results` via CASCADE) | keep last **20** per stage; prune the rest only when > 90 d old | row where `version == stage.current_version`; rows referenced by `integration_pushes.source_stage_version_id` (`NOT EXISTS`) |
| 2 | `storyboards` | keep last **5** per workspace (by `version DESC`); prune the rest when > 90 d | newest row regardless of age; `public_share_enabled = true`; non-terminal `status` |
| 3 — trash (user-facing) | `workspaces` + full cascade (stages → versions → evals; increments; ideas; storyboards; pushes → push tasks) | hard-delete when `status='archived'` AND clock expired (§5.2) | active workspaces (never on any timer); notice predicate unmet (§5.3) |
| 4 — forever | `credit_ledger`, all `billing_*` financial audit, `stripe_*` audit tables, `users`, `user_integrations`, `github_installations`, `templates` | retained | — |

Every window is a `config.py` env knob (§3.1), so dev/staging can run 1-day
windows. `increments`/`increment_ideas` have **no independent clock** — they die
with their workspace.

---

## 3. Phase 1 — retention service, config, Tier-1 purges

### 3.1 Config (`backend/config.py`, pydantic env settings — repo convention, no YAML)

```python
# --- Data retention (issue #43). Two keys must turn before anything deletes:
# the master enable AND dry_run=False. Per-tier flags gate each job separately
# so tiers roll out independently (§8).
retention_enabled: bool = True                 # master kill-switch (counting + purging)
retention_dry_run: bool = True                 # True ⇒ every job only counts candidates
retention_tier1_purge_enabled: bool = False    # telemetry TTL deletes
retention_tier2_purge_enabled: bool = False    # stage_versions/storyboards keep-N deletes
retention_tier3_purge_enabled: bool = False    # workspace trash deletes
retention_purge_batch_size: int = 1000
retention_max_rows_per_run: int = 50_000       # per job per daily run; backlog drains over days
retention_cost_events_days: int = 180
retention_eval_results_days: int = 180
retention_failed_batch_jobs_days: int = 30
retention_failed_pushes_days: int = 90
retention_stage_versions_keep: int = 20
retention_stage_versions_min_age_days: int = 90
retention_storyboards_keep: int = 5
retention_storyboards_min_age_days: int = 90
retention_trash_days: int = 30                 # post-deploy deletes (dialog shows this)
retention_legacy_archived_days: int = 180      # rows archived before this feature shipped
retention_table_stats_enabled: bool = True     # Phase 0 sampler
```

`validate_production_settings()` additions: when `retention_tier3_purge_enabled`
in prod, require `retention_trash_days >= 7` and
`retention_legacy_archived_days >= 90` (fat-finger guards).

### 3.2 `backend/services/retention.py` (new)

Mirrors `maintenance.py` / `billing_worker.purge_billing_events` conventions:

- One shared batched-delete helper: `SELECT id … WHERE <predicate> LIMIT batch`
  → `DELETE … WHERE id IN (…)` → `commit` per batch → loop until empty or the
  per-run cap. Dialect-neutral SQLAlchemy only (sqlite test backend).
- Every job: computes the candidate count first (always, even when purging —
  it feeds the gauge), honors `retention_dry_run`, and emits one structlog
  audit event per run: `retention.<job>_done` with
  `candidates / deleted / dry_run / cutoffs / batch_size / cap / duration`.
- Jobs (all idempotent, all keyed on indexed predicates):
  - `purge_cost_events(db)` — `created_at < cutoff` (index exists).
  - `purge_eval_results(db)` — `created_at < cutoff` (index from 0032).
  - `purge_failed_batch_jobs(db)` — `status='failed' AND updated_at < cutoff`
    (status is indexed; failed rows are few).
  - `purge_failed_pushes(db)` — `status='failed' AND created_at < cutoff`;
    push tasks die via CASCADE.

### 3.3 Migration `0032_eval_results_created_at_index.py`

Plain btree on `eval_results(created_at)`. Follow 0012's convention/note on
`CREATE INDEX CONCURRENTLY` for a large live table (build out-of-band + `alembic
stamp` if needed); skip cleanly on non-postgres like 0031.

### 3.4 Worker wiring (`backend/worker.py`)

- `retention_tier1_purge(ctx)` — plain cron (catch + log, like
  `purge_webhook_events`; a missed daily run is inconsequential), **bulk lane
  only**, daily **4:11 UTC** (clear of the full cron map in §1.5).
- Runs all four Tier-1 jobs sequentially in one session context, each with its
  own per-run cap.

### 3.5 Tests (`tests/test_retention.py`, mirroring `test_maintenance.py`)

- Old rows deleted / recent kept, per table.
- Dry-run deletes nothing but reports candidates.
- Batch cap honored (insert cap+1 candidates → exactly cap deleted, one left).
- `failed`-only predicates: non-terminal batch jobs and
  `pending`/`completed`/`stale` pushes untouched.
- Tier-1 flag off ⇒ counting only, even with `dry_run=False`.

---

## 4. Phase 2 — `stage_versions` keep-N (the byte win) + storyboards

`stage_versions.content` (tens of KB per row, plus `research_context`) is the
dominant byte cost; keep-N caps steady-state bytes at
`stages × N × avg_artifact_size` regardless of account age.

### 4.1 Candidate query (dialect-neutral, window function)

```sql
WITH ranked AS (
  SELECT sv.id,
         row_number() OVER (PARTITION BY sv.stage_id ORDER BY sv.version DESC) AS rn
  FROM stage_versions sv
)
SELECT sv.id FROM stage_versions sv
JOIN ranked r ON r.id = sv.id
JOIN stages s ON s.id = sv.stage_id
WHERE r.rn > :keep_n
  AND sv.created_at < :cutoff
  AND sv.version <> s.current_version              -- belt (rn>20 already implies it)
  AND NOT EXISTS (SELECT 1 FROM integration_pushes p
                  WHERE p.source_stage_version_id = sv.id)   -- the NO-ACTION FK (§1.5)
LIMIT :batch
```

- Uses `ix_stage_versions_stage_id`; EXPLAIN-verify on staging before enabling.
- `eval_results` cascade automatically (DB-level `ondelete=CASCADE`).
- Demo-Day `construction_verdict` stamps version ids as JSONB values (staleness
  compare only, no FK) — unaffected.
- **Product sign-off required before the flag flips:** this truncates the visible
  version/diff history beyond N=20 (90 d age floor makes practical loss ~nil,
  but it's a product policy call). `N` is a knob.

### 4.2 Storyboards

Rank per workspace by `version DESC`; delete `rn > 5 AND created_at < cutoff`,
excluding `public_share_enabled = true` (live public links must not 404), any
non-terminal `status`, and the newest row regardless of age.
`llm_cost_events.storyboard_id` is `SET NULL` — fine.

### 4.3 Wiring + tests

- Cron `retention_tier2_purge`, bulk lane, daily **4:31 UTC**, gated on
  `retention_tier2_purge_enabled`, same dry-run/cap/audit contract.
- Tests: newest-N survive; current_version survives even if beyond N (forced
  fixture); push-referenced version survives; evals cascade with pruned
  versions; shared/newest/non-terminal storyboards survive; age floor respected.

---

## 5. Phase 3 — workspace trash lifecycle (user-facing)

### 5.0 Decision (recommended path, given §1.1)

**Trash-can model:** "Delete workspace" becomes "Move to trash"; a visible
"Recently deleted" dashboard section shows the countdown with **Restore** and
**Export** for the whole window; hard-delete happens `retention_trash_days`
(default 30) after the user's explicit, recorded, delete confirmation.
The confirm dialog is the notice moment — it states the window and links the
policy page, and the acknowledgment is persisted server-side and **required by
the purge predicate**. This keeps the addendum's core principle ("awareness is a
hard precondition of deletion, enforced in the predicate") while matching what
archival actually is in this product: an explicit delete.

The alternative (passive archive: un-archive endpoint + archived views + 180 d
window + email ladder as hard gate, per the addendum) remains valid if product
wants "archive" as a real parking state. Deltas: add `retention_notices` table +
notifier cron 4:21 + a `services/notifications.py` provider seam, and Tier 3
cannot enable in prod without email configured. **Not the recommended v1** — it
builds an email stack to warn users about deletions they explicitly requested.

Pinning ("keep in trash forever") is cut: **Restore** already covers "I want to
keep this" losslessly, and a third never-purge state contradicts trash semantics.

### 5.1 Migration `0033_workspace_trash.py`

- `workspaces.archived_at TIMESTAMPTZ NULL` — set by the archive flow; cleared
  on restore. **Backfill existing archived rows to `now()`** (deploy time —
  `updated_at` is unreliable, §1.5), so nothing is instantly eligible.
- `workspaces.retention_ack_version TEXT NULL` — the policy version string the
  delete dialog displayed (e.g. `"trash-v1"`), stamped by the DELETE handler
  when the client supplies it. Legacy rows and stale-SPA deletes leave it NULL.
- Partial index `ix_workspaces_archived_at ON workspaces (archived_at) WHERE
  status = 'archived'` — matches the purge predicate exactly (0031 pattern).

### 5.2 Purge predicate (`purge_trashed_workspaces`)

A workspace is deletable iff `status='archived'` AND:

- **Post-deploy delete** (`retention_ack_version IS NOT NULL`):
  `archived_at < now() − retention_trash_days`; or
- **Legacy / un-acked row** (`retention_ack_version IS NULL`):
  `archived_at < now() − retention_legacy_archived_days` (180 d — by then the
  policy page and ToS update have been live for months, and these are
  workspaces users explicitly deleted, in some cases years ago).

One `DELETE FROM workspaces WHERE id IN (batch)` — Postgres fans the cascade out
to stages → versions → evals, increments, ideas, storyboards, pushes → push
tasks in-statement (safe w.r.t. the push→version NO-ACTION FK, §1.5).
`llm_cost_events` survive via `SET NULL` (cost ledger, intentional);
`credit_ledger` untouched (§1.5). Cron **4:51 UTC**, bulk lane, gated on
`retention_tier3_purge_enabled`, same dry-run/cap/audit contract — plus a
per-workspace structlog audit row (`retention.workspace_purged` with
workspace_id, user_id, archived_at, ack_version).

### 5.3 API (`routers/workspace.py`)

- `DELETE /workspaces/{id}` — accepts optional `ack_version` (query param);
  handler stamps `archived_at=now()` + `retention_ack_version`. Response gains
  nothing (stays 204); the frontend computes the purge date from the retention
  endpoint below. Old cached SPAs keep working — their deletes just fall into
  the conservative legacy window.
- `GET /workspaces/trashed` — archived workspaces for the user with
  `archived_at` and computed `purge_after` (window from config).
- `POST /workspaces/{id}/restore` — archived → active; clears `archived_at` +
  `retention_ack_version`. Re-delete restarts the clock (matches the addendum's
  "re-archiving restarts the ladder").
- `GET /retention/policy` — static policy metadata (windows, policy version,
  keep-N values) for the dialog/settings UI; unauthenticated-safe, cacheable.
- Export needs nothing: `workspace_service.get()` doesn't filter on status, so
  the existing `POST /workspaces/{id}/export` zip (and PDF) already works on
  trashed workspaces. Verified.

### 5.4 Frontend

- `WorkspaceCard` delete → confirm dialog: "Move to trash? It will be
  permanently deleted after {N} days. You can restore or export it until then."
  — passes `ack_version` from the policy endpoint on confirm.
- Dashboard: collapsed "Recently deleted" section (from `GET /workspaces/trashed`)
  with per-card countdown + Restore + Export.
- `Settings.tsx`: "Data retention" section rendering the policy
  (windows + link to the published policy doc).
- Copy changes: "Delete" → "Move to trash" wherever the old wording implied
  permanence-now.

### 5.5 Legal gate (unchanged from the issue comments)

`docs/RETENTION_POLICY.md` (user-facing tiers/windows/export/restore, DSAR
pointer) + ToS/privacy updates published **before**
`retention_tier3_purge_enabled` flips in prod. Account-deletion/DSAR flows stay
a separate issue (billing settlement ops already exist, RUNBOOK §9).

---

## 6. Phase 0 — telemetry baseline (ship FIRST, zero risk)

- `worker.sample_table_stats` — plain cron, **bulk lane**, hourly at **:41**
  (clear of every minute-set in §1.5), gated on `retention_table_stats_enabled`.
- Postgres-only (dialect-guarded, like 0031): samples
  `pg_total_relation_size(quote_ident(t))` and `pg_stat_user_tables.n_live_tup`
  for a **fixed allowlist** (the §2 tables) → gauges
  `thought2build_db_table_bytes{table}`, `thought2build_db_table_live_tuples{table}`
  in `services/observability.py`.
- This is the baseline every later "size stabilized" claim is judged against,
  and the evidence for tuning the §2 windows before anything deletes.

---

## 7. Phase 4 — observability, alerts, ops

Metrics (`services/observability.py`, existing naming conventions):

- `thought2build_retention_candidates{job}` (gauge — set every run incl. dry-run)
- `thought2build_retention_purged_rows_total{job,table}` (counter)
- `thought2build_retention_run_seconds{job}` (histogram)
- `thought2build_retention_last_success_timestamp{job}` (gauge — missed-run alert)

Alerts:

- Job failure: `time() − last_success > 26h` per job (structlog exception is
  the diagnostic, the gauge is the pager).
- Backlog: `retention_candidates` rising for 7 d while the tier's purge flag is
  on ⇒ per-run cap undersized (raise `retention_max_rows_per_run`).
- `thought2build_db_table_bytes` slope still positive 4 weeks after a tier enables.
- Run-duration regression (index rot / lock contention).

RUNBOOK **§18**: enable order, dry-run interpretation, pause procedure (flip the
tier flag — everything is additive and reversible), alert responses, and the
`pg_repack` note: **`DELETE` does not shrink files** — autovacuum makes dead
space reusable, so the success criterion is *plateau*, not *shrink*; actual disk
reclamation is `pg_repack` in a maintenance window, ops-optional.

---

## 8. Rollout (each step independently reversible by flag)

Thought2Build is **pre-production**: there is no accumulated prod corpus to drain and
no weeks-long prod soak to sit through. Retention can ship at (or before) GA so
steady-state holds from the first real row. Validation moves to **dev/staging
with short windows** — set the `*_days` knobs to `1` so candidates actually
materialize — plus the test suite, *not* calendar time in prod.

1. **Phase 0** telemetry ships with (or before) launch so the size baseline
   exists from day one — it's the yardstick every later "size stabilized" claim
   is measured against once real traffic arrives. Nothing to "observe for weeks."
2. **Tier 1** — validate the predicates in staging (short windows → dry-run
   parity: candidates counted ≈ rows deleted) and via `tests/test_retention.py`,
   then enable (`retention_tier1_purge_enabled=true`, `retention_dry_run=false`).
   Safe to turn on at launch: telemetry volume is negligible early and there is
   no backlog, so the per-run cap is never stressed. Row-count growth is bounded
   from the start with zero user-visible change.
3. **Tier 2** — gate on **EXPLAIN-verify** (staging) + **product sign-off** on
   keep-N (it truncates visible version/diff history beyond N), *not* on elapsed
   time. Enable once both clear. *Byte* growth becomes bounded here.
4. **Tier 3** last: migration 0033 + API + UI ship, **policy doc + ToS published**
   (the real gate is legal sign-off, not a soak) → staging dry-run → enable.
   Because retention ships at launch, the legacy/un-acked path (§5.2) is
   essentially empty in prod — every real delete carries an ack — so the 180 d
   conservative window only ever covers dev/staging rows and any brief
   pre-retention gap.
5. Dry-run parity check (staging) at each enable: candidates counted ≈ rows
   deleted.

Backout at any point: flip the tier flag (or `retention_enabled=false` for
everything, sampler included). Nothing in Phases 0–2 changes any API surface.

## 9. Test plan summary

| Area | File | Key cases |
|---|---|---|
| Tier-1 purges | `tests/test_retention.py` | old/recent split; dry-run; caps; failed-only predicates; flag gating |
| Keep-N | `tests/test_retention.py` | §4.3 guard matrix (current_version, push-ref, cascade, shared storyboards) |
| Trash lifecycle | `tests/test_workspace.py` + `tests/test_retention.py` | ack stamping; legacy vs acked windows; restore clears clock; purge is no-op without expired clock; full-cascade delete leaves `credit_ledger`/`llm_cost_events` rows (SET NULL) intact |
| Config | `tests/test_retention.py` | prod validation floors; two-key requirement |
| Migrations | migration tests per repo convention | 0032 index; 0033 backfill sets `archived_at` on pre-existing archived rows |
| Frontend | vitest | confirm dialog copy + ack param; trashed section renders countdown/restore/export |

## 10. Success criteria

- [ ] `thought2build_db_table_bytes` slope ~flat at steady state for every Tier-1/2
      table (plateau, not shrink)
- [ ] Dry-run parity at each tier enable
- [ ] All purge predicates index-backed (EXPLAIN on staging, no seq scan on hot
      tables); per-run caps honored; job failure alert wired
- [ ] Zero deletions ever of: current stage versions, push-referenced versions,
      non-`failed` pushes, non-terminal batch jobs, publicly-shared storyboards,
      active workspaces, financial/identity rows
- [ ] No workspace hard-deleted without either a recorded delete acknowledgment
      + `retention_trash_days`, or the legacy 180 d window — enforced by the
      predicate itself, verified by test
- [ ] Restore + export available for the entire trash window
- [ ] Every purge run emits a structlog audit event (counts, cutoffs, dry_run,
      config); workspace purges additionally audited per row
- [ ] `docs/RETENTION_POLICY.md` + RUNBOOK §18 published; ToS/privacy updated
      before Tier 3 enables
