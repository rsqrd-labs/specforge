from __future__ import annotations

import json
import time

import pytest

from config import settings
from services import queue


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.depth = 0
        self.oldest: list[tuple[str, float]] = []

    async def set(self, key: str, value: str, *, ex: int) -> None:
        del ex
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def zcard(self, _key: str) -> int:
        return self.depth

    async def zrange(
        self, _key: str, _start: int, _end: int, *, withscores: bool
    ) -> list[tuple[str, float]]:
        assert withscores is True
        return self.oldest


@pytest.mark.asyncio
async def test_generation_worker_heartbeat_makes_matching_revision_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-current")
    redis = _Redis()

    await queue.record_generation_worker_heartbeat(redis)  # type: ignore[arg-type]
    snapshot = await queue.generation_worker_snapshot(redis)  # type: ignore[arg-type]

    assert snapshot["ready"] is True
    assert snapshot["revision"] == "sha-current"
    assert snapshot["heartbeat_age_seconds"] is not None


@pytest.mark.asyncio
async def test_old_revision_cannot_make_new_api_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-old")
    await queue.record_generation_worker_heartbeat(redis)  # type: ignore[arg-type]

    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-new")
    snapshot = await queue.generation_worker_snapshot(redis)  # type: ignore[arg-type]

    assert snapshot["ready"] is False
    assert snapshot["revision"] == "sha-new"


@pytest.mark.asyncio
async def test_stale_heartbeat_fails_closed_and_queue_is_still_sampled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-current")
    redis = _Redis()
    key = queue._generation_worker_heartbeat_key()  # noqa: SLF001
    redis.values[key] = json.dumps(
        {
            "revision": "sha-current",
            "recorded_at": time.time()
            - queue.GENERATION_WORKER_HEARTBEAT_TTL_SECONDS
            - 1,
        }
    )
    redis.depth = 7
    redis.oldest = [("job", time.time() * 1000 - 12_000)]

    snapshot = await queue.generation_worker_snapshot(redis)  # type: ignore[arg-type]

    assert snapshot["ready"] is False
    assert snapshot["queue_depth"] == 7
    assert snapshot["oldest_job_age_seconds"] == pytest.approx(12, abs=1)


def test_readiness_enforcement_is_production_and_staging_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "generation_worker_readiness_required", True)
    for environment in ("production", "staging"):
        monkeypatch.setattr(settings, "environment", environment)
        assert queue.generation_worker_readiness_enforced() is True
    for environment in ("development", "test"):
        monkeypatch.setattr(settings, "environment", environment)
        assert queue.generation_worker_readiness_enforced() is False
