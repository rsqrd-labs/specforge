# GitHub Integration — Logic Audit

**Date:** 2026-06-26
**Scope:** Phase 21 GitHub "Living System of Record" (+ retained Phase 13 OAuth) — the
full integration surface, read end-to-end for logical/correctness issues.
**Method:** find-only review. No code was changed. Findings are ranked by severity.

## Files reviewed

- `backend/worker.py`, `backend/services/queue.py`
- `backend/routers/integrations.py`, GitHub endpoints in `backend/routers/workspace.py`
- `backend/services/integrations/`: `github_reconcile.py`, `push_repo.py`,
  `github_app_auth.py`, `github_api_client.py`, `github_governor.py`,
  `github_install_service.py`, `pr_evaluator.py`, `task_parser.py`
- `backend/services/pipeline/github_export_service.py`,
  `backend/services/pipeline/increment_service.py`
- `backend/models/integration_push_task.py`

## What is solid (no action needed)

These were checked specifically and are correctly built:

- **Webhook ingress ordering** (`routers/integrations.py`): HMAC verify → dedup
  insert → enqueue → *then* commit. The deliberate reorder vs. the Plan sketch
  (handoff-before-commit, at-least-once) is right.
- **Confused-deputy scoping** (`push_repo.find_live_pushes_for_event`): events
  resolve on the immutable numeric `repo_id` joined to the delivery's own
  `installation.id`; never `repo_full_name`.
- **Out-of-order safety** (`github_reconcile._apply_done`/`_apply_reopen`):
  `synced_at` holds the *event* timestamp as a high-water mark; a stale `reopened`
  can't regress a newer `closed`. `edited` correctly does not advance it.
- **Rate governor** (`github_governor.py`): atomic Lua token bucket keyed per
  installation, header-driven realign in `observe`, token-guarded compare-and-delete
  repo lock, fail-open on Redis trouble.
- **API client** (`github_api_client._send`): 401 → re-mint exactly once → retry →
  second 401 raises; governor `observe` runs *before* breaker accounting so a
  rate-limit 429/403 requeues as backpressure instead of tripping the breaker; the
  permission-403 vs rate-limit-403 split (`_is_rate_limited`) is handled.
- **PR-check loop breaker** (`pr_evaluator`): head-SHA dedup short-circuits the
  `check_suite:completed` echo our own posted verdict triggers.
- **Throttle requeue** (`queue._requeue_throttled`): a fresh arq job id (not the
  in-flight one) so the deferred requeue isn't dropped; off the dead-letter budget.

---

## 1. 🔴 Critical — Installation hijack via the install callback (IDOR)

**Where:** `routers/integrations.py::github_app_setup` (L123-163) →
`github_install_service.upsert_installation` (L180-223).

`GET /integrations/github/setup` is authenticated **solely by the one-time
`state`** — there is no `get_current_user` (by design: GitHub's browser redirect
carries no bearer token). The `installation_id` is an attacker-controlled query
parameter, and `consume_install_state` only recovers *which user started the flow*.
There is no binding between the `state` and any specific `installation_id` (there
can't be — the state is minted before the install exists).

`upsert_installation` then rebinds the row unconditionally:

```python
row.user_id = user_id        # github_install_service.py:213
row.suspended_at = None
```

**Attack.** An attacker starts their own install flow (a valid `state` bound to
their account), then requests:

```
/integrations/github/setup?installation_id=<victim_id>&state=<attacker_state>
```

`fetch_installation_account` succeeds because the App JWT can read **any** of the
App's own installations (`GET /app/installations/{id}`). The existing row for the
victim's installation is rebound to the attacker. The attacker now passes
`load_owned_installation`'s `installation.user_id == user_id` check and can
**export to (write) the victim's repositories**; the victim loses access (their
own exports start failing `load_owned_installation`). The *create* branch is worse
— the victim need not be a SpecForge user at all, merely have the App installed.

**Caveat (bounds likelihood, not validity):** the attacker needs the victim's
numeric `installation_id`, which is an enumerable integer. The missing control is
exactly the one the module docstring waves off ("a user-to-server identity token …
is out of scope here"): GitHub's setup callback is intended to be paired with the
user-to-server OAuth so the backend can confirm the caller actually administers the
account **before** binding it.

**Suggested direction:** complete the install callback with the GitHub App
user-to-server OAuth (`GITHUB_APP_CLIENT_ID`/`_SECRET` already exist in config),
verify the authenticated GitHub user is an admin of the installation's account, and
refuse to (re)bind otherwise.

---

## 2. 🟠 High — Issue↔task mapping corrupts on task renumber/reorder

The stable-identity design is documented but not wired into persistence/matching.

**Documented contract.** `task_parser.py:20`, the `compute_task_ref` docstring
(L49-72), and the `increment_service` module docstring all state matching/dedup is
**"always on the content-derived `compute_task_ref`, never the human `T-NNN`."**

**Actual implementation.** Every `IntegrationPushTask` is persisted and matched on
the volatile `T-NNN` (`parsed.ref`, which is the `T-\d+` heading per
`task_parser.py:123`):

| Site | Line | Code |
| --- | --- | --- |
| Export, app mode | `github_export_service.py:646` | `task_ref=parsed.ref` |
| Export, legacy mode | `github_export_service.py:753` | `task_ref=parsed.ref` |
| Increment sync | `increment_service.py:970` | `task_ref=parsed.ref` |
| Match (export) | `github_export_service.py:629` | `existing.get(parsed.ref)` |
| Match (increment) | `increment_service.py:949` | `existing.get(parsed.ref)` |

`compute_task_ref` is **never** persisted as the identity — it's used only for
generation-time dedup in `_reconcile_delta` and cosmetically in the agent-issue
YAML header / PR stubs.

**Concrete failure.** Re-finalising the Tasks stage marks the push `stale`
(`mark_pushes_stale_on_tasks_drift`) → the UI offers **resync** → `export_push` →
`_sync_issues` matches on `T-NNN`. If the regenerate **inserts or reorders** a task
(shifting `T-003`→`T-004`, …), each existing issue is `update_issue`'d with the
*next* task's content, and the new highest number opens a **duplicate** issue. In
the increment path it is worse: `_close_obsoleted_issues` also closes the original
issues whose `T-NNN` no longer appears. This is exactly the corruption
`compute_task_ref` exists to prevent.

**Scope (kept honest).** *Additive increments are safe* — the baseline TASKS.md is
appended verbatim, so baseline `T-NNN` never move. The bug only bites on a
reorder/renumber via re-finalise + resync. So the documented guarantee ("a
refinement that renumbers T-001→T-002 keeps the same Issue") is both
**unimplemented and untested** — the tests hard-code `task_ref="T-002"`
(`test_increment_sync.py:274`, `test_github_projects.py:395`), and the column
comment (`integration_push_task.py:50`, *"Content-stable across increments, e.g.
T-001"*) reflects the same internal confusion: it treats `T-NNN` as the stable key,
contradicting `compute_task_ref`'s own docstring.

**Suggested direction:** persist and match on `compute_task_ref(parsed.title)` at
the three sites above, with a backfill migration for existing rows (recompute from
the issue title), or — if `T-NNN` is intentionally the key — delete the
`compute_task_ref` "matching key" claims and the unused identity path so the code
and its docs agree.

---

## 3. 🟡 Medium — A transient queue outage during **resync** permanently fails a healthy push

**Where:** `routers/workspace.py::resync_workspace` (L555-567).

```python
push.status = "pending"
await db.commit()
...
except QueueUnavailableError:
    await github_export_service.mark_push_unstarted(db, push)   # → status="failed"
```

`resync_workspace` flips a live (`completed`/`stale`) push to `pending`, commits,
then enqueues. If Redis is briefly unavailable, `mark_push_unstarted` sets it to
**`failed`**, which `find_live_push` (`status != 'failed'`) then excludes — so the
workspace **loses its live push and all bidirectional sync** until a full
re-export. This is correct for a *first* export (the row had no prior live state)
but destructive for resync, where the push was already healthy.

**Suggested direction:** on an enqueue failure during resync, restore the previous
status instead of failing the row.

---

## 4. 🔵 Minor — Two divergent push-status vocabularies

The legacy OAuth path uses `in_progress`/`success`/`error`
(`github_export_service.py:763`; default `_mark_push_failed(status="error")` at
L819), while the App path and the canonical enum use
`pending`/`completed`/`failed`/`stale` (`push_repo.py:14`). Because
`find_live_push` filters only `status != 'failed'`, a legacy-errored push
(`status="error"`) is still treated as **live**, and `reconcile_drift` backfills
only `status == "completed"` so legacy `success` pushes are never drift-reconciled.
This self-heals in practice (the legacy reuse path resets the row; legacy has no App
webhooks anyway), so it is coherence debt rather than a live bug — but the two
vocabularies are an easy place for a future `status == "…"` check to go wrong.

---

## Worth a glance (not bugs)

- `reconcile_drift` enqueues `backfill_repo` for *every* completed push on each
  15-min tick, and `_run_backfill` builds its client **without a governor**
  (`github_reconcile.py:569-576`) — ungoverned reads. Fine at current scale
  (primary limit ~5000/hr), but it scales linearly with the completed-push count.
- The agent-ready issue body and PR stubs embed `task_ref: compute_task_ref(...)`
  while SpecForge tracks the issue internally by `T-NNN` — the same #2
  inconsistency, surfaced to coding agents that read the issue.

---

## Priority

1. **#1 (install hijack)** — security; fix first.
2. **#2 (task-ref identity)** — data-integrity of the issue mapping under a
   supported flow (re-finalise + resync).
3. **#3 (resync fails a healthy push)** — availability on a queue blip.
4. **#4 (status vocabulary)** — coherence debt.
