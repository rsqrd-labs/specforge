"""Deterministic graders for the generation surfaces with no corpus coverage.

The prompt-quality audit (theme 4) named three frequently-exercised surfaces
with no golden-corpus or grader coverage at all: the harness gap-patch (P06),
increment generation (P13), and the judges themselves. This module adds
zero-LLM graders for the first two; the judges' deterministic layers are pinned
by ``harness/tests/backend/test_judgment_golden.py`` against the fixtures in
``prompt_eval/golden_judgment/``.

These graders deliberately do NOT share the ``GraderFn`` stage signature —
a gap-patch is graded against ``(existing_harness, target_reqs)`` and an
increment against its baseline TASKS.md, neither of which is a
``(stage_type, artifact_md, deps)`` triple — so they are exported by name and
are not members of ``ALL_GRADERS``. A live run over freshly generated output
uses them exactly as the CI fixtures do.
"""

from __future__ import annotations

import re

from prompt_eval.graders.common import GraderResult, make_result

# `## File: path` section heads, as the patch prompt mandates. The core harness
# artifact uses `### File:` for its Files section — the patch's two-hash form is
# part of its output contract.
_PATCH_FILE_RE = re.compile(r"^##\s*File:\s*(\S+)\s*$", re.MULTILINE)
_HARNESS_FILE_RE = re.compile(r"^###?\s*File:\s*(\S+)\s*$", re.MULTILINE)
_TESTS_TAG_RE = re.compile(r"(?:#|//)\s*Tests:\s*([^\n]+)")
_REQ_ID_RE = re.compile(r"\b(?:FR|NFR|SEC|AC)-\d{3}(?:\.\d+)?\b")
_STUB_BODY_RE = re.compile(
    r"^\s*(?:pass|\.\.\.|raise\s+NotImplementedError\b|#\s*TODO)\s*$",
    re.MULTILINE,
)

# Task blocks in TASKS.md / increment output: `### T-015: Title`.
_TASK_HEADING_RE = re.compile(r"^###\s+T-(\d+):\s*(.+?)\s*$", re.MULTILINE)
_HARNESS_REFS_FIELD_RE = re.compile(
    r"^\*\*Harness\s+refs:\*\*", re.IGNORECASE | re.MULTILINE
)


def _patch_files(patch_md: str) -> list[str]:
    return _PATCH_FILE_RE.findall(patch_md or "")


def harness_patch_covers_targets(
    patch_md: str,
    target_reqs: list[str],
) -> GraderResult:
    """coverage: every requested uncovered requirement gains a tagged test.

    The gap-patch exists to close specific named gaps; a patch that emits
    plausible-looking files without a ``# Tests: <req-id>`` tag for each target
    silently leaves the gap open (the coverage joins run on the tags).
    """
    targets = [req.strip() for req in target_reqs if req.strip()]
    if not targets:
        return make_result(
            name="harness_patch_covers_targets",
            axis="coverage",
            score=1.0,
            metadata={"targets": 0, "missing": 0},
        )
    tagged: set[str] = set()
    for tag_line in _TESTS_TAG_RE.findall(patch_md or ""):
        tagged.update(_REQ_ID_RE.findall(tag_line))
    missing = sorted(req for req in targets if req not in tagged)
    return make_result(
        name="harness_patch_covers_targets",
        axis="coverage",
        score=(len(targets) - len(missing)) / len(targets),
        findings=[f"No tagged test for {req}" for req in missing],
        metadata={"targets": len(targets), "missing": len(missing)},
    )


def harness_patch_is_additive(
    patch_md: str,
    existing_harness_md: str,
) -> GraderResult:
    """format/safety: the patch adds new companion files and nothing else.

    The patch prompt's hard output contract: only new ``## File:`` sections,
    never a rewrite of an existing file (an LLM 'helpfully' re-emitting an
    existing file would clobber it on apply), every section carrying a fenced
    body with no stub-only content.
    """
    findings: list[str] = []
    patch_files = _patch_files(patch_md)
    if not patch_files:
        return make_result(
            name="harness_patch_is_additive",
            axis="format",
            score=0.0,
            findings=["Patch contains no `## File:` sections."],
            metadata={"files": 0},
        )
    existing = set(_HARNESS_FILE_RE.findall(existing_harness_md or ""))
    for path in patch_files:
        if path in existing:
            findings.append(f"Patch re-emits existing file {path}")

    sections = _PATCH_FILE_RE.split(patch_md)
    # split() yields [preamble, path1, body1, path2, body2, ...]
    preamble = sections[0].strip()
    if preamble:
        findings.append("Patch carries preamble/commentary before the first file.")
    bodies = sections[2::2]
    for path, body in zip(patch_files, bodies, strict=False):
        fence_count = body.count("```")
        if fence_count < 2 or fence_count % 2 != 0:
            findings.append(f"{path}: file body is not one balanced fenced block.")
            continue
        fenced = body.split("```", 2)[1]
        # Strip the language line, then flag stub-only content.
        content_lines = fenced.splitlines()[1:]
        content = "\n".join(content_lines).strip()
        if not content:
            findings.append(f"{path}: fenced body is empty.")
        elif _STUB_BODY_RE.fullmatch(content):
            findings.append(f"{path}: fenced body is a stub.")

    per_file_penalty = 1.0 / max(len(patch_files), 1)
    return make_result(
        name="harness_patch_is_additive",
        axis="format",
        score=1.0 - per_file_penalty * len(findings),
        findings=findings,
        metadata={"files": len(patch_files), "violations": len(findings)},
    )


def _task_blocks(tasks_md: str) -> dict[int, str]:
    """Map task number → full block text (heading through next heading)."""
    blocks: dict[int, str] = {}
    matches = list(_TASK_HEADING_RE.finditer(tasks_md or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(tasks_md)
        blocks[int(match.group(1))] = tasks_md[match.start() : end]
    return blocks


def increment_growth_is_monotonic(
    baseline_tasks_md: str,
    grown_tasks_md: str,
) -> GraderResult:
    """coverage/format: an increment appends well-formed tasks, mutating nothing.

    The increment contract (P13): the grown TASKS.md contains every baseline
    task byte-for-byte (the timeline is append-only — a 'refined' historical
    task silently rewrites already-exported GitHub issues), new tasks continue
    the T-NNN sequence with no gaps or collisions, and every new task carries a
    ``**Harness refs:**`` field so it stays joinable to the harness.
    """
    findings: list[str] = []
    baseline = _task_blocks(baseline_tasks_md)
    grown = _task_blocks(grown_tasks_md)

    for number, block in baseline.items():
        if number not in grown:
            findings.append(f"Baseline task T-{number:03d} disappeared.")
        elif grown[number].strip() != block.strip():
            findings.append(f"Baseline task T-{number:03d} was mutated.")

    new_numbers = sorted(set(grown) - set(baseline))
    if not new_numbers:
        findings.append("Increment added no tasks.")
    baseline_max = max(baseline, default=0)
    expected = list(range(baseline_max + 1, baseline_max + 1 + len(new_numbers)))
    if new_numbers and new_numbers != expected:
        findings.append(
            f"New task numbers {new_numbers} do not continue the sequence "
            f"(expected {expected})."
        )
    for number in new_numbers:
        if not _HARNESS_REFS_FIELD_RE.search(grown[number]):
            findings.append(f"New task T-{number:03d} has no Harness refs field.")

    checks = max(len(baseline) + max(len(new_numbers), 1), 1)
    return make_result(
        name="increment_growth_is_monotonic",
        axis="coverage",
        score=1.0 - len(findings) / checks,
        findings=findings,
        metadata={
            "baseline_tasks": len(baseline),
            "new_tasks": len(new_numbers),
            "violations": len(findings),
        },
    )
