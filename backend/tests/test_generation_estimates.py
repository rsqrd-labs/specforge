"""Tests for the honest generation-ETA rollup — issue #21 Phase 2b.

Covers the ledger aggregation shape, the ledger→client normalisation/filtering,
the Redis cache write/read (including malformed-blob robustness), and the
read-only endpoint (cache hit and cache miss → empty fallback)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from database import get_redis
from main import create_app
from middleware.auth import get_current_user
from models import User
from services.llm import generation_estimates as ge
from services.llm.cost_ledger import generation_latency_percentiles

_USER = User(
    id=uuid4(),
    email="eta@example.com",
    google_id="google-eta",
    name="Eta User",
    avatar_url=None,
    created_at=datetime.now(UTC),
)


# --------------------------------------------------------------------------- #
# generation_latency_percentiles — python mapping/coercion shape
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_generation_latency_percentiles_shape() -> None:
    class _Row:
        operation = "spec.generate"
        provider = "anthropic"
        stage_type = "spec"
        samples = 120
        p50_latency_ms = 28000
        p90_latency_ms = 71000

    class _DB:
        async def execute(self, stmt):
            return [_Row()]

    rows = await generation_latency_percentiles(_DB(), since=datetime.now(UTC))
    assert rows == [
        {
            "operation": "spec.generate",
            "provider": "anthropic",
            "stage_type": "spec",
            "samples": 120,
            "p50_latency_ms": 28000,
            "p90_latency_ms": 71000,
        }
    ]


# --------------------------------------------------------------------------- #
# _normalise_operation — ledger op → (stage, lookup_op)
# --------------------------------------------------------------------------- #
def test_normalise_maps_each_stage_generate_to_generate() -> None:
    for stage in ("spec", "plan", "harness", "tasks"):
        assert ge._normalise_operation(f"{stage}.generate", stage) == (
            stage,
            "generate",
        )


def test_normalise_maps_refine_focused_using_stage_type_column() -> None:
    assert ge._normalise_operation("refine.focused", "plan") == (
        "plan",
        "focused-patch",
    )


def test_normalise_rejects_refine_focused_with_unknown_stage() -> None:
    assert ge._normalise_operation("refine.focused", "") is None
    assert ge._normalise_operation("refine.focused", "mystery") is None


def test_normalise_drops_operations_we_do_not_serve() -> None:
    # regenerate.full, critic.review, eval.score, harness patch op, etc. → heuristic.
    for op in ("regenerate.full", "critic.review", "eval.score", "refine.section"):
        assert ge._normalise_operation(op, "spec") is None


# --------------------------------------------------------------------------- #
# compute_generation_estimates — filtering, ms→s + tail, sane band, order
# --------------------------------------------------------------------------- #
def _patch_rows(monkeypatch, rows):
    async def _fake(db, *, since=None, operations=None):
        return rows

    monkeypatch.setattr(ge, "generation_latency_percentiles", _fake)


@pytest.mark.asyncio
async def test_compute_converts_ms_to_seconds_and_adds_pipeline_tail(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_min_samples", 50)
    monkeypatch.setattr(ge.settings, "generation_estimates_pipeline_tail_seconds", 4)
    _patch_rows(
        monkeypatch,
        [
            {
                "operation": "plan.generate",
                "provider": "openai",
                "stage_type": "plan",
                "samples": 200,
                "p50_latency_ms": 41000,  # 41s
                "p90_latency_ms": 96000,  # 96s
            }
        ],
    )
    estimates = await ge.compute_generation_estimates(object())
    assert estimates == [
        {
            "stage": "plan",
            "operation": "generate",
            "p50": 45,  # round(41) + 4
            "p90": 100,  # round(96) + 4
            "n": 200,
        }
    ]


@pytest.mark.asyncio
async def test_compute_drops_rows_below_min_samples(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_min_samples", 50)
    _patch_rows(
        monkeypatch,
        [
            {
                "operation": "spec.generate",
                "provider": "anthropic",
                "stage_type": "spec",
                "samples": 49,  # below threshold
                "p50_latency_ms": 30000,
                "p90_latency_ms": 70000,
            }
        ],
    )
    assert await ge.compute_generation_estimates(object()) == []


@pytest.mark.asyncio
async def test_compute_drops_unmapped_and_out_of_band_rows(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_min_samples", 1)
    monkeypatch.setattr(ge.settings, "generation_estimates_pipeline_tail_seconds", 0)
    _patch_rows(
        monkeypatch,
        [
            # Unmapped operation → dropped.
            {
                "operation": "regenerate.full",
                "provider": "anthropic",
                "stage_type": "spec",
                "samples": 500,
                "p50_latency_ms": 30000,
                "p90_latency_ms": 70000,
            },
            # Absurdly long p90 (beyond the sane band) → dropped.
            {
                "operation": "tasks.generate",
                "provider": "google",
                "stage_type": "tasks",
                "samples": 500,
                "p50_latency_ms": 30000,
                "p90_latency_ms": 9_000_000,  # 9000s > 3600 cap
            },
        ],
    )
    assert await ge.compute_generation_estimates(object()) == []


@pytest.mark.asyncio
async def test_compute_ignores_provider_identity(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_min_samples", 1)
    monkeypatch.setattr(ge.settings, "generation_estimates_pipeline_tail_seconds", 0)
    _patch_rows(
        monkeypatch,
        [
            {
                "operation": "spec.generate",
                "provider": "mystery-provider",
                "stage_type": "spec",
                "samples": 500,
                "p50_latency_ms": 30000,
                "p90_latency_ms": 70000,
            }
        ],
    )
    result = await ge.compute_generation_estimates(object())
    assert result[0]["stage"] == "spec"
    assert "provider" not in result[0]


@pytest.mark.asyncio
async def test_compute_maps_refine_focused_and_sorts_output(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_min_samples", 1)
    monkeypatch.setattr(ge.settings, "generation_estimates_pipeline_tail_seconds", 0)
    _patch_rows(
        monkeypatch,
        [
            {
                "operation": "spec.generate",
                "provider": "openai",
                "stage_type": "spec",
                "samples": 80,
                "p50_latency_ms": 30000,
                "p90_latency_ms": 70000,
            },
            {
                "operation": "refine.focused",
                "provider": "anthropic",
                "stage_type": "harness",
                "samples": 60,
                "p50_latency_ms": 12000,
                "p90_latency_ms": 30000,
            },
        ],
    )
    estimates = await ge.compute_generation_estimates(object())
    assert [(e["stage"], e["operation"]) for e in estimates] == [
        ("harness", "focused-patch"),
        ("spec", "generate"),
    ]


# --------------------------------------------------------------------------- #
# Redis cache — write/read/robustness
# --------------------------------------------------------------------------- #
class _FakeRedis:
    """Minimal async Redis double: an in-memory string store."""

    def __init__(self, store=None) -> None:
        self.store = dict(store or {})
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))


@pytest.mark.asyncio
async def test_refresh_writes_payload_with_ttl(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_enabled", True)
    monkeypatch.setattr(ge.settings, "generation_estimates_cache_ttl_seconds", 900)

    async def _fake_compute(db, *, now=None):
        return [
            {
                "provider": "anthropic",
                "stage": "spec",
                "operation": "generate",
                "p50": 30,
                "p90": 70,
                "n": 100,
            }
        ]

    monkeypatch.setattr(ge, "compute_generation_estimates", _fake_compute)
    redis = _FakeRedis()
    count = await ge.refresh_generation_estimates_cache(redis, object())

    assert count == 1
    assert len(redis.set_calls) == 1
    key, value, ttl = redis.set_calls[0]
    assert key == ge.CACHE_KEY
    assert ttl == 900
    payload = json.loads(value)
    assert payload["estimates"][0]["stage"] == "spec"
    assert payload["generated_at"] is not None


@pytest.mark.asyncio
async def test_refresh_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(ge.settings, "generation_estimates_enabled", False)
    redis = _FakeRedis()
    count = await ge.refresh_generation_estimates_cache(redis, object())
    assert count == 0
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_read_returns_cached_payload() -> None:
    payload = {
        "estimates": [
            {
                "provider": "anthropic",
                "stage": "spec",
                "operation": "generate",
                "p50": 30,
                "p90": 70,
                "n": 100,
            }
        ],
        "generated_at": "2026-06-15T00:00:00+00:00",
    }
    redis = _FakeRedis({ge.CACHE_KEY: json.dumps(payload)})
    result = await ge.read_generation_estimates(redis)
    assert result == payload


@pytest.mark.asyncio
async def test_read_empty_on_cache_miss() -> None:
    result = await ge.read_generation_estimates(_FakeRedis())
    assert result == {"estimates": [], "generated_at": None}


@pytest.mark.asyncio
async def test_read_empty_on_malformed_blob() -> None:
    redis = _FakeRedis({ge.CACHE_KEY: "{not valid json"})
    assert await ge.read_generation_estimates(redis) == {
        "estimates": [],
        "generated_at": None,
    }


@pytest.mark.asyncio
async def test_read_empty_when_estimates_not_a_list() -> None:
    redis = _FakeRedis({ge.CACHE_KEY: json.dumps({"estimates": {"bad": 1}})})
    assert await ge.read_generation_estimates(redis) == {
        "estimates": [],
        "generated_at": None,
    }


@pytest.mark.asyncio
async def test_read_empty_when_redis_get_raises() -> None:
    class _BrokenRedis:
        async def get(self, key):
            raise RuntimeError("redis down")

    assert await ge.read_generation_estimates(_BrokenRedis()) == {
        "estimates": [],
        "generated_at": None,
    }


# --------------------------------------------------------------------------- #
# Endpoint — pure cache read, authed
# --------------------------------------------------------------------------- #
def _app(redis):
    app = create_app(redis_client=redis)
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_redis] = lambda: redis
    return app


@pytest.mark.asyncio
async def test_endpoint_returns_cached_estimates() -> None:
    payload = {
        "estimates": [
            {
                "stage": "plan",
                "operation": "generate",
                "p50": 45,
                "p90": 100,
                "n": 200,
            }
        ],
        "generated_at": "2026-06-15T00:00:00+00:00",
    }
    redis = _FakeRedis({ge.CACHE_KEY: json.dumps(payload)})
    app = _app(redis)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/stages/generation-estimates")

    assert response.status_code == 200
    data = response.json()
    assert data["estimates"] == payload["estimates"]
    # generated_at round-trips through the pydantic datetime (Z vs +00:00 form);
    # compare the parsed instant, not the string spelling.
    assert datetime.fromisoformat(data["generated_at"]) == datetime.fromisoformat(
        payload["generated_at"]
    )


@pytest.mark.asyncio
async def test_endpoint_returns_empty_on_cache_miss() -> None:
    app = _app(_FakeRedis())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/stages/generation-estimates")

    assert response.status_code == 200
    assert response.json() == {"estimates": [], "generated_at": None}
