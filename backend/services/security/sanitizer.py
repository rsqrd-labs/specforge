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


# A generated stage artifact excerpt spliced into a file a *different* AI coding
# agent (Claude Code, Codex, ...) auto-loads as high-trust project instructions
# (CLAUDE.md / AGENTS.md) is a cross-agent trust escalation: without this gate,
# an HTML comment or script-like payload smuggled through an upstream artifact
# would land, unsanitized, in a file the receiving agent treats as authoritative
# (audit finding #3). Both downstream-agent-artifact builders
# (agents_md_builder.py, agent_manual_service.py) call this single function so
# they cannot drift back apart — it is intentionally just ``sanitize_text``
# under a name that documents *why* the call site sanitizes.
sanitize_downstream_agent_content = sanitize_text
