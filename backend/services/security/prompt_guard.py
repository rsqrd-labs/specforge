from __future__ import annotations

import base64
import binascii
import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote

logger = logging.getLogger(__name__)

_MAX_DECODED_BYTES = 4096
_BASE64_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/]{16,}={0,2}\b")
_ZERO_WIDTH_CHARS = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
}

_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous\s+)?instructions?", re.I),
    re.compile(r"disregard\s+(?:the\s+)?system\s+prompt", re.I),
    re.compile(
        r"override\s+(?:the\s+)?(?:system|developer)\s+" r"(?:prompt|instructions?)",
        re.I,
    ),
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
    re.compile(r"developer\s+mode\b", re.I),
    re.compile(r"DAN\s+mode\b", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"role\s*:\s*(?:system|developer|tool|assistant)", re.I),
    re.compile(r"print\s+your\s+system\s+prompt", re.I),
    re.compile(r"output\s+(?:the\s+|your\s+)?system\s+prompt", re.I),
    re.compile(r"reveal\s+your\s+(?:system\s+)?instructions?", re.I),
    re.compile(
        r"show\s+(?:me\s+)?(?:the\s+|your\s+)?"
        r"(?:hidden\s+)?(?:prompt|instructions)",
        re.I,
    ),
    re.compile(r"exfiltrate|leak\s+(?:secrets?|tokens?|keys?|credentials?)", re.I),
    re.compile(
        r"(?:api[_ -]?keys?|tokens?|credentials?)\s+(?:from|in)\s+"
        r"(?:memory|environment|env)",
        re.I,
    ),
    re.compile(r"<\s*system\s*>", re.I),
    re.compile(r"<\s*/?\s*(?:developer|assistant|tool)\s*>", re.I),
    re.compile(r"<\|im_start\|>", re.I),
    re.compile(r"<\|system\|>", re.I),
    re.compile(r"```(?:system|developer|assistant)\b", re.I),
    re.compile(r"aWdub3JlIHByZXZpb3VzIGluc3RydWN0aW9ucw==", re.I),
    re.compile(r"aWdub3JlIGFsbCBwcmV2aW91cyBpbnN0cnVjdGlvbnM=", re.I),
    re.compile(r"summarize\s+(?:your\s+)?(?:hidden|internal)\s+(?:policy|rules)", re.I),
]


@dataclass
class ScanResult:
    is_safe: bool
    matched_pattern: str | None = None


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    without_zero_width = "".join(
        "" if char in _ZERO_WIDTH_CHARS else char for char in normalized
    )
    return re.sub(r"\s+", " ", without_zero_width)


def _decode_percent(text: str) -> str:
    decoded = text
    for _ in range(2):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _decode_base64_token(token: str) -> str | None:
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded_bytes = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return None

    if not decoded_bytes or len(decoded_bytes) > _MAX_DECODED_BYTES:
        return None

    try:
        decoded = decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if not decoded.isprintable():
        return None
    return decoded


def _scan_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    add(text)
    add(_normalize(text))
    add(_normalize(html.unescape(text)))
    add(_normalize(_decode_percent(text)))
    add(_normalize(_decode_percent(html.unescape(text))))

    for candidate in list(candidates):
        for token in _BASE64_TOKEN_RE.findall(candidate):
            decoded = _decode_base64_token(token)
            if decoded is not None:
                add(_normalize(decoded))

    return candidates


def scan(text: str) -> ScanResult:
    for candidate in _scan_candidates(text):
        for pattern in _PATTERNS:
            match = pattern.search(candidate)
            if match:
                logger.warning(
                    "prompt_injection_attempt_detected",
                    extra={"pattern": pattern.pattern},
                )
                return ScanResult(is_safe=False, matched_pattern=pattern.pattern)
    return ScanResult(is_safe=True)


class PromptGuard:
    def scan(self, text: str) -> ScanResult:
        return scan(text)

    def is_safe(self, text: str) -> bool:
        return self.scan(text).is_safe
