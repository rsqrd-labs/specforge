# Problem-Statement Abstractive Compression — Promotion Gate (Phase C)

The Rung-2 abstractive pass (`services/pipeline/problem_compressor.py`) is the
meaning-preserving half of problem-statement compression. It is **paid** (cheap
judge-model calls) and **lossy on prose**, so — exactly like adaptive LLM routing
(`ROUTE_PROMOTION.md`) — it ships **off** and is promoted only after an
evidence-based, partly-manual gate.

It is gated by a **sub-flag** of the Phase-B master flag:

- `problem_statement_compression` (**enabled by default since Phase D**) — the
  Phase-B master. The whole zero-LLM ladder (Rung 0/1/3) and the bounded-cost /
  never-fail guarantees live here. It changes nothing for under-budget input and
  uses only the deterministic ladder for over-budget input, so it shipped on once
  the Rung-0 regression pin and golden corpus were green. When it condenses
  (Rung 2/3) the user sees a non-blocking advisory notice on the generated stage
  (`AdvisoryFindingsPanel`).
- `problem_statement_abstractive` (default **false** — still pending this gate) — this gate. Meaningful
  **only when the master is also on**. When both are on, an over-budget statement
  that the deterministic ladder would hand to the Rung-3 clamp is instead routed
  through the capped map-reduce. Phase-B reliability never depends on this flag.

So "flip the flag" in the plan's Phase D is two flags in sequence: enable the
master (Phase B reliability), then — after this gate — enable the sub-flag.

## What Rung 2 guarantees by construction

The document is partitioned into **normative** blocks (any block with a `FR/NFR/SEC`
ID, a `must/shall/should` modal, a list item, or a table row) and **narrative**
blocks. Normative blocks are kept **verbatim and first**; only narrative is sent to
the model. The assembled result is `[verbatim normative] + [abstractive narrative]`
with a final boundary-aligned truncate that, because normative is first, can only
trim the narrative tail. Therefore **normative retention is 100% by construction** —
a requirement ID can never be paraphrased away or dropped.

The pass is **fail-open**: no narrative, no leftover budget, narrative over the
map-reduce input cap (`_RUNG2_MAX_CHUNKS × _RUNG2_CHUNK_TOKENS`), or any judge
error/timeout returns the deterministic Rung-3 floor (also normative-first).

## The gate

### 1. Dry-run — CI-safe, no API calls

```bash
cd backend
uv run python ../scripts/run_problem_compression_eval.py
```

Proves the structural invariant over `docs/evals/golden_prompts/problem_compression_rung2_golden.json`:
for every narrative-dominant case, partition exactly as the runtime does and assert
`normative_retention(raw, normative_prefix) == (total, total)`. Any lost ID is a
hard failure. This is also pinned in `tests/test_problem_compressor.py`
(`test_rung2_normative_retention_is_total`) so a regression breaks CI.

The dry-run **cannot** judge narrative semantic equivalence — that needs a live
model.

### 2. Live — manual, calls provider APIs

```bash
cd backend
uv run python ../scripts/run_problem_compression_eval.py --live --provider anthropic
# repeat for --provider openai / google
```

Runs the real map-reduce and reports, per case: the rung reached (expect `2`), the
**measured** normative-retention ratio (expect 1.0), and whether the result is
within budget. Then a human **reads the condensed narratives** and confirms:

- no invented facts, constraints, numbers, dates, or named entities;
- no dropped material constraint that was stated only in prose;
- the condensed prose still reads as the same product.

## Promotion criteria

Flip `problem_statement_abstractive` to **true** (per provider, after Phase B's
master flag is already on and healthy) only when:

| Criterion | Target |
|-----------|--------|
| Dry-run structural invariant | 100% of corpus cases (CI-enforced) |
| Live measured normative retention | ~99–100%, every case |
| Live narrative semantic equivalence (human read) | no invented/dropped facts |
| Added latency | < 3s p95 (the pass is amortised to ~0 across regens via the Redis cache) |
| Result within budget | every case |

## Rollback

Set `problem_statement_abstractive=false`. The next compression of any statement
recomputes under the deterministic ladder (the cache key carries the mode, `a1`
vs `a0`, so the two regimes never cross-serve). A degraded result (abstractive
requested but fell open to the floor) is cached for only 5 minutes, so a transient
judge outage self-heals without a flag flip. As noted in the plan's Phase-D
caveat, a flag flip does not invalidate the *generation* cache (≤24h TTL); accept
that window or pair the flip with a generation-cache flush.

## Telemetry

`thought2build_problem_compression_rung_total{rung}` now counts `rung="2"` for a
successful abstractive pass. A spike in `rung="3"` while the sub-flag is on means
the judge is failing open (outage, over-cap input, or no narrative room) — the
artifact is still safe (normative-first floor), but it is not getting the
meaning-preserving treatment.
