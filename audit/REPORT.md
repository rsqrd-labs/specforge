# SpecForge Prompt Quality Audit — Executive Report

**Scope:** every prompt sent to any model, anywhere in this codebase.
**Method:** call-site tracing backward from every LLM adapter invocation,
verified against a repo-wide keyword/grep sweep for prompt-shaped text and
downstream-agent-facing artifacts. Read-only — zero prompt files were
modified.

## Coverage statement

- **21 prompt/prompt-fragment sources found and scored** (see
  `prompt-inventory.md` for the full table, `scorecards/` for the 21
  individual 14-dimension evaluations).
- **Discovery method:** traced every call into `anthropic_adapter.py` /
  `openai_adapter.py` / `google_adapter.py` back through
  `gateway.get_llm` / `gateway.call_judge_model` / `complete_background_llm` /
  `InstrumentedAdapter.complete|stream` to its caller. Confirmed exhaustive by
  a second, independent grep for every call-site pattern
  (`get_llm(`, `call_judge_model(`, `adapter.complete(`, `adapter.stream(`,
  `complete_background_llm(`) across `backend/services` and
  `backend/routers`; every file that matched maps to a row in the inventory.
  No router calls a model directly, and a targeted frontend grep confirmed no
  client-side prompt construction exists.
- **Known blind spot (by design, per user direction at the start of this
  audit):** `prompts/base.py`'s Langfuse remote-prompt override
  (`load_prompt`) can serve live prompt content this audit has no
  credentials to read; only the in-code fallback and the override mechanism
  itself were evaluated (P01).
- **One discovery miss, caught and corrected:** the initial Phase-1 pass
  missed `agents_md_builder.py` (P21) — found only because
  `agent_manual_service.py`'s own docstring named it as a sibling. This is
  exactly the kind of gap the mandated Phase-1 checkpoint exists to catch,
  and it turned out to matter: P21 is the concrete evidence that closes the
  report's #1 finding (see below).
- **Advisor subagent was unavailable this session.** Per the audit's
  fallback instruction, an explicit self-adversarial pass was performed
  instead for every SHIP-BLOCKER candidate and the three highest-rated
  prompts (Phase 4). Three findings were **downgraded** after arguing against
  them, and the adversarial exercise **surfaced one new systemic finding**
  (the P01 delimiter-injection gap) that the first-pass, per-prompt scoring
  had rated favorably. This is disclosed throughout rather than presented as
  an external second opinion.

## Score distribution / condensed heatmap

Full 14-dimension tables with `file:line` evidence live in
`scorecards/<id>.md`. Condensed here: final verdict plus the lowest-scoring
dimensions (the ones that matter for prioritization).

| ID | Prompt | Verdict | Lowest dimensions (score) |
|----|--------|---------|---------------------------|
| P14 | online_eval judge | **SHIP-BLOCKER** | Injection safety (1), interpolation safety (1) |
| P01 | base.py shared infra | HIGH | Interpolation safety (2) — systemic, inherited by every consumer |
| P12 | agent_manual_service (CLAUDE.md/AGENTS.md) | HIGH | Injection safety (1), interpolation safety (2), eval coverage (2) |
| P10 | critic.py (quality-gate judge) | HIGH | Token/cost efficiency (2) |
| P09 | spec_clarification | HIGH | Injection safety (2) |
| P15 | pr_evaluator | HIGH | Interpolation safety (2) |
| P02 | spec.py | HIGH | Edge-case handling (3), determinism (3) |
| P06 | harness_patch | HIGH | Eval coverage (3) |
| P07 | demo_day (4 variants) | HIGH | Examples (3), cost efficiency (3), determinism (3) |
| P18 | refine (interactive) | HIGH | Examples (3), maintainability (3), eval coverage (3) |
| P19 | chunk-continuation contract | HIGH | (qualitative: unbounded `prior_chunks`) |
| P03 | plan.py | EXEMPLARY | Cost efficiency (3), determinism (3) |
| P04 | harness.py | EXEMPLARY | Determinism (3) |
| P05 | tasks.py | EXEMPLARY | Determinism (3), examples/edge-case tension |
| P13 | increment_service | MEDIUM | Examples (3), maintainability (3) |
| P20 | critic-findings regen augmentation | MEDIUM | — |
| P08 | storyboard.py | EXEMPLARY | (held up under adversarial testing) |
| P11 | problem_compressor Rung-2 | EXEMPLARY | — |
| P16 | provider health check | EXEMPLARY | — |
| P17 | research grounding frame | EXEMPLARY | — |
| P21 | agents_md_builder (generic) | EXEMPLARY | — |

**Reading this table:** "HIGH" here is doing double duty for two different
shapes of problem — genuine defects (P01, P09, P10, P12, P15) and prompts
that are otherwise excellent but carry one or two concrete, fixable gaps
(P02, P06, P07, P18, P19). Only P14 met this audit's bar for SHIP-BLOCKER: a
certain, non-adversarial, silently-triggered correctness bug.

## Top 10 findings (ranked by severity × likelihood × user-visibility)

1. **[SHIP-BLOCKER] Online-eval judge prompt corruption via chained `.replace()`** — `backend/services/evals/online_eval.py:979-982`. `_build_eval_prompt` does `_STAGE_PROMPTS[stage_type].replace("{spec_content}", context).replace("{content}", artifact)`. If `context` (the compacted spec/dependency text) contains the literal substring `{content}` — plausible in ordinary, non-adversarial generated output (e.g. an API Design section showing an example JSON body with a `"content"` field, common for any comment/message/CMS-shaped product) — the second `.replace()` also matches that occurrence and splices the artifact-under-evaluation into the wrong place in the prompt, **silently**, corrupting the score with no error surfaced. Feeds the user-facing quality badge. **Fix:** single-pass substitution (e.g. `re.sub` with a callback, or build via `str.format_map` against a dict after escaping literal braces once) instead of chained `.replace()`.

2. **[HIGH, systemic] `wrap_untrusted_content`'s delimiters are not escaped against appearing inside the wrapped content** — `backend/prompts/base.py:174-182`. Found via the mandatory Phase-4 adversarial pass, not the first-pass per-prompt review (which rated this function's usage 5/5 everywhere). A wrapped value containing the literal delimiter/sentinel strings can render a spoofed fence-closing sequence that is textually indistinguishable from a real one. Inherited by **every** prompt that calls this function — effectively the whole codebase (P02-P08, P11, P13, P15, P18-P20). Partially mitigated by the role-based (not tag-based) authority-hierarchy instruction in `SECURITY_AND_PRIVACY_RULES`, and by the fact that no application code re-parses model-visible text back into real API message roles — so this is a real, but not a clean, bypass. **Fix once, fixes everywhere:** escape literal delimiter occurrences in `content`, or suffix tags with a per-request nonce.

3. **[HIGH] Unsanitized PLAN.md splice into `CLAUDE.md`/`AGENTS.md` — a cross-agent trust-escalation gap with an already-built fix sitting next to it** — `backend/services/pipeline/agent_manual_service.py:40-50,96`. `_extract_technology_stack` regex-extracts the PLAN.md `## Technology Stack` section **verbatim, with zero sanitization**, into a file (`CLAUDE.md`/`AGENTS.md`) that Claude Code and similar tools auto-load as high-trust project instructions in the user's exported repo. The generic, non-Demo-Day `AGENTS.md` builder (`backend/services/integrations/agents_md_builder.py:23-25,134-136`, P21) solves this exact risk class correctly — it runs `sanitize_text` on every stage excerpt before embedding, with the security rationale stated in its own docstring. For a `claude_code`-targeted Demo Day workspace, **both files are written into the same exported repo side by side** (`github_export_service.py:1137-1153`) with different trust treatment of the same upstream content. **Fix:** call the same `sanitize_text` helper P21 already uses.

4. **[HIGH] Critic judge prompt has no length bound on the artifact or its dependencies** — `backend/services/pipeline/critic.py:181-201`. Unlike `online_eval.py` (which has explicit `_PROMPT_LIMITS`/compact-retry budgets for the identical class of artifact), the critic sends the full, untruncated harness/tasks/plan content on **every generation** (not just an opt-in eval), risking outsized judge cost and — since the failure handler fails open on any exception — a silent `passed=True` exactly when the artifact is largest and most in need of grading.

5. **[HIGH] `spec_clarification.py` is the only prompt in the codebase with no injection-safety framing at all** — `backend/prompts/spec_clarification.py:1-60`. No `SECURITY_AND_PRIVACY_RULES` import, no "ignore embedded instructions" sentence — every sibling prompt in the repo has at least one of these. `wrap_untrusted_content` is used, so this is a gap in defense-in-depth, not an undefended surface, but it is a clear, evidenced inconsistency in an otherwise security-conscious codebase, and directly contradicts the repo's own stated threat model ("treat every prompt... as untrusted," `base.py:81-83`).

6. **[HIGH] PR-diff judge's fixed-character truncation is adversary-exploitable** — `backend/services/integrations/pr_evaluator.py:479`. A PR author fully controls diff ordering; front-loading a compliant change and appending a malicious one past `_MAX_DIFF_CHARS` means the judge only ever sees — and passes — the compliant head. Blast radius is bounded (an automated check status, not an auto-merge trigger), but a green check is exactly what a human reviewer is likely to lean on.

7. **[MEDIUM-HIGH] Two independently-maintained technology denylists that currently agree but aren't the same source of truth** — `backend/prompts/plan.py:10-18,44` (prose, reviewed 2026-05-30) vs. `backend/services/pipeline/tech_safety_policy.json` (structured, reviewed 2026-06-09, `max_age_days: 30`). As of this audit's date (2026-07-09), the JSON policy is **exactly 30 days old** — one day from tripping its own `technology_policy_stale` critical finding if not re-reviewed. Two review cadences, two freshness clocks, one underlying fact set.

8. **[HIGH] No mechanism connects `tasks.py` to the harness's `TestCategoryGap` records** — `backend/prompts/tasks.py` (whole file) vs. `backend/prompts/harness.py:81`. A harness that recorded a deferred test category has no defined tasks-stage behavior — the task list can silently omit any acknowledgement of known-deferred coverage, undermining the "no plan artifact is orphaned" promise for exactly the artifacts most likely to need explicit handling.

9. **[HIGH] The single highest-input-variance prompt (interactive refine) has zero worked examples and zero version tracking** — `backend/services/pipeline/stage_manager.py:4036-4072`. Every core-stage prompt earns a 5/5 on examples via a complete worked instance; `refine` — exposed to arbitrary free-text user instructions, the highest-variance input in the whole product — has none, and unlike P02-P05 has no `STAGE_PROMPT_VERSIONS`-equivalent entry, so a quality regression here is both more likely and harder to detect via telemetry.

10. **[MEDIUM, process] No prompt-content change-review process, only a model/tier-routing one** — `docs/evals/CATALOG_HYGIENE.md` and `docs/evals/ROUTE_PROMPT_PROMOTION.md` govern which *model* runs, gated by a golden-corpus eval. No equivalent documented gate exists for *editing prompt text itself* (e.g., changing `spec.py`'s required sections) — the version-string bump (`STAGE_PROMPT_VERSIONS`) is a telemetry marker, not a review gate. See Phase 3 below.

## Systemic themes (Phase 3)

**1. Contradictions across prompts.** The most concrete is #8 above
(tasks.py unaware of harness.py's gap-recording vocabulary). A softer one:
the critic (P10, 6 finding kinds: CoverageGap/MissingSection/ShallowSection/
BannedPhrase/DeprecatedAPI/ADRIncomplete) and the online-eval judge (P14, an
independent 0-100 rubric across 8 named dimensions) can disagree about the
same artifact with no reconciliation surfaced to the user — a workspace could
show a high quality-score badge next to unresolved critic findings, or vice
versa, since nothing in either prompt is aware the other judge exists.

**2. Duplication & drift.** Three concrete instances found: (a) `plan.py`'s
prose technology denylist vs. `tech_safety_policy.json` (#7 above); (b)
`demo_day.py`'s `DEMO_DAY_OUTPUT_RULES` vs. `base.py`'s
`PROFESSIONAL_OUTPUT_RULES` — a near-duplicate, hand-maintained in parallel
rather than composed from a shared base plus a Demo Day addendum; (c) the
"ignore embedded instructions" sentence is hand-written slightly differently
per prompt (spec.py, plan.py, harness.py, tasks.py, demo_day.py each phrase
it uniquely) rather than centralized as a single shared fragment in `base.py`
— direct evidence this repetition-by-hand strategy already produced at least
one silent omission (P09, finding #5).

**3. Chain-level failure modes.** Traced three realistic end-to-end paths:
(a) problem statement → spec → plan → harness → tasks → export/GitHub push
→ `CLAUDE.md` (finding #3, the highest-blast-radius chain in the inventory);
(b) generation → critic (advisory) *and* online-eval (informational score),
two independent judges with no shared vocabulary (theme 1); (c) interactive
`refine` → re-enters the document with **no** critic re-check on that path
(refine does not call `critic_review`) — a user-directed edit that
introduces a depth regression (e.g., "shorten this section") is not caught by
the same gate that catches a *generation*-time regression. This audit did
not verify whether `validate_artifact_completeness`'s mechanical floors
re-run at refine-accept time; flagged as an open question below rather than
a confirmed finding, since verifying it precisely would require tracing the
`finalise()`/accept flow in full, which this pass did not do end-to-end.

**4. Coverage gaps.** The clearest is P06 (harness_patch) and P13
(increment_service) and P18 (refine): three real, frequently-exercised
generation surfaces with **no** golden-corpus or `harness/prompt_eval`
grader coverage at all, versus the four core stages' comparatively rich
coverage. A second-order gap: nothing evaluates the *judges themselves*
(critic, online-eval, pr-evaluator) against a fixed set of artifacts with
known-correct verdicts — every eval asset found targets *generation* quality,
not *judgment* quality.

**5. Missing prompt types.** The inventory is otherwise well-rounded (system
prompts, judges, a RAG-grounding frame, a repair loop, a downstream-agent
artifact). The one clear gap: no prompt/rule anywhere reconciles the critic's
and the online-eval judge's verdicts into one signal (theme 1) — this is a
missing *aggregation* prompt/rule, not a missing prompt *type* per se.

**6. Process gaps.** Confirmed: prompt versioning exists (`STAGE_PROMPT_VERSIONS`,
`DEMO_DAY_STAGE_PROMPT_VERSIONS`, `STORYBOARD_PROMPT_VERSION`,
`COMPRESSION_VERSION`) and is real, tied to telemetry/cost-ledger. But it is a
**tracking** mechanism, not a **review-gate** mechanism — nothing found
requires the golden-corpus eval to pass *before* a prompt-text edit merges,
the way `docs/evals/ROUTE_PROMOTION.md` gates a *model/tier* change. Three
prompts (`spec_clarification.py`, `increment_service.py`, the `refine`
prompt in `stage_manager.py`) have **no version constant at all** — edits to
these are invisible to the versioning discipline applied everywhere else.

**7. Consistency of voice/brand.** Strong and consistent across the four
core stages and Demo Day (shared `ASDD_METHODOLOGY_OVERVIEW`/
`SECURITY_AND_PRIVACY_RULES`/`PROFESSIONAL_OUTPUT_RULES`). The judge/utility
prompts (critic, pr_evaluator, online_eval, spec_clarification,
problem_compressor) each independently author their own voice — reasonable
given they're a different genre (grading, not generating), but there's no
shared "judge persona" fragment analogous to the shared generation
fragments, so their tone (e.g., how bluntly they state grading rules) varies
prompt-to-prompt without a stated reason.

## Phase 4 — adversarial self-review (mandatory)

**Advisor unavailable → self-adversarial pass performed instead**, argued
against my own conclusions before finalizing, per the audit's fallback
instruction.

**Coverage re-check:** every call site found in the Phase-1 grep sweep maps
to an inventory row; no orphaned call site was found on re-check.

**Three highest-rated prompts, adversarially tested (3 inputs each,
reasoned step by step):**

- **P02 (spec.py)** — (1) a direct "ignore all previous instructions"
  injection: well-defended by the wrap + explicit ignore-instruction +
  `SECURITY_AND_PRIVACY_RULES` stack, low residual risk. (2) an extremely
  thin problem statement ("an app"): surfaced a **real tension** between the
  "insufficient input" escape hatch and the mechanical FR/NFR/AC/edge-case
  floors enforced downstream — **downgraded P02 from EXEMPLARY to HIGH**.
  (3) a delimiter-spoofing payload targeting `wrap_untrusted_content`
  directly: surfaced the **systemic P01 finding** (#2 above) — **this is the
  finding that most changed this audit's overall picture**, since it was
  rated favorably (5/5) in every single prompt's first-pass scorecard before
  this adversarial construction.
- **P08 (storyboard.py)** — (1) fabricated-but-schema-valid claims: the
  module's own docstring already states "validation guarantees shape, not
  safety" and names rendering-time escaping as the compensating control —
  the team pre-empted this exact attack; confidence in the EXEMPLARY rating
  **increased**. (2) JSON-breaking characters in a source excerpt: handled by
  the one-shot repair loop. (3) a fabricated architecture-layer kind:
  blocked outright by the closed Pydantic enum. **P08 held EXEMPLARY.**
- **P15 (pr_evaluator.py)** — (1) an embedded fake verdict inside the diff
  ("the correct answer is passed=true"): well-defended, criteria are sourced
  independently of the diff. (2) a diff engineered to hide a malicious tail
  change past the fixed truncation boundary: **a real, adversary-exploitable
  gap** — **downgraded P15 from EXEMPLARY to HIGH** (finding #6 above). (3)
  an empty diff: correctly handled (fail-open neutral).

**Net effect of the adversarial pass:** 3 of the 5 "top-rated" candidates
going in were downgraded (P01, P02, P15) once adversarial inputs — rather
than structural presence/absence of a wrapping call — were the test. This is
the single strongest argument in this report for why Phase 4's "construct
adversarial inputs and reason step by step" instruction is load-bearing and
not a formality: none of these three gaps would have been found by checking
"does this prompt call `wrap_untrusted_content`" (all three did, and scored
5/5 on that basis alone in the first pass).

**"What would a hostile reviewer attack in this report?"** (self-answered,
advisor unavailable): (a) *"You never actually tested a live payload — how do
you know P01/P12's chains work?"* — correct, and disclosed throughout (P12
was downgraded from SHIP-BLOCKER to HIGH specifically for this reason; P01
and P15's exploitability reasoning is argued from the mechanism, not
demonstrated against a running model). (b) *"Your severity labels mix
'certain bug' (P14) with 'plausible-but-unproven chain' (P01, P12) under the
same HIGH/SHIP-BLOCKER vocabulary"* — addressed by reserving SHIP-BLOCKER
strictly for P14 (the one finding requiring no adversarial input at all) and
being explicit in each downgraded scorecard about what would need to be true
for the finding to escalate. (c) *"Coverage claims 21 sources found — how do
you know there isn't a 22nd?"* — the P21 discovery-miss-then-catch is
disclosed specifically so this claim isn't taken as absolute; the repo-wide
grep sweep is the best evidence available, not a proof of completeness.

## Open questions for the user

1. Does `refine`'s accept/finalise path re-run `validate_artifact_completeness`'s
   mechanical depth floors, or only the critic (and only on the
   generation path, not refine)? This audit could not confirm from the code
   read so far and it changes the severity of theme 3(c) above.
2. Is the `plan.py`/`tech_safety_policy.json` denylist duplication (finding
   #7) intentional (prose for the model, JSON for the deterministic gate,
   deliberately kept separate) or an accident of two features shipping at
   different times? This changes whether the remediation is "unify" or
   "just add a shared freshness-review calendar reminder."
3. Is verbosity/format drift across the five independent judge prompts
   (theme 7) acceptable, or should they share a "judge persona" fragment the
   way the four core stages share `base.py`?
4. Should this audit's severity language (SHIP-BLOCKER reserved for
   certain/non-adversarial bugs; HIGH for plausible-but-unproven chains) be
   the standing convention for future prompt reviews, given no advisor
   subagent was available to calibrate against this run?

See `remediation-plan.md` for the prioritized backlog.
