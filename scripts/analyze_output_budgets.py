#!/usr/bin/env python3
"""Phase-4 output-budget analysis (issue #26).

Reads the `llm_cost_events` ledger, computes the real output-token distribution
per (operation, provider), and prints an evidence-backed right-sizing
recommendation for each pair. It is **advisory only**: it never edits code and
never touches the ledger. To apply a recommendation, add the proposed value to
`OUTPUT_TOKEN_BUDGET_OVERRIDES` in `backend/services/llm/output_budget.py` after
the review described in `docs/evals/OUTPUT_BUDGET_TUNING.md`.

Usage (from repo root or backend/):

    cd backend
    uv run python ../scripts/analyze_output_budgets.py --since-days 28 --format markdown

Against an empty or sparse ledger every row reads "insufficient_samples" / no
change — the correct, conservative behavior when there is no evidence to act on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Config validation requires a baseline env even though this script only reads
# the DB. Real DATABASE_URL must be provided by the operator; the rest are inert
# placeholders so importing `config`/`database` does not fail.
_ENV_DEFAULTS = {
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_PRIVATE_KEY": "analysis",
    "JWT_PUBLIC_KEY": "analysis",
    "GOOGLE_CLIENT_ID": "analysis",
    "GOOGLE_CLIENT_SECRET": "analysis",
    "FRONTEND_URL": "http://localhost:5173",
    "ENCRYPTION_MASTER_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "CSRF_SECRET": "analysis",
    "ENVIRONMENT": "development",
}
for key, value in _ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)

from services.llm.cost_ledger import output_token_percentiles  # noqa: E402
from services.llm.output_budget import (  # noqa: E402
    output_budget_for_operation,
    recommend_output_budget,
)


async def _gather(since: datetime | None, operations: list[str] | None) -> list[dict]:
    from database import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        distributions = await output_token_percentiles(
            db, since=since, operations=operations
        )

    report: list[dict[str, Any]] = []
    for dist in distributions:
        operation = dist["operation"]
        provider = dist["provider"]
        try:
            current = output_budget_for_operation(operation, provider)
        except ValueError:
            # An operation present in the ledger but not in the budget table
            # (e.g. a renamed/removed op). Surface it without a recommendation.
            current = 0
        rec = recommend_output_budget(
            operation,
            provider,
            samples=dist["samples"],
            p95_output_tokens=dist["p95_output_tokens"],
            truncation_rate=dist["truncation_rate"],
            current_budget=current,
            # Ceiling is per-model, not per-provider; a *reduction* never trips
            # it, so leave it unset and let the floor + headroom govern.
            model_ceiling=None,
        )
        report.append({"distribution": dist, "recommendation": rec.__dict__})
    return report


def _format_markdown(report: list[dict]) -> str:
    lines = [
        "# Output Budget Analysis",
        "",
        (
            "| operation | provider | samples | p50 | p90 | p95 | max | trunc% | "
            "current | recommend | rationale |"
        ),
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|",
    ]
    for entry in report:
        d = entry["distribution"]
        r = entry["recommendation"]
        trunc = d["truncation_rate"]
        rec = r["recommended_budget"]
        lines.append(
            "| {op} | {prov} | {n} | {p50} | {p90} | {p95} | {mx} | {tr} | "
            "{cur} | {rec} | {why} |".format(
                op=d["operation"],
                prov=d["provider"],
                n=d["samples"],
                p50=d["p50_output_tokens"],
                p90=d["p90_output_tokens"],
                p95=d["p95_output_tokens"],
                mx=d["max_output_tokens"],
                tr=f"{trunc * 100:.2f}" if trunc is not None else "—",
                cur=r["current_budget"],
                rec="—" if rec is None else rec,
                why=r["rationale"],
            )
        )
    if not report:
        lines.append("| _(ledger empty for the window)_ ||||||||||| |")
    lines += [
        "",
        (
            "Recommendations are advisory. Promote one only after the gate in "
            "`docs/evals/OUTPUT_BUDGET_TUNING.md`, then add it to "
            "`OUTPUT_TOKEN_BUDGET_OVERRIDES`."
        ),
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evidence-backed output-budget right-sizing from the ledger."
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=28,
        help="Look-back window in days (default 28 — ~the plan's 2-4 weeks).",
    )
    parser.add_argument(
        "--operation",
        action="append",
        help="Restrict to one or more operations (repeatable). Default: all.",
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    since = (
        datetime.now(timezone.utc) - timedelta(days=args.since_days)
        if args.since_days > 0
        else None
    )
    report = asyncio.run(_gather(since, args.operation))

    rendered = (
        json.dumps(report, indent=2, default=str)
        if args.format == "json"
        else _format_markdown(report)
    )
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
