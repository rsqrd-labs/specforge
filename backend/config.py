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

    db_pool_size: int = 20
    db_max_overflow: int = 10
    llm_stream_timeout_seconds: int = 120
    llm_complete_timeout_seconds: int = 45
    max_request_body_bytes: int = 1_000_000

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

    if errors:
        raise RuntimeError("; ".join(errors))
