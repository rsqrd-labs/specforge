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
    llm_stream_timeout_seconds: int = 120
    llm_long_stream_timeout_seconds: int = 300
    llm_complete_timeout_seconds: int = 45
    max_request_body_bytes: int = 1_000_000

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
