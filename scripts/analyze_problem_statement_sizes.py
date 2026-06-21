#!/usr/bin/env python3
"""Phase-A problem-statement size analysis (compression plan §8).

Reads the real distribution of stored problem-statement sizes and the assembled
prompt-token distribution, and reports **what fraction of real inputs exceed the
compression THRESHOLD** — i.e. how often compression would even run once it
ships. It is advisory only: it never edits code, never writes the DB.

Two sources, deliberately:

* **Problem-statement size** comes straight from the ``workspaces`` table — the
  authoritative source. ``llm_cost_events`` only records the *whole* assembled
  prompt (``input_tokens``), never the problem statement on its own, so it cannot
  answer the THRESHOLD question. Token size is estimated with the same utf-8-byte
  basis as ``services.llm.usage.estimate_tokens`` (``(octet_length + 3) / 4``) so
  this report and the runtime histograms agree.
* **Assembled-prompt size** comes from the ledger (``input_token_percentiles``),
  honoring "read from the ledger" for the half it actually has — this is the
  figure the window-fit reliability ceiling (§5) is measured against.

Usage (from repo root or backend/):

    cd backend
    uv run python ../scripts/analyze_problem_statement_sizes.py \
        --threshold-tokens 8000 --format markdown

Expected day-one reading: every stored statement today is <=10K chars (~2.5K
tokens), so the "over threshold" fraction will be ~0% against an 8K threshold.
That is the correct reading, not a broken script — the fraction only grows as
real large inputs arrive after the cap raise.
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


async def _problem_statement_distribution(
    db: Any, *, since: datetime | None, threshold_tokens: int
) -> dict[str, Any]:
    """Token-size distribution of stored problem statements from ``workspaces``.

    The token estimate mirrors ``estimate_tokens`` exactly: ``(octet_length + 3)
    / 4`` (utf-8 bytes, integer division). Only active workspaces contribute.
    """
    from sqlalchemy import case, func, select  # noqa: PLC0415

    from models import Workspace  # noqa: PLC0415

    # Token estimate per row, byte-identical to services.llm.usage.estimate_tokens:
    # (utf-8 byte length + 3) floor-divided by 4. `//` renders as SQL integer
    # division (`/` on two integer operands), which truncates == floors for the
    # non-negative lengths here, exactly like Python's `//`.
    token_est = (func.octet_length(Workspace.problem_statement) + 3) // 4

    def _pct(level: float, column: Any) -> Any:
        return func.percentile_cont(level).within_group(column.asc())

    stmt = select(
        func.count().label("samples"),
        _pct(0.50, token_est).label("p50"),
        _pct(0.90, token_est).label("p90"),
        _pct(0.95, token_est).label("p95"),
        func.max(token_est).label("max"),
        func.coalesce(
            func.avg(case((token_est > threshold_tokens, 1.0), else_=0.0)), 0.0
        ).label("over_threshold_fraction"),
        func.coalesce(
            func.sum(case((token_est > threshold_tokens, 1), else_=0)), 0
        ).label("over_threshold_count"),
    ).where(Workspace.status == "active")
    if since is not None:
        stmt = stmt.where(Workspace.created_at >= since)

    row = (await db.execute(stmt)).one()

    def _int(value: Any) -> int | None:
        return int(value) if value is not None else None

    return {
        "threshold_tokens": threshold_tokens,
        "samples": int(row.samples),
        "p50_tokens": _int(row.p50),
        "p90_tokens": _int(row.p90),
        "p95_tokens": _int(row.p95),
        "max_tokens": _int(row.max),
        "over_threshold_count": int(row.over_threshold_count),
        "over_threshold_fraction": float(row.over_threshold_fraction or 0.0),
    }


async def _gather(since: datetime | None, threshold_tokens: int) -> dict[str, Any]:
    from database import AsyncSessionLocal  # noqa: PLC0415
    from services.llm.cost_ledger import input_token_percentiles  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        statements = await _problem_statement_distribution(
            db, since=since, threshold_tokens=threshold_tokens
        )
        assembled = await input_token_percentiles(db, since=since)

    return {"problem_statements": statements, "assembled_prompts": assembled}


def _format_markdown(report: dict[str, Any]) -> str:
    ps = report["problem_statements"]
    threshold = ps["threshold_tokens"]
    pct = ps["over_threshold_fraction"] * 100
    lines = [
        "# Problem-Statement Size Analysis",
        "",
        f"**Compression THRESHOLD:** {threshold:,} tokens.",
        "",
        "## Problem statements (source: `workspaces`, active only)",
        "",
        "| samples | p50 | p90 | p95 | max | over threshold | % over |",
        "|--:|--:|--:|--:|--:|--:|--:|",
        "| {n} | {p50} | {p90} | {p95} | {mx} | {oc} | {pct:.2f} |".format(
            n=ps["samples"],
            p50=ps["p50_tokens"] if ps["p50_tokens"] is not None else "—",
            p90=ps["p90_tokens"] if ps["p90_tokens"] is not None else "—",
            p95=ps["p95_tokens"] if ps["p95_tokens"] is not None else "—",
            mx=ps["max_tokens"] if ps["max_tokens"] is not None else "—",
            oc=ps["over_threshold_count"],
            pct=pct,
        ),
        "",
        (
            f"**{ps['over_threshold_count']} of {ps['samples']} "
            f"({pct:.2f}%) stored problem statements exceed the {threshold:,}-token "
            "THRESHOLD** — the fraction for which compression would run. A ~0% "
            "reading is expected until large inputs arrive after the cap raise."
        ),
        "",
        "## Assembled prompts (source: `llm_cost_events.input_tokens`)",
        "",
        "| operation | provider | samples | p50 | p90 | p95 | max |",
        "|---|---|--:|--:|--:|--:|--:|",
    ]
    assembled = report["assembled_prompts"]
    for row in assembled:
        lines.append(
            "| {op} | {prov} | {n} | {p50} | {p90} | {p95} | {mx} |".format(
                op=row["operation"],
                prov=row["provider"],
                n=row["samples"],
                p50=row["p50_input_tokens"],
                p90=row["p90_input_tokens"],
                p95=row["p95_input_tokens"],
                mx=row["max_input_tokens"],
            )
        )
    if not assembled:
        lines.append("| _(ledger empty for the window)_ |  |  |  |  |  |  |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Problem-statement size distribution + compression frequency."
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=0,
        help=(
            "Look-back window in days for both sources (default 0 = all time; the "
            "stored-statement census is most useful unbounded)."
        ),
    )
    parser.add_argument(
        "--threshold-tokens",
        type=int,
        default=8000,
        help=(
            "Compression THRESHOLD in tokens (default 8000). C_MAX is still an "
            "open product question (plan §10), so it is a CLI knob here, not "
            "hardcoded."
        ),
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.threshold_tokens <= 0:
        parser.error("--threshold-tokens must be a positive integer")

    since = (
        datetime.now(timezone.utc) - timedelta(days=args.since_days)
        if args.since_days > 0
        else None
    )
    report = asyncio.run(_gather(since, args.threshold_tokens))

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
