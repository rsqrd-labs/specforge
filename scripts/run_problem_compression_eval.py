#!/usr/bin/env python3
"""Phase-C promotion gate for the abstractive problem-statement compressor (Rung 2).

See ``docs/evals/PROBLEM_COMPRESSION_PROMOTION.md``. Two modes:

* **dry-run (default, CI-safe, no API).** Proves the *structural* promotion
  invariant: Rung 2 keeps every normative block verbatim and first, so the
  normative-retention ratio is **1.0 by construction**. For each corpus case the
  dry-run partitions the cleaned statement exactly as the runtime does and
  asserts ``normative_retention(raw, normative_prefix) == (total, total)``. Any
  case that loses a requirement ID is a hard failure (exit 1).

* **--live (manual, calls provider APIs).** Runs the real judge map-reduce and
  reports the *measured* normative-retention ratio (must stay ~1.0) and whether
  each result lands within budget at Rung 2. The narrative semantic-equivalence
  judgement is a human read of the condensed output — the step the dry-run cannot
  produce. Promote (flip ``problem_statement_abstractive``) only after that read.

Mirrors ``scripts/run_llm_route_eval.py``: a deterministic CI gate plus a
documented manual live gate, never a live judge call in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_DRY_RUN_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql+asyncpg://dry-run:dry-run@localhost/specforge",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_PRIVATE_KEY": "dry-run",
    "JWT_PUBLIC_KEY": "dry-run",
    "GOOGLE_CLIENT_ID": "dry-run",
    "GOOGLE_CLIENT_SECRET": "dry-run",
    "FRONTEND_URL": "http://localhost:5173",
    "ANTHROPIC_API_KEY": "",
    "OPENAI_API_KEY": "",
    "GOOGLE_API_KEY": "",
    "ENCRYPTION_MASTER_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "CSRF_SECRET": "dry-run",
    "ENVIRONMENT": "development",
}
for _key, _value in _DRY_RUN_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

from services.pipeline import problem_compressor as pc  # noqa: E402

DEFAULT_DATASET = (
    REPO_ROOT
    / "docs"
    / "evals"
    / "golden_prompts"
    / "problem_compression_rung2_golden.json"
)


def _build_statement(case: dict[str, Any]) -> str:
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
        parts.append(case["narrative_filler"] * case.get("narrative_repeat", 1))
    if "problem_statement_suffix" in case:
        parts.append(case["problem_statement_suffix"])
    return "\n\n".join(parts)


def _normative_prefix(cleaned: str) -> str:
    """The verbatim normative block Rung 2 keeps first (mirrors _rung2_abstractive)."""
    blocks = pc._split_blocks(cleaned)
    normative = [b for b in blocks if pc._is_normative_block(b)]
    return "\n\n".join(normative)


def _dry_run(cases: list[dict[str, Any]], provider: str, model: str) -> int:
    print("Problem-compression Rung-2 dry-run (no API calls)\n")
    failures = 0
    for case in cases:
        raw = _build_statement(case)
        cleaned = pc._rung1_cleanup(raw)
        prefix = _normative_prefix(cleaned)
        retained, total = pc.normative_retention(raw, prefix)
        ratio = 1.0 if total == 0 else retained / total
        ok = retained == total
        failures += 0 if ok else 1
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {case['id']}: "
            f"normative_retention={retained}/{total} ({ratio:.0%}) "
            f"raw_tokens={pc._estimate(provider, model, raw)} "
            f"budget={case['budget_tokens']}"
        )
    print(
        f"\nStructural invariant (normative kept verbatim ⇒ 100% retention): "
        f"{len(cases) - failures}/{len(cases)} cases pass."
    )
    if failures:
        print("FAILED — a requirement ID would be lost; do not promote.")
        return 1
    print("OK. The cheap-vs-quality narrative comparison is the manual --live step.")
    return 0


async def _live(cases: list[dict[str, Any]], provider: str, model: str) -> int:
    pc.settings.problem_statement_compression = True
    pc.settings.problem_statement_abstractive = True
    print(f"Problem-compression Rung-2 LIVE eval (provider={provider})\n")
    failures = 0
    for case in cases:
        raw = _build_statement(case)
        budget = case["budget_tokens"]
        text, rung = await pc._compress(raw, budget, provider, model, None)
        retained, total = pc.normative_retention(raw, text)
        ratio = 1.0 if total == 0 else retained / total
        out_tokens = pc._estimate(provider, model, text)
        within_budget = out_tokens <= budget
        ok = rung == "2" and retained == total and within_budget
        failures += 0 if ok else 1
        print(
            f"  [{'PASS' if ok else 'WARN'}] {case['id']}: rung={rung} "
            f"normative_retention={retained}/{total} ({ratio:.0%}) "
            f"within_budget={within_budget} out_tokens={out_tokens}"
        )
    print(
        f"\n{len(cases) - failures}/{len(cases)} cases hit Rung 2 at ~100% normative "
        "retention within budget."
    )
    print(
        "Read the condensed narratives by hand for semantic equivalence before "
        "flipping `problem_statement_abstractive`."
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call provider APIs and run the real abstractive pass (manual gate).",
    )
    args = parser.parse_args()

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))["cases"]
    if args.live:
        return asyncio.run(_live(cases, args.provider, args.model))
    return _dry_run(cases, args.provider, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
