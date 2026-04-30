from __future__ import annotations

import io
import logging
import re
import zipfile
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Stage, Workspace

logger = logging.getLogger(__name__)

_STAGE_FILES = {
    "spec": "SPEC.md",
    "plan": "PLAN.md",
    "tasks": "TASKS.md",
}
_HARNESS_FALLBACK = "harness/HARNESS.md"
_CODE_FENCE_RE = re.compile(
    r"```(?:\w+)?\s+(?P<filename>[^\n]+)\n(?P<content>.*?)```",
    re.DOTALL,
)


class ExportNotReadyError(Exception):
    pass


def _parse_harness_files(harness_content: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in _CODE_FENCE_RE.finditer(harness_content):
        filename = match.group("filename").strip()
        content = match.group("content")
        if filename:
            files[f"harness/{filename}"] = content
    return files


async def build_export(workspace_id: UUID, user_id: UUID, db: AsyncSession) -> bytes:
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = ws_result.scalar_one_or_none()
    if workspace is None or workspace.user_id != user_id:
        raise ExportNotReadyError("Workspace not found")

    stages_result = await db.execute(
        select(Stage).where(Stage.workspace_id == workspace_id)
    )
    stages = {s.type: s for s in stages_result.scalars()}

    for stage_type in ("spec", "plan", "harness", "tasks"):
        stage = stages.get(stage_type)
        if stage is None or stage.status != "finalised":
            raise ExportNotReadyError(
                f"Stage {stage_type!r} is not finalised — export unavailable"
            )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for stage_type, filename in _STAGE_FILES.items():
            zf.writestr(filename, stages[stage_type].content or "")

        harness_content = stages["harness"].content or ""
        harness_files = _parse_harness_files(harness_content)
        if harness_files:
            for path, content in harness_files.items():
                zf.writestr(path, content)
        else:
            logger.warning(
                "harness parse yielded no files for workspace_id=%s, using fallback",
                workspace_id,
            )
            zf.writestr(_HARNESS_FALLBACK, harness_content)

    return buf.getvalue()
