# Quality-Gate Recovery Plan (Issue #28)

Make a quality-gate failure after a long, expensive generation feel like a **helpful,
recoverable state** instead of a trap — **without** removing or weakening the gate. In the
observed `d3` case the gate was *correct*: the SPEC stopped mid-table at `FR-089` with no
NFR/AC refs and no completion sentinel. The defect is the end-to-end **product contract**
around that correct block, not the block itself.

This plan is grounded in the current code, not the issue text. Several of the issue's
"proposed fixes" describe a deeper change than the code actually needs (a new DB status,
a new credit-free endpoint); the grounding below shows the same user outcome is reached
with a derived-contract + single-source-of-truth change and no migration.

> **Current baseline (grounded read of the live code).** An incomplete generation already
> does the right things in the data layer: `_block_incomplete_output` (`stage_manager.py:3016`)
> **refunds** the failed attempt, then `_persist_quality_gate_blocked` (`:3060`) saves the
> partial as a new version with `quality_gate_status="blocked"`, `quality_gate_kind="incomplete_output"`,
> `quality_gate_version=current_version`. All **four** gate kinds persist this way
> (`incomplete_output`, `technology_safety`, `missing_sections`, `critic_findings`), so the
> blocked state **already survives refresh** via the `Stage.quality_gate` property (`models/stage.py:110`).
> What's wrong is *presentation and messaging*: (a) the partial saves as a normal `draft` with
> normal draft affordances; (b) `finalise()` raises bare `ValueError` strings (`:2511,:2526`) that
> the router flattens to a 409 string, and the frontend then **overwrites even that** with the
> generic `"Only draft stages can be finalised."` (`Workspace.tsx:1229`); (c) the finalise-disable
> reads a **second, dismissable** source of truth (the SSE-driven `qualityGateMap`) instead of the
> authoritative stage object; (d) `Dismiss` deletes that map entry, hiding the only on-screen
> explanation while the backend stays blocked.

---

## 1. Current state vs. issue assumptions

| # | Issue proposal / premise | Reality in code | Classification |
|---|--------------------------|-----------------|----------------|
| premise | Backend is *wrong* to block the `d3` SPEC | **Correct block.** Partial ended at `FR-089`, no NFR/AC, no sentinel; `validate_completion_sentinel` + `validate_artifact_completeness` rightly failed | **Keep the gate — fix the UX around it** |
| BE | "Represent blocked output as a **distinct recovery state**, not just `draft + blocked`" | The state is *already* distinct in data (`quality_gate_kind`, `quality_gate_status="blocked"`, `quality_gate_version`). What's missing is a **derived recovery contract** for the frontend, not a new `status` enum | **Derive, don't migrate — enrich `Stage.quality_gate`** |
| BE | "Ensure finalise 409s are **structured** (`{error, kind, message, recovery}`) not bare strings" | `finalise()` raises `ValueError(str)` for all three gate branches; router (`stage.py:347`) wraps as `HTTPException(409, detail=str)` | **Valid — structured exception + router shape** |
| BE | "Add `recovery_action` / `retry_eligible_without_credit` flag; dedicated credit-free recovery endpoint" | `/regenerate` (`stage.py:170`) already **refunds the failed attempt**, so the user is never *net*-charged for a failure today. A new free path is an unbudgeted abuse surface | **Descoped (product decision): charge normally, communicate the refund honestly** |
| BE | "Revisit chunk repair so an early sentinel miss doesn't trigger more long calls" | `_generate_complete_artifact` (`:1165`) deliberately runs every chunk + a bounded repair pass; CLAUDE.md: "Chunked generation **always** runs every chunk — deliberately NO early return," and route changes "ride the Phase-5 golden-corpus gate" | **Carved out — separate, optional, corpus-gated workstream (Phase 4)** |
| BE | Recovery double-charges even though the failed attempt was refunded | Not true on the ledger: `_block_incomplete_output` refunds; the only friction is the `require_credits(10)` precheck + the confirm modal | **UX/messaging fix, not a billing fix** |
| FE | "Treat `quality_gate.status === 'blocked'` on the stage object as the source of truth" | Finalise-disable reads `qualityGateMap` (SSE-driven, dismissable) (`Workspace.tsx:480`); `handleFinalise` *separately* reads `activeStage.quality_gate` (`:1200`) — **two sources** | **Valid — collapse onto the stage object** |
| FE | "`Dismiss` should not hide the only explanation" | `handleGateDismiss` (`:924`) deletes the `qualityGateMap` entry; the store *does* re-derive it from `stage.quality_gate` on the next `setStage`/`setStages`, but the disable + panel are gone until then | **Valid — make Dismiss a non-destructive "Hide details"** |
| FE | "Replace generic finalise catch copy with backend-derived recovery copy" | `handleFinalise` catch collapses **all** errors to `"Only draft stages can be finalised."` (`:1229`) | **Valid — surface the structured 409 message** |
| FE | "Label blocked drafts as `Blocked partial draft` / `Needs regeneration`" | Blocked partial renders as an ordinary draft document | **Valid — visual labeling** |
| FE | "Recovery survives refresh" | Already true: `setStages` re-derives the gate from `stage.quality_gate` on load (`stageStore.ts:66`); the `quality_gate_failed` SSE path rejects → `useStream` catch refetches the stage (`useStream.ts:100`) | **Already works — preserve it; verify in tests** |

**Net:** this is a **contract + presentation** change, not a pipeline or schema change. The
backend work is small and surgical (one structured exception, one enriched derived property);
the frontend work is the bulk (single source of truth, honest copy, non-destructive dismiss,
blocked-draft labeling). The tempting deeper changes — a new `status` value, a credit-free
recovery endpoint, an early-bail in the chunk loop — are each **descoped or carved out** for
the reasons in the table, and the same user outcome is reached without them.

---

## 2. Guardrails (apply to every phase)

- **The gate is never weakened to make recovery nicer.** `incomplete_output` and
  `technology_safety` stay **non-overridable** (`override_quality_gate` `:3108`/`:3112`);
  `missing_sections` and `critic_findings` stay overridable. Recovery = regenerate (or override
  where allowed), never "let the partial through."
- **No new DB status enum, no migration.** The recovery state is *derived* from existing
  columns. Adding a `status` value would touch `ck_stages_status`, every status switch, and need
  a backfill — disproportionate to a presentation fix.
- **One source of truth for finalise-blocking:** the persisted `Stage.quality_gate`. The
  SSE `qualityGateMap` is demoted to a transient streaming hint and must never be the thing that
  decides whether finalise is allowed.
- **Honest billing copy, real refund.** Recovery charges the normal credit (your product call),
  and the UI states plainly that the failed attempt was refunded. We do not imply "free" nor
  silently double-charge.
- **No change to which model runs, or to the chunk loop, in this issue.** Any such change rides
  the Phase-5 golden-corpus gate from issue #26 (Phase 4 here is explicitly deferred/optional).
- **Regression tests cover all gate kinds**, not just the `incomplete_output` repro: the AC names
  `incomplete_output`, `critic_findings`, and `technology_safety`.

---

## 3. Phased plan

### Phase 0 — Backend contract: structured finalise 409 + derived recovery payload *(foundation; the frontend depends on it)*

**Why first:** the honest frontend copy and single-source disable need a backend-authoritative
recovery contract to render. Ship the contract before the UI that consumes it.

1. **Structured finalise exception.** Add `QualityGateBlockedError(kind, message, recovery)` near
   `INCOMPLETE_OUTPUT_GATE_KIND` (`stage_manager.py:~743`). In `finalise()` (`:2507-2529`) replace
   the three gate `ValueError`s (incomplete / tech_safety / generic-blocked) with it, each carrying
   `kind` and a `recovery` dict. **Leave the `status != "draft"` branch (`:2506`) a plain
   `ValueError`** — it's not a gate block, and `test_finalise_integration.py:179` /
   `test_concurrency.py:186` assert its `"cannot be finalised"` string.
2. **Router shape.** In `finalise_stage` (`routers/stage.py:347-351`) catch `QualityGateBlockedError`
   → `HTTPException(409, detail={"error": "quality_gate_blocked", "kind", "message", "recovery"})`;
   keep the existing `ValueError` → 409-string catch for the status branch.
3. **Derived recovery contract.** Enrich the `Stage.quality_gate` property (`models/stage.py:110`)
   with a `recovery` block: `{"action": "regenerate", "overridable": <kind not in non-overridable>,
   "credit_required": 10, "refunded_prior_attempt": True, "message": <kind-specific>}`. Pure
   derivation, no migration; `StageResponse` already serializes `quality_gate`, so it ships in every
   stage GET and survives refresh natively.
4. **Update the two broken assertions:** `test_stage_manager.py:1475` ("blocked by the quality gate")
   and `:1519` ("unsafe technology choices") now assert `QualityGateBlockedError` + structured fields.
   Override-path tests (`:1571/:1594`) are untouched.

**Acceptance:** finalise on any blocked current version returns a structured 409 with `kind` +
`recovery`; the stage object exposes a `recovery` contract. (Issue ACs 3, 6.)
**Risk:** low — only the three gate branches change type; grep-confirmed test impact is 2 assertions.
**Effort:** S.

---

### Phase 1 — Frontend: one authoritative gate source + honest finalise

**Why early:** the highest-leverage, lowest-risk change. The `quality_gate_failed` SSE path already
refetches the stage (`useStream.ts:100`), so `activeStage.quality_gate` is reliably populated the
moment the gate fires and after every refresh — switching the disable onto it removes the
dual-source bug with no new data plumbing.

1. **Disable source** (`Workspace.tsx:480-487`): derive `qualityGateBlocked` and the disable message
   from `activeStage.quality_gate?.status === "blocked"` and its `recovery.message`, **not**
   `qualityGateMap`. Demote `qualityGateMap` to a transient streaming hint.
2. **Honest finalise catch** (`:1228-1229`): parse the structured 409
   (`err.response?.data?.detail?.message` / `.recovery`) and surface it; fall back to generic copy
   only when no structured detail exists. Kill the blanket `"Only draft stages can be finalised."`
   for gate blocks.
3. **Types:** add `recovery?: { action; overridable; credit_required; refunded_prior_attempt; message }`
   to `QualityGateInfo` (`types/stage.ts:32`).

**Acceptance:** finalise is blocked by a single authoritative source; finalise errors show the
backend gate reason, never the generic draft-only copy. (Issue ACs 3, 4, 6.)
**Risk:** low. **Effort:** S.

---

### Phase 2 — Frontend: persistent blocked state + non-destructive dismiss

**Why:** the issue's core complaint — a big partial document + a disabled button + a `Dismiss` that
hides the explanation. Make the blocked state legible and durable.

1. **Blocked partial draft labeling:** when `activeStage.quality_gate?.status === "blocked"`, render
   a banner/badge on the document ("Blocked partial draft — needs regeneration") so it never reads as
   an ordinary, finalisable draft.
2. **Dismiss → "Hide details":** `handleGateDismiss` (`:924`) currently deletes the dismissable map
   entry. Change it so collapsing the panel leaves a **persistent blocked chip** (rendered off
   `activeStage.quality_gate`, not the dismissable map) plus the disabled-finalise reason. Rename the
   button "Hide details".
3. **Accessible disabled reason:** finalise disabled with a nearby **visible** note +
   `aria-describedby`, not only a `title` tooltip (`GenerateBar.tsx:98-99`).

**Acceptance:** a blocked SPEC looks blocked, not finalisable; the blocked explanation survives both
local dismissal and refresh; the disabled reason is visible and accessible. (Issue ACs 1, 2, 5.)
**Risk:** low-med (UI surface). **Effort:** M.

---

### Phase 3 — Frontend: recovery CTA with honest refund copy

**Why:** close the "feels punitive" gap with messaging, per the product decision to charge normally.

1. **Primary CTA** for incomplete-output (and tech-safety) blocks: "Retry generation," sub-copy
   "Your previous attempt was refunded." For overridable kinds keep "Override and continue"
   (`StreamingOverlay.tsx:111` `canOverride`); for incomplete/tech keep override hidden.
2. **Drop confirm-modal friction** on recovery where it adds nothing — the retry routes through the
   existing `/regenerate` (refund-on-failure intact); the precheck stays as the balance guard.

**Acceptance:** recovery is explicit and not confusing; copy makes the refund/recovery behavior clear.
(Issue AC 5.) **Risk:** low. **Effort:** S.

---

### Phase 4 — *(Optional, carved out — NOT this PR)* early-bail on unrecoverable chunks

**Why deferred:** CLAUDE.md states chunked generation *deliberately* runs every chunk with no early
return, and any change to generation routing rides the Phase-5 golden-corpus gate (issue #26). The
issue only says "consider." Bundling it would drag this UX fix through the corpus gate and next to a
deliberate invariant.

**If pursued separately:** detect a repeated `provider_stopped_by_limit` on the **same** chunk at the
doubled/max budget (`_completion_stopped_by_limit` `:1053`, `_repair_budget` `:515`) and stop before
the full-artifact repair pass — the model is over-producing (89 FRs, truncated) and a third long call
won't help. Gate it behind the golden-corpus review; ship independently of Phases 0–3.

**Acceptance:** a known-unrecoverable early chunk does not spawn additional multi-minute calls before
the block surfaces. (Issue "Suggested tests" #4.) **Risk:** med-high (touches the generation loop +
corpus gate). **Effort:** M.

---

## 4. Validation plan (per the issue)

**Backend** (`tests/test_stage_manager.py`, new cases):
- finalise on an `incomplete_output` blocked version → structured 409 (`kind`, `recovery`,
  `overridable: false`).
- finalise on a `technology_safety` blocked version → structured 409, `overridable: false`.
- finalise on `critic_findings` / `missing_sections` blocked versions → structured 409,
  `overridable: true`.
- a generation with a missing completion sentinel persists `quality_gate_status="blocked"` +
  `quality_gate_kind="incomplete_output"` and a structured `quality_gate.recovery` payload.
- recovery via `/regenerate` after an incomplete block does not net-charge — assert the failed
  attempt's refund row in `credit_ledger`.

**Frontend** (`__tests__/WorkspaceFlow.test.tsx`, `components/workspace/StreamingOverlay.test.tsx`):
- a blocked incomplete SPEC renders as a "Blocked partial draft," not a normal draft.
- finalise stays disabled with a visible/accessible reason, including after a simulated stage refetch.
- "Hide details" collapses the panel but the blocked chip + reason remain.
- finalise failure shows the backend `recovery.message`, not the generic draft-only copy.
- the retry CTA copy mentions the refund.

A change promotes only if all three gate kinds behave correctly and no existing finalise/override
test regresses (the two intentionally-updated string assertions excepted).

---

## 5. Rollout order (dependency + risk ordered)

```
Phase 0  Backend contract: structured 409 + derived recovery payload   (foundation, low risk, S)
Phase 1  FE single authoritative gate source + honest finalise copy     (highest leverage, low risk, S)
Phase 2  FE persistent blocked state + non-destructive "Hide details"   (core UX, low-med risk, M)
Phase 3  FE recovery CTA with honest refund copy                        (messaging, low risk, S)
Phase 4  Early-bail on unrecoverable chunks   (OPTIONAL — corpus-gated, separate PR, NOT this issue)
```

Phase 0 leads because the frontend's honest copy and single-source disable both consume the
backend recovery contract. Phase 1 is pulled next as the single change that eliminates the
dual-source-of-truth bug at near-zero risk (the refetch path already guarantees the stage object is
authoritative). Phases 2–3 are presentation/messaging on top. Phase 4 is explicitly *not* part of
this issue — it touches the deliberately-invariant chunk loop and must ride the issue-#26 corpus gate.
