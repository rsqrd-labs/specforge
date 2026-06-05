from __future__ import annotations

import pytest

from schemas.stage import RefineRequest
from services.llm.output_budget import OUTPUT_TOKEN_BUDGETS, output_budget_for_operation


def test_output_budgets_cover_generation_and_refine_operations() -> None:
    for operation in [
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
        "refine.focused",
        "refine.section",
        "regenerate.full",
        "summary.create",
        "eval.score",
    ]:
        assert output_budget_for_operation(operation) > 0


def test_focused_refine_budget_is_smaller_than_full_regenerate() -> None:
    assert (
        OUTPUT_TOKEN_BUDGETS["refine.focused"] < OUTPUT_TOKEN_BUDGETS["regenerate.full"]
    )
    assert OUTPUT_TOKEN_BUDGETS["refine.focused"] <= 768


def test_unknown_operation_raises() -> None:
    with pytest.raises(ValueError):
        output_budget_for_operation("missing.operation")


def test_refine_request_defaults_to_focused_mode() -> None:
    request = RefineRequest(
        instruction="tighten",
        selection_start=0,
        selection_end=5,
        selected_text="hello",
    )

    assert request.mode == "focused"
