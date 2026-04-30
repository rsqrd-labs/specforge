from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous\s+)?instructions?", re.I),
    re.compile(r"you\s+are\s+now\b", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"print\s+your\s+system\s+prompt", re.I),
    re.compile(r"reveal\s+your\s+(?:system\s+)?instructions?", re.I),
    re.compile(r"<\s*system\s*>", re.I),
    re.compile(r"<\|im_start\|>", re.I),
]


@dataclass
class ScanResult:
    is_safe: bool
    matched_pattern: str | None = None


def scan(text: str) -> ScanResult:
    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            excerpt = text[:100].replace("\n", " ")
            logger.warning(
                "prompt_injection_attempt_detected",
                extra={"pattern": pattern.pattern, "excerpt": excerpt},
            )
            return ScanResult(is_safe=False, matched_pattern=pattern.pattern)
    return ScanResult(is_safe=True)
