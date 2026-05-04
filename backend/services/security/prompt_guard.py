from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous\s+)?instructions?", re.I),
    re.compile(r"forget\s+(?:everything|what)\s+you\s+(?:were\s+)?told", re.I),
    re.compile(r"(?:prior|previous|above)\s+rules?\s+no\s+longer\s+apply", re.I),
    re.compile(r"do\s+not\s+obey\s+(?:the\s+)?(?:above|previous)", re.I),
    re.compile(
        r"bypass\s+(?:the\s+)?(?:system|developer|safety)\s+instructions?",
        re.I,
    ),
    re.compile(r"you\s+are\s+now\b", re.I),
    re.compile(r"act\s+as\s+(?:a\s+)?(?:different|unrestricted|uncensored)", re.I),
    re.compile(r"pretend\s+(?:you\s+are|to\s+be)", re.I),
    re.compile(r"jailbreak\b", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"print\s+your\s+system\s+prompt", re.I),
    re.compile(r"output\s+(?:the\s+|your\s+)?system\s+prompt", re.I),
    re.compile(r"reveal\s+your\s+(?:system\s+)?instructions?", re.I),
    re.compile(
        r"show\s+(?:me\s+)?(?:the\s+|your\s+)?"
        r"(?:hidden\s+)?(?:prompt|instructions)",
        re.I,
    ),
    re.compile(r"exfiltrate|leak\s+(?:secrets?|tokens?|keys?|credentials?)", re.I),
    re.compile(r"<\s*system\s*>", re.I),
    re.compile(r"<\s*/?\s*(?:developer|assistant|tool)\s*>", re.I),
    re.compile(r"<\|im_start\|>", re.I),
    re.compile(r"```(?:system|developer|assistant)\b", re.I),
    re.compile(r"aWdub3JlIHByZXZpb3VzIGluc3RydWN0aW9ucw==", re.I),
    re.compile(r"summarize\s+(?:your\s+)?(?:hidden|internal)\s+(?:policy|rules)", re.I),
]


@dataclass
class ScanResult:
    is_safe: bool
    matched_pattern: str | None = None


def scan(text: str) -> ScanResult:
    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            logger.warning(
                "prompt_injection_attempt_detected",
                extra={"pattern": pattern.pattern},
            )
            return ScanResult(is_safe=False, matched_pattern=pattern.pattern)
    return ScanResult(is_safe=True)
