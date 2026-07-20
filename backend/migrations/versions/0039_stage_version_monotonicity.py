"""Enforce one immutable row per logical stage version.

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-20

Older rollback behavior rewound ``stages.current_version``. A subsequent edit
could therefore reuse a version number already present in ``stage_versions``.
Before adding the uniqueness constraint, deterministically renumber histories
that already contain duplicates, then append the current stage bytes as a new
head for any still-rewound or inconsistent stage.

Construction verdicts for affected workspaces are cleared: those JSON documents
embed stage-version numbers and must be recomputed rather than silently referring
to the repaired history.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL temporary tables keep the mapping stable across the data repair
    # statements and disappear automatically at transaction end. ``created_at,
    # id`` gives a total, deterministic ordering even for rows created in the
    # same transaction.
    op.execute("""
        CREATE TEMPORARY TABLE stage_version_repair_0039
        ON COMMIT DROP AS
        WITH affected AS (
            SELECT stage_id
            FROM stage_versions
            GROUP BY stage_id, version
            HAVING count(*) > 1
        )
        SELECT
            sv.id,
            sv.stage_id,
            sv.version AS old_version,
            row_number() OVER (
                PARTITION BY sv.stage_id
                ORDER BY sv.created_at, sv.id
            )::integer AS new_version
        FROM stage_versions AS sv
        JOIN (SELECT DISTINCT stage_id FROM affected) AS a
          ON a.stage_id = sv.stage_id
        """)
    op.execute("""
        CREATE TEMPORARY TABLE stage_current_repair_0039
        ON COMMIT DROP AS
        WITH matching_current AS (
            SELECT DISTINCT ON (s.id)
                s.id AS stage_id,
                r.new_version
            FROM stages AS s
            JOIN stage_version_repair_0039 AS r
              ON r.stage_id = s.id
            JOIN stage_versions AS sv
              ON sv.id = r.id
            WHERE r.old_version = s.current_version
              AND sv.content IS NOT DISTINCT FROM s.content
            ORDER BY s.id, sv.created_at DESC, sv.id DESC
        ),
        latest AS (
            SELECT stage_id, max(new_version) AS new_version
            FROM stage_version_repair_0039
            GROUP BY stage_id
        )
        SELECT
            s.id AS stage_id,
            s.current_version AS old_current_version,
            coalesce(mc.new_version, latest.new_version)::integer AS new_current_version
        FROM stages AS s
        JOIN latest ON latest.stage_id = s.id
        LEFT JOIN matching_current AS mc ON mc.stage_id = s.id
        """)

    # Use a negative intermediate namespace. It makes the repair safe even if an
    # operator has already installed an equivalent uniqueness index manually.
    op.execute("""
        UPDATE stage_versions AS sv
        SET version = -r.new_version
        FROM stage_version_repair_0039 AS r
        WHERE sv.id = r.id
        """)
    op.execute("""
        UPDATE stage_versions AS sv
        SET version = r.new_version
        FROM stage_version_repair_0039 AS r
        WHERE sv.id = r.id
        """)
    op.execute("""
        UPDATE stages AS s
        SET
            current_version = r.new_current_version,
            quality_gate_version = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN r.new_current_version
                ELSE NULL
            END,
            quality_gate_status = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_status
                ELSE 'clear'
            END,
            quality_gate_kind = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_kind
                ELSE NULL
            END,
            quality_gate_payload = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_payload
                ELSE NULL
            END,
            quality_gate_failed_at = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_failed_at
                ELSE NULL
            END
        FROM stage_current_repair_0039 AS r
        WHERE s.id = r.stage_id
        """)

    # A stage may have been rolled back but not edited yet, so its history has no
    # duplicate even though ``current_version`` points behind the immutable head.
    # It is just as dangerous: the next edit would reuse an existing number. After
    # duplicate repair, append the bytes currently presented to the user as a new
    # head for every rewound/inconsistent row. Preserve research provenance from
    # the newest identical historical artifact when one exists.
    op.execute("""
        CREATE TEMPORARY TABLE stage_head_append_0039
        ON COMMIT DROP AS
        WITH maxima AS (
            SELECT stage_id, max(version) AS max_version
            FROM stage_versions
            GROUP BY stage_id
        )
        SELECT
            s.id AS stage_id,
            s.workspace_id,
            s.current_version AS old_current_version,
            (
                greatest(coalesce(m.max_version, 0), s.current_version) + 1
            )::integer AS new_current_version,
            s.content,
            source.research_context,
            source.research_sources
        FROM stages AS s
        LEFT JOIN maxima AS m ON m.stage_id = s.id
        LEFT JOIN LATERAL (
            SELECT sv.research_context, sv.research_sources
            FROM stage_versions AS sv
            WHERE sv.stage_id = s.id
              AND sv.content IS NOT DISTINCT FROM s.content
            ORDER BY
                (sv.version = s.current_version) DESC,
                sv.created_at DESC,
                sv.id DESC
            LIMIT 1
        ) AS source ON true
        WHERE s.content IS NOT NULL
          AND (
              s.current_version <> coalesce(m.max_version, 0)
              OR NOT EXISTS (
                  SELECT 1
                  FROM stage_versions AS current_sv
                  WHERE current_sv.stage_id = s.id
                    AND current_sv.version = s.current_version
                    AND current_sv.content IS NOT DISTINCT FROM s.content
              )
          )
        """)
    op.execute("""
        INSERT INTO stage_versions (
            stage_id,
            version,
            content,
            created_by,
            research_context,
            research_sources
        )
        SELECT
            stage_id,
            new_current_version,
            content,
            'user',
            research_context,
            research_sources
        FROM stage_head_append_0039
        """)
    op.execute("""
        UPDATE stages AS s
        SET
            current_version = r.new_current_version,
            quality_gate_version = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN r.new_current_version
                ELSE NULL
            END,
            quality_gate_status = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_status
                ELSE 'clear'
            END,
            quality_gate_kind = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_kind
                ELSE NULL
            END,
            quality_gate_payload = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_payload
                ELSE NULL
            END,
            quality_gate_failed_at = CASE
                WHEN s.quality_gate_version = r.old_current_version
                    THEN s.quality_gate_failed_at
                ELSE NULL
            END
        FROM stage_head_append_0039 AS r
        WHERE s.id = r.stage_id
        """)
    op.execute("""
        UPDATE workspaces AS w
        SET construction_verdict = NULL
        WHERE construction_verdict IS NOT NULL
          AND (
              EXISTS (
                  SELECT 1
                  FROM stages AS s
                  JOIN stage_current_repair_0039 AS r ON r.stage_id = s.id
                  WHERE s.workspace_id = w.id
              )
              OR EXISTS (
                  SELECT 1
                  FROM stage_head_append_0039 AS r
                  WHERE r.workspace_id = w.id
              )
          )
        """)

    op.create_unique_constraint(
        "uq_stage_versions_stage_id_version",
        "stage_versions",
        ["stage_id", "version"],
    )


def downgrade() -> None:
    # Renumbering is intentionally not reversed: doing so would recreate the
    # ambiguous duplicate history this migration repairs.
    op.drop_constraint(
        "uq_stage_versions_stage_id_version",
        "stage_versions",
        type_="unique",
    )
