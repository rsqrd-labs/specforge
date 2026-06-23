"""Golden-corpus gate for the Phase-B compression ladder.

Asserts the contract the plan promises, not merely that the code runs:

* termination — every case ends ``est_tokens(output) <= budget``;
* the Rung-0 byte-identical pin for under-budget input;
* lossless Rung-1 structural cleanup (noise dropped, requirements kept);
* normative-first retention under the Rung-3 clamp (the discriminating property).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services.llm.usage import estimate_tokens
from services.pipeline.problem_compressor import compress_problem_statement

PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"

_CORPUS = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evals"
    / "golden_prompts"
    / "problem_compression_golden.json"
)


def _load_cases() -> list[dict]:
    data = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return data["cases"]


def _build_statement(case: dict) -> str:
    if "problem_statement" in case:
        return case["problem_statement"]
    parts: list[str] = []
    if "problem_statement_prefix" in case:
        parts.append(case["problem_statement_prefix"])
    if "fr_unit" in case:
        parts.append(
            "".join(case["fr_unit"].format(n=n) for n in range(1, case["fr_count"] + 1))
        )
    if "narrative_filler" in case:
        parts.append(case["narrative_filler"] * case["narrative_repeat"])
    if "problem_statement_suffix" in case:
        parts.append(case["problem_statement_suffix"])
    return "\n\n".join(parts)


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_golden_case(case: dict) -> None:
    raw = _build_statement(case)
    budget = case["budget_tokens"]
    text, rung = compress_problem_statement(raw, budget, PROVIDER, MODEL)

    # Termination — the core guarantee, holds for every case.
    assert (estimate_tokens(PROVIDER, MODEL, text) or 0) <= budget

    if "expected_rung" in case:
        assert rung == case["expected_rung"]

    if case.get("byte_identical"):
        assert text == raw

    for rid in case.get("must_retain_ids", []):
        assert rid in text, f"{case['id']}: lost normative id {rid}"

    for needle in case.get("must_drop_substrings", []):
        assert needle not in text, f"{case['id']}: failed to drop {needle!r}"

    for needle in case.get("must_not_contain", []):
        assert needle not in text, f"{case['id']}: unexpectedly kept {needle!r}"

    if case.get("retain_all_fr"):
        for n in range(1, case["fr_count"] + 1):
            assert f"FR-{n:03d}" in text, f"{case['id']}: dropped FR-{n:03d}"

    # No malformed/truncated requirement id ever leaks (mid-cut FR-0 / SEC-0).
    assert not re.search(r"\b(?:FR|NFR|SEC)-\d{1,2}\b", text)
