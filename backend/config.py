from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str

    jwt_private_key: str
    jwt_public_key: str
    google_client_id: str
    google_client_secret: str
    frontend_url: str

    # Marketing-zone canonical origin (issue #18, Phase 7). The Astro marketing
    # zone owns its own ``PUBLIC_SITE_URL``; this is the backend-side mirror for
    # any server-emitted canonical/sitemap concern. Optional (empty = unset, no
    # backend consumer reads it yet) but HTTPS-enforced in prod when set — see
    # ``validate_production_settings``. Hard-requiring it would fail-boot every
    # existing prod deploy that has not configured it, so the guard is
    # HTTPS-when-set (mirroring ``langfuse_host``), not unconditional.
    site_url: str = ""

    anthropic_api_key: str
    openai_api_key: str
    google_api_key: str

    encryption_master_key: str
    csrf_secret: str

    sentry_dsn: str = ""
    grafana_otlp_endpoint: str = ""
    grafana_otlp_token: str = ""

    # LLM observability (optional). Leave langfuse_secret_key empty to disable
    # the Langfuse integration entirely; when empty the SDK is never imported
    # and zero network traffic is sent to a Langfuse host.
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_prompt_cache_ttl: int = 300
    # Hard upper bound on how long a single Langfuse prompt fetch may take.
    # The SDK's get_prompt is synchronous and on a cache miss issues a
    # blocking HTTP call (default ~10s × 3 retries). We dispatch it to a
    # worker thread and bound the await with this timeout so a slow or
    # unreachable Langfuse host cannot stall the event loop or stage
    # generation. On timeout the local fallback prompt is used.
    langfuse_prompt_fetch_timeout_seconds: float = 5.0
    langfuse_content_capture_ack: bool = False

    environment: str

    # Empty string disables token auth; fall back to localhost-only IP check
    metrics_token: str = ""
    trusted_proxy_ips: str = ""
    max_active_workspaces_per_user: int = 50
    auth_login_burst_limit: int = 5
    auth_login_burst_window_seconds: int = 300
    auth_login_hourly_limit: int = 20
    auth_login_hourly_window_seconds: int = 3600

    db_pool_size: int = 20
    db_max_overflow: int = 10
    # LLM circuit-breaker rejections emit specforge_llm_circuit_rejections_total.
    #
    # Stream-watchdog policy: a generation stream is killed only when it is
    # actually unhealthy, never merely because the artifact is long.
    # - idle timeout: maximum gap between two provider stream EVENTS, not
    #   visible tokens — adapters yield empty liveness sentinels for
    #   reasoning/thinking deltas, pings, and usage chunks, so a frontier
    #   model reasoning silently for minutes never trips this bound while its
    #   connection is demonstrably alive.
    # - hard cap: absolute upper bound for a single stream call, bounding
    #   runaway provider cost.
    llm_stream_idle_timeout_seconds: int = 180
    llm_stream_hard_cap_seconds: int = 900
    llm_complete_timeout_seconds: int = 120
    # Phase 0 (issue #26) LLM cost ledger: persist one llm_cost_events row per
    # provider call. Fire-and-forget and fully exception-swallowed, but kept
    # behind a flag so a test/CI environment without a DB never even attempts
    # the write.
    llm_cost_ledger_enabled: bool = True
    # Phase 2 (issue #26): add cache_control hints to the system-prompt block for
    # providers that support explicit prompt caching (Anthropic cache_control).
    # Default True — quality-neutral (same content, same model; only billing and
    # latency change) and the break-even is low for chunked/multi-round paths.
    # Flip False to disable the structured block without a redeploy.
    llm_prompt_cache_enabled: bool = True
    # Phase 3 (issue #26): submit non-interactive judge/eval calls (eval.score)
    # through the provider Message Batches API for the 50% batch discount,
    # driven on the arq worker (submit → checkpoint batch id → cron poll →
    # collect). Default False — the feature ships behind a flag with automatic
    # fallback to the synchronous in-process path when off, when the provider
    # has no real batch API (only Anthropic today), or when the durable queue is
    # unavailable. Never batches interactive generation or the critic.
    llm_batch_enabled: bool = False
    # Issue #27 Phase 2: fraction of non-harness generations (spec/plan/tasks)
    # whose best-effort LLM *quality score* is computed. The score is no longer a
    # user-facing signal (Phase 1 cut it from the UI in favour of deterministic
    # findings), so it is sampled purely for internal telemetry. Default 0.0 ⇒ the
    # score-only judge call is never issued for those stages, which is the cost
    # win — deterministic findings (task traceability, completeness) still run
    # inline on every generation regardless. HARNESS stages are exempt from this
    # gate: their LLM-derived coverage finding (`coverage_percent`/`uncovered_reqs`)
    # has no deterministic equivalent and must stay visible (Decision A), so the
    # judge always runs there. The single gate lives in `_dispatch_stage_eval`.
    # Raise toward 1.0 only to gather model/provider quality telemetry. Must be in
    # [0.0, 1.0]; an out-of-range value fails startup in every environment.
    eval_score_sample_rate: float = 0.0
    # Critic async-advisory (docs/CRITIC_ASYNC_ADVISORY_PLAN.md): take the Phase-19
    # critic judge off the critical path. Default True — the usable draft is
    # delivered the moment the deterministic gates pass (sections, depth,
    # tech-safety) and the `done` SSE event fires; the LLM judge then runs in a
    # detached background task (mirroring the best-effort eval score) and, on a
    # failing verdict, attaches its findings to the already-delivered draft as
    # non-blocking advisory suggestions. There is NO auto-regenerate in this path.
    # Flip False to retain the legacy inline critic+regenerate loop verbatim for
    # one release (instant revert if quality/UX regresses) — the old branch is
    # removed in a follow-up once the new path is proven.
    critic_async_advisory: bool = True
    # Issue #21 Phase 2b — honest, data-backed generation ETA. A cheap periodic
    # worker cron rolls llm_cost_events latency_ms up into aggregate p50/p90 per
    # (provider, stage, operation), caches the result in Redis, and the read-only
    # GET /stages/generation-estimates endpoint serves it from cache (the heavy
    # query never runs per request). The frontend prefers these live percentiles
    # and falls back to its constant heuristic table on any miss/empty/low-sample
    # response, so the feature can never degrade the UX below the 2a baseline.
    # Flip enabled False to stop refreshing (the endpoint then serves empty and
    # every client falls back to the heuristic).
    generation_estimates_enabled: bool = True
    # Trailing window the rollup samples. Shorter tracks the current cheap-tier
    # models' latency; long enough to accumulate volume per (provider, stage).
    generation_estimates_window_days: int = 14
    # A (provider, stage, operation) key is only served once it has at least this
    # many samples — below it the client keeps the heuristic baseline.
    generation_estimates_min_samples: int = 50
    # Redis TTL for the cached rollup. The cron recomputes more often than this
    # (see worker.py) so the key never expires while the worker is healthy; if the
    # worker is down past the TTL the key lapses and clients fall back cleanly.
    generation_estimates_cache_ttl_seconds: int = 900
    # latency_ms measures the provider stream only; the post-stream pipeline tail
    # (artifact validator → critic judge → persistence) adds a few seconds of
    # perceived time the stream timer never sees. Added to the served p50/p90 so
    # the band reflects perceived wall-clock, not stream duration (keeps the
    # "still working" flip from firing early on the slow end of normal runs).
    generation_estimates_pipeline_tail_seconds: int = 4
    max_request_body_bytes: int = 1_000_000
    tech_safety_policy_max_age_days: int = 30
    tech_safety_osv_cache_ttl_seconds: int = 86_400
    tech_safety_eol_cache_ttl_seconds: int = 604_800
    tech_safety_advisory_timeout_seconds: float = 3.0
    tech_safety_osv_api_base: str = "https://api.osv.dev"
    tech_safety_eol_api_base: str = "https://endoflife.date/api/v1"
    tech_safety_blocked_severities: str = "critical,high,unknown"

    # GitHub OAuth App — leave blank to disable GitHub export
    github_client_id: str = ""
    github_client_secret: str = ""

    # GitHub App (Phase 21 living integration) — leave blank to disable.
    # github_app_id is GitHub's numeric App id used as the App-JWT `iss`.
    # github_app_private_key is the RS256 PEM that signs the App JWT; it is a
    # secret-manager value and is never persisted to the database (spec §8).
    # github_app_slug is the App's public slug, used to build the installation
    # URL (https://github.com/apps/{slug}/installations/new). Leave blank to
    # disable the App install flow (the Phase-13 OAuth path remains available).
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_app_slug: str = ""
    # Webhook HMAC signing secrets. Two are accepted so a secret rotation does
    # not drop in-flight deliveries: every inbound signature is checked against
    # the current secret and, if set, the previous one (spec §8/§12).
    github_app_webhook_secret: str = ""
    github_app_webhook_secret_prev: str = ""
    # Identity OAuth (user-to-server) for the App. This is the credential that
    # proves the person completing the install callback actually administers the
    # installation's account, closing the install-callback IDOR (GitHub
    # integration audit #1): without it the setup callback would (re)bind an
    # attacker-supplied ``installation_id`` to the caller with no proof of
    # control. It is therefore **required** when the App is enabled in production
    # (see ``validate_production_settings``).
    github_app_client_id: str = ""
    github_app_client_secret: str = ""

    @property
    def github_app_identity_enabled(self) -> bool:
        """True when the App's user-to-server identity OAuth is configured.

        Both the client id and secret are required to exchange the install
        callback's ``code`` for a user token and verify the installer
        administers the installation (audit #1). The single source of truth for
        "can we verify an installer", mirrored by
        ``github_install_service.app_identity_enabled``.
        """
        return bool(self.github_app_client_id and self.github_app_client_secret)

    @property
    def github_app_enabled(self) -> bool:
        """True when the GitHub App is configured (its identity is present).

        The single source of truth for "is the App on": the App cannot mint a JWT
        or build an install URL without both the numeric id and the public slug,
        so those two define "enabled" (matching ``github_install_service``). When
        enabled in production, ``validate_production_settings`` requires the
        signing key + webhook secret too.
        """
        return bool(self.github_app_id and self.github_app_slug)

    @property
    def github_app_webhook_secrets(self) -> list[str]:
        """The non-empty webhook signing secrets, current first (for rotation).

        Passed to ``verify_hmac`` so an inbound signature is accepted against the
        current secret and, during a rotation window, the previous one.
        """
        return [
            s
            for s in (
                self.github_app_webhook_secret,
                self.github_app_webhook_secret_prev,
            )
            if s
        ]

    # Phase 5.3 (issue #26) + issue #17 follow-up: master switch for the
    # product-wide cheap-primary generation policy (Haiku 4.5 / GPT-5.4 Mini
    # start, mid-tier escalation on a runtime/quality-gate failure).  Defaults
    # **True** (cheap-first): running every core generation on the mid tier
    # (Sonnet 4.6 / GPT-5.4) is too expensive to sustain at production volume —
    # it takes an unacceptable hit on per-generation margins — so **every**
    # artifact-generation feature — the four core stages, full regenerate, the
    # harness gap-patch, the storyboard keynote, and increment generation —
    # starts on the provider's cheapest viable tier and only escalates to mid on
    # a runtime/quality-gate failure, via the shared
    # ``services.llm.tier_policy.generation_tier_policy``.  Set False to revert
    # **all** of those features to the pre-cheap-swap mid-first default in one
    # toggle (mid start, strong escalation) if cheap-tier quality regresses.
    core_cheap_primary: bool = True

    # Stage latency lever (docs/STAGE_LATENCY_PLAN.md): when enabled, only the
    # primary stage-generation adapter requests use low reasoning/thinking on the
    # cheap primary model. Other uses of the same model (judge/eval, refine,
    # storyboard, increment, critic regenerate) keep the catalog default because
    # their call sites do not opt into operation-aware adapter policy.
    core_generation_low_reasoning: bool = True

    # Phase 5.2 (issue #26): deterministic, no-LLM complexity classifier that
    # raises the *starting* tier for predictably hard core generations (regulated
    # domains, large upstream chains, prior quality-gate failures) above the cheap
    # primary — so a request that would burn the cheap attempt + funded regenerate
    # starts on a capable model instead.  It is a floor, never a ceiling (it can
    # only raise a tier, never lower it) and only applies while `core_cheap_primary`
    # is on.  Default False — per issue AC, adaptive routing ships behind a flag
    # and is enabled only after the golden-corpus live gate validates it
    # (`docs/evals/ROUTE_PROMOTION.md`).
    core_complexity_routing: bool = False

    # Phase 4 (issue #28): early-bail on an unrecoverable chunk limit-stop. A chunk
    # that stops on its output-token budget is repaired with a *doubled* budget
    # (`_repair_budget`). Once that doubled budget is already clamped to the model
    # output ceiling, the repair is the final escalation — there is no larger budget
    # left to try — and a generation that over-produced at the prior budget (the d3
    # case: 89 FRs, truncated) is unlikely to fit at the ceiling. With this flag on,
    # that ceiling-capped repair is skipped and the `incomplete_output` block
    # surfaces immediately instead of after another multi-minute call. Under the live
    # catalog this DOES fire for core generation when a 49152-token chunk limit-stops:
    # the doubled repair clamps to the true 64000-token ceiling, so there is no larger
    # retry left after that 64K call. When it fires it actively cuts a call — it is NOT
    # outcome-preserving: a generation that only just overran 49152 could still fit at
    # 64000, so the flag trades that recovery for the saved call. That is exactly why it
    # ships Default False — a chunk-loop change that changes which artifacts recover
    # rides the issue-#26 golden-corpus gate and is promoted only after the manual live
    # review (`docs/evals/ROUTE_PROMOTION.md`). Flag OFF ⇒ the loop is byte-identical.
    pipeline_early_bail_unrecoverable_chunk: bool = False

    # Parallel chunk generation (issue #39 latency). A stage's wall-clock to
    # `done` is the SUM of its sequential streaming chunk calls (spec=3, plan=4,
    # harness=2, tasks=4). When True, the happy path generates a stage's chunks
    # in dependency-ordered WAVES (`_chunk_waves_for_stage`), running the chunks
    # within a wave concurrently — turning the sum into ~max(wave) and cutting
    # wall-clock the most on the worst offenders (plan ~4→1 wave, tasks ~4→2).
    # Each concurrent chunk uses its OWN adapter instance (no shared completion
    # state) and live token streaming is suppressed in favour of the supervising
    # progress heartbeats + the canonical end-of-stream replay (parallel token
    # streams cannot be interleaved into one coherent document). The sequential
    # path (`_chunk_specs_for_stage`) is left byte-identical as the OFF fallback,
    # and any incompleteness still routes through the existing per-chunk repair
    # plus a full SEQUENTIAL completeness-repair pass, so cross-chunk invariants
    # (effort-summary counts, numbering, traceability) are reconciled exactly as
    # today. It is OUTCOME-CHANGING (parallel chunks cannot see each other), so it
    # rides the issue-#26 golden-corpus gate (`docs/evals/ROUTE_PROMOTION.md`)
    # before promotion. Flag OFF ⇒ generation is byte-identical to the
    # pre-#39 sequential loop. Shipped ON (user decision, issue #39) to cut the
    # ~8-min/stage wall-clock now; instantly reversible by setting this False if
    # the corpus/live quality of parallel chunks regresses.
    pipeline_parallel_chunks: bool = True
    # Max chunks generated concurrently within a single stage generation. Caps
    # peak provider tokens-per-minute / concurrent streams so a fan-out does not
    # trip rate limits (which would claw the latency win back via 429 retries).
    pipeline_parallel_chunk_concurrency: int = 4

    # Problem-statement compression (docs/PROBLEM_STATEMENT_COMPRESSION_PLAN.md,
    # Phase B). When True, an over-budget problem statement is reduced to at most
    # `problem_statement_budget_tokens` (C_MAX) before any model sees it, via the
    # zero-LLM ladder in `services/pipeline/problem_compressor.py` (Rung 0 no-op →
    # Rung 1 lossless structural cleanup → Rung 3 deterministic normative-first
    # clamp). It is the *other half* of the raised input cap (Phase A): input is
    # accepted big and fed small, so per-call cost/latency stay bounded regardless
    # of input size, and no call can blow the model window. Default **False** — the
    # under-threshold common case is a byte-identical no-op, so flipping it changes
    # nothing for the vast majority of inputs; the Rung-0 regression pin and the
    # golden corpus gated the rollout. **Enabled by default in Phase D** (the
    # deterministic ladder is zero-LLM-cost and bounded; only genuinely over-budget
    # pastes condense). When a paste does condense (Rung 2/3), the user is told via
    # a non-blocking advisory notice on the generated stage (`AdvisoryFindingsPanel`).
    # The Rung-2 *abstractive* (paid, meaning-preserving) pass remains a separate,
    # default-off sub-gate (`problem_statement_abstractive`) below.
    problem_statement_compression: bool = True

    # C_MAX — the product token budget compression targets and triggers on
    # (THRESHOLD ≈ C_MAX). A *chosen* small constant set far below the model window
    # (200K–1M tokens): the win is sending less, not fitting the window. Pre-Phase-A
    # inputs (≤10K chars ≈ 2.5K tokens) sit below this and never compress; only the
    # new large pastes (up to the 50K-char `PROBLEM_STATEMENT_MAX_CHARS`) trip it.
    # One constant across providers keeps the cache key and golden corpus
    # deterministic (plan §10). The effective budget is `min(this, WINDOW_FIT_CEILING)`
    # so it can never exceed what the window physically allows.
    problem_statement_budget_tokens: int = 8000

    # Rung 2 — the meaning-preserving *abstractive* pass (Phase C). This is a
    # **sub-gate** of `problem_statement_compression`: it has no effect unless the
    # master flag is also on. When both are on, an over-budget statement that the
    # deterministic ladder would otherwise hand to the Rung-3 clamp is instead
    # routed through a capped map-reduce over the cheap judge model that keeps
    # normative content (requirement IDs, must/shall, lists, tables) verbatim and
    # condenses only the narrative prose, falling open to the Rung-3 floor on any
    # judge error/timeout or when there is no narrative room. Default **False**:
    # like `core_complexity_routing`, the paid LLM layer ships off and is promoted
    # only after the normative-retention + semantic-equivalence gate
    # (docs/evals/PROBLEM_COMPRESSION_PROMOTION.md). Phase B's zero-cost
    # reliability never depends on this flag.
    problem_statement_abstractive: bool = False

    # Overall wall-clock budget for the Rung-2 abstractive pass (all map + reduce
    # judge calls combined). On expiry the pass fails open to the Rung-3 floor, so
    # this caps the added latency, not correctness (plan §9 target: < 3s p95).
    problem_statement_abstractive_timeout_seconds: float = 8.0

    # Increment generation (Phase 21 — T-279). The MVP ships the *additive* path
    # only: an increment appends new tasks with their existing content pinned by
    # stable, content-derived task_refs. Behaviour-changing increments (compute
    # blast radius, mark affected items stale, re-run harness/critic only on the
    # affected areas) are the phase-two cut and stay gated off until that work
    # lands; flip this to true only once the blast-radius path is implemented.
    increment_blast_radius_enabled: bool = False

    # Lemon Squeezy billing (Phase 22) — the provider-neutral checkout that
    # supersedes Stripe at runtime. Leave the api key / store id / variant id
    # blank to ship with checkout DISABLED (GET /billing/package still works;
    # POST /billing/checkout returns 503). When all three are set the integration
    # is "enabled" (``lemonsqueezy_enabled``) and, in production,
    # ``validate_production_settings`` requires a complete LIVE config. There is
    # deliberately no ``lemonsqueezy_cancel_url`` (Plan §25.6 T-292).
    lemonsqueezy_api_key: str = ""
    # HMAC signing secrets for the X-Signature webhook header. Two are accepted so
    # a secret rotation does not drop in-flight deliveries (current + previous).
    lemonsqueezy_webhook_secret: str = ""
    lemonsqueezy_webhook_secret_prev: str = ""
    lemonsqueezy_store_id: str = ""
    lemonsqueezy_variant_id: str = ""
    lemonsqueezy_price_cents: int = 900  # $9.00 — 200 credits per purchase
    lemonsqueezy_currency: str = "USD"
    lemonsqueezy_credits_per_purchase: int = 200
    lemonsqueezy_credit_validity_days: int = 30
    lemonsqueezy_success_url: str = ""  # e.g. https://app.specforge.dev/billing
    # test_mode gates whether checkouts are created against Lemon's test store.
    # Production must run with this False (the production guard enforces it).
    lemonsqueezy_test_mode: bool = True
    # How long a created checkout attempt stays pollable before it is swept to
    # 'expired' by the retention job (T-298).
    lemonsqueezy_checkout_ttl_minutes: int = 30
    lemonsqueezy_api_base: str = "https://api.lemonsqueezy.com"
    # Upper bound on provider API calls per reconcile run (bounds lane 2, T-301).
    lemonsqueezy_reconcile_max_calls_per_run: int = 200

    # Comma-separated allowlist of admin emails authorised to issue billing admin
    # corrections (T-302). The codebase has no role column, so this allowlist is
    # the ONLY admin authorization surface — an empty value means no admin exists
    # and the correction endpoint 403s for everyone (closed by default).
    admin_user_emails: str = ""

    # Brave LLM Context API research enrichment (issue #12) — mirrors the
    # langfuse/lemonsqueezy optional-integration shape. The feature is a purely
    # *additive*, fail-open web-grounding layer: when it is off, unconfigured, or
    # failing at runtime, generation proceeds identically to today on an empty
    # research block. Leaving brave_search_api_key empty disables the feature with
    # zero network traffic; brave_search_flag is a second, explicit kill-switch so
    # the integration can be flipped on/off without rotating the key. Both must be
    # set for ``brave_search_enabled`` to be true (and even then every actual call
    # is further gated per-workspace + per-stage + per-credit; see the plan §3).
    brave_search_api_key: str = ""
    brave_search_flag: bool = False
    # Stages that benefit from grounding (spec/plan); 'tasks' is pure decomposition
    # of upstream artifacts and is intentionally excluded by default.
    brave_research_stages: str = "spec,plan"
    # Hard per-fetch latency budget — far tighter than Brave's 30s suggestion so a
    # slow third party can add at most this many seconds to a generation (and 0s
    # when cached or disabled).
    brave_timeout_seconds: float = 4.0
    # Redis cache TTL for a fetched research block; keeps regenerate loops and
    # bursty traffic off the per-query meter. 6h is a freshness-vs-cost tradeoff.
    brave_cache_ttl_seconds: int = 21600
    # Brave context size control (contract range 1024–32768).
    brave_max_tokens: int = 8192
    # Upper bound on the injected research block so it cannot crowd out upstream
    # deps or blow the context window.
    brave_max_context_chars: int = 12000
    # Per-workspace daily call ceiling enforced in Redis; protects the monthly
    # free/paid quota from runaway loops. Over-ceiling fails open to no research.
    brave_max_calls_per_workspace_per_day: int = 20
    # Freshness bias toward recent best-practices (pd|pw|pm|py or a date range).
    brave_freshness: str = "py"
    # Credits charged per *successful paid* Brave fetch (cache hits, failures,
    # timeouts, empty results, and the disabled/not-opted-in paths cost nothing).
    # Provisional placeholder — final price (§13 open question) is set from the
    # $5/1k Brave cost plus margin and confirmed with billing before launch.
    billing_credits_brave_research: int = 1
    # COGS (Phase 4): platform USD cost of one paid Brave call, recorded on an
    # ``llm_cost_events`` row (provider="brave") per paid fetch so platform spend
    # and the user-facing credit debit reconcile. Default = Brave Search plan
    # $5 / 1000 requests = $0.005 / request; revisit if we move to the
    # token-metered AI-grounding plan (§13 open question).
    brave_cost_usd_per_call: float = 0.005

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("eval_score_sample_rate")
    @classmethod
    def _validate_eval_score_sample_rate(cls, value: float) -> float:
        """Reject a sample rate outside [0.0, 1.0] (issue #27 Phase 2).

        This is a probability, not a count — a value below 0 or above 1 is a
        misconfiguration in any environment, so it fails fast at startup rather
        than silently clamping and quietly under/over-sampling the judge.
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                "eval_score_sample_rate must be between 0.0 and 1.0 " f"(got {value})"
            )
        return value

    @property
    def lemonsqueezy_enabled(self) -> bool:
        """True when Lemon Squeezy checkout is configured.

        The single source of truth for "is Lemon billing on": a checkout cannot be
        minted without the API key, the store, and the variant, so those three
        define "enabled". When enabled in production,
        ``validate_production_settings`` additionally requires a complete LIVE
        config (webhook secret, HTTPS success URL, live mode, …).
        """
        return bool(
            self.lemonsqueezy_api_key
            and self.lemonsqueezy_store_id
            and self.lemonsqueezy_variant_id
        )

    @property
    def lemonsqueezy_webhook_secrets(self) -> tuple[str, ...]:
        """The non-empty webhook signing secrets, current first (for rotation).

        Passed to the inbound HMAC verifier so a signature is accepted against the
        current secret and, during a rotation window, the previous one.
        """
        return tuple(
            s
            for s in (
                self.lemonsqueezy_webhook_secret,
                self.lemonsqueezy_webhook_secret_prev,
            )
            if s
        )

    @property
    def admin_emails(self) -> set[str]:
        """The parsed, lower-cased billing-admin allowlist (empty when unset).

        An empty set authorises no one — the admin-correction support path (T-302)
        is closed by default and there is no implicit admin.
        """
        return {
            email.strip().lower()
            for email in self.admin_user_emails.split(",")
            if email.strip()
        }

    @property
    def brave_search_enabled(self) -> bool:
        """True only when Brave research is fully configured AND switched on.

        The single source of truth for "is Brave on": the integration needs a
        non-empty subscription key *and* the explicit ``brave_search_flag``
        kill-switch flipped on. An empty key alone keeps it off (no traffic);
        the flag lets ops disable it without rotating the key. Note this property
        already folds in the key, so the production guard keys on
        ``brave_search_flag`` (the flag-on/key-missing misconfiguration) rather
        than on this property, which can never be true with an empty key.
        """
        return bool(self.brave_search_api_key) and self.brave_search_flag

    @property
    def brave_research_stage_set(self) -> frozenset[str]:
        """The parsed set of stage types eligible for Brave enrichment.

        Empty when ``brave_research_stages`` is blank, which disables enrichment
        for every stage even with the flag and key set.
        """
        return frozenset(
            stage.strip().lower()
            for stage in self.brave_research_stages.split(",")
            if stage.strip()
        )


settings = Settings()


_CI_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def validate_production_settings() -> None:
    if settings.environment.lower() != "production":
        return

    errors = []
    if not settings.metrics_token:
        errors.append("METRICS_TOKEN must be set in production")
    if not settings.frontend_url.startswith("https://"):
        errors.append("FRONTEND_URL must use HTTPS in production")
    # Marketing zone canonical origin (issue #18, Phase 7). HTTPS-when-set: an
    # http:// SITE_URL would emit insecure canonical/OG/sitemap URLs and leak the
    # marketing origin over plaintext. Empty is allowed (the backend has no
    # consumer yet); only a configured-but-insecure value is a misconfiguration.
    if settings.site_url and not settings.site_url.startswith("https://"):
        errors.append("SITE_URL must use HTTPS in production when set")
    if not settings.jwt_private_key.strip().startswith("-----BEGIN"):
        errors.append(
            "JWT_PRIVATE_KEY must be a PEM-encoded RSA or EC private key "
            "(must start with '-----BEGIN'). "
            "The CI stub value is not valid for production."
        )
    if settings.encryption_master_key == _CI_ENCRYPTION_KEY:
        errors.append(
            "ENCRYPTION_MASTER_KEY is set to the known CI placeholder value. "
            "Generate a real key: "
            'python -c "from cryptography.fernet import '
            'Fernet; print(Fernet.generate_key().decode())"'
        )
    if settings.langfuse_secret_key.strip():
        if not settings.langfuse_public_key.strip():
            errors.append(
                "LANGFUSE_PUBLIC_KEY must be set when LANGFUSE_SECRET_KEY is set"
            )
        if not settings.langfuse_host.lower().startswith("https://"):
            errors.append(
                "LANGFUSE_HOST must use HTTPS in production. Plaintext HTTP "
                "exposes the Langfuse public/secret keys, full prompts, and "
                "full model outputs to anyone on the network path. Use "
                "https://cloud.langfuse.com or an HTTPS self-hosted endpoint."
            )
        if not settings.langfuse_content_capture_ack:
            errors.append(
                "LANGFUSE_CONTENT_CAPTURE_ACK must be true when enabling "
                "Langfuse in production. Langfuse receives prompt and model "
                "output content after secret-shaped redaction; only enable it "
                "after approving that telemetry data flow."
            )

    # Lemon Squeezy production guard (Phase 22 — T-292 / SR7). When Lemon is
    # enabled (api key + store + variant all set), production must run a complete
    # LIVE config or the checkout/webhook paths fail at runtime instead of at
    # startup. The api key, store id, and variant id are already guaranteed
    # non-empty by ``lemonsqueezy_enabled``, so they are not re-checked here; a
    # half-configured Lemon (missing one of those three) is "disabled" and
    # intentionally fails to-disabled (checkout 503s, package/history still work).
    if settings.lemonsqueezy_enabled:
        if not settings.lemonsqueezy_webhook_secret.strip():
            errors.append(
                "LEMONSQUEEZY_WEBHOOK_SECRET must be set when Lemon Squeezy "
                "billing is enabled — inbound webhooks (the sole credit-grant "
                "authority) cannot be signature-verified without it."
            )
        if not settings.lemonsqueezy_success_url.lower().startswith("https://"):
            errors.append("LEMONSQUEEZY_SUCCESS_URL must use HTTPS in production.")
        if settings.lemonsqueezy_price_cents <= 0:
            errors.append("LEMONSQUEEZY_PRICE_CENTS must be a positive integer.")
        if settings.lemonsqueezy_credits_per_purchase <= 0:
            errors.append(
                "LEMONSQUEEZY_CREDITS_PER_PURCHASE must be a positive integer."
            )
        if settings.lemonsqueezy_credit_validity_days <= 0:
            errors.append(
                "LEMONSQUEEZY_CREDIT_VALIDITY_DAYS must be a positive integer."
            )
        if not settings.lemonsqueezy_currency.strip():
            errors.append("LEMONSQUEEZY_CURRENCY must be non-empty.")
        if settings.lemonsqueezy_test_mode is not False:
            errors.append(
                "LEMONSQUEEZY_TEST_MODE must be False in production "
                "(live mode required); a test-mode store charges nothing."
            )

    # Stream-watchdog guard: an idle timeout below 30s kills healthy frontier
    # reasoning streams (they can think for tens of seconds between tokens);
    # a hard cap below the idle timeout makes every generation time out.
    if settings.llm_stream_idle_timeout_seconds < 30:
        errors.append(
            "LLM_STREAM_IDLE_TIMEOUT_SECONDS must be at least 30 in production; "
            "lower values kill healthy reasoning-model streams."
        )
    if settings.llm_stream_hard_cap_seconds < settings.llm_stream_idle_timeout_seconds:
        errors.append(
            "LLM_STREAM_HARD_CAP_SECONDS must be >= LLM_STREAM_IDLE_TIMEOUT_SECONDS."
        )

    # GitHub App guard (Phase 21 — T-283). When the App is enabled (id + slug
    # set), production must also have the signing key and webhook secret, or the
    # install/JWT/webhook paths fail at runtime instead of at startup. An empty
    # private key is rejected explicitly: without it no installation token can be
    # minted, so every App-backed GitHub write would silently 401-loop.
    if settings.github_app_enabled:
        if not settings.github_app_private_key.strip():
            errors.append(
                "GITHUB_APP_PRIVATE_KEY must be set when the GitHub App is "
                "enabled (GITHUB_APP_ID + GITHUB_APP_SLUG present). It is the "
                "RS256 PEM that signs the App JWT; without it no installation "
                "token can be minted."
            )
        if not settings.github_app_webhook_secret.strip():
            errors.append(
                "GITHUB_APP_WEBHOOK_SECRET must be set when the GitHub App is "
                "enabled, or inbound webhooks cannot be signature-verified."
            )
        # Identity OAuth is the install-callback's proof-of-control (audit #1).
        # Without it the setup callback cannot verify the installer administers
        # the installation, so it would refuse every bind and installs would
        # silently fail closed. Require it loudly at startup instead.
        if not settings.github_app_identity_enabled:
            errors.append(
                "GITHUB_APP_CLIENT_ID and GITHUB_APP_CLIENT_SECRET must be set "
                "when the GitHub App is enabled: they are the user-to-server "
                "identity OAuth credentials the install callback uses to verify "
                "the installer administers the installation (prevents the "
                "install-callback IDOR). Without them every install is refused."
            )

    # Brave research guard (issue #12). The feature is allowed *off* in prod (no
    # hard requirement), but turning the flag on without a key is a silent
    # misconfiguration: every fetch would 401 and fail open to no research, so
    # the flag would look enabled while doing nothing. We key on the flag (not
    # ``brave_search_enabled``, which already folds in the key and so can never be
    # true here with an empty key) to catch exactly that flag-on/key-missing case.
    if settings.brave_search_flag and not settings.brave_search_api_key.strip():
        errors.append(
            "BRAVE_SEARCH_API_KEY must be set when BRAVE_SEARCH_FLAG is true; "
            "otherwise every Brave fetch 401s and silently disables research "
            "while the flag reads as enabled."
        )

    if errors:
        raise RuntimeError("; ".join(errors))
