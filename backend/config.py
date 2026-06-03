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

    # Stripe Payments (Phase 18) — leave blank to disable billing UI.
    # Use sk_test_* keys for development; sk_live_* keys for production only.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_cents: int = 900  # $9.00 — 200 credits per purchase
    stripe_credits_per_purchase: int = 200
    stripe_credit_validity_days: int = 30
    # IMPORTANT: STRIPE_SUCCESS_URL must point to /billing (NOT /billing/success).
    # T-238 registers /billing as the authenticated billing route.  The Billing
    # component detects ?session_id= on that route and enters polling mode.
    # There is no /billing/success route — users land on a 404 if you set this wrong.
    stripe_success_url: str = ""  # e.g. https://app.specforge.dev/billing
    stripe_cancel_url: str = ""  # e.g. https://app.specforge.dev/billing

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


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

    # Stripe production key guard.  A test key (sk_test_*) in production means
    # payments appear to succeed via test cards but no real money is charged.
    # This guard catches the misconfiguration at startup — before any user
    # attempts a purchase — using the same accumulate-then-raise pattern as all
    # other production checks above.  An empty stripe_secret_key (billing
    # disabled) passes the guard: "".startswith("sk_test_") is False.
    if settings.stripe_secret_key.startswith("sk_test_"):
        errors.append(
            "STRIPE_SECRET_KEY is a test key (sk_test_*). "
            "Production deployments must use a live key (sk_live_*). "
            "Using a test key in production silently accepts test card numbers "
            "without charging real money."
        )

    if errors:
        raise RuntimeError("; ".join(errors))
