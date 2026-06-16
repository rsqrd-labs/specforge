# Brave Grounding Promotion (issue #12, Phase 5)

Enabling Brave web-research grounding platform-wide is a **flag flip**, not a
deploy: `brave_search_flag` (with a non-empty `BRAVE_SEARCH_API_KEY`) gates the
entire feature, and per-workspace opt-in (`brave_research_enabled`, off by
default) still gates every individual call. The flip is instantly revertible.

Promotion is **manual and evidence-based**, mirroring `ROUTE_PROMOTION.md`. The
flag is flipped only after (1) the offline corpus comparison shows grounding
helps or is neutral with no fail-open regressions, and (2) a dogfood pass
confirms fail-open, billing, consent, and the provenance indicator end-to-end.

## 1. Dry run (CI-safe, deterministic, no network)

```bash
cd backend
uv run python scripts/compare_brave_grounding.py --format markdown
```

The dry run proves the two things that must hold before anyone spends a call:

- **Corpus shape** — `docs/evals/golden_prompts/brave_grounding_corpus.json` is
  well-formed (unique ids, in-scope stages, non-empty problem statements, and a
  recency-neutral **control** case).
- **The fail-open identity** — for every in-scope stage, rendering the prompt
  with `research_context=""` is **byte-identical** to rendering with no research
  at all, and a non-empty block is actually injected. This is the structural
  guarantee behind "no fail-open regressions": a Brave miss (the common case)
  leaves generation unchanged.

It exits non-zero if either fails. It never calls a provider or Brave, so it is
safe to run in CI. It **cannot** measure whether grounding improves output —
that is the live step.

## 2. Live comparison (operator-run, off the production path)

```bash
cd backend
# Requires BRAVE_SEARCH_API_KEY and a provider key (e.g. ANTHROPIC_API_KEY).
# brave_search_flag does NOT need to be on — this gate runs before the flip.
uv run python scripts/compare_brave_grounding.py --live --format markdown \
  --output /tmp/brave_grounding_live.md
```

For each corpus case the harness:

1. Builds the **real** research block via the production assembly seams
   (`brave_client.fetch` + `research_service._assemble_block`: same header
   framing, sanitisation, prompt-injection guard, char bound, and http(s) URL
   allowlist) — but bypasses `fetch_context`, so **no credits, no quota, no DB,
   no COGS row** are touched. A live run spends real Brave API budget; that is
   the only way to measure real grounding.
2. Generates each in-scope stage (`spec`, then `plan` threaded off the just-
   generated spec) **twice** — grounding off vs on — through the real prompt
   modules and the LLM gateway. No StageVersion is persisted and no credit is
   charged.
3. Runs the two **deterministic** production gates on both arms —
   `validate_sections` and `validate_artifact_completeness` — and reports the
   per-stage verdict **helps / neutral / regressed** on the finding count.

The LLM critic is deliberately excluded (non-deterministic). The run passes when
**no stage regressed** and no case errored.

### What the live comparison can and cannot prove

It is a **single-sample, directional** gate, not a statistically rigorous A/B:

- The off/on arms are confounded by LLM sampling noise. The deterministic
  structural findings dampen this (they are stable functions of the artifact),
  and a **neutral** result passes by design, so the gate answers "does grounding
  hurt?" reliably and "does grounding help?" only directionally.
- The corpus is weighted toward **recency-sensitive** prompts (current framework
  and API versions, current best practices) so grounding *can* demonstrably
  help, plus one recency-neutral **control** where grounding is expected to be
  neutral — a guard against spuriously concluding grounding helps everywhere.

Re-run the live comparison a few times (or expand the corpus) before drawing a
conclusion; a one-off "regressed" on a single noisy sample is not disqualifying
if it does not reproduce.

## 3. Dogfood

With `brave_search_flag` on for **internal** workspaces only, opt a few in
(`PATCH /workspaces/{id}/research`) and verify end-to-end:

- **Fail-open** — a workspace with research off, or a query Brave grounds
  nothing for, generates exactly as before.
- **Billing** — a grounded generation debits the Brave credit once and writes
  exactly one `provider="brave"` COGS row; a cache hit is grounded but free.
- **Consent** — the opt-in toggle writes the `brave_research_toggled` audit row;
  a non-owner cannot flip it.
- **Provenance** — a grounded version shows its research block + http(s) source
  links in the version view; a non-grounded version shows nothing.

## 4. The flip

Once the comparison and dogfood are clean, set `BRAVE_SEARCH_FLAG=true` (the key
must already be set). No redeploy is required and the flip is instantly
revertible by setting it back to `false`; per-workspace opt-in still gates every
call. Record the decision below.

## Decision log

| Date | Decision | Evidence | Owner |
| --- | --- | --- | --- |
| _pending_ | _enable / hold_ | _link to live comparison output + dogfood notes_ | _owner_ |
