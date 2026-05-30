from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from prometheus_client import REGISTRY

from models import Stage, StageVersion, Storyboard, Workspace
from prompts.storyboard import StoryboardPayloadError
from services import observability
from services.pipeline import (
    storyboard_public_service,
    storyboard_renderer,
    storyboard_service,
    storyboard_source,
)

_USER_ID = uuid4()
_WORKSPACE_ID = uuid4()
_STORYBOARD_ID = uuid4()


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return float(REGISTRY.get_sample_value(name, labels or {}) or 0.0)


def _storyboard(*, credit_ledger_id: UUID | None = None) -> Storyboard:
    now = datetime.now(UTC)
    return Storyboard(
        id=_STORYBOARD_ID,
        workspace_id=_WORKSPACE_ID,
        user_id=_USER_ID,
        version=3,
        status="ready",
        title="Launch Keynote",
        theme="indica",
        content_json={},
        speaker_notes_md="private notes",
        demo_script_md="private demo",
        technical_appendix_md="private appendix",
        source_map_json={},
        source_stage_version_ids={"spec": str(uuid4())},
        credit_ledger_id=credit_ledger_id,
        public_share_enabled=True,
        public_share_slug="sharetoken",
        allow_pdf_download=True,
        allow_notes_download=False,
        allow_appendix_download=False,
        allow_source_layer=False,
        created_at=now,
        updated_at=now,
    )


class _FakeLogger:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.rows.append(("info", event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.rows.append(("warning", event, fields))


def test_storyboard_metric_helpers_increment_bounded_series() -> None:
    started_before = _sample(
        "specforge_storyboard_generation_started_total", {"action": "generate"}
    )
    credits_before = _sample(
        "specforge_storyboard_credits_deducted_total",
        {"action": "regenerate_section"},
    )
    refunded_before = _sample(
        "specforge_storyboard_credits_refunded_total",
        {"action": "regenerate_section", "reason": "generation_failed"},
    )
    failed_before = _sample(
        "specforge_storyboard_generation_failed_total",
        {"action": "regenerate", "error_type": "timeout"},
    )
    public_before = _sample("specforge_storyboard_public_view_total")
    download_before = _sample(
        "specforge_storyboard_download_total",
        {"kind": "notes-md", "public": "true"},
    )
    missing_before = _sample(
        "specforge_storyboard_source_missing_total",
        {"source": "plan", "section": "stride"},
    )

    observability.record_storyboard_generation_started("generate")
    observability.record_storyboard_credits_deducted("regenerate_section", 5)
    observability.record_storyboard_credits_refunded(
        "regenerate_section", "generation_failed", 5
    )
    observability.record_storyboard_generation_failed("regenerate", "timeout")
    observability.record_storyboard_public_view()
    observability.record_storyboard_download("notes", public=True)
    observability.record_storyboard_source_missing("plan", "PLAN:stride")

    assert _sample(
        "specforge_storyboard_generation_started_total", {"action": "generate"}
    ) == pytest.approx(started_before + 1)
    assert _sample(
        "specforge_storyboard_credits_deducted_total",
        {"action": "regenerate_section"},
    ) == pytest.approx(credits_before + 5)
    assert _sample(
        "specforge_storyboard_credits_refunded_total",
        {"action": "regenerate_section", "reason": "generation_failed"},
    ) == pytest.approx(refunded_before + 5)
    assert _sample(
        "specforge_storyboard_generation_failed_total",
        {"action": "regenerate", "error_type": "timeout"},
    ) == pytest.approx(failed_before + 1)
    assert _sample("specforge_storyboard_public_view_total") == pytest.approx(
        public_before + 1
    )
    assert _sample(
        "specforge_storyboard_download_total",
        {"kind": "notes-md", "public": "true"},
    ) == pytest.approx(download_before + 1)
    assert _sample(
        "specforge_storyboard_source_missing_total",
        {"source": "plan", "section": "stride"},
    ) == pytest.approx(missing_before + 1)


def test_storyboard_public_view_and_download_events_are_content_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sb = _storyboard()
    public_logger = _FakeLogger()
    download_logger = _FakeLogger()
    public_metric_calls: list[bool] = []
    download_metric_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(storyboard_public_service, "logger", public_logger)
    monkeypatch.setattr(
        storyboard_public_service,
        "record_storyboard_public_view",
        lambda: public_metric_calls.append(True),
    )
    monkeypatch.setattr(storyboard_renderer, "logger", download_logger)
    monkeypatch.setattr(
        storyboard_renderer,
        "record_storyboard_download",
        lambda kind, *, public: download_metric_calls.append((kind, public))
        or "notes-md",
    )

    storyboard_public_service.record_public_view(sb)
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        user_id=sb.user_id,
        version=sb.version,
        kind="notes-md",
        public=False,
        status=sb.status,
    )

    assert public_metric_calls == [True]
    assert download_metric_calls == [("notes-md", False)]
    assert public_logger.rows[0][1] == "storyboard.public_viewed"
    assert "user_id" not in public_logger.rows[0][2]
    assert download_logger.rows[0][1] == "storyboard.downloaded"
    assert download_logger.rows[0][2]["user_id"] == str(sb.user_id)

    logged = repr(public_logger.rows + download_logger.rows)
    for forbidden in [
        "speaker_notes_md",
        "technical_appendix_md",
        "demo_script_md",
        "source_excerpt",
        "content_json",
        "private notes",
        "private demo",
        "private appendix",
    ]:
        assert forbidden not in logged


def test_storyboard_generation_event_fields_and_error_types_are_bounded() -> None:
    ledger_id = uuid4()
    sb = _storyboard(credit_ledger_id=ledger_id)

    fields = storyboard_service._storyboard_event_fields(
        sb,
        user_id=sb.user_id,
        action="generate",
        status="ready",
        include_credit_ledger=True,
    )

    assert fields == {
        "storyboard_id": str(sb.id),
        "workspace_id": str(sb.workspace_id),
        "version": sb.version,
        "action": "generate",
        "status": "ready",
        "user_id": str(sb.user_id),
        "credit_ledger_id": str(ledger_id),
    }
    assert storyboard_service._payload_error_type(
        StoryboardPayloadError("parse", "llm completion timed out")
    ) == "timeout"
    assert storyboard_service._payload_error_type(
        StoryboardPayloadError("parse", "llm provider error")
    ) == "provider"
    assert storyboard_service._payload_error_type(
        StoryboardPayloadError("schema", "missing section")
    ) == "payload_schema"


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> "_Result":
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(
        self,
        workspace: Workspace,
        stages: list[Stage],
        versions: list[StageVersion],
    ) -> None:
        self._workspace = workspace
        self._stages = stages
        self._versions = versions

    async def execute(self, statement: Any) -> _Result:
        entity = statement.column_descriptions[0]["entity"]
        if entity is Workspace:
            return _Result([self._workspace])
        if entity is Stage:
            return _Result(self._stages)
        if entity is StageVersion:
            return _Result(self._versions)
        raise AssertionError(f"unexpected query entity: {entity}")


def _stage(stage_type: str) -> Stage:
    return Stage(
        id=uuid4(),
        workspace_id=_WORKSPACE_ID,
        type=stage_type,
        content="draft content",
        status="finalised",
        current_version=1,
    )


def _version(stage: Stage, content: str) -> StageVersion:
    return StageVersion(
        id=uuid4(),
        stage_id=stage.id,
        version=1,
        content=content,
        created_by="ai",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_source_builder_emits_missing_section_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages = {name: _stage(name) for name in ("spec", "plan", "harness", "tasks")}
    workspace = Workspace(
        id=_WORKSPACE_ID,
        user_id=_USER_ID,
        name="SpecForge",
        problem_statement="Build a spec generator.",
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    versions = [
        _version(stages["spec"], "# Spec\n\n## Overview\nSpec overview.\n"),
        _version(stages["plan"], "# Plan\n\n## Architecture\nArchitecture only.\n"),
        _version(stages["harness"], "# Harness\n\n## Coverage\nCovered.\n"),
        _version(stages["tasks"], "# Tasks\n\n## Must-have\n- Ship auth.\n"),
    ]
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        storyboard_source,
        "record_storyboard_source_missing",
        lambda source, section: calls.append((source, section)),
    )

    package = await storyboard_source.build_storyboard_source(
        _FakeDB(workspace, list(stages.values()), versions),
        _WORKSPACE_ID,
        _USER_ID,
    )

    assert package.missing_source_sections
    assert ("plan", "PLAN:stride") in calls
    assert ("plan", "PLAN:fmea") in calls
