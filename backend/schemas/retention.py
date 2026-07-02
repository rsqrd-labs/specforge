from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RetentionPolicyResponse(BaseModel):
    """Static, cacheable data-retention policy metadata (issue #43, plan §5.3).

    Served unauthenticated from ``GET /retention/policy`` so the delete dialog,
    the "Recently deleted" section, and the Settings "Data retention" panel all
    render the live windows from one source of truth instead of hard-coding them.
    ``policy_version`` is the string the delete dialog stamps as
    ``retention_ack_version`` on confirm (proof the user saw the notice).
    """

    policy_version: str
    # Tier-3 workspace trash windows (days).
    trash_days: int
    legacy_archived_days: int
    # Tier-2 content keep-N.
    stage_versions_keep: int
    stage_versions_min_age_days: int
    storyboards_keep: int
    storyboards_min_age_days: int
    # Tier-1 telemetry TTL windows (days) — surfaced for the Settings panel.
    cost_events_days: int
    eval_results_days: int

    model_config = ConfigDict(extra="forbid")
