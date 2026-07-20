# Stage Screens Audit Remediation Plan

**Source:** End-to-end functional audit of the four stage screens (Spec / Plan / Harness /
Tasks), 2026-07-19. Thirteen findings (F1–F13): one High-severity data-corruption cluster,
four Medium functional/operational gaps, and a tail of Low/Info polish items.

**Goal:** Restore the content-integrity guarantee the product's USP claims. A user's
artifact must never be silently altered by the platform; every delivered version must
carry its quality signals; every advertised capability (version history) must be
reachable.

---

## Findings recap

| ID | Severity | One-line summary | Root location |
|-----|----------|------------------|---------------|
| F1 | **High** | Every manual edit bleaches the whole document; code-like content (`List<String>`, JSX, `<html>` mentions, `&`/`<`) is silently destroyed | `stage_manager.handle_content_edit` (`sanitize_text_async` over the full doc) |
| F2 | **High** | Refine permanently fails after F1's drift (editor raw doc vs bleached stored doc → `RefineSelectionError`), and the UI swallows the real error | `stage_manager.refine` raw-match + `Workspace.runRefine` catch |
| F3 | Medium | Sanitize-at-rest invariant is incoherent: `StageVersion.content` stores **raw** input while `stage.content` stores bleached; `rollback()` restores raw bytes with no re-sanitize | `handle_content_edit` + `rollback` |
| F4 | Medium | Generation-cache hits persist a new version but never persist/schedule an eval → "Quality: Unavailable" forever; common via starter templates (identical problem statements) | `stage_manager.generate` cached branch |
| F5 | Medium | `VersionHistoryPanel` is implemented + tested but never mounted; no UI path to restore an older version | `frontend/src/pages/Workspace.tsx` |
| F6 | Medium | Harness gap patch holds an idle DB transaction + FOR UPDATE row lock across the whole LLM stream; `db_idle_in_transaction_timeout_ms` (default 300 000) kills any patch streaming > 5 min | `stage_manager.generate_harness_patch` |
| F7 | Low | A network round-trip to `/auth/csrf-token` precedes every mutating request; the debounced auto-save doubles its traffic. **Constraint discovered:** CSRF tokens are single-use (Redis SETNX replay protection), so client-side token caching is NOT a valid fix | `api.ts attachCsrfHeader` + editor debounce |
| F8 | Low | `acceptDiff` / `rejectDiff` have no error handling → unhandled rejection, DiffViewer stuck open | `Workspace.tsx` |
| F9 | Low | Double-click Finalise / Keep fires a second POST that 409s and shows a spurious error toast | `Workspace.handleFinalise` / `handleAcknowledgeStale` |
| F10 | Low | GitHub-modal task count regex (`T-\d+:`) disagrees with `tasksParser` (`T-\d+\s*:`) → modal can preview 0 issues while the board shows N cards | `Workspace.tsx taskCount` |
| F11 | Low | `CreditConfirmModal` early-returns on `open === false` **before** `useRef`/`useFocusTrap` → latent hooks-order crash | `CreditConfirmModal.tsx` |
| F12 | Info | Gap patch (10 cr) and Refine (3 cr) charge without the credit-confirm modal; refine shows no cost anywhere | product decision |
| F13 | Info | Rejecting a refine diff spends 3 non-refunded credits, undocumented in the UI | product decision |

---

## Phase 1 — Content integrity cluster (F1 + F2 + F3) — ship together

> **Status: SHIPPED (2026-07-20).** At-rest bleach removed from `handle_content_edit`;
> refine feeds the raw selection/instruction into the keyed-nonce fences (the prompt-input
> bleach it also carried is gone); rollback documented as a plain byte copy; a boundary-local
> allowlist clean of the *rendered* HTML added at the one unprotected consumption point (PDF
> export). Regression tests cover byte-identity, rollback consistency, refine-after-edit,
> PDF sanitize, and frontend error surfacing. Verified live in-container: the real
> `PATCH /stages/{id}/content` path stores raw bytes end-to-end (stage + `StageVersion`
> byte-identical, `List<String>`/JSX intact), and a real PDF renders with script/handler
> payloads stripped while code and table alignment survive.

This is the release-blocking phase. The three findings share one root: sanitizing
markdown *source at rest* is the wrong layer, and it is applied inconsistently.

### Decision: stop bleaching stage content at rest

Store exactly what the user submitted (and what the model generated) in **both**
`stage.content` and `StageVersion.content`. Sanitization stays at the consumption
boundaries, where it already exists. This is the same layering argument the export
sanitizer shipped with (`sanitize_downstream_agent_content` — one choke point at the
boundary, not at rest).

### 1.0 Pre-flight: verify every consumption boundary independently sanitizes

Before removing the at-rest bleach, confirm each reader of `stage.content` is safe with
raw markdown (this is the safety argument for the whole phase — record the result in the
PR description):

- [ ] **Workspace render** — `MarkdownRenderer` runs `rehype-sanitize` (verified in audit). ✔ already safe.
- [ ] **Public share page** (`/p/:slug`, `PublicWorkspaceView`) — confirm it renders through the same `MarkdownRenderer` (or equivalent sanitizing renderer), not `dangerouslySetInnerHTML`.
- [ ] **PDF export** (`services/pipeline/pdf_export_service.py`) — confirm the markdown→HTML conversion escapes/sanitizes before WeasyPrint. If it does not, add a bleach pass **inside the PDF builder** (boundary-local, fence-aware not required for print output).
- [ ] **ZIP / AGENTS.md / CLAUDE.md exports** — `agents_md_builder` + `agent_manual_service` already route harvested excerpts through `sanitize_downstream_agent_content` and the downstream-command guard (verified in the 2026-07-16 security review). ✔ already safe. Confirm the raw-markdown files included verbatim in the ZIP are *intended* to be verbatim (they are — they're the user's artifact).
- [ ] **LLM prompts** (downstream stage generation, refine, critic, eval) — upstream artifacts are wrapped in untrusted-content fences with the keyed nonce; raw `<` is not an injection vector there. ✔ already safe.
- [ ] **Storyboard source layer** — confirm `storyboard_source.py` / renderer sanitize at their boundary.

Any boundary found unprotected gets its own boundary-local sanitize in this phase —
never a return of the at-rest bleach.

### 1.1 Backend changes

`backend/services/pipeline/stage_manager.py`:

1. **`handle_content_edit`**: replace
   `stage.content = await sanitize_text_async(new_content)` with
   `stage.content = new_content`. Keep everything else (version bump, staleness,
   tech-safety check, structural eval persist, background eval schedule).
   - Add the same prompt-injection **scan** the refine path uses
     (`scan_async(new_content)` → `SecurityError` on match) if review concludes edited
     content can reach a prompt without fencing. (Default: not needed — all prompt
     insertion points are fenced — but decide explicitly, in the PR.)
2. **`rollback`**: no change needed once (1) lands — `version.content` and
   `stage.content` are now the same policy (raw). Add a comment stating the invariant:
   *"StageVersion.content and Stage.content store identical bytes for a given version;
   sanitization happens at consumption boundaries only."*
3. **Grep for other at-rest sanitize call sites** on stage content
   (`sanitize_text_async(new_content)` was the only one found in audit; re-verify).

No DB migration: existing bleached rows are valid markdown, just degraded. The raw
originals of user edits survive in `StageVersion.content` (`created_by="user"`), so
users can recover via version restore once F5 (Phase 3) ships.

### 1.2 Frontend change (F2 error surfacing)

`frontend/src/pages/Workspace.tsx`, `runRefine` catch block:

```ts
} catch (error) {
  setGenericError(
    getApiErrorMessage(error, "Refine failed. Check your selection and try again."),
  )
}
```

so a `selection_mismatch` 409's structured message (and 402/429 details) reaches the
user instead of the fixed string. With F1 fixed, the mismatch itself should no longer
occur in the edit flow, but the honest error remains correct for genuine races
(another tab edited the stage).

### 1.3 Tests (Phase 1)

Backend (`backend/tests/test_stage_manager.py`):

- **Byte-identity round-trip (the F1 regression):** `handle_content_edit` with a
  document containing `List<String>`, `const el = <Button onClick={fn} />`,
  `a < b and c & d`, and a fenced code block → assert `stage.content` and the created
  `StageVersion.content` are **byte-identical** to the input.
- **Rollback consistency (F3):** edit → finalise → `rollback(current_version)` → assert
  `stage.content` unchanged (still the raw bytes).
- **Refine match survives an edit (F2):** edit content containing `<`/`&` via
  `handle_content_edit`, then `refine` with offsets computed against that same string →
  assert no `RefineSelectionError`.

Frontend (`frontend/src/pages/__tests__` or co-located):

- `runRefine` surfaces `detail.message` from a structured 409 (mock axios error).

### 1.4 Verification (Phase 1)

Per the standing project rule: stop, rebuild, and run the app after the backend edit
(`docker compose up --build`). Then drive the real loop:

1. Generate a Harness (or paste code-bearing content into any stage in Edit mode).
2. Type one character, pause > 500 ms (auto-save fires), toggle to Preview, navigate
   away and back, and hard-refresh — content identical at every step.
3. Select code text → Refine with a simple instruction → diff appears (no
   "Refine failed").
4. Export ZIP + PDF + public share of the same workspace — rendering intact, no raw
   script execution anywhere (paste a `<script>alert(1)</script>` line in an edit and
   confirm every surface renders it inert).

---

## Phase 2 — Cache-hit generations get evals (F4)

`backend/services/pipeline/stage_manager.py`, cached branch of `generate()` (the
`if cached_output is not None:` block that commits and yields):

After `await db.commit()` / cache-invalidate, mirror the pipeline's eval decoupling
(same pattern as `handle_content_edit` lines ~5146–5176):

1. Fetch `eval_context, harness_content_for_eval = await self._eval_context_for_stage(...)`
   for non-spec stages (before the version row's id goes out of scope, capture
   `version_id = version.id` after a `flush`).
2. Best-effort `persist_structural_eval(db, stage_version_id=version_id,
   stage_type=stage.type, content=cached_output, harness_content=...)` in a
   try/except that logs + rolls back on failure (never fails the delivery).
3. `_schedule_stage_eval(...)` for the background LLM score, `cache_hit=True` if the
   telemetry field exists on that path.

**Tests:** a cached-generation unit test asserting (a) a `StageVersion` and an
`EvalResult` row exist for the new version, (b) `_schedule_stage_eval` was invoked.
Extend the existing cache-hit test rather than duplicating its scaffolding.

**Verification:** create two workspaces from the same starter template; generate the
spec in the second (cache hit — instant). The QualityBadge must reach a real status
(not "Unavailable"), and on a tasks-stage hit the validation panel and Re-validate
button must appear.

---

## Phase 3 — Mount version history (F5)

`frontend/src/pages/Workspace.tsx`:

`VersionHistoryPanel` is self-contained (fetches via `getStageVersions(stage.id)`,
re-fetches on `stage.current_version` change, renders `null` with < 2 versions and no
research provenance) and takes `{ stage, onRollback }`. `performRollback` already
exists with A1-aware error handling.

1. **Non-spec stages:** render `<VersionHistoryPanel stage={activeStage}
   onRollback={performRollback} />` inside the right-rail `<aside>` (the non-diff
   branch, after `TaskValidationPanel`). Extend `showRightPanel` with a
   `hasVersionHistory` signal — simplest correct gate: `activeStage.current_version > 1`
   (cheap, no extra fetch; the panel itself handles the exact-count edge cases).
2. **Spec stage:** the spec layout has no right rail; render the panel under
   `ProblemStatementPanel` in the left column of `spec-compare-grid`.
3. Disable restore while the workspace generation lock is held: pass a `disabled`
   prop through (add it to the panel — mirror the `disabled`/`disabledReason` pattern
   every other panel uses) so a restore can't race a live generation (the backend 409s
   anyway; this is the UI courtesy layer).

**Tests:** extend `VersionHistoryPanel.test.tsx` for the new `disabled` prop; add a
Workspace-level render test asserting the panel appears for a stage with
`current_version > 1` and not for `=== 1`.

**Verification:** generate → edit (creates v2) → panel lists v1/v2 → Restore v1 →
content swaps, downstream stages marked stale, staleness banner appears.

---

## Phase 4 — Gap patch: stop holding a transaction across the LLM stream (F6)

`backend/services/pipeline/stage_manager.py`, `generate_harness_patch`.

**Restructure to buffer-then-transact:**

1. **Read phase (no lock, no deduction):** load stage (plain read), check
   `status in ("draft","stale")`, rate limits, `_assert_visible_credit_balance`
   (fail-fast check only — no `deduct`). Capture `baseline_content = stage.content`
   and `baseline_version = stage.current_version`. **Expire/close the transaction**
   before streaming (`await db.commit()` of the no-op read or `db.expire_all()` +
   connection release — verify with `pg_stat_activity` that the session is `idle`,
   not `idle in transaction`, during the stream).
2. **Stream phase:** run the watchdog-wrapped LLM stream to completion, yielding
   tokens to the client and accumulating, exactly as today.
3. **Mutation phase (short transaction):** re-load the stage `FOR UPDATE`; re-check
   `status in ("draft","stale")` **and** `current_version == baseline_version` — a
   mismatch means an edit/generation landed mid-stream: raise
   `StageStateError("The harness changed while the patch was generating…",
   code="stage_conflict")` with **no charge**. Then `deduct`, `_merge_harness_patch`
   (against the re-loaded content, which the version check guarantees equals
   `baseline_content`), the no-op rollback branch, tech-safety, persist, commit —
   unchanged logic, now spanning milliseconds instead of minutes.

This removes both failure modes: the idle-in-transaction kill (default 300 s) and the
multi-minute FOR UPDATE lock that blocked concurrent finalise/edit. Concurrent patches
now serialize at the mutation phase; the loser aborts uncharged instead of queueing on
a row lock.

**Frontend:** add a `stage_conflict` case to `streamErrorMessage` in `sseService.ts`
(friendly copy; non-retryable default is fine since the gap set may have changed).

**Tests:** (a) existing patch tests still pass with the restructure; (b) new test:
version bump between stream start and mutation phase → `StageStateError`
`stage_conflict`, no `deduct` recorded, stage untouched; (c) no-op merge still rolls
back uncharged.

**Verification:** run a real gap patch locally; confirm in `pg_stat_activity` that no
session sits `idle in transaction` while tokens stream.

---

## Phase 5 — Polish batch (F7–F11) — one PR

- **F7 (auto-save traffic):** client-side CSRF caching is **off the table** — tokens
  are single-use by design (SETNX replay protection, HF-6). Instead:
  (a) raise the `StageEditor` save debounce 500 ms → 1500 ms;
  (b) in `handleContentChange`, skip the PATCH when the new content equals
  `activeStage.content` (no-op saves currently still round-trip);
  (c) add a code comment at `attachCsrfHeader` documenting *why* there is no token
  cache, so the next optimizer doesn't break replay protection.
- **F8:** wrap `acceptDiff`/`rejectDiff` bodies in try/catch →
  `setGenericError(getApiErrorMessage(...))`; keep the diff open on failure so the
  user's proposed change isn't lost.
- **F9:** add a `finaliseInFlightRef` guard (mirror `refineInFlightRef`) shared by
  `handleFinalise` and `handleAcknowledgeStale`; set before the POST, clear in
  `finally`.
- **F10:** replace the `taskCount` regex in `Workspace.tsx` with
  `parseTaskBlocks(tasksStage.content).length` — one parser, one truth.
- **F11:** in `CreditConfirmModal`, move `if (open === false) return null` below the
  `useRef`/`useFocusTrap` calls (or delete the unused `open` prop and the branch —
  preferred; the only call site never passes it).

**Tests:** vitest for the F10 parity (a `### T-001 : Title` document yields the same
count in both), F8 error path (mock rejection → alert shown, diff retained), F9
double-invoke (second call is a no-op).

---

## Phase 6 — Product decisions (F12, F13) — needs owner sign-off, not engineering-gated

- **F12:** route the harness gap patch through `CreditConfirmModal`
  (`action: "regenerate"` with patch-specific copy, or a new `"patch"` action), and
  either give Refine the same confirm or add an inline "3 credits" note on the refine
  submit button (lighter-weight; recommended — refine is a high-frequency action and a
  modal would add friction).
- **F13:** one line in `DiffViewer`'s footer: *"Rejecting keeps your document unchanged;
  the 3-credit refinement charge is not refunded."*

Decide copy + pattern before implementing; both are < 1 h changes once decided.

---

## Ordering, gates, and rollout

1. **Phase 1 first and alone** — it changes persistence semantics; keep the diff
   reviewable. No feature flag: the change is strictly less destructive than current
   behavior, and the boundary checklist (1.0) is the safety argument. CI gates apply
   (ruff, black, bandit, pytest ≥ 80 % cov, tsc, vitest).
2. Phases 2 and 3 are independent of each other and of Phase 1 — parallelizable.
3. Phase 4 after Phase 1 lands (both touch `stage_manager.py`; avoid rebase churn).
4. Phase 5 anytime; Phase 6 after sign-off.
5. Every backend-touching phase ends with the standing local verification loop:
   rebuild containers, run the app, drive the affected flow end-to-end (not just
   tests).

## Explicitly out of scope

- Re-mangled-content repair migration (no reliable way to distinguish
  bleach-mangled from intentional content; users recover via version restore).
- Switching the CSRF model to per-session double-submit cookies (would obsolete the
  per-request fetch entirely, but is a deliberate security-model change needing its
  own review).
- The generation-cache's lack of user/workspace scoping (input-derived key; reviewed
  and accepted — a cache hit reveals nothing beyond what identical inputs imply).
