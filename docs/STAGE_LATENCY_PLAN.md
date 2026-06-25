# Stage Generation Latency Reduction Plan

## Summary

- Target p90 end-to-end stage generation under 120 seconds; p95 over 180 seconds is a regression signal.
- Current checkout already has parallel chunking and prompt caching. Remaining latency is mainly high reasoning/thinking on 49152-token core calls plus repair paths rerunning chunks at the 64000-token ceiling.
- v1 keeps output budgets unchanged and focuses on operation-scoped low reasoning plus optional ceiling-bound repair skipping.

## Implemented V1 Changes

- `core_generation_low_reasoning` gates operation-aware request policy for primary stage-generation calls only.
- Low policy applies only to `spec.generate`, `plan.generate`, `harness.generate`, `tasks.generate`, and `regenerate.full`.
- Effective low policy:
  - Anthropic Haiku: `reasoning_effort="low"`
  - OpenAI Mini: `reasoning_effort="low"`
  - Google Flash: `thinking_level="low"`
- Mid/strong escalation, judge/eval, clarify, refine, batch eval, storyboard, critic regenerate, harness patch, and increment paths keep catalog policy for v1.
- `get_llm(provider, model, *, operation=None, bypass_circuit=False)` caches adapters by `(provider, model, operation or "catalog", key_fingerprint)` so low core-stage policy cannot leak to non-core calls on the same model.
- `pipeline_early_bail_unrecoverable_chunk` now covers both sequential and parallel chunk paths. When a chunk hits `provider_stopped_by_limit` and the repair would run at the final model ceiling, the pipeline can skip the 64000-token retry, block/refund immediately, and increment `skipped_at_ceiling`.
- Non-limit depth, traceability, and completeness issues remain advisory findings rather than paid repair triggers.
- `llm_cost_events` metadata now includes populated `retry_count` and `repair_count`.
- Prometheus includes `specforge_pipeline_stage_end_to_end_duration_seconds{stage_type,provider,outcome}` for end-to-end stage wall time.

## Development Rollout

- No canary deployment: the app is in development.
- Rollout order:
  1. Implement behind flags.
  2. Run targeted automated tests.
  3. Rebuild and run locally.
  4. Execute one full Spec -> Plan -> Harness -> Tasks generation flow.
  5. Inspect `llm_cost_events` and Prometheus metrics.
  6. Keep `core_generation_low_reasoning=true` in development if acceptance criteria pass.
- Rollback is config-only:
  - Set `core_generation_low_reasoning=false` to restore catalog reasoning/thinking.
  - Set `pipeline_early_bail_unrecoverable_chunk=false` if repair skipping regresses recovery.
  - Last resort quality rollback remains `pipeline_parallel_chunks=false`.

## Verification

Run the latency query after a local full generation:

```sql
select operation, stage_type, model,
       count(*) as calls,
       round(avg(latency_ms)/1000.0,1) as avg_s,
       max(latency_ms)/1000 as max_s,
       round(avg(output_tokens)) as avg_out_tok,
       round(avg(reasoning_tokens)) as avg_reasoning_tok,
       sum(case when stopped_by_limit then 1 else 0 end) as limit_stops
from llm_cost_events
where latency_ms is not null and created_at > now() - interval '1 day'
group by operation, stage_type, model
order by calls desc;
```

Acceptance:

- p90 stage duration < 120s.
- Lower reasoning/output-token tail.
- No increase in `stopped_by_limit`.
- No quality-outcome regression in local/golden validation.
- `specforge_pipeline_completion_repairs_total{outcome="skipped_at_ceiling"}` only rises on ceiling-bound provider limit stops.

## Deferred

- Do not lower output budgets in v1.
- Run `scripts/analyze_output_budgets.py` only after low-reasoning telemetry lands.
