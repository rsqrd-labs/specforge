from __future__ import annotations

import difflib
import logging
import re

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^[ \t]{0,3}(```+|~~~+)", re.MULTILINE)
_WRAPPED_FENCE_RE = re.compile(
    r"^\s*(```+|~~~+)[^\n]*\n(?P<body>.*)\n\1\s*$",
    re.DOTALL,
)
_LEADING_SPACE_RE = re.compile(r"^\s+")
_TRAILING_SPACE_RE = re.compile(r"\s+$")


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


async def compute_diff_async(original: str, proposed: str) -> str:
    """Async ``compute_diff``: offloads difflib off the event loop (F7).

    ``difflib.unified_diff`` runs ``SequenceMatcher`` over the two documents; on a
    full-document refine (section/full mode) both sides are large and the diff
    stalls the loop. The larger of the two sides gates the offload; small diffs run
    inline. Byte-identical to ``compute_diff`` for any input.
    """
    from services.cpu_offload import run_cpu_bound

    sizer = original if len(original) >= len(proposed) else proposed
    return await run_cpu_bound(sizer, compute_diff, original, proposed)


def apply_diff(original: str, start: int, end: int, replacement: str) -> str:
    return original[:start] + replacement + original[end:]


def normalize_refine_replacement(selected_text: str, replacement: str) -> str:
    """Normalize an LLM refine replacement without changing user intent.

    Focused refine is applied directly into a Markdown document. Models often
    return helpful-looking wrappers such as ```markdown fences, or they trim the
    leading/trailing whitespace that belonged to the selected range. Either can
    corrupt Markdown when spliced back into the document, so normalize wrappers
    and restore the selected boundary whitespace before applying the patch.
    """
    selected = selected_text.replace("\r\n", "\n").replace("\r", "\n")
    value = replacement.replace("\r\n", "\n").replace("\r", "\n")

    if not _looks_like_wrapped_fenced_selection(selected):
        match = _WRAPPED_FENCE_RE.match(value)
        if match:
            value = match.group("body")

    leading = _LEADING_SPACE_RE.match(selected)
    trailing = _TRAILING_SPACE_RE.search(selected)
    leading_ws = leading.group(0) if leading else ""
    trailing_ws = trailing.group(0) if trailing else ""

    core = value.strip()
    return f"{leading_ws}{core}{trailing_ws}"


def markdown_fences_balanced(content: str) -> bool:
    return len(_FENCE_RE.findall(content)) % 2 == 0


def _looks_like_wrapped_fenced_selection(value: str) -> bool:
    return _WRAPPED_FENCE_RE.match(value.strip()) is not None
