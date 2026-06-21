from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from services.security.prompt_guard import scan

# Problem-statement size bounds — the single semantic authority for the floor
# and ceiling (docs/PROBLEM_STATEMENT_COMPRESSION_PLAN.md §2). The Pydantic
# request schemas (`schemas/workspace.py`) and the DB CHECK constraint
# (`models/workspace.py` + migration 0026) mirror these exact *raw-length*
# numbers, so the bound is consistent across all three layers. (One pre-existing
# edge this does not erase: the gate validates the raw input, while
# `workspace_service.create` stores the `sanitize_text` result, and bleach
# entity-escaping can expand length — `<` -> `&lt;` — so an input sitting on the
# ceiling with many such chars could still trip the DB CHECK. That predates this
# change; it is not introduced by raising the cap.)
#
# PROBLEM_STATEMENT_MAX_CHARS is the outer DoS/storage ceiling — the largest
# blob we will *store* at all (a long pasted PRD / requirements doc). It is
# deliberately far above the per-call model budget (`C_MAX`, a later phase):
# everything between that budget and this ceiling is handled by compression,
# not rejection. A "too large" rejection happens *only* above this ceiling, far
# above any realistic paste. These are character counts (matching the DB
# `char_length` constraint and Pydantic `max_length`), not token counts.
PROBLEM_STATEMENT_MIN_CHARS = 50
PROBLEM_STATEMENT_MAX_CHARS = 50_000

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
    # User types
    r"user|users|customer|customers|admin|admins|team|teams|manager|managers|"
    r"client|clients|employee|employees|staff|operator|operators|member|members|"
    r"doctor|doctors|patient|patients|receptionist|receptionists|"
    r"buyer|buyers|seller|sellers|vendor|vendors|"
    # Workflows and process artefacts (including plurals)
    r"workflow|workflows|process|processes|screen|screens|"
    r"dashboard|dashboards|login|signup|payment|payments|"
    r"notification|notifications|report|reports|approval|approvals|"
    r"booking|bookings|task|tasks|project|projects|order|orders|"
    r"tenant|tenants|role|roles|permission|permissions|"
    # Software action verbs specific to real products
    r"track|store|filter|notify|alert|schedule|submit|"
    r"export|import|sync|authenticate|assign|validate|"
    r"upload|download|fetch|query|"
    # Common product data and domain artefacts
    r"record|records|file|files|account|accounts|profile|profiles|"
    r"settings|message|messages|event|events|calendar|"
    r"form|forms|channel|channels|request|requests|endpoint|endpoints"
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
    # Ceiling check on the *raw* length first, so it matches the DB
    # `char_length` constraint and the Pydantic `max_length` exactly (whitespace
    # normalisation only ever shrinks the value, so checking the raw length is
    # the conservative, storage-faithful bound). This is the single rejection
    # point for a genuinely oversized blob; everything below it is accepted and,
    # in a later phase, compressed rather than refused.
    if len(text) > PROBLEM_STATEMENT_MAX_CHARS:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_too_long",
            message=(
                "Keep the problem statement under "
                f"{PROBLEM_STATEMENT_MAX_CHARS:,} characters."
            ),
            hints=[
                "Paste only the requirements and context the product needs.",
                "Trim background, transcripts, or unrelated appendices.",
            ],
        )

    value = _normalize(text)

    if len(value) < PROBLEM_STATEMENT_MIN_CHARS:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_too_short",
            message=(
                "Describe the product or software problem in at least "
                f"{PROBLEM_STATEMENT_MIN_CHARS} characters."
            ),
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
                (
                    "Remove instructions that ask the AI to ignore rules, "
                    "reveal prompts, or bypass safeguards."
                ),
                (
                    "Describe the product goal, users, workflows, and "
                    "expected outcome instead."
                ),
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
                (
                    "Describe what you want to build, not a general chat "
                    "or content-generation request."
                ),
                "Include the users, core workflow, data involved, and success outcome.",
            ],
        )

    if not has_product_intent or not has_build_intent:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_missing_product_intent",
            message=(
                "This needs to describe a product, app, system, workflow, "
                "or software tool to build."
            ),
            hints=[
                "Start with a phrase like: I want to build a ...",
                "Mention what the product does and who it serves.",
            ],
        )

    if not has_workflow_context:
        return ProblemStatementValidation(
            is_valid=False,
            code="problem_statement_not_product_relevant",
            message=(
                "This doesn't describe a real software product, system, " "or workflow."
            ),
            hints=[
                (
                    "Describe what the product does, who uses it, and what "
                    "problem it solves."
                ),
                (
                    "Focus on a workflow, user action, or data problem that "
                    "software can address."
                ),
            ],
        )

    return ProblemStatementValidation(is_valid=True)


def assert_valid_problem_statement(text: str) -> None:
    result = validate_problem_statement(text)
    if not result.is_valid:
        raise ProblemStatementValidationError(result)
