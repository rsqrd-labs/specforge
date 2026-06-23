from __future__ import annotations

import pytest

from services.llm.usage import estimate_tokens
from services.pipeline import problem_compressor as pc
from services.pipeline.problem_compressor import (
    _is_normative_line,
    _rung1_cleanup,
    _rung3_clamp,
    _truncate_to_tokens,
    compress_problem_statement,
    get_or_compress,
    problem_budget,
)

PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"


def _tok(text: str) -> int:
    return estimate_tokens(PROVIDER, MODEL, text) or 0


# --------------------------------------------------------------------------- #
# Rung 0 — no-op / byte-identical (the regression pin)
# --------------------------------------------------------------------------- #


def test_rung0_under_budget_is_byte_identical() -> None:
    raw = "Build a todo app. FR-001: users must authenticate to save tasks."
    text, rung = compress_problem_statement(
        raw, budget=8000, provider=PROVIDER, model=MODEL
    )
    assert rung == "0"
    assert text == raw  # byte-for-byte


def test_rung0_at_exact_budget_boundary_is_noop() -> None:
    raw = "x" * 400  # 400 bytes ≈ 101 tokens
    budget = _tok(raw)
    text, rung = compress_problem_statement(
        raw, budget=budget, provider=PROVIDER, model=MODEL
    )
    assert rung == "0"
    assert text == raw


# --------------------------------------------------------------------------- #
# Rung 1 — lossless structural cleanup
# --------------------------------------------------------------------------- #


def test_rung1_collapses_blank_runs_and_internal_spaces() -> None:
    raw = "Para one.\n\n\n\nThe    team    needs    a    CRM."
    cleaned = _rung1_cleanup(raw)
    assert "\n\n\n" not in cleaned
    assert "team    needs" not in cleaned
    assert "team needs a CRM." in cleaned


def test_rung1_drops_page_footers_and_signatures() -> None:
    raw = "Real content here.\n\nPage 3 of 9\n\nSent from my iPhone\n\nMore content."
    cleaned = _rung1_cleanup(raw)
    assert "Page 3 of 9" not in cleaned
    assert "Sent from my iPhone" not in cleaned
    assert "Real content here." in cleaned
    assert "More content." in cleaned


def test_rung1_dedupes_exact_duplicate_paragraphs() -> None:
    para = "The sales team tracks leads through the pipeline."
    raw = f"{para}\n\n{para}\n\n{para}"
    cleaned = _rung1_cleanup(raw)
    assert cleaned.count(para) == 1


def test_rung1_never_drops_normative_lines_even_if_duplicated() -> None:
    norm = "- FR-010: the system must record every lead source."
    raw = f"{norm}\n\n{norm}\n\nPage 1 of 2"
    cleaned = _rung1_cleanup(raw)
    # Both normative copies survive (dedup must not eat requirements); footer goes.
    assert cleaned.count("FR-010") == 2
    assert "Page 1 of 2" not in cleaned


def test_rung1_preserves_fenced_code_blocks_verbatim() -> None:
    raw = "Intro.\n\n```\ndef f():\n    x   =   1\n    return x\n```\n\nOutro."
    cleaned = _rung1_cleanup(raw)
    assert "    x   =   1" in cleaned  # internal spaces inside the fence untouched
    assert "    return x" in cleaned


def test_rung1_preserves_table_rows() -> None:
    raw = (
        "Heading.\n\n| Col A   | Col B   |\n"
        "| ------- | ------- |\n| 1       | 2       |"
    )
    cleaned = _rung1_cleanup(raw)
    assert "| Col A   | Col B   |" in cleaned  # table spacing is meaningful


# --------------------------------------------------------------------------- #
# normative detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line",
    [
        "FR-001: do the thing",
        "The system must persist data",
        "- a bullet item",
        "1. a numbered item",
        "| a | table |",
        "SEC-007 shall apply",
    ],
)
def test_normative_lines_detected(line: str) -> None:
    assert _is_normative_line(line) is True


@pytest.mark.parametrize(
    "line",
    ["just some background prose", "we have thought about this for years", ""],
)
def test_non_normative_lines(line: str) -> None:
    assert _is_normative_line(line) is False


# --------------------------------------------------------------------------- #
# Rung 3 — deterministic normative-first clamp
# --------------------------------------------------------------------------- #


def test_rung3_terminates_under_budget() -> None:
    raw = "narrative paragraph. " * 2000  # ~10K tokens
    budget = 200
    clamped = _rung3_clamp(raw, budget, PROVIDER, MODEL)
    assert _tok(clamped) <= budget


def test_rung3_keeps_normative_first_drops_narrative() -> None:
    narrative = "Background prose with no requirement. " * 300  # huge
    norms = "\n".join(f"- FR-{n:03d}: must do thing {n}." for n in range(1, 11))
    raw = f"{narrative}\n\n{norms}"
    budget = 300
    clamped = _rung3_clamp(raw, budget, PROVIDER, MODEL)
    assert _tok(clamped) <= budget
    for n in range(1, 11):
        assert f"FR-{n:03d}" in clamped  # every requirement retained
    # narrative is mostly gone (at most a sliver fits the leftover budget)
    assert clamped.count("Background prose") <= 2


def test_rung3_oversized_normative_keeps_earliest_in_order() -> None:
    norms = "\n".join(
        f"- SEC-{n:03d}: the platform shall mitigate threat {n} fully."
        for n in range(1, 81)
    )
    budget = 150
    clamped = _rung3_clamp(norms, budget, PROVIDER, MODEL)
    assert _tok(clamped) <= budget
    assert "SEC-001" in clamped  # earliest survives
    assert "SEC-080" not in clamped  # latest clamped — graceful degradation


# --------------------------------------------------------------------------- #
# _truncate_to_tokens — boundary safety
# --------------------------------------------------------------------------- #


def test_truncate_respects_budget() -> None:
    text = "word " * 1000
    out = _truncate_to_tokens(text, 50, PROVIDER, MODEL)
    assert _tok(out) <= 50


def test_truncate_snaps_to_newline_not_mid_id() -> None:
    text = "- FR-001: alpha\n- FR-002: bravo\n- FR-003: charlie\n- FR-004: delta"
    out = _truncate_to_tokens(text, 8, PROVIDER, MODEL)
    # No half-line: every retained line is whole (no dangling 'FR-0').
    for line in out.splitlines():
        assert not line.endswith("FR-0")
        assert "\n" not in line


def test_truncate_zero_budget_is_empty() -> None:
    assert _truncate_to_tokens("anything", 0, PROVIDER, MODEL) == ""


# --------------------------------------------------------------------------- #
# problem_budget
# --------------------------------------------------------------------------- #


def test_problem_budget_uses_product_knob_on_real_models() -> None:
    # C_MAX (8000 default) is far below the window-fit ceiling, so it wins the min.
    budget = problem_budget(PROVIDER, MODEL)
    assert budget == 8000


def test_problem_budget_unknown_model_falls_back_to_knob() -> None:
    budget = problem_budget("anthropic", "no-such-model")
    assert budget == 8000


def test_problem_budget_window_floor_can_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    # If the product knob is misconfigured huge, the window-fit ceiling clamps it.
    monkeypatch.setattr(pc.settings, "problem_statement_budget_tokens", 10_000_000)
    budget = problem_budget(PROVIDER, MODEL)
    assert budget < 10_000_000
    assert budget > 0


# --------------------------------------------------------------------------- #
# get_or_compress — caching + fail-open
# --------------------------------------------------------------------------- #


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0
        self.sets = 0

    async def get(self, key: str):
        self.gets += 1
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self.sets += 1
        self.store[key] = value


class _BrokenRedis:
    async def get(self, key: str):
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        raise RuntimeError("redis down")


@pytest.mark.asyncio
async def test_get_or_compress_under_budget_skips_redis() -> None:
    redis = _FakeRedis()
    raw = "Build a todo app. FR-001: users must authenticate."
    out = await get_or_compress(raw, 8000, redis, PROVIDER, MODEL)
    assert out == raw
    assert redis.gets == 0 and redis.sets == 0  # fast path never touches cache


@pytest.mark.asyncio
async def test_get_or_compress_caches_result() -> None:
    redis = _FakeRedis()
    raw = "narrative. " * 2000
    first = await get_or_compress(raw, 100, redis, PROVIDER, MODEL)
    assert redis.sets == 1
    assert _tok(first) <= 100
    second = await get_or_compress(raw, 100, redis, PROVIDER, MODEL)
    assert second == first
    assert redis.sets == 1  # served from cache, not recomputed+rewritten


@pytest.mark.asyncio
async def test_get_or_compress_fails_open_on_redis_error() -> None:
    raw = "narrative. " * 2000
    out = await get_or_compress(raw, 100, _BrokenRedis(), PROVIDER, MODEL)
    assert _tok(out) <= 100  # still bounded despite redis being down


@pytest.mark.asyncio
async def test_get_or_compress_fails_open_bounded_on_compressor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a, **_k):
        raise ValueError("compressor blew up")

    monkeypatch.setattr(pc, "compress_problem_statement", _boom)
    raw = "narrative. " * 2000
    out = await get_or_compress(raw, 100, _FakeRedis(), PROVIDER, MODEL)
    # The whole point of the phase: the error path is still bounded, never raw.
    assert _tok(out) <= 100
    assert out != raw


@pytest.mark.asyncio
async def test_get_or_compress_none_input() -> None:
    assert await get_or_compress("", 100, _FakeRedis(), PROVIDER, MODEL) == ""
