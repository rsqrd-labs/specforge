from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from services.security.prompt_guard import scan

_PRODUCT_INTENT_RE = re.compile(
    r"\b("
    r"app|application|platform|product|software|system|service|tool|website|"
    r"web\s+app|mobile\s+app|dashboard|portal|marketplace|saas|api|workflow|"
    r"automation|extension|plugin|bot|agent|copilot|assistant|crm|cms|erp|"
    r"database|backend|frontend"
    r")\b",
    re.I,
)
_BUILD_INTENT_RE = re.compile(
    r"\b("
    r"build|create|develop|design|launch|make|implement|need|want|help\s+me\s+build|"
    r"turn|automate|manage|track|schedule|generate|integrate|monitor|analyze"
    r")\b",
    re.I,
)
_USER_OR_WORKFLOW_RE = re.compile(
    r"\b("
    r"user|users|customer|customers|admin|admins|team|teams|manager|client|"
    r"workflow|process|screen|dashboard|login|signup|payment|notification|"
    r"report|approval|booking|task|project|order|tenant|role|permission"
    r")\b",
    re.I,
)
_NON_PRODUCT_REQUEST_RE = re.compile(
    r"\b("
    r"poem|joke|story|essay|song|lyrics|recipe|homework|translate|summarize|"
    r"rewrite|cover\s+letter|resume|email|blog\s+post|tweet|caption|explain|"
    r"chat\s+with\s+me|what\s+is|who\s+is|weather|news"
    r")\b",
    re.I,
)


@dataclass(frozen=True)
class ProblemStatementValidation:
    is_valid: bool
    code: str | None = None
    message: str | None = None
    hints: list[str] = field(default_factory=list)


class ProblemStatementValidationError(ValueError):
    def __init__(self, result: ProblemStatementValidation) -> None:
        self.result = result
        super().__init__(result.message or "Invalid problem statement")


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def validate_problem_statement(text: str) -> ProblemStatementValidation:
    value = _normalize(text)

    if len(value) < 50:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_too_short",
            message="Describe the product or software problem in at least 50 characters.",
            hints=[
                "Name the product or tool you want to build.",
                "Mention the primary users and the workflow they need.",
            ],
        )

    guard_result = scan(value)
    if not guard_result.is_safe:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_security_risk",
            message=(
                "This input looks like an instruction override or prompt-injection "
                "attempt, not a product problem statement."
            ),
            hints=[
                "Remove instructions that ask the AI to ignore rules, reveal prompts, or bypass safeguards.",
                "Describe the product goal, users, workflows, and expected outcome instead.",
            ],
        )

    has_product_intent = bool(_PRODUCT_INTENT_RE.search(value))
    has_build_intent = bool(_BUILD_INTENT_RE.search(value))
    has_workflow_context = bool(_USER_OR_WORKFLOW_RE.search(value))
    looks_like_non_product = bool(_NON_PRODUCT_REQUEST_RE.search(value))

    if looks_like_non_product and not has_build_intent:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_not_product_request",
            message=(
                "This does not look like a product or software problem statement."
            ),
            hints=[
                "Describe what you want to build, not a general chat or content-generation request.",
                "Include the users, core workflow, data involved, and success outcome.",
            ],
        )

    if not has_product_intent or not has_build_intent:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_missing_product_intent",
            message=(
                "This needs to describe a product, app, system, workflow, or software tool to build."
            ),
            hints=[
                "Start with a phrase like: I want to build a ...",
                "Mention what the product does and who it serves.",
            ],
        )

    if len(value.split()) < 10 and not has_workflow_context:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_too_vague",
            message="This is too vague to generate a reliable spec.",
            hints=[
                "Add the main user type, the core workflow, and the expected output.",
                "Include at least one constraint, integration, or important edge case if known.",
            ],
        )

    return ProblemStatementValidation(is_valid=True)


def assert_valid_problem_statement(text: str) -> None:
    result = validate_problem_statement(text)
    if not result.is_valid:
        raise ProblemStatementValidationError(result)
