# Stage Gate Logic Audit

**Date:** 2026-06-25
**Scope:** Generation + judge/critic/advisory logic for all four stages (Spec → Plan → Harness → Tasks).
**Files reviewed:** `services/pipeline/prompt_builder.py`, `services/pipeline/artifact_validator.py`,
`services/pipeline/critic.py`, `services/pipeline/stage_manager.py`, `services/pipeline/tech_safety.py`,
and the four prompt modules in `prompts/`.

This is a read-only logic review. Findings are ranked by severity. The gate architecture is sound
overall — the refundable-vs-advisory split, the fail-open critic, and the override/finalise contracts
are coherent. The findings below are correctness/consistency defects, not architectural problems.

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

## Summary

| # | Severity | Finding | Blocking? |
|---|----------|---------|-----------|
| 1 | HIGH | Truncated `## Architecture Quality Attribute` contract heading → empty body extraction → false shallow advisory on **every** plan | No (advisory) |
| 2 | MEDIUM | Broad sentinel + prompt-blessed "Not applicable" one-liner → false Frontend Architecture shallow advisory on backend/CLI plans | No (advisory) |
| 3 | LOW | `_critic_deps` (Redis cache) vs `_workspace_stage_deps` (ORM) divergence — mostly mitigated by `build_prompt` re-warm | No |
| 4 | LOW | Redundant double tech-safety pass in async-advisory path | No |
| 5 | LOW | Task dep-order check assumes topological numbering → false positives | No (advisory) |

The one finding worth fixing now is **#1** (and **#2** is the same mechanism): a single deliberately
truncated heading in `SECTION_CONTRACTS` is correct for the substring gate but silently wrong for the
line-anchored body gate, firing a false advisory on every plan generation.
