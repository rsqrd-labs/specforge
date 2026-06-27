# Demo Day Mode — Implementation Plan

Status: **Proposed** (not yet implemented). Last updated: 2026-06-26.

This document is written to be picked up cold by a future agent or engineer. It is
grounded in the current codebase (file paths and symbols are real as of the date
above). It defines the design, the data model, a phase-by-phase build, and the
exact contracts (section lists, completeness floors, the operating-manual template,
the linter checks) needed to implement the feature without re-deriving them.

Do **not** write code from this doc until the open decisions in §11 are confirmed
(they have recommended defaults; confirming them is a one-line answer each).

---

## 1. What this is

**Demo Day mode** is a generation *profile* on top of the existing four-stage
pipeline (Spec → Plan → Harness → Tasks). The user gives a problem statement, selects
**Demo Day mode** (and their coding agent), and SpecForge produces a Spec/Plan/Harness/Tasks
package tuned so that the user can hand the package to their own coding agent
(Claude Code / Codex), implement the tasks one by one, and arrive at a **working
prototype** — with the architecture choices documented well enough to answer the
standard demo-day rubric questions (*how scalable? how is AI used? how secure?*).

It is **not** a new product or a parallel pipeline. It is:

- a `mode` flag on the workspace (mirrors the existing `disable_critic` /
  `brave_research_enabled` boolean-column pattern on `backend/models/workspace.py`),
- mode-aware prompts, section contracts, and completeness floors,
- a new zero-LLM **construction verifier** (a "linter" for the build package),
- a per-agent **operating manual** added to the export bundle,
- a UI selector in the create-workspace modal.

Everything routes through the existing machinery (`prompt_builder.build_prompt`,
`artifact_validator`, `stage_manager`, `export_service`, the credit ledger, the tier
policy). Standard mode is unchanged.

---

## 2. The two claims (keep them separate)

This feature makes **two distinct promises**. Conflating them weakens both. The doc,
the code, and the UI must keep them apart.

### 2.1 The construction guarantee (strong, test-based)

> If every task's acceptance test passes, the prototype does what the approved spec
> says — *by construction*, because the tests collectively define "working."

This is the load-bearing claim. It is **structural and verifiable**: the
construction verifier (§7) certifies that the package is internally consistent —
every task maps to a test, every acceptance criterion maps to a test, the task DAG
is acyclic, and at least one unmockable end-to-end test exists and is reachable. When
those hold, "all tests green" provably means "the approved scope works."

The guarantee is **earned per package**, not asserted blanket: only a package that
passes the verifier gets the "Construction-verified ✓" badge. A package with gaps
ships with the gaps named.

It is also **anchored to consent**: "working" means the scope the user approved at the
`HumanReviewGate` (including the explicit *Out of Scope* / "NOT in this build" list),
never a scope SpecForge invented unilaterally.

### 2.2 The 5-hour budget (soft, calibration only)

The per-task minute estimates and their sum are **advisory metadata**, not a
certified property. LLM time estimates are unreliable; the verifier does **not**
certify the time budget the way it certifies test/DAG coverage. The UI presents it as
"estimated ~Xh (target ≤5h)", never as a guarantee. The time box's real job is to
*force scope down* to where the package is small enough to be fully verified — the
constraint is what makes §2.1 tractable.

**Implementation rule:** the verifier's pass/fail verdict (§7) depends only on
structural checks (C1–C4). The minute sum (C5) is reported but never flips the
verdict.

---

## 3. Design decisions (resolved)

These were open forks during ideation; they are resolved here with rationale so a
future agent does not reopen them.

1. **The verifier is advisory, never blocking.** It does **not** hard-block finalise
   or export. This is consistent with the existing gate philosophy: per `CLAUDE.md`,
   `NON_OVERRIDABLE_GATE_KINDS` is empty, every blocking gate kind is overridable, and
   "the user owns the artifact and can finalise it as-is." The verifier stamps a
   verdict and *may* trigger **one** platform-funded regenerate to close gaps (mirroring
   the legacy inline critic-regen path), after which any remaining gaps become advisory
   findings. It never prevents the user from exporting/finalising.

2. **Mode is set at creation and is workspace-scoped, not per-stage.** The four stages
   must be mutually coherent (a Demo Day spec must yield a Demo Day plan), so the mode is a
   property of the workspace chosen up front, like `provider`. There is no mid-flow
   toggle in v1 (changing it would invalidate all downstream stages).

3. **Two supported agents in v1: Claude Code and Codex.** Both execute tests (the
   construction guarantee *requires* a local test-execution oracle). Non-test-executing
   assistants are out of scope for the guarantee. The agent choice selects the operating
   manual filename and idiom (`CLAUDE.md` vs `AGENTS.md`) and nothing else structural.

4. **Demo Day artifacts use a leaner + re-pointed section set, not the full standard
   contract.** See §6. The existing standard `SECTION_CONTRACTS` (23 spec sections, etc.)
   is too heavy for a 5-hour Demo Day build and lacks the rubric sections. Demo Day mode gets its own
   contract dimension.

5. **Reuse, don't reinvent, the ASDD rigor.** The existing `prompts/tasks.py` already
   mandates atomic, topologically-ordered tasks, each AC "verifiable by a specific
   command", harness refs per task, and "~1–4h" sessions. Demo Day mode *re-tunes* this
   (ruthless scope, walking-skeleton ordering, per-task minutes, green-after-every-task)
   and *adds* the rubric sections + the verifier + the manual. It does not rewrite the
   methodology.

---

## 4. The regression-pin contract (non-negotiable)

This codebase ships every flagged behavior change with a **byte-identical OFF-path
regression pin** (see `core_cheap_primary`, `problem_statement_compression`,
`pipeline_parallel_chunks` in `backend/config.py` — each documents "flag OFF ⇒
byte-identical"). Demo Day mode must honor this:

> For any standard workspace (`mode="standard"`, the default) **and** for any
> workspace when `demo_day_mode_enabled=False`, every prompt, section contract,
> completeness floor, export bundle, and API response must be **byte-identical** to
> today.

This is an explicit acceptance criterion on Phases 0–1 and must have a pinned test
(mirror the existing Rung-0 / pre-5b derivation pins). A future agent will look for it.

---

## 5. Architecture: how `mode` threads through

```
CreateWorkspaceModal (mode + target_agent picker)
        │  POST /workspaces { ..., mode, target_agent }
        ▼
WorkspaceCreate schema ──► workspace_service.create ──► workspaces.mode / .target_agent (new columns)
        │
        ▼
Stage generation (stage_manager.generate)
        │  build_prompt(stage_type, workspace, ...)   ← already receives `workspace`
        ▼
prompt_builder.build_prompt  ──► branches on workspace.mode
        │     ├─ selects Demo Day system prompt + injects Demo Day directive block
        │     └─ _STAGE_KEEP_SECTIONS uses the Demo Day keep-list (§9 integration point)
        ▼
artifact_validator  ──► validate_sections / validate_artifact_completeness
        │                select contract + floors by workspace.mode
        ▼
(after all four stages exist)
demo_day_plan_linter.verify(workspace)  ──► construction verdict (advisory)  [NEW]
        │
        ▼
export_service.build_export / github_export_service
        │     └─ Demo Day mode appends CLAUDE.md|AGENTS.md operating manual + verdict  [NEW]
        ▼
Frontend: ConstructionVerifiedBadge + DemoDayHandoffPanel  [NEW]
```

The single most important grounding fact: **`prompt_builder.build_prompt` already
takes the `Workspace` object** (`backend/services/pipeline/prompt_builder.py:126`), so
the mode is available at prompt-assembly time with no signature change to the caller.

---

## 6. The Demo Day section contracts and floors (concrete)

These are the actual contracts. Add them to
`backend/services/pipeline/artifact_validator.py` as a parallel, mode-keyed structure.
Recommended shape:

```python
# Standard (unchanged) — keep exactly as today for the regression pin.
SECTION_CONTRACTS: dict[str, list[str]] = { ... }       # existing

# New: Demo-Day-mode contracts. Selected when workspace.mode == "demo_day".
DEMO_DAY_SECTION_CONTRACTS: dict[str, list[str]] = { ... }   # below

def section_contract(stage_type: str, mode: str = "standard") -> list[str]:
    if mode == "demo_day":
        return DEMO_DAY_SECTION_CONTRACTS.get(stage_type, [])
    return SECTION_CONTRACTS.get(stage_type, [])
```

`validate_sections` and `validate_artifact_completeness` take a `mode` argument
(default `"standard"`) and call `section_contract`. The `stage_manager` passes
`workspace.mode`.

### 6.1 Demo Day spec sections (`DEMO_DAY_SECTION_CONTRACTS["spec"]`)

Lean + the three rubric sections. Rubric sections are **required** so the demo-day
questions are always answered.

```
## Overview
## Target User and Core Problem
## Demo Day Scope                      # the single happy path we will build
## Out of Scope                   # the "NOT in the 5 hours" list — load-bearing
## Functional Requirements        # small set; each FR maps to an AC
## Acceptance Criteria            # each mechanically checkable; each maps to a test
## Success Demo                   # the headline journey the e2e smoke test exercises
## AI Usage                       # RUBRIC: how/whether AI is used (anti-gimmick honesty)
## Security Posture               # RUBRIC: minimum credible posture + "what we'd add for prod"
## Scalability Story              # RUBRIC: cheap-now choices + the credible scaling path
## Risks and Assumptions
```

### 6.2 Demo Day plan sections (`DEMO_DAY_SECTION_CONTRACTS["plan"]`)

Walking-skeleton-first, frozen interfaces, the scaling narrative as an ADR.

```
## Architecture Overview          # walking-skeleton-first; vertical slices
## Technology Stack               # PINNED versions, agent-affinity rationale
## Requirement Traceability Matrix
## Interface Contracts            # API shapes / schemas / signatures — the frozen seams
## Data Model and Persistence
## Build Sequence                 # the DAG: skeleton → ordered vertical slices
## Environment and Bootstrap      # exact scaffold/run/test/deploy commands
## Architecture Decision Records  # RUBRIC narrative: why each cheap choice scales/secures
## Scalability and Performance    # the credible scaling path
## Security Architecture          # the minimum credible posture
## Risks and Mitigations
```

### 6.3 Demo Day harness sections (`DEMO_DAY_SECTION_CONTRACTS["harness"]`)

The harness is the **frozen contract store** and the test oracle. Emphasize the e2e.

```
## Harness Overview
## Frozen Interface Contracts     # the single source of truth all tasks point at
## Requirement-to-Test Matrix
## End-to-End Smoke Test          # the unmockable, guarantee-bearing test; green from task 1
## File Tree
## Files
```

### 6.4 Demo Day tasks sections (`DEMO_DAY_SECTION_CONTRACTS["tasks"]`)

```
## Effort Summary                 # incl. "Estimated build time: ~Xh (target ≤ 5h)"
## Build Order                    # walking skeleton first; app green after every task
## Traceability Overview
## Tasks                          # each task: see per-task fields below
```

Per-task fields (extend the existing `prompts/tasks.py` task format with two Demo Day fields):
- existing: `Spec refs`, `Plan refs`, `Harness refs`, `Priority`, `Estimate`, steps,
  acceptance command(s).
- **new `Estimated minutes:`** an integer; the sum feeds the §2.2 advisory budget.
- **new `Precondition:`** the earlier task IDs / artifacts that must exist first (makes
  the DAG explicit and machine-checkable by the linter).

### 6.5 Demo Day completeness floors (`validate_artifact_completeness`, Demo Day branch)

Replace the standard floors (≥5 FR / ≥3 NFR / ≥3 AC / ≥6 tasks) with Demo-Day-appropriate
ones. All of these are **blocking gates only in the same advisory-overridable sense as
today** (a blocking gate resets to draft + emits `quality_gate_failed`, but every kind
is overridable):

- spec: ≥3 distinct FR, ≥3 AC, and **each AC must be present in the Acceptance Criteria
  section** (the rubric sections are enforced by `validate_sections`, not here).
- harness: **at least one End-to-End Smoke Test must be present** (new check,
  `missing_e2e_smoke_test`) — this is the guarantee-bearing test; its absence is the one
  Demo-Day-specific structural miss worth surfacing at generation time.
- tasks: ≥4 task blocks (lower than standard's 6 — the Demo Day build is smaller), each with the new
  `Estimated minutes` and `Precondition` fields present (`incomplete_task_fields`).

Keep `_min_body_chars` thresholds as-is (they are stage-level, not mode-level, and a
leaner section is still substantive).

---

## 7. The construction verifier (the linter) — concrete

New module: `backend/services/pipeline/demo_day_plan_linter.py`. **Zero-LLM**, pure
functions over the four persisted stage contents (mirrors `artifact_validator`'s
regex/substring style). Runs only for `mode="demo_day"` workspaces, only once all four
stages exist.

### 7.1 Checks

| ID | Name | What it asserts | Source data |
|----|------|-----------------|-------------|
| C1 | `dag_acyclic` | Every task's `Precondition` refs point only to earlier task IDs; no cycles | TASKS `## Tasks` |
| C2 | `task_to_test` | Every task's `Harness refs` resolve to a file/test present in the harness, or are explicit `_(none — reason)_` | TASKS refs × HARNESS `## Files` / `## File Tree` |
| C3 | `ac_to_test` | Every spec AC appears in the harness `## Requirement-to-Test Matrix` **and** is referenced by ≥1 task | SPEC `## Acceptance Criteria` × HARNESS RTM × TASKS |
| C4 | `e2e_reachable` | ≥1 end-to-end/smoke test exists in the harness and is referenced by the final task (and present from the first slice) | HARNESS `## End-to-End Smoke Test` × TASKS |
| C5 | `time_budget` (advisory) | Sum of `Estimated minutes` ≤ `time_budget_minutes` (column is nullable — the linter falls back to **300** when NULL; the default lives in the linter, not the DB) | TASKS `Estimated minutes` |

**Verdict:** `construction_verified = C1 and C2 and C3 and C4`. C5 is reported but
never flips the verdict (§2.2).

### 7.1.1 Identifier contract (the linter's join keys)

The verifier is zero-LLM substring/regex (like `artifact_validator`), so C1–C4 can only
join what the prompts emit in a **parse-stable** form. The Demo Day prompts (Phase 1)
MUST mandate, and a Phase-1 test MUST assert, these tokens — without them the linter
silently can't match and every package reads as "gaps", so this contract is as
load-bearing as the section contract:

- task blocks as `### T-NNN` (matches the existing `_MIN_TASK_BLOCKS` regex in
  `artifact_validator.py`), and `Precondition:` listing earlier `T-NNN` ids (C1).
- acceptance criteria as `AC-NNN` identifiers, present in SPEC `## Acceptance Criteria`,
  echoed in HARNESS `## Requirement-to-Test Matrix`, and referenced by ≥1 task (C3) —
  reuse the existing `_AC_ID_RE` / `_MATRIX_REQ_ID_RE`.
- `Harness refs:` as file paths that literally appear in HARNESS `## Files` /
  `## File Tree`, or the explicit `_(none — reason)_` escape (C2).
- the e2e test named under HARNESS `## End-to-End Smoke Test` with a stable path/name the
  final task's `Harness refs` cites verbatim (C4).

### 7.2 Output + persistence

Return a structured verdict:

```python
@dataclass
class ConstructionVerdict:
    verified: bool
    checks: dict[str, CheckResult]   # per-check pass/fail + the specific gaps
    estimated_minutes: int
    time_budget_minutes: int
    stage_versions: dict[str, int]   # the version of each stage it ran against
```

Persist it so it is auditable and surfaceable. **Two honest options — neither is
"free":**

- **`workspaces.construction_verdict` (nullable JSONB column) — recommended default.**
  The verdict is inherently *workspace-level* (it spans all four stage versions), which a
  workspace column matches directly. One small migration; the verdict overwrites on
  staleness re-run, and the per-stage versions it stamps (the `stage_versions` field of
  the dataclass above) carry the audit/staleness signal inside the JSON. No granularity
  mismatch.
- **`EvalResult` row.** Tempting for the version stamp + history, but `EvalResult` as it
  exists today **cannot** hold this verdict as-is: it has **no `kind` column**, no generic
  verdict JSONB (its columns are typed — `overall_score`, `completeness`,
  `coverage_percent`, `uncovered_reqs`, `tasks_without_ref`, `flagged`), and is keyed by a
  **single `stage_version_id`** — it is *per-stage-version*, not per-workspace
  (`coverage_utils.py` only reaches "per workspace" by joining through `StageVersion`).
  Using it requires a migration adding `kind TEXT` **and** a `verdict_json JSONB` column,
  plus a decision to home the workspace-level row on the **tasks** stage_version (the last
  stage, which the verifier runs after). Choose this only if cross-version verdict history
  is worth that schema churn.

This is open decision §11.3 — confirm before building.

### 7.3 When it runs + the advisory regenerate

- **After the tasks stage** completes generation (all four now exist), schedule the
  verifier as a **detached background task** exactly like the async-advisory critic
  (`_schedule_critic_review` / `_dispatch_critic_review` in `stage_manager.py`, with its
  own short-lived `AsyncSessionLocal`, under a `current_version` staleness guard).
- If `verified is False`, the **first** time per workspace, trigger **one
  platform-funded regenerate** with the gap list injected (mirror the legacy
  `BILLING_CREDITS_CRITIC_REGEN` path). **Gap→stage attribution (resolve the ambiguity):**
  the C-checks fail at *seams between* stages (C3 = an AC absent from the harness RTM; C4 =
  an e2e not referenced by the final task), so "the offending stage" is not obvious. Rule:
  regenerate **only the most-downstream stage that owns the gap** (C1/C2/C5 → tasks; C3/C4
  → harness, then tasks) — **never the spec**, because the spec is the user-approved scope
  and re-opening it under a platform regen would violate the §2.1 consent anchor. **Mind
  the cascade:** regenerating harness bumps its version and makes tasks stale, so a
  harness-owned gap must regenerate harness **and** tasks together in that single funded
  attempt, then re-run the verifier once. After that one attempt, any remaining gaps are
  surfaced as advisory findings (`AdvisoryFindingsPanel`, `kind="construction_gaps"`).
  **Never auto-regenerate more than once; never block.**
- **On-demand** re-run when the user opens the handoff panel or hits export, if any
  stage version changed since the last verdict (staleness — §9).

> **Phase 3 implementation notes (as built).** Two deliberate deviations from the
> text above, both flagged here so Phase 4 wires the right source:
>
> 1. **Gaps surface via the persisted verdict column, *not* `Stage.quality_gate`.**
>    The plan suggested attaching remaining gaps as `AdvisoryFindingsPanel`
>    findings (`kind="construction_gaps"`) on the tasks stage's `quality_gate`. But
>    the async-advisory critic *also* fires post-`done` for the tasks stage and does
>    a read-modify-write of that same `quality_gate` slot from its own detached
>    session — double-writing it from the verifier is a genuine race. Since the
>    verdict is independently persisted on `workspaces.construction_verdict` (the
>    §7.2 confirmed store) with the full per-check gap list, Phase 3 surfaces gaps
>    **through that column** and does not touch `Stage.quality_gate`. **Phase 4’s
>    `DemoDayHandoffPanel`/`ConstructionVerifiedBadge` must read the verdict column,
>    not `Stage.quality_gate`.**
> 2. **The one funded regenerate is tasks-only (C1/C2 gaps).** `generate()` requires
>    upstream stages finalised (`_assert_dependencies_finalised`), so a background
>    harness regenerate would leave harness in `draft` and break the immediate tasks
>    regenerate — the C3/C4 "harness then tasks" cascade is not safely drivable from
>    a detached task. So a tasks-owned gap (C1/C2) gets the single funded regenerate
>    (via `_regenerate_with_findings`, which never re-enters the pipeline → no
>    verifier recursion); a harness-owned gap (C3/C4) is left **advisory with the gap
>    named** (a named gap beats a fragile silent cascade). The `regen_attempted`
>    marker in the verdict JSON consumes the window on the first attempt
>    (success *or* failure), and the export-time staleness re-run preserves it.

---

## 8. The operating manual + handoff bundle — concrete

New module: `backend/services/pipeline/agent_manual_service.py`. For `mode="demo_day"`
workspaces only, the export gains the operating manual + the verdict. Wire it into both
export paths:

- `backend/services/pipeline/export_service.py` (`build_export`, the ZIP) — currently
  writes `SPEC.md`, `PLAN.md`, `TASKS.md`, and the harness files. Add the manual +
  `CONSTRUCTION_REPORT.md`.
- `backend/services/pipeline/github_export_service.py` — same files into the repo.

Filename by agent: `CLAUDE.md` for `target_agent="claude_code"`, `AGENTS.md` for
`target_agent="codex"`. Same body, agent-idiomatic phrasing.

### 8.1 Operating-manual template (the invariants)

The manual encodes the two preconditions the construction guarantee depends on (run the
test after every task; never edit the frozen harness) plus the build protocol. Generated
from the workspace (stack/versions are interpolated from the PLAN `## Technology Stack`).

```markdown
# Build Protocol — <workspace name>

You are implementing this Demo Day build from SPEC.md, PLAN.md, the harness, and TASKS.md.
Follow this protocol exactly. The four documents are the contract; this file is how to
execute them safely.

## Non-negotiable invariants
1. Implement tasks in TASKS.md order, one at a time. Do not skip ahead.
2. After each task, run its acceptance command. Do NOT proceed while it is red.
3. NEVER edit anything under `harness/`. The tests are the frozen oracle — if a test
   seems wrong, stop and surface it; do not change it to pass.
4. NEVER change a frozen interface (PLAN `## Interface Contracts`, HARNESS
   `## Frozen Interface Contracts`). Implement against them.
5. The stack is pinned (see below). Do not add dependencies or bump versions without
   noting it explicitly in your output.
6. The app must run and the end-to-end smoke test must pass after every task.
7. If blocked on a task for more than ~15 minutes, stop and report the blocker rather
   than hacking the test or stubbing the contract.

## Stack (pinned)
<interpolated from PLAN ## Technology Stack>

## The loop
For each task T-NNN:
  a. Read the task: its Spec refs, Plan refs, Harness refs, Precondition.
  b. Implement the file-level steps.
  c. Run the task's acceptance command and the e2e smoke test.
  d. Only advance when both are green.

## Definition of done
All tasks complete AND the end-to-end smoke test is green. At that point the prototype
does what SPEC.md's Acceptance Criteria specify — by construction.
```

For Claude Code, additionally instruct: "track tasks with your todo list; use one task
per todo item." For Codex, the equivalent idiom.

### 8.2 `CONSTRUCTION_REPORT.md`

A rendered form of the §7 verdict: the badge (verified / N gaps), each check's result,
the gap list, and the advisory estimated build time. Lets the user see the guarantee
status outside the app.

---

## 9. Integration points that will silently break standard mode if missed

A future agent must address these explicitly:

1. **`_STAGE_KEEP_SECTIONS` in `prompt_builder.py:50`** is the downstream verbatim-
   injection keep-list, keyed by the *standard* section headings (e.g.
   `## Functional Requirements`, `## API Design`). Demo Day mode renames/leans some of these
   (e.g. plan uses `## Interface Contracts`, not `## API Design`). Add a mode variant
   `_DEMO_DAY_STAGE_KEEP_SECTIONS` and select by `workspace.mode`, or cross-stage context
   threading for big Demo Day artifacts will silently drop the wrong sections.

2. **Verdict staleness.** The verifier can only run once all four stages exist, but
   stages get regenerated/refined afterward. Stamp the verdict with each stage's version
   (§7.2) and reuse the critic's `current_version` staleness guard. On the frontend,
   reuse the existing `StalenessWarning` component pattern to show "verdict is stale —
   re-run". Re-run on export if stale.

3. **Regression pins (§4).** Every change in Phases 0–1 needs a test asserting standard
   mode is byte-identical. Model it on the existing pinned derivation tests
   (`validate_core_generation_ladder`, the Rung-0 pin).

4. **`VALID_MODELS` / tier policy.** Demo Day mode does not change routing by default, but the
   guarantee-bearing artifacts are higher-stakes. **Recommended:** when
   `core_complexity_routing` is on, add a Demo Day floor to `_apply_complexity_floor` in
   `stage_manager.py` so Demo Day harness/tasks start at the mid tier (reuse the existing
   "harness/tasks stage floor" hook). This is optional and flag-gated — note it, don't
   hard-wire it.

---

## 10. Phased build (each phase independently shippable)

The **thinnest user-visible slice** is Phases 0+1+5-lite (mode selector → Demo-Day-shaped
artifacts → handoff bundle) — that already delivers value without the guarantee. The
phase that **earns the guarantee** is Phase 3 (the verifier + badge). Ship in this order;
each phase is releasable behind the flag.

### Phase 0 — Data model + plumbing (no behavior change)
- DB migration: add `workspaces.mode TEXT NOT NULL DEFAULT 'standard'`
  (CHECK in `('standard','demo_day')`), `workspaces.target_agent TEXT NULL`
  (CHECK in `('claude_code','codex')`), `workspaces.time_budget_minutes INT NULL`.
  Model: `backend/models/workspace.py` (mirror the `disable_critic` column block).
- Schema: add `mode`, `target_agent`, `time_budget_minutes` to `WorkspaceCreate` and
  `WorkspaceResponse` in `backend/schemas/workspace.py` (validators: mode in enum;
  target_agent required when mode=="demo_day").
- Service: thread the fields through `workspace_service.create`.
- Config: add `demo_day_mode_enabled: bool = False` to `backend/config.py` (gate the whole
  feature server-side; when False, `mode` is forced to `"standard"`).
- Frontend types: add `mode`, `target_agent` to `Workspace` and `CreateWorkspacePayload`
  in `frontend/src/types/workspace.ts`; thread through `workspaceStore` + `api.ts`.
- **AC:** standard create path byte-identical; new columns default to standard; pinned
  regression test.

### Phase 1 — Demo Day prompts, section contracts, floors
- `DEMO_DAY_SECTION_CONTRACTS` + `section_contract()` + mode arg on `validate_sections` /
  `validate_artifact_completeness` (`artifact_validator.py`) per §6.
- New `missing_e2e_smoke_test`, `incomplete_task_fields` checks (Demo Day branch only).
- Mode-aware prompts: add Demo Day system-prompt variants (or a Demo Day directive block appended
  in `build_user_prompt`) per stage in `backend/prompts/{spec,plan,harness,tasks}.py`,
  selected via `workspace.mode` in `prompt_builder.build_prompt`. Bump
  `STAGE_PROMPT_VERSIONS` for the Demo Day variants in `prompts/base.py`.
- `_DEMO_DAY_STAGE_KEEP_SECTIONS` in `prompt_builder.py` (§9.1).
- **AC:** standard prompts/contracts/floors byte-identical (pin); a Demo Day workspace
  produces the §6 section set.

### Phase 2 — Handoff bundle (operating manual)
- `agent_manual_service.py` (§8) + wire into `export_service.build_export` and
  `github_export_service`. Manual filename by `target_agent`.
- **AC:** standard export byte-identical; Demo Day export contains the manual.
- *Shippable here:* user can already create Demo Day workspaces, get Demo-Day-shaped artifacts,
  and download an agent-ready bundle — without the guarantee badge yet.

### Phase 3 — The construction verifier (earns the guarantee)
- `demo_day_plan_linter.py` (§7) — checks C1–C5, `ConstructionVerdict`.
- Persist per the confirmed §7.2 option (recommended default: a nullable JSONB
  `workspaces.construction_verdict` column + migration); surface it on the workspace
  response (coverage-style, `coverage_utils.py` pattern).
- Schedule the detached post-tasks run + the one funded advisory regenerate
  (`_schedule_critic_review` pattern) (§7.3).
- `CONSTRUCTION_REPORT.md` added to the export bundle (§8.2).
- **AC:** verdict computed for Demo Day workspaces; advisory only (never blocks finalise/
  export); staleness-guarded.

### Phase 4 — Frontend
- `CreateWorkspaceModal.tsx`: a **Mode** selector (Standard | Demo Day) above the
  existing "Advanced (provider)" disclosure. When Demo Day is selected: reveal a **target-agent**
  picker (Claude Code | Codex) and show the rubric-aware pipeline preview ("Spec · Plan ·
  Harness · Tasks → construction-verified handoff"). Gate the whole selector behind a
  build-time flag `VITE_DEMO_DAY_MODE` in `frontend/src/config/featureFlags.ts` (off until
  ready).
- New `ConstructionVerifiedBadge.tsx` + `DemoDayHandoffPanel.tsx` in
  `frontend/src/components/workspace/` — badge from the persisted verdict; panel with the
  gap list, the staleness warning, and the agent-tuned bundle download.
- **AC:** standard modal unchanged when the flag is off; Demo Day path renders badge + panel.

### Phase 5 — Rollout
- Credits decision (§11.2) wired into `credit_service`.
- Golden-corpus / route-promotion gate for the Demo Day prompts (this repo gates any change to
  "which artifact gets produced" behind the corpus — see `docs/evals/ROUTE_PROMOTION.md`).
  Add Demo Day problem statements to the corpus and assert the verifier passes on them.
- Docs: a `docs/RUNBOOK.md` note for the new `construction_verdict` eval kind; flip
  `demo_day_mode_enabled` + `VITE_DEMO_DAY_MODE` on after the live gate.

---

## 11. Open decisions (recommended defaults — confirm, don't reopen)

These have defaults so implementation is not blocked; confirm them when convenient.

1. **Zero-provisioning stack vs. documented setup step.** The most common "green on the
   spec, red on the user's machine" cause is the e2e test assuming infra the user must
   provision (a Postgres, an API key). **Recommended default:** Demo-Day-mode plans bias to
   **zero-provisioning** stacks (SQLite / in-process / externals mocked at the boundary)
   so the e2e is environment-independent and the guarantee survives the handoff. When the
   idea genuinely needs an external service, the bootstrap section documents the exact
   one setup step. *Confirm: zero-provisioning bias, yes/no.*

2. **Credit cost of Demo Day mode.** Demo Day generation produces more (rubric sections, manual,
   verifier, one funded advisory regenerate). **Recommended default:** same per-stage
   credit cost as standard; the operating-manual generation and the verifier are free
   (zero or near-zero LLM cost); the one advisory regenerate is platform-funded (mirrors
   the critic-regen precedent). *Confirm.*

3. **Verdict persistence location.** **Recommended default:** a nullable JSONB
   `workspaces.construction_verdict` column — it matches the verdict's workspace-level
   granularity with one small migration. The `EvalResult` route is *not* free (no `kind`
   column, no verdict JSONB, per-stage-version FK — see §7.2) and only earns its keep if
   cross-version verdict history matters. *Confirm.*

4. **Demo Day tier floor.** **Recommended default:** leave routing unchanged in v1; revisit an
   Demo Day complexity floor (§9.4) only if cheap-tier Demo Day quality regresses on the corpus.
   *Confirm: ship cheap-primary for Demo Day too, yes.*

---

## 12. Testing strategy

- **Regression pins (Phases 0–1):** standard workspace → byte-identical prompts, section
  contracts, floors, export. This is the headline safety test.
- **Backend unit:** `DEMO_DAY_SECTION_CONTRACTS` presence checks; Demo Day completeness floors; the
  `demo_day_plan_linter` checks C1–C5 against fixture packages (one verified, one with each gap
  kind); `agent_manual_service` output (right filename per agent, invariants present).
- **Verifier advisory semantics:** a package with gaps still finalises and exports
  (assert no blocking); exactly one funded regenerate; staleness re-run.
- **Frontend (vitest):** modal renders mode selector only when flag on; target-agent picker
  appears for Demo Day; badge/panel render from a verdict fixture; standard modal unchanged when
  flag off.
- **Harness contract tests:** add Demo Day golden workspaces to `harness/prompt_eval/` and
  assert the verifier passes on them (the corpus gate, §10 Phase 5).

---

## 13. File-change index (grounded)

| Area | File | Change |
|------|------|--------|
| Model | `backend/models/workspace.py` | + `mode`, `target_agent`, `time_budget_minutes` columns |
| Migration | `backend/alembic/versions/*` | new migration for the columns |
| Schema | `backend/schemas/workspace.py` | + fields on `WorkspaceCreate` / `WorkspaceResponse` |
| Service | `backend/services/workspace_service.py` | thread new fields in `create` |
| Config | `backend/config.py` | + `demo_day_mode_enabled: bool = False` |
| Prompts | `backend/prompts/{spec,plan,harness,tasks}.py`, `prompts/base.py` | Demo Day variants + versions |
| Prompt builder | `backend/services/pipeline/prompt_builder.py` | mode branch; `_DEMO_DAY_STAGE_KEEP_SECTIONS` |
| Validator | `backend/services/pipeline/artifact_validator.py` | `DEMO_DAY_SECTION_CONTRACTS`, `section_contract`, Demo Day floors |
| Verifier | `backend/services/pipeline/demo_day_plan_linter.py` | **new** |
| Manual | `backend/services/pipeline/agent_manual_service.py` | **new** |
| Export | `backend/services/pipeline/export_service.py`, `github_export_service.py` | append manual + report for Demo Day |
| Stage mgr | `backend/services/pipeline/stage_manager.py` | pass mode to validators; schedule verifier; optional Demo Day tier floor |
| FE types | `frontend/src/types/workspace.ts` | + `mode`, `target_agent` |
| FE store/api | `frontend/src/store/workspaceStore.ts`, `frontend/src/services/api.ts` | thread fields |
| FE modal | `frontend/src/components/dashboard/CreateWorkspaceModal.tsx` | mode + agent selectors |
| FE flags | `frontend/src/config/featureFlags.ts` | + `demoDayMode` |
| FE components | `frontend/src/components/workspace/ConstructionVerifiedBadge.tsx`, `DemoDayHandoffPanel.tsx` | **new** |

---

## 14. Out of scope (v1)

- Mid-flow mode switching (changing mode after stages exist).
- Agents beyond Claude Code / Codex.
- SpecForge *orchestrating* the coding agent (v1 is hand-off only — the user runs their
  own agent).
- A hard, blocking guarantee (the verifier is advisory by decision §3.1).
- Certifying the time budget (it is advisory metadata by decision §2.2).
