"""Repo-level agent context file builder — non-clobbering (Phase 21 — T-277).

Generates ``AGENTS.md`` (the agent-native standard; the same body also serves
``CLAUDE.md``) from the four finalised stages so a coding agent dropped into the
repo has the spec, the architecture, how the harness runs, and the task list
without fetching anything else.

**Never clobber.** The repo may already carry a hand-written ``AGENTS.md``. This
module writes only inside a delimited *managed block*::

    <!-- specforge:start -->
    ...generated content...
    <!-- specforge:end -->

Any pre-existing user content outside the markers is preserved byte-for-byte. A
regenerate replaces only the managed block; a file with no markers gets the
block appended (existing content kept); a malformed half-marker fails safe by
appending rather than eating the rest of the file. The generated block is
deterministic (no timestamps, no set ordering), so re-running against identical
stages produces byte-identical output — an idempotent sync that never emits a
spurious commit.

Security: the stage-derived content folded into the managed block is sanitised
with the same policy as public share / PDF. The managed markers are added
*after* sanitisation (bleach strips HTML comments), so they are never destroyed.
"""

from __future__ import annotations

import re

from services.integrations.task_parser import parse_tasks
from services.security.sanitizer import sanitize_downstream_agent_content

MANAGED_START = "<!-- specforge:start -->"
MANAGED_END = "<!-- specforge:end -->"

# Matches a *complete* managed block (start … end) that contains no nested start
# marker. Anchoring on a complete pair — rather than the first start + the first
# end — means an orphan start marker (e.g. one a user documented, or one left by
# a prior malformed file) is never paired with the real block's end, so a re-sync
# replaces only the genuine block and never swallows the content between them.
_MANAGED_BLOCK_RE = re.compile(
    re.escape(MANAGED_START)
    + r"(?:(?!"
    + re.escape(MANAGED_START)
    + r").)*?"
    + re.escape(MANAGED_END),
    re.DOTALL,
)

# Derived sections stay small because these files are automatically trusted by
# coding agents. We never splice whole generated artifacts into the instruction
# file.
_DERIVED_SECTION_CHARS = 1200
_SECTION_RE_TEMPLATE = r"^{heading}\s*$([\s\S]*?)(?=^##\s+|\Z)"
_COMMAND_FIELD_RE = re.compile(
    r"^\*\*(?:Acceptance command|Test command|Command):\*\*\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def build_agents_md(
    stages: dict[str, str],
    *,
    existing: str | None = None,
) -> str:
    """Return the new ``AGENTS.md`` contents, preserving any user content.

    ``stages`` maps ``spec``/``plan``/``harness``/``tasks`` → their markdown.
    ``existing`` is the current file contents (``None`` if the file does not
    exist). The SpecForge-managed block is (re)written; everything outside the
    markers is round-tripped untouched.
    """
    managed = _render_managed_block(stages)
    block = f"{MANAGED_START}\n{managed}\n{MANAGED_END}"

    if not existing:
        return block + "\n"

    return _replace_or_append(existing, block)


def _replace_or_append(existing: str, block: str) -> str:
    """Swap the managed block in place; otherwise append, preserving user text.

    Replaces the first *complete* managed pair, preserving content both BEFORE
    and AFTER it. An orphan start marker (no matching end) is left untouched as
    user content and the fresh block is appended — fail safe, never truncate the
    file. This holds across repeated syncs: a re-run finds only the genuine block
    and never pairs an orphan start with the real block's end.
    """
    match = _MANAGED_BLOCK_RE.search(existing)
    if match:
        return existing[: match.start()] + block + existing[match.end() :]

    # No complete managed pair — keep all existing content and append the block.
    separator = (
        "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
    )
    return f"{existing}{separator}{block}\n"


def managed_block(content: str) -> str | None:
    """Return the complete SpecForge standard block from rendered content."""
    match = _MANAGED_BLOCK_RE.search(content)
    return match.group(0) if match else None


def merge_managed_block(existing: str, block: str) -> str:
    """Public safe-merge seam used by GitHub instruction reconciliation."""
    return _replace_or_append(existing, block)


def remove_managed_block(existing: str) -> tuple[str, bool]:
    """Remove only a complete managed block, preserving all other bytes."""
    updated, count = _MANAGED_BLOCK_RE.subn("", existing)
    return updated, bool(count)


def _render_managed_block(stages: dict[str, str]) -> str:
    """Build the standard-mode deterministic implementation guide."""
    spec = stages.get("spec", "") or ""
    plan = stages.get("plan", "") or ""
    harness = stages.get("harness", "") or ""
    tasks = stages.get("tasks", "") or ""

    parts: list[str] = [
        "# Agent context",
        "",
        (
            "_Renderer: standard-v2. Managed by SpecForge — edit outside the "
            "markers; this block is regenerated on every sync._"
        ),
        "",
        "## Mission",
        _named_section(
            spec,
            ("## Problem Statement", "## Overview", "## Executive Summary"),
            "See `SPEC.md` for the project mission and acceptance criteria.",
        ),
        "",
        "## Sources of truth",
        "1. `SPEC.md` — requirements and acceptance criteria.",
        "2. `PLAN.md` — architecture, interfaces, and technology choices.",
        "3. `harness/` — executable verification that defines done.",
        "4. `TASKS.md` — ordered implementation work.",
        "",
        "## Technology stack",
        _named_section(
            plan, ("## Technology Stack",), "See `PLAN.md` § Technology Stack."
        ),
        "",
        "## Working rules",
        "- Follow frozen interfaces in `PLAN.md` and `harness/`.",
        "- Never weaken, delete, or rewrite a test merely to make it pass.",
        "- Keep changes scoped to the current task and preserve unrelated work.",
        (
            "- Do not invent requirements; surface a blocker when the artifacts "
            "are ambiguous."
        ),
        "",
        "## Validation commands",
        _validation_commands(tasks, harness),
        "",
        "## Task workflow",
        (
            "Implement tasks in `TASKS.md` order. For each task, read its "
            "references, make the smallest complete change, run its stated "
            "validation, and proceed only when it passes."
        ),
        "",
        "## Task checklist",
        _task_list(tasks),
        "",
        "## Definition of done",
        (
            "All applicable task validations and harness tests pass, and the "
            "implementation satisfies `SPEC.md` acceptance criteria without "
            "changing frozen contracts."
        ),
    ]
    return "\n".join(parts).strip()


def _clean_derived(value: str) -> str:
    clean = sanitize_downstream_agent_content(value)
    clean = clean.replace(MANAGED_START, "").replace(MANAGED_END, "").strip()
    if len(clean) > _DERIVED_SECTION_CHARS:
        clean = clean[:_DERIVED_SECTION_CHARS].rstrip() + "…"
    return clean


def _named_section(stage_md: str, headings: tuple[str, ...], fallback: str) -> str:
    for heading in headings:
        match = re.search(
            _SECTION_RE_TEMPLATE.format(heading=re.escape(heading)),
            stage_md or "",
            re.MULTILINE,
        )
        if match:
            clean = _clean_derived(match.group(1))
            if clean:
                return clean
    return fallback


def _validation_commands(tasks_md: str, harness_md: str) -> str:
    commands: list[str] = []
    for source in (tasks_md or "", harness_md or ""):
        for match in _COMMAND_FIELD_RE.finditer(source):
            command = _clean_derived(match.group(1))
            if command and command not in commands:
                commands.append(command)
    if not commands:
        return (
            "Use the acceptance commands in `TASKS.md` and the documented runner "
            "in `harness/`; do not guess a command."
        )
    return "\n".join(f"- `{command.strip('`')}`" for command in commands[:20])


def _task_list(tasks_md: str) -> str:
    """A deterministic checklist of the workspace's tasks."""
    parsed = parse_tasks(tasks_md)
    if not parsed:
        return "_No tasks parsed._"
    lines = [
        f"- [ ] {sanitize_downstream_agent_content(t.ref)}: "
        f"{sanitize_downstream_agent_content(t.title)}"
        for t in parsed
    ]
    return "\n".join(lines)
