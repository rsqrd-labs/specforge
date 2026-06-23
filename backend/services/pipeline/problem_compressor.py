"""Problem-statement compression — the zero-LLM ladder (Phase B).

See ``docs/PROBLEM_STATEMENT_COMPRESSION_PLAN.md``. This module reduces a large
problem statement to at most ``C_MAX`` tokens *before any model sees it*, so per
generation the input is bounded regardless of how big the user's paste was. It is
the other half of the raised input cap (Phase A): **input accepted big, fed
small.**

Phase B implements three of the four rungs — all pure-Python, zero LLM cost:

* **Rung 0 — no-op.** ``est_tokens(raw) <= budget`` ⇒ return the raw statement
  byte-for-byte. This is the common case (every pre-Phase-A input is ≤10K chars ≈
  2.5K tokens, below an 8K budget) and it is a strict regression pin: nothing
  changes for under-budget input, which also preserves provider prompt caching.
* **Rung 1 — lossless structural cleanup.** Collapse blank-line/space runs,
  drop page headers/footers and signature lines, and de-duplicate *exact*
  repeated paragraphs (common in pasted docs and email threads). Conservative by
  construction: it never removes a line that carries requirement meaning (the
  normative regex), never touches fenced code blocks, and never collapses table
  rows — so it cannot change requirements.
* **Rung 3 — deterministic normative-first clamp (the fail-safe floor).** The
  guarantee that the ladder *always* terminates ≤ ``budget`` for any input. Fill
  the budget with normative content first (requirements, IDs, lists, tables,
  must/shall sentences), then narrative, truncating at block/line boundaries.

Rung 2 (the meaning-preserving abstractive LLM pass) is Phase C and is not wired
here; Phase B already delivers *never-fail* + *bounded-cost*, it just isn't yet
meaning-preserving for prose. The ladder skips straight from Rung 1 to Rung 3.

Invariants (plan §4):

* **Never mutate the stored statement.** The result is a derived value cached in
  Redis keyed by ``sha256(raw) + budget + version``; the user's original always
  survives. The cache amortises the work across every call that re-reads the
  statement (spec regens, storyboard, clarifier).
* **Fail open, but stay bounded.** Any compressor error degrades to a bounded
  truncate of the raw input — never to an over-budget value, and never to a
  failed generation.
"""

from __future__ import annotations

import hashlib
import logging
import re

from config import settings
from services.llm.model_catalog import model_entry
from services.llm.output_budget import OUTPUT_TOKEN_BUDGETS
from services.llm.usage import estimate_tokens
from services.observability import record_problem_compression
from services.pipeline.stage_summary_service import _REQ_ID_RE  # reuse: no drift

logger = logging.getLogger(__name__)

# Bumping this invalidates every cached compression once (like a prompt-version
# bump), so a change to the ladder's output never serves a stale cached value.
COMPRESSION_VERSION = "psc-v1"
_CACHE_PREFIX = "psc:"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days — the raw statement is immutable

# Window-fit reliability math (plan §5). The product budget (C_MAX) is always far
# below this on current large-window models, so the `min` is a safety floor that
# guarantees the compressed statement physically fits even if the budget knob is
# misconfigured upward. `_SYSTEM_PROMPT_RESERVE_TOKENS` is a conservative
# allowance for the system prompt, which `build_prompt` assembles separately.
_SAFETY_FRACTION = 0.15
_SYSTEM_PROMPT_RESERVE_TOKENS = 4000

# Normative detection — the load-bearing safety property. A line is normative if
# it carries requirement *meaning*: a requirement ID, a modal obligation, a list
# item, or a table row. Rung 1 never drops one; Rung 3 keeps them first.
_MODAL_RE = re.compile(r"\b(?:must|shall|should|required|mandatory|acceptance)\b", re.I)
_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_FENCE_RE = re.compile(r"^\s*```")

# Conservative structural-noise patterns (Rung 1). Anchored tightly so they only
# match true boilerplate, never prose that merely contains these words.
_PAGE_FOOTER_RE = re.compile(
    r"^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|-\s*\d+\s*-|\d+\s*/\s*\d+)\s*$", re.I
)
_SIG_PHRASE_RE = re.compile(
    r"^\s*(?:sent from my \w+|get outlook for \w+|confidentiality notice:.*)$",
    re.I,
)
_INTERNAL_SPACE_RE = re.compile(r"[ \t]{2,}")


def _estimate(provider: str, model: str, text: str) -> int:
    """``estimate_tokens`` coerced to a non-negative int (None ⇒ 0)."""
    return estimate_tokens(provider, model, text) or 0


def problem_budget(
    provider: str,
    model: str,
    *,
    research_context: str = "",
    clarification_qa: str = "",
    stage_type: str = "spec",
) -> int:
    """Effective per-call token budget for the problem statement.

    ``min(C_MAX, WINDOW_FIT_CEILING)`` (plan §5). On current models C_MAX (the
    product knob) always wins; the window-fit term is the reliability floor that
    keeps the assembled prompt under the model window no matter what.
    """
    target = max(1, settings.problem_statement_budget_tokens)
    try:
        window = model_entry(provider, model).max_context_tokens
    except ValueError:
        # Unknown model: trust the product budget. We cannot derive the window
        # term, and C_MAX would win the `min` anyway on any real model.
        return target
    output_budget = OUTPUT_TOKEN_BUDGETS.get(
        f"{stage_type}.generate", OUTPUT_TOKEN_BUDGETS["spec.generate"]
    )
    safety = int(_SAFETY_FRACTION * window)
    fixed = (
        _SYSTEM_PROMPT_RESERVE_TOKENS
        + _estimate(provider, model, research_context)
        + _estimate(provider, model, clarification_qa)
    )
    window_fit_ceiling = window - output_budget - safety - fixed
    return max(1, min(target, window_fit_ceiling))


def _is_normative_line(line: str) -> bool:
    if "|" in line:  # markdown table row
        return True
    if _LIST_RE.match(line):
        return True
    if _REQ_ID_RE.search(line):
        return True
    return bool(_MODAL_RE.search(line))


def _is_normative_block(block: str) -> bool:
    return any(_is_normative_line(line) for line in block.splitlines())


def _split_blocks(text: str) -> list[str]:
    """Split into blank-line-separated blocks, fence-aware.

    A fenced code block is one atomic block (never split on blank lines inside a
    fence). Blank-line runs are collapsed for free — blanks just flush the current
    block and never become empty blocks. Used by both Rung 1 (dedup) and Rung 3
    (normative-first assembly), so the two rungs share one notion of a "block".
    """
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current.append(line)
            continue
        if in_fence:
            current.append(line)
            continue
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _collapse_internal_spaces(line: str) -> str:
    """Collapse internal space/tab runs but preserve leading indentation.

    Leading whitespace can carry markdown list/quote nesting; only runs *after*
    the first non-space char are pasted-column / justified-text noise.
    """
    stripped = line.lstrip(" \t")
    lead = line[: len(line) - len(stripped)]
    return lead + _INTERNAL_SPACE_RE.sub(" ", stripped)


def _rung1_cleanup(text: str) -> str:
    """Lossless structural cleanup. Never alters normative or fenced content."""
    kept: list[str] = []
    in_fence = False
    for raw_line in text.split("\n"):
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            kept.append(raw_line)
            continue
        if in_fence:
            kept.append(raw_line)
            continue
        if _is_normative_line(raw_line):
            kept.append(raw_line)  # untouched — meaning is load-bearing
            continue
        line = raw_line.replace("\f", "")
        if _PAGE_FOOTER_RE.match(line) or _SIG_PHRASE_RE.match(line):
            continue  # drop boilerplate
        if "|" not in line:  # table rows already short-circuit above; belt + braces
            line = _collapse_internal_spaces(line)
        kept.append(line)

    # Block level: collapse blank runs (free in _split_blocks) and drop exact
    # duplicate paragraphs, keeping the first occurrence. A normative block is
    # never dropped even if duplicated.
    seen: set[str] = set()
    out_blocks: list[str] = []
    for block in _split_blocks("\n".join(kept)):
        key = block.strip()
        if key in seen and not _is_normative_block(block):
            continue
        seen.add(key)
        out_blocks.append(block)
    return "\n\n".join(out_blocks)


def _truncate_to_tokens(text: str, budget: int, provider: str, model: str) -> str:
    """Longest boundary-aligned prefix of ``text`` that fits ``budget`` tokens.

    Binary search on the character prefix (``estimate_tokens`` is monotonic in
    length), then snap back to the last newline — or, failing that, the last
    space — so a cut never lands mid-line or mid-identifier (``FR-001`` → ``FR-0``).
    """
    if budget <= 0 or not text:
        return ""
    if _estimate(provider, model, text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _estimate(provider, model, text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    truncated = text[:lo]
    newline = truncated.rfind("\n")
    if newline > 0:
        truncated = truncated[:newline]
    else:
        space = truncated.rfind(" ")
        if space > 0:
            truncated = truncated[:space]
    return truncated.rstrip()


def _rung3_clamp(text: str, budget: int, provider: str, model: str) -> str:
    """Deterministic normative-first clamp — the fail-safe floor.

    Two ordered passes over the document's blocks so the result preserves
    document order while prioritising what must survive:

    1. Reserve every normative block (requirements, IDs, lists, tables,
       must/shall) in order until the budget is spent; the one block that
       overflows is itself boundary-truncated to fill the remainder.
    2. Fill any leftover budget with narrative blocks, in order.

    A final ``_truncate_to_tokens`` is the hard guarantee (block separators can
    nudge the join over budget). Cannot raise — every step is total.
    """
    blocks = _split_blocks(text)
    selected: list[str | None] = [None] * len(blocks)
    remaining = budget

    for i, block in enumerate(blocks):
        if not _is_normative_block(block):
            continue
        cost = _estimate(provider, model, block)
        if cost <= remaining:
            selected[i] = block
            remaining -= cost
        elif remaining > 0:
            selected[i] = _truncate_to_tokens(block, remaining, provider, model)
            remaining = 0  # budget exhausted by this normative block

    for i, block in enumerate(blocks):
        if selected[i] is not None or _is_normative_block(block):
            continue
        cost = _estimate(provider, model, block)
        if cost <= remaining:
            selected[i] = block
            remaining -= cost

    assembled = "\n\n".join(block for block in selected if block)
    return _truncate_to_tokens(assembled, budget, provider, model)


def compress_problem_statement(
    raw: str, budget: int, provider: str, model: str
) -> tuple[str, str]:
    """Run the pure ladder. Returns ``(compressed_text, rung_label)``.

    Guarantees ``est_tokens(result) <= budget`` for any input. Pure and
    synchronous — no Redis, no I/O — so it is trivially unit-testable and the
    cache wrapper owns all the fail-open concerns.
    """
    if _estimate(provider, model, raw) <= budget:
        return raw, "0"

    cleaned = _rung1_cleanup(raw)
    if _estimate(provider, model, cleaned) <= budget:
        return cleaned, "1"

    # Rung 2 (abstractive) is Phase C; skip straight to the deterministic floor.
    return _rung3_clamp(cleaned, budget, provider, model), "3"


def _cache_key(raw: str, budget: int) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{_CACHE_PREFIX}{COMPRESSION_VERSION}:{budget}:{digest}"


async def get_or_compress(
    raw: str, budget: int, redis, provider: str, model: str
) -> str:
    """Cached, fail-open entry point. Returns a statement ≤ ``budget`` tokens.

    The shared helper for all consumers (spec/plan/harness/tasks via
    ``build_prompt``, the clarifier, and the storyboard) so the single
    compression result is reused, not recomputed per surface.

    * Rung-0 fast path returns the raw value byte-for-byte without touching Redis
      — the common case stays a zero-cost no-op and preserves prompt caching.
    * Redis errors are swallowed (compute fresh / skip the write).
    * A compressor exception degrades to a *bounded* truncate of the raw input,
      never to an over-budget value (the bounded-cost invariant must hold even on
      the error path) and never to a failed generation.
    """
    if not raw or _estimate(provider, model, raw) <= budget:
        return raw

    key = _cache_key(raw, budget)
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached is not None:
                return (
                    cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
                )
        except Exception:  # noqa: BLE001 — cache is best-effort; never block on it
            logger.warning("problem_compression_cache_read_failed", exc_info=True)

    try:
        text, rung = compress_problem_statement(raw, budget, provider, model)
        record_problem_compression(rung)
    except Exception:  # noqa: BLE001 — fail open, but stay bounded (plan §4)
        logger.warning("problem_compression_failed_failing_open", exc_info=True)
        record_problem_compression("error")
        text = _truncate_to_tokens(raw, budget, provider, model)

    if redis is not None:
        try:
            await redis.set(key, text, ex=_CACHE_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            logger.warning("problem_compression_cache_write_failed", exc_info=True)

    return text
