"""Canonical LLM model catalog and routing policy.

This module is the single source of truth for provider model IDs, active
defaults, adapter API shape, and production rollout status. Provider-facing
catalogs and cost registries derive from this data so future model swaps are
made in one controlled place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProviderId = Literal["anthropic", "openai", "google", "openrouter"]
ModelTier = Literal["strong", "mid", "mini", "small", "judge", "embedding"]
ModelStatus = Literal["active", "preview", "deprecated"]
AdapterApi = Literal["messages", "responses", "chat_completions", "generate_content"]

# openrouter (issue #152) is a fourth provider reached through a thin
# chat_completions adapter over the openai SDK, pointed at
# https://openrouter.ai/api/v1. Day-one scope is open-weight models only
# (DeepSeek/GLM/Qwen) — frontier traffic stays on the native Anthropic
# adapter. Adding it here is inert until an operator opts in by adding
# "openrouter" to LLM_PROVIDER_PRIORITY and setting OPENROUTER_API_KEY; no
# call site defaults to it and platform_provider_priority() is entirely
# env-driven.
REQUIRED_PROVIDERS = frozenset({"anthropic", "openai", "google", "openrouter"})
MODEL_TIERS = frozenset({"strong", "mid", "mini", "small", "judge", "embedding"})
GENERATION_OPERATIONS = frozenset(
    {
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
        "refine.focused",
        "refine.section",
        "regenerate.full",
        "summary.create",
        "eval.score",
        # Storyboard keynote generation. Follows the same product-wide
        # cheap-primary→mid policy as core generation (issue #17 follow-up):
        # the cheap tier is the primary and mid is the quality-failure escalation.
        "storyboard.generate",
    }
)
CORE_GENERATION_OPERATIONS = (
    "spec.generate",
    "plan.generate",
    "harness.generate",
    "tasks.generate",
    "regenerate.full",
)
_LOW_REASONING_CORE_MODELS = {
    ("anthropic", "claude-haiku-4-5-20251001"),
    ("openai", "gpt-5.4-mini"),
    ("google", "gemini-3.6-flash"),
    # openrouter has NO row, and the reason is structural rather than an
    # oversight. Its ladder is two tiers, so deepseek-v4-flash (`mid`) is BOTH
    # the cheap primary AND `_CORE_ARTIFACT_TIER_POLICY`'s de-escalation target.
    # The other providers get that separation for free: their low-reasoning
    # model sits at `small`/`mini`, strictly BELOW the `mid` their artifact
    # policy falls back to, so this override can never touch a full-artifact
    # call. Here it would — and because core stages route through the artifact
    # policy rather than the cheap ladder, flash paired with a
    # CORE_GENERATION_OPERATION is reachable ONLY as the de-escalated retry.
    # Adding a row would therefore do nothing except run the rescue attempt for
    # a failed artifact at minimum reasoning, which is precisely the call that
    # can least afford it.
    # ``test_low_reasoning_never_degrades_an_artifact_fallback_tier`` pins this.
}

# --- Core-generation tier ladder (issue #26 Phase 5b) -------------------------
# The single, declarative source of truth for *how far below mid* each provider's
# core generation is allowed to start, and where it escalates. Phase 5 shipped a
# cheap-primary policy as an ad-hoc per-provider dict in ``stage_manager``; Phase
# 5b normalizes that into one validated ladder here so the per-provider floor is a
# deliberate, documented decision rather than a per-provider accident.
#
# Each tuple is ordered **cheapest viable core-gen tier → escalation tiers** and
# is read as a capability ladder, not a cost ladder. The runtime cheap-primary
# policy derives ``(primary, fallback) = (ladder[0], ladder[1])`` from it (see
# ``stage_manager.CORE_GENERATION_TIER_POLICY``); the deterministic complexity
# classifier (Phase 5.2) may raise the *start* to any later tier in the ladder.
#
# Per-provider viability rationale (the normalization itself — "how far below mid
# is safe here"):
#   * anthropic: ``small`` (Haiku 4.5) is a viable core-gen default → start one
#     tier below mid; escalate Sonnet 4.6 (mid) → Opus 4.8 (strong).
#   * openai: ``mini`` (GPT-5.4 Mini) is a viable core-gen default → start one
#     tier below mid; escalate GPT-5.4 (mid) → GPT-5.5 (strong).
#   * google: ``small`` (Flash-Lite) is **deliberately excluded** — it is not a
#     core-gen default (lightweight routing/judge only), so Google's floor is
#     ``mid`` (Flash). Its ``strong`` escalation has no *active* model today
#     (Pro Preview is preview-only), so a failure surfaces directly; the ladder
#     still declares ``strong`` as the escalation slot for when one ships.
#     NOTE: Google is now the platform's primary provider, so this "no active
#     strong tier" is load-bearing rather than theoretical — a core-gen failure
#     on Flash is surfaced, not retried. ``_runtime_fallback_route`` handles the
#     unresolvable escalation by returning None (it catches ``LLMRoutingError``),
#     so this degrades cleanly instead of raising.
#   * openrouter (issue #152): mirrors **Google's** shape, not anthropic/openai's.
#     The ladder is all-DeepSeek-V4 — ``mid`` (deepseek-v4-flash) → ``strong``
#     (deepseek-v4-pro) — and there is deliberately NO active ``small`` entry.
#     Two reasons this is a floor rather than an omission: (a) prompt caching on
#     OpenRouter exists only on DeepSeek's own upstream host and only on V4
#     models, so every tier must be a pinnable DeepSeek V4 slug or caching is
#     structurally zero (see ``upstream_providers``); (b) a ladder with no ``mid``
#     entry is unroutable, because ``tier_policy.generation_tier_policy`` returns
#     the mid-first ``DEFAULT_TIER_POLICY`` for EVERY provider whenever
#     ``core_cheap_primary`` is off, and ``raise_tier_to_floor`` can request
#     ``mid`` independently. Seating flash at ``mid`` keeps the one-toggle revert
#     and the complexity floor resolvable with no special-casing.
#
# Lowering any provider's floor (e.g. Google → ``small``) changes which model
# actually runs and therefore requires the Phase-5 golden-corpus live gate
# (``docs/evals/ROUTE_PROMOTION.md``) before it is edited here.
CORE_GENERATION_TIER_LADDER: dict[str, tuple[str, ...]] = {
    "anthropic": ("small", "mid", "strong"),
    "openai": ("mini", "mid", "strong"),
    "google": ("mid", "strong"),
    "openrouter": ("mid", "strong"),
}

# Capability ordering used only to assert each ladder is monotonically
# increasing. ``small``/``mini`` are cross-provider peers (a provider never lists
# both), so they share rank 0; ``mid`` < ``strong``. This is the catalog's own
# ordering for ladder hygiene and is independent of the classifier's floor rank.
_CORE_TIER_RANK: dict[str, int] = {"small": 0, "mini": 0, "mid": 1, "strong": 2}

PROVIDER_CAPABILITIES: dict[str, dict[str, bool]] = {
    "anthropic": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
    },
    "openai": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
    },
    "google": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
    },
    "openrouter": {
        "supports_streaming": True,
        # OpenRouter reports prompt_tokens_details.cached_tokens (reads) and
        # .cache_write_tokens (writes) on every chat-completions response for
        # models that support prefix caching, and _normalize_openrouter_usage
        # reads both — accounting is real. Explicit cache_control breakpoints
        # are deliberately NOT sent: the shipped ladder is DeepSeek-only, and
        # DeepSeek caching is automatic ("does not require any additional
        # configuration"). Breakpoints would only matter for a provider like
        # Alibaba Qwen, which is no longer in this catalog.
        "supports_prompt_cache_accounting": True,
        # No Message Batches integration in Phase 1 (issue #152 Phase 3 exit
        # criterion #4). eval_batch._REAL_BATCH_PROVIDERS excludes openrouter,
        # so batch evals fall back to the synchronous path automatically.
        "supports_batch": False,
        "supports_usage_tokens": True,
    },
}


@dataclass(frozen=True)
class ModelCatalogEntry:
    provider: ProviderId
    model_id: str
    display_name: str
    tier: ModelTier
    status: ModelStatus
    adapter_api: AdapterApi
    input_cost_per_million: float | None
    cached_input_cost_per_million: float | None
    output_cost_per_million: float | None
    max_context_tokens: int
    default_max_output_tokens: int
    recommended_operations: tuple[str, ...]
    default_operations: tuple[str, ...]
    supports_reasoning: bool = False
    supports_thinking: bool = False
    reasoning_effort: str | None = None
    thinking_level: str | None = None
    # Prompt-cache WRITE rates by TTL (issue #82). Anthropic prices cache
    # creation at a premium over base input (5m TTL 1.25x, 1h TTL 2x) while
    # only reads get the cached_input discount. None for providers whose
    # caching has no write premium (OpenAI/Google automatic prefix caching).
    cache_write_5m_cost_per_million: float | None = None
    cache_write_1h_cost_per_million: float | None = None
    rollout_notes: str = ""
    routing_priority: int = 100
    automatic_prompt_caching: bool = False
    prompt_cache_key: bool = False
    extended_prompt_cache_retention: bool = False
    cached_token_accounting: bool = False
    minimum_cacheable_input_tokens: int | None = None
    # Preferred upstream hosts for aggregator providers (openrouter, issue #152).
    # OpenRouter serves one model slug from many upstream hosts that differ in
    # quantisation, real output ceiling, price, cache-read price, and — decisively
    # — whether they support prefix caching at ALL (on deepseek-v4-flash, 1 of 19
    # hosts does). The adapter emits matching ``provider.order`` and
    # ``provider.only`` lists, so only the evaluated hosts may serve the request;
    # the durable pipeline owns recovery to another model/provider.
    #
    # Empty tuple = no host restriction. Non-empty = allow only these hosts.
    upstream_providers: tuple[str, ...] = ()

    def to_registry_config(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "tier": self.tier,
            "status": self.status,
            "adapter_api": self.adapter_api,
            "input_cost_per_million": self.input_cost_per_million,
            "cached_input_cost_per_million": self.cached_input_cost_per_million,
            "cache_write_5m_cost_per_million": self.cache_write_5m_cost_per_million,
            "cache_write_1h_cost_per_million": self.cache_write_1h_cost_per_million,
            "output_cost_per_million": self.output_cost_per_million,
            "max_context_tokens": self.max_context_tokens,
            "default_max_output_tokens": self.default_max_output_tokens,
            "recommended_operations": list(self.recommended_operations),
            "default_operations": list(self.default_operations),
            "supports_reasoning": self.supports_reasoning,
            "supports_thinking": self.supports_thinking,
            "reasoning_effort": self.reasoning_effort,
            "thinking_level": self.thinking_level,
            "rollout_notes": self.rollout_notes,
            "routing_priority": self.routing_priority,
            "automatic_prompt_caching": self.automatic_prompt_caching,
            "prompt_cache_key": self.prompt_cache_key,
            "extended_prompt_cache_retention": self.extended_prompt_cache_retention,
            "cached_token_accounting": self.cached_token_accounting,
            "minimum_cacheable_input_tokens": self.minimum_cacheable_input_tokens,
        }


MODEL_CATALOG: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-opus-5",
        display_name="Claude Opus 5",
        tier="strong",
        status="active",
        adapter_api="messages",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        cache_write_5m_cost_per_million=6.25,
        cache_write_1h_cost_per_million=10.0,
        output_cost_per_million=25.0,
        max_context_tokens=1_000_000,
        # Opus 5's real output ceiling is 128K. 64000 is the established
        # cross-provider core-gen convention (see the GPT-5.5 entry): it sits
        # below every current-gen model's real cap, so a >cap max_tokens can
        # never 400, and it still gives the doubling limit-stop repair genuine
        # headroom above the 49152 first-attempt budget.
        default_max_output_tokens=64000,
        # The four core stages + regenerate.full are RECOMMENDED but NOT
        # defaults. Route resolution (routing._model_for_operation) prefers a
        # tier's flagged default and otherwise falls back to any active model
        # recommending the operation, so Opus 5 wins the strong tier via
        # ``selection_reason="active_same_tier"`` — which is how the previous
        # frontier entry already behaved. Leaving default_operations empty keeps
        # validate_model_catalog's "exactly one active core-gen default per
        # provider" invariant satisfied by Haiku 4.5, which is still the primary
        # for the SHARED cheap ladder that storyboard/increment read.
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "storyboard.generate"),
        default_operations=(),
        supports_reasoning=True,
        # HIGH, not the previously-shipped medium, as of 2026-08-06. Core stages
        # are bound by a per-call attempt cap inside a longer durable run budget,
        # and high-effort reasoning tokens are spent before any
        # visible output, which is exactly what made medium the safer default
        # when the cap was a tighter 240s.
        #
        # This move is a deliberate quality-over-margin trade, NOT a re-measured
        # one: it was made after a production spec generation was judged not up
        # to the mark at medium effort, without first collecting a fresh
        # per-chunk wall-clock sample at high effort the way the 2026-07-30
        # medium measurement (generation 65fe5f10: ~38 visible tok/s on a dense
        # spec chunk) was collected. The call cap was widened from 240 to 270 in
        # the same change specifically to give high-effort reasoning more room
        # before the watchdog kills a chunk and discards its partial output —
        # but the chunk length targets in ``_chunk_length_target``
        # (stage_manager.py) are still sized against the ~145 chars/s MEDIUM
        # throughput figure, not a high-effort one. If chunks start timing out
        # (watch ``provider_stopped_by_limit`` / hard_cap kills in the
        # generation route logs) or the mid-tier Sonnet-5 fallback fires more
        # than before, that is the throughput assumption being wrong — capture a
        # real high-effort measurement and retarget both this value and the
        # chunk length targets together, the same way the medium figure was
        # originally derived.
        reasoning_effort="high",
        rollout_notes=(
            "Anthropic full-artifact generation primary: the four core ASDD "
            "stages, full regenerate and the harness gap-patch, in both standard "
            "and Demo Day mode. Resolves via active_same_tier (no default_operations "
            "claim) — route logs show that selection_reason, not active_default. "
            "A hard runtime failure retries down once on Sonnet 5 (mid). Runs at "
            "effort=high (2026-08-06) against the configured per-call cap — see the "
            "reasoning_effort comment for the unmeasured-throughput caveat."
        ),
        routing_priority=1,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        tier="mid",
        status="active",
        adapter_api="messages",
        # INTRODUCTORY PRICING — $2/$10 per MTok applies only through
        # 2026-08-31, after which Anthropic's standard Sonnet 5 rate of
        # $3/$15 (cached 0.3, cache-write 3.75/6.0) takes effect. Update this
        # entry on 2026-09-01 or the cost ledger silently under-reports.
        input_cost_per_million=2.0,
        cached_input_cost_per_million=0.2,
        cache_write_5m_cost_per_million=2.5,
        cache_write_1h_cost_per_million=4.0,
        output_cost_per_million=10.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=64000,
        # The core ops are recommended so Sonnet 5 can serve as the Opus 5
        # retry-down target after a hard core-generation failure; storyboard
        # keeps it as the cheap-primary quality-failure escalation target.
        #
        # ``refine.focused`` is recommended here to close a latent routing hole:
        # Demo Day floors ALL generation at the mid tier, but no Anthropic mid
        # model recommended focused refine, so the resolver found nothing for
        # Anthropic and silently continued to the next PROVIDER (it fell through
        # to Gemini). That was invisible while Google was primary; with Anthropic
        # primary and a placeholder Google key it would resolve no route at all
        # and raise. Standard mode is unaffected — its cheap policy resolves the
        # small tier first and never consults mid for this operation.
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "storyboard.generate",
        ),
        default_operations=("refine.section", "storyboard.generate"),
        supports_reasoning=True,
        reasoning_effort="medium",
        rollout_notes=(
            "Anthropic mid tier: the Opus 5 retry-down target for full-artifact "
            "generation, the section-refinement default, and the storyboard "
            "quality-failure escalation target (issue #17 follow-up). "
            "Introductory pricing expires 2026-08-31 — see the cost comment."
        ),
        routing_priority=20,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        tier="strong",
        status="deprecated",
        adapter_api="messages",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        cache_write_5m_cost_per_million=6.25,
        cache_write_1h_cost_per_million=10.0,
        output_cost_per_million=25.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=64000,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes=(
            "Superseded by Claude Opus 5. Retained (deprecate-don't-delete) so "
            "historical llm_cost_events rows keep resolving their pricing."
        ),
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        tier="mid",
        status="deprecated",
        adapter_api="messages",
        input_cost_per_million=3.0,
        cached_input_cost_per_million=0.3,
        cache_write_5m_cost_per_million=3.75,
        cache_write_1h_cost_per_million=6.0,
        output_cost_per_million=15.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=64000,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes=(
            "Superseded by Claude Sonnet 5. Retained (deprecate-don't-delete) so "
            "historical llm_cost_events rows keep resolving their pricing."
        ),
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        tier="small",
        status="active",
        adapter_api="messages",
        input_cost_per_million=1.0,
        cached_input_cost_per_million=0.1,
        cache_write_5m_cost_per_million=1.25,
        cache_write_1h_cost_per_million=2.0,
        output_cost_per_million=5.0,
        max_context_tokens=200_000,
        # This model's true output ceiling is 64K. It was previously capped at
        # 32768 to "fit" the 24576 budget, but with reasoning billed against
        # max_tokens a dense chunk (reasoning + ~8 sections) routinely exceeded
        # 32768 — and the doubling-repair clamped to the same 32768 ceiling, so
        # the repair was DOOMED and nearly every generation truncated with
        # provider_stopped_by_limit. Raised to the real 64K so the first attempt
        # and the doubling repair both have genuine headroom.
        default_max_output_tokens=64000,
        # storyboard.generate added (recommended + default) so the cheap primary
        # carries the keynote too — storyboard now follows the same
        # cheap-primary→mid policy as core generation (issue #17 follow-up).
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
            "storyboard.generate",
        ),
        default_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
            "storyboard.generate",
        ),
        supports_reasoning=True,
        # Haiku 4.5 reasons, but it does NOT accept the `effort` request
        # parameter: sending any value 400s with "This model does not support
        # the effort parameter", which hard-failed every judge/eval/refine call
        # on this model. `supports_reasoning` stays True (it does think); the
        # None here is specifically "no effort knob to send". Do not restore a
        # value without re-probing the live API.
        reasoning_effort=None,
        rollout_notes=(
            "Primary Anthropic core ASDD generation default — cheapest viable "
            "current-generation model — plus lightweight judge and focused refine."
        ),
        routing_priority=30,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-opus-4-7",
        display_name="Claude Opus 4.7",
        tier="strong",
        status="deprecated",
        adapter_api="messages",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        cache_write_5m_cost_per_million=6.25,
        cache_write_1h_cost_per_million=10.0,
        output_cost_per_million=25.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-5.5",
        display_name="GPT-5.5",
        tier="strong",
        status="active",
        adapter_api="responses",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        output_cost_per_million=30.0,
        max_context_tokens=1_000_000,
        # 64K matches the cross-provider core-gen ceiling. Every current-gen
        # frontier model caps output well above this (OpenAI GPT-5.x: 128K;
        # Gemini Flash: 65536; Anthropic Haiku 4.5 / Sonnet 4.6: 64K), so 64000
        # is safely below the real cap and never produces a >cap max_tokens 400.
        # The old 32768 clamped the doubling repair to the same value the first
        # attempt failed at, so the repair was doomed and chunks truncated.
        default_max_output_tokens=64000,
        # Core generation ops are RECOMMENDED but NOT defaults — the same shape
        # Opus 5 uses. This is now OpenAI's full-artifact PRIMARY (the
        # _CORE_ARTIFACT_TIER_POLICY strong slot), reached whenever Anthropic is
        # unconfigured or its circuit is open, and it wins the strong tier via
        # ``selection_reason="active_same_tier"``. Leaving default_operations
        # empty keeps validate_model_catalog's "exactly one active core-gen
        # default per provider" invariant satisfied by GPT-5.4 Mini, which is
        # still the primary for the SHARED cheap ladder that storyboard and
        # increment read.
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "storyboard.generate"),
        default_operations=(),
        supports_reasoning=True,
        # Medium, matching Opus 5 and for the identical reason: core stages are
        # bound by a per-call cap inside the durable generation deadline
        # and high-effort reasoning tokens are spent before any visible output.
        # This model is the FALLBACK artifact primary, so a high-effort timeout
        # here would fail precisely when Anthropic is already down. Raising it
        # back to high requires re-measuring per-chunk wall-clock first.
        reasoning_effort="medium",
        rollout_notes=(
            "OpenAI full-artifact generation primary: the four core ASDD "
            "stages, full regenerate and the harness gap-patch, in both standard "
            "and Demo Day mode, reached when Anthropic is unconfigured or its "
            "circuit is open. Resolves via active_same_tier. A hard runtime "
            "failure retries down once on GPT-5.4 (mid). Also the storyboard "
            "escalation target when reverted to mid-first."
        ),
        routing_priority=1,
        automatic_prompt_caching=True,
        prompt_cache_key=True,
        extended_prompt_cache_retention=True,
        cached_token_accounting=True,
        minimum_cacheable_input_tokens=1024,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-5.4",
        display_name="GPT-5.4",
        tier="mid",
        status="active",
        adapter_api="responses",
        input_cost_per_million=2.5,
        cached_input_cost_per_million=0.25,
        output_cost_per_million=15.0,
        max_context_tokens=1_000_000,
        # 64K cross-provider core-gen ceiling (real cap is far higher) — see the
        # GPT-5.5 entry. Gives the limit-stop repair real headroom.
        default_max_output_tokens=64000,
        # storyboard.generate kept here so GPT-5.4 is the mid-tier escalation
        # target when the cheap storyboard primary (GPT-5.4 Mini) fails a gate.
        # refine.focused mirrors the Anthropic mid entry — without it the Demo
        # Day mid floor resolves no OpenAI model for focused refine and falls
        # through to another provider (see the Sonnet 5 entry).
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "storyboard.generate",
        ),
        default_operations=("refine.section", "storyboard.generate"),
        supports_reasoning=True,
        reasoning_effort="medium",
        rollout_notes=(
            "OpenAI mid-tier core ASDD generation escalation (one-shot retry "
            "after a GPT-5.4 Mini failure), section refinement default, and "
            "storyboard quality-failure escalation target (issue #17 follow-up)."
        ),
        routing_priority=20,
        automatic_prompt_caching=True,
        prompt_cache_key=True,
        extended_prompt_cache_retention=True,
        cached_token_accounting=True,
        minimum_cacheable_input_tokens=1024,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-5.4-mini",
        display_name="GPT-5.4 Mini",
        tier="mini",
        status="active",
        adapter_api="responses",
        input_cost_per_million=0.75,
        cached_input_cost_per_million=0.075,
        output_cost_per_million=4.5,
        max_context_tokens=400_000,
        # 64K cross-provider core-gen ceiling. GPT-5.x mini-tier models cap
        # output at 128K, well above 64000, so this never 400s on a >cap
        # max_tokens. As the cheap OpenAI primary, this carries the full 49152
        # first-attempt budget with the limit-stop repair doubling into 64000.
        default_max_output_tokens=64000,
        # storyboard.generate added (recommended + default) so the cheap primary
        # carries the keynote too — storyboard now follows the same
        # cheap-primary→mid policy as core generation (issue #17 follow-up).
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
            "storyboard.generate",
        ),
        default_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
            "storyboard.generate",
        ),
        supports_reasoning=True,
        # Medium (not low) effort: as the core-gen primary, Mini must reason
        # hard enough to clear the completeness/critic gates.  Per-model field,
        # so this also lifts its judge/eval/non-core uses to medium.
        reasoning_effort="medium",
        rollout_notes=(
            "Primary OpenAI core ASDD generation default — cheapest viable "
            "current-generation model — plus lightweight non-core operations."
        ),
        routing_priority=30,
        automatic_prompt_caching=True,
        prompt_cache_key=True,
        extended_prompt_cache_retention=True,
        cached_token_accounting=True,
        minimum_cacheable_input_tokens=1024,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4o",
        display_name="GPT-4o",
        tier="strong",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=2.5,
        cached_input_cost_per_million=1.25,
        output_cost_per_million=10.0,
        max_context_tokens=128_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
        automatic_prompt_caching=True,
        prompt_cache_key=True,
        extended_prompt_cache_retention=True,
        cached_token_accounting=True,
        minimum_cacheable_input_tokens=1024,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        tier="mini",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=0.15,
        cached_input_cost_per_million=0.075,
        output_cost_per_million=0.6,
        max_context_tokens=128_000,
        default_max_output_tokens=4096,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
        automatic_prompt_caching=True,
        prompt_cache_key=True,
        extended_prompt_cache_retention=True,
        cached_token_accounting=True,
        minimum_cacheable_input_tokens=1024,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="o1-preview",
        display_name="o1 Preview",
        tier="strong",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=15.0,
        cached_input_cost_per_million=7.5,
        output_cost_per_million=60.0,
        max_context_tokens=128_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
        automatic_prompt_caching=True,
        prompt_cache_key=True,
        extended_prompt_cache_retention=True,
        cached_token_accounting=True,
        minimum_cacheable_input_tokens=1024,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        # Flash is Google's fast/cheap core-generation model, so it sits on
        # the mid tier — the primary core-generation route. Google has no
        # active strong-tier escalation model; a runtime failure surfaces
        # directly instead of retrying on a second model.
        # storyboard.generate: Google has no sub-Flash core-gen model, so its
        # cheap-primary policy floors at mid — Flash is the storyboard primary
        # for Google, exactly as it is for core generation. No active strong
        # escalation exists (Pro Preview is preview-only), so a storyboard
        # quality failure surfaces directly — consistent with core gen.
        tier="mid",
        status="active",
        adapter_api="generate_content",
        input_cost_per_million=1.5,
        cached_input_cost_per_million=0.15,
        output_cost_per_million=7.5,
        max_context_tokens=1_048_576,
        # 64K cross-provider core-gen ceiling. Gemini Flash caps output at
        # 65536, so 64000 sits just below the real cap (no >cap max_tokens 400)
        # while giving Google's cheap primary the full 49152 first-attempt
        # budget and a limit-stop repair that doubles into 64000.
        default_max_output_tokens=64000,
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "storyboard.generate",
        ),
        default_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "storyboard.generate",
        ),
        supports_thinking=True,
        # Unchanged from the Gemini 3.5 Flash entry this supersedes, so the
        # effective per-operation thinking policy does not drift with the model
        # swap: core generation is lowered to "low" by
        # _LOW_REASONING_CORE_MODELS when core_generation_low_reasoning is on
        # (the shipped default), and every other operation keeps "high".
        thinking_level="high",
        rollout_notes=(
            "Stable Gemini 3-family core ASDD generation default and "
            "storyboard primary on Google (no sub-Flash core-gen model). "
            "Platform core-generation primary since the Gemini cutover."
        ),
        routing_priority=1,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash-Lite",
        tier="small",
        status="active",
        adapter_api="generate_content",
        # Real published rates. The superseded 3.1 Flash-Lite entry carried
        # None for all three, which makes estimate_cost_usd() return None and
        # silently records a zero-cost ledger row for every judge/eval call —
        # harmless while Google was unconfigured, wrong now that it is the
        # platform provider and owns the whole judge/eval path.
        input_cost_per_million=0.30,
        cached_input_cost_per_million=0.03,
        output_cost_per_million=2.50,
        max_context_tokens=1_048_576,
        default_max_output_tokens=8192,
        recommended_operations=("refine.focused", "summary.create", "eval.score"),
        default_operations=("refine.focused", "summary.create", "eval.score"),
        supports_thinking=True,
        # "minimal" (this model's own documented default), NOT "low". Gemini
        # bills thought tokens against max_output_tokens, and every call site
        # that lands here runs on a tight budget (eval.score 1024,
        # call_judge_model 2048, summary.create 2048). At a higher thinking
        # level a reasoning burst consumes the whole budget and the response
        # comes back with finish_reason=MAX_TOKENS and empty text. Minimal is
        # also what Google recommends for routing/classification/extraction —
        # exactly what these judge call sites do.
        thinking_level="minimal",
        rollout_notes="Stable Gemini 3-family lightweight routing and judge model.",
        routing_priority=30,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        tier="mid",
        status="deprecated",
        adapter_api="generate_content",
        input_cost_per_million=1.5,
        cached_input_cost_per_million=0.15,
        output_cost_per_million=9.0,
        max_context_tokens=1_048_576,
        default_max_output_tokens=64000,
        recommended_operations=("summary.create",),
        default_operations=(),
        supports_thinking=True,
        thinking_level="high",
        rollout_notes=(
            "Superseded by Gemini 3.6 Flash. Retained (deprecate-don't-delete) "
            "so historical cost-ledger and stage rows still resolve a catalog "
            "entry and can be priced."
        ),
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite",
        tier="small",
        status="deprecated",
        adapter_api="generate_content",
        input_cost_per_million=None,
        cached_input_cost_per_million=None,
        output_cost_per_million=None,
        max_context_tokens=1_048_576,
        default_max_output_tokens=4096,
        recommended_operations=("summary.create",),
        default_operations=(),
        supports_thinking=True,
        thinking_level="low",
        rollout_notes=(
            "Superseded by Gemini 3.5 Flash-Lite. Retained "
            "(deprecate-don't-delete) for historical row resolution."
        ),
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.1-pro-preview",
        display_name="Gemini 3.1 Pro Preview",
        tier="strong",
        status="preview",
        adapter_api="generate_content",
        input_cost_per_million=None,
        cached_input_cost_per_million=None,
        output_cost_per_million=None,
        max_context_tokens=1_048_576,
        default_max_output_tokens=8192,
        # storyboard.generate included so this model appears as a candidate for
        # Phase 1 strong-tier escalation once it reaches active status. In
        # preview, _model_for_operation skips it (status != "active"), so
        # resolve_llm_route raises LLMRoutingError and Google surfaces directly.
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "storyboard.generate"),
        default_operations=(),
        supports_thinking=True,
        thinking_level="high",
        rollout_notes="Preview only; not a production default without eval evidence.",
        routing_priority=50,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3-flash-preview",
        display_name="Gemini 3 Flash Preview",
        tier="mid",
        status="preview",
        adapter_api="generate_content",
        input_cost_per_million=None,
        cached_input_cost_per_million=None,
        output_cost_per_million=None,
        max_context_tokens=1_048_576,
        default_max_output_tokens=8192,
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "refine.section"),
        default_operations=(),
        supports_thinking=True,
        thinking_level="high",
        rollout_notes="Preview only; not a production default without eval evidence.",
        routing_priority=60,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-1.5-pro",
        display_name="Gemini 1.5 Pro",
        tier="strong",
        status="deprecated",
        adapter_api="generate_content",
        input_cost_per_million=1.25,
        cached_input_cost_per_million=0.125,
        output_cost_per_million=5.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-1.5-flash",
        display_name="Gemini 1.5 Flash",
        tier="small",
        status="deprecated",
        adapter_api="generate_content",
        input_cost_per_million=0.075,
        cached_input_cost_per_million=0.01875,
        output_cost_per_million=0.3,
        max_context_tokens=1_000_000,
        default_max_output_tokens=4096,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    # --- openrouter (issue #152) --------------------------------------------
    # A fourth provider reached through a thin chat_completions adapter over
    # the openai SDK, base_url=https://openrouter.ai/api/v1.
    #
    # The ladder is all DeepSeek V4 and prefers DeepSeek's own endpoint via
    # ``upstream_providers=("deepseek",)`` while retaining same-model endpoint
    # fallback for availability. Verified against the live endpoints API:
    #
    #   * Prompt caching exists on exactly ONE upstream host. On
    #     deepseek-v4-flash, ``supports_implicit_caching`` is true for 1 of 19
    #     hosts (DeepSeek's own) and false for the other 18; the retired
    #     deepseek-v3.2 (0/14 hosts) and z-ai/glm-5.2 (0/32) supported it
    #     nowhere at all, and qwen3.8-max needs explicit cache_control
    #     breakpoints this adapter deliberately does not send. An unpinned
    #     route therefore has structurally ZERO cache hit rate, and prefix
    #     caching is per-host anyway, so consecutive chunks of one stage
    #     landing on different hosts share nothing.
    #   * Rates below are the preferred host's, not the model alias's. These
    #     differ materially: deepseek-v4-pro bills $1.168/$2.336 at the alias
    #     and $0.435/$0.870 on DeepSeek's own host. Reading alias pricing into
    #     the catalog is how the retired glm-5.2 entry came to understate
    #     output cost by 64%. ``scripts/check_openrouter_catalog_drift.py``
    #     re-checks these against the preferred endpoint.
    #   * The real output ceiling varies 32x across hosts (32,768 → 1,048,576
    #     on flash; 7,168 → 163,840 on the retired v3.2) against the 32,768 the
    #     pipeline sends, so an unpinned route can hit a host that truncates.
    #
    # cache_write_5m is set to the BASE INPUT rate rather than left None. That
    # is arithmetically neutral for DeepSeek — it charges cache misses at the
    # normal input rate with no write premium — while avoiding the trap in
    # estimate_cost_usd(): a None rate with non-zero write tokens makes it
    # return None and the ledger records NO cost for the call.
    # cache_write_1h stays None: OpenRouter carries no Anthropic-style
    # ephemeral_5m/1h breakdown, so _cache_write_ttl_split attributes 100% of
    # writes to the 5m bucket and the 1h rate can never be consulted.
    ModelCatalogEntry(
        provider="openrouter",
        model_id="deepseek/deepseek-v4-flash",
        display_name="DeepSeek V4 Flash (OpenRouter)",
        tier="mid",
        status="active",
        adapter_api="chat_completions",
        upstream_providers=("deepseek",),
        input_cost_per_million=0.14,
        cached_input_cost_per_million=0.0028,
        cache_write_5m_cost_per_million=0.14,
        output_cost_per_million=0.28,
        max_context_tokens=1_048_576,
        # The pinned DeepSeek host's real ceiling is 384,000. 64000 matches the
        # cross-provider core-gen convention (see the Opus 5 / GPT-5.5 entries):
        # comfortably below the real cap, so a >cap max_tokens can never 400,
        # and the doubling limit-stop repair still has genuine headroom.
        default_max_output_tokens=64000,
        # Shape mirrors Gemini 3.6 Flash: this provider's ladder floor is `mid`,
        # so the mid entry — not a `small` one — is the sole active core-gen
        # default (validate_model_catalog's "exactly one active default per
        # (provider, core op)" invariant) AND carries the cheap ladder's
        # non-core operations.
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
            "storyboard.generate",
        ),
        default_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
            "storyboard.generate",
        ),
        # Live OpenRouter metadata (2026-08-15) accepts only high/xhigh effort
        # and reports mandatory=false. ``medium`` depends on implicit gateway
        # remapping rather than the model's advertised contract. It deliberately
        # remains exempt from _LOW_REASONING_CORE_MODELS because this mid-tier
        # model is also the full-artifact rescue route; the registry comment
        # documents that guard.
        supports_reasoning=True,
        reasoning_effort="high",
        rollout_notes=(
            "Primary openrouter core ASDD generation default and judge/eval "
            "model. Pinned to DeepSeek's own upstream host — the only host "
            "serving this slug that supports prefix caching. Inert until an "
            "operator adds 'openrouter' to LLM_PROVIDER_PRIORITY."
        ),
        routing_priority=20,
    ),
    ModelCatalogEntry(
        provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        display_name="DeepSeek V4 Pro (OpenRouter)",
        tier="strong",
        status="active",
        adapter_api="chat_completions",
        upstream_providers=("deepseek",),
        input_cost_per_million=0.435,
        cached_input_cost_per_million=0.003625,
        cache_write_5m_cost_per_million=0.435,
        output_cost_per_million=0.87,
        max_context_tokens=1_048_576,
        # Pinned DeepSeek host's real ceiling is 384,000; 64000 convention.
        default_max_output_tokens=64000,
        # RECOMMENDED but NOT a default — same shape as Opus 5 / GPT-5.5: wins
        # the strong tier via selection_reason="active_same_tier", leaving
        # default_operations empty so deepseek-v4-flash stays the sole core-gen
        # default holder. Deliberately does NOT recommend refine.focused /
        # refine.section (neither does Opus 5 or GPT-5.5) — those stay on the
        # cheap ladder and always resolve flash (mid) first.
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "storyboard.generate"),
        default_operations=(),
        supports_reasoning=True,
        # The live gateway currently advertises only high/xhigh. Use the lower
        # valid value; throughput remains explicitly unmeasured and is protected
        # by the per-call watchdog + independent-provider fallback.
        reasoning_effort="high",
        rollout_notes=(
            "openrouter full-artifact generation primary (reached only once an "
            "operator opts 'openrouter' into LLM_PROVIDER_PRIORITY). Resolves "
            "via active_same_tier. A hard runtime failure retries down once on "
            "deepseek-v4-flash (mid)."
        ),
        routing_priority=1,
    ),
    # Retired 2026-08-14 (deprecate-don't-delete, docs/evals/CATALOG_HYGIENE.md).
    # All three were replaced by the all-DeepSeek-V4 ladder above. Reasons, in
    # order of severity: none of them could cache (glm-5.2 supports implicit
    # caching on 0 of 32 hosts, deepseek-v3.2 on 0 of 14, and qwen3.8-max needs
    # explicit cache_control breakpoints); their catalog rates were read from
    # the model alias rather than a pinned host, which is how glm-5.2 came to
    # understate output cost by 64% ($1.536 recorded vs $2.52 live); and
    # deepseek-v3.2 had upstream hosts capping output at 7,168 tokens against
    # the 32,768 the pipeline sends.
    ModelCatalogEntry(
        provider="openrouter",
        model_id="deepseek/deepseek-v3.2",
        display_name="DeepSeek V3.2 (OpenRouter)",
        tier="small",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=0.269,
        cached_input_cost_per_million=0.1345,
        cache_write_5m_cost_per_million=0.269,
        output_cost_per_million=0.40,
        max_context_tokens=163_840,
        default_max_output_tokens=64000,
        recommended_operations=(*CORE_GENERATION_OPERATIONS,),
        default_operations=(),
        # Corrected: the live models API lists `reasoning` and
        # `include_reasoning` in this model's supported_parameters. The
        # original entry declared supports_reasoning=False, which was the
        # stated basis for omitting an _LOW_REASONING_CORE_MODELS row. Only
        # the `reasoning_effort` half of that claim was true.
        supports_reasoning=True,
        reasoning_effort=None,
        rollout_notes=(
            "Deprecated 2026-08-14: superseded by deepseek-v4-flash. No "
            "upstream host serving this slug supports prefix caching, and "
            "some cap output at 7,168 tokens."
        ),
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="openrouter",
        model_id="z-ai/glm-5.2",
        display_name="GLM-5.2 (OpenRouter)",
        tier="mid",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=0.40,
        cached_input_cost_per_million=0.08,
        cache_write_5m_cost_per_million=0.40,
        output_cost_per_million=2.52,
        max_context_tokens=1_048_576,
        default_max_output_tokens=64000,
        recommended_operations=(*CORE_GENERATION_OPERATIONS,),
        default_operations=(),
        supports_reasoning=True,
        reasoning_effort="medium",
        rollout_notes=(
            "Deprecated 2026-08-14: superseded by deepseek-v4-flash. Supports "
            "prefix caching on 0 of 32 upstream hosts. Rates corrected to the "
            "live values on retirement (output was recorded as 1.536)."
        ),
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="openrouter",
        model_id="qwen/qwen3.8-max",
        display_name="Qwen3.8 Max (OpenRouter)",
        tier="strong",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=2.00,
        cached_input_cost_per_million=0.25,
        cache_write_5m_cost_per_million=2.50,
        output_cost_per_million=6.00,
        max_context_tokens=1_000_000,
        default_max_output_tokens=64000,
        recommended_operations=(*CORE_GENERATION_OPERATIONS,),
        default_operations=(),
        supports_reasoning=True,
        reasoning_effort="medium",
        rollout_notes=(
            "Deprecated 2026-08-14: superseded by deepseek-v4-pro. Alibaba "
            "Qwen requires explicit cache_control breakpoints, which this "
            "adapter does not send, so it could never cache. Note it DOES "
            "carry a real cache-write premium ($2.50/M vs $2.00 base) — the "
            "original entry assumed OpenRouter had no write premiums."
        ),
        routing_priority=500,
    ),
)


def iter_model_entries(provider: str | None = None) -> tuple[ModelCatalogEntry, ...]:
    if provider is None:
        return MODEL_CATALOG
    return tuple(entry for entry in MODEL_CATALOG if entry.provider == provider)


def model_entry(provider: str, model_id: str) -> ModelCatalogEntry:
    for entry in MODEL_CATALOG:
        if entry.provider == provider and entry.model_id == model_id:
            return entry
    raise ValueError(f"Unknown model for provider {provider!r}: {model_id!r}")


def valid_model_ids(provider: str) -> set[str]:
    _require_provider(provider)
    return {entry.model_id for entry in iter_model_entries(provider)}


def public_model_list(provider: str) -> list[dict[str, str]]:
    _require_provider(provider)
    return [
        {"id": entry.model_id, "name": entry.display_name}
        for entry in iter_model_entries(provider)
    ]


def default_model_for_operation(provider: str, operation: str) -> str:
    candidates = [
        entry
        for entry in iter_model_entries(provider)
        if entry.status == "active" and operation in entry.default_operations
    ]
    if not candidates:
        raise ValueError(
            "No active default model for "
            f"provider={provider!r}, operation={operation!r}"
        )
    return sorted(candidates, key=lambda entry: entry.routing_priority)[0].model_id


def build_provider_capability_registry() -> dict[str, dict[str, Any]]:
    validate_model_catalog()
    registry: dict[str, dict[str, Any]] = {}
    for provider, capabilities in PROVIDER_CAPABILITIES.items():
        registry[provider] = {**capabilities, "models": {}}
    for entry in MODEL_CATALOG:
        registry[entry.provider]["models"][entry.model_id] = entry.to_registry_config()
    return registry


def model_max_output_tokens(provider: str, model_id: str) -> int:
    """The hard per-call output-token ceiling for a catalog model.

    Used to clamp per-operation output budgets: reasoning tokens share this
    budget with visible artifact tokens on frontier models, so the ceiling
    must be generous enough that thinking never starves the artifact.
    """
    return model_entry(provider, model_id).default_max_output_tokens


def _core_generation_low_reasoning_enabled() -> bool:
    try:
        from config import settings  # noqa: PLC0415

        return bool(settings.core_generation_low_reasoning)
    except Exception:
        return False


def model_request_policy(
    provider: str,
    model_id: str,
    operation: str | None = None,
) -> dict[str, Any]:
    entry = model_entry(provider, model_id)
    reasoning_effort = entry.reasoning_effort
    thinking_level = entry.thinking_level
    if (
        operation in CORE_GENERATION_OPERATIONS
        and (provider, model_id) in _LOW_REASONING_CORE_MODELS
        and _core_generation_low_reasoning_enabled()
    ):
        # Gate on the effort value, not on `supports_reasoning`: this override
        # *lowers* an effort the model already accepts, and must never introduce
        # one on a model that rejects the parameter (Haiku 4.5 reasons but has
        # no effort knob — see its catalog entry).
        if entry.reasoning_effort is not None:
            reasoning_effort = "low"
        if entry.supports_thinking:
            thinking_level = "low"
    return {
        "adapter_api": entry.adapter_api,
        "supports_reasoning": entry.supports_reasoning,
        "supports_thinking": entry.supports_thinking,
        "reasoning_effort": reasoning_effort,
        "thinking_level": thinking_level,
        "automatic_prompt_caching": entry.automatic_prompt_caching,
        "prompt_cache_key": entry.prompt_cache_key,
        "extended_prompt_cache_retention": entry.extended_prompt_cache_retention,
        "cached_token_accounting": entry.cached_token_accounting,
        "minimum_cacheable_input_tokens": entry.minimum_cacheable_input_tokens,
        # Aggregator upstream-host allow-list. The adapter turns a non-empty
        # value into matching ``provider.order`` and ``provider.only`` lists.
        "upstream_providers": entry.upstream_providers,
        # True when this operation is one of the core artifact-generation ops.
        # The adapter uses it to suppress reasoning on the cheap non-core paths
        # (judge/refine/summary), whose output budgets are far too small to
        # absorb a reasoning burst — see output_budget.OUTPUT_TOKEN_BUDGETS.
        "is_core_generation": operation in CORE_GENERATION_OPERATIONS,
    }


def validate_model_catalog() -> None:
    missing_providers = REQUIRED_PROVIDERS - set(PROVIDER_CAPABILITIES)
    if missing_providers:
        raise RuntimeError(
            f"Model catalog missing providers: {sorted(missing_providers)}"
        )

    seen_ids: set[str] = set()
    provider_operation_defaults: dict[tuple[str, str], list[str]] = {}
    for entry in MODEL_CATALOG:
        if entry.model_id in seen_ids:
            raise RuntimeError(f"Duplicate model catalog ID: {entry.model_id}")
        seen_ids.add(entry.model_id)
        _validate_entry(entry)
        if entry.status == "active":
            for operation in entry.default_operations:
                provider_operation_defaults.setdefault(
                    (entry.provider, operation), []
                ).append(entry.model_id)

    for provider in REQUIRED_PROVIDERS:
        for operation in CORE_GENERATION_OPERATIONS:
            defaults = provider_operation_defaults.get((provider, operation), [])
            if len(defaults) != 1:
                raise RuntimeError(
                    "Core generation operation must have exactly one active "
                    f"default: provider={provider!r}, operation={operation!r}, "
                    f"defaults={defaults!r}"
                )

    validate_core_generation_ladder()


def core_generation_ladder(provider: str) -> tuple[str, ...]:
    """The declared cheapest-first core-generation tier ladder for a provider."""
    _require_provider(provider)
    ladder = CORE_GENERATION_TIER_LADDER.get(provider)
    if not ladder:
        raise RuntimeError(f"No core-generation tier ladder declared for {provider!r}")
    return ladder


def core_generation_tier_policy(provider: str) -> tuple[str, str]:
    """Derive the live ``(primary, fallback)`` cheap-primary policy from the ladder.

    The runtime policy is exactly ``(ladder[0], ladder[1])`` — the cheapest viable
    starting tier and its one-shot escalation. Deriving it here (rather than
    hand-maintaining a parallel dict) keeps the per-provider floor a single,
    catalog-validated decision (issue #26 Phase 5b).
    """
    ladder = core_generation_ladder(provider)
    return ladder[0], ladder[1]


def validate_core_generation_ladder() -> None:
    """Assert every provider's core-gen tier ladder is well-formed (Phase 5b).

    Hygiene invariants (CI-enforced via ``validate_model_catalog``):

    * Every required provider declares a ladder of at least ``(primary, fallback)``.
    * Each tier is a valid model tier and the ladder is strictly increasing in
      capability rank (cheapest first), so an escalation never *lowers* capability.
    * The **primary** tier resolves to exactly one active core-generation default
      model — the model that actually runs by default. Escalation tiers may have
      no active model today (e.g. Google ``strong``: a failure surfaces directly),
      so they are not required to resolve; ``_validate_entry`` independently bars
      any deprecated/preview model from being a default.
    """
    active_core_default_tiers: dict[tuple[str, str], set[str]] = {}
    for entry in MODEL_CATALOG:
        if entry.status != "active":
            continue
        defaults_core = any(
            op in entry.default_operations for op in CORE_GENERATION_OPERATIONS
        )
        if defaults_core:
            active_core_default_tiers.setdefault(
                (entry.provider, entry.tier), set()
            ).add(entry.model_id)

    for provider in REQUIRED_PROVIDERS:
        ladder = CORE_GENERATION_TIER_LADDER.get(provider)
        if not ladder or len(ladder) < 2:
            raise RuntimeError(
                f"Provider {provider!r} must declare a core-generation ladder of "
                f"at least (primary, fallback); got {ladder!r}"
            )
        previous_rank = -1
        for tier in ladder:
            if tier not in _CORE_TIER_RANK:
                raise RuntimeError(
                    f"{provider!r} core-generation ladder references non-core tier "
                    f"{tier!r}"
                )
            rank = _CORE_TIER_RANK[tier]
            if rank <= previous_rank:
                raise RuntimeError(
                    f"{provider!r} core-generation ladder is not strictly "
                    f"increasing in capability: {ladder!r}"
                )
            previous_rank = rank

        primary_tier = ladder[0]
        primary_defaults = active_core_default_tiers.get(
            (provider, primary_tier), set()
        )
        if len(primary_defaults) != 1:
            raise RuntimeError(
                f"{provider!r} core-generation primary tier {primary_tier!r} must "
                f"resolve to exactly one active default model; got "
                f"{sorted(primary_defaults)!r}"
            )


def _validate_entry(entry: ModelCatalogEntry) -> None:
    _require_provider(entry.provider)
    if entry.tier not in MODEL_TIERS:
        raise RuntimeError(f"{entry.provider}/{entry.model_id} invalid tier")
    if entry.adapter_api not in _adapter_apis_for_provider(entry.provider):
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} uses unsupported adapter API "
            f"{entry.adapter_api!r}"
        )
    if entry.status == "deprecated" and entry.default_operations:
        raise RuntimeError(
            f"Deprecated model cannot be an active default: {entry.model_id}"
        )
    if not entry.recommended_operations:
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} must recommend operations"
        )
    invalid_operations = set(entry.recommended_operations) - GENERATION_OPERATIONS
    if invalid_operations:
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} invalid operations: "
            f"{sorted(invalid_operations)}"
        )
    invalid_defaults = set(entry.default_operations) - set(entry.recommended_operations)
    if invalid_defaults:
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} default operations are not "
            f"recommended: {sorted(invalid_defaults)}"
        )
    if entry.status == "preview" and entry.default_operations:
        raise RuntimeError(
            f"Preview model cannot be a production default: {entry.model_id}"
        )
    for field in ("max_context_tokens", "default_max_output_tokens"):
        if getattr(entry, field) <= 0:
            raise RuntimeError(f"{entry.provider}/{entry.model_id} invalid {field}")
    for field in (
        "input_cost_per_million",
        "cached_input_cost_per_million",
        "output_cost_per_million",
    ):
        value = getattr(entry, field)
        if value is not None and value < 0:
            raise RuntimeError(f"{entry.provider}/{entry.model_id} negative {field}")


def _adapter_apis_for_provider(provider: str) -> set[str]:
    table = {
        "anthropic": {"messages"},
        "openai": {"responses", "chat_completions"},
        "google": {"generate_content"},
        "openrouter": {"chat_completions"},
    }
    if provider not in table:
        raise RuntimeError(f"No adapter API table entry for provider {provider!r}")
    return table[provider]


def _require_provider(provider: str) -> None:
    if provider not in REQUIRED_PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {provider!r}")


validate_model_catalog()
