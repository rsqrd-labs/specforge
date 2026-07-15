"""Demo Day operating manual + construction report (plan §8).

For ``mode="demo_day"`` workspaces only, the export bundle gains an agent
operating manual — the *build protocol* that encodes the two preconditions the
construction guarantee depends on (run the test after every task; never edit the
frozen harness) plus the per-task loop and definition of done. This is distinct
from the GitHub integration's generic agent-context ``AGENTS.md`` (which restates
the four stages): the manual is *how to execute them safely*.

Filename by agent: ``CLAUDE.md`` for ``target_agent="claude_code"``, ``AGENTS.md``
for ``target_agent="codex"`` — same body, agent-idiomatic phrasing.

Pure functions over the persisted stage contents; no LLM call.
"""

from __future__ import annotations

import re
from typing import Protocol

from services.integrations import agents_md_builder
from services.integrations.task_parser import parse_tasks
from services.security.sanitizer import sanitize_downstream_agent_content

_CLAUDE_FILENAME = "CLAUDE.md"
_AGENTS_FILENAME = "AGENTS.md"
CONSTRUCTION_REPORT_FILENAME = "CONSTRUCTION_REPORT.md"
DEMO_MANAGED_START = "<!-- specforge:demo-day:start -->"
DEMO_MANAGED_END = "<!-- specforge:demo-day:end -->"

# The plan's ## Technology Stack section heading (Demo Day plan contract).
_TECH_STACK_HEADING = "## Technology Stack"
_SECTION_RE_TEMPLATE = r"^{heading}\s*$([\s\S]*?)(?=^##\s+|\Z)"


class _WorkspaceLike(Protocol):
    name: str
    target_agent: str | None


def manual_filename(target_agent: str | None) -> str:
    """The operating-manual filename for the target agent (defaults to AGENTS.md)."""
    return _CLAUDE_FILENAME if target_agent == "claude_code" else _AGENTS_FILENAME


def effective_targets(target_agent: str | None) -> tuple[str, ...]:
    """Resolve the persisted selection; legacy NULL remains Codex-compatible."""
    if target_agent == "both":
        return ("codex", "claude_code")
    if target_agent == "claude_code":
        return ("claude_code",)
    return ("codex",)


def _extract_technology_stack(plan_content: str) -> str:
    """Pull the PLAN ## Technology Stack body so the manual pins the stack inline.

    Sanitized before interpolation (audit finding #3): this body lands verbatim
    in CLAUDE.md/AGENTS.md, a file the user's own coding agent auto-loads as
    high-trust instructions, so an HTML comment or script-like payload smuggled
    through PLAN.md must not survive the splice — the same defense
    ``agents_md_builder.build_agents_md`` already applies to its own excerpts.
    """
    if not plan_content:
        return "See PLAN.md ## Technology Stack."
    pattern = re.compile(
        _SECTION_RE_TEMPLATE.format(heading=re.escape(_TECH_STACK_HEADING)),
        re.MULTILINE,
    )
    match = pattern.search(plan_content)
    body = match.group(1).strip() if match else ""
    body = sanitize_downstream_agent_content(body).strip()
    return body or "See PLAN.md ## Technology Stack."


def _agent_todo_note(target_agent: str | None) -> str:
    if target_agent == "claude_code":
        return (
            "Track tasks with your todo list — one task per todo item. Mark a todo "
            "done only when its acceptance command AND the end-to-end smoke test are "
            "green."
        )
    return (
        "Keep a running task checklist and work one task at a time. Only advance "
        "when the task's acceptance command AND the end-to-end smoke test pass."
    )


def build_agent_manual(
    workspace: _WorkspaceLike,
    plan_content: str,
    *,
    target_agent: str | None = None,
    tasks_content: str = "",
) -> tuple[str, str]:
    """Return ``(filename, content)`` for the Demo Day operating manual.

    ``plan_content`` is the finalised PLAN.md text; the pinned stack is
    interpolated from its ## Technology Stack section.
    """
    selected = target_agent or workspace.target_agent
    filename = manual_filename(selected)
    stack = _extract_technology_stack(plan_content)
    todo_note = _agent_todo_note(selected)
    name = (workspace.name or "this build").strip() or "this build"
    task_lines = [
        f"- [ ] {sanitize_downstream_agent_content(task.ref)}: "
        f"{sanitize_downstream_agent_content(task.title)}"
        for task in parse_tasks(tasks_content)
    ]
    checklist = "\n".join(task_lines) or "- Follow the ordered tasks in `TASKS.md`."
    managed = f"""# Build Protocol — {name}

_Renderer: demo-day-v2. Managed by SpecForge._

You are implementing this Demo Day build from SPEC.md, PLAN.md, the harness, and
TASKS.md. Follow this protocol exactly. The four documents are the contract; this file
is how to execute them safely.

## Non-negotiable invariants
1. Implement tasks in TASKS.md order, one at a time. Do not skip ahead.
2. After each task, run its acceptance command. Do NOT proceed while it is red.
3. NEVER edit anything under `harness/`. The tests are the frozen oracle — if a test
   seems wrong, stop and surface it; do not change it to pass.
4. NEVER change a frozen interface (PLAN `## Interface Contracts`, HARNESS
   `## Frozen Interface Contracts`). Implement against them.
5. The stack is pinned (see below). Do not add dependencies or bump versions without
   noting it explicitly in your output.
6. The app must run and the end-to-end smoke test must pass after every task.
7. If blocked on a task for more than ~15 minutes, stop and report the blocker rather
   than hacking the test or stubbing the contract.

## Stack (pinned)
{stack}

## The loop
For each task T-NNN:
  a. Read the task: its Spec refs, Plan refs, Harness refs, Precondition.
  b. Implement the file-level steps.
  c. Run the task's acceptance command and the end-to-end smoke test.
  d. Only advance when both are green.

{todo_note}

## Task checklist
{checklist}

## Definition of done
All tasks complete AND the end-to-end smoke test is green. At that point the prototype
does what SPEC.md's Acceptance Criteria specify — by construction.
"""
    content = f"{DEMO_MANAGED_START}\n{managed.strip()}\n{DEMO_MANAGED_END}\n"
    return filename, content


def build_instruction_files(
    workspace: _WorkspaceLike,
    stages: dict[str, str],
    *,
    target_agent: str | None = None,
) -> dict[str, str]:
    """Render exactly the selected standard or Demo Day instruction files."""
    selection = workspace.target_agent if target_agent is None else target_agent
    files: dict[str, str] = {}
    for target in effective_targets(selection):
        if getattr(workspace, "mode", "standard") == "demo_day":
            filename, content = build_agent_manual(
                workspace,
                stages.get("plan", ""),
                target_agent=target,
                tasks_content=stages.get("tasks", ""),
            )
        else:
            filename = manual_filename(target)
            content = agents_md_builder.build_agents_md(stages)
        files[filename] = content
    return files


def build_construction_report(verdict: dict) -> str:
    """Render the §7 construction verdict as CONSTRUCTION_REPORT.md (§8.2).

    ``verdict`` is the persisted JSON form of ``ConstructionVerdict``:
    ``{verified, checks: {id: {name, passed, gaps}}, estimated_minutes,
    time_budget_minutes, stage_versions}``. Tolerant of partial/legacy shapes —
    a missing field renders a sane default rather than raising, because this runs
    at export time and must never fail a download.
    """
    verified = bool(verdict.get("verified"))
    checks = verdict.get("checks") or {}
    estimated = verdict.get("estimated_minutes")
    budget = verdict.get("time_budget_minutes")

    if verified:
        badge = "✅ Construction-verified — the package is internally consistent."
    else:
        gap_count = sum(
            1
            for c in checks.values()
            if isinstance(c, dict) and not c.get("passed", True)
        )
        badge = (
            f"⚠️ Not construction-verified — {gap_count} structural "
            f"gap{'s' if gap_count != 1 else ''} named below."
        )

    lines = [
        "# Construction Report",
        "",
        badge,
        "",
        "## Checks",
        "",
    ]
    for check_id in sorted(checks):
        result = checks[check_id]
        if not isinstance(result, dict):
            continue
        passed = result.get("passed", False)
        name = result.get("name", check_id)
        mark = "PASS" if passed else "FAIL"
        lines.append(f"- **{check_id} {name}**: {mark}")
        for gap in result.get("gaps", []) or []:
            lines.append(f"    - {gap}")

    lines.append("")
    lines.append("## Estimated build time (advisory)")
    lines.append("")
    if isinstance(estimated, (int, float)):
        hours = estimated / 60
        budget_note = ""
        if isinstance(budget, (int, float)):
            budget_note = f" (target ≤ {budget / 60:.1f}h)"
        lines.append(
            f"Estimated build time: ~{hours:.1f}h{budget_note}. This is calibration "
            "only — it is never certified, only the structural checks above are."
        )
    else:
        lines.append(
            "No per-task minute estimates were available. The time budget is advisory "
            "and never certified."
        )
    lines.append("")
    return "\n".join(lines)
