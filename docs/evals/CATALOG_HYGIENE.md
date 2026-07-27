# Model Catalog Hygiene & Core-Generation Tier Ladder

*Issue #26, Phase 5b — "latest-generation only" catalog hygiene and the normalized
per-provider cheap-tier floor.*

The model catalog (`backend/services/llm/model_catalog.py`) is the **single source
of truth** for provider model IDs, tiers, status, adapter shape, costs, and the
core-generation routing ladder. Every cost/route decision derives from it, so a
model swap is made in exactly one place. This document is the written policy for
keeping that catalog current and for the per-provider tier floor.

## 1. The core-generation tier ladder (the normalized floor)

`CORE_GENERATION_TIER_LADDER` declares, per provider, an ordered
**cheapest-viable-first → escalation** capability ladder. The live cheap-primary
policy is *derived* from it — `(primary, fallback) = (ladder[0], ladder[1])` via
`core_generation_tier_policy()` — and re-exported as
`stage_manager.CORE_GENERATION_TIER_POLICY`. There is no longer a hand-maintained
parallel dict to drift.

| Provider  | Ladder                         | Primary (runs by default) | Escalation |
| --------- | ------------------------------ | ------------------------- | ---------- |
| anthropic | `(small, mid, strong)`         | Haiku 4.5 (`small`)       | Sonnet 4.6 (`mid`) → Opus 4.8 (`strong`) |
| openai    | `(mini, mid, strong)`          | GPT-5.4 Mini (`mini`)     | GPT-5.4 (`mid`) → GPT-5.5 (`strong`) |
| google    | `(mid, strong)`                | Gemini 3.6 Flash (`mid`)  | (`strong` slot — no active model; surfaces directly) |

**"How far below mid is safe" is a per-provider decision, documented here:**

- **anthropic / openai** ship a viable core-gen default one tier *below* mid
  (Haiku, GPT-5.4 Mini), so their floor is `small` / `mini`.
- **google** deliberately floors at `mid` (Flash). Flash-Lite (`small`) is active
  but is **not** a core-gen default — it serves lightweight routing / judge / focused
  refine only. Google's `strong` escalation has no *active* model today (Pro Preview
  is preview-only), so a runtime/quality failure on Flash surfaces directly rather
  than retrying on a second model.

The deterministic complexity classifier (Phase 5.2) may **raise** the start to any
later tier in the ladder for predictably hard requests; it is a floor, never a
ceiling, and never lowers a route.

### Changing the ladder is a routing change — it rides the Phase-5 gate

Lowering any floor (e.g. Google → `small`) or otherwise changing which model
actually runs is **not** a Phase-5b edit. It requires the golden-corpus live
quality gate in [`ROUTE_PROMOTION.md`](ROUTE_PROMOTION.md): a cheap-vs-current
comparison over the expanded corpus showing cost drops with no quality / security /
traceability regression. Phase 5b only *normalized and documented* the existing
floor; it changed no route (a pinned test asserts the derived policy is
byte-identical to what Phase 5 shipped).

## 2. CI-enforced invariants

`validate_core_generation_ladder()` runs inside `validate_model_catalog()` (called
at catalog import and in `test_model_catalog.py`), so CI fails closed on:

- every required provider declaring a ladder of at least `(primary, fallback)`;
- each ladder tier being a valid core tier and the ladder **strictly increasing**
  in capability rank (an escalation can never lower capability);
- the **primary** tier resolving to exactly **one active, non-deprecated** core-gen
  default model — the model that actually runs.

Escalation tiers may legitimately resolve to no active model (Google `strong`), so
they are not required to resolve; if/when one ships active it is picked up
automatically. Deprecated and preview models are already barred from being defaults
by `_validate_entry`.

## 3. Periodic review (the "latest-generation only" hygiene step)

Run this review **quarterly** and **on any provider model release**:

1. **Inventory.** For each provider, confirm the active core-gen default (`small`/
   `mini`/`mid`) and the escalation (`mid`/`strong`) are still the newest
   generation that provider offers in that tier. Flag any model now superseded.
2. **Deprecate, don't delete.** When a provider ships a newer cheap/fast model
   (next Haiku / GPT-mini / Flash), mark the old entry `status="deprecated"`
   (keeps cost history + old-ID validation working) and add the new entry. Never
   rename a `model_id` in place.
3. **Eval before promote.** A new model becomes a core-gen **default** only after it
   passes the golden-corpus gate ([`ROUTE_PROMOTION.md`](ROUTE_PROMOTION.md)) for
   its operation/provider family — same gate as any tier/provider change.
4. **One-place swap.** Promotion is a single edit to the catalog entry's
   `default_operations` (and, if the tier floor moves, `CORE_GENERATION_TIER_LADDER`);
   downstream registries/routes derive automatically. Re-run
   `uv run pytest tests/test_model_catalog.py tests/test_llm_cost_registry.py -q`.
5. **Record.** Note the review date/outcome in the promotion review attached to the
   change (per `ROUTE_PROMOTION.md`).

## 4. Deferred (not built): cheapest-provider-first for platform keys

The plan's third Phase-5b lever — routing *platform-key* (non-BYO) core generation
to the cheapest-mid **provider** (Gemini 3.6 Flash, the cheapest mid by output)
rather than the user's nominal provider — is **intentionally not implemented**. It
changes *which provider* a user's output comes from, so it ships only behind both
golden-corpus quality parity **and** an explicit product decision. BYO-key users
always stay on their chosen provider. Until that product decision, `allow_cross_provider`
remains a fallback-only mechanism and no cheapest-provider-primary flag exists (dead
config that gates nothing is worse than this note). When it is taken up, it rides the
same `ROUTE_PROMOTION.md` gate.
