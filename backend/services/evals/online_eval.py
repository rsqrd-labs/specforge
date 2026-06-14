from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import EvalResult
from services import langfuse_service
from services.llm.batch_executor import complete_background_llm
from services.llm.cost_ledger import LLMCostContext
from services.llm.gateway import get_llm
from services.llm.output_budget import output_budget_for_operation
from services.llm.provider_config import JUDGE_MODELS
from services.observability import EVAL_POLL_FAILURES, record_judge_call

logger = logging.getLogger(__name__)
_EVAL_TIMEOUT_SECONDS = 90.0
_PROMPT_LIMITS: dict[str, tuple[int, int]] = {
    "spec": (0, 28_000),
    "plan": (10_000, 18_000),
    "harness": (10_000, 20_000),
    "tasks": (10_000, 14_000),
}
_COMPACT_RETRY_LIMITS: dict[str, tuple[int, int]] = {
    "spec": (0, 14_000),
    "plan": (5_000, 9_000),
    "harness": (5_000, 10_000),
    "tasks": (5_000, 8_000),
}

# --- Structural task-reference validator ---
_TASK_HEADING_RE = re.compile(r"^###\s+T-(\d+):\s+(.+)$")
_HARNESS_REFS_FIELD_RE = re.compile(r"^\*\*Harness\s+refs:\*\*", re.IGNORECASE)
_BOLD_FIELD_START_RE = re.compile(r"^\*\*\w")
_BACKTICK_REF_RE = re.compile(r"`([^`]+)`")
_SETUP_ONLY_MARKER_RE = re.compile(r"_\(none|none\s*[—–-]", re.IGNORECASE)
# Per-task Priority and Estimate fields (T-164 / T-USE-05).
# Tolerant of bold/colon spacing variations and optional list-marker prefixes.
_PRIORITY_FIELD_RE = re.compile(
    r"^[\s\-*]*\*\*\s*Priority\s*:?\s*\*\*\s*:?\s*(.+?)\s*$", re.IGNORECASE
)
_ESTIMATE_FIELD_RE = re.compile(
    r"^[\s\-*]*\*\*\s*Estimate\s*:?\s*\*\*\s*:?\s*(.+?)\s*$", re.IGNORECASE
)
_PRIORITY_ENUM = {"MUST", "SHOULD", "COULD"}
_ESTIMATE_ENUM = {"S", "M", "L", "XL"}
_HARNESS_FILE_HEADING_RE = re.compile(r"^#{2,3}\s+File:\s+(.+)$")
_HARNESS_FENCE_OPEN_RE = re.compile(r"^(`{3,})[a-zA-Z0-9]*$")
_CLASS_DEF_RE = re.compile(r"^class\s+(Test\w+)")
# Matches Python test functions; TypeScript Jest tests are not parsed here.
_TEST_FUNC_DEF_RE = re.compile(r"^\s*def\s+(test_\w+)")

_JUDGE_SYSTEM = (
    "You are an independent senior product and software engineering evaluator. "
    "Score only what is present in the submitted artifact and provided context. "
    "Do not reward implied intent, brand polish, verbosity, or architectural detail "
    "that is not appropriate for the current stage. Be calibrated and conservative: "
    "85+ requires strong, concrete evidence across almost every rubric dimension. "
    "Respond ONLY with valid JSON matching the requested schema. No markdown."
)

_RUBRIC = """
Score each dimension from 0 to 100 using this calibration:
- 0-39: unusable or mostly missing
- 40-59: partial, vague, or materially risky
- 60-74: usable but has notable gaps
- 75-84: good, specific, and mostly complete
- 85-94: excellent with only minor gaps
- 95-100: exceptional, comprehensive, and immediately actionable

Rules:
- Use the full range. Do not default to 85.
- Penalize vague placeholders, contradictions, missing acceptance criteria,
  missing non-functional expectations, and untestable language.
- Prefer concrete, stakeholder-readable requirements over deep implementation
  detail unless the stage explicitly calls for implementation work.
- If a requirement, flow, test, or task cannot be found in the text, list it
  as a gap instead of assuming it exists.

Return exactly this JSON shape:
{
  "scores": {
    "goal_alignment": 0-100,
    "requirements_coverage": 0-100,
    "specificity_testability": 0-100,
    "user_flow_coverage": 0-100,
    "non_functional_coverage": 0-100,
    "traceability": 0-100,
    "feasibility": 0-100,
    "clarity": 0-100
  },
  "coverage_percent": null or 0-100,
  "uncovered_reqs": [],
  "tasks_without_ref": [],
  "risks": []
}
""".strip()

_STAGE_PROMPTS: dict[str, str] = {
    "spec": (
        "Evaluate this software specification as a product specification, not an "
        "implementation design. A strong spec defines product goals, user problems, "
        "functional requirements, non-functional requirements, user flows, acceptance "
        "criteria, constraints, success metrics, and high-level system expectations. "
        "It may include high-level conceptual diagrams, but should avoid deep "
        "implementation details.\n\n"
        f"{_RUBRIC}\n\n"
        "Content:\n{content}"
    ),
    "plan": (
        "Evaluate this implementation plan against the specification. A strong plan "
        "translates spec requirements into coherent work areas, sequencing, risks, "
        "dependencies, validation strategy, and delivery boundaries without losing "
        "traceability to the product goals.\n\n"
        f"{_RUBRIC}\n\n"
        "Spec:\n{spec_content}\n\nPlan:\n{content}"
    ),
    "harness": (
        "Evaluate this test harness against the specification. A strong harness "
        "covers critical functional requirements, user flows, acceptance criteria, "
        "edge cases, and major non-functional expectations. Set coverage_percent to "
        "your best evidence-based estimate of requirement coverage, and list specific "
        "uncovered requirements.\n\n"
        f"{_RUBRIC}\n\n"
        "Spec:\n{spec_content}\n\nHarness:\n{content}"
    ),
    "tasks": (
        "Evaluate this task list against the test harness and specification. A strong "
        "task list is complete, sequenced, independently actionable, test-linked, and "
        "traceable. In tasks_without_ref, include objects shaped as "
        '{{"task_number": int or null, "task_title": string, "reason": string, '
        '"referenced_test": string or null}} for any task that lacks a clear test or '
        "harness reference.\n\n"
        f"{_RUBRIC}\n\n"
        "Reference context:\n{spec_content}\n\nTasks:\n{content}"
    ),
}

_SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "spec": {
        "goal_alignment": 0.15,
        "requirements_coverage": 0.25,
        "specificity_testability": 0.20,
        "user_flow_coverage": 0.15,
        "non_functional_coverage": 0.15,
        "clarity": 0.10,
    },
    "plan": {
        "goal_alignment": 0.10,
        "requirements_coverage": 0.20,
        "specificity_testability": 0.15,
        "traceability": 0.20,
        "feasibility": 0.20,
        "clarity": 0.15,
    },
    "harness": {
        "requirements_coverage": 0.30,
        "specificity_testability": 0.20,
        "traceability": 0.20,
        "coverage_percent": 0.20,
        "clarity": 0.10,
    },
    "tasks": {
        "requirements_coverage": 0.20,
        "specificity_testability": 0.20,
        "traceability": 0.25,
        "feasibility": 0.20,
        "clarity": 0.15,
    },
}


def _parse_task_blocks(tasks_content: str) -> list[dict[str, Any]]:
    """Split tasks content into per-task dicts with harness_refs extracted.

    harness_refs values:
      None  — **Harness refs:** field is absent (GENERATION_FAILURE)
      []    — field present but marked as setup-only
      [str] — list of backtick-quoted test path references
    """
    lines = tasks_content.split("\n")
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _TASK_HEADING_RE.match(line.rstrip())
        if m:
            headings.append((i, int(m.group(1)), m.group(2).strip()))

    tasks: list[dict[str, Any]] = []
    for idx, (start, task_num, task_title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        block = lines[start:end]

        refs_start: int | None = None
        for i, line in enumerate(block):
            if _HARNESS_REFS_FIELD_RE.match(line):
                refs_start = i
                break

        if refs_start is None:
            tasks.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "harness_refs": None,
                }
            )
            continue

        field_lines: list[str] = []
        for i, line in enumerate(block[refs_start:]):
            stripped = line.strip()
            if i > 0 and (
                _BOLD_FIELD_START_RE.match(stripped) or stripped.startswith("###")
            ):
                break
            field_lines.append(line)

        refs_text = "\n".join(field_lines)
        if _SETUP_ONLY_MARKER_RE.search(refs_text):
            tasks.append(
                {"task_number": task_num, "task_title": task_title, "harness_refs": []}
            )
            continue

        tasks.append(
            {
                "task_number": task_num,
                "task_title": task_title,
                "harness_refs": _BACKTICK_REF_RE.findall(refs_text),
            }
        )

    return tasks


def _extract_harness_refs(harness_content: str) -> set[str]:
    """Build matchable test identifiers from harness file headings and code blocks.

    Supports Python pytest conventions (def test_* / class Test*).
    TypeScript Jest tests (it/describe/test) are not extracted.
    """
    known: set[str] = set()
    lines = harness_content.split("\n")
    i = 0
    while i < len(lines):
        heading_m = _HARNESS_FILE_HEADING_RE.match(lines[i])
        if heading_m:
            raw_path = heading_m.group(1).strip()
            normalized = raw_path.replace("\\", "/")
            if normalized.startswith("harness/"):
                normalized = normalized[len("harness/") :]
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                fence_m = _HARNESS_FENCE_OPEN_RE.match(lines[j].rstrip())
                if fence_m:
                    fence = fence_m.group(1)
                    k = j + 1
                    current_class: str | None = None
                    while k < len(lines) and lines[k].rstrip() != fence:
                        line = lines[k]
                        cls_m = _CLASS_DEF_RE.match(line)
                        if cls_m:
                            current_class = cls_m.group(1)
                        elif line and not line.startswith((" ", "\t")):
                            current_class = None
                        func_m = _TEST_FUNC_DEF_RE.match(line)
                        if func_m:
                            fn = func_m.group(1)
                            known.add(f"{normalized}::{fn}")
                            known.add(fn)
                            if current_class and line.startswith((" ", "\t")):
                                known.add(f"{normalized}::{current_class}::{fn}")
                                known.add(f"{current_class}::{fn}")
                        k += 1
                    i = k + 1
                    continue
        i += 1
    return known


def _ref_matches_harness(ref: str, known_refs: set[str]) -> bool:
    """Lenient match: strip harness/ prefix, try full path, Class::method, bare name."""
    normalized = ref.strip().replace("\\", "/")
    if normalized.startswith("harness/"):
        normalized = normalized[len("harness/") :]
    if normalized in known_refs:
        return True
    parts = normalized.split("::")
    if len(parts) >= 2 and "::".join(parts[-2:]) in known_refs:
        return True
    return bool(parts) and parts[-1] in known_refs


def _build_gap_details(
    missing_ref: str,
) -> tuple[str | None, str | None, str, str, str]:
    """Parse a missing test ref into actionable details.

    Returns (harness_file, class_name, fn_name, code_stub, remediation_text).
    """
    normalized = missing_ref.strip().replace("\\", "/")
    if normalized.startswith("harness/"):
        normalized = normalized[len("harness/") :]

    parts = normalized.split("::")

    if len(parts) == 3 and "/" in parts[0]:
        # file::Class::method
        file_path, class_name, fn_name = parts[0], parts[1], parts[2]
        harness_file = f"harness/{file_path}"
        code_stub = f"class {class_name}:\n    def {fn_name}(self):\n        pass"
        remediation = (
            f"In `{harness_file}`, add `def {fn_name}(self)` "
            f"to the `{class_name}` class."
        )
    elif len(parts) == 2 and "/" in parts[0]:
        # file::function
        file_path, fn_name = parts[0], parts[1]
        harness_file = f"harness/{file_path}"
        class_name = None
        code_stub = f"def {fn_name}():\n    pass"
        remediation = f"In `{harness_file}`, add `def {fn_name}()`."
    elif len(parts) == 2:
        # Class::method (no file path)
        class_name, fn_name = parts[0], parts[1]
        harness_file = None
        code_stub = f"class {class_name}:\n    def {fn_name}(self):\n        pass"
        remediation = (
            f"Add `def {fn_name}(self)` to the `{class_name}` class in your harness."
        )
    else:
        # bare function name
        fn_name = parts[0]
        harness_file = None
        class_name = None
        code_stub = f"def {fn_name}():\n    pass"
        remediation = f"Add `def {fn_name}()` to a test file in your harness."

    return harness_file, class_name, fn_name, code_stub, remediation


def _extract_field_value(line: str, regex: re.Pattern[str]) -> str | None:
    """Pull the value after **Field:** from a single line, stripped of formatting."""
    match = regex.match(line.rstrip())
    if not match:
        return None
    value = match.group(1).strip()
    # Trim trailing parenthetical commentary (e.g. "MUST (ship blocker)").
    paren = value.find("(")
    if paren > 0:
        value = value[:paren].strip()
    # Strip surrounding markdown emphasis, backticks, and trailing punctuation.
    value = value.strip("`*_ .,;")
    return value or None


def _validate_task_fields(tasks_content: str) -> list[dict[str, Any]]:
    """Per-task Priority/Estimate validation (T-USE-05).

    Returns one issue per missing or invalid field, shaped to merge cleanly into
    the existing tasks_without_ref list. Issues are surfaced in the existing
    TaskValidationPanel UI without any shape change.
    """
    lines = tasks_content.split("\n")
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _TASK_HEADING_RE.match(line.rstrip())
        if m:
            headings.append((i, int(m.group(1)), m.group(2).strip()))

    issues: list[dict[str, Any]] = []
    for idx, (start, task_num, task_title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        block = lines[start:end]

        priority_value: str | None = None
        estimate_value: str | None = None
        for line in block:
            if priority_value is None:
                priority_value = _extract_field_value(line, _PRIORITY_FIELD_RE)
            if estimate_value is None:
                estimate_value = _extract_field_value(line, _ESTIMATE_FIELD_RE)
            if priority_value is not None and estimate_value is not None:
                break

        if priority_value is None or priority_value.upper() not in _PRIORITY_ENUM:
            reason = (
                "Task is missing a **Priority:** line."
                if priority_value is None
                else (
                    f"`{priority_value}` is not a valid Priority "
                    "(expected MUST/SHOULD/COULD)."
                )
            )
            issues.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "reason": reason,
                    "referenced_test": None,
                    "gap_type": "MISSING_PRIORITY",
                    "remediation": (
                        "Add `**Priority:** MUST` (or SHOULD/COULD) to this task."
                    ),
                    "harness_file": None,
                    "code_stub": None,
                }
            )

        if estimate_value is None or estimate_value.upper() not in _ESTIMATE_ENUM:
            reason = (
                "Task is missing an **Estimate:** line."
                if estimate_value is None
                else f"`{estimate_value}` is not a valid Estimate (expected S/M/L/XL)."
            )
            issues.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "reason": reason,
                    "referenced_test": None,
                    "gap_type": "MISSING_ESTIMATE",
                    "remediation": ("Add `**Estimate:** S` (or M/L/XL) to this task."),
                    "harness_file": None,
                    "code_stub": None,
                }
            )

    return issues


def _validate_task_references(
    tasks_content: str, harness_content: str
) -> list[dict[str, Any]]:
    """Structural traceability check: returns issues with gap_type classification.

    GENERATION_FAILURE — task has no **Harness refs:** field (prompt quality issue,
      hidden from users but logged for observability).
    GENUINE_GAP — task refs a test that does not exist in the harness (shown to user).
    """
    task_blocks = _parse_task_blocks(tasks_content)
    known_refs = _extract_harness_refs(harness_content)

    issues: list[dict[str, Any]] = []
    generation_failures: list[int] = []

    for task in task_blocks:
        refs = task["harness_refs"]
        task_num = task["task_number"]
        task_title = task["task_title"]

        if refs is None:
            generation_failures.append(task_num)
            issues.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "reason": "Task is missing its Harness refs field.",
                    "referenced_test": None,
                    "gap_type": "GENERATION_FAILURE",
                    "remediation": None,
                    "harness_file": None,
                    "code_stub": None,
                }
            )
        elif refs:
            unmatched = [r for r in refs if not _ref_matches_harness(r, known_refs)]
            if unmatched:
                missing = unmatched[0]
                harness_file, class_name, fn_name, code_stub, remediation = (
                    _build_gap_details(missing)
                )
                issues.append(
                    {
                        "task_number": task_num,
                        "task_title": task_title,
                        "reason": (
                            f"`{missing}` is referenced but not found "
                            "in the harness."
                        ),
                        "referenced_test": missing,
                        "gap_type": "GENUINE_GAP",
                        "remediation": remediation,
                        "harness_file": harness_file,
                        "code_stub": code_stub,
                    }
                )
        # refs == [] means setup-only — not an issue

    if generation_failures:
        logger.warning(
            "tasks_structural_validation_generation_failures count=%d task_numbers=%s",
            len(generation_failures),
            generation_failures[:10],
        )

    issues.extend(_validate_task_fields(tasks_content))

    return issues


def _log_dataset_error(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        logger.error("langfuse_dataset_background_failed", extra={"error": str(exc)})


def _dataset_for_score(score: int | float | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return "high_quality_generations"
    if score < 60:
        return "low_quality_generations"
    return None


def _clamp_score(value: Any) -> int | None:
    if value is None:
        return None
    try:
        score = round(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _weighted_score(
    values: dict[str, int | None], weights: dict[str, float]
) -> int | None:
    weighted_total = 0.0
    weight_total = 0.0
    for key, weight in weights.items():
        score = values.get(key)
        if score is None:
            continue
        weighted_total += score * weight
        weight_total += weight
    if weight_total == 0:
        return None
    return round(weighted_total / weight_total)


def _average_score(*scores: int | None) -> int | None:
    present = [score for score in scores if score is not None]
    if not present:
        return None
    return round(sum(present) / len(present))


def _normalise_task_issues(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    issues: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        task_number = item.get("task_number")
        if task_number is not None:
            try:
                task_number = int(task_number)
            except (TypeError, ValueError):
                task_number = None
        task_title = item.get("task_title") or item.get("task") or "Unspecified task"
        reason = item.get("reason") or "No clear test or harness reference."
        referenced_test = item.get("referenced_test")
        issues.append(
            {
                "task_number": task_number,
                "task_title": str(task_title),
                "reason": str(reason),
                "referenced_test": (
                    str(referenced_test) if referenced_test is not None else None
                ),
                "gap_type": item.get("gap_type"),
                "remediation": item.get("remediation"),
                "harness_file": item.get("harness_file"),
                "code_stub": item.get("code_stub"),
            }
        )
    return issues


def _normalise_eval_payload(stage_type: str, data: dict[str, Any]) -> dict[str, Any]:
    scores = data.get("scores")
    if not isinstance(scores, dict):
        overall_score = _clamp_score(data.get("overall_score"))
        completeness = _clamp_score(data.get("completeness"))
        clarity = _clamp_score(data.get("clarity"))
        coverage_percent = _clamp_score(data.get("coverage_percent"))
        return {
            "overall_score": overall_score,
            "completeness": completeness,
            "clarity": clarity,
            "coverage_percent": coverage_percent,
            "uncovered_reqs": data.get("uncovered_reqs"),
            "tasks_without_ref": _normalise_task_issues(data.get("tasks_without_ref")),
        }

    score_values = {
        key: _clamp_score(value)
        for key, value in scores.items()
        if isinstance(key, str)
    }
    coverage_percent = _clamp_score(data.get("coverage_percent"))
    if coverage_percent is not None:
        score_values["coverage_percent"] = coverage_percent

    completeness = _average_score(
        score_values.get("requirements_coverage"),
        score_values.get("user_flow_coverage"),
        score_values.get("non_functional_coverage"),
        score_values.get("traceability"),
    )
    clarity = score_values.get("clarity")
    overall_score = _weighted_score(
        score_values,
        _SCORE_WEIGHTS.get(stage_type, _SCORE_WEIGHTS["spec"]),
    )

    uncovered_reqs = data.get("uncovered_reqs")
    if not isinstance(uncovered_reqs, list):
        uncovered_reqs = None

    return {
        "overall_score": overall_score,
        "completeness": completeness,
        "clarity": clarity,
        "coverage_percent": coverage_percent,
        "uncovered_reqs": uncovered_reqs,
        "tasks_without_ref": _normalise_task_issues(data.get("tasks_without_ref")),
    }


def _parse_eval_json(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return data

    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def _compact_text(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    head = max(0, int(limit * 0.65))
    tail = max(0, limit - head)
    omitted = len(value) - head - tail
    return (
        value[:head].rstrip()
        + f"\n\n[... {omitted} characters omitted for eval budget ...]\n\n"
        + value[-tail:].lstrip()
    )


def _build_eval_prompt(
    stage_type: str,
    content: str,
    spec_content: str,
    *,
    compact: bool = False,
) -> str:
    context_limit, content_limit = (
        _COMPACT_RETRY_LIMITS if compact else _PROMPT_LIMITS
    ).get(stage_type, _PROMPT_LIMITS["spec"])
    context = _compact_text(spec_content, context_limit)
    artifact = _compact_text(content, content_limit)
    return (
        _STAGE_PROMPTS[stage_type]
        .replace("{spec_content}", context)
        .replace("{content}", artifact)
    )


async def _call_eval_judge(
    *,
    provider: str,
    model: str,
    user_prompt: str,
) -> str:
    # Count the spend at the point the provider request is issued — once per real
    # attempt, so the compact-prompt re-try counts as the separate call it is
    # (issue #27, Phase 0).
    record_judge_call("eval.score")
    result = await asyncio.wait_for(
        complete_background_llm(
            operation="eval.score",
            provider=provider,
            model=model,
            system=_JUDGE_SYSTEM,
            user=user_prompt,
            max_tokens=output_budget_for_operation("eval.score", provider),
            stage_type="eval",
            prompt_version="eval-v2",
            adapter_factory=get_llm,
            cost_context=LLMCostContext(product_surface="eval"),
        ),
        timeout=max(settings.llm_complete_timeout_seconds, _EVAL_TIMEOUT_SECONDS),
    )
    return result.output


async def _score_with_retry(
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str,
    model: str,
) -> str | None:
    for compact in (False, True):
        user_prompt = _build_eval_prompt(
            stage_type,
            content,
            spec_content,
            compact=compact,
        )
        try:
            return await _call_eval_judge(
                provider=provider,
                model=model,
                user_prompt=user_prompt,
            )
        except Exception:
            logger.exception(
                "eval judge call failed for stage_version_id=%s compact=%s",
                stage_version_id,
                compact,
            )
    return None


async def _add_generation_to_dataset(
    *,
    dataset_name: str,
    content_generation_id: str,
    eval_result: EvalResult,
    content: str,
) -> None:
    await langfuse_service.get_langfuse_client().add_to_dataset(
        dataset_name=dataset_name,
        item={
            "stage_type": eval_result.stage_type,
            "overall_score": eval_result.overall_score,
            "completeness": eval_result.completeness,
            "clarity": eval_result.clarity,
            "content": content,
        },
        source_observation_id=content_generation_id,
    )


async def run_eval(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    db: AsyncSession,
    provider: str = "anthropic",
    judge_model: str | None = None,
    content_generation_id: str | None = None,
    harness_content: str | None = None,
) -> EvalResult | None:
    resolved_judge_model = judge_model or JUDGE_MODELS[provider]
    raw = await _score_with_retry(
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        content=content,
        spec_content=spec_content,
        provider=provider,
        model=resolved_judge_model,
    )
    if raw is None:
        # Both compact=False and compact=True calls failed — increment the
        # eval poll failure counter so silent drops are visible.  T-194.
        EVAL_POLL_FAILURES.labels(stage_type=stage_type).inc()
        return None

    data = _parse_eval_json(raw)
    if data is None:
        logger.error(
            "eval judge returned non-JSON for stage_version_id=%s: %r",
            stage_version_id,
            raw[:200],
        )
        retry_raw = await _score_with_retry(
            stage_version_id=stage_version_id,
            stage_type=stage_type,
            content=content,
            spec_content=spec_content,
            provider=provider,
            model=resolved_judge_model,
        )
        if retry_raw is None:
            EVAL_POLL_FAILURES.labels(stage_type=stage_type).inc()
            return None
        data = _parse_eval_json(retry_raw)
        if data is None:
            logger.error(
                "eval judge retry returned non-JSON for stage_version_id=%s: %r",
                stage_version_id,
                retry_raw[:200],
            )
            EVAL_POLL_FAILURES.labels(stage_type=stage_type).inc()
            return None

    return await _persist_eval_data(
        db,
        data,
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        content=content,
        harness_content=harness_content,
        content_generation_id=content_generation_id,
    )


def build_eval_request(
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str | None = None,
) -> tuple[str, str, int]:
    """Build the (system, user, max_tokens) for one eval-judge call.

    The submit side of the deferred-batch path (Phase 3): a batch request reuses
    exactly the prompt the synchronous path's first (non-compact) attempt would
    send, so a batched eval scores the same artifact identically. ``provider``
    is threaded so a per-(operation, provider) budget override (Phase 4) applies
    to batched evals identically to synchronous ones.
    """
    user_prompt = _build_eval_prompt(stage_type, content, spec_content, compact=False)
    return (
        _JUDGE_SYSTEM,
        user_prompt,
        output_budget_for_operation("eval.score", provider),
    )


async def persist_eval_from_raw(
    db: AsyncSession,
    raw: str,
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    harness_content: str | None = None,
    content_generation_id: str | None = None,
) -> EvalResult | None:
    """Parse a judge response and persist the EvalResult, or return None.

    The completion side of the deferred-batch path: one parse attempt, no
    re-scoring (a batch round trip can take hours — re-batching on a parse miss
    is the wrong call). Returns None when the judge output is not parseable JSON;
    the caller decides whether to fall back to a single synchronous score.
    """
    data = _parse_eval_json(raw)
    if data is None:
        logger.error(
            "batch eval judge returned non-JSON for stage_version_id=%s: %r",
            stage_version_id,
            raw[:200],
        )
        return None
    return await _persist_eval_data(
        db,
        data,
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        content=content,
        harness_content=harness_content,
        content_generation_id=content_generation_id,
    )


async def _persist_eval_data(
    db: AsyncSession,
    data: dict[str, Any],
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    harness_content: str | None,
    content_generation_id: str | None,
) -> EvalResult:
    normalised = _normalise_eval_payload(stage_type, data)
    coverage_percent: int | None = normalised["coverage_percent"]
    uncovered_reqs: list[str] | None = normalised["uncovered_reqs"]
    tasks_without_ref: list[dict[str, Any]] | None = normalised["tasks_without_ref"]

    if stage_type == "tasks" and harness_content:
        tasks_without_ref = _validate_task_references(content, harness_content)

    flagged = False
    if (
        stage_type == "harness"
        and coverage_percent is not None
        and coverage_percent < 80
    ):
        flagged = True
    if stage_type == "tasks" and tasks_without_ref:
        # GENERATION_FAILURE is a prompt quality issue — only GENUINE_GAP
        # flags the result
        flagged = any(
            i.get("gap_type") != "GENERATION_FAILURE" for i in tasks_without_ref
        )

    eval_result = EvalResult(
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        overall_score=normalised["overall_score"],
        completeness=normalised["completeness"],
        clarity=normalised["clarity"],
        coverage_percent=coverage_percent,
        uncovered_reqs=uncovered_reqs,
        tasks_without_ref=tasks_without_ref,
        flagged=flagged,
    )
    db.add(eval_result)
    await db.commit()
    await db.refresh(eval_result)
    if content_generation_id and eval_result.overall_score is not None:
        try:
            await langfuse_service.get_langfuse_client().score_generation(
                generation_id=content_generation_id,
                name="overall",
                value=float(eval_result.overall_score),
            )
        except Exception:
            logger.exception(
                "eval score link failed for stage_version_id=%s",
                stage_version_id,
            )
        dataset_name = _dataset_for_score(eval_result.overall_score)
        if dataset_name:
            dataset_task = asyncio.create_task(
                _add_generation_to_dataset(
                    dataset_name=dataset_name,
                    content_generation_id=content_generation_id,
                    eval_result=eval_result,
                    content=content,
                )
            )
            dataset_task.add_done_callback(_log_dataset_error)
    return eval_result


async def run_eval_background(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str,
    judge_model: str,
    content_generation_id: str | None = None,
    harness_content: str | None = None,
) -> EvalResult | None:
    async with AsyncSessionLocal() as db:
        return await run_eval(
            stage_version_id,
            stage_type,
            content,
            spec_content,
            db,
            provider,
            judge_model,
            content_generation_id,
            harness_content=harness_content,
        )
