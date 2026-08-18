# Adversarial review — OpenRouter adapter (#152, dfce2d3), targeting DeepSeek V4 Flash

Scope: does flipping `LLM_PROVIDER_PRIORITY` to `openrouter` with DeepSeek V4 Flash
preserve prompt caching, batching, and timeout behaviour?

Live data below was pulled from `GET https://openrouter.ai/api/v1/models` and
`.../models/deepseek/deepseek-v4-flash/endpoints` on 2026-08-14, and from the
OpenRouter provider-routing / errors docs.

---

## F1 — BLOCKER. DeepSeek V4 Flash is not in the catalog, and the tier that runs full artifacts is not DeepSeek

`backend/services/llm/model_catalog.py:877` ships `deepseek/deepseek-v3.2` at tier
`small`. There is no `deepseek-v4-flash` entry. Separately,
`backend/services/pipeline/stage_manager.py:740-762` sets
`_CORE_ARTIFACT_TIER_POLICY["openrouter"] = ("strong", "mid")` and the Demo Day
table matches.

**Failure scenario.** Operator sets `OPENROUTER_API_KEY` and
`LLM_PROVIDER_PRIORITY=openrouter,anthropic`, believing they switched to DeepSeek
V4 Flash. The four core stages, `regenerate.full` and the harness gap-patch
resolve `strong` → `qwen/qwen3.8-max` at $2.00/$6.00 per M, de-escalating to
`z-ai/glm-5.2`. DeepSeek is reached only for judge/eval/refine/storyboard. The
cost profile is ~14× the intended input rate and the artifacts come from a model
nobody graded.

Both slugs were verified live and both resolve, so this fails *silently* as
described rather than 404-ing on the first generation. Their prices did not both
survive the check — see F9.

Two branches, both need an explicit decision:

- **(a) Add V4 Flash to the cheap ladder** (`small`, replacing v3.2). Core stages
  still run Qwen. This is a judge/refine swap, not a generation swap.
- **(b) Point full-artifact generation at V4 Flash** — either by placing it at
  `strong`, or by editing `_CORE_ARTIFACT_TIER_POLICY["openrouter"]` to
  `("small", …)`. This collides head-on with the invariant in CLAUDE.md: the
  artifact policy is a separate table *precisely* so `core_cheap_primary` cannot
  "quietly downgrade an artifact a user was charged for". Users charged
  frontier-tier credits would receive flash-class artifacts. That is a pricing
  decision, not a routing decision, and it needs the Phase-5 golden-corpus gate
  (`docs/evals/ROUTE_PROMOTION.md`) plus a credit-model answer.

---

## F2 — BLOCKER. The upstream route is not pinned. `allow_fallbacks: false` is a no-op without `order`/`only`

`backend/services/llm/openrouter_adapter.py:88` sends
`{"data_collection": "deny", "allow_fallbacks": False}` and the module docstring
(lines 39-46) claims this makes host selection reproducible.

OpenRouter's provider-routing doc is explicit that `allow_fallbacks` "is combined
with the `order` field … to restrict the providers that OpenRouter will
prioritize to just your chosen list." With no `order` or `only`, it only prevents
falling back *past* a list that was never supplied. Default load balancing across
all eligible hosts is untouched. `data_collection: "deny"` is a genuine filter and
survives independently.

`deepseek/deepseek-v4-flash` currently has **20+ live upstream endpoints**:

| Host | quant | max_completion_tokens | prompt $/M | cache-read $/M |
|---|---|---|---|---|
| DeepSeek | unknown | 384,000 | 0.140 | **0.0028** |
| Venice | unknown | **32,768** | 0.138 | 0.028 |
| DeepInfra | fp4 | 65,536 | 0.090 | 0.018 |
| Sail Research | **fp4** | 1,048,576 | 0.072 | 0.016 |
| Baidu | fp8 | 131,072 | 0.085 | 0.017 |
| Parasail | fp8 | 1,048,576 | 0.140 | **0.070** |
| CoreWeave | fp8 | 1,048,576 | 0.140 | 0.070 |

**Three separate failures follow, and they are the three things the review asked about:**

1. **Caching — this is the decisive one.** The endpoints payload carries a
   per-host `supports_implicit_caching` flag. On `deepseek/deepseek-v4-flash` it is
   **`true` on exactly 1 of 19 hosts** (DeepSeek's own; the other 18, including
   every cheaper one the load balancer prefers, are `false`). Prompt caching is
   therefore not "degraded" by the unpinned route — under the shipped config it is
   **structurally near-zero**, since the balancer has 19 candidates and only one of
   them caches at all. Even landing on DeepSeek once doesn't help: prefix caching is
   per-host, so chunk 1 on Baidu and chunk 2 on Fireworks share nothing. This is
   exactly the reuse `_should_cache_system_prompt` exists to exploit.

   Directly answering the question asked: **prompt caching does not survive the
   switch as the adapter is currently written.** `only: ["deepseek"]` is what fixes
   it, and it is the same one-line fix as the reproducibility problem.
2. **Timeouts / output ceiling.** `_chunk_output_budget`
   (`stage_manager.py:1890`) sends `max_tokens=min(32_768, catalog_ceiling)`.
   Venice's real ceiling is exactly 32,768 — zero margin — and it varies 32× across
   the pool. A catalog `default_max_output_tokens` is one number for a fleet that
   isn't one number.
3. **Reproducibility.** Quantisation ranges fp4 → fp8 → unknown. The golden-corpus
   promotion gate grades whichever host answered that afternoon; production runs
   whichever answers next. `docs/evals/ROUTE_PROMOTION.md`'s "confirm upstream route
   pinning is still in place" gate item cannot pass, because it was never in place.

**Fix.** Add `"only": ["deepseek"]` (or an explicit `order`) alongside
`allow_fallbacks: false`. Note the interaction: `only`/`order` *plus*
`data_collection: "deny"` can narrow the pool to zero, which OpenRouter answers with
**503 "no available model provider meets your routing requirements"** — see F7 for
the retry consequence.

**One gap I could not size.** The endpoints payload carries no data-policy field, so
I could not count how many of the 19 hosts survive `data_collection: "deny"` on its
own. If `deny` alone already narrows the pool to a handful, the quantisation and
ceiling spread in the table above is narrower than it looks. It does **not** rescue
the caching finding either way — `supports_implicit_caching` is true on one host,
and `deny` cannot manufacture more. Worth measuring with a real key before sizing
the reproducibility half of this finding.

---

## F3 — HIGH. Prompt caching is unwired, and the ledger structurally cannot show it working

Two independent halves.

**(a) The write path is dropped.** `openrouter_adapter.py:140` and `:202` are
`del cache_system, cache_policy`. Meanwhile
`stage_manager._should_cache_system_prompt` (line 2116) returns `True` for
openrouter — it only suppresses for `anthropic and demo_day and whole_document` —
so `stage_manager.py:3291` still enters `with user_prefix_cache_hint(user_prompt)`
on every call. `current_user_prefix_cache_hint()` is read **only** by
`anthropic_adapter.py:81,135`. The hint is computed and discarded every generation.
Harmless, but it means the code reads as if caching is active when it isn't.

This is defensible for Phase 1 *if* the upstream does automatic prefix caching
(DeepSeek does, with no write premium — `input_cache_write` is absent from every
endpoint's pricing). But it only pays off if F2 is fixed first.

**(b) The read path is priced at full rate.** All three openrouter entries set
`cached_input_cost_per_million == input_cost_per_million`
(`model_catalog.py:884-886, 931-933, 964-966`). The commit justifies this as "no
published cache-discount schedule at review time".

That is not correct. The models API — the same endpoint the commit says pricing was
pulled from on 2026-08-12 — publishes `input_cache_read` for every one of these:

| slug | prompt $/M | catalog `cached_input` | live `input_cache_read` | overstated by |
|---|---|---|---|---|
| `deepseek/deepseek-v3.2` (shipped) | 0.269 | 0.269 | 0.1345 | **2×** |
| `deepseek/deepseek-v4-flash` | 0.140 | — | 0.028 | **5×** |
| via DeepSeek's own host | 0.140 | — | 0.0028 | **50×** |

Cache reads *are* normalised correctly — `usage.py:57-68` delegates to
`_normalize_openai_usage`, which reads `prompt_tokens_details.cached_tokens`. So
tokens land in the cached bucket and are then multiplied by the full input rate.

**Failure scenario.** The switch is made to cut cost. Caching works (after F2 is
fixed), the ledger reports no saving because the discount was priced away, and
`scripts/analyze_output_budgets.py`'s evidence gate reads that same
`llm_cost_events` table. The instrumentation cannot measure the thing being
switched for.

The "safer failure mode" reasoning in the commit is sound as a *default* — it
guards against the `None`-rate/non-zero-token trap that zeroes a row. It just isn't
needed here, because the real rate is published.

---

## F4 — HIGH. No openrouter output-budget override, and DeepSeek V4 Flash is a reasoning model

`output_budget.py:87-98` documents this exact failure for Google in prose: Gemini
bills thought tokens against `max_output_tokens`, so at the 768-token
`refine.focused` default "a single thinking burst consumes the entire budget and the
call returns finish_reason=MAX_TOKENS with empty text." That is why
`("refine.focused","google"): 4096` exists.

`deepseek/deepseek-v4-flash` lists `reasoning`, `reasoning_effort` and
`include_reasoning` in `supported_parameters` — as do `qwen/qwen3.8-max` and
`z-ai/glm-5.2`, both of which the catalog already pins to `effort="medium"`.

The mechanism is confirmed, not assumed. OpenRouter's reasoning-tokens doc:
"**Reasoning tokens are considered output tokens and charged accordingly**" and
"`max_tokens` must be strictly higher than the reasoning budget to ensure there are
tokens available for the final response after thinking." So this is the Gemini shape
exactly, on every openrouter model in the catalog.

`OUTPUT_TOKEN_BUDGET_OVERRIDES` (`output_budget.py:99`) has **no openrouter entry**,
so these apply:

| operation | budget | risk |
|---|---|---|
| `refine.focused` | 768 | the exact Gemini shape |
| `eval.score` | 1024 | judge returns empty JSON |
| `summary.create` | 2048 | tight |

**Failure scenario.** The commit message notes the flip also moves the critic, the
eval judge, the Rung-2 compressor and `pr_check`. The eval judge gets 1024 tokens,
spends them reasoning, returns `finish_reason=length` with empty text. The critic is
**fail-open by design** — judge errors never brick a generation — so quality scoring
silently stops producing scores while every generation still succeeds. Nothing
alerts. `EvalResult` rows just get thinner.

**Fix.** Add openrouter overrides for `eval.score` / `refine.focused` /
`summary.create` *before* the flip (an increase, so outside the evidence gate — same
carve-out the Google entry already documents), or set `reasoning: {"exclude": true}`
/ effort=minimal for the cheap operations.

---

## F5 — MEDIUM (downgraded on evidence). The idle-timeout argument rests on a catalog flag that contradicts the live API

`openrouter_adapter.py:11-25` accepts that the openai SDK drops
`: OPENROUTER PROCESSING` SSE comments (they start with `:`, so the decoder discards
them before they become chunks) and therefore can never reset the watchdog's idle
timer. The stated mitigation: reasoning-delta chunks arrive as real `data:` events
with `delta.content = None` and do reach guard 3 (line 183), yielding the empty
liveness sentinel.

That argument requires reasoning deltas to be in the stream, and the catalog says
they aren't: the shipped primary `deepseek-v3.2` is declared
`supports_reasoning=False` (`model_catalog.py:915`) with the comment "Does not
accept a reasoning/effort request field on OpenRouter" (line 914).

**That flag is factually wrong, and that is a finding in its own right.** The live
models API lists `reasoning` and `include_reasoning` in `deepseek-v3.2`'s
`supported_parameters`. Only the `reasoning_effort` half of the comment is true —
v3.2 does not accept `reasoning_effort`, but it does reason and does accept
`reasoning`.

The wrong flag cuts *for* safety here, which is why this downgrades rather than
stands. OpenRouter's doc: "Reasoning tokens are included in the response by default
if the model decides to output them." So reasoning deltas most likely do arrive as
real `data:` events with `delta.content = None`, hit guard 3
(`openrouter_adapter.py:183-186`), and yield the liveness sentinel — the docstring's
mitigation works, just not for the reason it states.

What still stands:

- **The pre-first-token queueing gap is genuinely uncovered.** The `:
  OPENROUTER PROCESSING` keepalives are the only signal in that window and the SDK
  drops them. `stage_provider_idle_timeout_seconds` (180s) is the sole bound, against
  a 19-host pool with unpinned selection (F2) and no latency guarantee.
- **A hybrid model that declines to reason on a given request emits nothing** until
  the first content token. V4 Flash is explicitly a hybrid-attention efficiency
  model; "if the model decides to output them" is not a guarantee.
- **The flag is load-bearing elsewhere.** It is the stated basis for F10's omission
  and it feeds `supports_reasoning` consumers generally. Correct it regardless.

**Failure scenario.** A 1M-context prompt is queued behind a slow upstream host, the
model answers without a reasoning phase, and no event arrives for 180s.
`_watchdog_stream` (`stage_manager.py:954-976`) kills the call as `idle`, partial
text is discarded, the chunk is lost.

**Verification step:** measure first-token latency on `deepseek-v4-flash` under load
and confirm reasoning deltas actually appear. If they are intermittent, either send
`reasoning: {"enabled": true}` explicitly so the sentinel path is guaranteed, or
raise the idle timeout for this provider.

---

## F6 — MEDIUM. Opus-5 wall-clock constants are inherited unchanged, and the test that pins them cannot detect it

Every chunk length target is a wall-clock budget calibrated at **~38 visible tok/s
≈ 145 chars/s, measured on Opus 5** (`stage_manager.py:1893-1901` and CLAUDE.md).
Three things sit on that constant:

- the harness two-chunk arithmetic: contract ~103s + files ~152s ≈ 255s of a 270s
  run budget;
- `_wave_deadline`'s weighted split for standard spec/tasks, weighted by
  `_max_target_chars`;
- `test_the_two_harness_chunks_fit_the_run_budget_together`.

That test is **provider-agnostic arithmetic over the advertised character targets**.
It stays green regardless of which model runs. So the commit's verification story —
"zero regressions, identical 151-entry failure set, 2578 → 2598 passing" — is true
and also structurally incapable of detecting a throughput recalibration.

Flash-class throughput is likely *faster* than Opus 5, so the immediate risk is low
and the direction is favourable. But `qwen3.8-max` at `effort=medium` (F1: the
model that actually runs core stages today) is entirely unmeasured, and the wave
split hands slack forward based on a chars/s figure that no longer describes the
route. Re-measure per-chunk wall-clock on the real route before the flip, exactly as
the Opus 5 medium→high change should have.

---

## F7 — MEDIUM. A single bad upstream host burns the circuit breaker for the whole provider

`base.py:95` — `RATE_LIMIT_STATUS_CODES = frozenset({429, 529, 503})`. Per
OpenRouter's error docs, **502** = "your chosen model is down or we received an
invalid response from it" — i.e. *upstream provider failure*, including upstream
throttling normalised into a gateway error.

502 is not in that set, so it becomes a plain `ProviderError` →
`record_provider_failure` → 3 within 600s opens the openrouter circuit for the
process. With 19 hosts behind one slug and unpinned selection (F2), one flaky
upstream having a bad minute takes down the whole provider even though 18 healthy
hosts were available — and Anthropic's per-process breaker semantics mean this is
burned once per worker with no cross-worker view.

Consider treating 502 as retry-in-place (it is far closer to a transient upstream
throttle here than to a hard provider failure), or at minimum excluding it from the
breaker the way 429 already is.

**Rider on my own F2 fix, not a defect as shipped.** 503 has two documented meanings
— "no available model provider that meets your routing requirements" *and* "the
provider is temporarily overloaded." Retrying the second is exactly right, so
503-in-`RATE_LIMIT_STATUS_CODES` is correct today. But once `only` +
`data_collection: "deny"` can narrow the pool to zero, the *first* meaning becomes
reachable, and a permanent configuration error will burn
`PROVIDER_RATE_LIMIT_MAX_RETRIES` retries before surfacing. Worth a startup check
that the pinned host list is non-empty under the data policy.

**Verified as working:** `extract_retry_after` returns `None` for a mid-stream
error (no `.response` attached) and correctly falls through to backoff+jitter.

---

## F8 — MEDIUM. Batching degrades correctly, but the economics and the governance both change

The wiring is right: `eval_batch._REAL_BATCH_PROVIDERS = frozenset({"anthropic"})`
(`services/evals/eval_batch.py:66`) and
`PROVIDER_CAPABILITIES["openrouter"]["supports_batch"] = False`
(`model_catalog.py:143`), so `provider_supports_real_batch` is false twice over and
eval falls through to `batch_executor`. That path records `batch=False` on the cost
event, so it does not halve the recorded cost — no ledger corruption. Good.

Two consequences worth stating explicitly rather than discovering later:

1. **The 50% Message Batches discount is gone** for `eval.score` /
   `summary.create` / `audit.artifact_quality` / `prompt_regression.run`. On the
   raw rates DeepSeek is still far cheaper, so this is a smaller effect than F3 —
   but it is a real part of the cost delta and it is not in the commit's arithmetic.
   Note that OpenRouter does expose batch pricing on some models as a **slug
   variant** (`z-ai/glm-5.2:batch` is live today) rather than through a Message
   Batches API. That is a catalog-entry change, not an adapter change, if the
   discount is wanted back for the async eval path.
2. **The fan-out is governed differently.** Per CLAUDE.md the provider inflight
   budget (`provider_max_inflight_generations`) is a *core-generation* budget and
   ships at 0/unlimited; eval batches ride their own rate tiers. The synchronous
   eval path is bounded only by `max_concurrent_advisory_tasks` (default 12). A
   backlog sweep (`_SWEEP_LIMIT = 200`) that previously became one Anthropic batch
   submission now becomes up to 200 real-time OpenRouter calls throttled at 12
   concurrent — against an account-level 429 ceiling (F7) rather than a batch queue.

---

## F9 — MEDIUM (upgraded on evidence). Catalog prices for the shipped tiers are already wrong, and floating slugs guarantee more drift

Checking the two slugs F1 depends on against the live API found the catalog is
already out of step two days after the pull:

| slug | catalog in/out $/M | live in/out $/M | live `input_cache_read` | live `input_cache_write` |
|---|---|---|---|---|
| `qwen/qwen3.8-max` (strong) | 2.00 / 6.00 | 2.00 / 6.00 ✓ | **0.25** (catalog: 2.00) | **2.50** (catalog: 2.00) |
| `z-ai/glm-5.2` (mid) | 0.489 / **1.536** | 0.40 / **2.52** | **0.08** (catalog: 0.489) | — |

Two things beyond the F3 cache-read pattern:

- **`glm-5.2` output cost is understated by 64%** (1.536 vs 2.52). That is the
  retry-down target for full-artifact generation, so every de-escalated core
  generation under-reports its real cost in `llm_cost_events`. Input is overstated
  22% in the other direction, so the errors do not cancel.
- **`qwen3.8-max` has a real `input_cache_write` premium of $2.50/M** — 1.25× base
  input, the exact Anthropic shape the commit assumed OpenRouter didn't have
  ("OpenRouter's usage payload carries no Anthropic-style ephemeral_5m/1h
  breakdown"). The TTL-split reasoning is fine; the premise that no write premium
  exists is not. Since `usage.py:57-68` leaves `cache_write_input_tokens`
  unpopulated, any implicit cache writes on this model are billed by OpenRouter and
  recorded as zero by the ledger.

### Floating slugs

`deepseek/deepseek-v4-flash` is a moving alias. Live today:

`deepseek/deepseek-v4-flash` is a moving alias. Live today:

| slug | prompt / completion $/M | max_completion_tokens |
|---|---|---|
| `deepseek/deepseek-v4-flash` | 0.140 / 0.280 | 393,216 |
| `deepseek/deepseek-v4-flash-0731` | 0.080 / 0.180 | 384,000 |
| `~deepseek/deepseek-v4-flash-latest` | 0.072 / 0.144 | 262,144 |

Nearly 2× on price and a different output ceiling. `docs/evals/CATALOG_HYGIENE.md`
already mandates quarterly + on-release review and deprecate-don't-delete; note in
the entry's `rollout_notes` that these rates are a point-in-time snapshot of a
floating alias, or pin the dated slug.

---

## F10 — LOW. `_LOW_REASONING_CORE_MODELS` gap goes live the moment V4 Flash lands

(Note this finding's cited justification is itself built on the wrong capability
flag — see F5.)

`model_catalog.py:53-62` correctly predicts this: the openrouter row is omitted
because v3.2 "declares no `reasoning_effort` at all … a deliberate day-one no-op …
The moment the ladder primary gains an effort knob this stops being free and needs a
row here."

`deepseek-v4-flash` **does** support `reasoning_effort`. If it is added to the cheap
ladder with any effort value and no row here, `core_generation_low_reasoning`
becomes a silent no-op on the primary. Add the row in the same change.

---

## F11 — LOW. Mid-stream errors are handled correctly today, but on undocumented SDK internals

I expected a silent-truncation hole here and it isn't one. Verified against the
installed SDK (openai 2.41.0):

- OpenRouter reports mid-stream failures as HTTP 200 + an SSE chunk carrying a
  top-level `error` object and `choices[0].finish_reason = "error"`.
- `openai/_streaming.py:87-99` checks `data.get("error")` **before** processing the
  chunk and raises `APIError`.
- `APIError` subclasses `OpenAIError`, so `openrouter_adapter.py:188` catches it and
  `_wrap_openrouter_error` runs.
- `classify_provider_status` reads `.code`, which `APIError.__init__` populates from
  the body. OpenRouter sets `code` as an **integer**. Confirmed by construction: a
  body of `{"code": 429, …}` classifies as 429 → `ProviderRateLimitError`; `{"code":
  502}` classifies as 502 → `ProviderError`.

So partial text is discarded and the chunk is retried, same as every other provider
— it never reaches `apply_finish_reason` and never grades as a real artifact.

The caveat: `pyproject.toml:22` pins `openai>=2.0,<3.0`, and this behaviour is
undocumented SDK internals inside a wide range. If a minor bump stops raising, the
regression is silent — Guard 1 yields `""`, the stream ends early with partial text,
`stopped_by_limit` stays False, and a truncated artifact is graded. Under the refund
policy `missing_sections` does **not** refund, so the user pays for it. Worth one
pinned test that feeds an error-bearing chunk through the adapter and asserts it
raises.

---

## What does not break

Stated so the rest is calibrated:

- **`harness_coverage_ratio`** is deterministic and provider-independent. The
  coverage chip, CoveragePanel gap list and paid patch stay consistent.
- **`artifact_validator.validate_sections` / `validate_artifact_completeness`** are
  zero-LLM. Section contracts and depth floors are unaffected by the provider.
- **Config skip / circuit breaker plumbing** is complete: `provider_status.py:30`
  maps `openrouter` → `openrouter_api_key`, `config.py:33` defaults it to `""` which
  `is_provider_configured` treats as unset, and `validate_llm_provider_priority`
  accepts the name. The adapter is genuinely inert until opted in.
- **Adapter API table** (`cost_registry.py:187`) and the `quality_gates.py:124`
  openrouter baseline row are both present and correctly shaped.
- **Batch flag correctness** — see F8; `batch=False` is recorded honestly.

## Cross-cutting, not asked about but inside "won't be broken"

The flip also moves the **critic, the eval judge, the Rung-2 compressor and
`pr_check`** (the commit says so). Eval scores produced before and after are not
comparable, and no `EvalResult` row records which judge model produced it — so
historical `overall_score` trends silently splice two different graders. Either
record the judge model on the row, or pin judge/eval to Anthropic across the flip
and move only generation. `docs/evals/ROUTE_PROMOTION.md`'s judge-agreement check
covers this; make sure it runs before, not after.
