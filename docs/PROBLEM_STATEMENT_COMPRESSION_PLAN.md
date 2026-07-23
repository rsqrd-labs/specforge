# Problem-Statement Compression Plan

**Goal (as stated):** let users bring a *large* problem statement — a pasted PRD,
a long requirements doc, an ingested file — and have the system **compress it down
to a budget without losing its meaning** before any model sees it, so generation
stays **reliable, cost-effective, and fast** no matter how big the input is.

This is a rewrite. The previous draft was built on a premise that is **false against
the current schema**, and it pointed at a tool that does not do what it claimed. Both
corrections are load-bearing, so they come first.

---

## 0. Two facts that reshape the problem

**Fact 1 — the problem statement is already hard-capped at 10,000 chars.**
[`models/workspace.py:27`](../backend/models/workspace.py#L27) carries a DB
`CheckConstraint("char_length(problem_statement) BETWEEN 50 AND 10000")`, mirrored by
Pydantic `max_length=10_000` in [`schemas/workspace.py:16`](../backend/schemas/workspace.py#L16)
(create), [`schemas/workspace.py:49`](../backend/schemas/workspace.py#L49) (update), and
[`schemas/template.py:33`](../backend/schemas/template.py#L33). At ~2,500 tokens against
200K–1M-token model windows ([`model_catalog.py`](../backend/services/llm/model_catalog.py#L152),
`max_context_tokens` 200K Anthropic / 1M Google), **compression of the current input
saves pennies and only adds latency.** The old draft's "hundreds of pages / 2,000
pages" scenario *cannot reach the column today.*

> Therefore compression is only worth building **as the other half of raising the cap.**
> This plan does both: it lifts the input ceiling so large problem statements are
> *accepted*, and compresses them so they stay cheap to *generate from*.

**Fact 2 — `summarize_stage_content` is extractive, not abstractive.**
[`stage_summary_service.py:37`](../backend/services/pipeline/stage_summary_service.py#L37)
is pure regex — it pulls headings, `FR/NFR/SEC` IDs, `METHOD /path` API lines, and
`Entity:`/`Table:` names into fixed buckets. It **does not paraphrase prose** and will
silently drop any requirement not written in those exact shapes. "Compress without
losing meaning" is precisely paraphrase, so it needs a **real abstractive LLM pass**
(cheap judge model). The extractive reducer is still useful — but as the deterministic
*fail-safe floor*, not the meaning-preserving path.

**Fact 3 (context) — every *other* spec-prompt input is already bounded**, so raising
the problem-statement cap is the only place the prompt can grow unboundedly:
`research_context` ≤ `brave_max_context_chars`
([`research_service.py:416`](../backend/services/research/research_service.py#L416)),
`clarification_qa` is system-generated, and upstream stage artifacts are reduced to
`_MAX_UPSTREAM_CHARS = 200_000` via `_section_aware_injection`
([`prompt_builder.py:24`](../backend/services/pipeline/prompt_builder.py#L24)). Compression
must slot into the prompt assembler the same way, beside that existing reducer.

---

## 1. The goal, stated as an invariant

Three guarantees, one invariant:

1. **Large inputs are accepted** (the cap is raised) — the product can ingest a real PRD.
2. **Generation stays reliable** — no generation fails because the input is large.
3. **Generation stays cheap and fast** — cost and latency have a fixed upper bound
   independent of input size.

> **Bounded-cost invariant.** Before any stage call, the problem statement is reduced to
> at most `C_MAX` tokens. Every stage/repair/regen call therefore receives ≤ `C_MAX`
> problem-statement tokens, the *compression step itself* reads at most a bounded number
> of chunks (so its own cost is bounded), and the number of calls per generation is a
> constant. Total generation cost has a **fixed upper bound regardless of input size**,
> and no call can blow the context window on input.

Two of the three multiplicands are already bounded; this plan adds the third and a bound
on the compressor itself:

| Factor | Bound | Source |
|--------|-------|--------|
| Problem-statement tokens per stage call | ≤ `C_MAX` | **new** — compression target |
| Compressor's own input | ≤ `N_CHUNKS × chunk_size` | **new** — capped map-reduce |
| Output per call | ≤ `OUTPUT_TOKEN_BUDGETS[op]` (24576 spec) | [`output_budget.py:48`](../backend/services/llm/output_budget.py#L48) (exists) |
| Calls per generation | 1 gen + ≤1 limit-repair + ≤1 critic regen + ≤1 escalation | `stage_manager.py` (exists) |

## 2. Step one — raise the cap (a real schema change, not a footnote)

Compression is pointless until the system *accepts* large input. This is the unglamorous
prerequisite, and it touches five places that all enforce the current 10K limit:

| Place | Change |
|-------|--------|
| [`models/workspace.py:27`](../backend/models/workspace.py#L27) CHECK constraint | Alembic migration to raise the upper bound `10000 → INPUT_HARD_CAP` (keep the `≥ 50` floor). |
| [`schemas/workspace.py:16`](../backend/schemas/workspace.py#L16) `WorkspaceCreate` | `max_length` → `INPUT_HARD_CAP`. |
| [`schemas/workspace.py:49`](../backend/schemas/workspace.py#L49) `WorkspaceUpdate` | same. |
| [`schemas/template.py:33`](../backend/schemas/template.py#L33) | same (or leave templates tight — open question §10). |
| [`problem_statement_gate.py:81`](../backend/services/security/problem_statement_gate.py#L81) | floor check unaffected; add the new ceiling here too so the gate is the single semantic authority. |

`INPUT_HARD_CAP` is the **outer DoS/storage ceiling** — the largest blob we will *store*
at all (e.g. 200K chars ≈ a long PRD). It is deliberately much larger than `C_MAX`
(what a model sees) and is the only place a true "too large" rejection can occur, far
above any realistic paste. Everything between `C_MAX` and `INPUT_HARD_CAP` is handled by
compression, not rejection.

Storage note: the `problem_statement` column is already `Text`; no type change. Existing
rows are untouched (all ≤ 10K, so all still valid under the relaxed constraint).

**Blast radius — audit what *assumes* ≤10K, not just what enforces it.** Raising a
long-standing limit ~20× has reach the prompt path never sees. Before Phase A, audit every
surface that renders, exports, scrubs, logs, or embeds the *full* statement — and decide
whether it gets the raw value or the compressed one:

- **PDF / public-share export** (WeasyPrint; `/p/:slug`) — a 200K-char statement in a
  rendered doc/PDF is a layout and render-cost problem; these should likely show the
  compressed value or a truncated preview.
- **Frontend rendering** of the full statement in the workspace/editor (DOM weight,
  scroll).
- **`_scrub(workspace.problem_statement)`** in
  [`storyboard_source.py:426`](../backend/services/pipeline/storyboard_source.py#L426) and
  any other O(n) per-request transform.
- **Logging / Sentry / hashing** paths that carry the statement (now 20× larger payloads).

These don't block the rewrite being valid, but they are the real implementation surprise
in "raise the cap" — see also §10.

## 3. The "certain limit" — when compression fires

Compression is **threshold-triggered**, exactly as you framed it ("if it exceeds a
certain limit"). The single most important design point: **the trigger is a deliberate
product budget set well *below* the model window, not the window-fit ceiling.** With
200K–1M-token windows, almost any legal input *fits* — so if we only compressed inputs
that fail to fit, compression would never run and the cost/speed goals would be unmet. A
smaller prompt is cheaper and faster *even when the big one is technically legal*; the win
comes entirely from **choosing to send less.** Four numbers, in token terms via
`estimate_tokens` ([`usage.py:59`](../backend/services/llm/usage.py#L59) — reuse it, **no
new tokenizer**):

- **`C_MAX`** — the **product budget / target** ("the certain limit"). A chosen constant
  set *well below* the window — e.g. **8K–16K tokens** — that trades fidelity for
  cost/speed. The compressed statement must end ≤ `C_MAX`. This is *not* window-derived;
  it is a product knob. (Tunable per provider, but its purpose is a small budget, not
  "as much as the window allows.")
- **`COMPRESSION_THRESHOLD`** — the trigger. If `est_tokens(problem) ≤ THRESHOLD`, do
  nothing — return the raw statement byte-for-byte (preserves provider prompt caching; the
  common case stays a no-op). Set `THRESHOLD ≈ C_MAX`. Pre-existing ≤10K-char inputs
  (~2.5K tokens) sit below an 8K budget and never trip it; the new large pastes do.
- **`WINDOW_FIT_CEILING`** — the *reliability* hard cap, window-derived (§5). `C_MAX` is
  always far below it, so a compressed prompt trivially fits. This number exists only to
  guarantee no call ever blows the window; it is **not** the trigger.
- **`INPUT_HARD_CAP`** — the storage ceiling from §2; beyond it, ingestion is rejected.

## 4. Design — meaning-preserving compression with a deterministic floor

A short ladder, applied lazily in the prompt assembler, cached by content hash. Climb
only as far as needed.

**Rung 0 — No-op.** `est_tokens(problem) ≤ THRESHOLD` ⇒ return unchanged. Byte-identical
to today. Regression-pinned.

**Rung 1 — Lossless structural cleanup (zero LLM cost, deterministic).** Collapse
whitespace/blank-line runs, de-duplicate repeated paragraphs/boilerplate (common in
pasted docs and email threads), strip signatures and page headers/footers. Pure Python,
O(n). On pasted material this alone often drops 15–30% and may return us under
`THRESHOLD` with **zero** quality loss and no model call.

**Rung 2 — Meaning-preserving abstractive compression (LLM, the heart of the feature).**
If still over budget, paraphrase to fit `C_MAX` *without losing meaning* — this is the
behavior you asked for, and it needs a real model pass (Fact 2):

- **Partition** the document with the `_split_by_h2` / keep-verbatim pattern already in
  `_section_aware_injection` ([`prompt_builder.py:87`](../backend/services/pipeline/prompt_builder.py#L87)).
- **Keep normative content verbatim, never paraphrased** — sentences with
  "must/shall/should", numbered/bulleted lists, acceptance criteria, tables, IDs. These
  *are* the requirements; paraphrase risks changing their meaning. They are preserved
  exactly and counted against the budget first.
- **Abstractively summarize only the narrative** (background, rationale, prose) with the
  cheap selector `JUDGE_MODELS[provider]` (Haiku / GPT-5.4 Mini / Flash — the same
  selector `spec_clarifier` already uses). Target = whatever budget remains after the
  verbatim normative block.
- **Bound the compressor's own cost** via **capped map-reduce**: split narrative into at
  most `N_CHUNKS` fixed-size chunks, summarize each, then summarize the summaries. The
  chunk cap is what keeps *the compression step itself* from scaling with input size — if
  narrative exceeds `N_CHUNKS × chunk_size`, the overflow is handed to Rung 3 rather than
  fed to the model. One bounded extra reduce pass, not an unbounded fan-out.
- **Result** = `[verbatim normative] + [abstractive narrative summary]`, guaranteed
  ≤ `C_MAX`. This is meaning-preserving where meaning is fuzzy (prose) and lossless where
  meaning is exact (requirements).

**Rung 3 — Deterministic extractive clamp (zero LLM cost — the fail-safe floor).** The
guarantee that the ladder *always terminates ≤ `C_MAX` for any input*, even if the model
is down, slow, or the input exceeds the map-reduce cap. Fill the budget normative-first,
then narrative, by truncation. This is where `summarize_stage_content`'s extractive
machinery is the right tool — it cannot lose normative IDs because it keeps them
verbatim. **Rung 2 always falls open to Rung 3** on timeout/error (mirrors the
`asyncio.timeout(5.0)`, fail-open contract of `critic.py` and `spec_clarifier.py`). The
floor never makes a generation fail.

### Invariants the design must hold

- **Never mutate the stored `problem_statement`.** Compress to a derived value cached in
  Redis, keyed `sha256(raw) + C_MAX_bucket + prompt_version`. The user's original always
  survives; spec regenerates, the storyboard, and the clarifier all reuse the cache — so
  the *one* abstractive pass is amortized across every call that re-reads the statement
  (this is where the cost win actually compounds).
- **Run after `sanitize_text` + `PromptGuard`**, never before — keep the trust-boundary
  ordering already enforced around `assert_valid_problem_statement` / `scan`
  ([`stage_manager.py:1721`](../backend/services/pipeline/stage_manager.py#L1721)).
- **Fail open** — any compressor error degrades to Rung 3 (or Rung 1) output, never to a
  failed generation.
- **Apply at all three consumers** — spec ([`prompts/spec.py:116`](../backend/prompts/spec.py#L116)),
  storyboard ([`prompts/storyboard.py:637`](../backend/prompts/storyboard.py#L637) via
  [`storyboard_source.py:426`](../backend/services/pipeline/storyboard_source.py#L426)),
  clarifier ([`spec_clarification.py:46`](../backend/prompts/spec_clarification.py#L46) via
  [`spec_clarifier.py:148`](../backend/services/pipeline/spec_clarifier.py#L148)) — through
  one shared helper, so the cached compressed value is reused, not recomputed per surface.
- **Clarifier interplay.** Compression is for *long*, not *vague*. Short-but-rambling
  input should still route to the clarification Q&A (which *adds* structure); only
  over-`THRESHOLD` input compresses. Mirrors the "ambiguity gated behind length" rule in
  `complexity_classifier.py`.
- **Surface to the user.** When Rung ≥ 2 fired, attach a non-blocking notice via the
  existing `AdvisoryFindingsPanel` channel: *"Your problem statement was condensed to fit
  the model; your original is preserved and used for reference."*

## 5. Budget math (reuse `estimate_tokens` + `model_entry`, no new tokenizer)

**Two distinct numbers — do not fuse them** (fusing them is what would make compression
never fire):

**(a) `WINDOW_FIT_CEILING` — the reliability cap.** The most input-tokens that can
physically be sent without blowing the window, computed against the *whole assembled spec
prompt* (`research_context` and `clarification_qa` stack with the statement):

```
window               = model_entry(provider, model).max_context_tokens   # 200K Anthropic … 1M Google
output_budget        = OUTPUT_TOKEN_BUDGETS["spec.generate"]             # 24576, reserved
safety               = 0.15 * window                                     # reasoning + caching slack
fixed                = est(system_prompt) + est(research_context) + est(clarification_qa)
WINDOW_FIT_CEILING   = window - output_budget - safety - fixed           # ≈ 130K tokens on Anthropic
```

**(b) `C_MAX` — the product budget (the actual compression target).** A *chosen* small
constant — e.g. **8K–16K tokens** — set deliberately far below `WINDOW_FIT_CEILING`. This
is the number compression compresses *to*, and `THRESHOLD ≈ C_MAX` is what it triggers
*on*. We pick it for cost/speed, not for "what fits."

```
C_MAX = min(PROMPT_BUDGET_TOKENS, WINDOW_FIT_CEILING)   # PROMPT_BUDGET_TOKENS ≈ 8K–16K, the product knob
```

The `min` is just a safety floor — on these large-window models `PROMPT_BUDGET_TOKENS`
always wins, so `C_MAX` is the small product budget. Compression is the bridge that lets a
raised `INPUT_HARD_CAP` (e.g. 50–200K *chars*) coexist with a small per-call budget:
**input accepted big, fed small.**

**Worked cost ceiling (spec stage).** Per generation: one bounded compression pass
(≤ `N_CHUNKS` cheap-model calls, amortized via cache across regens) **plus** the stage
calls, each seeing ≤ `C_MAX`: `C_MAX × (1 gen + ≤1 repair + ≤1 critic regen + ≤1
escalation) ≈ 4 × C_MAX` input tokens — a constant, whether the user pasted 2 pages or
200.

## 6. Integration seat

Lazily inside [`build_prompt`](../backend/services/pipeline/prompt_builder.py#L119),
beside `_section_aware_injection` — **not** a workspace-creation hook (creation-time
compression would be stale if budgets/models later change, and would fight the
"never mutate stored value" rule).

```python
# prompt_builder.build_prompt — replaces the raw assignment at line 130
raw    = workspace.problem_statement
budget = _problem_budget(provider, model, research_context, clarification_qa)
deps["problem_statement"] = await get_or_compress(raw, budget, redis, provider, model)
```

`get_or_compress` is a new module — `services/pipeline/problem_compressor.py` — called by
the spec branch and reused (via the cache) by the storyboard and clarifier paths.

## 7. The unavoidable tradeoff (stated honestly)

With a raised cap you can guarantee **accept-any-size + never-fail + bounded-cost**. You
**cannot also** guarantee perfect fidelity for *unbounded* input — a 200-page spec cannot
survive whole in a `C_MAX`-token prompt. Beyond `C_MAX` the behavior is **graceful
degradation**: normative content (requirements, ACs, IDs) is kept verbatim and first,
narrative is meaning-preservingly condensed (Rung 2) or, in the worst case, deterministically
clamped (Rung 3), and the advisory UI tells the user it happened. The original is always
retrievable. The one behavior the product goal forbids — rejecting a large paste outright
below `INPUT_HARD_CAP` — never happens.

## 8. Roadmap

**Phase A — Raise the cap + instrument (small behavior change).** Ship §2 (migration +
schema + gate) raising `INPUT_HARD_CAP`. Add Prometheus gauges for assembled-prompt token
size and problem-statement token size at generation time; read the real distribution from
the `llm_cost_events` ledger (same evidence-gated method as
`scripts/analyze_output_budgets.py`). *Exit: large inputs are accepted; data shows what
fraction of real inputs exceed `THRESHOLD` — i.e. how often compression will even run.*

> **Phase A — shipped (2026-06-22).** `INPUT_HARD_CAP = 50_000` chars
> (`PROBLEM_STATEMENT_MAX_CHARS` in `services/security/problem_statement_gate.py`, the
> single semantic authority; mirrored by the Pydantic create/update schemas and DB CHECK
> via migration `0026`). Templates deliberately stay tight at 10K (`schemas/template.py`).
> The gate now rejects only above the ceiling (`problem_statement_too_long`), on raw
> length, before the content checks. **Instruments are Histograms, not gauges** — a gauge
> holds only the last value and cannot express a distribution; precedent is
> `BRAVE_CONTEXT_CHARS`. Two were added (`services/observability.py`):
> `thought2build_problem_statement_tokens{provider}` (emitted in the spec branch *before* the
> generation-cache check, so cache hits count) and
> `thought2build_assembled_prompt_tokens{provider,stage_type}` (emitted on cache-miss after
> `build_prompt`); both reuse `estimate_tokens` (no new tokenizer). The analysis script is
> `scripts/analyze_problem_statement_sizes.py`: problem-statement sizes come from
> `workspaces` (the ledger lacks the statement-only size; `octet_length` matches
> `estimate_tokens`' utf-8 basis), assembled-prompt sizes from the ledger
> (`input_token_percentiles`); `--threshold-tokens` is a CLI knob (default 8000) since
> `C_MAX` is still §10-open. Day-one reading will be ~0% over threshold — correct, not
> broken: every stored statement is ≤10K chars today.
>
> **Blast-radius audit (§2) — audited, deliberately *not fixed* in Phase A.** The
> PDF/public-share export, full-statement frontend rendering, `_scrub` in
> `storyboard_source.py`, and the logging/Sentry paths now all *may* see up to 50K chars.
> None hard-fails at 50K (≪ the 1MB request-body limit), and the right fix is to feed them
> the *compressed* value, which does not exist until Phase B/C. They are left as-is; the
> frontend `maxLength={10000}` is also left for the Phase-D UI work. Tracked here so the
> deferral is explicit, not an oversight.

**Phase B — Rungs 0/1/3 + the deterministic floor (delivers never-fail + bounded-cost).**
Pure-Python, zero LLM cost, lazy in `build_prompt` behind a default-off flag
(`problem_statement_compression`). Unit-tested + an offline golden corpus alongside
`asdd_route_golden.json`. *Exit: for input of arbitrary size up to `INPUT_HARD_CAP`, the
assembled prompt is provably ≤ window; Rung-0 output is byte-identical for under-threshold
input (regression pin).* **This phase already satisfies reliability + cost; it just isn't
yet "meaning-preserving" for prose.**

> **Phase B — shipped (2026-06-23).** New module
> `services/pipeline/problem_compressor.py` implements the pure-Python ladder —
> Rung 0 (no-op, byte-identical), Rung 1 (lossless structural cleanup), Rung 3
> (deterministic normative-first clamp). Rung 2 is Phase C, so the ladder skips
> Rung 1 → Rung 3. The public surface is `get_or_compress(raw, budget, redis,
> provider, model)` (cached, fail-open) over the pure `compress_problem_statement`;
> `problem_budget(...)` computes `min(C_MAX, WINDOW_FIT_CEILING)`. Wired **lazily
> behind the default-off `problem_statement_compression` flag** at all three
> consumers through the one shared helper: `build_prompt` (covering spec **and**
> plan/harness/tasks, since `problem_statement` is in `deps` for every stage), the
> clarifier (`spec_clarifier.py` — still runs on short input; only over-budget input
> condenses), and the storyboard (`storyboard_source.py`, after `_scrub`). `C_MAX`
> ships as one constant, `problem_statement_budget_tokens = 8000` (config). The
> cache key is `psc:{COMPRESSION_VERSION}:{budget}:{sha256(raw)}` (7-day TTL; the raw
> statement is immutable). **Three guarantees are enforced by construction and pinned
> by tests:** (1) Rung 0 / flag-off output is byte-identical for under-budget input;
> (2) the ladder always terminates `est_tokens ≤ budget` for any input up to
> `INPUT_HARD_CAP` (the fail-open path *also* truncates — never raw); (3) Rung 1 never
> drops a normative line and never touches fenced code/tables. Telemetry:
> `thought2build_problem_compression_rung_total{rung}` (1/3/error; Rung-0 no-ops are not
> counted). Tests: `tests/test_problem_compressor.py` (unit), the offline golden
> corpus `docs/evals/golden_prompts/problem_compression_golden.json` consumed by
> `tests/test_problem_compression_golden.py`, and flag-on/off integration assertions
> in `tests/test_prompt_builder.py`. The blast-radius surfaces deferred in Phase A
> (PDF/share export, frontend rendering) are *unchanged* — they still read the raw
> stored value; feeding them the compressed value is Phase D UI work.

**Phase C — Rung 2 (meaning-preserving abstractive pass).** Reuse `JUDGE_MODELS`, capped
map-reduce, fail-open to Rung 3, length-gated against the clarifier. Quality gate: a
**normative-retention eval** — count distinct normative statements (must/shall/numbered
items, FR/NFR/SEC IDs) before vs. after, and an LLM-judge semantic-equivalence score on
the narrative — promote only at ~zero loss of normative content, mirroring the live gate
in `docs/evals/ROUTE_PROMOTION.md`.

> **Phase C — shipped (2026-06-23).** Rung 2 lives in `problem_compressor.py` behind a
> **second** default-off flag, `problem_statement_abstractive` — a *sub-gate* of the
> Phase-B master `problem_statement_compression` (no effect unless the master is also on).
> This deliberately splits the plan's singular "flip the flag" into two: the master
> delivers Phase-B's zero-cost reliability; the sub-gate enables the *paid, lossy* LLM
> pass, promoted independently via the gate below — mirroring the
> `core_cheap_primary`/`core_complexity_routing` two-flag precedent (a paid adaptive layer
> must not be force-enabled by a reliability toggle). The pure ladder
> (`compress_problem_statement`) is **unchanged** and stays the deterministic source of
> truth + Rung-3 floor; the new async `_compress` orchestrator runs the pure ladder first
> and only attempts Rung 2 when it would otherwise reach Rung 3 *and* the sub-gate is on,
> falling back to the already-computed floor if it declines. **Design:** partition the
> cleaned doc into normative vs. narrative blocks (the Phase-B `_split_blocks` /
> `_is_normative_block`); keep normative **verbatim and first** (so it is never sent to
> the model and **normative retention is 100% by construction**); condense only narrative
> via a capped map-reduce over `call_judge_model` (cheap `JUDGE_MODELS[provider]`, prompt
> held in code like the critic, content wrapped via `wrap_untrusted_content`); assemble
> `[normative]+[summary]` and hard-truncate (only the narrative tail can be trimmed). The
> map fans out in parallel (`asyncio.gather`) with a single reduce pass only if needed
> (≤ `N_CHUNKS+1` calls), all under an overall `asyncio.timeout`
> (`problem_statement_abstractive_timeout_seconds`, default 8s). **Fail-open** to Rung 3
> on no narrative, no leftover budget, over-cap narrative, or any judge error/timeout —
> Rung 2 never raises, and `get_or_compress`'s outer fallback was upgraded from a *prefix*
> truncate of the raw input to a `_rung3_clamp` so a fail-open path can never drop trailing
> requirements. Cost is attributed (`product_surface` per consumer) and amortised by the
> Redis cache, whose key now carries the mode (`a1`/`a0`) so flipping the sub-gate never
> cross-serves a deterministic vs. abstractive value; a *degraded* result (abstractive
> requested, fell to the floor) is cached only 5 min so a transient judge outage
> self-heals. Telemetry: `thought2build_problem_compression_rung_total{rung="2"}`. Gate &
> tests: the deterministic normative-retention invariant is the automated CI gate
> (`scripts/run_problem_compression_eval.py` dry-run over
> `golden_prompts/problem_compression_rung2_golden.json`, pinned by
> `tests/test_problem_compressor.py`); the narrative semantic-equivalence judge score is
> the manual `--live` step. Full procedure in `docs/evals/PROBLEM_COMPRESSION_PROMOTION.md`.

**Phase D — Enable + UI surfacing.** Flip the flag after the gate; ship the advisory
"condensed" notice via `AdvisoryFindingsPanel`. *Exit: large-input workspaces generate
within the cost ceiling; zero increase in spec quality-gate failures or user-reported
missing requirements.*

> **Phase D — shipped (2026-06-23).** Two halves, gated independently.
> **(1) Enable.** The Phase-B master `problem_statement_compression` is now **enabled by
> default** (`config.py`): the deterministic ladder is zero-LLM-cost and bounded, so the
> common (under-budget) case stays a byte-identical no-op and only genuinely over-budget
> pastes condense (Rung 1/3). The **paid, lossy** abstractive sub-gate
> `problem_statement_abstractive` stays **default-off** — its promotion strictly requires
> the live normative-retention + human semantic-equivalence read in
> `docs/evals/PROBLEM_COMPRESSION_PROMOTION.md`, which is a manual operational step (real
> provider calls), not a code change. Per the Phase-D cache caveat below, the master flip
> does not invalidate previously-cached generations; pair the deploy with a
> generation-cache flush or accept the ≤24h window.
> **(2) UI surfacing.** When a stage's problem statement was *lossily* condensed (Rung
> 2 = abstractive summary, Rung 3 = deterministic clamp), the user is told via a
> **non-blocking advisory notice** on the generated stage, reusing the issue-#34
> `AdvisoryFindingsPanel`. `build_prompt` now returns the per-stage compression rung
> (`prompt_builder.py`), recovered purely and **cache-hit-safe** by
> `classify_compression_rung` (replays the pure ladder's decision points against the
> returned text against the exact budget used — never a second compression, correct on
> the cache hits that 3 of the 4 stages take). `StageManager._execute_generation_pipeline`
> threads the rung to the success path and, for Rung 2/3, appends a
> `ProblemStatementCondensed` finding to the **same advisory bucket** as any critic
> findings (they coexist; `_mark_quality_gate_advisory` now takes serialised dicts).
> The notice is informational: it states that every requirement ID was kept verbatim,
> never blocks finalisation, never refunds, and the panel **suppresses the misleading
> "Regenerate to address" action** when the only findings are informational notices
> (`isInformationalFinding` in `qualityGate.ts`; copy switches "suggestion" → "note").
> The rung is genuinely per-stage (`problem_budget` varies by `stage_type`). Tests:
> `classify_compression_rung` unit + ladder-parity (`test_problem_compressor.py`),
> `build_prompt` rung reporting (`test_prompt_builder.py`), the advisory merge /
> coexistence / clear-when-unchanged paths (`test_critic.py`), and the panel
> informational-only suppression + label (`AdvisoryFindingsPanel.test.tsx`,
> `qualityGate.test.ts`).

> **Phase-D enable caveat (cache coherence).** The generation cache key in
> `stage_manager.py` hashes the *raw* `problem_statement`; compression runs *after*
> that check, inside `build_prompt`. While the flag is stable this is coherent (raw
> → deterministic compressed → output). But flipping `problem_statement_compression`
> on/off — or bumping `COMPRESSION_VERSION` — does **not** invalidate
> previously-cached generations, so a stale (uncompressed-input) output can linger up
> to the 24h generation-cache TTL. Harmless and self-healing, but the flip should
> either accept the ≤24h window or be paired with a generation-cache flush. (Phase B
> deliberately does **not** add the compressed value to the generation cache key.)

## 9. Success metrics

| Metric | Target |
|--------|--------|
| Max accepted problem-statement size | `INPUT_HARD_CAP` (raised from 10K) |
| Max assembled spec-prompt tokens, any accepted input | ≤ window − output_budget − safety (hard ceiling) |
| Max billed input tokens per spec generation | ≤ `~4 × C_MAX` (constant, size-independent) |
| Generation failures attributable to input size | **0** |
| Rung-0 byte-identical output for under-threshold input | 100% (regression pin) |
| Normative-content retention (Rung 2) | ~99–100% |
| Narrative semantic-equivalence (Rung 2 judge score) | above promotion gate |
| Added latency (Rungs 0/1/3 / Rung 2) | ~0 / < 3s p95, amortized to ~0 across regens via cache |
| Compression LLM cost, common case (under threshold) | $0 |

## 10. Open questions

- **`INPUT_HARD_CAP` value.** How big a paste do we actually want to *store*? 50K? 200K
  chars? Drives the migration and the DoS surface. (Lean: start 50K, raise on demand.)
- **`C_MAX` / `PROMPT_BUDGET_TOKENS` value.** What small budget actually balances
  cost/speed against fidelity — 8K? 16K? Per-provider, or one constant for golden-corpus
  determinism? (Lean: one constant, bucket the cache key for stability. This is a product
  knob, *not* window-derived — see §3/§5.)
- **Templates.** Do starter templates need the raised cap, or stay tight at 10K?
  ([`schemas/template.py:33`](../backend/schemas/template.py#L33).)
- **Storyboard budget.** Storyboard has its own output budget and escalation path
  (`storyboard_service.py`); same `C_MAX` or tighter?
- **Clarifier length gate threshold.** Exactly where does "vague → clarify" hand off to
  "long → compress"? Tune against Phase A data.
- **Is Rung 2 worth it?** If Phase A shows real inputs rarely exceed `THRESHOLD` *after*
  Rung 1, Phases A–B + the deterministic floor may be the whole product, and the
  abstractive pass (added LLM cost + lossiness on a source-of-truth doc) can wait.
