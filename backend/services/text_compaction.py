from __future__ import annotations


def compact_text(value: str, limit: int) -> str:
    """Head/tail-truncate ``value`` to at most ``limit`` chars, marking the gap.

    Keeps the start (usually headings/overview) and the end (usually the most
    recently written content) and drops the middle, rather than a naive
    head-only cut, so a judge prompt stays informative at both ends of a large
    artifact. ``limit <= 0`` means "no bound" (returns ``value`` unchanged) —
    used by callers that only bound one of two interpolated values.
    """
    if limit <= 0 or len(value) <= limit:
        return value
    head = max(0, int(limit * 0.65))
    tail = max(0, limit - head)
    omitted = len(value) - head - tail
    return (
        value[:head].rstrip()
        + f"\n\n[... {omitted} characters omitted for eval budget ...]\n\n"
        + value[-tail:].lstrip()
    )
