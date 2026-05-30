"""Unit coverage for the Storyboard ORM model (Phase 20 — T-250).

These assertions inspect SQLAlchemy table metadata (no live DB) to lock the
column set, nullability, foreign-key delete semantics, constraints, indexes,
and boolean defaults against the T-250 contract. The live ``alembic upgrade
head`` / ``downgrade -1`` acceptance checks are run separately against Postgres.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from models import Base, Storyboard


def test_storyboard_is_registered_on_metadata() -> None:
    assert Storyboard.__tablename__ == "storyboards"
    assert "storyboards" in Base.metadata.tables


def test_storyboard_has_all_contract_columns() -> None:
    cols = Storyboard.__table__.columns
    expected = {
        "id",
        "workspace_id",
        "user_id",
        "version",
        "status",
        "title",
        "theme",
        "content_json",
        "speaker_notes_md",
        "demo_script_md",
        "technical_appendix_md",
        "source_map_json",
        "source_stage_version_ids",
        "credit_ledger_id",
        "public_share_slug",
        "public_share_enabled",
        "allow_pdf_download",
        "allow_notes_download",
        "allow_appendix_download",
        "allow_source_layer",
        "created_at",
        "updated_at",
    }
    assert expected == set(cols.keys())


def test_jsonb_columns_are_native_jsonb_not_text() -> None:
    cols = Storyboard.__table__.columns
    for name in ("content_json", "source_map_json", "source_stage_version_ids"):
        assert isinstance(cols[name].type, JSONB), f"{name} must be native JSONB"
        assert not cols[name].nullable, f"{name} must be NOT NULL"


def test_required_columns_are_not_nullable() -> None:
    cols = Storyboard.__table__.columns
    for name in (
        "workspace_id",
        "user_id",
        "version",
        "status",
        "title",
        "theme",
        "speaker_notes_md",
        "demo_script_md",
        "technical_appendix_md",
        "public_share_enabled",
        "allow_pdf_download",
        "allow_notes_download",
        "allow_appendix_download",
        "allow_source_layer",
        "created_at",
        "updated_at",
    ):
        assert not cols[name].nullable, f"{name} must be NOT NULL"


def test_nullable_columns() -> None:
    cols = Storyboard.__table__.columns
    for name in ("credit_ledger_id", "public_share_slug"):
        assert cols[name].nullable, f"{name} must be nullable"


def _fk_for(column_name: str):
    cols = Storyboard.__table__.columns
    fks = list(cols[column_name].foreign_keys)
    assert len(fks) == 1, f"{column_name} must have exactly one foreign key"
    return fks[0]


def test_workspace_and_user_fks_cascade_delete() -> None:
    assert _fk_for("workspace_id").column.table.name == "workspaces"
    assert _fk_for("workspace_id").ondelete == "CASCADE"
    assert _fk_for("user_id").column.table.name == "users"
    assert _fk_for("user_id").ondelete == "CASCADE"


def test_credit_ledger_fk_does_not_cascade_or_null() -> None:
    # Directive: deleting a referenced credit_ledger entry is not allowed, so the
    # FK must use NO ACTION (no ondelete) — never SET NULL or CASCADE.
    fk = _fk_for("credit_ledger_id")
    assert fk.column.table.name == "credit_ledger"
    assert fk.ondelete in (None, "NO ACTION")


def test_unique_workspace_version_constraint() -> None:
    uniques = {
        c.name: c
        for c in Storyboard.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert "uq_storyboards_workspace_version" in uniques
    cols = [c.name for c in uniques["uq_storyboards_workspace_version"].columns]
    assert cols == ["workspace_id", "version"]


def test_check_constraints_present() -> None:
    checks = {
        c.name: str(c.sqltext)
        for c in Storyboard.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert "version > 0" in checks.get("ck_storyboards_version", "")
    status_sql = checks.get("ck_storyboards_status", "")
    for status in ("generating", "ready", "failed", "stale"):
        assert status in status_sql
    assert "200" in checks.get("ck_storyboards_title_len", "")


def test_partial_unique_index_on_public_share_slug() -> None:
    idx = {i.name: i for i in Storyboard.__table__.indexes}
    slug_idx = idx["uq_storyboards_public_share_slug"]
    assert slug_idx.unique is True
    assert [c.name for c in slug_idx.columns] == ["public_share_slug"]
    where = slug_idx.dialect_options["postgresql"].get("where")
    assert where is not None, "public slug index must be partial (WHERE not null)"


def test_query_indexes_present() -> None:
    names = {i.name for i in Storyboard.__table__.indexes}
    assert "ix_storyboards_workspace_created_at" in names
    assert "ix_storyboards_user_created_at" in names


def test_boolean_server_defaults() -> None:
    cols = Storyboard.__table__.columns
    # allow_pdf_download defaults TRUE; every other boolean defaults FALSE.
    assert "true" in str(cols["allow_pdf_download"].server_default.arg).lower()
    for name in (
        "public_share_enabled",
        "allow_notes_download",
        "allow_appendix_download",
        "allow_source_layer",
    ):
        assert "false" in str(cols[name].server_default.arg).lower()
