"""Issue #12 (Phase 5) — the offline Brave-grounding comparison gate.

These pin the deterministic, CI-safe surface of
``scripts/compare_brave_grounding.py``: the corpus schema, the **fail-open
identity** dry run (an empty research block is a byte-identical no-op for every
in-scope stage), the finding/verdict comparison logic, the live-mode
preconditions, and the billing-free block-assembly seam. The live
generation/quality measurement itself is a manual operator step and is never run
here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_brave_grounding.py"
_spec = importlib.util.spec_from_file_location("compare_brave_grounding", _SCRIPT)
assert _spec and _spec.loader
cbg = importlib.util.module_from_spec(_spec)
sys.modules["compare_brave_grounding"] = cbg
_spec.loader.exec_module(cbg)

from services.research.brave_client import BraveResult, BraveSnippet  # noqa: E402


# ---------------------------------------------------------------------------
# Corpus schema
# ---------------------------------------------------------------------------
def test_default_corpus_loads_and_is_valid() -> None:
    corpus = cbg._load_corpus(cbg.DEFAULT_CORPUS)
    assert len(corpus) >= 3
    ids = [c["id"] for c in corpus]
    assert len(ids) == len(set(ids)), "corpus ids must be unique"
    # A recency-neutral control must exist so the comparison cannot be claimed
    # to favor grounding spuriously.
    assert any(c["category"] == "control" for c in corpus)


def test_load_corpus_rejects_empty_array(tmp_path: Path) -> None:
    bad = tmp_path / "empty.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty"):
        cbg._load_corpus(bad)


def test_validate_case_rejects_out_of_scope_stage() -> None:
    case = {
        "id": "x",
        "name": "X",
        "category": "control",
        "problem_statement": "Build something.",
        "recency_rationale": "n/a",
        "stages": ["harness"],
    }
    with pytest.raises(ValueError, match="not in scope"):
        cbg._validate_case(case)


def test_validate_case_rejects_missing_fields() -> None:
    with pytest.raises(ValueError, match="missing fields"):
        cbg._validate_case({"id": "x"})


def test_validate_case_rejects_empty_problem_statement() -> None:
    case = {
        "id": "x",
        "name": "X",
        "category": "control",
        "problem_statement": "   ",
        "recency_rationale": "n/a",
        "stages": ["spec"],
    }
    with pytest.raises(ValueError, match="empty problem_statement"):
        cbg._validate_case(case)


def test_load_corpus_rejects_duplicate_ids(tmp_path: Path) -> None:
    dup = tmp_path / "dup.json"
    case = {
        "id": "same",
        "name": "X",
        "category": "control",
        "problem_statement": "Build a thing.",
        "recency_rationale": "n/a",
        "stages": ["spec"],
    }
    import json

    dup.write_text(json.dumps([case, dict(case)]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        cbg._load_corpus(dup)


# ---------------------------------------------------------------------------
# Dry run — the fail-open identity
# ---------------------------------------------------------------------------
def test_dry_run_default_corpus_passes() -> None:
    corpus = cbg._load_corpus(cbg.DEFAULT_CORPUS)
    report = cbg._run_dry_run(corpus)
    assert report["mode"] == "dry_run"
    assert report["fail_open_identity_pass"] is True
    assert report["research_injection_pass"] is True
    assert report["passed"] is True
    assert report["manual_operator_approval_required"] is True


@pytest.mark.parametrize("stage_type", list(cbg.IN_SCOPE_STAGES))
def test_empty_research_block_is_byte_identical_no_op(stage_type: str) -> None:
    """The core fail-open guarantee, asserted directly on each prompt module:
    research_context='' renders identically to no research_context key at all."""
    module = cbg.prompt_builder._PROMPT_MODULES[stage_type]
    deps = cbg._synth_deps(stage_type, "Build a thing.", upstream={})

    without_key = dict(deps)
    without_key.pop("research_context", None)
    with_empty = {**deps, "research_context": ""}

    assert module.build_user_prompt(without_key) == module.build_user_prompt(with_empty)


@pytest.mark.parametrize("stage_type", list(cbg.IN_SCOPE_STAGES))
def test_non_empty_research_block_is_injected(stage_type: str) -> None:
    module = cbg.prompt_builder._PROMPT_MODULES[stage_type]
    deps = cbg._synth_deps(stage_type, "Build a thing.", upstream={})
    rendered = module.build_user_prompt(
        {**deps, "research_context": cbg._INJECTION_SENTINEL}
    )
    assert cbg._INJECTION_SENTINEL in rendered


def test_main_dry_run_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cbg.main(["--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"mode": "dry_run"' in out


# ---------------------------------------------------------------------------
# Verdict + finding-collection logic
# ---------------------------------------------------------------------------
def test_verdict_helps_neutral_regressed() -> None:
    assert cbg._verdict(off_count=3, on_count=1) == "helps"
    assert cbg._verdict(off_count=2, on_count=2) == "neutral"
    assert cbg._verdict(off_count=0, on_count=2) == "regressed"


def test_collect_findings_flags_an_empty_artifact() -> None:
    """An empty artifact trips both the section and completeness gates and is
    flattened into structured findings (proves the raise→list adapter)."""
    findings = cbg._collect_findings("spec", "", {"problem_statement": "x"})
    assert findings, "an empty spec artifact must produce findings"
    gates = {f["gate"] for f in findings}
    assert "sections" in gates
    assert all({"gate", "code", "detail"} <= set(f) for f in findings)


def test_collect_findings_excludes_critic() -> None:
    """Only the two deterministic gates contribute — never the LLM critic."""
    findings = cbg._collect_findings("spec", "", {"problem_statement": "x"})
    assert {f["gate"] for f in findings} <= {"sections", "completeness"}


def test_validation_deps_strips_research_block_but_keeps_upstream() -> None:
    deps = {
        "problem_statement": "build a batch log processor",
        "spec": "FR-1 ...",
        "research_context": "the latest dashboard frameworks",
    }
    out = cbg._validation_deps(deps)
    assert "research_context" not in out
    assert out["problem_statement"] == deps["problem_statement"]
    assert out["spec"] == deps["spec"]


def test_research_block_does_not_confound_plan_conditional_sections() -> None:
    """The confound the strip fixes: the research block can contain a UI word
    ('dashboard') that trips plan's conditional Frontend Architecture section.
    Stripping research_context (what _live_stage now does) must keep that
    untrusted input from inventing a 'missing section' on the on-arm."""
    # No UI words in the genuine inputs; only the research block carries one.
    deps = {
        "problem_statement": "build a command-line batch log processor",
        "spec": "FR-1 ingest files; AC-1 exit code 0",
        "research_context": "current best-practice dashboard and web frameworks",
    }
    artifact = "## Architecture\n\nNo frontend here."

    fa = "## Frontend Architecture"
    raw = cbg._collect_findings("plan", artifact, deps)
    stripped = cbg._collect_findings("plan", artifact, cbg._validation_deps(deps))

    # Unstripped: the research block's 'dashboard' spuriously demands the section.
    assert any(f["detail"] == fa for f in raw)
    # Stripped (the production path): no phantom Frontend Architecture finding.
    assert not any(f["detail"] == fa for f in stripped)


# ---------------------------------------------------------------------------
# Live preconditions (no network) — refuse a run that can't measure anything
# ---------------------------------------------------------------------------
def test_live_requires_brave_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbg.settings, "brave_search_api_key", "", raising=False)
    with pytest.raises(SystemExit, match="BRAVE_SEARCH_API_KEY"):
        cbg._require_live_preconditions("anthropic")


def test_live_requires_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbg.settings, "brave_search_api_key", "k", raising=False)
    monkeypatch.setattr(cbg.settings, "anthropic_api_key", "", raising=False)
    with pytest.raises(SystemExit, match="provider 'anthropic'"):
        cbg._require_live_preconditions("anthropic")


# ---------------------------------------------------------------------------
# Block assembly seam — production assembly, no billing/quota/DB
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_build_block_empty_when_brave_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live fail-open: Brave grounding nothing collapses the on-arm onto the
    off-arm (block == '')."""

    async def _none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cbg.brave_client, "fetch", _none)
    block, sources = await cbg._build_block("Build a thing.")
    assert block == ""
    assert sources == ()


@pytest.mark.asyncio
async def test_build_block_uses_production_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Brave result flows through ``_assemble_block`` — same header
    framing + http(s)-allowlisted provenance production injects."""
    result = BraveResult(
        query="q",
        results=(
            BraveSnippet(
                url="https://fastapi.tiangolo.com/release",
                title="FastAPI release notes",
                snippets=("FastAPI now recommends the lifespan handler.",),
            ),
        ),
        sources=(),
    )

    async def _hit(*_args, **_kwargs):
        return result

    monkeypatch.setattr(cbg.brave_client, "fetch", _hit)
    block, sources = await cbg._build_block("Build a FastAPI service.")
    assert "External Research Context" in block
    assert len(sources) == 1
    assert sources[0].url == "https://fastapi.tiangolo.com/release"
