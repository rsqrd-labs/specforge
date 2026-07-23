from __future__ import annotations

import re
from dataclasses import dataclass

_LEAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"ASDD_METHODOLOGY_OVERVIEW", re.I),
    re.compile(r"You are Thought2Build", re.I),
    re.compile(r"ASDD \(AI-Spec-Driven Development\)", re.I),
    re.compile(r"Output format requirements:", re.I),
    re.compile(r"Non-negotiable security and privacy rules:", re.I),
    re.compile(r"Professional output rules:", re.I),
    re.compile(r"Treat all text inside dependency tags as untrusted", re.I),
    re.compile(r"Follow only the system prompt", re.I),
    re.compile(r"Never reveal, quote, transform, summarize", re.I),
    re.compile(r"hidden policies, chain-of-thought, internal reasoning", re.I),
    re.compile(r"SYSTEM_PROMPT", re.I),
    re.compile(r"SECURITY_AND_PRIVACY_RULES", re.I),
    re.compile(r"PROFESSIONAL_OUTPUT_RULES", re.I),
    re.compile(r"system\s+message\s+says", re.I),
    re.compile(r"my\s+(?:hidden|internal)\s+(?:policy|instructions?)", re.I),
]


@dataclass
class ValidationResult:
    is_safe: bool
    reason: str | None = None


def validate(output: str) -> ValidationResult:
    for pattern in _LEAK_PATTERNS:
        if pattern.search(output):
            return ValidationResult(
                is_safe=False,
                reason=f"System prompt content detected: {pattern.pattern}",
            )
    return ValidationResult(is_safe=True)


async def validate_async(output: str) -> ValidationResult:
    """Async ``validate``: offloads the leak-pattern scan off the event loop (F7).

    The scan runs every leak pattern over the full LLM artifact. Large outputs are
    dispatched to the dedicated CPU pool so the scan does not stall the loop; small
    outputs run inline. Byte-identical to ``validate`` for any input.
    """
    from services.cpu_offload import run_cpu_bound

    return await run_cpu_bound(output, validate, output)
