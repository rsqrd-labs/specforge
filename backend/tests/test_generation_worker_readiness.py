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
    assert snapshot["observed_revision"] == "sha-current"
    assert snapshot["revision_matched"] is True
    assert snapshot["heartbeat_age_seconds"] is not None


@pytest.mark.asyncio
async def test_live_worker_on_another_revision_still_drains_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readiness is liveness, not code identity.

    The API and the worker are separately deployed Railway services building the
    same commit. Refusing paid generation for the minute between the two deploys
    landing — or after a backend-only redeploy — is an outage we would be causing
    ourselves, so a live heartbeat from another revision is ready-but-logged.
    """

    monkeypatch.setattr(settings, "generation_worker_revision_match_required", False)
    redis = _Redis()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-old")
    await queue.record_generation_worker_heartbeat(redis)  # type: ignore[arg-type]

    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-new")
    snapshot = await queue.generation_worker_snapshot(redis)  # type: ignore[arg-type]

    assert snapshot["ready"] is True
    assert snapshot["revision"] == "sha-new"
    assert snapshot["observed_revision"] == "sha-old"
    assert snapshot["revision_matched"] is False


@pytest.mark.asyncio
async def test_strict_mode_restores_revision_pinned_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "generation_worker_revision_match_required", True)
    redis = _Redis()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-old")
    await queue.record_generation_worker_heartbeat(redis)  # type: ignore[arg-type]

    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-new")
    snapshot = await queue.generation_worker_snapshot(redis)  # type: ignore[arg-type]

    assert snapshot["ready"] is False
    assert snapshot["revision_matched"] is False


@pytest.mark.asyncio
async def test_no_heartbeat_at_all_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate that matters: nothing is draining, so nobody may be charged."""

    monkeypatch.setattr(settings, "generation_worker_revision_match_required", False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-current")

    snapshot = await queue.generation_worker_snapshot(_Redis())  # type: ignore[arg-type]

    assert snapshot["ready"] is False
    assert snapshot["observed_revision"] is None


@pytest.mark.asyncio
async def test_stale_heartbeat_fails_closed_and_queue_is_still_sampled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "generation_worker_revision_match_required", False)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-current")
    redis = _Redis()
    redis.values[queue.GENERATION_WORKER_HEARTBEAT_KEY] = json.dumps(
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


@pytest.mark.asyncio
async def test_snapshot_samples_the_queue_generation_actually_lands_on() -> None:
    """The gate reads the lane ``queue_for_job`` routes ``stage_generate`` to."""

    sampled: list[str] = []

    class _RecordingRedis(_Redis):
        async def zcard(self, key: str) -> int:
            sampled.append(key)
            return 0

        async def zrange(
            self, key: str, _start: int, _end: int, *, withscores: bool
        ) -> list[tuple[str, float]]:
            assert withscores is True
            sampled.append(key)
            return []

    await queue.generation_worker_snapshot(_RecordingRedis())  # type: ignore[arg-type]

    assert set(sampled) == {queue.queue_for_job("stage_generate")}


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
