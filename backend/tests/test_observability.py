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
    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


def test_metrics_endpoint_exposes_prometheus_metrics() -> None:
    client = TestClient(create_app(redis_client=_NoopRedis()))

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_metrics_use_route_templates() -> None:
    client = TestClient(create_app(redis_client=_NoopRedis()))

    client.get("/stages/not-a-uuid")
    metrics = client.get("/metrics")

    assert 'path="/stages/{stage_id}"' in metrics.text


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
