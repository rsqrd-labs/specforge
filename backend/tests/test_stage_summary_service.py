from __future__ import annotations

from uuid import uuid4

from services.pipeline.stage_summary_service import (
    SUMMARY_SECTIONS,
    content_hash,
    summarize_stage_content,
    summary_cache_key,
)


def test_summary_has_required_sections_and_traceability() -> None:
    summary = summarize_stage_content(
        "plan",
        """
        # Architecture Decision
        FR-001 Users can create projects.
        SEC-002 Prompt injection is rejected.
        POST /projects
        Entity: Project
        email TEXT NOT NULL UNIQUE
        ## Open Questions
        Assumption: single region deployment.
        """,
    )

    for section in SUMMARY_SECTIONS:
        assert f"## {section}" in summary.content
    assert "FR-001" in summary.content
    assert "SEC-002" in summary.content
    assert "POST /projects" in summary.content
    assert "Project" in summary.content


def test_content_hash_changes_when_source_changes() -> None:
    assert content_hash("version one") != content_hash("version two")


def test_summary_cache_key_includes_source_hash() -> None:
    workspace_id = uuid4()
    first = summary_cache_key(workspace_id, "spec", content_hash("one"))
    second = summary_cache_key(workspace_id, "spec", content_hash("two"))

    assert first != second
    assert str(workspace_id) in first
