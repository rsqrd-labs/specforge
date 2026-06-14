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
    # Optional identity OAuth for the App (learning the installing user's login).
    # The integration works without these; leave blank to disable identity OAuth.
    github_app_client_id: str = ""
    github_app_client_secret: str = ""

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

    # Phase 1 (issue #26): route storyboard generation through the mid tier
    # (Sonnet 4.6 / GPT-5.4 / Gemini 3.5 Flash) first and escalate to the
    # strong tier on a quality-gate failure (schema/parse/grounding error).
    # Default False until golden-corpus old-vs-new comparison validates the
    # routing — Phase 5.3 owns that gate.  Never flip to True in production
    # before the evaluation passes.
    storyboard_mid_first: bool = False

    # Phase 5.3 (issue #26): master switch for the shipped cheap-primary core
    # generation policy (Haiku 4.5 / GPT-5.4 Mini start, mid-tier escalation on a
    # runtime/quality-gate failure).  Default True — it wraps the *live* behavior
    # so it can be reverted with one toggle: set False and every core generation
    # (fresh stages, full regenerate, harness gap-patch) falls back to the
    # pre-cheap-swap *mid-first* default (Sonnet 4.6 / GPT-5.4 first, strong
    # escalation).  Increment generation is independent (`_INCREMENT_TIERS`) and
    # is unaffected by this flag.  Flip False if the golden-corpus comparison ever
    # shows the cheap primary regressing artifact quality.
    core_cheap_primary: bool = True

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
    # catalog this DOES fire for core generation (budget 24576 doubles into the 32768
    # ceiling), so it actively cuts a call — it is NOT outcome-preserving: a
    # generation that only just overran could still fit at the ceiling, so the flag
    # trades that recovery for the saved call. That is exactly why it ships Default
    # False — a chunk-loop change that changes which artifacts recover rides the
    # issue-#26 golden-corpus gate and is promoted only after the manual live review
    # (`docs/evals/ROUTE_PROMOTION.md`). Flag OFF ⇒ the loop is byte-identical.
    pipeline_early_bail_unrecoverable_chunk: bool = False

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

    if errors:
        raise RuntimeError("; ".join(errors))
