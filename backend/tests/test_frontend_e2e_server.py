from scripts.run_frontend_e2e_server import _artifact
from services.pipeline.artifact_validator import (
    validate_artifact_completeness,
    validate_sections,
)


def test_deterministic_spec_satisfies_both_workspace_mode_gates() -> None:
    artifact = _artifact("spec")

    for mode in ("standard", "demo_day"):
        validate_sections("spec", artifact, {}, mode)
        validate_artifact_completeness("spec", artifact, {}, mode)


def test_deterministic_artifacts_cover_both_section_contracts() -> None:
    for stage in ("spec", "plan", "harness", "tasks"):
        artifact = _artifact(stage)
        for mode in ("standard", "demo_day"):
            validate_sections(stage, artifact, {}, mode)
