from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from config import Settings
from services.llm.model_catalog import MODEL_CATALOG, model_request_policy
from services.llm.openai_adapter import OpenAIAdapter
from services.llm.prompt_cache import build_prompt_cache_policy


def _policy(*, user: str = "dynamic workspace artifact", retention: str = "memory"):
    return build_prompt_cache_policy(
        namespace="stage_generation",
        stage_type="plan",
        mode="standard",
        prompt_version="asdd-v1:plan-v1",
        system_prompt="stable system instructions",
        base_user_prompt=user,
        retention=retention,
    )


def _adapter(request_policy: dict) -> OpenAIAdapter:
    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "any-openai-model"
    adapter._request_policy = request_policy
    adapter._client = MagicMock()
    return adapter


def test_logical_policy_is_model_agnostic_and_tenant_safe() -> None:
    policy = _policy()

    assert "gpt" not in policy.routing_key
    assert "mini" not in policy.routing_key
    assert "dynamic workspace artifact" not in policy.routing_key
    assert len(policy.routing_key) <= 64


def test_dynamic_prefix_changes_fingerprint_not_routing_bucket() -> None:
    first = _policy(user="workspace A")
    second = _policy(user="workspace B")

    assert first.routing_key == second.routing_key
    assert first.eligible_prefix_fingerprint != second.eligible_prefix_fingerprint


def test_prompt_contract_or_system_change_rotates_routing_bucket() -> None:
    base = _policy()
    version_changed = build_prompt_cache_policy(
        namespace="stage_generation",
        stage_type="plan",
        mode="standard",
        prompt_version="asdd-v2:plan-v1",
        system_prompt="stable system instructions",
        base_user_prompt="dynamic workspace artifact",
    )
    system_changed = build_prompt_cache_policy(
        namespace="stage_generation",
        stage_type="plan",
        mode="standard",
        prompt_version="asdd-v1:plan-v1",
        system_prompt="changed system instructions",
        base_user_prompt="dynamic workspace artifact",
    )

    routing_keys = {
        base.routing_key,
        version_changed.routing_key,
        system_changed.routing_key,
    }
    assert len(routing_keys) == 3


@pytest.mark.parametrize(
    "entry",
    [entry for entry in MODEL_CATALOG if entry.provider == "openai"],
)
def test_every_catalogued_openai_model_declares_cache_capabilities(entry) -> None:
    policy = model_request_policy("openai", entry.model_id)

    assert policy["automatic_prompt_caching"] is True
    assert policy["prompt_cache_key"] is True
    assert policy["cached_token_accounting"] is True
    assert policy["minimum_cacheable_input_tokens"] == 1024


def test_responses_request_uses_same_key_for_any_capable_model() -> None:
    policy = _policy()
    request_policy = {
        "adapter_api": "responses",
        "reasoning_effort": None,
        "prompt_cache_key": True,
        "extended_prompt_cache_retention": True,
    }
    first = _adapter(request_policy)
    second = _adapter(request_policy)
    first.model = "model-a"
    second.model = "model-b"

    first_request = first._responses_request(
        system="sys", user="user", max_tokens=100, stream=True, cache_policy=policy
    )
    second_request = second._responses_request(
        system="sys", user="user", max_tokens=100, stream=True, cache_policy=policy
    )

    assert first_request["prompt_cache_key"] == second_request["prompt_cache_key"]
    assert first_request["model"] != second_request["model"]


def test_extended_retention_is_opt_in_and_capability_gated() -> None:
    capable = _adapter(
        {
            "adapter_api": "responses",
            "reasoning_effort": None,
            "prompt_cache_key": True,
            "extended_prompt_cache_retention": True,
        }
    )
    unsupported = _adapter(
        {
            "adapter_api": "responses",
            "reasoning_effort": None,
            "prompt_cache_key": False,
            "extended_prompt_cache_retention": False,
        }
    )

    memory_request = capable._responses_request(
        system="sys", user="user", max_tokens=100, stream=False, cache_policy=_policy()
    )
    extended_request = capable._responses_request(
        system="sys",
        user="user",
        max_tokens=100,
        stream=False,
        cache_policy=_policy(retention="24h"),
    )
    unsupported_request = unsupported._responses_request(
        system="sys",
        user="user",
        max_tokens=100,
        stream=False,
        cache_policy=_policy(retention="24h"),
    )

    assert "prompt_cache_retention" not in memory_request
    assert extended_request["prompt_cache_retention"] == "24h"
    assert "prompt_cache_key" not in unsupported_request
    assert "prompt_cache_retention" not in unsupported_request


def test_openai_cache_retention_configuration_is_validated() -> None:
    assert (
        Settings(openai_prompt_cache_retention="MEMORY").openai_prompt_cache_retention
        == "memory"
    )
    assert (
        Settings(openai_prompt_cache_retention="24h").openai_prompt_cache_retention
        == "24h"
    )
    with pytest.raises(ValidationError):
        Settings(openai_prompt_cache_retention="forever")
