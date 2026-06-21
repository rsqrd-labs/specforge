"""Raise the workspace problem-statement ceiling 10K -> 50K chars.

Phase A of the problem-statement compression plan
(docs/PROBLEM_STATEMENT_COMPRESSION_PLAN.md §2): the product must *accept* a
large pasted PRD / requirements doc before it can compress it down to a per-call
budget. This relaxes the storage ceiling; the >=50 floor is unchanged.

50000 is the outer DoS/storage ceiling (PROBLEM_STATEMENT_MAX_CHARS in
services/security/problem_statement_gate.py — the semantic authority these
literals mirror). It is far below the 1MB request-body limit, so no other
ingestion guard is affected. Existing rows are all <=10K and so remain valid
under the relaxed constraint; no data migration is needed.

Postgres cannot alter a CHECK predicate in place, so this drops and recreates
the same-named constraint.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_workspaces_problem_statement_len", "workspaces", type_="check"
    )
    op.create_check_constraint(
        "ck_workspaces_problem_statement_len",
        "workspaces",
        "char_length(problem_statement) BETWEEN 50 AND 50000",
    )


def downgrade() -> None:
    # The old 10K ceiling cannot be re-applied while any stored statement exceeds
    # it. This downgrade deliberately does NOT truncate user data: it fails loudly
    # if a >10K row exists, so the operator makes an explicit decision rather than
    # silently destroying a problem statement.
    op.drop_constraint(
        "ck_workspaces_problem_statement_len", "workspaces", type_="check"
    )
    op.create_check_constraint(
        "ck_workspaces_problem_statement_len",
        "workspaces",
        "char_length(problem_statement) BETWEEN 50 AND 10000",
    )
