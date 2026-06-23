# Critic Off the Critical Path — Async Advisory Plan

**Goal (as stated):** reduce the latency a user *perceives* when generating a stage,
specifically by taking the Phase-19 critic off the critical path so the usable draft
is delivered as early as possible. UX is the priority: "done" should mean done.

**Decision (made with the user):** **advisory-only** — drop the critic-triggered
auto-regenerate entirely. After the draft is delivered, run only the judge pass in the
background and attach its findings as the existing non-blocking suggestions. No
automatic regenerate, no silent artifact swap.

---

## 0. Findings that shaped this design

Three facts from the current code determine the only correct shape. They are
load-bearing, so they come first.

**Fact 1 — the critic is already advisory, but it runs *before* `done`.** Since issue
#34 the critic cannot block finalisation; its findings surface as non-blocking
suggestions via the persisted `Stage.quality_gate`
([`utils/qualityGate.ts:24-28`](../frontend/src/utils/qualityGate.ts#L24-L28),
`AdvisoryFindingsPanel`). But the judge call **and** an optional full regenerate still
run synchronously between the streamed draft and the `done` event
([`stage_manager.py:2280-2365`](../backend/services/pipeline/stage_manager.py#L2280-L2365)),
so the user waits for them.

**Fact 2 — an "inline, after-`done`" critic is unsafe and *feels* slower.** The SSE
pump only terminates when the **pipeline task returns**, and its `finally`
**cancels the pipeline on client disconnect**
([`stage_manager.py:1925-1932`](../backend/services/pipeline/stage_manager.py#L1925-L1932)).
The `db` session is **request-scoped** (passed in from the router). So if the critic
ran inline after emitting `done`:
- the pump would keep emitting `progress` heartbeats until the judge finished — the UI
  would look busy after the draft is ready (the exact lingering-loading feel we want to
  avoid);
- a user closing the tab the instant they get their draft (the common case) would trip
  `pipeline.cancel()` and kill the critic mid-run;
- the request-scoped session closes when the request ends, so it could not write
  findings later anyway.

**Fact 3 — the right vehicle already exists.** The best-effort LLM eval score already
runs *after* `done` as a detached background task: `_schedule_stage_eval`
([`stage_manager.py:369`](../backend/services/pipeline/stage_manager.py#L369)) creates
an `asyncio` task held in a module-level strong-ref set (`_BACKGROUND_EVAL_TASKS`), and
`_dispatch_stage_eval` opens its **own** short-lived `AsyncSessionLocal` —
"*never the request session, which the generation flow closes*"
([`stage_manager.py:271-284`](../backend/services/pipeline/stage_manager.py#L271-L284)).
That task is **not** the `pipeline` task, so the generator's `finally` never cancels it;
it survives client disconnect and has an independent DB session.

**Conclusion:** mirror `_schedule_stage_eval` for the critic. This is the smallest change
that gives least *perceived* latency (the pipeline returns the instant `done` fires) and
survives disconnect — and it is consistent with how post-`done` LLM work already happens.
A new arq worker job (see §6) is the alternative only if findings must survive a process
restart; for a non-blocking advisory, in-process parity with evals is the right call.

---

## 1. Current behaviour (what we are changing)

Inside `_execute_generation_pipeline`, after the artifact streams:

1. Zero-LLM section gate (`validate_sections`) — blocking, terminal on miss.
2. Zero-LLM depth checks (`validate_artifact_completeness`) — blocking.
3. **Critic judge pass** `critic_review` — one LLM call, **always**, unless the owner set
   `disable_critic` ([guard at `stage_manager.py:2232`](../backend/services/pipeline/stage_manager.py#L2232)).
4. **If the verdict fails → one platform-funded regenerate** `_regenerate_with_findings`
   ([`:2320`](../backend/services/pipeline/stage_manager.py#L2320)), possibly escalated to
   the mid tier, charged via `BILLING_CREDITS_CRITIC_REGEN`
   ([`:2351`](../backend/services/pipeline/stage_manager.py#L2351)), then re-validated for
   security. After `MAX_REGENERATES` the remaining findings become advisory
   ([`:2289-2298`](../backend/services/pipeline/stage_manager.py#L2289-L2298)).
5. Tech-safety gate `_ensure_technology_safe` — blocking
   ([`:2374-2406`](../backend/services/pipeline/stage_manager.py#L2374-L2406)).
6. Persist version, mark advisory (`_mark_quality_gate_advisory`,
   [def `:3173`](../backend/services/pipeline/stage_manager.py#L3173)), set cost outcome
   `critic_advisory` vs `passed` ([`:2465-2468`](../backend/services/pipeline/stage_manager.py#L2465-L2468)),
   cache, schedule eval.
7. `stream_reset` → replay → **`done`** ([`:2532`](../backend/services/pipeline/stage_manager.py#L2532)).

Steps 3–4 are the latency the user feels.

## 2. Target behaviour

1–2. Blocking cheap gates (sections, depth) — **unchanged, stay before `done`**.
3. Tech-safety gate — **stays before `done`** (it is blocking; delivering then yanking
   would be worse UX). It now runs against the streamed artifact directly (no critic
   regenerate has mutated it).
4. Persist draft (`quality_gate` cleared; cost outcome `passed` for now), cache, eval.
5. `stream_reset` → replay → **`done`**. **The user has the usable draft here.**
6. **Schedule the critic** as a detached background task (judge only, no regenerate).
   The pipeline returns immediately → pump sends `_PIPELINE_END` → clean completion, no
   trailing heartbeats.
7. The background critic, on its own session: re-load the stage; **if its version still
   matches** the scheduled version (staleness guard), and the verdict fails → attach
   findings via `_mark_quality_gate_advisory`, commit, and update the cost outcome to
   `critic_advisory`. Fail-open: any judge error is logged and dropped, never touching the
   already-delivered draft.

**Net latency win:** every generation drops a judge call from the critical path, and the
fraction that previously failed the critic drops a *whole extra generation*. **Cost win:**
`BILLING_CREDITS_CRITIC_REGEN` charges go to zero.

---

## 3. Changes by component

### 3.1 `backend/services/pipeline/stage_manager.py`
- **Remove** the inline critic `while` loop (judge + regenerate + quality escalation +
  security re-validation), [`:2280-2365`](../backend/services/pipeline/stage_manager.py#L2280-L2365).
- Keep `validate_sections`, depth checks, and `_ensure_technology_safe` on the
  pre-`done` path.
- At persist, set cost outcome to `passed` and clear the quality gate (no `advisory_findings`
  known yet).
- After the existing `done` emit ([`:2532`](../backend/services/pipeline/stage_manager.py#L2532)),
  call a new `_schedule_critic_review(...)` (skip when `workspace.disable_critic`).
- Drop the now-unused `_regenerate_with_findings` call site, `MAX_REGENERATES` loop, and
  the `critic_regen` cost context from this path (keep the helpers if referenced elsewhere;
  remove if not).

### 3.2 New `_schedule_critic_review` / `_dispatch_critic_review` (mirror the eval pair)
- `_schedule_critic_review(*, stage_id, version, stage_type, content, critic_deps, provider, content_generation_id)`:
  `asyncio.create_task(_dispatch_critic_review(...))`, add to a module-level
  `_BACKGROUND_CRITIC_TASKS` strong-ref set, attach discard + error-log done-callbacks —
  identical lifecycle to `_schedule_stage_eval` ([`:369`](../backend/services/pipeline/stage_manager.py#L369)).
- `_dispatch_critic_review(...)` (own `AsyncSessionLocal`):
  1. `await critic_review(stage_type, content, critic_deps, provider=provider)` — judge only.
  2. Re-load the stage; **abort if `stage.current_version != version`** (a newer generation
     superseded this one) — staleness guard prevents stamping findings onto the wrong draft.
  3. If `not result.passed`: `_mark_quality_gate_advisory(stage, result.findings)`, commit,
     `update_cost_event_quality_outcome(content_generation_id, "critic_advisory")`.
  4. Wrap everything in try/except → log + drop. Fail-open is mandatory: the draft is
     already delivered and charged.
- `critic_deps` are plain strings (`_workspace_stage_deps`), so they pass by value into the
  detached task without holding ORM objects.

### 3.3 Config flag — `backend/config.py`
- Add `critic_async_advisory: bool = True` (pattern: `llm_prompt_cache_enabled`,
  [`config.py:88`](../backend/config.py#L88)).
- `True` → new background path. `False` → retain the existing inline critic+regenerate
  loop verbatim for one release (instant revert if UX/quality regresses). Remove the old
  branch in a follow-up once the new path is proven.

### 3.4 Frontend — surface findings that now arrive after `done`
- Advisory findings derive purely from `stage.quality_gate`
  ([`qualityGate.ts:24-28`](../frontend/src/utils/qualityGate.ts#L24-L28)); today's single
  post-`done` refetch is now too early.
- Add a **short delayed refetch / bounded poll** of the stage after `done` (e.g. 2–3 polls
  over ~10–15s, stop once `quality_gate.status === "advisory"` or a clean result, or on
  timeout). `AdvisoryFindingsPanel` renders unchanged when findings land.
- No new SSE event — the stream still ends cleanly at `done`.

---

## 4. Billing & telemetry
- `BILLING_CREDITS_CRITIC_REGEN` is no longer incremented from the stage path (pure
  savings; the regenerate was platform-funded).
- Keep `record_judge_call` instrumentation inside the background judge so critic spend is
  still attributed.
- **Add a counter** for "critic verdict failed (advisory)" so we can monitor how often the
  dropped auto-regenerate *would* have fired — this is the signal for the quality tradeoff
  we are accepting.

## 5. Edge cases & risks
- **User regenerates / finalises before the critic finishes.** The version staleness guard
  (§3.2.2) skips stamping findings onto a superseded version. Writing advisory findings to
  an already-finalised stage is harmless (advisory never blocks finalise), but the guard
  also covers it cleanly.
- **Quality tradeoff (accepted).** Dropping the one platform-funded regenerate means the
  delivered artifact is the first draft. The critic only ever regenerated once and often did
  not fully resolve findings; the user can still regenerate manually. Monitor via §4 counter.
- **Durability (accepted tradeoff).** An in-process task is lost if the process restarts
  mid-flight → findings missing for that one generation. This matches the existing eval
  score's guarantee and is acceptable for a non-blocking advisory. See §6 for the durable
  alternative.
- **Fail-open is non-negotiable.** A judge outage must never affect the delivered draft.

## 6. Alternative considered — arq worker job
Run the judge as an arq job in [`worker.py`](../backend/worker.py) (enqueue via
[`services/queue.py`](../backend/services/queue.py)), keyed/idempotent on the stage version,
with its own session and bounded retries. **Pro:** survives process restarts/deploys.
**Con:** more infrastructure and a new job type for what is a non-blocking suggestion.
**Decision:** not chosen for v1 — in-process parity with the existing eval score (§0 Fact 3)
is simpler and consistent. Revisit only if advisory findings must survive a deploy window.

## 7. Testing
- **Unit (backend):**
  - With `critic_async_advisory=True`, `critic_review` is **not** awaited inside
    `_execute_generation_pipeline`; `done` is emitted before any judge call.
  - `_dispatch_critic_review`: failing verdict → marks advisory + updates cost outcome;
    passing verdict → no change; version-mismatch → no write; judge raises → swallowed.
  - `critic_async_advisory=False` → existing inline critic+regenerate behaviour preserved.
- **Contract:** update harness contract tests that assert pre-`done` critic-regen behaviour.
- **Frontend:** delayed poll surfaces advisory findings; blocked-gate handling unchanged.
- **Manual (per repo rule):** rebuild and run the stack; generate a stage; confirm the draft
  appears without the judge/regenerate wait and findings appear a few seconds later.

## 8. Non-goals
- No change to the blocking gates (sections, depth, tech-safety) — they stay synchronous.
- No "propose the regenerate as a diff" flow (option B from discussion) — explicitly out of
  scope for advisory-only.
- No durability/arq work in v1 (§6).

## 9. Rollout
1. Land behind `critic_async_advisory` (default **True**), old path retained.
2. Rebuild + run; verify draft latency drop and findings surfacing.
3. Watch the §4 counter + advisory rate for a quality regression signal.
4. Follow-up PR: delete the inline critic+regenerate branch once proven.
