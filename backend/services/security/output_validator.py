from __future__ import annotations

import re
from dataclasses import dataclass

_LEAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"ASDD_METHODOLOGY_OVERVIEW", re.I),
    re.compile(r"You are SpecForge", re.I),
    re.compile(r"ASDD \(AI-Spec-Driven Development\)", re.I),
    re.compile(r"Output format requirements:", re.I),
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
