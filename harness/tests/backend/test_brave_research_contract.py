"""
Harness contracts for the Brave LLM Context integration (issue #12).

Source-level invariants that pin the feature's spine across its phases. They are
RED before the phase lands and GREEN after, and guard the non-negotiable design
constraint: Brave is an OPTIONAL, purely ADDITIVE enrichment that is OFF by
default and NEVER a dependency — generation must work identically when Brave is
unconfigured, not opted in, or failing.

  Phase 1  config keys + brave_client.py adapter (fail-open, never-raises).
  Phase 2  research_service.fetch_context — cache/quota/sanitise/billing.
  Phase 3  Workspace.brave_research_enabled column + migration,
           PATCH /workspaces/{id}/research opt-in toggle (audited),
           build_prompt(research_context=…) threading,
           generate() preflight wiring.

These are greps, not behavioural tests; the behavioural coverage lives in the
backend suite (test_brave_client / test_research_service / test_research_wiring /
test_prompt_builder).
"""

from __future__ import annotations

import json
import re

from conftest import BACKEND_ROOT, REPO_ROOT, read_backend_file

# ---------------------------------------------------------------------------
# Phase 1 — config surface + adapter.
# ---------------------------------------------------------------------------


def test_config_defines_brave_keys_off_by_default() -> None:
    src = read_backend_file("config.py")
    # The feature is gated on BOTH a non-empty key and an explicit flag, and the
    # flag defaults OFF — so the feature is dark out of the box.
    assert "brave_search_api_key" in src
    assert re.search(r"brave_search_flag\s*:\s*bool\s*=\s*False", src), (
        "brave_search_flag must default to False so the feature ships dark."
    )
    assert "def brave_search_enabled" in src
    assert "billing_credits_brave_research" in src


def test_brave_client_exists_and_never_logs_the_key() -> None:
    src = read_backend_file("services", "research", "brave_client.py")
    assert re.search(r"async\s+def\s+fetch\s*\(", src), (
        "brave_client must expose an async fetch(...) adapter."
    )
    # The subscription token is a secret: it may be attached as a header but must
    # never be interpolated into a log line.
    assert "X-Subscription-Token" in src
    for log_call in re.findall(r"\.(?:debug|info|warning|error)\([^)]*", src):
        assert "api_key" not in log_call and "subscription" not in log_call.lower(), (
            "The Brave API key must never appear in a log call."
        )


# ---------------------------------------------------------------------------
# Phase 2 — research service orchestration.
# ---------------------------------------------------------------------------


def test_research_service_fetch_context_is_fail_open() -> None:
    src = read_backend_file("services", "research", "research_service.py")
    assert re.search(r"async\s+def\s+fetch_context\s*\(", src), (
        "research_service must expose async fetch_context(...)."
    )
    # Charge only on delivered value: the deduct reason is workspace/stage-scoped.
    assert "brave_research:" in src
    # Untrusted web text flows through the same guard as user input.
    assert "PromptGuard" in src and "sanitize_text" in src
    # The raw idea text is never logged — only its hash.
    assert "_query_hash" in src


def test_billing_metric_for_brave_research_exists() -> None:
    src = read_backend_file("services", "observability.py")
    assert "BILLING_CREDITS_BRAVE_RESEARCH" in src


# ---------------------------------------------------------------------------
# Phase 3 — opt-in surface + generation wiring.
# ---------------------------------------------------------------------------


def test_workspace_model_has_opt_in_column_off_by_default() -> None:
    src = read_backend_file("models", "workspace.py")
    assert "brave_research_enabled" in src
    # NOT NULL with a false server_default so every existing row backfills to OFF.
    block = src[src.index("brave_research_enabled") :]
    assert 'server_default=text("false")' in block[:400], (
        "brave_research_enabled must default to false at the DB layer."
    )


def test_migration_adds_brave_research_enabled_column() -> None:
    path = BACKEND_ROOT / "migrations" / "versions"
    matches = [p for p in path.glob("*.py") if "brave_research_enabled" in p.read_text()]
    assert matches, "An Alembic migration must add workspaces.brave_research_enabled."
    body = matches[0].read_text()
    assert "add_column" in body and "drop_column" in body


def test_patch_research_endpoint_exists_and_is_audited() -> None:
    src = read_backend_file("routers", "workspace.py")
    assert re.search(r'@router\.patch\(\s*"/\{id\}/research"', src), (
        "PATCH /workspaces/{id}/research must exist."
    )
    assert "AUDIT_EVENT_BRAVE_RESEARCH_TOGGLED" in src, (
        "Toggling the opt-in must write a brave_research_toggled audit row."
    )


def test_workspace_response_exposes_opt_in_flag() -> None:
    src = read_backend_file("schemas", "workspace.py")
    assert "class WorkspaceResearchToggle" in src
    assert re.search(r"brave_research_enabled\s*:\s*bool", src)


def test_build_prompt_accepts_research_context() -> None:
    src = read_backend_file("services", "pipeline", "prompt_builder.py")
    assert re.search(r"research_context\s*:\s*str\s*=\s*\"\"", src), (
        "build_prompt must accept an optional research_context defaulting to ''."
    )


def test_generate_preflight_wires_research_service() -> None:
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    assert "research_service" in src
    assert "_fetch_research_context" in src
    assert "research_context=research.block" in src, (
        "generate() must pass the fetched block into build_prompt."
    )


# ---------------------------------------------------------------------------
# Phase 4 — StageVersion persistence + COGS visibility.
# ---------------------------------------------------------------------------


def test_stage_version_has_research_persistence_columns() -> None:
    src = read_backend_file("models", "stage_version.py")
    assert "research_context" in src and "research_sources" in src, (
        "StageVersion must persist the injected research block + its sources."
    )


def test_migration_adds_stage_version_research_columns() -> None:
    path = BACKEND_ROOT / "migrations" / "versions"
    matches = [
        p
        for p in path.glob("*.py")
        if "research_context" in p.read_text() and "stage_versions" in p.read_text()
    ]
    assert matches, "An Alembic migration must add the StageVersion research columns."
    assert any(
        "add_column" in migration.read_text()
        and "drop_column" in migration.read_text()
        for migration in matches
    ), "A matching migration must add and remove the research columns."


def test_research_service_records_brave_cogs_row() -> None:
    src = read_backend_file("services", "research", "research_service.py")
    # Spend is recorded on llm_cost_events with provider="brave", per paid call.
    assert "persist_cost_event" in src
    assert '"provider": "brave"' in src, (
        "Each paid Brave call must write a provider='brave' COGS row."
    )


def test_source_urls_are_http_allowlisted() -> None:
    """Untrusted web source URLs are an XSS vector; they must be scheme-allowlisted
    at the backend chokepoint before persistence/rendering."""
    src = read_backend_file("services", "research", "research_service.py")
    assert "_safe_http_url" in src


def test_stage_version_response_exposes_research() -> None:
    src = read_backend_file("schemas", "stage.py")
    assert "research_context" in src and "research_sources" in src, (
        "StageVersionResponse must expose the research block + sources."
    )


# ---------------------------------------------------------------------------
# Phase 5 — offline comparison gate + flag-flip stays an ops action.
# ---------------------------------------------------------------------------


def test_phase5_comparison_script_exists_and_is_gated() -> None:
    """The pre-launch comparison ships dry-run-by-default with a --live gate."""
    src = read_backend_file("scripts", "compare_brave_grounding.py")
    assert "--live" in src, "live mode must be an explicit, opt-in flag"
    assert "_run_dry_run" in src and "_run_live" in src


def test_phase5_comparison_never_bills() -> None:
    """The comparison must reuse the assembly seams, NOT fetch_context — it must
    never charge a credit, consume the quota, or write a COGS row."""
    src = read_backend_file("scripts", "compare_brave_grounding.py")
    assert "_assemble_block" in src, "block must come from the production assembler"
    assert "fetch_context(" not in src, (
        "the comparison must bypass fetch_context (no credit/quota/DB/COGS)."
    )


def test_phase5_corpus_exists_with_a_control_case() -> None:
    """A recency-neutral control guards against spuriously favoring grounding."""
    path = (
        REPO_ROOT / "docs" / "evals" / "golden_prompts" / "brave_grounding_corpus.json"
    )
    assert path.exists(), f"Missing corpus: {path.relative_to(REPO_ROOT)}"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(corpus, list) and corpus
    assert any(case.get("category") == "control" for case in corpus)


def test_phase5_flag_still_ships_dark() -> None:
    """Phase 5 delivers the *gate*, not the flip: the flag stays False in code."""
    src = read_backend_file("config.py")
    assert re.search(r"brave_search_flag\s*:\s*bool\s*=\s*False", src)
