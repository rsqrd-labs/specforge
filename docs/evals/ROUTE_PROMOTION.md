# LLM Route Promotion

Route promotion is manual and evidence-based. Cheaper provider/model tiers can
become defaults only after the ASDD golden dataset shows no deterministic
validator regressions, no security coverage regression, acceptable quality, and
the expected cost reduction for that operation/provider family.

Run the CI-safe dry-run:

```bash
cd backend
uv run python ../scripts/run_llm_route_eval.py --operation all --provider openai --format markdown
```

The dry-run never calls provider APIs. It validates dataset shape, route
resolution, deterministic validators, estimated usage/cost plumbing, the
promotion gate configuration, and the **deterministic complexity classifier**
(Phase 5.2): every golden case must classify to its declared
`complexity.expected_level` / `expected_tier_floor`. The classifier check is
evaluated at the problem-statement level (stage `spec`, no upstream) so the
expectation is a stable function of the prompt itself — later stages can only
raise the floor, never lower it.

## Adaptive routing (Phase 5.2 / 5.3) — what the dry run can and cannot prove

Core generation ships a **cheap-primary** policy (Haiku 4.5 / GPT-5.4 Mini start,
mid escalation on a runtime or quality-gate failure). Two flags gate the
adaptive layer:

- `core_cheap_primary` (default **true**) — wraps the live behavior. Set it
  **false** to revert every core generation (fresh stages, full regenerate,
  harness gap-patch) to the pre-cheap-swap **mid-first** default in one toggle.
- `core_complexity_routing` (default **false**) — the deterministic complexity
  classifier that raises the *starting* tier for predictably hard requests
  (regulated domains, large upstream chains, prior quality-gate failures). It is
  a floor, never a ceiling, and only applies while `core_cheap_primary` is on.
  Per the issue's acceptance criteria, it ships **off** and is enabled only after
  the manual live gate below validates it.

**The dry run cannot produce the cheap-vs-mid *quality* comparison.** Its
simulated output is fabricated from `expected_traits` and is identical regardless
of tier, so running it at the cheap tier vs the mid tier yields identical
deterministic-validator and quality scores — only the resolved route and
estimated cost differ. The genuine quality comparison (artifact completeness,
critic pass rate, traceability, Storyboard schema/grounding, **cost per
successful artifact**) is therefore the **manual live gate**: run the expanded
golden corpus through real provider calls from an operator-approved branch with
`core_complexity_routing` toggled on vs. off, and attach the saved report to the
promotion review. Only promote (flip `core_complexity_routing` to true by
default) if cost drops and no quality / security / traceability metric regresses.

Storyboard generation is validated through its own `StoryboardPayload` schema +
grounding path, not the deterministic route-eval simulated output; it carries a
route gate entry only so the gate config is complete and its route resolves.
Since the issue #17 follow-up it shares the product-wide cheap-primary→mid
policy (`generation_tier_policy`, gated by `core_cheap_primary`); the quality of
the cheap storyboard primary vs. mid is a live manual check, since the dry run is
tier-identical.

**Classifier watch list (check before defaulting `core_complexity_routing` on):**
the regulated-keyword set is deliberately broad on a few high-frequency terms —
notably `payment` (and `financial`, `audit trail`) — which alone cross the high
threshold and raise the start to mid. Many ordinary apps mention payments without
being PCI-scoped, so the live comparison should report the **false-positive
raise rate** (cheap-viable prompts pushed to mid) alongside the quality numbers.
This is a floor (cost-up, never quality-down), so it is safe to ship off; the
live gate exists precisely to confirm the over-routing rate is acceptable before
the default flips.

Promotion requires:

- Passing deterministic validators against the golden dataset.
- Average quality at or above the operation/provider gate.
- Human acceptance on sampled live outputs.
- Cost reduction at or above the configured target.
- No regression on security-sensitive or adversarial prompts.

Live provider evals must be run from an operator-approved branch with explicit
API keys and a saved JSON/Markdown report attached to the promotion review.

## Chunk failure policy

Core stage generation has no automatic completeness-repair or whole-document
regeneration path. A token-limit/completeness failure checkpoints successful
siblings, saves a safe partial as `incomplete_output`, refunds once, and ends the
durable run. A user-requested Regenerate starts a new run. Model-routing changes
still require this promotion gate; failure cleanup does not have a rollout flag.

The deterministic dry run cannot measure the trade (its simulated output never
limit-stops), so promotion is a **manual live step**: on the golden corpus, with
the flag on, confirm the count of artifacts that recover *only* via the
ceiling-budget repair is negligible, and that latency/cost on the limit-stop path
drops. Only then flip the default to true.

Scope notes: the bail is confined to the per-chunk limit-stop repair. A
sub-ceiling limit-stop (the doubling can still hand the repair a strictly larger,
below-ceiling budget) and the full-artifact repair pass — which carries
**structural** completeness issues, never `provider_stopped_by_limit` — are both
left untouched. An uncatalogued model (unknown ceiling) never bails. With the
flag off, the chunk loop is byte-identical to today.

## Tier ladder & catalog hygiene (Phase 5b)

The per-provider cheap-tier floor is a single declarative ladder
(`CORE_GENERATION_TIER_LADDER` in `model_catalog.py`) from which the live
cheap-primary policy is derived and CI-validated. Any change to *which model
actually runs* — lowering a provider's floor, promoting a new cheap/fast model to
a core-gen default, or taking up the deferred cheapest-provider-first lever —
rides this same golden-corpus gate. The ladder, the CI-enforced hygiene
invariants, and the quarterly/on-release review process are documented in
[`CATALOG_HYGIENE.md`](CATALOG_HYGIENE.md).

## openrouter provider promotion (issue #152)

Shipping the openrouter catalog entries, adapter, and per-provider table rows
is inert by itself: nothing routes there until `LLM_PROVIDER_PRIORITY` is
edited to include `"openrouter"` and `OPENROUTER_API_KEY` is set to a real
key. That env flip is a **separate, gated promotion** — the four items below,
not just the golden-corpus run every other route change requires — because it
moves more than generation.

0. **Privacy-compatible pool preflight — do this first; it can invalidate everything
   below.** `GET /providers/health?model=deepseek/deepseek-v4-pro` (admin) makes
   a real 1-token call carrying the catalog's upstream-host preference and
   privacy policy. If `data_collection: "deny"` filters out every host, the pool is
   empty, OpenRouter answers a permanent **503 "no available model provider
   meets your routing requirements"**, and every generation fails identically.
   The response's `probe_error` field distinguishes that from a bad key. There
   is no way to determine this from code — DeepSeek's data policy is not exposed
   on the public API. Do not weaken the data-retention policy to make the probe
   pass; keep a direct provider next in `LLM_PROVIDER_PRIORITY` instead.

1. **Live golden-corpus run.** Same procedure as the rest of this document:
   run the expanded golden corpus through real openrouter calls
   (`deepseek/deepseek-v4-flash` mid, `deepseek/deepseek-v4-pro` strong) from an
   operator-approved branch and attach the saved report.

   **Also capture throughput.** Every chunk length target is a wall-clock budget
   converted at `stage_manager._MEASURED_CHARS_PER_SECOND`, where openrouter is
   `None` (unmeasured) and the shipped numbers come from Opus 5 at
   `effort=medium`. Read `latency_ms` and output length back from
   `llm_cost_events` for one spec and one harness generation, derive chars/s,
   and record it. If it diverges materially, re-derive `_chunk_length_target`'s
   numbers **and** the harness two-chunk split together — they are one
   arithmetic, and `test_the_two_harness_chunks_fit_the_run_budget_together` is
   arithmetic over the advertised targets, so it stays green either way.

2. **Judge-agreement check — required before step 1's quality numbers can be
   trusted, not after.** `provider_config.JUDGE_MODELS["openrouter"]` resolves
   to `deepseek/deepseek-v4-flash`. Because `call_judge_model`'s routing is
   `judge_provider = provider if provider in JUDGE_MODELS else
   _DEFAULT_JUDGE_PROVIDER` (`gateway.py`), the flip moves the **critic**
   (`services/pipeline/critic.py`), the **eval judge** itself, the **Rung-2
   problem compressor** (whose output becomes the problem statement for all
   four stages), and the GitHub **`pr_check`** evaluator onto the openrouter
   judge model in the same instant it moves core generation — on artifacts
   that did not change. Score ≥30 stored artifacts spanning all four stages
   and both modes (standard + Demo Day) under both
   `JUDGE_MODELS["anthropic"]` (Haiku 4.5) and `JUDGE_MODELS["openrouter"]`
   (deepseek-v4-flash) before the golden-corpus run's quality numbers are
   accepted. **Accept only if** mean `|Δ overall_score|` ≤ 0.03 and no scored
   artifact crosses a `QualityBadge` colour boundary. These numbers are a
   starting proposal, fixed **before** the run — not chosen after looking at
   the data.

3. **Privacy Policy update, merged first.**
   `frontend/src/pages/LegalPrivacy.tsx` currently names only Anthropic,
   OpenAI, and Google as AI model providers. The day-one openrouter ladder
   routes through **DeepSeek** via the OpenRouter proxy — an undisclosed
   sub-processor today, headquartered in **CN** with no datacenter list
   published on OpenRouter's provider API. Update the policy (and its
   `LegalPrivacy.test.tsx` coverage) to name openrouter and its upstream
   models before the env flip ships to production — shipping the adapter
   inert changes nothing here; the flip is what starts transmitting user
   content to them.

4. **Preferred upstream route with same-model fallback — verify both.**
   `services/llm/openrouter_adapter.py` sends
   `provider: {"order": [...], "allow_fallbacks": true, "data_collection":
   "deny"}`, where `order` comes from the catalog entry's `upstream_providers`.

   `order` keeps DeepSeek's cache-capable/costed endpoint first in the normal
   case; `allow_fallbacks: true` lets OpenRouter use another endpoint for the
   same model when that host is unavailable. On `deepseek-v4-flash` just 1 of
   19 upstream hosts supports prefix caching, hosts disagree on real output
   ceiling by up to 32x, and catalog rates describe the preferred host rather
   than the alias, so resolved-upstream usage metadata is authoritative when a
   fallback occurs.

   Verify with `uv run python ../scripts/check_openrouter_catalog_drift.py`
   (exit 0), and record the resolved upstream
   (`last_completion.raw["resolved_upstream_provider"]`, carried through to
   `llm_cost_events.provider_usage_raw`) in the promotion report so a future
   reviewer can confirm which host actually served the corpus.

5. **Judge provenance is recorded.** `eval_results.judge_provider` /
   `judge_model` (migration 0045) are written on both the synchronous and
   batch-collect paths. Confirm new rows carry them before the flip — they are
   what makes the step-2 agreement numbers joinable and stop pre/post
   `overall_score` trends from silently splicing two graders.

Two of these four are not code, which is exactly why they are called out here
rather than assumed: a clean `pytest` run and a passing dry-run eval do not
touch the Privacy Policy or produce the judge-agreement numbers.
