# LLM Cost Optimization Plan (Issue #26)

Production-ready program to reduce LLM API spend **without** weakening intelligence,
artifact completeness, traceability, security validators, or user trust.

This plan is grounded in the current code, not the issue text. Several of the issue's
stated cost drivers are already mitigated; others are genuinely unbuilt. The phasing
below removes waste and instruments first, then introduces cheaper routing only behind
validators and telemetry.

---

## 1. Current state vs. issue assumptions

| # | Issue proposal / premise | Reality in code | Classification |
|---|--------------------------|-----------------|----------------|
| premise | Core SPEC/PLAN/HARNESS/TASKS route **strong-first** | `STAGE_GENERATION_TIERS` = `("mid","strong")` for all four stages; mid-first with single strong retry already shipped (commit `8746db7`, `stage_manager.py:119-128`) | **Already done** |
| extra | Use the **cheap/fast latest-gen model** per provider | Core gen already defaults to the mid tier = the fast/cheap current-gen model: Sonnet 4.6 / GPT-5.4 / Gemini 3.5 Flash (`model_catalog.py`). The genuinely cheaper latest-gen tier (GPT-5.4 Mini, Flash-Lite) is **locked out of core ops**; tier ladder is asymmetric across providers | **Mostly done — cheap-tier floor is the delta** |
| premise | Full **regenerate** routes strong-first; refine.section/full strong | `regenerate.full`, `refine.section`, `refine.full` still resolve `strong` (`stage_manager.py:417-431`) | **Valid — still strong** |
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

**Net:** the safe, high-value path is **phase 0 (real accounting) → storyboard mid-first → provider caching → real batch → budget right-sizing → adaptive routing**. Core-gen downgrade — the scary part — is already shipped; what remains is regenerate/refine and the measurement+caching that lets us go further safely.

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

### Phase 5 — Adaptive routing for core generation *(riskiest; last; golden-corpus gated)*

Do **not** globally downgrade. Add a **deterministic** complexity classifier (no LLM call):
- problem length, ambiguity markers, security/regulatory keywords, number of source artifacts/upstream refs, prior failed generations, quality-gate history, template type.

Policy:
- **High complexity →** strong first.
- **Normal/low →** mid first with automatic strong escalation on validator failure, incomplete output, quality-gate failure, or low eval score (the escalation machinery already exists for the current mid→strong retry).
- **HARNESS/TASKS:** conservative rollout only after golden-corpus validation.
- **Increment generation:** keep strong until tests prove mid preserves task refs + traceability.

**Gating:** expand `asdd_route_golden.json` from 8 cases to a corpus covering simple/medium/complex across all stages + storyboard; run `scripts/run_llm_route_eval.py` old-vs-new through the existing `ROUTE_PROMOTION.md` process. Ship behind an `adaptive_routing` flag; default-on only after the promotion gate passes (no validator regression, quality ≥ threshold, cost reduction met, no security regression).

**Acceptance:** adaptive routing behind a flag with golden-corpus comparison before default (Issue AC 6). **Risk:** high. **Effort:** L.

#### 5b — Cheap-tier floor & latest-gen catalog hygiene

Core gen *already* uses the cheap/fast latest-gen model (the mid tier: Sonnet 4.6 / GPT-5.4 / Gemini 3.5 Flash). The remaining levers:

1. **Let the genuinely cheapest latest-gen tier serve the low-complexity branch.** Today `mini`/`small` models (GPT-5.4 Mini at $0.75/$4.5 — ~3.3× cheaper than GPT-5.4; Gemini Flash-Lite) are not in `CORE_GENERATION_OPERATIONS`' recommended set, so routing can't pick them for a stage even when the work is trivial. Add them as **recommended (not default)** for core ops and let the Phase-5 complexity classifier route low-complexity stages there, with automatic mid→strong escalation on any validator/quality failure. This is the safe way to go *below* mid without globally downgrading.
2. **Normalize the per-provider cheap-tier floor.** The ladder is asymmetric: Anthropic jumps mid→small (Sonnet→Haiku, no mini), OpenAI has mini but no small, Google has small (Flash-Lite). Decide each provider's cheap floor for core gen's low-complexity branch (e.g. is Haiku 4.5 acceptable for a trivial spec, or is Sonnet the Anthropic floor?) and encode it consistently.
3. **"Latest-generation only" catalog hygiene.** The catalog is already the single source of truth with deprecated models flagged. Add a written periodic-review step (e.g. quarterly + on any provider release) so the next cheaper fast model (next Flash/Haiku/mini) is eval'd on the golden corpus and swapped in one place — keeping the cheap tier on the current generation without ad-hoc edits.
4. **(Optional, sensitive) cheapest-provider-first for platform-key generations.** Gemini 3.5 Flash is the cheapest mid by output ($9/M vs $15/M). `allow_cross_provider` exists today only as a fallback; using it as a *primary* cost-optimizing choice for platform-key (non-BYO) generations is a real lever — but it changes which provider a user's output comes from, so it ships only behind golden-corpus quality parity and a product decision. BYO-key users always stay on their chosen provider.

**Acceptance:** cheap-tier eligibility + catalog-hygiene policy land with the same golden-corpus gating as Phase 5; no quality/security/traceability regression. **Risk:** med-high (folds into Phase 5's gating). **Effort:** S-M on top of Phase 5.

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
Phase 0  Real usage accounting + DB cost ledger      (foundation, low risk)
Phase 1  Storyboard mid-first + strong escalation     (high ROI, low-med risk)
Phase 2  Provider prompt caching (+ extraction #7)    (med risk, adapter change)
Phase 2b Slim static prompt templates (caching-safe)   (med risk, co-designed w/ Phase 2)
Phase 3  Real batch for eval/PR-check/summaries       (med risk, worker)
Phase 4  Budget right-sizing from ledger percentiles  (med risk, repair-guarded)
Phase 5  Adaptive routing for core gen                (high risk, flag + corpus gated)
   ↳ cheaper-workflow UX (#8) ships opportunistically alongside any phase
```

This matches the issue's own "safest initial savings path = caching + batch + storyboard," but front-loads the measurement foundation the issue lists as AC #1 — because every later phase's safety case depends on real numbers we don't capture today.
