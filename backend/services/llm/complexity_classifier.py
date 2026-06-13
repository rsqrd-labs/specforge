"""Deterministic, no-LLM complexity classifier for the core-generation starting tier.

Phase 5.2 of issue #26.  Core generation ships a *cheap-primary* policy: every
request starts on the provider's cheapest viable model (Claude Haiku 4.5 /
GPT-5.4 Mini) and escalates to the mid tier only on a runtime/provider failure
(``CORE_GENERATION_TIER_POLICY``) or a quality-gate failure (Phase 5.1).  For a
small set of *predictably hard* requests, that cheap first attempt — and the one
platform-funded regenerate — is wasted before the escalation finally reaches a
capable model.

This classifier raises the **starting** tier for those requests, deterministically
and with no extra model call or latency.  It is a *floor*, never a ceiling: it can
only raise the starting tier above the cheap default, never lower it, and it is
disabled by default (``settings.core_complexity_routing``) until the golden-corpus
live gate validates it (Phase 5.3, ``docs/evals/ROUTE_PROMOTION.md``).

Design notes:

* **Every signal is a pure function of stored, non-LLM inputs** — problem text,
  upstream artifact bytes, the stage row, the workspace template.  No network, no
  tokenizer, no provider call.  This keeps it cheap, testable, and reproducible
  in the offline golden-corpus eval (``scripts/run_llm_route_eval.py``).
* **Regulated/high-stakes keywords dominate.**  Generic auth ("users",
  "authenticate", "login") is intentionally *excluded* — almost every SaaS app
  has it and it is not a complexity signal.  Only genuinely high-stakes,
  compliance/sensitive-data/safety-critical terms count, so a simple CRUD app
  that merely authenticates users stays on the cheap primary.
* **Ambiguity is gated behind length.**  A short vague prompt ("make me an app
  that makes money") yields clarifying questions, which is cheap work — routing
  it to a strong model is pure waste.  Ambiguity markers therefore only count
  once the problem statement is also substantial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Tier capability ordering -------------------------------------------------
# Core generation uses three "cheap" peer tiers across providers (Anthropic
# ``small`` = Haiku, OpenAI ``mini`` = GPT-5.4 Mini) plus ``mid`` and ``strong``.
# For the purpose of "raise the floor", the two cheap tiers are peers (rank 0):
# raising to a ``mid`` floor lifts Haiku/Mini to Sonnet/GPT-5.4; a ``strong``
# floor lifts to Opus/GPT-5.5 (and degrades to mid via route fallback for a
# provider with no core-gen strong model, e.g. Google).
_TIER_CAPABILITY_RANK = {"small": 0, "mini": 0, "mid": 1, "strong": 2}

# --- Scoring thresholds -------------------------------------------------------
# Tuned against the existing golden anchors (``asdd_route_golden.json``):
#   * ``crud_saas_team_tasks`` ("authenticate users")     -> normal (stays cheap)
#   * ``vague_make_me_money``  (short, vague)              -> normal (stays cheap)
#   * ``regulated_health_triage`` (PHI / EHR / patient)   -> high   (-> mid floor)
# Keep these three pinned in the unit tests; they guard the two failure modes the
# signal set invites (generic-auth false positives, vague-prompt over-routing).
_HIGH_THRESHOLD = 3
_CRITICAL_THRESHOLD = 6

# --- Signal weights -----------------------------------------------------------
_REGULATED_WEIGHT = 3
_PRIOR_GATE_BLOCKED_WEIGHT = 3
_TEMPLATE_WEIGHT = 2
_STAGE_BASE_WEIGHT = 1  # harness/tasks integrate more upstream than spec/plan
_AMBIGUITY_WEIGHT = 1
_AMBIGUITY_MIN_LENGTH = 400  # ambiguity only counts for a substantial prompt
_AMBIGUITY_MIN_MARKERS = 2

# Regulated / high-stakes domains.  Matched case-insensitively on word boundaries.
# Generic auth/CRUD terms are deliberately absent.
_REGULATED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"\b{p}\b", re.IGNORECASE)
    for p in (
        # compliance regimes
        "hipaa",
        "pci",
        "pci[- ]dss",
        "gdpr",
        "ccpa",
        "soc ?2",
        "sox",
        "ferpa",
        "glba",
        "fedramp",
        "iso ?27001",
        # sensitive data / regulated domains
        "phi",
        "pii",
        "ssn",
        "social security number",
        "medical",
        "clinical",
        "patient",
        "health record",
        "ehr",
        "emr",
        "diagnos\\w*",
        "prescription",
        "biometric",
        "financial",
        "banking",
        "payment",
        "credit card",
        "cardholder",
        "brokerage",
        "securities",
        "tax",
        "payroll",
        "insurance claim",
        # safety-critical integrity controls
        "audit trail",
        "immutable audit",
        "regulatory",
        "compliance",
        "encryption at rest",
    )
)

# Under-specification markers.  Only counted for a substantial prompt (see above).
_AMBIGUITY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\betc\.?\b",
        r"\band so on\b",
        r"\band more\b",
        r"\band others\b",
        r"\bvarious\b",
        r"\bsomehow\b",
        r"\bmaybe\b",
        r"\bpossibly\b",
        r"\bnot sure\b",
        r"\btbd\b",
        r"\bto be (?:decided|determined)\b",
        r"\bthings like\b",
        r"\bor similar\b",
    )
)

# Template slugs whose domain implies inherent complexity.  Substring match on the
# slug (templates use kebab-case slugs); conservative so an unknown slug scores 0.
_COMPLEX_TEMPLATE_MARKERS: tuple[str, ...] = (
    "health",
    "medical",
    "clinical",
    "fintech",
    "finance",
    "payment",
    "banking",
    "regulated",
    "compliance",
    "hipaa",
    "insurance",
)

# FR-001 / NFR-3 / SEC-002 / AC-12 style identifiers carried in upstream artifacts.
_REQUIREMENT_ID_PATTERN = re.compile(r"\b(?:FR|NFR|NF|SEC|AC)-\d+\b", re.IGNORECASE)

_HIGHER_FLOOR_STAGES = frozenset({"harness", "tasks"})


@dataclass(frozen=True)
class ComplexitySignals:
    """Raw, non-LLM inputs the classifier scores.  All fields are cheap to gather
    from the stage/workspace rows already loaded during preflight."""

    stage_type: str
    problem_statement: str
    upstream_artifact_count: int
    upstream_artifacts_text: str
    template_slug: str | None = None
    prior_quality_gate_blocked: bool = False
    clarification_count: int = 0


@dataclass(frozen=True)
class ComplexityAssessment:
    """The classifier verdict: a level, the tier floor it implies, and an
    explanation trail for logging/eval transparency."""

    level: str  # "normal" | "high" | "critical"
    tier_floor: str | None  # None | "mid" | "strong"
    score: int
    reasons: tuple[str, ...] = field(default_factory=tuple)


def count_requirement_ids(text: str) -> int:
    """Distinct FR/NFR/SEC/AC identifiers in upstream artifact text."""
    if not text:
        return 0
    return len({m.upper() for m in _REQUIREMENT_ID_PATTERN.findall(text)})


def _regulated_hits(text: str) -> int:
    return sum(1 for pattern in _REGULATED_PATTERNS if pattern.search(text))


def _ambiguity_markers(text: str) -> int:
    return sum(1 for pattern in _AMBIGUITY_PATTERNS if pattern.search(text))


def classify_complexity(signals: ComplexitySignals) -> ComplexityAssessment:
    """Score a request and map it to a starting-tier floor.

    Pure and deterministic.  Returns ``tier_floor=None`` (keep the cheap primary)
    for the common case; ``"mid"`` for high-complexity requests that would
    predictably burn the cheap attempt; ``"strong"`` for the rare critical request
    (regulated *and* already-failed, or regulated with a large upstream chain).
    """
    score = 0
    reasons: list[str] = []

    problem = signals.problem_statement or ""

    # 1. Regulated / high-stakes domain — the dominant, reliable signal.
    if _regulated_hits(problem) >= 1:
        score += _REGULATED_WEIGHT
        reasons.append("regulated_domain")

    # 2. Problem-statement size (scope proxy).  Tiered, length in characters.
    length = len(problem)
    if length >= 3500:
        score += 2
        reasons.append("very_long_problem")
    elif length >= 1500:
        score += 1
        reasons.append("long_problem")

    # 3. Ambiguity — only for a substantial prompt; a short vague prompt is cheap
    #    clarifying-question work, not a strong-model job.
    if length >= _AMBIGUITY_MIN_LENGTH:
        if _ambiguity_markers(problem) >= _AMBIGUITY_MIN_MARKERS:
            score += _AMBIGUITY_WEIGHT
            reasons.append("ambiguous_long_problem")

    # 4. Upstream integration weight (later stages carry more to reconcile).
    if signals.upstream_artifact_count >= 3:
        score += 2
        reasons.append("many_upstream_artifacts")
    elif signals.upstream_artifact_count >= 2:
        score += 1
        reasons.append("multiple_upstream_artifacts")

    requirement_ids = count_requirement_ids(signals.upstream_artifacts_text)
    if requirement_ids >= 30:
        score += 2
        reasons.append("many_upstream_requirement_ids")
    elif requirement_ids >= 15:
        score += 1
        reasons.append("upstream_requirement_ids")

    # 5. This stage already failed the quality gate on the cheap model — start the
    #    retry higher instead of repeating the failure.
    if signals.prior_quality_gate_blocked:
        score += _PRIOR_GATE_BLOCKED_WEIGHT
        reasons.append("prior_quality_gate_blocked")

    # 6. Stage-type floor: harness/tasks reconcile the most upstream and are the
    #    likeliest to need a stronger model (plan §5.2).
    if signals.stage_type in _HIGHER_FLOOR_STAGES:
        score += _STAGE_BASE_WEIGHT
        reasons.append(f"{signals.stage_type}_stage_floor")

    # 7. Template domain.
    if _template_is_complex(signals.template_slug):
        score += _TEMPLATE_WEIGHT
        reasons.append("complex_template")

    level, tier_floor = _score_to_level(score)
    return ComplexityAssessment(
        level=level,
        tier_floor=tier_floor,
        score=score,
        reasons=tuple(reasons),
    )


def _template_is_complex(slug: str | None) -> bool:
    if not slug:
        return False
    lowered = slug.lower()
    return any(marker in lowered for marker in _COMPLEX_TEMPLATE_MARKERS)


def _score_to_level(score: int) -> tuple[str, str | None]:
    if score >= _CRITICAL_THRESHOLD:
        return "critical", "strong"
    if score >= _HIGH_THRESHOLD:
        return "high", "mid"
    return "normal", None


def raise_tier_to_floor(requested_tier: str, floor: str | None) -> str:
    """Lift ``requested_tier`` up to ``floor`` if the floor is more capable.

    Never lowers a tier (the classifier is a floor, not a ceiling) and is a no-op
    when the request already starts at or above the floor (e.g. Google, whose
    cheap primary is already ``mid``)."""
    if floor is None:
        return requested_tier
    if _TIER_CAPABILITY_RANK.get(floor, 0) <= _TIER_CAPABILITY_RANK.get(
        requested_tier, 0
    ):
        return requested_tier
    return floor
