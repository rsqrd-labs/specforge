from __future__ import annotations

import difflib
import logging

logger = logging.getLogger(__name__)


def compute_diff(original: str, proposed: str) -> str:
    original_lines = original.splitlines(keepends=True)
    proposed_lines = proposed.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            original_lines,
            proposed_lines,
            fromfile="original",
            tofile="proposed",
        )
    )


def apply_diff(original: str, start: int, end: int, replacement: str) -> str:
    return original[:start] + replacement + original[end:]
