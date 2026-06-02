"""Unit tests for the Phase 21 GitHub living-integration schemas (T-266).

Pure, in-memory Pydantic validation — no DB, no network. Covers the
load-bearing contract edges: export_mode is constrained, requests forbid extra
fields and require an installation target, and response models map cleanly from
ORM attributes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas.github import (
    GitHubExportRequest,
    InstallationList,
    InstallationOption,
    InstallationStatus,
    PushStatusResponse,
    SyncStateResponse,
    TaskSyncState,
    WebhookAck,
)


def test_export_request_accepts_both_valid_modes() -> None:
    for mode in ("files_to_default", "pr_with_tests"):
        req = GitHubExportRequest(
            installation_id=uuid4(),
            repo_name="my-export",
            export_mode=mode,
        )
        assert req.export_mode == mode


def test_export_request_defaults_to_files_to_default() -> None:
    req = GitHubExportRequest(installation_id=uuid4(), repo_name="my-export")
    assert req.export_mode == "files_to_default"
    assert req.visibility == "private"


def test_export_request_rejects_invalid_mode() -> None:
    with pytest.raises(ValidationError):
        GitHubExportRequest(
            installation_id=uuid4(),
            repo_name="my-export",
            export_mode="files_and_pr",  # not a valid mode
        )


def test_export_request_requires_installation_target() -> None:
    with pytest.raises(ValidationError):
        GitHubExportRequest(repo_name="my-export")


def test_export_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GitHubExportRequest(
            installation_id=uuid4(),
            repo_name="my-export",
            access_token="ghs_secretleak",  # extra="forbid" must reject this
        )


@pytest.mark.parametrize("bad_name", ["", "a" * 101, "has space", "../etc", "re@po"])
def test_export_request_rejects_unsafe_repo_names(bad_name: str) -> None:
    with pytest.raises(ValidationError):
        GitHubExportRequest(installation_id=uuid4(), repo_name=bad_name)


def test_webhook_ack_defaults_and_constrains_status() -> None:
    assert WebhookAck().status == "accepted"
    assert WebhookAck(status="skipped").status == "skipped"
    with pytest.raises(ValidationError):
        WebhookAck(status="processed")


def test_installation_status_and_list_construct() -> None:
    status = InstallationStatus(
        connected=True,
        account_login="octo-org",
        account_type="Organization",
        repository_selection="selected",
        username="octocat",
        on_legacy_oauth=True,
    )
    assert status.on_legacy_oauth is True

    option = InstallationOption(
        id=uuid4(),
        installation_id=12345,
        account_login="octo-org",
        account_type="Organization",
        repository_selection="all",
    )
    listing = InstallationList(installations=[option], on_legacy_oauth=False)
    assert len(listing.installations) == 1
    assert listing.installations[0].installation_id == 12345


def test_installation_status_disconnected_is_minimal() -> None:
    status = InstallationStatus(connected=False)
    assert status.connected is False
    assert status.account_login is None
    assert status.on_legacy_oauth is False


def test_push_status_response_maps_from_orm_attributes() -> None:
    class _Row:
        id = uuid4()
        status = "completed"
        export_mode = "pr_with_tests"
        branch_name = "specforge/inc-1"
        pr_number = 7
        repo_full_name = "octo-org/app"
        repo_url = "https://github.com/octo-org/app"
        pushed_at = datetime.now(UTC)

    resp = PushStatusResponse.model_validate(_Row())
    assert resp.push_id == _Row.id
    assert resp.export_mode == "pr_with_tests"
    assert resp.pr_number == 7
    # shipped/total default to 0 when not supplied by the row.
    assert resp.shipped == 0 and resp.total == 0


def test_task_sync_state_aliases_issue_number() -> None:
    class _TaskRow:
        task_ref = "task-deadbeef0001"
        external_issue_number = 42
        state = "done"
        done_via = "pr_merge"
        done_at = datetime.now(UTC)
        synced_at = datetime.now(UTC)

    task = TaskSyncState.model_validate(_TaskRow())
    assert task.issue_number == 42
    assert task.done_via == "pr_merge"

    resp = SyncStateResponse(
        push_id=uuid4(),
        status="completed",
        out_of_sync=True,
        shipped=1,
        total=2,
        tasks=[task],
    )
    assert resp.out_of_sync is True
    assert resp.tasks[0].issue_number == 42
