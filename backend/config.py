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

    sentry_dsn: str
    grafana_otlp_endpoint: str
    grafana_otlp_token: str

    environment: str

    # Empty string disables token auth; fall back to localhost-only IP check
    metrics_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
