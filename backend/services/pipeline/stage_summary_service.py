from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

SUMMARY_SECTIONS = (
    "Decisions",
    "Entities",
    "APIs",
    "Security Requirements",
    "Data Constraints",
    "Open Questions",
    "Downstream Constraints",
)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)
_REQ_ID_RE = re.compile(r"\b(?:FR|NFR|SEC)-\d{3}(?:\.\d+)?\b")
_API_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`|)]+)")
_ENTITY_RE = re.compile(r"\b(?:Entity|Table|Model):\s*([A-Za-z][A-Za-z0-9_ -]+)")


@dataclass(frozen=True)
class StageSummary:
    stage_type: str
    source_hash: str
    content: str


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def summary_cache_key(workspace_id, stage_type: str, source_hash: str) -> str:
    return f"stage-summary:{workspace_id}:{stage_type}:{source_hash}"


def summarize_stage_content(stage_type: str, content: str) -> StageSummary:
    source_hash = content_hash(content)
    headings = _extract_headings(content)
    requirement_ids = sorted(set(_REQ_ID_RE.findall(content)))
    api_paths = sorted({f"{method} {path}" for method, path in _API_RE.findall(content)})
    entities = sorted(set(_ENTITY_RE.findall(content)))

    sections = {
        "Decisions": _bulletize(headings[:12], "No explicit decisions extracted."),
        "Entities": _bulletize(entities, "No explicit entities extracted."),
        "APIs": _bulletize(api_paths, "No explicit API contracts extracted."),
        "Security Requirements": _bulletize(
            [req for req in requirement_ids if req.startswith("SEC-")],
            "No explicit security requirement IDs extracted.",
        ),
        "Data Constraints": _extract_constraint_summary(content),
        "Open Questions": _extract_open_question_summary(content),
        "Downstream Constraints": _bulletize(
            requirement_ids[:40],
            "No requirement IDs extracted for downstream traceability.",
        ),
    }

    rendered = "\n\n".join(
        f"## {section}\n{sections[section]}" for section in SUMMARY_SECTIONS
    )
    return StageSummary(stage_type=stage_type, source_hash=source_hash, content=rendered)


def _extract_headings(content: str) -> list[str]:
    return [
        match.group(2).strip()
        for match in _HEADING_RE.finditer(content)
        if match.group(2).strip()
    ]


def _extract_constraint_summary(content: str) -> str:
    lines = _matching_lines(
        content,
        (
            "constraint",
            "nullable",
            "unique",
            "foreign key",
            "retention",
            "delete",
            "validation",
        ),
    )
    return _bulletize(lines[:20], "No explicit data constraints extracted.")


def _extract_open_question_summary(content: str) -> str:
    lines = _matching_lines(content, ("open question", "assumption", "tbd"))
    return _bulletize(lines[:20], "No explicit open questions extracted.")


def _matching_lines(content: str, needles: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip(" -\t")
        if not line:
            continue
        lowered = line.lower()
        if any(needle in lowered for needle in needles):
            matches.append(line[:240])
    return matches


def _bulletize(items: list[str], empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)
