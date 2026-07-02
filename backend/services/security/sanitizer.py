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


async def sanitize_text_async(text: str) -> str:
    """Async ``sanitize_text``: offloads the bleach pass off the event loop (F7).

    ``bleach.clean`` runs html5lib's pure-Python tokenizer over the whole input
    and holds the GIL; on a large LLM artifact / content edit that stalls the
    loop. Large inputs are dispatched to the dedicated CPU pool; small inputs run
    inline (the dispatch round-trip would dominate). Byte-identical to
    ``sanitize_text`` for any input.
    """
    from services.cpu_offload import run_cpu_bound

    return await run_cpu_bound(text, sanitize_text, text)
