from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app


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
