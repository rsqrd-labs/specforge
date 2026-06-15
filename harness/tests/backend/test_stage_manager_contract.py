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


def test_progress_heartbeat_exposes_additive_phase_field() -> None:
    """Issue #21 Phase 2c: the SSE progress heartbeat carries an additive
    ``phase`` field alongside the existing ``state``/``elapsed_seconds`` so the
    loading UI reflects the real pipeline phase.  The field must be additive (the
    legacy keys stay) and cover the four declared phases."""
    module = import_backend("services.pipeline.stage_manager")

    assert module.PIPELINE_PHASE_STREAMING == "streaming"
    assert module.PIPELINE_PHASE_QUALITY_GATE == "quality_gate"
    assert module.PIPELINE_PHASE_CRITIC == "critic"
    assert module.PIPELINE_PHASE_PERSISTING == "persisting"

    source = read_backend_file("services", "pipeline", "stage_manager.py")
    # The heartbeat payload keeps the legacy contract and adds `phase`.
    assert '"state": "generating"' in source
    assert '"elapsed_seconds"' in source
    assert '"phase": phase_tracker.phase' in source
