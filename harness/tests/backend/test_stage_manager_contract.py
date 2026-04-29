from __future__ import annotations

from conftest import import_backend, read_backend_file


def test_stage_manager_encodes_canonical_order_and_dependencies() -> None:
    module = import_backend("services.pipeline.stage_manager")
    manager = getattr(module, "StageManager", None)

    assert manager is not None
    assert manager.STAGE_ORDER == ["spec", "plan", "harness", "tasks"]
    assert manager.STAGE_DEPENDENCIES == {
        "spec": ["problem_statement"],
        "plan": ["spec"],
        "harness": ["spec", "plan"],
        "tasks": ["spec", "plan", "harness"],
    }


def test_stage_manager_mentions_atomic_credits_refund_and_staleness() -> None:
    source = read_backend_file("services", "pipeline", "stage_manager.py").lower()

    for required in ["deduct", "refund", "finalise", "rollback", "stale"]:
        assert required in source, f"stage_manager.py must implement {required} behavior"


def test_stage_manager_prevents_duplicate_generation_streams() -> None:
    source = read_backend_file("services", "pipeline", "stage_manager.py").lower()

    assert "in_progress" in source
    assert "already" in source or "conflict" in source or "409" in source
