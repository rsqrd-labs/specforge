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

## Early-bail on an unrecoverable chunk (issue #28, Phase 4)

`pipeline_early_bail_unrecoverable_chunk` (default **false**) is a chunk-loop
change and therefore rides this same gate. A chunk that stops on its output-token
budget is repaired with a *doubled* budget (`_repair_budget`). Once that doubled
budget is already clamped to the model **ceiling**, the repair is the final
escalation — there is no larger budget left to try — and a generation that
over-produced at the prior budget (the d3 case: 89 FRs, truncated) is unlikely to
fit at the ceiling. With the flag on, that ceiling-capped repair is skipped
(counter `specforge_pipeline_completion_repairs_total{outcome="skipped_at_ceiling"}`)
and the `incomplete_output` block surfaces immediately; the refund and recovery
contract are unchanged.

**Under the live catalog this DOES fire for core generation.** Core-gen budgets
are 49152 and the Haiku 4.5 / GPT-5.4 Mini / Gemini 3.5 Flash ceilings are
64000, so an initial limit-stop's doubled budget (98304) clamps to 64000 = the
ceiling → the bail triggers and actively cuts the 64K repair call. It is
therefore **not outcome-preserving**: a generation that only *just* overran
49152 could still fit at 64000, so the flag trades that recovery for the saved
call. That is precisely why it remains a separate rollback flag.

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
