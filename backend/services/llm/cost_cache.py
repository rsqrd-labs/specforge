"""Redis-backed cache for LLM generation outputs.

This module makes Redis calls (not LLM HTTP calls).  HTTP timeout policy
(H-6 — T-182): timeout= enforcement belongs to each adapter's httpx.Timeout.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

DEFAULT_GENERATION_CACHE_TTL_SECONDS = 60 * 60 * 24
GENERATION_CACHE_PREFIX = "llmcache:v1:"


def build_generation_cache_key(
    *,
    prompt_version: str,
    stage_type: str,
    operation: str,
    provider: str,
    model: str,
    model_tier: str,
    problem_statement_hash: str,
    upstream_artifact_hashes: Mapping[str, str],
    user_instruction_hash: str,
    output_contract_version: str,
) -> str:
    payload = {
        "prompt_version": prompt_version,
        "stage_type": stage_type,
        "operation": operation,
        "provider": provider,
        "model": model,
        "model_tier": model_tier,
        "problem_statement_hash": problem_statement_hash,
        "upstream_artifact_hashes": dict(sorted(upstream_artifact_hashes.items())),
        "user_instruction_hash": user_instruction_hash,
        "output_contract_version": output_contract_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{GENERATION_CACHE_PREFIX}{digest}"


async def get_cached_generation(redis, key: str) -> str | None:
    value = await redis.get(key)
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


async def set_cached_generation(
    redis,
    key: str,
    output: str,
    ttl_seconds: int = DEFAULT_GENERATION_CACHE_TTL_SECONDS,
) -> None:
    await redis.set(key, output, ex=ttl_seconds)
