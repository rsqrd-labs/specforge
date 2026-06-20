from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from services.pipeline import tech_safety
from services.pipeline.tech_safety import (
    TechSafetyError,
    analyze_technology_safety,
    parse_technology_stack,
    validate_technology_safety,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self.store[key] = value


def _plan_table(*rows: str) -> str:
    return "\n".join(
        [
            "## Technology Stack and Rationale",
            "",
            (
                "| Layer | Choice | Version (latest stable as of YYYY-MM) | "
                "Support status | EOL date | Why not the next-best alternative |"
            ),
            "|---|---|---|---|---|---|",
            *rows,
        ]
    )


def test_parse_technology_stack_table_extracts_required_columns() -> None:
    artifact = _plan_table(
        "| language | Python | 3.12 latest stable as of 2026-06 | "
        "Active | 2028-10-31 | Better ecosystem than Go |"
    )

    choices = parse_technology_stack(artifact)

    assert len(choices) == 1
    assert choices[0].layer == "language"
    assert choices[0].choice == "Python"
    assert choices[0].version == "3.12"
    assert choices[0].support_status == "Active"
    assert choices[0].eol_date == "2028-10-31"


@pytest.mark.asyncio
async def test_validate_technology_safety_blocks_deprecated_support_status() -> None:
    artifact = _plan_table(
        "| framework | LegacyJS | 1.0.0 | Deprecated (do not use) | "
        "2024-01-01 | React is heavier |"
    )

    with pytest.raises(TechSafetyError) as exc_info:
        await validate_technology_safety("plan", artifact, {}, redis=_FakeRedis())

    assert exc_info.value.findings[0].code == "support_status_blocked"
    assert exc_info.value.findings[0].technology == "LegacyJS"


@pytest.mark.asyncio
async def test_validate_technology_safety_blocks_hard_denylist_choices() -> None:
    artifact = _plan_table(
        "| language | Python 3.10 | 3.10 | Active | 2026-10-04 | It is familiar |",
        "| LLM provider | gpt-3.5-turbo | 2026-06 | Active | n/a | Cheap |",
    )

    findings = await analyze_technology_safety("plan", artifact, {}, redis=_FakeRedis())
    codes = {finding.code for finding in findings}

    assert "runtime_eol" in codes
    assert "deprecated_model_family" in codes


@pytest.mark.asyncio
async def test_validate_technology_safety_fails_when_policy_is_stale(
    monkeypatch,
) -> None:
    policy = dict(tech_safety.load_policy())
    policy["last_reviewed"] = "2025-01-01"
    monkeypatch.setattr(tech_safety, "load_policy", lambda: policy)

    with pytest.raises(TechSafetyError) as exc_info:
        await validate_technology_safety(
            "spec",
            "## Constraints\nNo implementation choices.",
            {},
            redis=_FakeRedis(),
            today=date(2026, 6, 9),
        )

    assert exc_info.value.findings[0].code == "technology_policy_stale"


@pytest.mark.asyncio
async def test_validate_technology_safety_blocks_osv_high_advisory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/querybatch"
        body = json.loads(request.content)
        assert body["queries"][0]["package"]["name"] == "fastapi"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "vulns": [
                            {
                                "id": "GHSA-test",
                                "database_specific": {"severity": "HIGH"},
                            }
                        ]
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.osv.dev"
    ) as client:
        with pytest.raises(TechSafetyError) as exc_info:
            await validate_technology_safety(
                "tasks",
                "Install FastAPI with `pip install fastapi==0.95.0`.",
                {"plan": ""},
                redis=_FakeRedis(),
                http_client=client,
            )

    assert exc_info.value.findings[0].code == "vulnerable_dependency"
    assert exc_info.value.findings[0].severity == "high"


@pytest.mark.asyncio
async def test_validate_technology_safety_uses_cached_lifecycle_lookup() -> None:
    artifact = _plan_table(
        "| Runtime | Python | 3.12.1 | Active |  | Supported runtime |"
    )
    redis = _FakeRedis()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/products/python/releases/3.12"
        return httpx.Response(
            200,
            json={
                "result": {
                    "name": "3.12",
                    "isEol": True,
                    "eolFrom": "2025-10-31",
                    "isMaintained": False,
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://endoflife.date/api/v1",
    ) as client:
        with pytest.raises(TechSafetyError) as exc_info:
            await validate_technology_safety(
                "plan",
                artifact,
                {},
                redis=redis,
                http_client=client,
            )

    assert exc_info.value.findings[0].code == "technology_eol"
    assert exc_info.value.findings[0].source == "endoflife.date"
    assert redis.store
