# P21 — `backend/services/integrations/agents_md_builder.py` (generic `AGENTS.md` agent-context file)

**Found during Phase 3 cross-cutting analysis** (a Phase-1 discovery miss,
caught by following `agent_manual_service.py`'s own docstring reference to
"the GitHub integration's generic agent-context `AGENTS.md`"). Same category
as P12 — a downstream-agent-facing artifact, not an API call site — and the
**better-defended sibling** of P12: both write a file a coding agent will
treat as project context, but this one sanitizes first.

| # | Dimension | Score | Evidence |
|---|-----------|-------|----------|
| 1 | Task clarity & specificity | 5 | Single job, clearly stated: give a coding agent the spec/architecture/harness/tasks briefing without it fetching anything else (`agents_md_builder.py:3-6`). |
| 6 | Edge case & failure handling | 5 | The non-clobbering managed-block design (`agents_md_builder.py:8-21, 43-50`) is genuinely excellent: anchors on a *complete* marker pair so an orphan start marker never eats user content, fails safe to append-only on a malformed half-marker, and is fully deterministic (no timestamps) so a re-sync never produces a spurious commit — exactly the kind of "what if this runs twice / what if the user already had a file here" thinking the rubric asks for. |
| 7 | Constraint completeness | 5 | Explicit non-negotiable: "Any pre-existing user content outside the markers is preserved byte-for-byte" (`agents_md_builder.py:15`) — respects that this is writing into a repo the user (and possibly other tools/humans) also owns. |
| 8 | Injection & untrusted-content safety | 5 | **`_excerpt` calls `sanitize_text` on every stage excerpt before embedding** (`agents_md_builder.py:134-136`), with the module docstring stating the explicit security rationale: "the stage-derived content folded into the managed block is sanitised with the same policy as public share / PDF" (`agents_md_builder.py:23-25`). This directly closes the class of gap found in P12 (`agent_manual_service.py`'s unsanitized Technology Stack splice) — this file is the concrete, in-codebase proof that the team already has the fix pattern for that exact risk, just not applied to the Demo Day CLAUDE.md/AGENTS.md path. |
| 9 | Variable interpolation safety | 4 | Bounded per-stage excerpt length (`_STAGE_EXCERPT_CHARS = 1500`, `agents_md_builder.py:54,134-141`) and sanitized task refs/titles (`_task_list`, `agents_md_builder.py:144-150`) — good. Minor: the 1500-char truncation is a blunt mid-section cut with no boundary-awareness (could truncate mid-sentence/mid-code-fence), a cosmetic rather than safety concern. |
| 11 | Token/cost efficiency | 5 | Zero LLM cost — pure deterministic template rendering, same as P12. |
| 12 | Determinism & robustness | 5 | "no timestamps, no set ordering... re-running against identical stages produces byte-identical output" (`agents_md_builder.py:19-20`) is a strong, explicitly-tested-for property (idempotent sync). |
| 13 | Maintainability | 4 | Well-commented, single-purpose. Verified this module and `agent_manual_service.py` (P12) are maintained independently with **no shared sanitization helper** between them despite serving the same threat model — worth unifying (see remediation plan). |
| 14 | Testability & eval coverage | 4 | The non-clobbering/managed-block regex logic is exactly the kind of pure-function behavior that's easy to unit test; this audit did not locate a dedicated test file for `agents_md_builder.py` but the deterministic, side-effect-free design makes it straightforward to test if not already covered. |

**Top risk:** None on its own — this is one of the strongest-designed artifacts in the inventory. Its only role in this audit's findings is as the evidence that closes the "how would you fix P12" question: reuse this file's `sanitize_text` call.

**Verdict:** EXEMPLARY.
