# Stage Gate Logic Audit

**Date:** 2026-06-25
**Scope:** Generation + judge/critic/advisory logic for all four stages (Spec → Plan → Harness → Tasks),
plus the credit-accounting paths those gates charge/refund against (added 2026-06-25).
**Files reviewed:** `services/pipeline/prompt_builder.py`, `services/pipeline/artifact_validator.py`,
`services/pipeline/critic.py`, `services/pipeline/stage_manager.py`, `services/pipeline/tech_safety.py`,
the four prompt modules in `prompts/`, and — for the credit review — `services/credit_service.py`,
`services/pipeline/recovery_service.py`, `services/pipeline/increment_service.py`, and
`services/pipeline/storyboard_service.py`.

This is a read-only logic review. Findings are ranked by severity. Both the gate architecture and the
credit ledger are sound overall — the refundable-vs-advisory split, the fail-open critic, the
override/finalise contracts, the FOR-UPDATE-serialised deduct, the idempotent SAVEPOINT-scoped refund,
and the heartbeat-vs-recovery race closure are all coherent. The findings below are
correctness/consistency defects, not architectural problems.

---

## 1. HIGH — Every plan generation emits a false "Architecture Quality Attribute" shallow advisory

**Mechanism.** `SECTION_CONTRACTS["plan"]` stores the heading as `## Architecture Quality Attribute`
(`artifact_validator.py:58`) — deliberately truncated so the **substring** check in
`validate_sections` (`artifact_validator.py:240`, `heading not in artifact_md`) still matches the plan
prompt's actual heading `## Architecture Quality Attribute Matrix` (`prompts/plan.py`).

The same list is consumed by a **second** check with different matching semantics. `_section_body()`
(`artifact_validator.py:383-391`) extracts the section body with a **line-anchored** regex
`^{heading}\s*$`. That anchor cannot match the longer real heading (`...Attribute Matrix`), so the body
is extracted as `""`. `_section_body_issues` (`artifact_validator.py:363-380`) then sees an empty body
(len 0 < the 150-char plan floor) and emits a `shallow_required_section` finding on **every** plan.

**Empirically confirmed:**

```
_section_body(art, "## Architecture Quality Attribute")        -> ''   (len 0)   # truncated contract heading
_section_body(art, "## Architecture Quality Attribute Matrix") -> '| Attribute | Tactic | ...'  # real heading
```

**Impact.** The finding is advisory (non-blocking), so generation is not broken. But the
`AdvisoryFindingsPanel` falsely tells **every** user that the Architecture Quality Attribute section
"does not contain substantive content." This is persistent noise that erodes trust in the entire
advisory surface, and it is a self-inflicted contract drift: one `SECTION_CONTRACTS` list feeds two
checks (`validate_sections` substring vs `_section_body` line-anchored) with incompatible matching.

**Fix.** Store the full `## Architecture Quality Attribute Matrix` in `SECTION_CONTRACTS["plan"]`. The
`validate_sections` substring check still passes, and `_section_body`'s anchor now matches the real
heading. (Alternative: make `_section_body` prefix-match instead of line-anchored, but fixing the data
is simpler and removes the trap for any future truncated contract entry.)

---

## 2. MEDIUM — Backend/CLI plans get a false Frontend Architecture shallow advisory

**Mechanism.** The conditional sentinel `\b(UI|web|app|page|screen|dashboard|console)\b`
(`artifact_validator.py:97-102`) is broad enough to fire on backend/CLI specs (e.g. "console",
standalone "app"). The plan prompt (`prompts/plan.py:68`) explicitly blesses a one-line
`Not applicable because <reason>` body for the `## Frontend Architecture` section on backend-only
projects.

But once the sentinel fires, `_section_body_issues` requires the section body to clear the ≥150
normalized-char plan floor (`_min_body_chars["plan"]`, `artifact_validator.py:419-424`). The blessed
one-liner is well under that, so it trips `shallow_required_section`.

**Impact.** The prompt and the validator disagree on what a valid backend-only section looks like. A
CLI/backend plan that correctly marks Frontend Architecture "Not applicable" gets a false shallow
advisory. Non-blocking, but it is a direct prompt-vs-validator contradiction.

**Fix.** Exempt an explicit "Not applicable" body from the depth floor for conditional sections (mirror
the way `_normalise_body_for_depth` already neutralizes TODO/TBD/placeholder), or tighten the sentinel
so it does not fire on non-UI surfaces.

---

## 3. LOW (mostly mitigated) — Two different dependency sources feed gates in the same generation

**Mechanism.** Within one generation, two gate families read upstream dependency content from two
different sources:

- `validate_artifact_completeness` runs on ORM deps via `_workspace_stage_deps`
  (`stage_manager.py:2788`) — authoritative, always present.
- `validate_sections` and `critic_review` run on `_critic_deps` (`stage_manager.py:4182`), which reads
  the Redis `stage:` cache (TTL 3600s, no ORM fallback — `redis.get(...) or ""`).

The original concern: a cold cache (e.g. finalise spec, then generate plan >1h later) would make
`_critic_deps` return empty strings, so the critic runs blind (no `CoverageGap` detection — its
headline job) and the conditional Frontend Architecture requirement silently disappears from
`validate_sections`.

**Why it is mostly mitigated.** `build_prompt` → `_fetch_stage_content`
(`prompt_builder.py:222-242`) re-warms that exact cache key from the DB on a miss, and it runs at
preflight (`stage_manager.py:2543`) **before** the gates read the cache. So in the main generation path
the cache is warm by the time `_critic_deps` runs.

**Residual exposure.** `finalise()`'s tech-safety re-check calls `_critic_deps`
(`stage_manager.py:3823`) with no preceding `build_prompt` re-warm, so deps can be cold there. Impact is
small because tech-safety mainly inspects the artifact itself; deps are supplementary context.

**Recommendation.** Have the gates use the ORM `deps` that are already in scope rather than re-fetching
from a TTL'd mirror of the same finalised content. It is strictly more authoritative and removes the
divergence entirely.

---

## 4. LOW — Redundant double tech-safety pass in the async-advisory path

With `critic_async_advisory=true` (the default), `_ensure_technology_safe` runs at
`stage_manager.py:3021` and again at `stage_manager.py:3278` on identical content. The second call was
designed to bracket the inline critic/regenerate loop (which could introduce unsafe tech), but in the
async path that inline regenerate no longer runs, so the content is unchanged between the two calls.

Tech-safety is deterministic and Redis-cached, so this is cheap — just wasted work. The second call is
only meaningful in the legacy (`critic_async_advisory=false`) path.

**Fix (optional).** Skip the second tech-safety pass when `critic_async_advisory` is true (no inline
content mutation occurred).

---

## 5. LOW — Task dependency-order check assumes topological numbering

`invalid_task_dependency_order` (`artifact_validator.py:862-879`) flags any dependency where
`dep_num >= task_num`, i.e. it assumes a task may only depend on a lower-numbered task. If a model
numbers tasks by feature area rather than strict execution order, a legitimate `T-003 → T-008`
dependency is falsely flagged.

**Impact.** Advisory-only (non-refundable), so non-blocking — but it is a real false-positive class.

**Fix (optional).** Validate acyclicity via a proper graph check (the dependency graph is already
emitted) rather than relying on task-number ordering as a proxy for topological order.

---

## Credit system (added 2026-06-25)

The ledger core is robust and does **not** have the orphaned-charge / double-spend / false-recovery
classes of bug. For the record, the things that are *correct*: `deduct` re-locks the user row
(`SELECT ... FOR UPDATE` + `populate_existing`) and re-checks balance under lock, so the pre-flight
`_assert_visible_credit_balance` is only a UX hint and cannot be raced into a double-spend; every refund
is keyed on a unique `reason` inside a SAVEPOINT, so the inline failure path and the recovery sweep can
both fire on one deduction and only one refund row is ever written; and `_stage_db_heartbeat` bumps
`updated_at` every 30s against the 3-minute recovery threshold (a 6× margin), so a frontier generation
legitimately running for minutes — up to the 900s hard cap — is never falsely swept and refunded
mid-flight. The findings below are the residual defects.

---

## 6. MEDIUM — Increment holds the user-row `FOR UPDATE` lock across the entire LLM call

**Mechanism.** Every other charge path commits the deduction (releasing the user-row lock `deduct`
takes) **before** the slow model call: the stage path commits at `stage_manager.py:2570` before the
detached pipeline runs, and `storyboard_service.py:604` commits at `:604` then explicitly releases its
reserve lock before generating ("Always release the reserve lock before the slow LLM call so a single
user is never blocked for the generation's full duration", `:609`). The increment path does not. It
deducts at `increment_service.py:241` and does not commit until `:298` — **after**
`await adapter.complete(...)`. Because `deduct` → `_get_user(lock=True)` holds `SELECT ... FOR UPDATE`
on the user row until that commit, the lock is held for the whole generation (up to
`llm_complete_timeout_seconds`).

**Impact.** Any concurrent credit operation for the **same user** blocks behind the increment's
in-flight LLM call: another generation's `deduct`, the lazy expiry sweep, a `refund`, and — most
importantly — a **billing-webhook `grant_credits_with_debt_recovery`**, which would stall the arq
billing worker job until the increment's model call finishes or times out. This is a lock-held-across-IO
antipattern; it is the only one in the credit paths.

**Why it isn't an orphaned-charge bug.** The flip side of committing late is that increment is
effectively *charge-on-commit*: a hard process death mid-generation rolls back the increment row **and**
the deduction together, so no charge is ever orphaned (see also finding #7). The fix must preserve that
property.

**Fix.** Restructure to match the stage/storyboard pattern: commit the deduction (and the `generating`
placeholder) to release the lock, then run the LLM call, then refund-on-failure / append-on-success in a
**fresh** transaction. This trades the clean charge-on-commit rollback for the existing refund path
(`_refund_and_mark_draft`) plus an orphan-recovery sweep (finding #7), which is the same trade the stage
path already makes.

---

## 7. LOW — No orphan-recovery sweep for increments (mitigated today, becomes load-bearing after #6)

**Mechanism.** `recover_stuck_stages` (`recovery_service.py:28`) sweeps only `Stage` rows stuck
`in_progress` and (via `recover_stuck_storyboards`) storyboards. An increment left in `generating` by a
hard process death is never swept.

**Impact today: none.** Because increment is charge-on-commit (finding #6), a dead process rolls the
deduction back with the increment row — there is no committed charge to recover, so the missing sweep
costs nothing.

**Coupling to #6.** If #6 is fixed by committing the deduction before the LLM call (as recommended), the
increment becomes charge-then-generate **exactly like the stage path** — at which point a hard death
*can* leave a committed charge against a `generating` increment with no in-process `finally` to refund
it. The increment sweep is therefore not optional cleanup; it must land **in the same change** as #6.

**Fix.** Add an increment lane to the leader-locked recovery cycle mirroring `recover_stuck_storyboards`:
reset `generating` increments older than a threshold to `draft` and refund `deduction_ledger_id` through
the same idempotent `credit_service.refund`.

---

## 8. LOW — Recovery sweep logs a hardcoded refund amount

`recover_stuck_stages` logs `credits_refunded = CREDIT_COSTS["generate"]` (=10) unconditionally
(`recovery_service.py:45`) regardless of the swept stage's actual deduction. The **actual** refund is
correct — `credit_service.refund` reverses `abs(original.amount)` from the real ledger row — so this is
log-only. But a stage whose `deduction_ledger_id` points at a non-10-credit deduction (e.g. a future
cost change, or a refine that somehow left a stage `in_progress`) would log a misleading figure feeding
dashboards/alerts.

**Fix.** Log the actual reversed amount (`abs(original.amount)` returned from the refund) rather than the
`generate` constant.

---

## 9. POLICY (not a defect) — Blocking `missing_sections` / `technology_safety` gates do not refund

`missing_sections` and `technology_safety` are **blocking** gates that reset the stage to draft, but only
`incomplete_output` refunds (CLAUDE.md "Refunds are minimal"). `missing_sections` is additionally
*terminal* (no auto-regenerate). So a user can be charged the full `generate` cost for output the system
itself rejected, and must **Override** (free) or **Regenerate** (another full charge) to proceed.

This is intentional — the rationale is that the artifact is still delivered and overridable, so the user
got something for the charge. It is recorded here not as a bug but because the fairness of the charge
rests **entirely** on the Override action being discoverable in the UI (`StreamingOverlay` Regenerate +
Override actions on the `quality_gate_failed` event). If that affordance ever regresses, this silently
becomes a "charged for nothing" path. No code change required; flagged for an explicit product decision.

---

## Summary

| # | Severity | Finding | Blocking? |
|---|----------|---------|-----------|
| 1 | HIGH | Truncated `## Architecture Quality Attribute` contract heading → empty body extraction → false shallow advisory on **every** plan | No (advisory) |
| 2 | MEDIUM | Broad sentinel + prompt-blessed "Not applicable" one-liner → false Frontend Architecture shallow advisory on backend/CLI plans | No (advisory) |
| 3 | LOW | `_critic_deps` (Redis cache) vs `_workspace_stage_deps` (ORM) divergence — mostly mitigated by `build_prompt` re-warm | No |
| 4 | LOW | Redundant double tech-safety pass in async-advisory path | No |
| 5 | LOW | Task dep-order check assumes topological numbering → false positives | No (advisory) |
| 6 | MEDIUM | Increment holds the user-row `FOR UPDATE` lock across the entire LLM call — serialises all of a user's credit ops (incl. billing grants) behind it | n/a (credit) |
| 7 | LOW | No orphan-recovery sweep for increments — harmless today, **must land with #6** (which makes increment charge-then-generate) | n/a (credit) |
| 8 | LOW | Recovery sweep logs a hardcoded `CREDIT_COSTS["generate"]` instead of the actual reversed amount — log-only | n/a (credit) |
| 9 | POLICY | Blocking `missing_sections` / `technology_safety` gates don't refund — fairness rests on the Override affordance staying discoverable | n/a (policy) |

Among the gate-logic findings, the one worth fixing first is **#1** (and **#2** is the same mechanism):
a single deliberately truncated heading in `SECTION_CONTRACTS` is correct for the substring gate but
silently wrong for the line-anchored body gate, firing a false advisory on every plan generation. Among
the credit findings, **#6 and #7 are coupled and must ship together** — fixing the increment lock-hold
turns it into a charge-then-generate path, which requires the increment recovery sweep to exist or a
hard death could orphan a real charge.
