# Plan: Preserve generated content across a refresh during generation

## Context

**Problem:** When a user refreshes the page while a stage is generating, the
whole generated artifact is erased.

**Root cause (confirmed in code, not a stray bug):** A refresh closes the SSE
connection. The supervising generator in `StageManager.generate()` treats client
disconnect as a cancellation signal and, in its `finally`, calls
`pipeline.cancel()` ([stage_manager.py:2016-2023](../backend/services/pipeline/stage_manager.py#L2016-L2023)).
The pipeline's own `finally` then refunds the credit, resets the stage to
`draft`, and **discards the partial** — logged as `stage.interrupted_partial_discarded`
([stage_manager.py:2737-2746](../backend/services/pipeline/stage_manager.py#L2737-L2746)).
The streamed text only ever lived in the in-memory Zustand store on the client
([useStream.ts:118](../frontend/src/hooks/useStream.ts#L118)), and the stage is only
persisted at `done`, so after a refresh there is nothing to reload.

**Intended outcome:** A refresh no longer kills the work. Generation keeps
running server-side to completion and persists normally; the reloaded page
detects the in-progress stage and shows the finished artifact when it lands.

**Decision (confirmed with user):** Billing flips from *refund-on-disconnect* to
**charge-on-completion** — if generation finishes, the user keeps the artifact
and the charge stands. Refunds remain only for genuine failures.

**Scope decision:** Reconnect = **poll for the persisted result**, not live-token
reattach. The user loses the token-by-token animation across the refresh but gets
the complete artifact. True live-streaming resume needs a Redis pub/sub event bus
and is deliberately deferred.

## Approach

Detach the generation pipeline from the client connection so it completes
regardless of disconnect, give the detached task its own DB session, and have the
frontend poll for the result on reload.

### Backend — `backend/services/pipeline/stage_manager.py`

1. **Stop cancelling on disconnect.** In the supervising generator's `finally`
   ([2016-2023](../backend/services/pipeline/stage_manager.py#L2016-L2023)) remove
   `pipeline.cancel()`. On the normal path `await pipeline` (2015) still runs and
   the task is already done. On disconnect (`GeneratorExit`) leave the task
   running. The post-disconnect `events.put_nowait` calls land in a queue nobody
   reads — harmless and GC'd with the closure when the pipeline ends.

2. **Keep a strong reference so the detached task is not GC'd mid-flight.** Add a
   module-level `_BACKGROUND_PIPELINE_TASKS: set[asyncio.Task]` mirroring the
   existing `_BACKGROUND_CRITIC_TASKS` ([~stage_manager.py:276](../backend/services/pipeline/stage_manager.py#L276)):
   `add()` on create, `discard()` in a done-callback.

3. **Make-or-break: the detached pipeline must own its DB session.** The
   request-scoped `db` is closed by FastAPI the instant the generator tears down,
   but the pipeline body does `db.commit/add/flush/rollback`,
   `credit_service.refund(db, …)`, and reads expire-on-commit ORM attributes of
   `stage`/`workspace`. So inside `_execute_generation_pipeline`:
   - Open `async with AsyncSessionLocal() as own_db:` at the top (same pattern
     already used at [2726](../backend/services/pipeline/stage_manager.py#L2726),
     `_stage_db_heartbeat` [603](../backend/services/pipeline/stage_manager.py#L603),
     and `_dispatch_critic_review`).
   - Re-load `stage` and `workspace` by id on `own_db`; pass scalars
     (`user_id`, `deduction_id`) instead of the request-bound `user`/`deduction`
     objects. Use `own_db` for every `db.*` call and every helper that takes a
     session (`_refund_and_reset`, `_persist_quality_gate_blocked`, the version
     persist at [~2603](../backend/services/pipeline/stage_manager.py#L2603), the
     interrupted-cleanup block). The request `db` is then used only by
     `generate()` for preflight + the `in_progress` commit (1946), which already
     commits before the task is spawned.

4. **Cleanup semantics now mean "genuine failure," not "client left."** Because
   we no longer cancel on disconnect, the success path still sets
   `_cleanup_done = True` and the `finally` becomes a no-op → charge stands
   (matches the billing decision). The refund + reset-to-draft +
   `interrupted_partial_discarded` path now fires only on a real
   exception/failure. The `db_heartbeat` already lives inside the pipeline (2064),
   so it survives with the detached task and keeps the recovery sweep from
   resetting a healthy in-progress stage; if the detached task crashes, the
   heartbeat stops and the existing stuck-stage recovery sweep
   ([586/608](../backend/services/pipeline/stage_manager.py#L586)) is the safety net.

### Frontend — `frontend/src/pages/Workspace.tsx`

5. **Reconnect-by-poll on reload.** The page already computes `inProgressStage`
   ([Workspace.tsx:518](../frontend/src/pages/Workspace.tsx#L518)) and already drives
   `checking`/StreamingOverlay off `status === "in_progress"`. Add a `useEffect`
   keyed on `inProgressStage?.id` that — only when this client is **not** the
   active streamer (`!isStreaming`, true on a fresh mount after refresh) — polls
   `getStage(id)` on an interval and `setStage`s the result, stopping when the
   stage leaves `in_progress`. Reuse the existing poll idiom (the eval poller
   ~[688](../frontend/src/pages/Workspace.tsx#L688) and the advisory poll in
   [useStream.ts:59](../frontend/src/hooks/useStream.ts#L59)) — bounded interval,
   cancel token via cleanup. The double-generation guard
   ([stage_manager.py:1776](../backend/services/pipeline/stage_manager.py#L1776)) and
   the existing in_progress action-disable ([Workspace.tsx:674](../frontend/src/pages/Workspace.tsx#L674))
   already prevent a re-trigger, so reconnect strictly polls.

### Tests

6. **Flip the pinned contract test.** `test_generate_marks_langfuse_span_failed_on_client_disconnect`
   ([test_stage_manager.py:1390-1464](../backend/tests/test_stage_manager.py#L1390-L1464))
   currently asserts disconnect ⇒ discarded + draft + version 0 + refund. Rewrite
   it as a contract change: disconnect ⇒ pipeline keeps running on its own session
   and is **not** cancelled; no refund; the stage is not reset by the disconnect.
7. **New backend test:** client disconnect → detached pipeline runs to completion
   on its own `AsyncSessionLocal` → stage persisted as `draft` with content and a
   bumped version, credit **not** refunded.
8. **Frontend test:** mount with an `in_progress` stage and `isStreaming=false` →
   poller calls `getStage` and updates the store to the completed draft.
9. Keep `test_generate_runs_db_heartbeat_for_lifetime_of_generation` passing
   (heartbeat still started/cancelled once per generation).

## Verification

- `cd backend && PYTHONPATH=. uv run pytest tests/test_stage_manager.py tests/test_concurrency.py -q`
  then the full `uv run pytest tests/ -q`; `uv run ruff check . && uv run black --check .`.
- `cd frontend && pnpm test && pnpm tsc`.
- Manual (per the repo's rebuild rule): `docker compose up --build`, start a
  generation, hard-refresh mid-stream. Expect: the page reloads showing the
  in-progress/checking state, then the completed artifact appears without a manual
  re-generate; backend logs show the pipeline completing (no
  `interrupted_partial_discarded`); the credit is charged, not refunded.

## Implementation notes (as built)

- The detached pipeline is split into a thin `_execute_generation_pipeline`
  wrapper (opens `AsyncSessionLocal`, re-loads `stage`/`workspace` by id) and the
  existing body, now `_run_generation_pipeline_body(db=own_db, …)`. **The wrapper
  `await own_db.commit()`s immediately after the two reloads** so the pooled
  connection is released during the (multi-minute) LLM stream rather than held
  idle-in-transaction — `expire_on_commit=False` keeps the loaded scalars usable,
  and the persist write auto-begins a fresh transaction. Without this the session
  could be killed by a Postgres `idle_in_transaction_session_timeout` before the
  final persist, and one connection would be pinned per concurrent generation.
- `_start_langfuse_span`, `_block_incomplete_output`,
  `_block_technology_safety_output`, and `_refund_and_reset` now take `user_id`
  /`deduction_id` scalars instead of request-bound ORM objects.
- Frontend reconnect-by-poll lives in a dedicated, unit-tested
  `hooks/useReconnectPoll.ts` (`useReconnectPoll(inProgressStage?.id, isStreaming)`)
  rather than an inline `useEffect`.
- Test harness: `_MultiQueryDB` now replays a previously-seen Stage/Workspace for
  any by-id re-load (modelling a real DB's identity map) and an autouse fixture
  points `database.AsyncSessionLocal` at the seeded fake, so existing generate
  tests pass unchanged. A spy asserts the pipeline opened its own session.

### Follow-up fix — the reconnect was invisible (2026-06-24)

The first cut delivered the artifact but the **reconnecting page showed nothing**:
the loading overlay, elapsed time, and any sign of activity vanished on refresh,
so the generation looked lost (the user's "everything disappeared" report). Two
gaps, both in `Workspace.tsx`, fixed stage-agnostically (spec/plan/harness/tasks):

1. **Stage selection landed on the wrong stage.** On a fresh mount the page
   selected `firstUnlockedStage` — the *first* non-locked stage — so a refresh
   mid-PLAN landed on a finalised SPEC, not the generating PLAN. Extracted
   `pickActiveStageOnLoad(stages, existing)`: keep a still-valid prior selection,
   else prefer the `in_progress` stage, else fall back to `firstUnlockedStage`.
   Unit-tested in `pages/Workspace.reconnect.test.ts`.
2. **The overlay never rendered during reconnect.** `StreamingOverlay`'s
   `isVisible` is driven by `activeGenerationActivity`, which only existed for a
   live local stream — `null` after a refresh. Synthesize a `reconnectActivity`
   when the active stage is `in_progress` and this client is **not** streaming it;
   `startedAt` reads the stage's `updated_at` (stamped at the `in_progress`
   transition in `generate()`; nothing bumps the row mid-stream, so elapsed is
   accurate). The overlay shows full (no live tokens to collapse into a pill),
   and clears the instant `useReconnectPoll` settles the stage to `draft`.

## Out of scope / follow-up

- Live token-streaming resume across refresh (needs Redis pub/sub fan-out). The
  poll delivers the finished artifact; the live animation is not restored.
