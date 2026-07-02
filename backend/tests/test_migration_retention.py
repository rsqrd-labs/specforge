"""Contract tests for the data-retention migrations (issue #43).

The unit suite builds its schema with ``Base.metadata.create_all`` and never
drives Alembic against Postgres, so — mirroring
``test_migration_0031_partial_index.py`` — these pin the cheap-but-load-bearing
facts statically:

  - 0032 adds a plain btree on ``eval_results(created_at)`` for the Tier-1 TTL
    purge, and is additive (the 0012 composite index is not dropped).
  - 0033 adds ``archived_at`` + ``retention_ack_version`` to ``workspaces``,
    **backfills existing archived rows to now()** (updated_at is unreliable), and
    builds a Postgres-only partial index matching the Tier-3 purge predicate.
"""

from __future__ import annotations

import importlib
from pathlib import Path

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(module_name: str):
    return importlib.import_module(f"migrations.versions.{module_name}")


def test_0032_adds_plain_created_at_index_additively() -> None:
    module = _load("0032_eval_results_created_at_index")
    assert module.revision == "0032"
    assert module.down_revision == "0031"
    source = (_VERSIONS_DIR / "0032_eval_results_created_at_index.py").read_text()
    assert "ix_eval_results_created_at" in source
    assert '"eval_results"' in source
    assert '["created_at"]' in source
    # Additive: the downgrade drops ONLY the new index — the 0012 composite index
    # (stage_version_id, created_at DESC) is never dropped here, so it still serves
    # the per-version eval poll.
    assert "op.drop_index(_INDEX_NAME" in source
    assert 'drop_index("ix_eval_results_stage_version_created_at"' not in source


def test_0033_columns_backfill_and_partial_index() -> None:
    module = _load("0033_workspace_trash")
    assert module.revision == "0033"
    assert module.down_revision == "0032"
    source = (_VERSIONS_DIR / "0033_workspace_trash.py").read_text()
    # The two trash columns.
    assert '"archived_at"' in source
    assert '"retention_ack_version"' in source
    # Backfill existing archived rows to deploy time (updated_at is unreliable).
    assert "UPDATE workspaces SET archived_at = now()" in source
    assert "status = 'archived' AND archived_at IS NULL" in source
    # Partial index matching the Tier-3 purge predicate, Postgres-only.
    assert "ix_workspaces_archived_at" in source
    assert "postgresql_where" in source
    assert "status = 'archived'" in source
    # Non-postgres backends must skip the partial index cleanly (both directions).
    assert source.count('== "postgresql"') == 2


def test_0033_upgrade_backfills_and_skips_index_off_postgres(monkeypatch) -> None:
    """Off Postgres the columns + backfill still run; the partial index is skipped."""
    module = _load("0033_workspace_trash")
    calls: list[str] = []

    class _SqliteDialect:
        name = "sqlite"

    class _SqliteBind:
        dialect = _SqliteDialect()

    monkeypatch.setattr(module.op, "get_bind", lambda: _SqliteBind())
    monkeypatch.setattr(
        module.op, "add_column", lambda *a, **k: calls.append("add_column")
    )
    monkeypatch.setattr(module.op, "execute", lambda *a, **k: calls.append("execute"))

    def _explode_index(*a, **kw):  # pragma: no cover - failure path only
        raise AssertionError("create_index must not run off postgres")

    monkeypatch.setattr(module.op, "create_index", _explode_index, raising=False)

    module.upgrade()
    # Both columns added and the backfill executed; the partial index was skipped.
    assert calls.count("add_column") == 2
    assert "execute" in calls
