# Storyboard Output Quality — Phase 4 Verification (Definition of Done)

> **Scope.** This is the Phase 4 deliverable of
> [`docs/STORYBOARD_OUTPUT_QUALITY_PLAN.md`](STORYBOARD_OUTPUT_QUALITY_PLAN.md)
> §4 "Phase 4 — Verification (definition of done)". Phases 1–3 are implemented
> and pushed to `main` (P1 `1f3adfe`, P2 `d79e14e`, P3 `1b07cd9`). Phase 4 has
> three parts — **§4.1 automated** (done, recorded here), **§4.2 live QA**
> (manual, runbook below — **owner must execute**), and **§4.3 rollback story**
> (recorded here).
>
> **Status at a glance:** the automated half is **complete and green**; the live
> QA half is **outstanding and belongs to the owner** — it is irreducibly manual
> (`docker compose up --build`, human visual inspection of clipping/diagram
> shape/substance) and cannot be discharged by the test suites. **Phase 4 is not
> closed until the §4.2 checklist passes.**

---

## 1. Automated verification (plan §4.1) — DONE, GREEN

Run from repo root on `main` @ `1b07cd9` (2026-07-06). Docker/Postgres/Redis were
down locally, so the DB-dependent backend suites did not execute (see the caveat
below); everything else ran.

| Suite | Command | Result |
|---|---|---|
| Backend lint | `cd backend && uv run ruff check .` | **clean** |
| Backend format | `cd backend && uv run black --check .` | **clean** (353 files) |
| Backend storyboard + budget (non-DB) | `uv run pytest tests/test_storyboard_{prompt,source,grounding,renderer,phase1,model,quality,observability}.py tests/test_output_budget.py -q` | **148 passed, 2 skipped** |
| Frontend types | `cd frontend && pnpm tsc` | **clean** |
| Frontend unit (vitest) | `cd frontend && pnpm test` | **431 passed** (69 files) |
| Harness backend contracts | `cd backend && uv run pytest ../harness/tests/backend/ -q` | **751 passed**; 12 pre-existing env failures ¹ |
| Harness backend — storyboard | `…/test_phase23_storyboard_contract.py` | **55 passed** |
| Harness frontend contracts | `cd harness && npx vitest run --config ../frontend/vitest.harness.config.ts` | **163 passed**; 7 pre-existing drift failures ² |
| Harness frontend — storyboard | `…/phase23-storyboard.contract.test.ts` | **29 passed** |

All storyboard-scoped automated coverage passes.

### 1.1 New tests added by P1–P3 that lock this plan's acceptance criteria

Each criterion that *can* be automated is guarded by a committed test (so a future
regression is caught in CI, not just live QA):

| Criterion (plan) | Guard test(s) |
|---|---|
| P1.1 — no `SPEC/PLAN/HARNESS/TASKS` chip text on printed pages | `test_storyboard_renderer.py::test_no_source_citations_on_any_printed_page` |
| P1.1 — no source badges on live slides / no node source ids | `StoryboardDeck.test.tsx`, `ArchitectureReveal.test.tsx` (badge/`arch-node__source` removal) |
| P1.3/P1.4 — max-cap deck renders un-clipped, render clamps | `StoryboardDeck.test.tsx` (`makeMaxCapStoryboardPayload`, `MAX_CAP_*`); `test_storyboard_renderer.py` (`_MAX_CAP_*`) |
| P2 — subset diagram renders only present planes; legacy 8-layer unchanged | `ArchitectureReveal.test.tsx` ("omits absent planes", all-8 parity); `test_storyboard_renderer.py::test_arch_core_only_subset_renders_only_present_planes`, `::test_arch_topology_geometry_all_eight_reduces_to_canonical` |
| P2 — core-only diagram validates; missing core kind fails; legacy validates | `test_storyboard_prompt.py::test_storyboard_architecture_reveal_accepts_core_only_subset` (+ harness contract subset/missing-`api` cases) |
| P3.3 — truncated raw triggers exactly one doubled-budget retry; budget resolves per model | `test_storyboard_phase1.py` (`test_doubled_output_budget_clamps_to_model_ceiling`, `test_complete_and_validate_doubles_budget_on_truncation`, `…_no_retry_when_not_truncated`) |
| P3.4 — product/walkthrough/trust slides require a `points`/`metric` descriptor; grandfathered for splices | `test_storyboard_prompt.py` (substance-floor enforced/grandfathered/framing-exempt/metric-accepted) |
| P3.5 — deterministic quality gate rules; escalatable classification | `test_storyboard_quality.py` (per-rule + `_assert_deck_quality`→`_payload_error_type == "payload_schema"`) |

### 1.2 Caveats — read before trusting "all green"

1. **¹ Harness backend — 12 pre-existing failures are environmental, not from this
   plan.** They are `csrf`, `stage_manager`, `llm-adapter`, `tasks-prompt`
   contract-drift/env tests on files P1–P3 never touched. Verified by running the
   identical set against the pre-storyboard commit `a74de8a` in an isolated
   worktree — **they fail identically there** (e.g.
   `StageManager has no attribute STAGE_DEPENDENCIES`). CI runs these from the
   `backend/` CWD with JWT/CSRF env injected; the "43 failures" seen when run from
   the `harness/` CWD collapse to these 12 once `Settings()` can load `.env`.
2. **² Harness frontend — 7 pre-existing failures are drift, not from this plan.**
   They are `StreamingOverlay`, `useStream` eval-SSE, `useFocusTrap`, `stageStore`
   token-append, and `workspace-ui` credit contracts. `git diff --name-only
   a74de8a..1b07cd9` shows **none** of those subjects were touched by P1–P3 (the
   diff is storyboard files only, plus additive-only `config.py`,
   `output_budget.py`, `observability.py`). The storyboard contract
   (`phase23-storyboard.contract.test.ts`) is among the **passing** files.
3. **DB-dependent backend suites did NOT run locally** (Postgres/Redis down). CI is
   the backstop. Risk is low: P1–P3's only changes to *shared* modules
   (`output_budget.py`, `observability.py`, `config.py`) are **purely additive**
   (a new budget key + floor, a new counter + 3 label values, a new default-`False`
   flag) — no existing signature, value, or code path changed.
4. **The four storyboard *integration* suites are permanently CI-`--ignore`d**
   (`test_storyboard_{service,source_integration,router_integration,public_service}.py`
   — they need a `TEST_DATABASE_URL` Postgres) and are **never** a CI gate. P3 did
   fix their stale fixtures for local/QA use; those fixtures were verified offline
   via `StoryboardPayload.model_validate(...)` + `assess_payload_quality(...)`. The
   real service path they would exercise is otherwise locked by the two
   CI-running wiring tests in `test_storyboard_quality.py`.

---

## 2. Live QA runbook (plan §4.2) — OUTSTANDING, owner-run

> **This is the manual half of Phase 4 and cannot be automated.** jsdom performs no
> layout, so clipping is unobservable in tests; the subset-render tests prove the
> *renderer* omits absent planes, not that the *model* emits a correct subset for a
> real product. Per the project memory
> ([[feedback-rebuild-after-backend-changes]]): **full stop → rebuild → run** after
> the backend edits before testing.

```bash
docker compose up --build     # Postgres 5432, Redis 6379, API 8000, Vite 5173, worker
```

Then generate **fresh** storyboards for **two real workspaces** and check each row.
Pick one **web-SaaS-shaped** product (has a frontend + an LLM + integrations) and
one **CLI/batch tool** product (has **no** frontend and **no** LLM) — the second is
the load-bearing case for P2.

| # | Check (plan §4.2) | Where | Pass? |
|---|---|---|---|
| 1 | No slide content clipped at **1280×720 windowed** | live deck | ☐ |
| 2 | No slide content clipped at **fullscreen** (1920×1080) | live deck (F / fullscreen) | ☐ |
| 3 | No slide content clipped in the **downloaded PDF** | PDF export | ☐ |
| 4 | **Zero** `SPEC/PLAN/HARNESS/TASKS` text on any slide or diagram node | live deck + PDF | ☐ |
| 5 | **Sources** overlay (S key / button) still shows per-slide evidence | live deck | ☐ |
| 6 | The **CLI-shaped** product's diagram shows **no invented** `llm`/`frontend`/`integrations` planes (only the planes it truly has) | live + PDF arch slide | ☐ |
| 7 | Interior product/walkthrough/trust slides carry **real bullets/metrics**, not decorative color swatches | live deck | ☐ |
| 8 | No **verbatim wall-of-text** excerpts (short quotes/paraphrases only) | Sources overlay | ☐ |
| 9 | **Regenerate** the whole deck works | live deck | ☐ |
| 10 | Open a **pre-existing** (pre-v1.5) deck; **regenerate one act** — still validates & renders | live deck | ☐ |
| 11 | Both decks generated **without error** on the configured provider(s) | — | ☐ |

**Observability to sanity-check during QA** (Prometheus `/metrics`):
- `specforge_storyboard_escalations_total` — should stay near its baseline; a spike
  means the cheap tier keeps failing the quality gate.
- `specforge_storyboard_truncation_retries_total` — a nonzero-but-small value is
  healthy (the doubling repair firing occasionally); a large value means the base
  budget is too tight.

**If the cheap tier persistently fails the quality gate** (escalation metric high),
flip the escape hatch `storyboard_force_mid_tier=true` (config default `False`) to
start every storyboard generation at the mid tier. This is a single flag; it does
not change the product-wide `tier_policy.py`.

---

## 3. Rollback story (plan §4.3)

- **P1** is pure presentation (frontend CSS/components + offline template/renderer,
  no schema/prompt/service change): revert = `git revert 1f3adfe`.
- **P2/P3** are gated by prompt version bump `storyboard-v1.4 → v1.5` and a
  **loosened-not-tightened** contract (harness JSON schema `minItems 8 → 3` +
  three `contains`; Pydantic requires core kinds only). No previously stored
  payload is invalidated: legacy 8-layer diagrams and 1 200-char excerpts still
  validate and render. The only stored-shape change for **new** decks is *fewer
  layers / shorter excerpts / substance descriptors*, which every renderer already
  accepts (invariant §1.5). Reverting P3's fresh-generation floors (`git revert
  1b07cd9`) never touches historical decks.
- No credit/idempotency/refund/transaction path was modified (invariant §1.4).

---

## 4. Sign-off

- [x] **§4.1 Automated** — all storyboard-scoped suites green; pre-existing
      failures proven unrelated; caveats recorded (§1.2). — Claude, 2026-07-06
- [ ] **§4.2 Live QA** — owner runs the §2 checklist against two real workspaces.
- [x] **§4.3 Rollback story** — recorded (§3).

Phase 4 is **complete** only when the §2 checklist is fully ticked by the owner.
