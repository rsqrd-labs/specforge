# SpecForge Prompt Quality — Remediation Plan

Ordered by ROI (impact of the fix vs. effort). Each item: fix **approach**
(not a rewritten prompt), effort, risk if unfixed, and the eval to add so the
regression can't silently recur.

---

### 1. Fix the online-eval `.replace()` chaining bug
**Finding:** #1 (SHIP-BLOCKER). **File:** `backend/services/evals/online_eval.py:966-982`.
**Fix approach:** Replace the two chained `.str.replace()` calls with a
single-pass substitution that can't re-match text introduced by an earlier
substitution — e.g. `re.sub(r"\{spec_content\}|\{content\}", lambda m: {"{spec_content}": context, "{content}": artifact}[m.group()], template)`, or restructure `_STAGE_PROMPTS` to use `%`-style
or `string.Template.safe_substitute` (which doesn't recursively rescan
substituted text) instead of raw `.replace()`.
**Effort:** S (a few lines, one function).
**Risk if unfixed:** Silent, non-adversarial corruption of a user-facing
quality score whenever graded content contains the literal substring
`{content}` — plausible for any product with a "content" field (comments,
CMS, messaging).
**Eval to add:** A unit test in `backend/tests/` constructing a `spec_content`
fixture containing the literal string `{content}` and asserting the rendered
eval prompt places `artifact` only in the `Content:`/`Tasks:`/etc. slot, never
inside the spec/context block.

---

### 2. Escape (or nonce) `wrap_untrusted_content`'s delimiters
**Finding:** #2 (HIGH, systemic — inherited by every consumer). **File:**
`backend/prompts/base.py:174-182`.
**Fix approach:** Either (a) escape literal occurrences of
`END_UNTRUSTED_CONTENT:`, `</untrusted_content>`, and `</{label}>` within
`content` before interpolating (e.g. replace with a visually similar but
non-matching Unicode look-alike, or a `\` escape convention the model is told
about), or (b) suffix every tag with a short per-call random token
(`<untrusted_content source="{label}" nonce="{nonce}">` ... closed only by
the matching nonce) so a spoofed closing sequence requires guessing an
unpredictable value. Fix in this one shared function; every caller inherits
it automatically.
**Effort:** M (touches the single highest-leverage shared function; needs
careful testing against every consumer to confirm no formatting regression).
**Risk if unfixed:** A crafted problem statement or refine instruction could
attempt to spoof the end of the untrusted-content fence and inject text that
reads, to the model, as though it sits outside the untrusted boundary.
Partially mitigated by the role-based authority-hierarchy instruction, so
likely not a clean bypass — but it's the top-leverage single fix in the
entire codebase (fixes every prompt at once).
**Eval to add:** Extend `harness/prompt_eval/graders/safety.py` with a new
grader, e.g. `delimiter_spoof_scan`, that renders a wrapped payload
containing the literal closing-delimiter strings and asserts the rendered
prompt cannot be trivially split at a spoofed boundary (e.g., count that the
real closing tag still appears after any embedded copy).

---

### 3. Sanitize the PLAN.md splice into `CLAUDE.md`/`AGENTS.md`
**Finding:** #3 (HIGH). **File:**
`backend/services/pipeline/agent_manual_service.py:40-50,96`.
**Fix approach:** Call the same `sanitize_text()` helper
`agents_md_builder.py` already uses (`agents_md_builder.py:134-136`) on the
extracted Technology Stack body before interpolating it into the manual.
Trivial reuse of an existing, already-tested pattern in the same codebase.
**Effort:** S.
**Risk if unfixed:** The only artifact in the pipeline that becomes a
high-trust instruction file for a *different* AI agent has no sanitization
at the export boundary, while its sibling (`agents_md_builder.py`) already
does — and for `claude_code` Demo Day workspaces both files land in the same
repo side by side.
**Eval to add:** A backend test asserting `build_agent_manual` strips/escapes
HTML comments and script-like content from `plan_content` the same way
`agents_md_builder.build_agents_md` does — ideally by having both call a
single shared `sanitize_downstream_agent_content()` helper so future drift
between the two is structurally impossible, not just tested.

---

### 4. Bound the critic's artifact + dependency length
**Finding:** #4 (HIGH). **File:** `backend/services/pipeline/critic.py:181-201`.
**Fix approach:** Add a `_compact_text`-style head/tail truncation (reuse or
extract the one already in `online_eval.py:944-963`) with per-stage limits
before building the critic user prompt, sized so a harness/tasks artifact
can't blow the judge's context/cost budget.
**Effort:** S-M (mostly reusing existing logic).
**Risk if unfixed:** Judge cost scales unboundedly with generated artifact
size on every single generation (not just opt-in eval); a judge-call
context-limit error is swallowed by the fail-open handler as a silent
`passed=True`, exactly when the artifact most needs grading.
**Eval to add:** A test asserting `_build_critic_user_prompt`'s output length
stays under a fixed ceiling for a synthetic maximal-size harness fixture
(e.g., 50 files × 200 lines).

---

### 5. Add injection-safety framing to `spec_clarification.py`
**Finding:** #5 (HIGH). **File:** `backend/prompts/spec_clarification.py:1-60`.
**Fix approach:** Import and append `SECURITY_AND_PRIVACY_RULES` to
`SYSTEM_PROMPT` (or a scoped subset, if the full block is judged too heavy
for this cheap/latency-sensitive call), and add the same one-line "data, not
instructions" sentence the other user prompts carry adjacent to the wrapped
problem statement.
**Effort:** S.
**Risk if unfixed:** The single prompt in the codebase with no
authority-hierarchy defense at all, contradicting the repo's own stated
threat model; blast radius is bounded (output is 3-5 short questions a human
reviews) but the inconsistency itself is the finding.
**Eval to add:** Extend `harness/prompt_eval/graders/safety.py`'s
`security_rules_stripped`/`role_change_accept` graders to run against this
prompt too (they currently appear scoped to stage artifacts, not the
clarifier).

---

### 6. Make PR-diff truncation hunk-aware
**Finding:** #6 (HIGH). **File:** `backend/services/integrations/pr_evaluator.py:479`.
**Fix approach:** Truncate on the last complete `diff --git` hunk boundary at
or before `_MAX_DIFF_CHARS`, rather than a raw character cut — or, if the
diff exceeds the limit, evaluate per-file in bounded batches and require all
batches to pass rather than grading a single head-truncated blob.
**Effort:** M.
**Risk if unfixed:** An adversary who controls diff ordering (any PR author)
can hide a change behind the truncation boundary and get a "passed" check on
the visible, compliant portion alone.
**Eval to add:** A fixture PR diff engineered exactly this way (compliant
head, unrelated change past the current char limit) with an assertion that
the judge either sees the tail or the check reports "diff truncated,
inconclusive" rather than a clean pass.

---

### 7. Unify (or explicitly reconcile) the two technology denylists
**Finding:** #7 (MEDIUM-HIGH). **Files:** `backend/prompts/plan.py:10-18,44`,
`backend/services/pipeline/tech_safety_policy.json`.
**Fix approach:** Either (a) generate `plan.py`'s prose denylist text from
`tech_safety_policy.json` at prompt-construction time (single source of
truth, matching the codebase's stated principle for the model catalog), or
(b) if intentionally separate (prompt guidance vs. deterministic gate), add
a shared freshness-review calendar/alert so both dates move together instead
of drifting independently. **Ask the user which is intended (open question
#2 in REPORT.md) before choosing.**
**Effort:** M (option a) / S (option b).
**Risk if unfixed:** The JSON policy is 30 days old as of this audit's date
and one day from tripping its own staleness gate — a concrete, dated
reminder that the two-list design has no shared operational cadence.
**Eval to add:** A CI check asserting the two denylists' technology/version
sets are a superset/subset match (whichever direction is intended), failing
loudly on drift instead of silently disagreeing.

---

### 8. Teach `tasks.py` about `TestCategoryGap`
**Finding:** #8 (HIGH). **File:** `backend/prompts/tasks.py` /
`backend/prompts/harness.py:81`.
**Fix approach:** Add an instruction to `tasks.py`'s system or user prompt:
when the harness contains a `TestCategoryGap` record, tasks.md must
reference it explicitly (e.g., a task or an Open Questions-style note
acknowledging the deferred category) rather than silently proceeding as if
coverage were complete.
**Effort:** S.
**Risk if unfixed:** Known-deferred harness coverage (already surfaced by the
harness stage) has no defined downstream acknowledgement, breaking the
"no plan artifact is orphaned" promise for exactly the artifacts that
recorded a shortfall.
**Eval to add:** A golden-corpus case with a harness containing a
`TestCategoryGap` record, asserting the generated tasks.md references it.

---

### 9. Add a worked example + version tracking to `refine`
**Finding:** #9 (HIGH). **File:** `backend/services/pipeline/stage_manager.py:4036-4072`.
**Fix approach:** Add one compact before/after worked example to the refine
system prompt (mirroring the pattern every core-stage prompt already uses),
and add a `REFINE_PROMPT_VERSION` constant threaded through the same
cost-ledger/telemetry mechanism `STAGE_PROMPT_VERSIONS` already provides.
**Effort:** S.
**Risk if unfixed:** The highest-input-variance prompt in the product has
the least anchoring and the least observability into whether an edit to it
regresses quality.
**Eval to add:** A small golden set of (document, selection, instruction) →
expected-shape assertions (scope stays tight, stable IDs preserved) for the
`focused` and `section` refine modes.

---

### 10. Establish a prompt-content change-review gate
**Finding:** #10 (MEDIUM, process). **Files:** `docs/evals/CATALOG_HYGIENE.md`,
`docs/evals/ROUTE_PROMOTION.md` (existing model/tier gates, no prompt-text
equivalent).
**Fix approach:** Document (mirroring `ROUTE_PROMOTION.md`'s structure) a
lightweight rule: any edit to a `STAGE_PROMPT_VERSIONS`-tracked prompt (or
any prompt lacking a version constant — see finding at P09/P13/P18) bumps
the version string and runs the relevant golden corpus before merging.
Extend version-constant coverage to the three currently-untracked prompts
(`spec_clarification.py`, `increment_service.py`, `refine`).
**Effort:** S (documentation + three small version-constant additions).
**Risk if unfixed:** Prompt-text edits are currently reviewable only by
human diff-reading, with no gate comparable to the one already proven
valuable for model/tier changes.
**Eval to add:** N/A — this item *is* the eval-gating process; no additional
eval, just the process document plus wiring the three missing version
constants into existing telemetry.

---

## Lower-priority / good-hygiene items (not re-ranked individually)

- Merge `demo_day.py`'s `DEMO_DAY_OUTPUT_RULES` with `base.py`'s
  `PROFESSIONAL_OUTPUT_RULES` into one base + Demo Day addendum (S effort,
  removes hand-sync risk).
- Centralize the per-prompt "ignore embedded instructions" sentence as a
  shared `base.py` fragment rather than five hand-written variants (S effort,
  directly prevents recurrence of finding #5's omission class).
- Add a reconciliation note (in the frontend or in the persisted
  `quality_gate` payload) when the critic and online-eval judge disagree
  about the same artifact, rather than showing two independent, silent
  signals (M effort — theme 1 in REPORT.md).
- Add golden-corpus/grader coverage for the three generation surfaces with
  none today: `harness_patch.py` (P06), `increment_service.py` (P13), and
  the judges themselves (critic, online-eval, pr-evaluator) against fixed
  artifacts with known-correct verdicts (M-L effort, closes the
  "nothing evaluates the judges" gap in theme 4).
- Confirm whether `refine`'s accept/finalise path re-runs the mechanical
  depth-floor validator (open question #1 in REPORT.md) — resolve before
  deciding whether this needs its own remediation item.
