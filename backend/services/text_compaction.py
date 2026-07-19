from __future__ import annotations

# The elision marker inserted where compact_text drops the middle of a bounded
# text. Judge prompts (critic.py, online_eval.py) DESCRIBE this marker to the
# model so it never reports content as missing when the content could fall
# inside an elided region (prompt-quality audit H4) — if the wording here
# changes, those prompt sentences and their pinned tests must move with it.
ELISION_MARKER_PHRASE = "characters omitted for"


def compact_text(value: str, limit: int, *, reason: str = "eval budget") -> str:
    """Head/tail-truncate ``value`` to at most ``limit`` chars, marking the gap.

    Keeps the start (usually headings/overview) and the end (usually the most
    recently written content) and drops the middle, rather than a naive
    head-only cut, so a judge prompt stays informative at both ends of a large
    artifact. ``limit <= 0`` means "no bound" (returns ``value`` unchanged) —
    used by callers that only bound one of two interpolated values.

    ``reason`` names the budget in the elision marker (default preserves the
    historical judge-prompt wording byte-for-byte; generation-context callers
    pass e.g. ``"context budget"``).
    """
    if limit <= 0 or len(value) <= limit:
        return value
    head = max(0, int(limit * 0.65))
    tail = max(0, limit - head)
    omitted = len(value) - head - tail
    return (
        value[:head].rstrip()
        + f"\n\n[... {omitted} {ELISION_MARKER_PHRASE} {reason} ...]\n\n"
        + value[-tail:].lstrip()
    )
