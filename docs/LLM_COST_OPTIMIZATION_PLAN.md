# LLM Cost Optimization Plan (Issue #26)

Production-ready program to reduce LLM API spend **without** weakening intelligence,
artifact completeness, traceability, security validators, or user trust.

This plan is grounded in the current code, not the issue text. Several of the issue's
stated cost drivers are already mitigated; others are genuinely unbuilt. The phasing
below removes waste and instruments first, then introduces cheaper routing only behind
validators and telemetry.

> **Current baseline (updated after commit `1ccd4ab`).** Core generation (the four
> streamed stages + full regenerate) now routes **cheapest-tier-first** per provider —
> Claude Haiku 4.5 / GPT-5.4 Mini / Gemini 3.5 Flash — via `CORE_GENERATION_TIER_POLICY`
> in `stage_manager.py`, escalating to the mid tier (Sonnet 4.6 / GPT-5.4) **only on a
> runtime/provider failure**. This shipped the *aggressive* form of the cost saving
> **ahead of its safety rails**: there is (a) **no complexity-aware starting tier** — every
> request starts cheapest regardless of difficulty; (b) **no quality-gate-triggered
> escalation** — a critic/validator failure regenerates on the *same* cheap model
> (`route=route`) and then refunds+fails rather than escalating to a stronger tier; and
> (c) **no golden-corpus validation** that the cheap primary holds artifact quality.
> **Closing (a)–(c) is now the most important near-term work and is folded into Phase 5.**

---

## 1. Current state vs. issue assumptions

| # | Issue proposal / premise | Reality in code | Classification |
|---|--------------------------|-----------------|----------------|
| premise | Core SPEC/PLAN/HARNESS/TASKS route **strong-first** | **No longer true.** Core gen routes **cheapest-tier-first** (Haiku 4.5 / GPT-5.4 Mini / Flash) via `CORE_GENERATION_TIER_POLICY`, escalating to mid (Sonnet 4.6 / GPT-5.4) only on a runtime/provider failure (commit `1ccd4ab`) | **Shipped aggressively — safety rails missing (Phase 5)** |
| extra | Use the **cheap/fast latest-gen model** per provider | Done *deterministically*: Haiku 4.5 / GPT-5.4 Mini are the core-gen defaults (output ceilings raised 4096→32768, `reasoning_effort` bumped low→medium); Sonnet/GPT-5.4 demoted to escalation; Google stays on Flash (`model_catalog.py`) | **Shipped — adaptive/complexity-aware version is Phase 5** |
| premise | Full **regenerate** routes strong-first; refine.section/full strong | `regenerate.full` now follows the same cheap-primary policy as a fresh stage. `refine.section` still mid→strong; `refine.focused` still mini→small (`_route_for_refine`) | **regenerate shipped cheap; refine unchanged** |
| 1 | Add an LLM **cost ledger** (per-call, rolled up per workspace/stage/storyboard) | Only Prometheus counters + a `structlog` line + Langfuse generation (`observability.py:873`, `instrumented_adapter.py`). No DB table; no per-workspace/stage rollup | **Partially done (telemetry only) — needs DB ledger** |
| 1 | Capture real input/cached/output/reasoning tokens | Adapters **do** capture `last_completion.usage` from terminal usage chunks (all 3 providers), but `InstrumentedAdapter._cost_metadata` ignores it and calls `estimated_usage_from_text` → `cached_input_tokens` is always `None`, costs are tokenizer estimates | **Bug/gap — wiring fix, not adapter surgery** |
| 2 | Provider prompt/context **caching** (cache_control / prompt_cache_key / cached content) | None. Adapter interface is plain `(system, user, max_tokens)` — no way to express cache breakpoints. `model_catalog` already prices `cached_input_cost_per_million` + flags `supports_prompt_cache_accounting`, so accounting is ready, wiring is absent | **Greenfield (needs adapter interface change)** |
| 2 | (not the same thing) SpecForge output cache | `build_generation_cache_key` + Redis `get_cached_generation` already skips identical regens (`cost_cache.py`, wired in `stage_manager.py:1335,2127`) | **Already done — keep, distinct from provider caching** |
| 3 | **Batch/deferred** for non-interactive judge/eval calls | `batch_executor.complete_background_llm` sets a `batch` **boolean label** but calls `instrumented.complete()` — no Anthropic Message Batches / OpenAI Batch endpoint anywhere. The 50% batch discount is unclaimed | **Greenfield (cosmetic flag today)** |
| 4 | Storyboard **mid-first** w/ strong escalation | Storyboard uses `source.provider, source.model` — the persisted workspace (usually strong) model; does **not** go through `resolve_llm_route` (`storyboard_service.py:735,748`). Schema validation + 2-round repair already exist | **Valid — highest ROI-per-risk** |
| 5 | **Adaptive routing** (complexity classifier) behind a flag, golden-corpus gated | Routing is static per-operation (`routing.py`, `quality_gates.py`). Golden harness exists: `scripts/run_llm_route_eval.py`, `docs/evals/golden_prompts/asdd_route_golden.json` (8 cases), `ROUTE_PROMOTION.md` | **Greenfield policy; corpus needs expansion (8 → simple/medium/complex)** |
| 6 | Right-size **output budgets** w/ percentiles + repair safety | Uniform 24576 for all core ops (`output_budget.py`); `provider_stopped_by_limit` repair already doubles into ceiling | **Blocked on phase 0 real-usage data** |
| 7 | Reduce prompt size via **deterministic extraction** (not LLM summary) | Prompt builder currently injects full upstream artifacts (`prompt_builder.py`); no row/ID-level extraction | **Valid — medium effort** |
| 7b | Slim the **static prompt templates** in `backend/prompts/` | Templates are large and verbose: spec ~3.9K, plan ~6.9K, harness ~4.5K, tasks ~5.0K, storyboard ~8.2K est. tokens. Every core-gen/refine call re-sends a **~3.3K-token shared prefix** (`ASDD_METHODOLOGY_OVERVIEW` + `SECURITY_AND_PRIVACY_RULES` + `PROFESSIONAL_OUTPUT_RULES`) byte-identical across all four stages (`base.py:20-247`). Real redundancy/belt-and-braces phrasing exists | **Valid — must be caching-safe (new)** |
| 8 | Surface cheaper **narrow workflows** (focused refine, section rewrite, coverage-gap) | Narrow ops exist and are cheap (`refine.focused` 768 budget); discoverability/defaulting is a product surface, not a backend gap | **Mostly product/UX** |

**Net:** the safe, high-value path is **phase 0 (real accounting) → storyboard mid-first → provider caching → real batch → budget right-sizing → adaptive routing**. The core-gen downgrade — the scary part — has *already shipped in its aggressive form* (always-cheapest, escalate only on infra failure, unvalidated). So the priorities flip slightly: Phase 0 (measurement) and Phase 5 (the complexity classifier + quality-gate escalation + golden-corpus validation that retrofit the safety rails onto what's already live) are the two highest-value items; caching, batch, and budget work are pure additive savings on top.

---

## 2. Guardrails (apply to every phase)

- **No quality gate, security validator, or traceability check is removed or weakened to save cost.** Artifact validator, critic, output validator, prompt-injection guard, tech-safety, task-traceability all stay.
- **Critic stays in the interactive path** — it gates persistence and funds a regenerate; it is *not* batchable.
- **No grey-market proxy / unofficial provider.** Official provider SDKs only.
- Every cheaper route ships **behind a flag** with automatic strong escalation on validator failure, incomplete output, quality-gate failure, or low eval score.
- Every phase lands with **telemetry before behavior** — we never change routing we can't measure.

---

## 3. Phased plan

### Phase 0 — Real cost accounting + DB ledger *(foundation; everything depends on it)*

**Why first:** budget right-sizing needs real p50/p90/p95 output tokens; cache validation needs real `cached_input_tokens`; routing comparison needs real per-call cost. Today all of these are tokenizer estimates.

1. **Thread provider-reported usage into the cost event.** In `InstrumentedAdapter._cost_metadata`, prefer `normalize_provider_usage(provider, self.last_completion.usage)` over `estimated_usage_from_text`, falling back to the estimate only when `last_completion.usage` is `None`. Keep `usage_estimation_method` honest (`provider_reported` vs `tokenizer_estimated`). This alone unlocks cached-token and reasoning-token visibility that already flows from the adapters.
2. **Add a `llm_cost_events` table** (new model + Alembic migration): one row per model call with the issue's full schema — operation, provider, model, tier, input/cached_input/output/reasoning tokens, latency, finish_reason, retry/repair count, cache_hit, batch, cross_provider_fallback, quality_outcome, credit_reason/product_surface, and **foreign keys to workspace_id + stage_id/storyboard_id/increment_id** for rollups. Write from `record_llm_cost_event` (async, fire-and-forget, never blocks generation — same defensive posture the wrapper already uses).
3. **Rollup views/queries:** cost per successful workspace, stage, storyboard, increment, PR check. Expose via an admin/read endpoint and a Grafana/Metabase-friendly view. Keep the existing Prometheus counters for real-time alerting.
4. **Backfill threading of `quality_outcome`** from the stage manager (pass/fail of validator + critic) and `retry/repair count` (already tracked in the generation loop) into the event.

**Acceptance:** ledger captures all interactive + background calls with provider-reported tokens; dashboard shows cost by operation/provider/model/surface/outcome. (Issue AC 1, 2.)
**Risk:** low — additive. **Effort:** M.

---

### Phase 1 — Storyboard mid-first with strong escalation *(highest ROI per unit risk; pull early)*

**Why early:** structured + validator-backed + repair-looped already, and it currently defaults to the strong workspace model — the single clearest waste.

1. Route storyboard through `resolve_llm_route(operation="storyboard.generate", requested_tier="mid", fallback_tier="strong")` instead of `source.model`. Register the operation in `cost_registry`/`model_catalog` `recommended_operations` and a `ROUTE_QUALITY_GATES` entry.
2. **Preserve** strict `StoryboardPayload` schema validation, grounding checks, and the 2-round repair loop verbatim.
3. **Escalate to strong** on: schema validation failure, grounding failure, payload validation failure, or low quality signal — *before* surfacing an error to the user. Count escalations (`storyboard_strong_escalations_total`).
4. Validate on the golden corpus (schema + grounding pass rate) old-vs-new before flipping the default; ship behind `storyboard_mid_first` flag.

**Acceptance:** storyboard no longer defaults to persisted strong model without an escalation reason (Issue AC 5). **Risk:** low-med (validator-backed). **Effort:** M.

---

### Phase 2 — Provider prompt/context caching

**Architectural enabler first:** evolve `BaseLLMAdapter.stream/complete` to accept structured prompt blocks with cache hints (e.g. an ordered list of `PromptBlock(text, cacheable: bool)` plus an optional stable `cache_key`) instead of a bare `system: str`. Keep a back-compat shim so existing call sites compile during migration.

Then per provider (pricing already in `model_catalog`):
- **Anthropic:** `cache_control: {"type":"ephemeral"}` on the stable system+contract block and on repeated upstream-artifact context.
- **OpenAI:** stable-prefix ordering + a deterministic `prompt_cache_key` per (stage, operation, contract version).
- **Gemini:** explicit context caching for large repeated workspace/storyboard source packages where the break-even justifies it.

**Target the call-sites that re-send a stable prefix *within the provider cache TTL (minutes)*** — that's where caching actually pays:
- chunked generation (every chunk re-sends system+contract+prior context — CLAUDE.md confirms all chunks run),
- repair / limit-stop retries,
- critic regenerate,
- storyboard multi-round repair.

Cross-*stage* prompts mostly **don't** share a prefix (spec contract ≠ plan contract), so don't over-claim "cache all stable prompts." Validate with the phase-0 `cached_input_tokens` metric: cache hit ratio per call-site must rise and cost fall, with zero artifact-quality regression.

**Acceptance:** provider caching implemented where support exists (Issue AC 3). **Risk:** med (interface change). **Effort:** L.

---

### Phase 2b — Slim the static prompt templates *(caching-safe; co-designed with Phase 2)*

**The opportunity.** The templates in `backend/prompts/` are large and verbose (spec ~3.9K, plan ~6.9K, harness ~4.5K, tasks ~5.0K, storyboard ~8.2K est. tokens). Crucially, every core-gen/refine call re-sends a **~3.3K-token prefix that is byte-identical across all four stages** — `ASDD_METHODOLOGY_OVERVIEW` + `SECURITY_AND_PRIVACY_RULES` + `PROFESSIONAL_OUTPUT_RULES` (`base.py:20-247`). There is genuine redundancy: overlapping "depth mandate" / "instructions" / "before returning verify" blocks, repeated traceability/granularity restatements, and defensive double-phrasing. We can cut tokens **without removing detail** by deduplicating and tightening prose — not by deleting requirements, sections, IDs, or the security rules.

**Why this is its own phase, not a quick edit:** done naively it *breaks* provider caching. The rules below are mandatory.

**Caching-safety rules (non-negotiable):**
1. **Trim to a fixed constant, never per-request dynamic assembly.** Producing one shorter, static version of each block is caching-neutral (the prefix is still identical call-to-call). Conditionally including/excluding sections per request (e.g. "drop the security block when the problem doesn't mention auth") *shatters* the shared prefix → cache miss on every variant → net cost almost certainly **worse**. Do not make the cacheable prefix input-dependent.
2. **Keep the shared base blocks first and byte-identical across stages.** The ~3.3K base prefix is the largest cross-stage cache-reuse opportunity. Trim each base block once, keep all four stages importing the *same* constant in the *same* order (ASDD → security → professional → per-stage role), and place the Phase-2 `cache_control` breakpoint after the largest stable span.
3. **All variable content stays after the cache breakpoint / in the user turn.** The wrapped problem statement, clarifications, and upstream artifacts already live in the user prompt (`build_user_prompt`) — keep it that way so they never invalidate the cached system prefix.
4. **Bump the prompt version on every edit and expect one clean invalidation.** `STAGE_PROMPT_VERSIONS` / `ASDD_PROMPT_VERSION` (`base.py:13`) already version prompts and that version is part of the output-cache key. A template edit invalidates the provider cache once (plus a one-time cache-*write* cost), then restabilizes. Batch edits; don't trim continuously.
5. **Keep `_enforce_security_rules` in lockstep.** That gate (`base.py:252`) does an exact-substring check for the canonical `SECURITY_AND_PRIVACY_RULES`. If the trimmed security block isn't updated as the same canonical constant, the gate double-appends it — bloating the prompt *and* breaking the byte-identical prefix. Update the constant atomically with the trim.
6. **Pin the cacheable prefix to repo constants.** Langfuse remote overrides (`load_prompt`) can change the prefix unpredictably. For the cacheable span, prefer the in-repo fallback constants, or treat any remote prompt change as a version bump so the cache invalidation is deliberate, not silent.

**Approach:**
- Measure tokens per template/block before and after (cheap, deterministic).
- Deduplicate overlapping guidance across `base.py` and the per-stage files; tighten verbose phrasing; keep every section heading, every ID scheme, every "Before returning, verify" check, and the full security/privacy rules intact (these are quality and validator contracts — `artifact_validator` checks for headings).
- Co-design with Phase 2: the trim reduces both the uncached first-call cost *and* the per-write cache-creation cost, so sequence it immediately before or together with caching.

**Validation:** token reduction per template (target a meaningful cut on the shared prefix first — it's the highest-multiplier since it's in every call); golden-corpus old-vs-new quality comparison through the existing `run_llm_route_eval.py` / `ROUTE_PROMOTION.md` gates (no eval/critic/validator/security regression); and confirm via the Phase-0 `cached_input_tokens` metric that the cache **hit ratio does not drop** after the edit restabilizes.

**Acceptance:** static prompts are smaller with no quality/validator/security regression and no degradation in provider cache hit ratio. **Risk:** med (quality + caching interaction). **Effort:** M.

---

### Phase 3 — Real batch/deferred for non-interactive judge/eval work

Replace the cosmetic `batch` flag with actual provider Batch submission for **non-user-blocking** calls only:
- eval scoring (`eval.score`), PR evaluator judge calls, optional secondary quality checks, non-urgent summaries/analytics.
- **Never** batch: interactive streaming generation, **and not the critic** (it gates persistence inline).

Run on the existing arq worker with the established idempotent/checkpointed/dead-letter pattern (batch jobs are inherently async; poll for completion, dead-letter to a `llm:batch:deadletter` lane). Capture the 50% batch discount in the phase-0 ledger (`batch=true` rows should show ~half cost).

**Acceptance:** non-interactive judge/eval has a batch path where feasible (Issue AC 4). **Risk:** med. **Effort:** L.

---

### Phase 4 — Right-size output budgets (evidence-backed)

Using ≥2–4 weeks of phase-0 ledger data:
1. Compute p50/p90/p95 **real** output tokens (incl. reasoning) per operation × provider.
2. Lower the uniform 24576 budget **only** where p95 + reasoning headroom supports it (likely harness/tasks/refine first). Keep per-operation granularity.
3. Preserve `provider_stopped_by_limit` detection + the doubling repair, completion sentinels, and `validate_artifact_completeness`. A too-tight budget self-heals via repair; we monitor `pipeline_*` repair counters for regressions.

**Acceptance:** budget changes backed by observed distributions + validator-backed repair (Issue AC 7). **Risk:** med (mitigated by repair). **Effort:** S-M.

---

### Phase 5 — Retrofit safety rails onto the shipped cheap-primary routing *(riskiest; highest near-term priority)*

The aggressive cost saving is **already live** (always-cheapest core gen, escalate only on infra failure, unvalidated). Phase 5 is no longer "go cheaper" — it is **making what already shipped safe**. Three workstreams, each independently shippable:

**5.1 — Quality-gate-triggered tier escalation *(do this first — closes the biggest live risk).***
Today `_runtime_fallback_route` escalates to mid only on a runtime/provider *failure*; a critic/validator *quality* failure regenerates on the **same** cheap model (`route=route`) then refunds+fails. Add: when the artifact-completeness validator or critic fails on the cheap primary, **escalate the (one funded) regenerate to the mid tier** instead of repeating on the cheap model. This is the single change that turns the live "always cheapest, hope it passes" into "cheapest, but a quality miss is caught by a stronger model." Count it (`pipeline_quality_escalations_total`).

**5.2 — Deterministic complexity classifier for the *starting* tier (no LLM call).** *(Shipped — flag-gated `core_complexity_routing`, default off.)* `services/llm/complexity_classifier.py` scores each request from non-LLM signals and raises the starting tier (a floor, never a ceiling) via `_apply_complexity_floor` in `stage_manager.py`. Counter: `pipeline_complexity_tier_floors_total`.
Signals: problem length, ambiguity markers, security/regulatory keywords, number of source artifacts/upstream refs, prior failed generations, quality-gate history, template type. Policy (note the baseline inverted — we now start cheap and decide when to start *higher*):
- **High complexity →** start at mid (or strong for the hardest), skipping the cheap primary that would predictably fail its gates and waste a regenerate.
- **Normal/low →** keep the current cheap-first behavior.
- **HARNESS/TASKS:** most likely to need a higher floor; tune from Phase-0 quality-outcome data per stage.
- **Increment generation:** unchanged — stays on mid (`_INCREMENT_TIERS = ("mid", None)`) until tests prove a cheaper tier preserves task refs + traceability.

**5.3 — Golden-corpus validation (the gate that should have preceded the swap).** *(Shipped — corpus expanded, classifier gated in the eval, flag in place.)* `asdd_route_golden.json` now spans simple/high/critical bands (each case declares `complexity.expected_*`); `scripts/run_llm_route_eval.py` asserts the classifier deterministically and reports per-case tier floors. The whole cheap-primary policy is behind `core_cheap_primary` (default on) — flip it false to revert to mid-first in one toggle. **Note (honest scope):** the dry run's simulated output is tier-identical, so it *cannot* produce the cheap-vs-mid **quality** comparison — that stays the manual live gate over the expanded corpus (`ROUTE_PROMOTION.md`), which must pass before `core_complexity_routing` is defaulted on. Storyboard keeps its own schema/grounding gate (Phase 1) rather than a fabricated route-eval case.

**Acceptance:** quality failures escalate tier (not just infra failures); a deterministic classifier sets the starting tier; the cheap-primary policy is flag-guarded and validated old-vs-new on the expanded golden corpus with no validator/quality/security/traceability regression (Issue AC 6). **Risk:** high. **Effort:** L (5.1 is S–M and should ship soon).

#### 5b — Latest-gen catalog hygiene & cross-provider cost (what's *left* after the swap) *(Shipped — levers 1+2; lever 3 deferred.)*

The deterministic cheap-tier floor is now shipped (Haiku 4.5 / GPT-5.4 Mini are core-gen defaults). Levers:

1. **Normalize the per-provider cheap-tier floor.** *(Done.)* The asymmetric ladder (Anthropic mid→small, OpenAI mid→mini, Google mid-floor) is now a single declarative `CORE_GENERATION_TIER_LADDER` in `model_catalog.py` — the source of truth. `stage_manager.CORE_GENERATION_TIER_POLICY` is **derived** from it (`core_generation_tier_policy()` → `(ladder[0], ladder[1])`), not hand-maintained. The per-provider viability decision ("how far below mid is safe") is documented in the ladder itself: Google floors at `mid` because Flash-Lite is not a core-gen default. **Behavior-preserving:** a pinned test asserts the derived policy is byte-identical to what Phase 5 shipped — no route changed.
2. **"Latest-generation only" catalog hygiene.** *(Done.)* `validate_core_generation_ladder()` (run inside `validate_model_catalog()`, CI-enforced) asserts each ladder is strictly capability-increasing and each primary tier resolves to exactly one active, non-deprecated core-gen default. The written quarterly/on-release periodic-review process — deprecate-don't-delete, eval-before-promote, one-place swap — lives in [`docs/evals/CATALOG_HYGIENE.md`](evals/CATALOG_HYGIENE.md).
3. **(Optional, sensitive) cheapest-provider-first for platform-key generations.** *(Deferred — intentionally not built.)* Routing platform-key (non-BYO) gen to the cheapest-mid provider (Gemini 3.5 Flash) changes *which provider* a user's output comes from, so it ships only behind golden-corpus quality parity **and** a product decision. No flag is added (dead config that gates nothing is worse than a deferral note). `allow_cross_provider` stays fallback-only; BYO-key users always stay on their provider. See `CATALOG_HYGIENE.md` §4.

**Acceptance:** *(Met for 1+2.)* catalog-hygiene policy documented (`CATALOG_HYGIENE.md`); the per-provider floor is one validated ladder; any further tier/provider change rides the same golden-corpus gating as Phase 5 (`ROUTE_PROMOTION.md`). **Risk:** med. **Effort:** S–M.

---

### Cross-cutting (folded into above, not separate phases)

- **#7 Deterministic prompt extraction:** include only relevant SPEC rows/IDs for PLAN, needed PLAN contracts/AC for HARNESS, parsed harness refs/dependency maps for TASKS (reuse storyboard source-excerpt patterns in `storyboard_source.py`). No lossy LLM summarization. Pairs naturally with phase 2 (smaller, more cacheable prefixes). Validate token reduction via phase-0 ledger; guard with completeness validators.
- **#8 Cheaper workflows:** surface/default focused-refine, section-rewrite, coverage-gap regeneration over full regenerate in the workspace UI; reserve full regenerate for true replacement. Mostly frontend (`StageEditor`/`CoveragePanel`).

---

## 4. Validation plan (per the issue)

Build/extend the golden workspace corpus (simple/medium/complex). For every routing or budget change, compare old vs new on:
eval scores · critic pass rate · artifact completeness · validator pass rate · harness validity · task traceability · storyboard schema/grounding pass rate · user-visible retries · **total cost per successful artifact** (phase-0 ledger).

A change promotes only if cost drops **and** no quality/security/traceability metric regresses.

---

## 5. Rollout order (dependency + risk ordered)

```
Phase 0  Real usage accounting + DB cost ledger        (foundation, low risk)
Phase 5.1 Quality-gate-triggered tier escalation        (HIGH PRIORITY — closes a live risk; S–M)
Phase 1  Storyboard mid-first + strong escalation       (high ROI, low-med risk)
Phase 2  Provider prompt caching (+ extraction #7)      (med risk, adapter change)
Phase 2b Slim static prompt templates (caching-safe)    (med risk, co-designed w/ Phase 2)
Phase 3  Real batch for eval/PR-check/summaries         (med risk, worker)
Phase 4  Budget right-sizing from ledger percentiles    (med risk, repair-guarded)
Phase 5.2/5.3 Complexity classifier + golden-corpus gate (high risk, flag-guarded)
Phase 5b Catalog hygiene / normalized tier ladder       (DONE — levers 1+2; lever 3 deferred)
   ↳ cheaper-workflow UX (#8) ships opportunistically alongside any phase
```

Note the reordering vs. the original plan: because the cheap-primary swap already shipped *without* its safety rails, **Phase 5.1 (escalate to a stronger tier on a quality-gate failure) jumps near the front** — it's small and it closes the biggest live risk. Phase 0 still leads because every later phase's safety case (including 5.2/5.3's golden-corpus comparison) depends on the real per-call cost/quality numbers we don't capture today.
