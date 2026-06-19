# Eval / Judge Rework Plan (Issue #27)

Spend judge-model calls **only where the result gives the user a concrete next action,
blocks a harmful output, or improves internal model/routing quality** — and stop spending
them on a vague, user-facing `Eval 87/100` number that reassures without telling anyone what
to do. This reduces operational cost (a judge call removed from most generations) **without**
weakening any deterministic validator, the critic safety gate, or task traceability.

This plan is grounded in the current code, not the issue text. The issue frames the work as
"cut or hide the eval score." The grounded read shows the harder, more important truth: the
single `eval.score` judge call produces **three outputs of very different value**, and the most
actionable of them (deterministic task traceability) is **structurally coupled** to the LLM
call it should be independent of. The spine of this work is **decoupling**, not deletion.

> **Current baseline (grounded read of the live code).** After a stage streams and passes the
> quality gate, `StageManager.generate()` calls `_schedule_stage_eval` (`stage_manager.py:2276`,
> `:2795`, `:3484`), which routes through `_dispatch_stage_eval` (`:243`) → either the provider
> batch path (`llm_batch_enabled`) or `run_eval_background` → `run_eval` (`online_eval.py:771`).
> `run_eval` calls `_score_with_retry` (full prompt **and** a compact-prompt retry), and on a JSON
> parse miss calls `_score_with_retry` **again** — up to **four** judge attempts per stage. The
> generation flow then *blocks the stream up to 30s* on the eval via `asyncio.shield`/`wait_for`
> (`:2298`, `:3496`) before emitting `{"eval": …}`. That one call produces three things:
> **(1)** `overall_score`/`completeness`/`clarity` — the vague number rendered by
> `QualityBadge.tsx` and the `87/100` sidebar signal (`Workspace.tsx:1698`); **(2)** harness
> `coverage_percent` + `uncovered_reqs` — LLM-derived, *actionable*, with **no deterministic
> replacement**; **(3)** tasks `tasks_without_ref`/`flagged` — already **deterministic** via
> `_validate_task_references` (`online_eval.py:441`) when harness content is present, the judge's
> version only a fallback. The trap: `_validate_task_references` runs **inside** `_persist_eval_data`
> (`:909`), gated behind a successful judge call. Naively "disabling the eval" silently kills the
> deterministic task validation and the coverage panel too. The deterministic path already exists
> standalone in `POST /stages/{id}/revalidate-tasks` (`stage.py:463`) — it creates an
> `EvalResult(overall_score=None, …)` with structural results only, no LLM call. That endpoint is
> the template for what generation should do inline.

---

## 1. Current state vs. issue assumptions

| # | Issue proposal / premise | Reality in code | Classification |
|---|--------------------------|-----------------|----------------|
| premise | "Cut or hide the generic eval score" is the core change | True for the *number*, but the same judge call also produces harness coverage and (a fallback for) task traceability. "Disable the eval" is too coarse | **Reframe — split the three outputs, decouple before cutting** |
| 1 | `eval.score` is a candidate for removal/sampling | Valid. The score is the weakest user-facing signal; it costs up to 4 judge attempts and blocks the stream up to 30s (`:2298`) | **Cut from UI; sample for telemetry behind a rate flag** |
| 2 | Deterministic task validation is high value and should stay | True and **at risk**: `_validate_task_references` lives *inside* `_persist_eval_data` (`:909`), so it only runs after a successful judge call today | **Decouple — extract a shared inline helper; run with no judge** |
| 2 | HARNESS coverage gaps should remain visible "when available" | `coverage_percent`/`uncovered_reqs` are **LLM-derived** (`_STAGE_PROMPTS["harness"]`); there is no deterministic equivalent. Dropping the score drops this too | **Product fork — see Decision A; keep it, decoupled from the score** |
| 3 | Critic gate has real value; run it selectively after deterministic checks | Per CLAUDE.md the critic *already* runs after `validate_sections` (terminal `MissingSectionError`) and `validate_artifact_completeness`; those block before the judge | **Largely already satisfied — verify ordering; optional verdict cache** |
| 4 | PR-diff judging should be opt-in / tiered / manual | `pr_evaluator.run_pr_check` already has daily budget, debounce, head-SHA dedup, diff caps, fail-open neutral — but no on/off/manual *mode* setting; it runs on every routed push | **Valid — add a `pr_check_mode` gate; keep existing cost controls** |
| 5 | Clarification questions are a separate use case; keep separate | `spec_clarifier` is independent of post-generation eval already; SPEC retries already reuse saved answers | **No change — explicitly out of scope** |
| FE | Replace numeric score with an actionable status | `QualityBadge.tsx` renders `score/100`; `Workspace.tsx:1698` shows `87/100` / `Awaiting eval` in the sidebar | **Valid — status derived from findings, not score** |
| FE | Public/shared pages must not expose internal judge failures | Already clean: `routers/public.py` exposes **no** eval/score field (the `publicShare.ts` type carries `overall_score` but the backend never populates it) | **Already satisfied — preserve; assert in tests** |
| Ops | Add metrics for judge calls by purpose + skipped-by-reason | Only `EVAL_POLL_FAILURES` exists; no per-purpose judge counter, no skip-reason counter | **Valid — new counters; the before/after spend instrument** |

**Net:** this is a **decouple-then-cut** change, not a pure deletion. The backend work is
surgical (extract one deterministic helper, gate the LLM score at the single `_dispatch_stage_eval`
chokepoint, drop the 30s stream-block on the common path); the frontend work swaps a number for a
findings-derived status. The tempting "just stop scheduling the eval" shortcut would regress task
traceability and harness coverage — both named in the acceptance criteria — so it is explicitly
rejected.

---

## 2. Guardrails (apply to every phase)

- **No deterministic validator is removed or weakened.** `_validate_task_references`,
  `_validate_task_fields`, and the harness coverage finding all survive. Cutting the *score* must
  never cut a *finding*.
- **The critic safety gate is untouched in behavior.** Fail-open, bounded schema (no artifact
  bytes), one-regenerate cap, owner `disable_critic` escape hatch all stay exactly as they are.
  Phase 3 only *confirms* ordering and optionally *caches* identical verdicts — it never makes the
  gate more permissive.
- **Deterministic findings run inline and always.** Task traceability is microsecond regex
  parsing; it must run on every generation **without** a judge call and **without** blocking the
  stream. The judge becomes optional, the validators do not.
- **One chokepoint for the LLM score decision.** Sampling is gated in `_dispatch_stage_eval`
  (`:243`) so it covers all three `_schedule_stage_eval` sites *and* the batch path in one place.
  No per-call-site edits.
- **Harness coverage is a retained finding, not collateral of the score.** (Decision A.) It
  survives even when `overall_score` is sampled out.
- **Public/shared surfaces never expose a judge failure or internal score.** Already true; keep it
  true with a test.
- **No user workflow is blocked by a judge outage** unless a deterministic safety gate blocks it
  (unchanged from today's fail-open critic).
- **Contract tests move *with* the contract, visibly.** The harness contract tests below are
  intentionally frozen; changing them is a deliberate, called-out part of the PR, not a silent edit.

---

## 3. Decisions (recommended, stated out loud)

**Decision A — Harness coverage: KEEP it, decoupled from the score.**
`coverage_percent`/`uncovered_reqs` is LLM-derived but the most actionable thing the judge
produces, and the acceptance criteria require "HARNESS coverage gaps remain visible when
available." Dropping it with the score is cleaner to build but **fails the issue's own ACs**.
Recommendation: on harness stages, the coverage finding survives sampling — either always-sample
harness, or run a coverage-only judge pass independent of the score sample rate. The vague
`overall_score` still goes away from the UI; the coverage *finding* stays. *This is the one call
that, if made wrong, ships a plan that fails its own acceptance criteria.*

**Decision B — Sample rate: a single global `EVAL_SCORE_SAMPLE_RATE`, default `0.0`.**
Follows the `llm_batch_enabled` flag pattern (one flag, no redeploy to flip). Users see no number
by default; raise the rate only for internal telemetry batches. Per-user / per-workspace /
per-provider granularity (the issue's open question) is **deferred** — noted as future, not built
now, to keep Phase 1 small.

**Decision C — Users never see a numeric quality score by default.** The primary surface becomes
a findings-derived status (`Ready` / `Needs attention` / `Checking` / `Unavailable`). Any sampled
score is internal telemetry only. (Revisit only if a concrete user need for a number appears.)

---

## 4. Phased plan

### Phase 0 — Per-purpose judge metrics (instrument first) *(foundation; proves the savings)*

- Add `judge_calls_total{purpose="eval.score"|"critic"|"pr_check"|"clarify"}` and
  `judge_calls_skipped_total{reason="sampled_out"|"deterministic_gate"|"disabled"|"budget"|"debounce"|"cached"}`
  in `services/observability.py`, incremented at each judge call site.
- This is the before/after spend instrument the issue's Validation Plan asks for; it ships first so
  Phase 1's reduction is measurable, not asserted.

### Phase 1 — Decouple deterministic findings + cut the user-facing score *(the substantive phase)*

**Backend**

1. Extract `validate_stage_findings(stage_type, content, harness_content) -> (tasks_without_ref, flagged)`
   from `_persist_eval_data` (`online_eval.py:909-924`). Both `revalidate-tasks` (`stage.py:490`)
   and the generation flow call it. Pure regex, no LLM.
2. In `StageManager.generate()`, run that helper **inline** after the gate passes, persist a minimal
   `EvalResult` (score fields `null`, structural findings populated) and emit the existing
   `{"eval": …}` SSE **immediately**. This lets us **delete the 30s `asyncio.shield`/`wait_for`
   block** on the common path (`:2298`, `:3496`) — a latency win on every generation, not just a
   cost win.
3. Gate the LLM score at the single chokepoint `_dispatch_stage_eval` (`:243`): consult
   `EVAL_SCORE_SAMPLE_RATE` (Decision B). Sampled out ⇒ no judge call (increment
   `judge_calls_skipped_total{reason="sampled_out"}`), structural `EvalResult` already persisted by
   step 2. Sampled in ⇒ existing background/batch score path runs and *updates* the row's score
   fields. Harness coverage honored per Decision A.
4. Keep `_score_with_retry`'s retry behavior **only** on the sampled path; remove the score-only
   double-parse-retry loop's reach into the common path (it no longer runs every generation).

**Frontend**

5. Replace `QualityBadge.tsx`'s `score/100` with a status component derived from **findings, not
   score**: `Ready` (no genuine gaps, not `flagged`), `Needs attention` (genuine gaps OR `flagged`
   OR `uncovered_reqs`), `Checking` (validation in flight), `Unavailable` (validation couldn't
   complete — quiet, non-blocking, no infinite shimmer).
6. Remove the `87/100` / `Awaiting eval` sidebar signal (`Workspace.tsx:1695-1701`). Keep
   `CoveragePanel.tsx` and `TaskValidationPanel.tsx` prominent whenever they have findings.
7. Drop primary UI emphasis on `overall_score`; leave the field on the type as nullable telemetry.

### Phase 2 — Sampling flag wiring + config *(small)*

- Add `eval_score_sample_rate: float = 0.0` to `config.py` (Decision B), documented next to
  `llm_batch_enabled`. Validate `0.0 ≤ rate ≤ 1.0`.
- Wire it into `_dispatch_stage_eval`'s gate (Phase 1 step 3). Harness-coverage carve-out lives here
  too (Decision A).

### Phase 3 — Critic: confirm, don't rebuild *(verify + optional cache)*

- **Confirm** in `stage_manager` that `validate_sections` (terminal) and
  `validate_artifact_completeness` run *before* `critic_review`, so the critic is already skipped
  when a deterministic gate blocks. Add a regression test that asserts this ordering, and increment
  `judge_calls_skipped_total{reason="deterministic_gate"}` when it happens.
- **Optional:** artifact-hash + prompt/policy-version verdict cache so an identical regeneration does
  not re-pay the critic judge (`reason="cached"`). Keep fail-open, bounded schema, one-regenerate cap
  **unchanged**. (Open question — cache key = artifact hash **plus** prompt/policy version — answered
  here: yes, both.)

### Phase 4 — PR-diff judging becomes controllable *(peripheral)*

- Add a `pr_check_mode` setting (`off` | `manual` | `auto`, default `manual` or `off`) at the
  workspace/installation level, gated in `pr_evaluator._run_pr_check` before any judge call.
- Keep the existing daily budget / debounce / head-SHA dedup / diff caps / fail-open-neutral check.
  Make the posted GitHub check copy explicit when skipped by setting (`reason="disabled"`).
- (Open question — workspace vs. GitHub-integration vs. billing-plan setting — recommend the
  GitHub-integration/installation level, matching where budgets already live.)

### Phase 5 — Internal quality learning stays, sampled *(telemetry hygiene)*

- The sampled score (Phase 2) continues to feed Langfuse `score_generation` + the high/low dataset
  routing (`_dataset_for_score`) — but only on sampled generations, not every user workflow.
- Store enough metadata (stage_type, provider, model, score) to compare model/provider quality
  without charging every generation for full eval coverage.

---

## 5. Blast radius — "production ready" = green CI at 80% coverage

**Harness contract tests (frozen — move *with* the contract, called out in the PR):**
- `harness/tests/frontend/phase4-navigator-quality-badge.contract.test.tsx` — asserts the numeric
  score renders; update to the new findings-status contract.
- `harness/tests/frontend/phase6-eval-sse.contract.test.ts` — asserts the `{"eval": …}` SSE shape;
  the shape is preserved (score fields just become `null` on the common path), but verify.
- `harness/schemas/public-workspace.schema.json` keeps `overall_score` nullable — no change needed.

**Backend tests to add/update:** `tests/test_online_eval.py`, `tests/test_stage_manager.py`,
`tests/test_task_validation.py`, `tests/test_stage_router.py`, `tests/test_eval_batch.py`. New
assertions:
- Generation completes and emits structural findings **without scheduling a score-only eval** when
  sampled out.
- `tasks_without_ref` / `flagged` are produced with **no** judge call (deterministic path).
- Critic still runs when enabled/applicable; critic is **skipped** when a deterministic gate already
  blocks.
- Sampling honors `EVAL_SCORE_SAMPLE_RATE` (0.0 ⇒ never, 1.0 ⇒ always).
- Harness coverage finding survives sampling-out (Decision A).
- PR judge respects `off` / `manual` / `auto` / budget-reached.

**Frontend tests:** replace `QualityBadge` score tests with findings-status tests; assert no
`Eval 87/100` renders in the main workspace by default; assert `CoveragePanel` /
`TaskValidationPanel` still render concrete remediation; assert `Unavailable` is quiet and
non-blocking; assert public/shared pages expose no judge failure.

---

## 6. Acceptance criteria mapping

| Issue AC | Delivered by |
|----------|--------------|
| Generic numeric score no longer a primary user-facing control | Phase 1 (FE 5–7), Decision C |
| Users still see concrete quality issues when actionable gaps exist | Phase 1 (deterministic inline findings), Decision A |
| TASKS traceability validation runs without an LLM call | Phase 1 step 1–2 (decoupled helper) |
| HARNESS coverage gaps remain visible when available | Decision A + Phase 2 carve-out |
| Critic still blocks/regenerates but not when a deterministic gate decides | Phase 3 (verify ordering) |
| Score-only eval disabled by default / sampled | Phase 2 (`EVAL_SCORE_SAMPLE_RATE=0.0`) |
| PR-diff judging opt-in / tiered / manual by default | Phase 4 (`pr_check_mode`) |
| Fail-open behavior remains for judge outages | Guardrails (critic untouched; sampled score is best-effort) |
| No workflow blocked by a judge outage unless a deterministic safety gate blocks it | Guardrails + Phase 1 (findings are deterministic) |

---

## 7. Open questions — answered or deferred

- **Sampling granularity** (global / per-user / per-workspace / per-provider): **global** now
  (Decision B); finer granularity deferred.
- **Should users ever see a number?** No by default (Decision C); internal telemetry only.
- **PR-judge setting location:** GitHub-integration / installation level (Phase 4), matching budgets.
- **Critic verdict cache key:** artifact hash **plus** prompt/policy version (Phase 3).
- **Minimum deterministic validation before any judge:** sections present + completeness depth +
  (tasks) traceability — all already exist and run before the critic; the score adds nothing
  deterministic, which is why it is the one safe to sample.
