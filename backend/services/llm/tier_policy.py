"""Product-wide cheap-primary tier policy — the single source of truth.

Every artifact-generation feature selects its *starting* model tier through this
one helper, so "cheapest viable primary, escalate one tier on failure" is uniform
across the product and reverts through a single flag:

* the four core stages + full regenerate (``stage_manager``),
* the storyboard keynote (``storyboard_service``),
* increment generation (``increment_service``).

``core_cheap_primary`` (default ``True``) is that flag. Live, it returns the
provider's catalog-declared cheap floor escalating to ``mid``; flipped ``False``
it reverts every feature to the pre-cheap-swap *mid-first* default (``mid`` →
``strong``) in one toggle, no redeploy.

The per-provider cheap floor + its escalation are *derived* from the catalog
ladder (``core_generation_tier_policy`` → ``(ladder[0], ladder[1])``), so the
floor stays one catalog-validated decision rather than a constant duplicated per
call site. Lowering a provider's floor still rides the golden-corpus gate
(``docs/evals/ROUTE_PROMOTION.md``) because it changes which model actually runs.
"""

from __future__ import annotations

from config import settings
from services.llm.model_catalog import (
    CORE_GENERATION_TIER_LADDER,
    core_generation_tier_policy,
)

# Pre-cheap-swap default: start at ``mid`` and escalate to ``strong``. Used for
# any provider without a declared cheap ladder, and for *every* provider whenever
# the cheap-primary flag is off (the one-toggle revert target).
DEFAULT_TIER_POLICY: tuple[str, str] = ("mid", "strong")

# (primary_tier, escalation_tier) per provider when the cheap-primary policy is
# live. Derived from the catalog ladder so it cannot drift from the floor that
# CI validates (``validate_core_generation_ladder``).
CHEAP_PRIMARY_TIER_POLICY: dict[str, tuple[str, str]] = {
    provider: core_generation_tier_policy(provider)
    for provider in CORE_GENERATION_TIER_LADDER
}


def generation_tier_policy(provider: str) -> tuple[str, str]:
    """``(primary_tier, escalation_tier)`` for any artifact-generation feature.

    Honors the product-wide ``core_cheap_primary`` flag: live ⇒ the provider's
    cheap floor escalating to ``mid``; reverted ⇒ ``mid`` escalating to
    ``strong``. A provider without a declared cheap ladder falls back to the
    mid-first default, so an unrecognised provider is never silently downgraded.
    """
    if not settings.core_cheap_primary:
        return DEFAULT_TIER_POLICY
    return CHEAP_PRIMARY_TIER_POLICY.get(provider, DEFAULT_TIER_POLICY)
