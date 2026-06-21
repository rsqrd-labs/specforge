# Problem-Statement Compression Plan

Make core generation **fail-proof and cost-bounded for any input size**, including
pathological pastes (hundreds of pages), without weakening requirement fidelity for
normal input or silently rewriting the user's source-of-truth.

This plan is grounded in the current code, not a generic NLP brief. The stack has no
spaCy/HuggingFace and does not need them: the abstractive path already exists
(`stage_summary_service.py` / `summarize_stage_content`, the cheap `JUDGE_MODELS`
selector), and an extractive, section-aware reducer already exists for *upstream
artifacts* (`_section_aware_injection` in `prompt_builder.py`). The gap is that the
**user's problem statement is never reduced at all**.

---

## 1. The goal, stated as an invariant

The product requirement is not "summarize long inputs." It is two hard guarantees:

1. **No generation fails because the input is large.**
2. **No generation becomes uncontrollably expensive because the input is large.**

Both fall out of a single invariant that this plan is built around:

> **Bounded-cost invariant.** Every LLM call in a generation — the compression pass
> *and* every stage/repair call — receives at most `C_MAX` input tokens of
> problem-statement content, emits at most its existing per-operation output budget,
> and the number of calls per generation is bounded by a constant. Therefore the
> total cost of a generation has a **fixed upper bound independent of input size**,
> and no call can exceed the model context window on account of input size.

The bound is the product of three things, two of which are *already* bounded today:

| Factor | Bound | Source |
|--------|-------|--------|
| Problem-statement input per call | ≤ `C_MAX` tokens | **new** — the clamp in this plan |
| Output per call | ≤ `OUTPUT_TOKEN_BUDGETS[op]` (24576 for spec), doubling-repair capped at model ceiling | `output_budget.py` (exists) |
| Calls per generation | 1 generate + ≤1 limit-stop repair + ≤1 critic regenerate + ≤1 tier-escalation retry | `stage_manager.py` (exists) |

So the only missing piece is the first row: **clamp problem-statement input to a
constant before any model sees it.**

## 2. Current state (grounded in code)

| Fact | Location | Consequence |
|------|----------|-------------|
| `problem_statement` is an **uncapped** `Text` column | [`models/workspace.py:43`](../backend/models/workspace.py#L43) | Any size can be stored. |
| It is injected raw into the prompt, **never reduced** | [`prompt_builder.py:130`](../backend/services/pipeline/prompt_builder.py#L130) | The unguarded path. |
| Only **upstream stage artifacts** get reduced | `_section_aware_injection`, [`prompt_builder.py:87`](../backend/services/pipeline/prompt_builder.py#L87) | Downstream stages (plan/harness/tasks) are already bounded; the problem statement is not. |
| Exactly **three** consumers read `problem_statement` | spec [`prompts/spec.py:116`](../backend/prompts/spec.py#L116), storyboard [`prompts/storyboard.py:637`](../backend/prompts/storyboard.py#L637), clarifier [`prompts/spec_clarification.py:46`](../backend/prompts/spec_clarification.py#L46) | Plan/harness/tasks consume the **spec artifact**, not the problem statement — so the cost driver is "spec gen + every spec regen + storyboard," not a 4× duplication. |
| Token sizing heuristic already exists | `estimate_tokens` (bytes/4), [`services/llm/usage.py`](../backend/services/llm/usage.py) | Reuse it; do **not** add a tokenizer dependency. |
| Cheap judge-model selector already exists | `JUDGE_MODELS[provider]` (Haiku / GPT-5.4 Mini / Flash), used by `spec_clarifier` | Reuse it for any abstractive pass. |
| Abstractive summarizer already exists | `summarize_stage_content` / `stage_summary_service.py` | Reuse it; do not hand-roll. |
| Critic/clarifier are **fail-open** with `asyncio.timeout(5.0)` | `critic.py`, `spec_clarifier.py` | Compression must follow the same contract — never brick a generation. |

**Net:** the problem statement is the one input on the spec path with no size ceiling.
Closing it with a *free, deterministic clamp* delivers both guarantees; an abstractive
polish on top is an optional quality add-on that is also bounded because it runs on
already-clamped input.

## 3. Why the obvious approaches fail the invariant

- **Reject oversized input (HTTP 422).** Violates guarantee #1 — a rejection *is* the
  generation failing. Not acceptable.
- **Abstractively summarize the raw input.** Moves cost, does not bound it: feeding 200
  pages to the cheap model costs in proportion to input size. Map-reduce/chunking has
  the same flaw unless the chunk count is capped — at which point it is just a clamp
  with extra steps.
- **Truncate to the first N chars.** Bounds cost but destroys requirement fidelity
  blindly (drops whatever is at the end) — fails the source-of-truth constraint.

The fix is a **structure-aware clamp that always terminates at `C_MAX`**, runs with
zero model cost, and keeps the highest-value (normative) content first.

## 4. Design — a conservative ladder that always terminates

Applied lazily inside `build_prompt` for the spec stage (and the storyboard / clarifier
consumers) via a shared helper. Climb only as far as needed; stop at the first rung that
fits the budget.

```
compressed = get_or_compress(workspace.problem_statement, budget)   # cached by content hash
```

**Rung 0 — No-op (common case).** If `est_tokens(problem) ≤ budget`, return the input
unchanged. Byte-identical to today; preserves provider prompt caching. Most workspaces
never leave this rung.

**Rung 1 — Lossless structural reduction (zero LLM cost, deterministic).**
Collapse whitespace/blank-line runs; de-duplicate repeated paragraphs/boilerplate
(common in pasted PRDs and email threads); strip signatures, page headers/footers,
"confidential" footers. Pure Python, O(n), always terminates. Often recovers 15–30% on
pasted material at no quality cost.

**Rung 2 — Structure-preserving extractive clamp (zero LLM cost, deterministic — THIS is the guarantee).**
Partition the document (reuse the `_split_by_h2` / keep-verbatim pattern from
`_section_aware_injection`):
- **Normative / enumerable content kept verbatim, highest priority** — anything with
  "must / shall / should", numbered or bulleted lists, acceptance-style statements,
  tables, IDs. These are latent requirements; never summarized, never dropped before
  narrative.
- **Narrative content** (background, rationale, prose) — lowest priority, truncated
  first.

Fill a `C_MAX`-token budget normative-first, then narrative until full. **This rung
always produces an output ≤ `C_MAX`, for input of any size, with no model call.** It is
the rung that makes both guarantees true. A metric mirrors
`pipeline_upstream_section_skipped_total` so dashboards see when/what was clamped.

**Rung 3 — Abstractive polish of *narrative only* (LLM, optional, also bounded).**
Only after Rung 2 has clamped input to ≤ `C_MAX`. Summarize **only** the narrative
partition via `summarize_stage_content` with `JUDGE_MODELS[provider]`, then
re-concatenate `[verbatim normative] + [narrative summary]`. Because its input is
already ≤ `C_MAX`, its cost is bounded. Wrapped in `asyncio.timeout(5.0)`; on any error
it **fails open to Rung 2's output**. This rung improves quality on large input; it is
*not* required for the guarantees and can ship later (or never).

**Clarifier interplay.** Compression is for *long*, not *vague*. Gate Rung 3 behind a
length threshold so short-but-rambling input routes to the existing clarification Q&A
flow (which *adds* structure) instead of lossy summarization — mirroring the
"ambiguity gated behind length" rule in `complexity_classifier.py`.

### Invariants this design must hold

- **Never mutate the stored `problem_statement`.** Compress to a derived, Redis-cached
  value keyed by `sha256(raw) + budget_bucket + prompt_version`. The user's original
  always survives; regenerates and the storyboard reuse the cache (the cost win
  compounds exactly where the cost is — repeated spec calls).
- **Run after `sanitize_text` + `PromptGuard`, never before** — preserve the existing
  trust-boundary ordering.
- **Fail open** — compression errors degrade to the deterministic Rung 2 output, never
  to a failed generation.
- **Surface to the user** — when Rung ≥2 fired, attach a non-blocking notice via the
  existing `AdvisoryFindingsPanel` channel: "Your problem statement was condensed for
  generation; your original is preserved."

## 5. Budget & ratio math (reuse `estimate_tokens`, no new tokenizer)

`C_MAX` is computed against the **whole assembled spec prompt**, not the problem
statement in isolation (late inputs — `research_context`, `clarification_qa`, system
prompt — stack with it):

```
window         = model_context_window(provider, model)        # model_catalog
output_budget  = OUTPUT_TOKEN_BUDGETS["spec.generate"]        # 24576, reserved
safety         = 0.15 * window                                # reasoning + caching slack
fixed          = est(system_prompt) + est(research_context) + est(clarification_qa)
C_MAX          = window - output_budget - safety - fixed      # tokens left for problem statement
```

Compression ratio is a **derived target, never a fixed knob**:

```
target_ratio = min(1.0, C_MAX / est(problem_statement))
```

`target_ratio == 1.0` ⇒ Rung 0. The ladder climbs only until
`est(compressed) ≤ C_MAX`. Because the core-gen models here have **200K+ windows**
(Gemini ~1M), `C_MAX` is large and Rungs 0–1 satisfy nearly all real input; Rung 2 is
the safety floor for pathological input; Rung 3 is quality polish.

**Worked cost ceiling (spec stage, illustrative).** With input clamped to `C_MAX`
tokens and the bounded call count from §1, the maximum input tokens billed for a single
spec generation is `C_MAX × (1 generate + ≤1 repair + ≤1 critic regen + ≤1 escalation)`
≈ `4 × C_MAX` — a constant, whether the user pasted 2 pages or 2,000.

## 6. Integration seat

Lazily inside [`build_prompt`](../backend/services/pipeline/prompt_builder.py#L120),
beside `_section_aware_injection` — **not** a workspace-creation hook (creation-time
compression would be wrong if budgets/models later change, and would fight the
"never mutate stored value" rule).

```python
# prompt_builder.build_prompt, spec branch
raw = workspace.problem_statement
budget = _spec_problem_budget(provider, model, research_context, clarification_qa)
deps["problem_statement"] = await get_or_compress(raw, budget, redis, provider)
```

`get_or_compress` is a new module, e.g. `services/pipeline/problem_compressor.py`,
applied at all three consumers (spec, storyboard, clarifier) via the shared helper.

## 7. The unavoidable tradeoff (state it honestly)

You can guarantee **never-fails + bounded-cost for any size**. You **cannot also**
guarantee full requirement fidelity for unbounded input — capturing 2,000 pages of
requirements in a `C_MAX`-token spec is physically impossible. Beyond `C_MAX` the
behavior is **graceful degradation**: the spec always generates, always stays under the
cost ceiling, and covers the highest-priority (normative, verbatim-kept) content first,
condensing the rest — with the advisory UI notice telling the user their input was
condensed. The rejected alternative (422) is the one thing the product goal forbids.

## 8. Roadmap

**Phase A — Instrument (no behavior change).** Add Prometheus gauges for assembled
spec-prompt token size and `problem_statement` token size at generation time. Read the
real distribution from the `llm_cost_events` ledger (same evidence-gated approach as
`scripts/analyze_output_budgets.py`). *Exit: data on what fraction of workspaces would
ever leave Rung 0/1 — confirms whether Rung 3 is worth building at all.*

**Phase B — Rungs 0–2 + the clamp (delivers both guarantees).** Pure-Python,
deterministic, zero LLM cost, lazy in `build_prompt` behind a default-off flag
(`problem_statement_compression`). Unit-tested + offline golden corpus alongside
`asdd_route_golden.json`. *Exit: for input of arbitrary size, assembled spec prompt is
provably ≤ window; Rung-0 output is byte-identical for under-budget input (regression
pin).* **This phase alone satisfies the product goal.**

**Phase C — Rung 3 (abstractive narrative polish), only if Phase A justifies it.**
Reuse `summarize_stage_content` + `JUDGE_MODELS`, fail-open, length-gated against the
clarifier. Quality gate: a **normative-retention eval** — count distinct normative
statements (must/shall/numbered items) before vs. after; promote only at ~zero loss of
normative content, mirroring the live gate in `docs/evals/ROUTE_PROMOTION.md`.

**Phase D — Enable + UI surfacing.** Flip the flag after the gate; ship the advisory
"condensed" notice. *Exit: input-token cost per long-input workspace drops; zero
increase in spec quality-gate failures or user-reported missing requirements.*

## 9. Success metrics

| Metric | Target |
|--------|--------|
| Max assembled spec-prompt tokens, any input size | ≤ window − output_budget − safety (hard ceiling) |
| Max billed input tokens per spec generation | ≤ `~4 × C_MAX` (constant, size-independent) |
| Generation failures attributable to input size | **0** |
| Rung-0 byte-identical output for under-budget input | 100% (regression pin) |
| Normative-content retention (Rung 3, the critical one) | ~99–100% |
| Added latency (Rungs 0–2 / Rung 3) | ~0 / <3s p95 |
| Compression LLM cost for the common case (Rungs 0–2) | $0 |

## 10. Recommended cut line

Ship **Phases A–B only** and stop unless Phase A's data proves otherwise. The
deterministic clamp (Rung 2) is what delivers "never fails + bounded cost for any
size." Abstractive summarization of a source-of-truth document (Rung 3) is added quality
at the cost of lossiness and an LLM call — build it only if real workspaces are shown to
genuinely exceed `C_MAX` after lossless reduction.

---

## Open questions

- **`C_MAX` per provider vs. fixed.** Derive per (provider, model) from
  `model_catalog` window, or pin one conservative constant for determinism in the golden
  corpus? (Leaning: derive, but bucket for cache-key stability.)
- **Storyboard budget.** Storyboard has its own output budget and escalation path; does
  it want the same `C_MAX` or a tighter one? (Confirm against `storyboard_service.py`.)
- **Clarifier length gate threshold.** Where exactly does "vague → clarify" hand off to
  "long → compress"? Tune against Phase A data.
