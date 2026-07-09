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

# Per-stage section length cap so AGENTS.md stays a navigable briefing, not a
# verbatim dump of four large artifacts.
_STAGE_EXCERPT_CHARS = 1500


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


def _render_managed_block(stages: dict[str, str]) -> str:
    """Build the (sanitised, deterministic) managed-block body from the stages."""
    spec = stages.get("spec", "") or ""
    plan = stages.get("plan", "") or ""
    harness = stages.get("harness", "") or ""
    tasks = stages.get("tasks", "") or ""

    parts: list[str] = [
        "# Agent context",
        "",
        (
            "_Managed by SpecForge — edit outside the markers; this block is "
            "regenerated on every sync._"
        ),
        "",
        "## What this project is",
        _excerpt(spec),
        "",
        "## Architecture",
        _excerpt(plan),
        "",
        "## How the harness works",
        _excerpt(harness),
        "",
        "## Tasks",
        _task_list(tasks),
        "",
        "## Where to look",
        "- `SPEC.md` — the full specification",
        "- `PLAN.md` — the architecture and plan",
        "- `harness/` — the tests that define done",
        "- `TASKS.md` — the task breakdown",
    ]
    return "\n".join(parts).strip()


def _excerpt(stage_md: str) -> str:
    """A sanitised, bounded excerpt of a stage artifact."""
    clean = sanitize_downstream_agent_content(stage_md).strip()
    if not clean:
        return "_Not available._"
    if len(clean) <= _STAGE_EXCERPT_CHARS:
        return clean
    return clean[:_STAGE_EXCERPT_CHARS].rstrip() + "\n\n…"


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
