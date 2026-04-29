from __future__ import annotations

from sqlalchemy import inspect

from conftest import import_backend


EXPECTED_COLUMNS = {
    "User": {"id", "email", "google_id", "name", "avatar_url", "created_at"},
    "Workspace": {
        "id",
        "user_id",
        "name",
        "problem_statement",
        "provider",
        "model",
        "status",
        "created_at",
        "updated_at",
    },
    "Stage": {
        "id",
        "workspace_id",
        "type",
        "content",
        "status",
        "current_version",
        "finalised_at",
        "review_gate_acknowledged",
        "created_at",
        "updated_at",
    },
    "StageVersion": {"id", "stage_id", "version", "content", "created_by", "created_at"},
    "CreditLedger": {"id", "user_id", "amount", "reason", "metadata", "created_at"},
    "EvalResult": {
        "id",
        "stage_version_id",
        "stage_type",
        "overall_score",
        "completeness",
        "clarity",
        "coverage_percent",
        "uncovered_reqs",
        "tasks_without_ref",
        "flagged",
        "created_at",
    },
}


def test_sqlalchemy_models_match_spec_fields() -> None:
    models = import_backend("models")

    for model_name, expected_columns in EXPECTED_COLUMNS.items():
        model = getattr(models, model_name, None)
        assert model is not None, f"models.__init__ must export {model_name}"
        actual_columns = {column.key for column in inspect(model).columns}
        assert expected_columns.issubset(actual_columns), (
            f"{model_name} missing columns: {sorted(expected_columns - actual_columns)}"
        )


def test_stage_enums_are_restricted_to_spec_values() -> None:
    models = import_backend("models")
    stage_table = models.Stage.__table__
    constraints = " ".join(
        str(constraint.sqltext)
        for constraint in stage_table.constraints
        if hasattr(constraint, "sqltext")
    )

    for value in ["spec", "plan", "harness", "tasks"]:
        assert value in constraints
    for value in ["locked", "draft", "in_progress", "finalised", "stale"]:
        assert value in constraints
