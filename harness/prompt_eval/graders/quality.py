from __future__ import annotations

import datetime
import json
import re
from functools import lru_cache
from pathlib import Path

from prompt_eval.graders.common import make_result

# backend/prompts/plan.py holds the deprecation denylist (T-241) and its
# DENYLIST_LAST_REVIEWED anchor.  graders/ -> prompt_eval -> harness -> repo root.
_PLAN_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "backend" / "prompts" / "plan.py"
)
# backend/prompts/style_denylist.py holds the filler/hedge-phrase denylist
# (density initiative) and its own FILLER_DENYLIST_LAST_REVIEWED anchor. Read
# as source text for the same reason as _PLAN_PROMPT_PATH above: this grader
# carries no runtime dependency on the backend package.
_STYLE_DENYLIST_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "prompts"
    / "style_denylist.py"
)
_TECH_SAFETY_POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "services"
    / "pipeline"
    / "tech_safety_policy.json"
)
_REVIEW_DATE_RE = re.compile(r'DENYLIST_LAST_REVIEWED\s*=\s*"(\d{4}-\d{2}-\d{2})"')
_FILLER_REVIEW_DATE_RE = re.compile(
    r'FILLER_DENYLIST_LAST_REVIEWED\s*=\s*"(\d{4}-\d{2}-\d{2})"'
)
_FILLER_PHRASES_BLOCK_RE = re.compile(
    r"FILLER_PHRASES\s*:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\n\)", re.DOTALL
)
_QUOTED_LITERAL_RE = re.compile(r'"([^"]+)"')
# Directive #8 budget: the denylist must be re-reviewed within 12 months.
_FRESHNESS_BUDGET_MONTHS = 12


@lru_cache(maxsize=1)
def _read_denylist_review_date() -> datetime.date | None:
    """Parse DENYLIST_LAST_REVIEWED out of backend/prompts/plan.py source.

    Reads the source file rather than importing it so the grader carries no
    runtime dependency on the backend package (the eval runs from harness/).
    Returns None when the file or a well-formed date cannot be found.
    """
    try:
        src = _PLAN_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _REVIEW_DATE_RE.search(src)
    if match is None:
        return None
    try:
        return datetime.date.fromisoformat(match.group(1))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _read_filler_denylist_review_date() -> datetime.date | None:
    """Parse FILLER_DENYLIST_LAST_REVIEWED out of style_denylist.py source."""
    try:
        src = _STYLE_DENYLIST_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FILLER_REVIEW_DATE_RE.search(src)
    if match is None:
        return None
    try:
        return datetime.date.fromisoformat(match.group(1))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _read_filler_phrases() -> tuple[str, ...]:
    """Parse the FILLER_PHRASES tuple out of style_denylist.py source.

    Same read-as-text approach as the review-date parsers above — no runtime
    import of the backend package. Returns an empty tuple if the file or the
    tuple literal cannot be found (fail-open: banned_phrase_hit_count falls
    back to its pre-existing pattern list).
    """
    try:
        src = _STYLE_DENYLIST_PATH.read_text(encoding="utf-8")
    except OSError:
        return ()
    block = _FILLER_PHRASES_BLOCK_RE.search(src)
    if block is None:
        return ()
    return tuple(_QUOTED_LITERAL_RE.findall(block.group(1)))


@lru_cache(maxsize=1)
def _read_tech_safety_policy() -> dict:
    try:
        return json.loads(_TECH_SAFETY_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _freshness_deadline(reviewed: datetime.date) -> datetime.date:
    """The date 12 months after *reviewed* (Feb-29 clamped to Feb-28)."""
    try:
        return reviewed.replace(year=reviewed.year + 1)
    except ValueError:
        return reviewed.replace(year=reviewed.year + 1, day=28)


def _score_denylist_freshness(
    reviewed: datetime.date | None,
    today: datetime.date,
) -> tuple[float, list[str]]:
    """Pure freshness decision, factored out for deterministic testing."""
    if reviewed is None:
        return 0.0, [
            "Deprecation denylist freshness anchor DENYLIST_LAST_REVIEWED not "
            "found in backend/prompts/plan.py — the freshness gate cannot run."
        ]
    if today > _freshness_deadline(reviewed):
        age_days = (today - reviewed).days
        return 0.0, [
            f"Deprecation denylist last reviewed {reviewed.isoformat()} "
            f"({age_days} days ago) — exceeds the {_FRESHNESS_BUDGET_MONTHS}-month "
            f"freshness budget. Re-review the denylist entries in plan.py and bump "
            f"DENYLIST_LAST_REVIEWED."
        ]
    return 1.0, []


def denylist_freshness(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: both denylists (T-241 deprecated-tech, filler-phrase) are fresh.

    Phase 19 directive #8 — a denylist goes stale on its own clock (Python
    EOLs pass, gpt-4/gemini-1.x deprecate; filler vocabulary drifts too). This
    grader reads DENYLIST_LAST_REVIEWED from backend/prompts/plan.py and
    FILLER_DENYLIST_LAST_REVIEWED from backend/prompts/style_denylist.py (the
    closest machine-readable proxy for each list's most recent entry, since
    both denylists are undated prose/tuples) and fails (score 0.0) if either
    is more than 12 months old, forcing a periodic re-review. It is artifact-
    independent, returning the same score on every stage call.
    """
    today = datetime.date.today()
    reviewed = _read_denylist_review_date()
    dep_score, dep_findings = _score_denylist_freshness(reviewed, today)
    filler_reviewed = _read_filler_denylist_review_date()
    filler_score, filler_findings = _score_denylist_freshness(filler_reviewed, today)
    return make_result(
        name="denylist_freshness",
        axis="quality",
        score=min(dep_score, filler_score),
        findings=dep_findings + filler_findings,
        metadata={
            "last_reviewed": reviewed.isoformat() if reviewed else "unknown",
            "filler_last_reviewed": (
                filler_reviewed.isoformat() if filler_reviewed else "unknown"
            ),
        },
    )


def _section_body(artifact_md: str, heading: str) -> str:
    start = artifact_md.find(heading)
    if start < 0:
        return ""
    rest = artifact_md[start + len(heading) :]
    end = re.search(r"\n##\s+", rest)
    return rest[: end.start()] if end else rest


def deprecated_api_hit_count(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: deprecated runtime, SDK, or LLM family choices are absent."""

    policy = _read_tech_safety_policy()
    patterns = [
        str(entry.get("pattern"))
        for entry in policy.get("hard_denylists", [])
        if entry.get("pattern")
    ]
    if not patterns:
        patterns = [
            r"\bPython\s*(?:<=|<|=)?\s*3\.10\b",
            r"\bNode(?:\.js)?\s*(?:<=|<|=)?\s*18\b",
            r"\bgpt-3(?:\.5)?\b",
            r"\bgemini-1\.",
            r"\bclaude-[12](?:\.|\b)",
        ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, artifact_md, flags=re.IGNORECASE))
    return make_result(
        name="deprecated_api_hit_count",
        axis="quality",
        score=1.0 / (1 + len(hits)),
        findings=[f"Deprecated choice mentioned: {hit}" for hit in hits[:10]],
        metadata={"hit_count": len(hits)},
    )


def banned_phrase_hit_count(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: low-specificity, placeholder, and filler phrases are absent."""

    patterns = [
        r"\bTBD\b",
        r"\bTODO\b",
        r"\bFIXME\b",
        r"\bbest effort\b",
        r"\bhandle errors\b",
        r"\bsecure the endpoint\b",
        r"\bplaceholder\b",
        r"\bpass\s*(?:#.*)?$",
    ]
    # Density initiative: the filler/hedge-phrase denylist in
    # backend/prompts/style_denylist.py, parsed as source text (no runtime
    # dependency on the backend package — see _read_filler_phrases).
    patterns.extend(
        r"\b" + re.escape(phrase) + r"\b" for phrase in _read_filler_phrases()
    )
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(
            re.findall(pattern, artifact_md, flags=re.IGNORECASE | re.MULTILINE)
        )
    return make_result(
        name="banned_phrase_hit_count",
        axis="quality",
        score=1.0 / (1 + len(hits)),
        findings=[f"Banned phrase hit: {hit}" for hit in hits[:10]],
        metadata={"hit_count": len(hits)},
    )


def adr_completeness_pct(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: top-five ADRs include the five required lines."""

    if stage_type != "plan":
        return make_result(name="adr_completeness_pct", axis="quality", score=1.0)

    body = _section_body(artifact_md, "## Architecture Decision Records")
    entries = [
        entry for entry in re.split(r"(?m)^###\s+ADR-\d+\s+", body) if entry.strip()
    ]
    required = [
        "Decision:",
        "Forces:",
        "Options Considered:",
        "Chosen + WHY-not-next-best:",
        "Reversal Cost:",
    ]
    if not entries:
        return make_result(
            name="adr_completeness_pct",
            axis="quality",
            score=0.0,
            findings=["No ADR entries found."],
            metadata={"adr_count": 0},
        )

    complete_lines = 0
    missing: list[str] = []
    for index, entry in enumerate(entries, start=1):
        for label in required:
            if label in entry:
                complete_lines += 1
            else:
                missing.append(f"ADR-{index:03d} missing {label}")
    expected_lines = max(5, len(entries)) * len(required)
    score = complete_lines / expected_lines
    if len(entries) < 5:
        missing.append("Fewer than five ADRs present.")
    return make_result(
        name="adr_completeness_pct",
        axis="quality",
        score=score,
        findings=missing[:10],
        metadata={"adr_count": len(entries), "missing_lines": len(missing)},
    )


def frontend_section_presence_when_applicable(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    """quality: browser-facing plans include Frontend Architecture."""

    if stage_type != "plan":
        return make_result(
            name="frontend_section_presence_when_applicable",
            axis="quality",
            score=1.0,
        )

    combined = " ".join([artifact_md, *deps.values()])
    applicable = bool(
        re.search(
            r"\b(frontend|browser|web UI|dashboard|screen|page)\b",
            combined,
            re.I,
        )
    )
    present = "## Frontend Architecture" in artifact_md
    return make_result(
        name="frontend_section_presence_when_applicable",
        axis="quality",
        score=1.0 if (not applicable or present) else 0.0,
        findings=[] if (not applicable or present) else ["Frontend plan is missing."],
        metadata={"applicable": int(applicable)},
    )


def capacity_model_presence(
    stage_type: str,
    artifact_md: str,
    deps: dict[str, str],
):
    if stage_type != "plan":
        return make_result(name="capacity_model_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## Capacity Model")
    required = ["Target RPS", "p95", "p99", "Data growth", "10x", "100x"]
    missing = [token for token in required if token.lower() not in body.lower()]
    return make_result(
        name="capacity_model_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"Capacity Model missing {token}" for token in missing],
    )


def stride_presence(stage_type: str, artifact_md: str, deps: dict[str, str]):
    if stage_type != "plan":
        return make_result(name="stride_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## Threat Model")
    required = [
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information disclosure",
        "Denial of service",
        "Elevation of privilege",
    ]
    missing = [token for token in required if token not in body]
    return make_result(
        name="stride_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"STRIDE missing {token}" for token in missing],
    )


def slo_presence(stage_type: str, artifact_md: str, deps: dict[str, str]):
    if stage_type != "plan":
        return make_result(name="slo_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## SLOs and Error Budgets")
    required = ["Availability", "Latency", "Correctness", "Error budget", "Paging"]
    missing = [token for token in required if token.lower() not in body.lower()]
    return make_result(
        name="slo_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"SLO section missing {token}" for token in missing],
    )


def fmea_presence(stage_type: str, artifact_md: str, deps: dict[str, str]):
    if stage_type != "plan":
        return make_result(name="fmea_presence", axis="quality", score=1.0)
    body = _section_body(artifact_md, "## Failure Mode and Effects Analysis")
    required = [
        "Failure mode",
        "Detection",
        "Blast radius",
        "Mitigation",
        "Recovery time",
        "Customer impact",
    ]
    missing = [token for token in required if token.lower() not in body.lower()]
    return make_result(
        name="fmea_presence",
        axis="quality",
        score=(len(required) - len(missing)) / len(required),
        findings=[f"FMEA missing {token}" for token in missing],
    )


_DEPTH_ID_RE = re.compile(
    r"\b(?:FR|NFR|SEC|AC|US|RISK|OQ)-\d{3}(?:\.\d+)?\b|\bADR-\d+\b"
)
_DEPTH_TASK_ID_RE = re.compile(r"\bT-\d{3}\b")
# A data row: pipe-delimited, and not a markdown table separator (---|---).
_DEPTH_TABLE_ROW_RE = re.compile(r"^\s*\|(?!\s*:?-+:?\s*\|).+\|\s*$", re.MULTILINE)
_DEPTH_FILE_HEADING_RE = re.compile(r"^#{2,3}\s*File:\s*\S+", re.MULTILINE)
_DEPTH_H2_RE = re.compile(r"^##\s+\S", re.MULTILINE)


def _substance_units(artifact_md: str) -> dict[str, int]:
    """Count substance signals independent of prose length or line count.

    Density initiative (2026-08-02): the density prompt change makes total
    line count shrink even as substance holds, so the old fixed-line-count
    floor would fail dense, complete output for being short — precisely the
    outcome the density change is going after. This mirrors the precedent
    ``_manifest_section_issue`` already set in artifact_validator.py (grading
    ``## File Tree`` by path count, not prose length): count things that
    correlate with real decision content — distinct requirement/decision/task
    IDs (FR/NFR/SEC/AC/US/RISK/OQ/ADR/T-NNN), markdown table data rows, and
    ``### File:`` blocks.

    ``h2_headings`` is reported for visibility but deliberately EXCLUDED from
    the gated total: ``validate_sections``/``MissingSectionError`` already
    guarantees every required heading is present as a separate, terminal
    gate, so counting headings here double-dips on a check that exists
    elsewhere and — because every stage's heading count alone (e.g. spec's 17)
    sits close to or above these floors — would let an artifact that is
    nothing but empty headings and the bare-minimum ID floor score 1.0,
    defeating the point of a depth gate. See
    ``test_artifact_depth_pct_rejects_a_degenerate_shell`` in
    ``harness/tests/backend/`` for the regression this guards against.
    """
    ids = set(_DEPTH_ID_RE.findall(artifact_md)) | set(
        _DEPTH_TASK_ID_RE.findall(artifact_md)
    )
    return {
        "distinct_ids": len(ids),
        "table_rows": len(_DEPTH_TABLE_ROW_RE.findall(artifact_md)),
        "file_blocks": len(_DEPTH_FILE_HEADING_RE.findall(artifact_md)),
        "h2_headings": len(_DEPTH_H2_RE.findall(artifact_md)),
    }


# Substance-unit floors — a degenerate-output guard, not a padding reward.
# Gated total = distinct_ids + table_rows + file_blocks (h2_headings excluded,
# see _substance_units' docstring). Set above the bare structural minimum
# already enforced elsewhere (_SPEC_MIN_ID_FLOORS: FR>=5/NFR>=3/AC>=3 = 11
# distinct ids; _MIN_TASK_BLOCKS=6 T-NNN ids) so an artifact that clears ONLY
# those pre-existing floors and nothing else still fails this one — proven by
# test_artifact_depth_pct_rejects_a_degenerate_shell. NOT tuned against
# live-generated output under the new prompts — the golden workspace fixtures
# need a live regeneration + human quality review pass before
# baseline_scores.json is re-pinned (see docs/evals/PROMPT_CHANGE_REVIEW.md),
# which is a separate, explicitly deferred step; treat these as a starting
# point, not a validated calibration.
_SUBSTANCE_FLOORS: dict[str, int] = {
    "spec": 18,
    "plan": 20,
    "harness": 14,
    "tasks": 14,
}


def artifact_depth_pct(stage_type: str, artifact_md: str, deps: dict[str, str]):
    """quality: generated artifacts retain enough substance to avoid truncation.

    Replaces the old fixed-line-count floor (a prose-volume proxy the density
    initiative deliberately makes a worse and worse signal) with a
    substance-token count: distinct FR/NFR/SEC/AC/US/RISK/OQ/ADR/T-NNN IDs,
    markdown table data rows, and ``### File:`` blocks (heading count is
    tracked but excluded from the gate — see ``_substance_units``). A
    short-but-dense artifact that answers every ID in a table row instead of
    a paragraph now scores the same as a verbose one that says the same thing
    at 3x the length — which is the whole point of the density change.
    """
    floor = _SUBSTANCE_FLOORS.get(stage_type, 14)
    units = _substance_units(artifact_md)
    gated_total = units["distinct_ids"] + units["table_rows"] + units["file_blocks"]
    score = min(1.0, gated_total / floor) if floor else 1.0
    findings = []
    if score < 1.0:
        findings.append(
            f"{stage_type} artifact has {gated_total} substance units "
            f"(ids={units['distinct_ids']}, table_rows={units['table_rows']}, "
            f"file_blocks={units['file_blocks']}); expected at least {floor}."
        )
    return make_result(
        name="artifact_depth_pct",
        axis="quality",
        score=score,
        findings=findings,
        metadata={"substance_units": gated_total, "minimum_units": floor, **units},
    )
