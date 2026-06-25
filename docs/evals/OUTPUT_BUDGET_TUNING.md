# Output Budget Tuning (Phase 4 — issue #26)

Right-sizing the per-operation `max_tokens` budgets is **evidence-based and
manual**, mirroring route promotion. A budget is lowered only when the cost
ledger proves, for a specific `(operation, provider)` pair, that the smaller
budget still fits real artifacts with headroom and without truncation.

We never guess a budget down. The defaults in `OUTPUT_TOKEN_BUDGETS`
(`backend/services/llm/output_budget.py`) are deliberately generous because
frontier reasoning tokens bill against the same `max_tokens` as visible output
(issue #19). Core stage generation currently uses a 49152-token first-attempt
budget with a limit-stop repair that can grow to the 64000-token model ceiling.
Do not lower those budgets in the latency v1 change; first collect telemetry
after `core_generation_low_reasoning` lands, because lowering reasoning changes
the output-token distribution this gate reads.

## The evidence

Every model call writes one `llm_cost_events` row (Phase 0) with
provider-reported `output_tokens`, `reasoning_tokens`, and `stopped_by_limit`.
`reasoning_tokens` is already **inside** `output_tokens`, so the percentile of
`output_tokens` already accounts for thinking — never add a separate reasoning
allowance on top of p95.

Run the analysis (read-only; never edits code, never writes the ledger):

```bash
cd backend
uv run python ../scripts/analyze_output_budgets.py --since-days 28 --format markdown
```

It computes p50/p90/p95/max of `output_tokens` and the truncation rate per
`(operation, provider)`, then prints a recommendation per pair. Against an empty
or sparse ledger every row reads `insufficient_samples` and recommends no
change — the correct behavior when there is no evidence.

## The promotion gate

`recommend_output_budget` proposes a reduction only when **all** hold:

1. **Enough samples** — `samples >= 200` for that `(operation, provider)`. A
   percentile from a handful of calls is noise.
2. **Zero truncation** — `truncation_rate <= 0.005`. Any meaningful rate of
   `stopped_by_limit` means the *current* budget is already too tight; lowering
   it would be wrong.
3. **Fits with headroom** — `ceil(p95 × 1.30)`, clamped to
   `[floor(operation), model_ceiling]`, is **strictly below** the current
   budget. The 30% headroom clears the p95→p99 tail; the rare miss is caught at
   runtime by the existing `provider_stopped_by_limit` doubling repair.
4. **Above the completeness floor** — the recommendation is floored
   (`_OUTPUT_BUDGET_FLOORS`) well above what `validate_artifact_completeness`
   needs, so a "right-sized" budget can never cause a permanent repair loop.

## Promoting a change

1. Confirm the gate is met for the pair over a representative window (≥ the
   plan's 2–4 weeks).
2. Re-run the ASDD golden corpus (`scripts/run_llm_route_eval.py`,
   `docs/evals/ROUTE_PROMOTION.md`) — no validator / critic / security
   regression.
3. Add the value to `OUTPUT_TOKEN_BUDGET_OVERRIDES` keyed by
   `(operation, provider)`. Leave the per-operation default untouched so other
   providers keep the generous budget until they clear the gate independently.
4. Bump the prompt version is **not** required — `max_tokens` is a request
   parameter, not part of the cached prompt prefix, so caching is unaffected;
   the SpecForge output cache invalidates once, like any budget change.

## Monitoring after a change

A too-tight budget self-heals via repair, so watch for the regression signal
rather than artifact failures:

- `stopped_by_limit` rate for the tuned `(operation, provider)` in the ledger —
  must stay ~0.
- The `pipeline_*` repair counters (`provider_stopped_by_limit` doublings) —
  a rise means the new budget is biting; revert the override.

Reverting is a one-line deletion from `OUTPUT_TOKEN_BUDGET_OVERRIDES`.
