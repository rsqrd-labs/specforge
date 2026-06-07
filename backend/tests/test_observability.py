from __future__ import annotations

import logging
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import create_app
from services import observability
from services.observability import (
    SensitiveDataFilter,
    redact_sensitive_data,
    redact_structlog_event,
)


class _NoopPipeline:
    def zremrangebyscore(self, *args):
        return self

    def zadd(self, *args):
        return self

    def zcard(self, *args):
        return self

    def expire(self, *args):
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _NoopRedis:
    async def eval(self, *args, **kwargs) -> int:
        return 1

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


def test_metrics_endpoint_exposes_prometheus_metrics() -> None:
    with patch.object(observability.settings, "metrics_token", "test-metrics-token"):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer test-metrics-token"}
        )

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_storyboard_metrics_are_registered() -> None:
    for metric in [
        "STORYBOARD_GENERATION_STARTED",
        "STORYBOARD_GENERATION_COMPLETED",
        "STORYBOARD_GENERATION_FAILED",
        "STORYBOARD_SECTION_REGENERATED",
        "STORYBOARD_GENERATION_DURATION",
        "STORYBOARD_CREDITS_DEDUCTED",
        "STORYBOARD_CREDITS_REFUNDED",
        "STORYBOARD_PUBLIC_VIEW",
        "STORYBOARD_DOWNLOAD",
        "STORYBOARD_SOURCE_MISSING",
    ]:
        assert hasattr(observability, metric)


def test_metrics_endpoint_rejects_unauthenticated() -> None:
    with patch.object(observability.settings, "metrics_token", "secret"):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        response = client.get("/metrics")
    assert response.status_code == 401


def test_metrics_endpoint_requires_token_in_production() -> None:
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", ""),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "METRICS_TOKEN" in str(exc)
        else:
            raise AssertionError("production app started without METRICS_TOKEN")


def test_production_app_requires_https_frontend_url() -> None:
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "http://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "FRONTEND_URL" in str(exc)
        else:
            raise AssertionError("production app started with non-HTTPS FRONTEND_URL")


def test_production_app_rejects_stub_jwt_private_key() -> None:
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(observability.settings, "jwt_private_key", "ci-test-private-key"),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "JWT_PRIVATE_KEY" in str(exc)
        else:
            raise AssertionError("production app started with stub JWT_PRIVATE_KEY")


def test_production_app_rejects_ci_placeholder_encryption_key() -> None:
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(
            observability.settings,
            "encryption_master_key",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        ),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "ENCRYPTION_MASTER_KEY" in str(exc)
        else:
            raise AssertionError(
                "production app started with CI placeholder encryption key"
            )


def test_production_app_requires_langfuse_content_capture_ack() -> None:
    fake_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    )
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(observability.settings, "jwt_private_key", fake_pem),
        patch.object(observability.settings, "encryption_master_key", "real-key"),
        patch.object(observability.settings, "langfuse_secret_key", "sk-langfuse"),
        patch.object(observability.settings, "langfuse_public_key", "pk-langfuse"),
        patch.object(observability.settings, "langfuse_content_capture_ack", False),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "LANGFUSE_CONTENT_CAPTURE_ACK" in str(exc)
        else:
            raise AssertionError(
                "production app started with Langfuse enabled but no content "
                "capture acknowledgement"
            )


def test_production_app_rejects_langfuse_host_without_https() -> None:
    """Plaintext HTTP to Langfuse would leak the public/secret keys, the
    full prompts, and the full model outputs to anyone on the network
    path. The production gate must reject any non-HTTPS Langfuse host."""
    fake_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    )
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(observability.settings, "jwt_private_key", fake_pem),
        patch.object(observability.settings, "encryption_master_key", "real-key"),
        patch.object(observability.settings, "langfuse_secret_key", "sk-langfuse"),
        patch.object(observability.settings, "langfuse_public_key", "pk-langfuse"),
        patch.object(
            observability.settings, "langfuse_host", "http://langfuse.internal:3000"
        ),
        patch.object(observability.settings, "langfuse_content_capture_ack", True),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "LANGFUSE_HOST" in str(exc) and "HTTPS" in str(exc)
        else:
            raise AssertionError(
                "production app started with a plaintext Langfuse host"
            )


def test_production_app_accepts_langfuse_host_with_https() -> None:
    """The default https://cloud.langfuse.com host must pass the gate."""
    fake_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    )
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(observability.settings, "jwt_private_key", fake_pem),
        patch.object(observability.settings, "encryption_master_key", "real-key"),
        patch.object(observability.settings, "langfuse_secret_key", "sk-langfuse"),
        patch.object(observability.settings, "langfuse_public_key", "pk-langfuse"),
        patch.object(
            observability.settings, "langfuse_host", "https://cloud.langfuse.com"
        ),
        patch.object(observability.settings, "langfuse_content_capture_ack", True),
    ):
        # Must not raise — every Langfuse production requirement is satisfied.
        create_app(redis_client=_NoopRedis())


def test_production_app_rejects_langfuse_secret_without_public_key() -> None:
    fake_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    )
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(observability.settings, "jwt_private_key", fake_pem),
        patch.object(observability.settings, "encryption_master_key", "real-key"),
        patch.object(observability.settings, "langfuse_secret_key", "sk-langfuse"),
        patch.object(observability.settings, "langfuse_public_key", ""),
        patch.object(observability.settings, "langfuse_content_capture_ack", True),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "LANGFUSE_PUBLIC_KEY" in str(exc)
        else:
            raise AssertionError(
                "production app started with Langfuse secret but no public key"
            )


def test_production_app_accepts_valid_pem_jwt_key() -> None:
    fake_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    )
    with (
        patch.object(observability.settings, "environment", "production"),
        patch.object(observability.settings, "frontend_url", "https://app.example.com"),
        patch.object(observability.settings, "metrics_token", "metrics-token"),
        patch.object(observability.settings, "jwt_private_key", fake_pem),
    ):
        try:
            create_app(redis_client=_NoopRedis())
        except RuntimeError as exc:
            assert "JWT_PRIVATE_KEY" not in str(
                exc
            ), f"Startup rejected a valid PEM key: {exc}"


def test_metrics_use_route_templates() -> None:
    with patch.object(observability.settings, "metrics_token", "test-metrics-token"):
        client = TestClient(create_app(redis_client=_NoopRedis()))
        client.get("/stages/not-a-uuid")
        metrics = client.get(
            "/metrics", headers={"Authorization": "Bearer test-metrics-token"}
        )

    assert 'path="/stages/{id}"' in metrics.text


def test_redact_sensitive_data_masks_nested_secrets() -> None:
    value = {
        "headers": {"Authorization": "Bearer access.token.value"},
        "openai_api_key": "sk-testsecret123456789",
        "google": "AIzaSyD-exampleGoogleSecretKey12345",
        "payload": [
            "refresh_token=refresh-token-value",
            "-----BEGIN PRIVATE KEY-----abc123-----END PRIVATE KEY-----",
        ],
    }

    redacted = redact_sensitive_data(value)

    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["openai_api_key"] == "[REDACTED]"
    assert redacted["google"] == "[REDACTED]"
    assert redacted["payload"] == ["refresh_token=[REDACTED]", "[REDACTED]"]


def test_redact_masks_github_app_private_key_and_installation_token() -> None:
    """T-283: the GitHub App private key (by key) and installation tokens (by
    key AND by value, wherever a ghs_/ghu_ token appears) are scrubbed."""
    value = {
        "github_app_private_key": "-----BEGIN RSA PRIVATE KEY-----abc-----END...",
        "inst_token": "ghs_1234567890abcdefghijklmnopqrstuvwxyz",
        "access_token": "ghu_abcdefghijklmnopqrstuvwxyz1234567890",
        "installation_token": "ghs_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        "note": "resolved token ghs_1234567890abcdefghijklmnopqrstuvwxyz for inst",
    }

    redacted = redact_sensitive_data(value)

    assert redacted["github_app_private_key"] == "[REDACTED]"
    assert redacted["inst_token"] == "[REDACTED]"
    assert redacted["access_token"] == "[REDACTED]"
    assert redacted["installation_token"] == "[REDACTED]"
    # The token value is scrubbed even when embedded in a free-text string under
    # a non-secret key.
    assert "ghs_" not in redacted["note"]
    assert "[REDACTED]" in redacted["note"]


def test_redact_masks_lemonsqueezy_secrets_and_nonce() -> None:
    """T-304/T-308: the Lemon API key, both webhook secrets, and the raw checkout
    nonce are scrubbed by key; the API-key JWT and the X-Signature hex are scrubbed
    by value wherever they appear. (The Stripe-Signature pattern was retired with
    the Stripe decommission — no Stripe signatures exist anymore.)"""
    value = {
        "lemonsqueezy_api_key": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123_-xyz",
        "lemonsqueezy_webhook_secret": "supersecretsigningvalue",
        "lemonsqueezy_webhook_secret_prev": "previoussigningvalue",
        "checkout_nonce": "raw-nonce-never-logged",
        "headers": {
            "X-Signature": "a" * 64,
        },
        "note": "key eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123_-xyz used",
        "log_line": "X-Signature: " + "e" * 64 + " verified",
    }

    redacted = redact_sensitive_data(value)

    assert redacted["lemonsqueezy_api_key"] == "[REDACTED]"
    assert redacted["lemonsqueezy_webhook_secret"] == "[REDACTED]"
    assert redacted["lemonsqueezy_webhook_secret_prev"] == "[REDACTED]"
    assert redacted["checkout_nonce"] == "[REDACTED]"
    # Signature header values are scrubbed by key (structured header fields).
    assert redacted["headers"]["X-Signature"] == "[REDACTED]"
    # The API-key JWT is scrubbed even embedded in free text under a non-secret key.
    assert "eyJhbGci" not in redacted["note"]
    assert "[REDACTED]" in redacted["note"]
    # A signature inline in a free-text log line is scrubbed by the keyed pattern.
    assert "e" * 64 not in redacted["log_line"]
    assert "[REDACTED]" in redacted["log_line"]


def test_redact_preserves_intentional_sha256_hashes() -> None:
    """T-304: bare 64-hex sha256 values we log on purpose (nonce_hash, payload_hash)
    are NOT scrubbed — the signature patterns are keyed on the header name so they
    never broad-match a hash."""
    value = {
        "checkout_nonce_hash": "c" * 64,
        "payload_hash": "d" * 64,
    }

    redacted = redact_sensitive_data(value)

    assert redacted["checkout_nonce_hash"] == "c" * 64
    assert redacted["payload_hash"] == "d" * 64


def test_structlog_redaction_processor_runs_before_rendering() -> None:
    event = redact_structlog_event(
        None,
        "info",
        {
            "event": "calling provider with sk-testsecret123456789",
            "Authorization": "Bearer access-token",
        },
    )

    assert event["event"] == "calling provider with [REDACTED]"
    assert event["Authorization"] == "[REDACTED]"


def test_sensitive_data_filter_scrubs_standard_log_record() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer access-token sk-testsecret123456789",
        args=(),
        exc_info=None,
    )
    record.api_key = "sk-testsecret123456789"

    assert SensitiveDataFilter().filter(record) is True

    assert record.getMessage() == "Authorization: [REDACTED] [REDACTED]"
    assert record.api_key == "[REDACTED]"


def test_sentry_before_send_redacts_event(monkeypatch) -> None:
    monkeypatch.setattr(observability.settings, "sentry_dsn", "https://key@sentry.io/1")
    monkeypatch.setattr(observability, "_sentry_configured", False)

    with patch.object(observability.sentry_sdk, "init") as mock_init:
        observability.setup_sentry()

    before_send = mock_init.call_args.kwargs["before_send"]
    event = {
        "request": {"headers": {"Authorization": "Bearer access-token"}},
        "extra": {"refresh_token": "refresh-token-value"},
        "message": "provider key sk-testsecret123456789",
    }

    redacted = before_send(event, {})

    assert redacted["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["extra"]["refresh_token"] == "[REDACTED]"
    assert redacted["message"] == "provider key [REDACTED]"

    monkeypatch.setattr(observability, "_sentry_configured", False)


def test_app_starts_without_observability_config() -> None:
    """create_app() must not raise when Sentry/OTLP env vars are absent."""
    with (
        patch.object(observability.settings, "sentry_dsn", ""),
        patch.object(observability.settings, "grafana_otlp_endpoint", ""),
        patch.object(observability.settings, "grafana_otlp_token", ""),
    ):
        app = create_app(redis_client=_NoopRedis())
    assert app is not None


def test_lifespan_flushes_langfuse_on_shutdown() -> None:
    """Application shutdown must drain the Langfuse SDK's event queue. A
    rolling deploy or SIGTERM during a Railway restart otherwise drops the
    final batch of traces silently."""
    from unittest.mock import AsyncMock

    from services import langfuse_service

    flushed = AsyncMock()

    class _StubClient:
        enabled = False  # skip startup_check in lifespan — T-221

        async def flush(self) -> None:
            await flushed()

    with (
        patch.object(observability.settings, "metrics_token", "test-metrics-token"),
        patch.object(
            langfuse_service, "get_langfuse_client", return_value=_StubClient()
        ),
    ):
        # Entering the TestClient context fires lifespan startup; exiting
        # fires lifespan teardown, which is where flush() must run.
        with TestClient(create_app(redis_client=_NoopRedis())):
            pass

    flushed.assert_awaited_once()
