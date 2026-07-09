"""
Harness contracts for Phase 22 — Prompt Pipeline Quality Hardening.

These tests are RED before T-239 through T-249 are implemented and GREEN after.

Every test maps to one or more tasks from Plan v1.md Phase 22:

  T-239  plan.py — Architecture Anti-Patterns denylist + 5-line ADR format +
         Multi-tenancy stance.  Closes audit F-1 (architecture not forced toward
         correctness).

  T-240  plan.py — Capacity Model + STRIDE Threat Model + SLO/SLI/error budget +
         FMEA-lite + Architecture Quality Attribute matrix.  Closes F-3, F-6
         (architect thinking; scalability/reliability/resilience).

  T-241  plan.py + tasks.py — Technology Currency discipline.  Mandatory version
         + support-status + EOL columns; hard deprecation denylist; per-task SCA
         + version-pin acceptance criterion.  Closes F-2 (no deprecation guard).

  T-242  plan.py — Frontend Architecture section (state, data-fetching, forms,
         components, tokens, routing, loading/error/empty/offline, a11y, perf,
         CSP, i18n, browser matrix).  Closes F-5 (frontend design patterns).

  T-243  tasks.py — Frontend task checklist (loading + error + empty + focus +
         a11y assertion + perf-budget delta per FE-touching task).  Closes F-5.

  T-244  harness.py — Expand mandatory test categories (boundary, property-based,
         concurrency, chaos, regression-safety, migration-safety, accessibility,
         performance-budget, supply-chain) + rewrite output-budget rule so
         security/contract/migration/integration are never droppable.  Closes
         F-4, F-6.

  T-245  base.py — Tighten PROFESSIONAL_OUTPUT_RULES escape-hatch wording;
         promote security/privacy/a11y/observability/reliability/abuse from
         "when they materially affect" to mandatory with an explicit "Not
         applicable because <reason>" exception protocol.  Closes F-7.5.

  T-246  prompt_builder.py — Raise _MAX_UPSTREAM_CHARS from 50_000 to 200_000;
         switch to section-aware injection when upstream exceeds cap; emit
         pipeline_upstream_section_skipped_total{stage, section} per skipped
         section.  Closes F-7.1 (lossy summarization).

  T-247  services/pipeline/critic.py — Judge-model second-pass per stage with
         one-regenerate cap, disable_critic owner-only escape hatch
         (audit-logged), output schema restricted to findings (no artifact
         rewrite), inline prompt template (never loaded via Langfuse).  Closes
         F-7.2 (no critic loop).

  T-248  services/pipeline/artifact_validator.py — Zero-LLM mandatory-section
         presence check.  MissingSectionError surfaces structured list of absent
         sections.  Runs BEFORE the critic.  Conditional sections (T-242
         Frontend Architecture) enforced when sentinel string present.  Closes
         F-7.3.

  T-249  harness/prompt_eval/ — 3 golden workspaces × 25 deterministic graders.
         CI workflow gates ASDD_PROMPT_VERSION bumps on the eval suite passing.
         RUNBOOK.md §10 documents the prompt-experimentation workflow.  Closes
         F-7.4 (no prompt versioning + eval).

Design invariants enforced here:
  * plan.py contains an ## Architecture Decision Records section with Forces +
    Options + Reversal cost format.
  * plan.py contains an explicit Architecture Anti-Patterns denylist naming
    distributed monolith, premature sharding, dual-write, N+1, and
    sync-in-request-path.
  * plan.py mandates a Multi-tenancy Stance declaration.
  * plan.py mandates a Capacity Model with RPS + p95/p99 + 10×/100× projection.
  * plan.py mandates a STRIDE Threat Model section.
  * plan.py mandates SLOs + Error Budgets per user-facing service.
  * plan.py mandates an FMEA-lite per external dependency.
  * plan.py mandates an Architecture Quality Attribute matrix with five named
    columns.
  * plan.py Technology Stack table has Version + Support status + EOL columns.
  * plan.py hard-denylists Python ≤ 3.10, Node ≤ 18, gpt-3, claude-2, gemini-1.x.
  * tasks.py requires SCA + version-pin acceptance criteria for dependency-
    introducing tasks.
  * plan.py contains a Frontend Architecture section listing all 14 required
    sub-bullets.
  * tasks.py requires loading/error/empty + focus + a11y + bundle-budget for
    frontend-touching tasks.
  * harness.py lists nine new mandatory test categories and rewrites the
    output-budget rule so security/contract/migration/integration are
    NEVER-droppable.
  * base.py PROFESSIONAL_OUTPUT_RULES no longer contains "when they materially
    affect"; contains the "Not applicable because" exception protocol instead.
  * prompt_builder.py _MAX_UPSTREAM_CHARS == 200_000.
  * prompt_builder.py emits pipeline_upstream_section_skipped_total per skipped
    section.
  * services/pipeline/critic.py exists with critic_review function and
    StageCriticResult Pydantic model.
  * critic_review output schema is restricted to findings (no artifact bytes).
  * critic.py defines its prompt template inline (does NOT call load_prompt).
  * One-regenerate cap is enforced (regenerate count tracked).
  * A blocked draft is persisted after the second consecutive failure.
  * BILLING_CREDITS_CRITIC_REGEN counter is defined.
  * disable_critic toggle writes an audit event with the actor user_id.
  * services/pipeline/artifact_validator.py exists with SECTION_CONTRACTS dict.
  * SECTION_CONTRACTS covers all four stages and includes T-239 / T-240 / T-242
    additions.
  * MissingSectionError exposes the missing-sections list.
  * Validator runs BEFORE the critic in stage_manager.
  * harness/prompt_eval/ directory exists with golden_workspaces, graders, and
    run.py.
  * .github/workflows/prompt-eval.yml gates merges on ASDD_PROMPT_VERSION bumps.
  * RUNBOOK.md §10 documents the prompt experimentation workflow.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from conftest import BACKEND_ROOT, REPO_ROOT, import_backend, read_backend_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_prompt(name: str) -> str:
    """Read a backend/prompts/<name>.py file and return its source.

    Prompts are versioned in code (ASDD_PROMPT_VERSION) so structural checks
    against the source are the authoritative contract — Langfuse remote
    overrides are subject to the security-rules gate but never relax this
    invariant.
    """
    return read_backend_file("prompts", f"{name}.py")


def _read_plan_prompt() -> str:
    return _read_prompt("plan")


def _read_tasks_prompt() -> str:
    return _read_prompt("tasks")


def _read_harness_prompt() -> str:
    return _read_prompt("harness")


def _read_base_prompt() -> str:
    return _read_prompt("base")


def _phrases_present(source: str, phrases: list[str]) -> list[str]:
    """Return the phrases that are NOT present in the source (case-sensitive)."""
    return [p for p in phrases if p not in source]


def _extract_section(source: str, heading: str) -> str:
    """Return the body of a markdown section identified by its `## ` heading.

    Returns the text between `heading` (matched as a substring on any line) and
    the next `## ` heading (or end of input).  Returns the empty string if the
    heading is not found.

    Used by the T-242 sub-bullet tests to scope phrase checks to the Frontend
    Architecture section, preventing false positives where unrelated parts of
    the prompt (e.g. T-241's Technology Stack layers list, which mentions
    "state management (if applicable)" as a layer name) accidentally satisfy a
    Frontend-section requirement.
    """
    start = source.find(heading)
    if start < 0:
        return ""
    rest = source[start + len(heading) :]
    # The next "## " on its own line terminates the section.  Use a regex
    # anchored on a newline so a bare "## " inside a code fence cannot prematurely
    # end the section.
    end_match = re.search(r"\n##\s", rest)
    return rest[: end_match.start()] if end_match else rest


# ===========================================================================
# T-239 — plan.py: Architecture Anti-Patterns + ADR + Multi-tenancy
# ===========================================================================


def test_t239_plan_prompt_requires_architecture_decision_records_section() -> None:
    """T-239 — plan.py must mandate an ## Architecture Decision Records section.

    Without a binding ADR format, the model's design rationale collapses to
    prose and loses the Forces / Options / Chosen / Reversal-cost structure
    needed to audit architecture decisions later.
    """
    src = _read_plan_prompt()
    assert (
        "## Architecture Decision Records" in src
        or "## Architecture Decision Records (ADR)" in src
    ), (
        "plan.py SYSTEM_PROMPT must include an '## Architecture Decision Records' "
        "section heading.  T-239 (audit F-1)."
    )


def test_t239_plan_prompt_adr_format_includes_reversal_cost() -> None:
    """T-239 — the ADR format must require a Reversal Cost line per decision.

    Reversal cost is the single most-important field — it captures the lock-in
    that "chose this option" silently buys.  Without it, the model can pick
    technologies whose true cost only surfaces at scale.
    """
    src = _read_plan_prompt()
    assert "Reversal Cost" in src or "Reversal cost" in src, (
        "plan.py ADR format must require a 'Reversal Cost' field per decision.  "
        "T-239."
    )


def test_t239_plan_prompt_adr_format_requires_options_considered() -> None:
    """T-239 — the ADR format must require ≥2 Options Considered with tradeoffs."""
    src = _read_plan_prompt()
    assert re.search(
        r"Options Considered|Options considered|options considered", src
    ), "plan.py ADR format must require an 'Options Considered' field.  T-239."


def test_t239_plan_prompt_has_architecture_anti_patterns_denylist() -> None:
    """T-239 — plan.py must contain an explicit anti-pattern denylist.

    Calling out anti-patterns by name (distributed monolith, dual-write, N+1)
    is the most reliable way to prevent them.  The model rarely volunteers a
    "do not propose X" rule; we have to inject it.
    """
    src = _read_plan_prompt()
    assert "Architecture Anti-Patterns" in src or "Anti-Patterns" in src, (
        "plan.py SYSTEM_PROMPT must include an 'Architecture Anti-Patterns' "
        "denylist section.  T-239 (audit F-1)."
    )


def test_t239_plan_prompt_denylists_distributed_monolith() -> None:
    """T-239 — the anti-pattern denylist must name 'distributed monolith'."""
    src = _read_plan_prompt()
    assert "distributed monolith" in src.lower(), (
        "plan.py anti-pattern denylist must explicitly name 'distributed monolith'.  "
        "T-239."
    )


def test_t239_plan_prompt_denylists_premature_sharding() -> None:
    """T-239 — the anti-pattern denylist must name premature sharding."""
    src = _read_plan_prompt()
    assert "premature sharding" in src.lower() or "premature shard" in src.lower(), (
        "plan.py anti-pattern denylist must explicitly name premature sharding.  "
        "T-239."
    )


def test_t239_plan_prompt_denylists_dual_write_without_outbox() -> None:
    """T-239 — denylist must call out dual-write without outbox/CDC."""
    src = _read_plan_prompt()
    assert (
        "dual-write" in src.lower() or "dual write" in src.lower()
    ), "plan.py anti-pattern denylist must call out 'dual-write' patterns.  T-239."


def test_t239_plan_prompt_denylists_sync_external_calls_in_request_path() -> None:
    """T-239 — denylist must call out synchronous external calls in the request path."""
    src = _read_plan_prompt()
    assert (
        "sync external calls" in src.lower()
        or "synchronous external" in src.lower()
        or "circuit breaker" in src.lower()
    ), (
        "plan.py anti-pattern denylist must call out sync external calls in the "
        "request path without a circuit breaker.  T-239."
    )


def test_t239_plan_prompt_denylists_n_plus_one() -> None:
    """T-239 — denylist must call out N+1 patterns."""
    src = _read_plan_prompt()
    assert "N+1" in src or "n+1" in src.lower(), (
        "plan.py anti-pattern denylist must call out N+1 patterns and require "
        "an explicit eager-load or batch strategy.  T-239."
    )


def test_t239_plan_prompt_has_multi_tenancy_stance_section() -> None:
    """T-239 — plan.py must require a Multi-tenancy Stance declaration."""
    src = _read_plan_prompt()
    assert "Multi-tenancy" in src or "multi-tenancy" in src or "multi tenancy" in src, (
        "plan.py SYSTEM_PROMPT must mandate a Multi-tenancy Stance declaration.  "
        "T-239 (audit F-1)."
    )


def test_t239_plan_prompt_multi_tenancy_lists_named_options() -> None:
    """T-239 — Multi-tenancy stance must list shared-schema / RLS / schema-per-tenant.

    A free-form "multi-tenancy strategy" prompt section drifts to prose.
    Forcing the model to pick from a fixed enum produces auditable architecture.
    """
    src = _read_plan_prompt().lower()
    missing = _phrases_present(
        src,
        ["shared-schema", "row-level security", "schema-per-tenant"],
    )
    # At least 2 of the 3 named options must be present (some products may have
    # an additional 'physical isolation' option which is fine).
    assert (
        len(missing) <= 1
    ), f"Multi-tenancy stance must list named options.  Missing: {missing}.  T-239."


# ===========================================================================
# T-240 — plan.py: Capacity + STRIDE + SLO + FMEA + Architecture Quality Attribute matrix
# ===========================================================================


def test_t240_plan_prompt_has_capacity_model_section() -> None:
    """T-240 — plan.py must require a ## Capacity Model section."""
    src = _read_plan_prompt()
    assert "## Capacity Model" in src, (
        "plan.py SYSTEM_PROMPT must include a '## Capacity Model' section.  "
        "T-240 (audit F-3)."
    )


def test_t240_capacity_model_requires_rps_and_latency_budget() -> None:
    """T-240 — Capacity Model must require RPS + p95/p99 latency."""
    src = _read_plan_prompt()
    assert "RPS" in src, "Capacity Model must require RPS targets.  T-240."
    assert re.search(
        r"p95|p99|p50/p95/p99", src
    ), "Capacity Model must require latency budgets (p50/p95/p99).  T-240."


def test_t240_capacity_model_requires_10x_100x_projection() -> None:
    """T-240 — Capacity Model must require BOTH 10× AND 100× stress projections.

    "Where does this design break first?" is the question that separates
    "we picked PostgreSQL because Django uses it" from "we picked PostgreSQL
    and it breaks at 10K writes/sec on a single primary, at which point we
    add read replicas + Citus."

    Requires both projections separately so that incidental "10x" mentions
    elsewhere in the prompt (e.g. ADR Reversal Cost guidance from T-239) do
    not falsely satisfy the Capacity Model requirement.
    """
    src = _read_plan_prompt()
    assert re.search(r"10×|\b10x\b", src), (
        "Capacity Model must require a 10× stress projection naming where "
        "the design breaks first.  T-240."
    )
    assert re.search(r"100×|\b100x\b", src), (
        "Capacity Model must require a 100× stress projection naming the "
        "redesign required at that scale.  T-240."
    )
    # The two projections must co-occur in the prompt near the phrase
    # "stress projection" — otherwise the matches are likely from unrelated
    # context.
    assert "stress projection" in src.lower(), (
        "Capacity Model must use the phrase 'stress projection' so the "
        "10×/100× requirements are anchored to the Capacity Model section "
        "rather than incidental mentions elsewhere.  T-240."
    )


def test_t240_plan_prompt_has_threat_model_section() -> None:
    """T-240 — plan.py must require a STRIDE threat model section."""
    src = _read_plan_prompt()
    assert "## Threat Model" in src and "STRIDE" in src, (
        "plan.py SYSTEM_PROMPT must include a '## Threat Model (STRIDE)' section.  "
        "T-240 (audit F-3)."
    )


def test_t240_threat_model_lists_all_stride_categories() -> None:
    """T-240 — STRIDE section must enumerate all 6 categories."""
    src = _read_plan_prompt()
    for category in [
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information disclosure",
        "Denial of service",
        "Elevation of privilege",
    ]:
        assert category in src, f"STRIDE section must enumerate '{category}'.  T-240."


def test_t240_plan_prompt_has_slo_and_error_budget_section() -> None:
    """T-240 — plan.py must require an SLO + error budget section."""
    src = _read_plan_prompt()
    assert "SLO" in src and ("Error Budget" in src or "error budget" in src), (
        "plan.py SYSTEM_PROMPT must include an SLOs and Error Budgets section.  "
        "T-240 (audit F-6)."
    )


def test_t240_slo_section_requires_availability_latency_correctness() -> None:
    """T-240 — SLO section must require availability + latency + correctness."""
    src = _read_plan_prompt()
    assert (
        "availability SLO" in src.lower() or "availability" in src.lower()
    ), "SLO section must require an availability SLO.  T-240."
    assert (
        "latency SLO" in src.lower() or "latency" in src.lower()
    ), "SLO section must require a latency SLO.  T-240."


def test_t240_plan_prompt_has_fmea_section() -> None:
    """T-240 — plan.py must require an FMEA-lite section per dependency."""
    src = _read_plan_prompt()
    assert "FMEA" in src or "Failure Mode" in src, (
        "plan.py SYSTEM_PROMPT must include an FMEA-lite section "
        "('Failure Mode and Effects Analysis').  T-240 (audit F-6)."
    )


def test_t240_fmea_requires_blast_radius_and_recovery_time() -> None:
    """T-240 — FMEA must require blast radius + recovery time per failure mode."""
    src = _read_plan_prompt()
    assert (
        "Blast radius" in src or "blast radius" in src.lower()
    ), "FMEA section must require a 'Blast radius' field per failure mode.  T-240."
    assert (
        "Recovery time" in src or "recovery time" in src.lower()
    ), "FMEA section must require a 'Recovery time' field per failure mode.  T-240."


def test_t240_plan_prompt_has_quality_attribute_matrix() -> None:
    """T-240 — plan.py must require an Architecture Quality Attribute matrix."""
    src = _read_plan_prompt()
    assert "Quality Attribute" in src or "Architecture Quality Attribute" in src, (
        "plan.py SYSTEM_PROMPT must include an Architecture Quality Attribute "
        "Matrix section.  T-240."
    )


def test_t240_quality_attribute_matrix_has_five_named_columns() -> None:
    """T-240 — AQA matrix must list Performance/Scalability/Reliability/Security/Maintainability.

    The matrix's value is its column structure — it forces the model to fill
    five named cells per component instead of writing prose that quietly
    omits scalability or maintainability.
    """
    src = _read_plan_prompt()
    for column in [
        "Performance",
        "Scalability",
        "Reliability",
        "Security",
        "Maintainability",
    ]:
        assert column in src, (
            f"Architecture Quality Attribute Matrix must include '{column}' "
            f"column.  T-240."
        )


# ===========================================================================
# T-241 — plan.py + tasks.py: Technology Currency + Deprecation Denylist
# ===========================================================================


def test_t241_plan_prompt_technology_stack_requires_version_column() -> None:
    """T-241 — Technology Stack table must require a Version column.

    The Gemini Flash deprecation (commit fbe19ed) is the canonical example
    of this failure: the model picked a model name without recording its
    version or support status, so the deprecation went unnoticed until a
    production failure.
    """
    src = _read_plan_prompt()
    assert "latest stable as of" in src.lower(), (
        "plan.py Technology Stack section must require 'Version (latest stable "
        "as of YYYY-MM)' per entry.  T-241 (audit F-2)."
    )


def test_t241_plan_prompt_technology_stack_requires_support_status() -> None:
    """T-241 — Technology Stack must require Support Status (Active/Maintenance/Deprecated/EOL)."""
    src = _read_plan_prompt()
    assert (
        "Support status" in src or "support status" in src
    ), "plan.py Technology Stack must require a Support status column.  T-241."
    # All four enum values must be enumerated explicitly.
    for level in ["Active", "Maintenance", "Deprecated", "EOL"]:
        assert level in src, f"Support status legend must enumerate '{level}'.  T-241."


def test_t241_plan_prompt_technology_stack_requires_eol_date() -> None:
    """T-241 — Technology Stack must require an EOL date column."""
    src = _read_plan_prompt()
    assert (
        "EOL date" in src or "EOL" in src
    ), "plan.py Technology Stack must require an EOL date per entry.  T-241."


def test_t241_plan_prompt_denylists_eol_python_and_node() -> None:
    """T-241 — denylist must name Python ≤ 3.10 and Node ≤ 18 as security EOL.

    Prompt Quality Remediation finding #7: the denylist's technology/version
    facts are now GENERATED at import time from
    ``services/pipeline/tech_safety_policy.json`` (the deterministic gate's
    single source of truth) rather than hand-duplicated as literal text in
    plan.py's source — so this checks the RENDERED ``SYSTEM_PROMPT`` (what the
    model actually reads), not the source file, which now legitimately
    contains a function call instead of the literal facts.

    Accepts the Unicode form (``Python ≤ 3.10``), the ASCII less-than-or-equal
    (``Python <= 3.10``), bare less-than (``Python < 3.10``), or the literal
    version (``Python 3.10``) — any of those is a clear EOL declaration.
    """
    plan = import_backend("prompts.plan")
    rendered = plan.SYSTEM_PROMPT
    python_pat = r"Python\s*(?:≤|<=|<|=)\s*3\.10|Python\s*3\.10\b"
    # "Node" may be immediately followed by ".js" now that the technology name
    # comes from tech_safety_policy.json's "Node.js" entry.
    node_pat = r"Node(?:\.js)?\s*(?:≤|<=|<|=)\s*18|Node(?:\.js)?\s*18\b"
    assert re.search(python_pat, rendered), (
        "Deprecation denylist must name Python ≤ 3.10 (or <= 3.10) as security "
        "EOL.  T-241."
    )
    assert re.search(node_pat, rendered), (
        "Deprecation denylist must name Node ≤ 18 (or <= 18) as security EOL.  "
        "T-241."
    )


def test_t241_plan_prompt_denylists_deprecated_llm_families() -> None:
    """T-241 — denylist must call out gpt-3, gemini-1.x, claude-1.x, claude-2.x.

    We have first-hand evidence of this failure mode (the Gemini Flash
    replacement commit).  Naming the deprecated families explicitly is the
    only way the model reliably avoids them. Checks the rendered
    ``SYSTEM_PROMPT`` — see the docstring above on finding #7.

    The generated prose (tech_safety_policy.json's "technology" field) writes
    these as prose ("Google Gemini 1.x family") rather than the hyphenated
    slug form ("gemini-1.x") the hand-written text used, so each pattern
    accepts either a hyphen or whitespace between the family name and its
    version — same intent (the model must not choose these families), just
    tolerant of the JSON-sourced formatting.
    """
    plan = import_backend("prompts.plan")
    rendered = plan.SYSTEM_PROMPT.lower()
    family_patterns = {
        "gpt-3": r"gpt[\s-]*3",
        "gemini-1": r"gemini[\s-]*1",
        "claude-1": r"claude[\s-]*1",
        # The JSON groups both under one combined "Claude 1.x/2.x family"
        # entry, so "2" can appear several characters after "claude" (past
        # the "1.x/" prefix) rather than immediately adjacent to it.
        "claude-2": r"claude[\d./x\s-]*2",
    }
    for family, pattern in family_patterns.items():
        assert re.search(pattern, rendered), (
            f"Deprecation denylist must call out the '{family}' family.  T-241."
        )


def test_t241_plan_prompt_denylists_stale_libraries() -> None:
    """T-241 — denylist must call out libraries with no commits in last 18 months."""
    src = _read_plan_prompt()
    assert "18 months" in src or "18-month" in src, (
        "Deprecation denylist must call out libraries with no commit in the last "
        "18 months.  T-241."
    )


def test_t241_tasks_prompt_requires_sca_acceptance_criterion() -> None:
    """T-241 — tasks.py must require an SCA tool acceptance criterion."""
    src = _read_tasks_prompt()
    assert "pip-audit" in src or "pnpm audit" in src or "SCA" in src, (
        "tasks.py SYSTEM_PROMPT must require an SCA tool (pip-audit / pnpm audit / "
        "equivalent) acceptance criterion for dependency-introducing tasks.  T-241."
    )


def test_t241_tasks_prompt_requires_version_pin_matches_plan() -> None:
    """T-241 — tasks.py must require the pinned version match PLAN.md Technology Stack."""
    src = _read_tasks_prompt()
    assert (
        "matches the version recorded in" in src.lower()
        or "pinned version" in src.lower()
    ), (
        "tasks.py SYSTEM_PROMPT must require the pinned dependency version to "
        "match the version recorded in PLAN.md Technology Stack.  T-241."
    )


def test_t241_tasks_prompt_blocks_deprecated_or_eol_packages() -> None:
    """T-241 — tasks.py must require that chosen packages are not on Deprecated/EOL line."""
    src = _read_tasks_prompt()
    assert "Deprecated" in src and "EOL" in src, (
        "tasks.py must require an acceptance criterion that the chosen package "
        "is not on the Deprecated or EOL support-status line.  T-241."
    )


def test_finding8_tasks_prompt_requires_test_category_gap_acknowledgement() -> None:
    """Prompt Quality Remediation finding #8: no mechanism connected tasks.py to
    the harness's TestCategoryGap vocabulary — a harness that recorded a
    deferred test category had no defined tasks-stage behavior, so known-
    deferred coverage could silently disappear downstream. tasks.py's system
    prompt (the task-design rules) and its user-prompt verify checklist must
    both instruct acknowledgement of any TestCategoryGap record.
    """
    src = _read_tasks_prompt()
    assert "TestCategoryGap" in src, (
        "tasks.py must reference the harness's TestCategoryGap vocabulary so a "
        "deferred coverage category is never silently unacknowledged."
    )
    # Must appear in both places: the generation rule (system prompt) and the
    # verify checklist (user prompt) — a rule with no verify step is easy to
    # regress silently.
    assert src.count("TestCategoryGap") >= 2, (
        "tasks.py must reference TestCategoryGap in both the task-design rules "
        "and the 'Before returning, verify' checklist."
    )


# ===========================================================================
# T-242 — plan.py: Frontend Architecture section
# ===========================================================================


def test_t242_plan_prompt_has_frontend_architecture_section() -> None:
    """T-242 — plan.py must require a Frontend Architecture section (when applicable)."""
    src = _read_plan_prompt()
    assert "## Frontend Architecture" in src, (
        "plan.py SYSTEM_PROMPT must include a '## Frontend Architecture' section "
        "(conditional on browser-facing surface).  T-242 (audit F-5)."
    )


def test_t242_frontend_section_lists_state_management() -> None:
    """T-242 — Frontend section must require a state management decision.

    Scoped to the Frontend Architecture section body so unrelated mentions
    (e.g. "state management (if applicable)" appearing as a layer name in
    T-241's Technology Stack list) do not satisfy the requirement.
    """
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert "state management" in body.lower(), (
        "The Frontend Architecture section must require a state management "
        "decision.  T-242."
    )


def test_t242_frontend_section_lists_data_fetching_and_cache_invalidation() -> None:
    """T-242 — Frontend section must require a data-fetching layer and cache invalidation."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert "data fetching" in body.lower(), (
        "The Frontend Architecture section must require a Data fetching "
        "decision.  T-242."
    )
    assert "cache invalidation" in body.lower(), (
        "The Frontend Architecture section must require a cache invalidation "
        "strategy.  T-242."
    )


def test_t242_frontend_section_requires_loading_error_empty_offline_contract() -> None:
    """T-242 — Frontend section must require loading + error + empty + offline contract.

    These four states are the most-forgotten UI primitives.  Without an
    explicit contract, the model emits happy-path components that silently
    spin forever on a 500 response.
    """
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture").lower()
    for state in ["loading", "error", "empty", "offline"]:
        assert state in body, (
            f"The Frontend Architecture section must require a '{state}' "
            f"state contract.  T-242."
        )


def test_t242_frontend_section_requires_wcag_and_axe_core_baseline() -> None:
    """T-242 — Frontend section must require WCAG level + axe-core baseline."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert (
        "WCAG" in body
    ), "The Frontend Architecture section must require a WCAG level.  T-242."
    assert "axe-core" in body or "axe core" in body, (
        "The Frontend Architecture section must require an axe-core baseline.  "
        "T-242."
    )


def test_t242_frontend_section_requires_bundle_budget() -> None:
    """T-242 — Frontend section must require a bundle-size budget."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture").lower()
    assert "bundle budget" in body or "bundle size" in body, (
        "The Frontend Architecture section must require a bundle-size budget.  "
        "T-242."
    )


def test_t242_frontend_section_requires_csp_policy() -> None:
    """T-242 — Frontend section must require a CSP policy + Trusted Types stance."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert (
        "CSP" in body
    ), "The Frontend Architecture section must require a CSP policy.  T-242."
    assert "Trusted Types" in body or "trusted types" in body, (
        "The Frontend Architecture section must require a Trusted Types "
        "stance.  T-242."
    )


def test_t242_frontend_section_requires_browser_support_matrix() -> None:
    """T-242 — Frontend section must require an explicit browser support matrix."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert "browser support" in body.lower(), (
        "The Frontend Architecture section must require an explicit Browser "
        "support matrix.  T-242."
    )


def test_t242_frontend_section_requires_design_tokens() -> None:
    """T-242 — Frontend section must require design tokens + dark-mode strategy."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert (
        "design tokens" in body.lower()
    ), "The Frontend Architecture section must require Design tokens.  T-242."


def test_t242_frontend_section_requires_error_boundaries() -> None:
    """T-242 — Frontend section must require error boundaries + fallback UI contract."""
    body = _extract_section(_read_plan_prompt(), "## Frontend Architecture")
    assert (
        "error boundaries" in body.lower()
    ), "The Frontend Architecture section must require error boundaries.  T-242."


# ===========================================================================
# T-243 — tasks.py: Frontend task checklist
# ===========================================================================


def test_t243_tasks_prompt_requires_loading_error_empty_in_frontend_steps() -> None:
    """T-243 — tasks.py must require loading + error + empty state in Steps.

    Accepts the states named individually ("loading state", "error state",
    "empty state") or as the compound checklist phrase the prompt actually
    uses ("loading, error, and empty states" / "loading + error + empty
    states") — the requirement is that all three are mandated together, not a
    particular grammatical form.
    """
    src = _read_tasks_prompt().lower()
    compound = re.compile(
        r"loading\s*(?:,|\+)\s*error\s*(?:,|\+)?\s*(?:and\s+)?empty\s+states?"
    )
    if not compound.search(src):
        # Fall back to the individual-phrase form.
        for state in ["loading state", "error state", "empty state"]:
            assert state in src, (
                f"tasks.py SYSTEM_PROMPT must require '{state}' implementation "
                f"in Steps for frontend-touching tasks.  T-243 (audit F-5)."
            )


def test_t243_tasks_prompt_requires_focus_keyboard_interaction() -> None:
    """T-243 — tasks.py must require focus/keyboard interaction for frontend tasks.

    The check is intentionally strict: "focus" or "keyboard" alone appears in
    many unrelated contexts (focus_metrics, key in dict).  The new T-243
    section must use the phrase 'focus/keyboard' or 'where the focus lands'
    or 'keyboard interaction' as a recognisable requirement.
    """
    src = _read_tasks_prompt().lower()
    assert (
        "focus/keyboard" in src
        or "where the focus lands" in src
        or "where focus lands" in src
        or "keyboard interaction" in src
    ), (
        "tasks.py must require focus/keyboard interaction Steps for frontend "
        "tasks using a recognisable phrase ('focus/keyboard', "
        "'where focus lands', or 'keyboard interaction').  T-243."
    )


def test_t243_tasks_prompt_requires_accessibility_assertion() -> None:
    """T-243 — tasks.py must require an a11y assertion (axe-core or RTL role query)."""
    src = _read_tasks_prompt()
    assert "axe-core" in src or "accessibility assertion" in src.lower(), (
        "tasks.py must require an accessibility assertion in Acceptance Criteria "
        "for frontend tasks (axe-core scan or RTL role-based query).  T-243."
    )


def test_t243_tasks_prompt_requires_bundle_size_delta() -> None:
    """T-243 — tasks.py must require a bundle-size delta for FE tasks that add deps."""
    src = _read_tasks_prompt().lower()
    assert "bundle" in src and ("delta" in src or "size" in src), (
        "tasks.py must require a bundle-size delta in Acceptance Criteria for "
        "frontend tasks that add a runtime dependency.  T-243."
    )


# ===========================================================================
# T-244 — harness.py: Mandatory test categories + output-budget rewrite
# ===========================================================================


def test_t244_harness_prompt_requires_boundary_values_category() -> None:
    """T-244 — harness.py must require a boundary_values test category.

    The pre-Phase-22 prompt mentions "boundary values" loosely.  The new
    mandatory category must be discoverable as the underscore form
    'boundary_values' (a stable identifier the Coverage Plan can reference).
    """
    src = _read_harness_prompt()
    assert "boundary_values" in src, (
        "harness.py SYSTEM_PROMPT must require a 'boundary_values' (underscore "
        "form) mandatory test category — the underscore form is the stable "
        "Coverage Plan identifier.  T-244 (audit F-4)."
    )


def test_t244_harness_prompt_requires_property_based_with_hypothesis() -> None:
    """T-244 — harness.py must require a property-based test category."""
    src = _read_harness_prompt().lower()
    assert (
        "property_based" in src or "property-based" in src
    ), "harness.py must require a property_based test category.  T-244."
    assert "hypothesis" in src or "fast-check" in src, (
        "harness.py property_based category must name Hypothesis (Python) or "
        "fast-check (TS) by name.  T-244."
    )


def test_t244_harness_prompt_requires_concurrency_category() -> None:
    """T-244 — harness.py must require a concurrency test category.

    The pre-Phase-22 prompt mentions "concurrency or idempotency tests where
    relevant" — too soft.  The new mandatory category requires N-concurrent-
    writer tests per idempotent resource.
    """
    src = _read_harness_prompt().lower()
    assert (
        "n-concurrent-writer" in src
        or "n concurrent writer" in src
        or "concurrent-writer" in src
    ), (
        "harness.py must require an N-concurrent-writer concurrency test per "
        "idempotent resource (not the soft 'concurrency or idempotency tests "
        "where relevant' wording).  T-244."
    )


def test_t244_harness_prompt_requires_chaos_category() -> None:
    """T-244 — harness.py must require a chaos / dependency-kill test category."""
    src = _read_harness_prompt().lower()
    assert "chaos" in src, (
        "harness.py must require a chaos test category (dependency-kill test per "
        "external service).  T-244."
    )


def test_t244_harness_prompt_requires_regression_safety_category() -> None:
    """T-244 — harness.py must require a regression_safety category (schema diff)."""
    src = _read_harness_prompt().lower()
    assert "regression_safety" in src or "regression safety" in src, (
        "harness.py must require a regression_safety category with schema-diff "
        "against the last released contract.  T-244."
    )


def test_t244_harness_prompt_requires_migration_safety_category() -> None:
    """T-244 — harness.py must require a migration_safety category."""
    src = _read_harness_prompt().lower()
    assert "migration_safety" in src or "migration safety" in src, (
        "harness.py must require a migration_safety category with forward + "
        "backward read + rollback test.  T-244."
    )


def test_t244_harness_prompt_requires_accessibility_category() -> None:
    """T-244 — harness.py must require an accessibility test category."""
    src = _read_harness_prompt().lower()
    assert (
        "accessibility" in src
    ), "harness.py must require an accessibility test category.  T-244."
    assert "axe-core" in src, (
        "harness.py accessibility category must name axe-core (or equivalent) "
        "by name.  T-244."
    )


def test_t244_harness_prompt_requires_performance_budget_category() -> None:
    """T-244 — harness.py must require a performance_budget category."""
    src = _read_harness_prompt().lower()
    assert "performance_budget" in src or "performance budget" in src, (
        "harness.py must require a performance_budget test category with bundle-"
        "size, Lighthouse score floor, and p95 latency assertions.  T-244."
    )


def test_t244_harness_prompt_requires_supply_chain_category() -> None:
    """T-244 — harness.py must require a supply_chain category (SBOM + lockfile-pinned)."""
    src = _read_harness_prompt().lower()
    assert "supply_chain" in src or "supply chain" in src, (
        "harness.py must require a supply_chain test category (SBOM presence + "
        "lockfile-pinned).  T-244 (audit F-6)."
    )
    assert (
        "sbom" in src
    ), "harness.py supply_chain category must require SBOM presence test.  T-244."


def test_t244_harness_prompt_rewrites_output_budget_rule_with_never_drop() -> None:
    """T-244 — output-budget rule must protect integration/security/contract/migration.

    Without this, the model defers files to fit the token budget — which has
    repeatedly produced harnesses missing security or migration tests.  The
    new rule turns that into "drop categories in this priority order, but
    NEVER drop the protected four."
    """
    src = _read_harness_prompt()
    # The new rule must explicitly name the protected categories.
    assert "NEVER drop" in src or "never drop" in src.lower(), (
        "harness.py output-budget rule must name a NEVER-drop set so security/"
        "contract/migration/integration are protected.  T-244."
    )
    for protected in ["integration", "security", "contract", "migration"]:
        assert (
            protected in src.lower()
        ), f"harness.py NEVER-drop set must include '{protected}'.  T-244."


def test_t244_harness_prompt_output_budget_requires_testcategorygap_record() -> None:
    """T-244 — output-budget rewrite must require a TestCategoryGap record on drop."""
    src = _read_harness_prompt()
    assert "TestCategoryGap" in src, (
        "harness.py output-budget rule must require a 'TestCategoryGap' record "
        "naming each dropped category and the requirement IDs left uncovered.  "
        "T-244."
    )


# ===========================================================================
# T-245 — base.py: PROFESSIONAL_OUTPUT_RULES tightening
# ===========================================================================


def test_t245_base_prompt_drops_when_they_materially_affect_phrase() -> None:
    """T-245 — base.py must no longer contain the 'when they materially affect' escape hatch.

    This phrase gave the model a license to silently omit security, privacy,
    a11y, observability, reliability, and abuse content from artifacts.  The
    audit identified it as the single highest-leverage word change in the
    pipeline.
    """
    src = _read_base_prompt()
    assert "when they materially affect" not in src, (
        "base.py PROFESSIONAL_OUTPUT_RULES must no longer contain 'when they "
        "materially affect' — this escape-hatch phrase allowed silent omission "
        "of security/privacy/a11y/observability/reliability/abuse content.  T-245."
    )


def test_t245_base_prompt_makes_security_privacy_a11y_mandatory() -> None:
    """T-245 — base.py must promote security/privacy/a11y/observability/reliability to MUST."""
    src = _read_base_prompt()
    assert "Every artifact MUST include" in src or "MUST include security" in src, (
        "base.py PROFESSIONAL_OUTPUT_RULES must mandate (MUST include) security, "
        "privacy, accessibility, observability, reliability, and abuse content.  "
        "T-245."
    )


def test_t245_base_prompt_has_not_applicable_exception_protocol() -> None:
    """T-245 — base.py must define the 'Not applicable because <reason>' exception protocol."""
    src = _read_base_prompt()
    assert "Not applicable because" in src, (
        "base.py must define an explicit 'Not applicable because <reason>' "
        "exception protocol so the model writes an audit-visible exemption "
        "instead of silently omitting the heading.  T-245."
    )


# ===========================================================================
# T-246 — prompt_builder.py: Faithful upstream injection
# ===========================================================================


def test_t246_prompt_builder_raises_upstream_char_cap_to_200k() -> None:
    """T-246 — _MAX_UPSTREAM_CHARS must be 200_000 (raised from 50_000).

    The 50K cap was a 2024-era artifact.  Current frontier models handle 200K+
    context windows.  At 50K, every Phase 21 spec/plan generation was running
    on a lossy summary — a quality regression we shipped through.
    """
    src = read_backend_file("services", "pipeline", "prompt_builder.py")
    assert re.search(r"_MAX_UPSTREAM_CHARS\s*=\s*200_?000", src), (
        "_MAX_UPSTREAM_CHARS must equal 200_000 in services/pipeline/"
        "prompt_builder.py.  T-246 (audit F-7.1)."
    )


def test_t246_prompt_builder_has_section_aware_injection() -> None:
    """T-246 — prompt_builder must implement section-aware injection.

    When upstream exceeds the cap, narrative sections may be summarized but
    the RTM + API Design + Security Architecture + Data Model must be kept
    verbatim so downstream stages see the IDs they need by name.
    """
    src = read_backend_file("services", "pipeline", "prompt_builder.py")
    assert (
        "section_aware" in src
        or "_section_aware_injection" in src
        or "Requirement Traceability Matrix" in src
    ), (
        "prompt_builder.py must implement section-aware injection that keeps the "
        "Requirement Traceability Matrix verbatim when the upstream exceeds the "
        "cap.  T-246."
    )


def test_t246_prompt_builder_emits_section_skipped_metric() -> None:
    """T-246 — prompt_builder must emit pipeline_upstream_section_skipped_total."""
    src = read_backend_file("services", "pipeline", "prompt_builder.py")
    assert "pipeline_upstream_section_skipped_total" in src, (
        "prompt_builder.py must emit a 'pipeline_upstream_section_skipped_total' "
        "Prometheus counter per skipped section so quality regressions on large "
        "products are observable in Grafana.  T-246."
    )


def test_t246_section_skipped_metric_registered_in_observability() -> None:
    """T-246 — the new metric must be exported from services.observability."""
    src = read_backend_file("services", "observability.py")
    assert (
        "pipeline_upstream_section_skipped_total" in src
        or "PIPELINE_UPSTREAM_SECTION_SKIPPED" in src
    ), (
        "The pipeline_upstream_section_skipped_total Prometheus counter must be "
        "defined in services/observability.py so dashboards can reach it.  T-246."
    )


# ===========================================================================
# T-247 — services/pipeline/critic.py: Critic loop
# ===========================================================================


def test_t247_critic_module_file_exists() -> None:
    """T-247 — services/pipeline/critic.py must exist."""
    path = BACKEND_ROOT / "services" / "pipeline" / "critic.py"
    assert (
        path.exists()
    ), "services/pipeline/critic.py must exist.  T-247 (audit F-7.2)."


def test_t247_critic_module_exposes_critic_review_function() -> None:
    """T-247 — critic.py must expose an async critic_review function."""
    src = read_backend_file("services", "pipeline", "critic.py")
    assert re.search(r"async\s+def\s+critic_review\s*\(", src), (
        "services/pipeline/critic.py must expose 'async def critic_review(...)'.  "
        "T-247."
    )


def test_t247_critic_module_exposes_stage_critic_result_model() -> None:
    """T-247 — critic.py must expose a StageCriticResult Pydantic model."""
    src = read_backend_file("services", "pipeline", "critic.py")
    assert "class StageCriticResult" in src, (
        "services/pipeline/critic.py must expose a StageCriticResult Pydantic "
        "model.  T-247."
    )


def test_t247_critic_result_schema_excludes_artifact_bytes() -> None:
    """T-247 SECURITY — the critic result schema must not allow free-form artifact bytes.

    A critic that could rewrite the artifact directly is a vector for silently
    weakening it.  The schema must only allow structured findings
    (CoverageGap / MissingSection / BannedPhrase / DeprecatedAPI).
    """
    src = read_backend_file("services", "pipeline", "critic.py")
    # The result model must contain a findings list but no field that accepts
    # full markdown content.  We assert the model body does not contain a
    # field typed as a long string for the artifact.
    assert (
        re.search(r"findings\s*:\s*list", src) or "list[CriticFinding]" in src
    ), "StageCriticResult must contain a 'findings: list[...]' field.  T-247."
    # No "artifact_md" / "artifact_content" / "rewritten" field — the critic
    # cannot produce a rewrite.
    for forbidden in [
        "artifact_md:",
        "artifact_content:",
        "rewritten:",
        "new_artifact:",
    ]:
        assert forbidden not in src, (
            f"StageCriticResult must NOT contain a '{forbidden}' field — the "
            f"critic cannot rewrite the artifact directly.  T-247 SECURITY."
        )


def test_t247_critic_prompt_template_held_in_code_not_langfuse() -> None:
    """T-247 SECURITY — critic prompt template must be inline (no load_prompt call).

    A Langfuse-loaded critic prompt would let a compromised dashboard silently
    weaken the gate.  The critic prompt MUST be defined in code.
    """
    src = read_backend_file("services", "pipeline", "critic.py")
    assert "load_prompt(" not in src, (
        "services/pipeline/critic.py must NOT call load_prompt() — the critic "
        "prompt MUST be held in code so a compromised Langfuse dashboard cannot "
        "weaken the quality gate.  T-247 SECURITY."
    )


def test_t247_critic_enforces_one_regenerate_cap() -> None:
    """T-247 — critic loop must cap regenerates at exactly one per stage."""
    src = read_backend_file("services", "pipeline", "critic.py") + read_backend_file(
        "services", "pipeline", "stage_manager.py"
    )
    assert (
        "regenerate" in src.lower()
    ), "Critic loop must implement a one-regenerate cap.  T-247."
    # Look for the cap as a literal — either a constant or a counter check.
    assert (
        re.search(r"MAX_REGENERATES\s*=\s*1", src)
        or re.search(r"regenerate_count\s*<\s*1", src)
        or re.search(r"regenerate_count\s*<=\s*1", src)
        or re.search(r"regenerate_count\s*==\s*0", src)
        or "exactly one regenerate" in src.lower()
    ), "Critic loop must cap regenerates at exactly one per stage.  T-247."


def test_t247_critic_persists_advisory_draft_on_second_failure() -> None:
    """T-247 (+issue #34) — after the one regenerate the critic is advisory.

    The second consecutive critic failure no longer blocks; it delivers a
    finalisable draft with the findings attached as non-blocking suggestions
    (quality_gate_status="advisory") so the user can inspect, finalise, or
    regenerate.
    """
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    assert "_mark_quality_gate_advisory" in src and '"advisory"' in src, (
        "Critic loop must attach advisory findings (status='advisory') after the "
        "second consecutive failure instead of blocking the draft.  Issue #34."
    )


def test_t247_critic_sse_event_quality_gate_failed_exists() -> None:
    """T-247 — the quality_gate_failed SSE event must be emitted on terminal failure."""
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    assert "quality_gate_failed" in src, (
        "stage_manager must emit a 'quality_gate_failed' SSE event when the "
        "critic gate fails terminally so the frontend StreamingOverlay can "
        "render the findings.  T-247."
    )


def test_t247_billing_credits_critic_regen_counter_defined() -> None:
    """T-247 — BILLING_CREDITS_CRITIC_REGEN counter must be defined."""
    src = read_backend_file("services", "observability.py")
    assert "BILLING_CREDITS_CRITIC_REGEN" in src, (
        "services/observability.py must define a BILLING_CREDITS_CRITIC_REGEN "
        "counter so platform-funded regenerate spend is auditable.  T-247."
    )


def test_t247_disable_critic_writes_audit_event() -> None:
    """T-247 SECURITY — toggling disable_critic must write an audit event."""
    src = read_backend_file("services", "pipeline", "critic.py") + read_backend_file(
        "models", "__init__.py"
    )
    # Either the critic module or the audit-log enum must mention the event.
    assert "critic_disabled" in src, (
        "Toggling the disable_critic workspace flag must write an "
        "audit_event = 'critic_disabled' row with the actor user_id.  T-247 SECURITY."
    )


# ===========================================================================
# T-248 — services/pipeline/artifact_validator.py: Section presence
# ===========================================================================


def test_t248_artifact_validator_module_file_exists() -> None:
    """T-248 — services/pipeline/artifact_validator.py must exist."""
    path = BACKEND_ROOT / "services" / "pipeline" / "artifact_validator.py"
    assert (
        path.exists()
    ), "services/pipeline/artifact_validator.py must exist.  T-248 (audit F-7.3)."


def test_t248_validator_has_section_contracts_dict() -> None:
    """T-248 — validator must expose a SECTION_CONTRACTS dict."""
    src = read_backend_file("services", "pipeline", "artifact_validator.py")
    assert "SECTION_CONTRACTS" in src, (
        "artifact_validator.py must expose a SECTION_CONTRACTS dict mapping each "
        "stage_type to its required section headings.  T-248."
    )


def test_t248_section_contracts_covers_all_four_stages() -> None:
    """T-248 — SECTION_CONTRACTS must include keys for spec / plan / harness / tasks."""
    src = read_backend_file("services", "pipeline", "artifact_validator.py")
    for stage in ["spec", "plan", "harness", "tasks"]:
        assert (
            f'"{stage}"' in src
        ), f"SECTION_CONTRACTS must include a '{stage}' key.  T-248."


def test_t248_section_contracts_plan_includes_t239_t240_t242_additions() -> None:
    """T-248 — SECTION_CONTRACTS['plan'] must enforce Phase 22 additions.

    The validator is the single source of truth for mandatory section presence.
    If the new Phase 22 sections (ADR, anti-patterns, multi-tenancy, capacity,
    STRIDE, SLO, FMEA, AQA, Frontend Architecture) are not in the contract,
    they will never be enforced.
    """
    src = read_backend_file("services", "pipeline", "artifact_validator.py")
    required_plan_sections = [
        "## Architecture Decision Records",
        "## Architecture Anti-Patterns",
        "## Multi-tenancy Stance",
        "## Capacity Model",
        "## Threat Model",
        "## SLOs and Error Budgets",
        "## Failure Mode and Effects Analysis",
        "## Architecture Quality Attribute",
    ]
    missing = [s for s in required_plan_sections if s not in src]
    assert not missing, (
        f"SECTION_CONTRACTS['plan'] must enforce the new Phase 22 sections.  "
        f"Missing: {missing}.  T-248."
    )


def test_t248_missing_section_error_class_exists() -> None:
    """T-248 — MissingSectionError must be raised with a 'missing' attribute."""
    src = read_backend_file("services", "pipeline", "artifact_validator.py")
    assert (
        "class MissingSectionError" in src
    ), "artifact_validator.py must define a MissingSectionError exception.  T-248."
    # The error must expose the absent section list.
    assert "missing" in src, (
        "MissingSectionError must expose a 'missing' attribute listing absent "
        "section headings.  T-248."
    )


def test_t248_validator_runs_before_critic_in_stage_manager() -> None:
    """T-248 — stage_manager must call validator BEFORE critic.

    Order matters: section presence is the cheaper gate (zero LLM cost) and
    catches a class of generic format failures that would otherwise burn a
    critic call.
    """
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    assert (
        "artifact_validator" in src or "MissingSectionError" in src
    ), "stage_manager must import the artifact_validator.  T-248."
    assert (
        "critic_review" in src or "StageCriticResult" in src
    ), "stage_manager must invoke the critic.  T-247 / T-248."
    validator_pos = src.find("artifact_validator")
    critic_pos = src.find("critic_review")
    assert validator_pos >= 0 and critic_pos >= 0, (
        "stage_manager must reference both artifact_validator and critic_review "
        "so their ordering can be verified.  T-248."
    )
    assert validator_pos < critic_pos, (
        "stage_manager must call artifact_validator BEFORE critic_review — "
        "validator is the cheaper gate (zero LLM cost).  T-248."
    )


def test_t248_conditional_frontend_section_sentinel_detection_exists() -> None:
    """T-248 — validator must conditionally enforce Frontend Architecture section.

    The Frontend section is mandatory only when the spec mentions a browser-
    facing surface.  Detection sentinels: UI / web / app / page / screen /
    dashboard.
    """
    src = read_backend_file("services", "pipeline", "artifact_validator.py")
    # The sentinel list must mention at least three of the six sentinels.
    sentinels = ["UI", "web", "app", "page", "screen", "dashboard"]
    found = sum(1 for s in sentinels if s in src or s.lower() in src.lower())
    assert found >= 3, (
        f"artifact_validator.py must detect UI sentinels to conditionally "
        f"enforce the Frontend Architecture section.  Found {found}/6 sentinels.  "
        f"T-248."
    )


# ===========================================================================
# T-249 — harness/prompt_eval/: Offline eval suite + prompt versioning
# ===========================================================================


def test_t249_prompt_eval_directory_exists() -> None:
    """T-249 — harness/prompt_eval/ must exist."""
    path = REPO_ROOT / "harness" / "prompt_eval"
    assert (
        path.exists() and path.is_dir()
    ), "harness/prompt_eval/ directory must exist.  T-249 (audit F-7.4)."


def test_t249_golden_workspaces_directory_exists() -> None:
    """T-249 — harness/prompt_eval/golden_workspaces/ must exist with ≥ 3 snapshots."""
    path = REPO_ROOT / "harness" / "prompt_eval" / "golden_workspaces"
    assert (
        path.exists() and path.is_dir()
    ), "harness/prompt_eval/golden_workspaces/ directory must exist.  T-249."
    snapshots = [p for p in path.iterdir() if p.is_dir()]
    assert len(snapshots) >= 3, (
        f"harness/prompt_eval/golden_workspaces/ must contain ≥ 3 snapshots "
        f"(simple SaaS CRUD, AI-facing product, real-time / event-driven).  "
        f"Found {len(snapshots)}.  T-249."
    )


def test_t249_graders_directory_exists() -> None:
    """T-249 — harness/prompt_eval/graders/ must exist."""
    path = REPO_ROOT / "harness" / "prompt_eval" / "graders"
    assert (
        path.exists() and path.is_dir()
    ), "harness/prompt_eval/graders/ directory must exist.  T-249."


def test_t249_graders_cover_four_categories() -> None:
    """T-249 — graders must cover Coverage / Quality / Format / Safety.

    The audit identified four distinct grader axes.  All four must be
    represented to gate prompt changes meaningfully.
    """
    path = REPO_ROOT / "harness" / "prompt_eval" / "graders"
    assert path.exists() and path.is_dir(), (
        "harness/prompt_eval/graders/ must exist (precondition for axis check).  "
        "T-249."
    )
    combined = "\n".join(p.read_text(encoding="utf-8") for p in path.rglob("*.py"))
    for axis in ["coverage", "quality", "format", "safety"]:
        assert (
            axis in combined.lower()
        ), f"Graders must include at least one '{axis}' grader axis.  T-249."


def test_t249_run_py_cli_exists() -> None:
    """T-249 — harness/prompt_eval/run.py CLI must exist."""
    path = REPO_ROOT / "harness" / "prompt_eval" / "run.py"
    assert path.exists(), (
        "harness/prompt_eval/run.py CLI must exist so engineers can run "
        "'uv run python -m prompt_eval.run --version <new> --baseline <old>'.  "
        "T-249."
    )


def test_t249_run_py_supports_version_and_baseline_flags() -> None:
    """T-249 — run.py must accept --version and --baseline flags."""
    path = REPO_ROOT / "harness" / "prompt_eval" / "run.py"
    assert path.exists(), (
        "harness/prompt_eval/run.py must exist (precondition for flag check).  "
        "T-249."
    )
    src = path.read_text(encoding="utf-8")
    assert (
        "--version" in src
    ), "run.py must accept a --version flag for the new prompt version.  T-249."
    assert (
        "--baseline" in src
    ), "run.py must accept a --baseline flag for the prior version.  T-249."


def test_t249_ci_workflow_for_prompt_eval_exists() -> None:
    """T-249 — .github/workflows/prompt-eval.yml must exist."""
    path = REPO_ROOT / ".github" / "workflows" / "prompt-eval.yml"
    assert path.exists(), (
        ".github/workflows/prompt-eval.yml must exist so any PR that bumps "
        "ASDD_PROMPT_VERSION runs the eval suite as a merge gate.  T-249."
    )


def test_t249_ci_workflow_gates_on_asdd_prompt_version_bump() -> None:
    """T-249 — the CI workflow must trigger when ASDD_PROMPT_VERSION changes."""
    path = REPO_ROOT / ".github" / "workflows" / "prompt-eval.yml"
    assert path.exists(), (
        ".github/workflows/prompt-eval.yml must exist (precondition for the "
        "trigger check).  T-249."
    )
    src = path.read_text(encoding="utf-8")
    assert "ASDD_PROMPT_VERSION" in src or "prompts/base.py" in src, (
        "prompt-eval.yml must trigger on changes to ASDD_PROMPT_VERSION (or the "
        "file prompts/base.py that defines it).  T-249."
    )


def test_t249_runbook_section_10_documents_prompt_experimentation() -> None:
    """T-249 — RUNBOOK.md §10 must document the prompt-experimentation workflow."""
    path = REPO_ROOT / "docs" / "RUNBOOK.md"
    assert path.exists(), "docs/RUNBOOK.md must exist."
    src = path.read_text(encoding="utf-8")
    assert "§10" in src or "## 10" in src or "## 10." in src or "# 10." in src, (
        "docs/RUNBOOK.md must include a §10 section documenting the prompt-"
        "experimentation workflow (branch → edit prompt → bump version → run "
        "eval → review delta → merge).  T-249."
    )
    assert "prompt_eval" in src or "prompt experimentation" in src.lower(), (
        "docs/RUNBOOK.md §10 must reference the prompt_eval suite or 'prompt "
        "experimentation' by name.  T-249."
    )


# ===========================================================================
# Cross-cutting: ASDD_PROMPT_VERSION bump for Phase 22
# ===========================================================================


def test_phase22_asdd_prompt_version_bumped() -> None:
    """Phase 22 must bump ASDD_PROMPT_VERSION above 1.7.1.

    Every prompt-structure change requires a version bump so the eval CI
    workflow runs.  Phase 22 changes spec / plan / harness / tasks / base
    prompts; without a version bump the eval gate is silently skipped.
    """
    src = _read_base_prompt()
    # Match the constant; current value is "asdd-v1.7.1".  Anything ≥ 1.8.0
    # is acceptable.
    match = re.search(r'ASDD_PROMPT_VERSION\s*=\s*"asdd-v(\d+)\.(\d+)\.(\d+)"', src)
    assert match is not None, (
        "ASDD_PROMPT_VERSION must be defined in backend/prompts/base.py.  " "Phase 22."
    )
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    # Pre-Phase-22 baseline is 1.7.1.  Phase 22 must bump at least the minor.
    assert (major, minor) > (1, 7), (
        f"ASDD_PROMPT_VERSION must bump to ≥ asdd-v1.8.0 for Phase 22.  Current: "
        f"asdd-v{major}.{minor}.{patch}.  T-249."
    )


# ===========================================================================
# Cross-cutting: critic + validator integration
# ===========================================================================


def test_critic_and_validator_both_wired_in_stage_manager() -> None:
    """Phase 22 — stage_manager must invoke both validator and critic.

    Without both calls wired, the quality gates have no enforcement surface.
    """
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    assert (
        "artifact_validator" in src or "MissingSectionError" in src
    ), "stage_manager must invoke the artifact_validator.  T-248."
    assert (
        "critic_review" in src or "StageCriticResult" in src
    ), "stage_manager must invoke critic_review.  T-247."


# ===========================================================================
# Cross-cutting: structural completeness
# ===========================================================================


def test_phase22_does_not_remove_existing_phase21_invariants() -> None:
    """Phase 22 must not regress Phase 21 invariants.

    A meta-test that the new prompt rules don't accidentally undo the Stripe
    payments harness contracts (e.g., by removing the requirement for
    contract tests).
    """
    src = _read_harness_prompt()
    # Phase 21 relies on contract tests being mandatory in the harness prompt.
    assert "Contract tests" in src or "contract" in src.lower(), (
        "harness.py must still require contract tests — Phase 21's webhook "
        "tests depend on this.  Phase 22 must not regress.  T-244."
    )
    # Phase 21 relies on security tests being mandatory.
    assert "Security tests" in src or "security" in src.lower(), (
        "harness.py must still require security tests — Phase 21's IDOR and "
        "idempotency invariants depend on this.  Phase 22 must not regress.  T-244."
    )


def test_issue7_provider_completion_diagnostics_are_wired() -> None:
    """Issue #7 — provider max-token stops must be observable by StageManager."""
    base_src = read_backend_file("services", "llm", "base.py")
    assert "def stream" in base_src and "last_completion" not in base_src, (
        "BaseLLMAdapter.stream signature must remain stable; completion metadata "
        "belongs on concrete adapters/wrappers, not the abstract interface."
    )
    src = (
        read_backend_file("services", "llm", "completion.py")
        + read_backend_file("services", "llm", "openai_adapter.py")
        + read_backend_file("services", "llm", "anthropic_adapter.py")
        + read_backend_file("services", "llm", "google_adapter.py")
        + read_backend_file("services", "llm", "instrumented_adapter.py")
    )
    assert "LLMCompletionInfo" in src and "last_completion" in src, (
        "Provider adapters and InstrumentedAdapter must expose last_completion "
        "metadata so StageManager can detect token-limit truncation. Issue #7."
    )
    assert "stopped_by_limit" in src and "finish_reason" in src, (
        "Completion diagnostics must normalise finish_reason and stopped_by_limit. "
        "Issue #7."
    )


def test_issue7_incomplete_output_gate_and_no_partial_disconnect_persistence() -> None:
    """Issue #7 — incomplete outputs are blocked; interrupted partials are discarded."""
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    assert "incomplete_output" in src and "override_allowed" in src, (
        "StageManager must persist incomplete generations as a regenerate-only "
        "quality gate. Issue #7."
    )
    assert (
        "PIPELINE_INTERRUPTED_STREAMS" in src
    ), "Interrupted generation streams must be observable. Issue #7."
    assert "partial_content = _strip_code_fence(accumulated)" not in src, (
        "Client disconnect cleanup must not persist accumulated partial_content "
        "as a normal StageVersion. Issue #7."
    )


def test_issue7_cache_writes_after_completeness_validation() -> None:
    """Issue #7 — shallow/truncated outputs must never enter generation cache."""
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    completeness_pos = src.find("validate_artifact_completeness")
    cache_pos = src.rfind("set_cached_generation(redis, cache_key")
    assert completeness_pos >= 0 and cache_pos >= 0, (
        "StageManager must both validate artifact completeness and write successful "
        "generations to cache. Issue #7."
    )
    assert completeness_pos < cache_pos, (
        "The completeness validation code path must appear before cache writes so "
        "incomplete outputs cannot be cached. Issue #7."
    )


def test_issue9_technology_safety_policy_and_validator_are_wired() -> None:
    """Issue #9 — deterministic technology safety must be a runtime gate."""
    policy = BACKEND_ROOT / "services" / "pipeline" / "tech_safety_policy.json"
    validator = BACKEND_ROOT / "services" / "pipeline" / "tech_safety.py"
    assert (
        policy.exists()
    ), "Technology safety must have a committed versioned policy. Issue #9."
    assert (
        validator.exists()
    ), "Technology safety must have a deterministic runtime validator. Issue #9."
    policy_data = json.loads(policy.read_text(encoding="utf-8"))
    reviewed = date.fromisoformat(policy_data["last_reviewed"])
    max_age = int(policy_data["max_age_days"])
    assert date.today() - reviewed <= timedelta(days=max_age), (
        "The committed technology safety policy is stale. Re-review and update "
        "last_reviewed before accepting generated stacks. Issue #9."
    )
    src = validator.read_text(encoding="utf-8")
    assert (
        "parse_technology_stack" in src and "Technology Stack and Rationale" in src
    ), "The validator must parse the PLAN Technology Stack table. Issue #9."
    assert "/v1/querybatch" in src and "endoflife.date" in src, (
        "Technology safety must include bounded advisory and lifecycle checks. "
        "Issue #9."
    )


def test_issue9_stage_manager_blocks_before_cache_and_finalise() -> None:
    """Issue #9 — unsafe technology is gated before cache + revalidated at finalise.

    Issue #34 update: a technology_safety block is now OVERRIDABLE (the user owns
    the artifact and may finalise it as-is), so the previous "cannot be
    overridden" guard is gone.  The gate still runs before cache writes and
    finalise still revalidates an un-overridden draft.
    """
    src = read_backend_file("services", "pipeline", "stage_manager.py")
    validation_pos = src.find("await self._ensure_technology_safe")
    cache_pos = src.rfind("set_cached_generation(redis, cache_key")
    assert "TECH_SAFETY_GATE_KIND" in src and "technology_safety" in src, (
        "StageManager must reuse the quality gate with kind=technology_safety. "
        "Issue #9."
    )
    assert (
        validation_pos >= 0 and cache_pos >= 0 and validation_pos < cache_pos
    ), "Technology safety validation must run before cache writes. Issue #9."
    assert (
        "Current stage version has unsafe technology choices" in src
    ), "Finalise must revalidate and reject unsafe technology choices. Issue #9."


def test_issue9_prompt_eval_uses_shared_policy_data() -> None:
    """Issue #9 — eval denylist must not drift from the runtime policy."""
    src = (REPO_ROOT / "harness" / "prompt_eval" / "graders" / "quality.py").read_text(
        encoding="utf-8"
    )
    assert "tech_safety_policy.json" in src and "hard_denylists" in src, (
        "Prompt-eval deprecated-choice checks must read the shared tech-safety "
        "policy instead of maintaining a separate regex list. Issue #9."
    )
