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
    render_hard_denylist_prose,
    validate_technology_safety,
)


# ---------------------------------------------------------------------------
# Audit finding #7: plan.py's prose denylist is now generated from this
# policy (the deterministic gate's own single source of truth) instead of
# hand-duplicated, so the two can no longer silently drift apart.
# ---------------------------------------------------------------------------
def test_render_hard_denylist_prose_names_every_entry() -> None:
    prose = render_hard_denylist_prose()
    for expected in (
        "Python",
        "Node.js",
        "Java",
        "OpenAI GPT-3 family",
        "Google Gemini 1.x family",
        "Anthropic Claude 1.x/2.x family",
    ):
        assert expected in prose


def test_render_hard_denylist_prose_includes_version_thresholds() -> None:
    # denied_versions is authored right next to the enforcement regex in the
    # JSON, so the model-facing threshold and the machine-enforced one can
    # never silently disagree.
    prose = render_hard_denylist_prose()
    assert "Python ≤ 3.10" in prose
    assert "Node.js ≤ 18" in prose
    assert "Java ≤ 11" in prose


def test_render_hard_denylist_prose_reflects_policy_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A policy edit (new entry, changed threshold) must appear in the
    rendered prose without any change to plan.py — proving the two files
    cannot drift apart, closing the actual finding."""
    policy = dict(tech_safety.load_policy())
    policy["hard_denylists"] = [
        {
            "code": "runtime_eol",
            "technology": "Ruby",
            "denied_versions": "≤ 2.7",
            "pattern": r"\bruby\s*2\.7\b",
            "severity": "critical",
            "remediation": "Use a supported Ruby release.",
        }
    ]
    monkeypatch.setattr(tech_safety, "load_policy", lambda: policy)
    assert render_hard_denylist_prose() == "Ruby ≤ 2.7"


def test_plan_prompt_denylist_last_reviewed_matches_policy_last_reviewed() -> None:
    """The two freshness clocks named in finding #7 must move together: a
    reviewer who re-reviews one without the other is exactly the drift this
    fix closes. This is a CI check, not a hand-maintained reminder."""
    from prompts.plan import DENYLIST_LAST_REVIEWED

    policy = tech_safety.load_policy()
    assert DENYLIST_LAST_REVIEWED == policy["last_reviewed"], (
        "backend/prompts/plan.py's DENYLIST_LAST_REVIEWED and "
        "tech_safety_policy.json's last_reviewed must be updated together — "
        "they document the same review of the same denylist facts."
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


def _demo_day_plan_table(*rows: str) -> str:
    """A Demo Day-shaped Technology Stack table: the leaner heading (no "and
    Rationale") and the leaner 3-column shape Demo Day's own prompt asks for
    (no Support status / EOL date columns) — the real shape this parser must
    tolerate, not just the standard 6-column table `_plan_table` builds."""
    return "\n".join(
        [
            "## Technology Stack",
            "",
            "| Layer | Choice | Version |",
            "|---|---|---|",
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


def test_parse_technology_stack_resolves_demo_day_heading() -> None:
    # Regression: `## Technology Stack` (no "and Rationale") previously never
    # matched the hardcoded standard-only heading, so parse_technology_stack
    # silently returned [] for every Demo Day plan.
    artifact = _demo_day_plan_table("| Runtime | Python | 3.12.1 |")

    choices = parse_technology_stack(artifact)

    assert len(choices) == 1
    assert choices[0].layer == "Runtime"
    assert choices[0].choice == "Python"
    assert choices[0].version == "3.12.1"


def test_parse_technology_stack_still_prefers_standard_heading() -> None:
    # Regression pin: standard-mode artifacts (the more specific heading)
    # resolve exactly as before the heading-tuple fix.
    artifact = _plan_table(
        "| language | Python | 3.12 latest stable as of 2026-06 | "
        "Active | 2028-10-31 | Better ecosystem than Go |"
    )

    choices = parse_technology_stack(artifact)

    assert len(choices) == 1
    assert choices[0].source.startswith("## Technology Stack and Rationale:")


def test_demo_day_missing_optional_columns_parses_without_crash() -> None:
    # Demo Day's own prompt (pre Fix 2 in this same change) never asked for
    # Support status / EOL date columns at all; the relaxed header gate must
    # still recognise the table and default the missing fields to None rather
    # than requiring them to even see the table as a header row.
    artifact = _demo_day_plan_table("| Cache | Redis | 7.4 |")

    choices = parse_technology_stack(artifact)

    assert len(choices) == 1
    assert choices[0].support_status is None
    assert choices[0].eol_date is None


@pytest.mark.asyncio
async def test_demo_day_support_status_blocked_when_declared() -> None:
    # Once a Demo Day table DOES carry a Support status column (Fix 2), the
    # same structured block that already protects standard mode must fire for
    # Demo Day too -- this is the actual regression the heading fix closes.
    artifact = "\n".join(
        [
            "## Technology Stack",
            "",
            "| Layer | Choice | Version | Support status | EOL date |",
            "|---|---|---|---|---|",
            "| framework | LegacyJS | 1.0.0 | Deprecated | 2024-01-01 |",
        ]
    )

    with pytest.raises(TechSafetyError) as exc_info:
        await validate_technology_safety(
            "plan", artifact, {}, redis=_FakeRedis(), today=date(2026, 8, 5)
        )

    assert exc_info.value.findings[0].code == "support_status_blocked"
    assert exc_info.value.findings[0].technology == "LegacyJS"


@pytest.mark.asyncio
async def test_plan_denylist_scans_whole_document_not_just_tech_stack_section() -> None:
    # The hard denylist must catch a denylisted runtime named OUTSIDE the
    # Technology Stack table -- e.g. a Demo Day restricted-environment
    # Environment and Bootstrap install command -- for both modes. Narrowing
    # the scan to only the resolved Technology Stack section (a tempting
    # side effect of fixing the heading mismatch) would have silently dropped
    # this coverage instead of just fixing the bug.
    standard_artifact = "\n\n".join(
        [
            _plan_table("| language | Go | 1.22 | Active | n/a | Fast enough |"),
            "## Deployment and Operations",
            "Bootstrap: run `python 3.9 -m venv .venv` for the local tooling shim.",
        ]
    )
    demo_day_artifact = "\n\n".join(
        [
            _demo_day_plan_table("| Language | Go | 1.22 |"),
            "## Environment and Bootstrap",
            "Bootstrap: run `python 3.9 -m venv .venv` for the local tooling shim.",
        ]
    )

    for artifact in (standard_artifact, demo_day_artifact):
        findings = await analyze_technology_safety(
            "plan", artifact, {}, redis=_FakeRedis(), today=date(2026, 8, 5)
        )
        assert any(finding.code == "runtime_eol" for finding in findings)


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
async def test_validate_technology_safety_treats_stale_policy_as_advisory(
    monkeypatch,
) -> None:
    policy = dict(tech_safety.load_policy())
    policy["last_reviewed"] = "2025-01-01"
    monkeypatch.setattr(tech_safety, "load_policy", lambda: policy)

    findings = await analyze_technology_safety(
        "spec",
        "## Constraints\nNo implementation choices.",
        {},
        redis=_FakeRedis(),
        today=date(2026, 6, 9),
    )

    assert findings[0].code == "technology_policy_stale"
    await validate_technology_safety(
        "spec",
        "## Constraints\nNo implementation choices.",
        {},
        redis=_FakeRedis(),
        today=date(2026, 6, 9),
    )


@pytest.mark.asyncio
async def test_validate_technology_safety_treats_osv_high_as_advisory() -> None:
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
        findings = await analyze_technology_safety(
            "tasks",
            "Install FastAPI with `pip install fastapi==0.95.0`.",
            {"plan": ""},
            redis=_FakeRedis(),
            http_client=client,
        )

    assert findings[0].code == "vulnerable_dependency"
    assert findings[0].severity == "high"


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
