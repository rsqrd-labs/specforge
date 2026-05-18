from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import PurePosixPath
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
_FILE_HEADING_RE = re.compile(r"^#{2,3}\s+File:\s+(?P<filename>.+)$")
_FENCE_OPEN_RE = re.compile(r"^(?P<fence>`{3,})[a-zA-Z0-9]*$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class ExportNotReadyError(Exception):
    pass


def _safe_harness_path(filename: str) -> str | None:
    normalized = filename.strip().replace("\\", "/")
    if not normalized:
        return None
    if any(ord(char) < 32 for char in normalized):
        return None

    # Strip a leading "harness/" prefix the LLM includes in headings — we
    # always re-add it below via PurePosixPath("harness", path).
    if normalized.startswith("harness/"):
        normalized = normalized[len("harness/"):]
    if not normalized:
        return None

    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        return None
    if not path.parts or any(":" in part for part in path.parts):
        return None
    for part in path.parts:
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            return None

    safe_path = PurePosixPath("harness", path)
    if len(safe_path.parts) <= 1:
        return None
    return safe_path.as_posix()


def _parse_labelled_harness_files(harness_content: str) -> dict[str, str]:
    """State-machine parser: finds ## / ### File: headings and captures the
    immediately-following fenced code block as the file's content.

    Uses the fence string itself (backtick count) as the block delimiter so
    files whose content contains ``` (e.g. README.md) are handled correctly.
    """
    files: dict[str, str] = {}
    lines = harness_content.split("\n")
    i = 0
    while i < len(lines):
        heading_match = _FILE_HEADING_RE.match(lines[i])
        if heading_match:
            filename = heading_match.group("filename").strip()
            # Skip blank lines between heading and fence opener
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                fence_match = _FENCE_OPEN_RE.match(lines[j].rstrip())
                if fence_match:
                    fence = fence_match.group("fence")  # e.g. "```"
                    content_start = j + 1
                    k = content_start
                    while k < len(lines) and lines[k].rstrip() != fence:
                        k += 1
                    if k < len(lines):  # found matching closing fence
                        content = "\n".join(lines[content_start:k]) + "\n"
                        path = _safe_harness_path(filename)
                        if path:
                            files[path] = content
                        i = k + 1
                        continue
        i += 1
    return files


def parse_harness_files(harness_content: str) -> dict[str, str]:
    files = _parse_labelled_harness_files(harness_content)
    return files or {_HARNESS_FALLBACK: harness_content}


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
        harness_files = parse_harness_files(harness_content)
        if harness_files.keys() == {_HARNESS_FALLBACK}:
            logger.warning(
                "harness parse yielded no files for workspace_id=%s, using fallback",
                workspace_id,
            )

        for path, content in harness_files.items():
            zf.writestr(path, content)

    return buf.getvalue()
