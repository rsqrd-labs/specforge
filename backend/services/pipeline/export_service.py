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
from services.pipeline import agent_manual_service, demo_day_verdict

logger = logging.getLogger(__name__)

_STAGE_FILES = {
    "spec": "SPEC.md",
    "plan": "PLAN.md",
    "tasks": "TASKS.md",
}
_HARNESS_FALLBACK = "harness/HARNESS.md"
_FILE_HEADING_RE = re.compile(r"^#{2,3}\s+File:\s+(?P<filename>.+)$")
_FENCE_OPEN_RE = re.compile(r"^(?P<fence>`{3,})[a-zA-Z0-9_-]*$")
_FENCE_FILE_RE = re.compile(r"^(?P<fence>`{3,})[a-zA-Z0-9_-]+\s+(?P<filename>.+?)\s*$")
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
        normalized = normalized[len("harness/") :]
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


def _read_fenced_block(
    lines: list[str],
    fence_index: int,
    fence: str,
) -> tuple[str, int] | None:
    content_start = fence_index + 1
    k = content_start
    while k < len(lines) and lines[k].rstrip() != fence:
        k += 1
    if k >= len(lines):
        return None
    return "\n".join(lines[content_start:k]) + "\n", k


def _parse_labelled_harness_files(harness_content: str) -> tuple[dict[str, str], bool]:
    """State-machine parser: finds ## / ### File: headings and captures the
    immediately-following fenced code block as the file's content.

    Uses the fence string itself (backtick count) as the block delimiter so
    files whose content contains ``` (e.g. README.md) are handled correctly.
    """
    files: dict[str, str] = {}
    found_labelled_block = False
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
                    fenced_block = _read_fenced_block(lines, j, fence)
                    if fenced_block is not None:
                        content, k = fenced_block
                        found_labelled_block = True
                        path = _safe_harness_path(filename)
                        if path:
                            files[path] = content
                        i = k + 1
                        continue
        fence_file_match = _FENCE_FILE_RE.match(lines[i].rstrip())
        if fence_file_match:
            fence = fence_file_match.group("fence")
            fenced_block = _read_fenced_block(lines, i, fence)
            if fenced_block is not None:
                content, k = fenced_block
                found_labelled_block = True
                path = _safe_harness_path(fence_file_match.group("filename"))
                if path:
                    files[path] = content
                i = k + 1
                continue
        i += 1
    return files, found_labelled_block


def parse_harness_files(harness_content: str) -> dict[str, str]:
    files, found_labelled_block = _parse_labelled_harness_files(harness_content)
    if files or found_labelled_block:
        return files
    return {_HARNESS_FALLBACK: harness_content}


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

        # Demo Day mode (plan §8): add the agent operating manual so the bundle is
        # ready to hand to the user's coding agent. Standard exports are
        # byte-identical (this whole block is skipped).
        if getattr(workspace, "mode", "standard") == "demo_day":
            manual_filename, manual_body = agent_manual_service.build_agent_manual(
                workspace, stages["plan"].content or ""
            )
            zf.writestr(manual_filename, manual_body)
            # CONSTRUCTION_REPORT.md (plan §7.3/§8.2): refresh the verdict if a
            # stage was refined after it was computed (zero-LLM, cheap), then
            # render it. ensure_fresh_verdict is fail-open, so a hiccup just ships
            # the last-known verdict (or omits the report) rather than failing the
            # download.
            verdict = await demo_day_verdict.ensure_fresh_verdict(db, workspace, stages)
            if verdict:
                report = agent_manual_service.build_construction_report(verdict)
                zf.writestr(agent_manual_service.CONSTRUCTION_REPORT_FILENAME, report)

    return buf.getvalue()
