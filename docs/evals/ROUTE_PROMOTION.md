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
resolution, deterministic validators, estimated usage/cost plumbing, and the
promotion gate configuration.

Promotion requires:

- Passing deterministic validators against the golden dataset.
- Average quality at or above the operation/provider gate.
- Human acceptance on sampled live outputs.
- Cost reduction at or above the configured target.
- No regression on security-sensitive or adversarial prompts.

Live provider evals must be run from an operator-approved branch with explicit
API keys and a saved JSON/Markdown report attached to the promotion review.
