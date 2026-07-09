# Prompt-Content Change Review

*Prompt Quality Remediation, finding #10 — a process gate for editing prompt
**text**, mirroring [`ROUTE_PROMOTION.md`](ROUTE_PROMOTION.md) (which gates
*model/tier* changes) and [`CATALOG_HYGIENE.md`](CATALOG_HYGIENE.md) (which
gates catalog edits).*

Prompt versioning (`STAGE_PROMPT_VERSIONS`, `DEMO_DAY_STAGE_PROMPT_VERSIONS`,
`STORYBOARD_PROMPT_VERSION`, `COMPRESSION_VERSION`, `REFINE_PROMPT_VERSION`,
`SPEC_CLARIFICATION_PROMPT_VERSION`, `INCREMENT_PROMPT_VERSION`) has always been
a **tracking** mechanism tied to the cost ledger and telemetry. Until this
document, it was not a **review-gate** mechanism: nothing required the
golden-corpus eval to pass *before* a prompt-text edit merged, the way
`ROUTE_PROMOTION.md` gates a model/tier change. This is that gate.

## The rule

Any edit to a prompt's system or user prompt text — the string(s) actually
sent to a model — must:

1. **Bump the version constant** for that prompt (see the table below for
   which one). If the prompt has no version constant, add one; the three that
   were missing (`spec_clarification.py`, `increment_service.py`, the
   `refine` prompt in `stage_manager.py`) are now covered — there should be no
   fourth.
2. **Run the golden-corpus eval** (`cd harness && PYTHONPATH=.
   python -m prompt_eval.run --version <new> --baseline <old>`) for any prompt
   the suite covers (currently: `spec`, `plan`, `harness`, `tasks`). Attach the
   report (or its PASS/FAIL summary) to the PR. A regression must be resolved
   or explicitly justified before merging, not silently accepted.
3. **For a prompt the golden-corpus suite does not yet cover** (`critic.py`,
   `pr_evaluator.py`, `online_eval.py`, `harness_patch.py`, `increment_service.py`,
   the `refine` prompt, `problem_compressor.py`, `spec_clarification.py`) — run
   the module's own unit tests (every prompt-construction function in this
   codebase has at least a "renders the expected instruction" test; add one if
   missing) and state in the PR description that no golden-corpus equivalent
   exists yet. This is a known gap (see the remediation plan's "good-hygiene"
   backlog: `harness_patch.py`, `increment_service.py`, and the judges
   themselves have no golden-corpus/grader coverage) — the manual unit-test
   step is the interim substitute, not a replacement for eventually closing it.

A prompt-text edit that ships without a version bump is a process defect, not
just a missed convention — it means a quality regression on that prompt has no
telemetry signal to catch it and no version boundary to bisect against.

## Which constant to bump

| Prompt(s) | Constant | Location |
|---|---|---|
| `spec.py`, `plan.py`, `harness.py`, `tasks.py` (standard) | `STAGE_PROMPT_VERSIONS[stage]` (built from `ASDD_PROMPT_VERSION` + a per-stage suffix) | `prompts/base.py` |
| `demo_day.py` (4 variants) | `DEMO_DAY_STAGE_PROMPT_VERSIONS[stage]` (built from `DEMO_DAY_PROMPT_VERSION`) | `prompts/base.py` |
| `storyboard.py` | `STORYBOARD_PROMPT_VERSION` | `prompts/storyboard.py` |
| `problem_compressor.py` | `COMPRESSION_VERSION` | `services/pipeline/problem_compressor.py` |
| `spec_clarification.py` | `SPEC_CLARIFICATION_PROMPT_VERSION` | `prompts/spec_clarification.py` |
| `increment_service.py` | `INCREMENT_PROMPT_VERSION` | `services/pipeline/increment_service.py` |
| `refine` (interactive rewrite) | `REFINE_PROMPT_VERSION` | `services/pipeline/stage_manager.py` |

**Shared-infrastructure exception.** A change to `prompts/base.py` — most
notably `wrap_untrusted_content`, `SECURITY_AND_PRIVACY_RULES`,
`PROFESSIONAL_OUTPUT_RULES`, or `ASDD_METHODOLOGY_OVERVIEW` — changes the
*rendered* prompt of every consumer even when that consumer's own prompt text
is untouched. Bump `ASDD_PROMPT_VERSION` (and `DEMO_DAY_PROMPT_VERSION` if
Demo Day is affected, which it is for anything routed through
`wrap_untrusted_content`) rather than every individual per-stage suffix, and
bump the affected judge/utility prompts' own constants (`STORYBOARD_PROMPT_VERSION`,
etc.) separately since they are not part of `STAGE_PROMPT_VERSIONS`. When only
*one* stage's own prompt text changes (e.g. `plan.py`'s hard-denylist
sentence), bump only that stage's per-stage suffix — do not bump the shared
prefix for an unrelated stage's edit.

## Judge/utility prompts without a version constant

`critic.py` and `pr_evaluator.py` are deliberately excluded from the version
table above: both are held inline per the Phase 19 Security Directive
specifically so they are never subject to a remote (Langfuse) override, and
neither currently participates in cost-ledger telemetry keyed by prompt
version. If either grows a materially different verdict schema or grading
rubric, add a version constant at that time rather than retrofitting one
speculatively now — the review-gate rule above (run the module's unit tests,
state it in the PR) still applies to them today.

## Why this is separate from `ROUTE_PROMOTION.md`

`ROUTE_PROMOTION.md` gates *which model runs* — a routing/tier decision with
its own cost and latency tradeoffs, evaluated by the dry-run + manual live
gate described there. This document gates *what the prompt says* — a content
change with its own quality/security tradeoffs, evaluated by the golden-corpus
suite (`harness/prompt_eval/`) plus the introspection checklist in
`audit/remediation-plan.md`'s parent skill/process (intent clarity, output
contract, edge-case handling, injection surface, no vague hedges). The two
gates can both apply to the same PR (e.g. a prompt-text edit that also changes
which tier a stage routes to), in which case satisfy both.
