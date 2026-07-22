"""Add cache_write_input_tokens to llm_cost_events (issue #82).

Anthropic prompt-cache writes are premium-priced (5m TTL 1.25x, 1h TTL 2x base
input) while only reads earn the cached-input discount, so write tokens get
their own column instead of being folded into cached_input_tokens. Additive and
nullable; historical rows stay reconcilable from the raw provider usage kept in
Langfuse metadata.

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_cost_events",
        sa.Column("cache_write_input_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_cost_events", "cache_write_input_tokens")
