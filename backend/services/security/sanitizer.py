from __future__ import annotations

import re

import bleach

_SCRIPT_OR_STYLE_BLOCK = re.compile(
    r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_text(text: str) -> str:
    without_executable_blocks = _SCRIPT_OR_STYLE_BLOCK.sub("", text)
    return bleach.clean(without_executable_blocks, tags=[], attributes={}, strip=True)
