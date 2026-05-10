from __future__ import annotations

OUTPUT_TOKEN_BUDGETS: dict[str, int] = {
    "spec.generate": 8192,
    "plan.generate": 8192,
    "harness.generate": 8192,
    "tasks.generate": 6144,
    "refine.focused": 2048,
    "refine.section": 4096,
    "regenerate.full": 8192,
    "summary.create": 2048,
    "eval.score": 1024,
}


def output_budget_for_operation(operation: str) -> int:
    try:
        return OUTPUT_TOKEN_BUDGETS[operation]
    except KeyError as exc:
        raise ValueError(f"Unknown output budget operation: {operation!r}") from exc
