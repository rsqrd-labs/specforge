from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from services.llm.cost_cache import (
    GENERATION_CACHE_PREFIX,
    build_generation_cache_key,
    get_cached_generation,
    set_cached_generation,
)


def _key(**overrides) -> str:
    payload = {
        "prompt_version": "asdd-v1",
        "stage_type": "tasks",
        "operation": "tasks.generate",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "model_tier": "mini",
        "problem_statement_hash": "problem-a",
        "upstream_artifact_hashes": {"spec": "spec-a", "plan": "plan-a"},
        "user_instruction_hash": "instruction-a",
        "output_contract_version": "tasks-v1",
    }
    payload.update(overrides)
    return build_generation_cache_key(**payload)


def test_cache_key_is_stable_and_prefixed() -> None:
    first = _key()
    second = _key(upstream_artifact_hashes={"plan": "plan-a", "spec": "spec-a"})

    assert first == second
    assert first.startswith(GENERATION_CACHE_PREFIX)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_version", "asdd-v2"),
        ("stage_type", "harness"),
        ("operation", "harness.generate"),
        ("provider", "anthropic"),
        ("model", "claude-haiku-4-5-20251001"),
        ("model_tier", "small"),
        ("problem_statement_hash", "problem-b"),
        ("upstream_artifact_hashes", {"spec": "spec-b", "plan": "plan-a"}),
        ("user_instruction_hash", "instruction-b"),
        ("output_contract_version", "tasks-v2"),
    ],
)
def test_cache_key_changes_for_semantic_inputs(field: str, value) -> None:
    assert _key(**{field: value}) != _key()


class _RedisStub:
    def __init__(self) -> None:
        self.values: dict[str, str | bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex


@pytest.mark.asyncio
async def test_cache_helpers_round_trip_completed_output() -> None:
    redis = _RedisStub()
    key = _key()

    assert await get_cached_generation(redis, key) is None
    await set_cached_generation(redis, key, "complete output", ttl_seconds=30)

    assert await get_cached_generation(redis, key) == "complete output"
    assert redis.ttls[key] == 30


@pytest.mark.asyncio
async def test_cache_outage_is_fail_open_for_reads_and_writes() -> None:
    class _DownRedis:
        async def get(self, _key: str):
            raise RedisConnectionError("down")

        async def set(self, _key: str, _value: str, ex: int) -> None:
            del ex
            raise RedisConnectionError("down")

    redis = _DownRedis()
    assert await get_cached_generation(redis, _key()) is None
    await set_cached_generation(redis, _key(), "valid persisted output")


@pytest.mark.asyncio
async def test_cache_invalid_utf8_is_a_miss() -> None:
    redis = _RedisStub()
    redis.values[_key()] = b"\xff\xfe"

    assert await get_cached_generation(redis, _key()) is None
