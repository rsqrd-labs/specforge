#!/usr/bin/env python3
"""Phase 5 pre-launch gate for Brave web-research grounding (issue #12).

Runs a fixed corpus of problem statements through generation **with Brave
grounding off vs on** and dumps the deterministic, zero-LLM validator findings
side by side. It exists to answer one launch question before the global
``brave_search_flag`` is flipped: *does grounding help, or is it at worst
neutral, with no fail-open regressions?* (plan §12 / Phase 5 acceptance.)

Two modes — the same split as ``scripts/run_llm_route_eval.py``:

* **Dry-run (default, CI-safe, no network).** Proves the two things that need to
  hold *before* anyone spends a provider/Brave call: the corpus is well-formed,
  and the **fail-open identity** holds — an empty research block yields a
  byte-identical prompt to the no-research baseline for every in-scope stage, and
  a non-empty block is actually injected. The empty-block no-op is the structural
  guarantee behind "no fail-open regressions"; it is asserted here, deterministic
  and reproducible, with no artifacts and no provider calls.

* **Live (``--live``, operator-gated).** Actually grounds each case (a real,
  operator-funded Brave call via ``brave_client``, bypassing billing/quota/DB),
  generates the in-scope stages twice through the real prompt modules + LLM
  gateway, and runs the production deterministic gates
  (``validate_sections`` + ``validate_artifact_completeness``) on both arms. The
  per-stage verdict is *helps / neutral / regressed* on the finding count; the
  run passes only if no stage regressed. This is the genuinely live measurement
  the route-eval dry run cannot produce; it is never run in CI.

What this tool deliberately does NOT do (no hacks, honest boundaries):

* It never calls ``research_service.fetch_context`` — that charges credits,
  consumes the daily quota, and writes to the DB/ledger. The block is built from
  the same lower-level seams production uses (``brave_client.fetch`` +
  ``research_service._assemble_block``: identical header framing, sanitisation,
  prompt-injection guard, and char bound) with none of the billing side effects.
* It never persists a StageVersion, charges a credit, or writes a COGS row. A
  live run spends real Brave API budget (the only way to measure real grounding)
  but touches no SpecForge billing state.
* It does not use the LLM critic. The critic is a non-deterministic judge model;
  the comparison is built only on the two deterministic structural gates so the
  side-by-side is reproducible.

Caveats (see docs/evals/BRAVE_GROUNDING_PROMOTION.md): the live on/off comparison
is single-sample and confounded by LLM sampling noise. The deterministic
structural findings dampen that, and a *neutral* result passes by design, so this
is a sound **directional** gate — not a statistically rigorous A/B. The corpus is
intentionally weighted toward recency-sensitive prompts (current framework/API
versions, current best practices) plus one recency-neutral control.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Importing ``config`` constructs Settings, which requires a handful of keys even
# for the offline dry run. Mirror run_llm_route_eval's harmless defaults so the
# CI-safe path imports without real secrets. ``setdefault`` never clobbers a real
# value an operator exported for a live run.
_DRY_RUN_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql+asyncpg://dry-run:dry-run@localhost/specforge",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_PRIVATE_KEY": "dry-run",
    "JWT_PUBLIC_KEY": "dry-run",
    "GOOGLE_CLIENT_ID": "dry-run",
    "GOOGLE_CLIENT_SECRET": "dry-run",
    "FRONTEND_URL": "http://localhost:5173",
    "ENCRYPTION_MASTER_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "CSRF_SECRET": "dry-run",
    "ENVIRONMENT": "development",
}
for _key, _value in _DRY_RUN_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

from config import settings  # noqa: E402
from services.llm.gateway import complete_with_timeout  # noqa: E402
from services.llm.model_catalog import default_model_for_operation  # noqa: E402
from services.pipeline import prompt_builder  # noqa: E402
from services.pipeline.artifact_validator import (  # noqa: E402
    IncompleteArtifactError,
    MissingSectionError,
    validate_artifact_completeness,
    validate_sections,
)
from services.research import brave_client, research_service  # noqa: E402

DEFAULT_CORPUS = (
    REPO_ROOT / "docs" / "evals" / "golden_prompts" / "brave_grounding_corpus.json"
)

# The stages that can carry grounding (mirrors the ``brave_research_stages``
# default). Each must have a registered prompt module and dependency list.
IN_SCOPE_STAGES = ("spec", "plan")

# Output budget for one offline generation. Generous enough for a full spec/plan
# artifact; this harness is not cost-sensitive and never writes the COGS ledger.
_GENERATION_MAX_TOKENS = 8192

# A sentinel woven into the research block during the dry-run injection check. It
# must not occur in any prompt template so its presence proves the block landed.
_INJECTION_SENTINEL = "BRAVE_GROUNDING_INJECTION_SENTINEL_7f3a"

# Deterministic placeholder for synthesized upstream deps in the dry-run identity
# check. Content is irrelevant there — the check is purely about whether the
# research block changes the rendered prompt — so a stable string keeps it
# reproducible.
_UPSTREAM_PLACEHOLDER = "## Upstream Artifact\n\nPlaceholder upstream content.\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Brave web-research grounding off vs on over a fixed corpus. "
            "Dry-run (default) is deterministic and CI-safe; --live runs real "
            "Brave + LLM calls for the pre-launch quality gate."
        )
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Run the real Brave + LLM comparison (operator-funded, off the "
            "production path). Requires BRAVE_SEARCH_API_KEY and a provider key. "
            "Default is the deterministic dry run."
        ),
    )
    parser.add_argument(
        "--provider",
        default="anthropic",
        help="LLM provider for live generation (default: anthropic).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model id for live generation. Defaults to the provider's core-"
            "generation spec model from the catalog, so it tracks what the "
            "pipeline actually routes."
        ),
    )
    args = parser.parse_args(argv)

    corpus = _load_corpus(args.corpus)

    if args.live:
        report = asyncio.run(
            _run_live(corpus, provider=args.provider, model=args.model)
        )
    else:
        report = _run_dry_run(corpus)

    rendered = (
        _render_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, indent=2, sort_keys=True)
    )
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    return 0 if report["passed"] else 1


# ---------------------------------------------------------------------------
# Corpus loading / validation
# ---------------------------------------------------------------------------
def _load_corpus(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Brave grounding corpus must be a non-empty JSON array")
    seen: set[str] = set()
    for case in data:
        _validate_case(case)
        if case["id"] in seen:
            raise ValueError(f"Duplicate corpus case id: {case['id']!r}")
        seen.add(case["id"])
    return data


def _validate_case(case: object) -> None:
    if not isinstance(case, dict):
        raise ValueError("Each corpus case must be a JSON object")
    required = {
        "id",
        "name",
        "category",
        "problem_statement",
        "recency_rationale",
        "stages",
    }
    missing = sorted(required - set(case))
    if missing:
        raise ValueError(f"Corpus case missing fields: {missing}")
    if (
        not isinstance(case["problem_statement"], str)
        or not case["problem_statement"].strip()
    ):
        raise ValueError(f"Corpus case {case['id']!r} has an empty problem_statement")
    stages = case["stages"]
    if not isinstance(stages, list) or not stages:
        raise ValueError(f"Corpus case {case['id']!r} must list at least one stage")
    for stage in stages:
        if stage not in IN_SCOPE_STAGES:
            raise ValueError(
                f"Corpus case {case['id']!r} stage {stage!r} is not in scope "
                f"{IN_SCOPE_STAGES}"
            )


# ---------------------------------------------------------------------------
# Dry run — corpus shape + the fail-open identity (deterministic, no network)
# ---------------------------------------------------------------------------
def _run_dry_run(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    cases: list[dict[str, Any]] = []
    all_pass = True
    for case in corpus:
        case_result = _dry_run_case(case)
        all_pass = (
            all_pass and case_result["identity_pass"] and case_result["injection_pass"]
        )
        cases.append(case_result)
    return {
        "mode": "dry_run",
        "corpus_size": len(corpus),
        "in_scope_stages": list(IN_SCOPE_STAGES),
        "fail_open_identity_pass": all(c["identity_pass"] for c in cases),
        "research_injection_pass": all(c["injection_pass"] for c in cases),
        "passed": all_pass,
        "manual_operator_approval_required": True,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "cases": cases,
    }


def _dry_run_case(case: dict[str, Any]) -> dict[str, Any]:
    """Assert the fail-open identity per in-scope stage for one problem statement.

    For each stage module: rendering with ``research_context=""`` must be
    byte-identical to rendering with no research at all (the empty block is a
    true no-op — the structural fail-open guarantee), and rendering with a
    sentinel block must inject that sentinel (so an on-run actually differs).
    """
    stages: list[dict[str, Any]] = []
    for stage_type in case["stages"]:
        module = prompt_builder._PROMPT_MODULES[stage_type]
        base_deps = _synth_deps(stage_type, case["problem_statement"], upstream={})

        without_key = dict(base_deps)
        without_key.pop("research_context", None)
        with_empty = {**base_deps, "research_context": ""}
        with_block = {**base_deps, "research_context": _INJECTION_SENTINEL}

        rendered_without = module.build_user_prompt(without_key)
        rendered_empty = module.build_user_prompt(with_empty)
        rendered_block = module.build_user_prompt(with_block)

        identity = rendered_without == rendered_empty
        injection = (
            _INJECTION_SENTINEL in rendered_block
            and _INJECTION_SENTINEL not in rendered_empty
        )
        stages.append(
            {
                "stage": stage_type,
                "identity_pass": identity,
                "injection_pass": injection,
            }
        )
    return {
        "case_id": case["id"],
        "category": case["category"],
        "identity_pass": all(s["identity_pass"] for s in stages),
        "injection_pass": all(s["injection_pass"] for s in stages),
        "stages": stages,
    }


def _synth_deps(
    stage_type: str, problem_statement: str, *, upstream: dict[str, str]
) -> dict[str, str]:
    """Build the dependency dict a prompt module's ``build_user_prompt`` reads.

    ``problem_statement`` and ``research_context`` are always present; each
    upstream stage the module depends on (per ``prompt_builder._DEPENDENCIES``)
    is filled from ``upstream`` when available (live threading: the just-
    generated spec feeds plan) or a deterministic placeholder (dry run).
    """
    deps: dict[str, str] = {
        "problem_statement": problem_statement,
        "research_context": "",
    }
    for dep in prompt_builder._DEPENDENCIES[stage_type]:
        deps[dep] = upstream.get(dep, _UPSTREAM_PLACEHOLDER)
    return deps


# ---------------------------------------------------------------------------
# Live run — real grounding + generation + deterministic gates
# ---------------------------------------------------------------------------
async def _run_live(
    corpus: list[dict[str, Any]], *, provider: str, model: str | None
) -> dict[str, Any]:
    _require_live_preconditions(provider)
    # One run-wide model keeps the off/on arms identical except for grounding; the
    # spec-generation operation key resolves the provider's core-gen default so it
    # tracks what the pipeline actually routes for a fresh stage.
    resolved_model = model or default_model_for_operation(provider, "spec.generate")
    started = time.perf_counter()

    cases: list[dict[str, Any]] = []
    for case in corpus:
        cases.append(await _live_case(case, provider=provider, model=resolved_model))

    regressed = [
        {"case_id": c["case_id"], "stage": s["stage"]}
        for c in cases
        for s in c["stages"]
        if s["verdict"] == "regressed"
    ]
    errored = [c["case_id"] for c in cases if c["error"]]
    passed = not regressed and not errored

    return {
        "mode": "live",
        "provider": provider,
        "model": resolved_model,
        "corpus_size": len(corpus),
        "in_scope_stages": list(IN_SCOPE_STAGES),
        "verdict_counts": _verdict_counts(cases),
        "regressions": regressed,
        "errored_cases": errored,
        "passed": passed,
        "manual_operator_approval_required": True,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "cases": cases,
    }


def _require_live_preconditions(provider: str) -> None:
    """Refuse a live run that cannot produce a real comparison.

    The Brave API key (not the ``brave_search_flag`` — this tool runs *before*
    the flag is flipped, bypassing ``fetch_context``) and a provider LLM key must
    both be present, or the off/on arms would be meaningless.
    """
    if not settings.brave_search_api_key.strip():
        raise SystemExit(
            "Live comparison needs BRAVE_SEARCH_API_KEY set (the flag itself is "
            "not required — this gate runs before the flag flip)."
        )
    provider_keys = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "google": settings.google_api_key,
    }
    if not (provider_keys.get(provider) or "").strip():
        raise SystemExit(
            f"Live comparison needs a configured API key for provider {provider!r}."
        )


async def _live_case(
    case: dict[str, Any], *, provider: str, model: str
) -> dict[str, Any]:
    """Ground one case, generate every in-scope stage off vs on, and gate both.

    Wrapped so a single Brave/LLM failure records on the case instead of
    aborting the whole corpus run.
    """
    try:
        block, sources = await _build_block(case["problem_statement"])
        # Thread each arm's upstream independently so plan-off reads spec-off and
        # plan-on reads spec-on — the arms never cross-contaminate.
        upstream_off: dict[str, str] = {}
        upstream_on: dict[str, str] = {}
        stages: list[dict[str, Any]] = []
        for stage_type in case["stages"]:
            stage_result = await _live_stage(
                stage_type,
                case["problem_statement"],
                block=block,
                upstream_off=upstream_off,
                upstream_on=upstream_on,
                provider=provider,
                model=model,
            )
            stages.append(stage_result)
        return {
            "case_id": case["id"],
            "category": case["category"],
            "grounded": bool(block),
            "source_count": len(sources),
            "stages": stages,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — surface, never abort the corpus
        return {
            "case_id": case["id"],
            "category": case["category"],
            "grounded": None,
            "source_count": None,
            "stages": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _live_stage(
    stage_type: str,
    problem_statement: str,
    *,
    block: str,
    upstream_off: dict[str, str],
    upstream_on: dict[str, str],
    provider: str,
    model: str,
) -> dict[str, Any]:
    module = prompt_builder._PROMPT_MODULES[stage_type]
    system = await module.get_system_prompt()

    deps_off = _synth_deps(stage_type, problem_statement, upstream=upstream_off)
    deps_on = _synth_deps(stage_type, problem_statement, upstream=upstream_on)
    deps_on["research_context"] = block

    artifact_off = await _generate(
        provider, model, system, module.build_user_prompt(deps_off), stage_type
    )
    artifact_on = await _generate(
        provider, model, system, module.build_user_prompt(deps_on), stage_type
    )

    # Thread this stage's output into each arm's upstream for the next stage.
    upstream_off[stage_type] = artifact_off
    upstream_on[stage_type] = artifact_on

    # The deterministic gates scan ``" ".join(deps.values())`` for conditional-
    # section sentinels (plan's Frontend Architecture) and upstream traceability
    # IDs. ``research_context`` is generation *input* grounding, not an upstream
    # artifact — leaving it in the validator deps would let the on-arm's ~12KB of
    # research text spuriously add a "required" section or phantom IDs, a
    # confound that has nothing to do with artifact quality. Strip it from BOTH
    # arms so the only difference the gates see is the generated artifact (plus
    # the legitimate, per-arm upstream-spec cascade, which we keep).
    findings_off = _collect_findings(
        stage_type, artifact_off, _validation_deps(deps_off)
    )
    findings_on = _collect_findings(stage_type, artifact_on, _validation_deps(deps_on))
    verdict = _verdict(len(findings_off), len(findings_on))

    return {
        "stage": stage_type,
        "off": {"finding_count": len(findings_off), "findings": findings_off},
        "on": {"finding_count": len(findings_on), "findings": findings_on},
        "verdict": verdict,
    }


async def _build_block(problem_statement: str) -> tuple[str, tuple[Any, ...]]:
    """Build the production research block for a problem statement, sans billing.

    Reuses the exact assembly seams ``fetch_context`` uses — the deterministic
    query builder, the real Brave client, and ``_assemble_block`` (header framing
    + sanitisation + prompt-injection guard + char bound + http(s) URL
    allowlist) — but none of the quota/credit/DB/cache machinery. Returns
    ``("", ())`` whenever Brave grounds nothing, exactly as production would,
    so the on-arm collapses onto the off-arm (the live fail-open case).
    """
    workspace = _CorpusWorkspace(problem_statement)
    query = research_service._build_query(workspace)
    if not query:
        return "", ()
    query_hash = research_service._query_hash(query)
    result = await brave_client.fetch(
        query,
        max_tokens=settings.brave_max_tokens,
        freshness=settings.brave_freshness,
        timeout=settings.brave_timeout_seconds,
    )
    if result is None or result.is_empty:
        return "", ()
    return research_service._assemble_block(result, query_hash)


def _validation_deps(deps: dict[str, str]) -> dict[str, str]:
    """Deps for the deterministic gates: every upstream artifact, never the
    research block. ``research_context`` is generation input grounding, so
    including it would confound the off/on validator comparison (see
    ``_live_stage``)."""
    return {key: value for key, value in deps.items() if key != "research_context"}


def _collect_findings(
    stage_type: str, artifact: str, deps: dict[str, str]
) -> list[dict[str, Any]]:
    """Run the two production deterministic gates and structure what they raise.

    ``validate_sections`` (missing required headings) and
    ``validate_artifact_completeness`` (per-section depth, spec id floors,
    traceability, markdown shape, task-count floor) both *raise* on failure; we
    flatten the exceptions into a stable list so the off/on arms compare cleanly.
    The LLM critic is intentionally excluded — non-deterministic.
    """
    findings: list[dict[str, Any]] = []
    try:
        validate_sections(stage_type, artifact, deps)
    except MissingSectionError as exc:
        for heading in exc.missing:
            findings.append(
                {"gate": "sections", "code": "missing_section", "detail": heading}
            )
    try:
        validate_artifact_completeness(stage_type, artifact, deps)
    except IncompleteArtifactError as exc:
        for issue in exc.issues:
            findings.append(
                {
                    "gate": "completeness",
                    "code": issue.code,
                    "detail": issue.detail,
                    "reference": issue.reference,
                }
            )
    return findings


def _verdict(off_count: int, on_count: int) -> str:
    if on_count < off_count:
        return "helps"
    if on_count > off_count:
        return "regressed"
    return "neutral"


def _verdict_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"helps": 0, "neutral": 0, "regressed": 0}
    for case in cases:
        for stage in case["stages"]:
            counts[stage["verdict"]] += 1
    return counts


async def _generate(
    provider: str, model: str, system: str, user: str, stage_type: str
) -> str:
    """One-shot generation via the real gateway, with no cost-ledger write.

    ``operation=None`` keeps this off the COGS ledger — a comparison harness must
    not pollute production cost telemetry.
    """
    return await complete_with_timeout(
        provider,
        model,
        system,
        user,
        max_tokens=_GENERATION_MAX_TOKENS,
        stage_type=stage_type,
        model_tier="offline_eval",
    )


class _CorpusWorkspace:
    """The minimal workspace surface ``research_service._build_query`` reads.

    ``_build_query`` reads ``name`` and ``problem_statement`` via ``getattr``;
    the corpus has no separate name, so the problem statement carries the query.
    """

    def __init__(self, problem_statement: str) -> None:
        self.name = ""
        self.problem_statement = problem_statement


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render_markdown(report: dict[str, Any]) -> str:
    if report["mode"] == "dry_run":
        return _render_dry_run_markdown(report)
    return _render_live_markdown(report)


def _render_dry_run_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Brave Grounding Comparison — Dry Run",
        "",
        f"- Corpus size: `{report['corpus_size']}`",
        f"- In-scope stages: `{', '.join(report['in_scope_stages'])}`",
        f"- Fail-open identity pass: `{report['fail_open_identity_pass']}`",
        f"- Research injection pass: `{report['research_injection_pass']}`",
        f"- Passed: `{report['passed']}`",
        "- Live promotion: manual operator approval required",
        "",
        "| Case | Identity | Injection |",
        "| --- | --- | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['identity_pass']} | "
            f"{case['injection_pass']} |"
        )
    return "\n".join(lines)


def _render_live_markdown(report: dict[str, Any]) -> str:
    counts = report["verdict_counts"]
    lines = [
        "# Brave Grounding Comparison — Live",
        "",
        f"- Provider/model: `{report['provider']}` / `{report['model']}`",
        f"- Corpus size: `{report['corpus_size']}`",
        f"- Verdicts: helps `{counts['helps']}`, neutral `{counts['neutral']}`, "
        f"regressed `{counts['regressed']}`",
        f"- Errored cases: `{len(report['errored_cases'])}`",
        f"- Passed (no regressions, no errors): `{report['passed']}`",
        "",
        "| Case | Stage | Grounded | Off findings | On findings | Verdict |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        if case["error"]:
            lines.append(f"| {case['case_id']} | — | ERROR | — | — | {case['error']} |")
            continue
        for stage in case["stages"]:
            lines.append(
                f"| {case['case_id']} | {stage['stage']} | {case['grounded']} | "
                f"{stage['off']['finding_count']} | {stage['on']['finding_count']} "
                f"| {stage['verdict']} |"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
