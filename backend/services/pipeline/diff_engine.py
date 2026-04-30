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


def apply_diff(original: str, selected_text: str, replacement: str) -> str:
    idx = original.find(selected_text)
    if idx == -1:
        logger.error(
            "apply_diff_selection_not_found",
            extra={"selected_len": len(selected_text)},
        )
        return original
    return original[:idx] + replacement + original[idx + len(selected_text) :]
