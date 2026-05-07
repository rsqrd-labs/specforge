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

    if errors:
        raise RuntimeError("; ".join(errors))
