"""Public data-retention policy metadata (issue #43, plan §5.3).

A single read-only, unauthenticated endpoint the frontend reads so the delete
dialog, the "Recently deleted" section, and the Settings "Data retention" panel
render the live windows (and the ack version to stamp) from one source of truth
instead of hard-coding them. No user data is exposed — only static config-derived
policy numbers — so it needs no auth and is safely cacheable.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from config import settings
from schemas.retention import RetentionPolicyResponse
from services.retention import RETENTION_POLICY_VERSION

router = APIRouter(prefix="/retention", tags=["retention"])

# Cacheable for an hour: the policy only changes on a redeploy (the windows are
# config), so a short-to-medium cache keeps this off the hot path without ever
# serving a stale window for long.
_POLICY_CACHE_CONTROL = "public, max-age=3600"


@router.get("/policy", response_model=RetentionPolicyResponse)
async def get_retention_policy(response: Response) -> RetentionPolicyResponse:
    """Return the live retention windows + the current policy version."""
    response.headers["Cache-Control"] = _POLICY_CACHE_CONTROL
    return RetentionPolicyResponse(
        policy_version=RETENTION_POLICY_VERSION,
        trash_days=settings.retention_trash_days,
        legacy_archived_days=settings.retention_legacy_archived_days,
        stage_versions_keep=settings.retention_stage_versions_keep,
        stage_versions_min_age_days=settings.retention_stage_versions_min_age_days,
        storyboards_keep=settings.retention_storyboards_keep,
        storyboards_min_age_days=settings.retention_storyboards_min_age_days,
        cost_events_days=settings.retention_cost_events_days,
        eval_results_days=settings.retention_eval_results_days,
    )
