from __future__ import annotations

import asyncio

import pytest

from services.llm.usage import estimate_tokens
from services.pipeline import problem_compressor as pc
from services.pipeline.problem_compressor import (
    _is_normative_line,
    _rung1_cleanup,
    _rung3_clamp,
    _truncate_to_tokens,
    classify_compression_rung,
    compress_problem_statement,
    get_or_compress,
    normative_retention,
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


# --------------------------------------------------------------------------- #
# Rung 2 — meaning-preserving abstractive pass (Phase C)
# --------------------------------------------------------------------------- #


class _FakeJudge:
    """Stub for ``pc.call_judge_model`` — records calls, returns a canned summary.

    The whole point of Rung 2's tests: drive the LLM path *deterministically* so
    we assert the structural contract (normative kept verbatim, budget honoured,
    fail-open) without a live, flaky judge model.
    """

    def __init__(
        self, summary: str = "Condensed narrative.", *, sleep: float = 0.0, error=None
    ) -> None:
        self.summary = summary
        self.sleep = sleep
        self.error = error
        self.calls: list[str] = []

    async def __call__(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        provider=None,
        max_tokens: int = 2048,
        operation: str = "judge.call",
        stage_type: str = "-",
        cost_context=None,
    ) -> str:
        self.calls.append(operation)
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.error is not None:
            raise self.error
        return self.summary


def _enable_abstractive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc.settings, "problem_statement_compression", True)
    monkeypatch.setattr(pc.settings, "problem_statement_abstractive", True)


# A small verbatim normative block + a large narrative block. The narrative
# dominates so Rung 2 is actually exercised (every Phase-B golden case is
# normative-heavy ⇒ no narrative room ⇒ the floor, never the model).
_NORMS = "\n".join(f"- FR-{n:03d}: the system must do thing {n}." for n in range(1, 6))
_NARRATIVE = "Background prose with rationale, history, and market context. " * 200
_MIXED = f"{_NORMS}\n\n{_NARRATIVE}"


@pytest.mark.asyncio
async def test_rung2_flag_off_never_calls_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pc.settings, "problem_statement_compression", True)
    monkeypatch.setattr(pc.settings, "problem_statement_abstractive", False)
    judge = _FakeJudge(error=AssertionError("judge must not be called when flag off"))
    monkeypatch.setattr(pc, "call_judge_model", judge)
    out = await get_or_compress(_MIXED, 400, _FakeRedis(), PROVIDER, MODEL)
    assert judge.calls == []  # deterministic floor only
    assert _tok(out) <= 400


@pytest.mark.asyncio
async def test_rung2_compresses_narrative_keeps_normative_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    judge = _FakeJudge("CONDENSED SUMMARY OF BACKGROUND.")
    monkeypatch.setattr(pc, "call_judge_model", judge)

    text, rung = await pc._compress(_MIXED, 400, PROVIDER, MODEL, None)

    assert rung == "2"
    assert judge.calls == ["problem_compression.map"]  # one chunk ⇒ one call
    assert _tok(text) <= 400
    for n in range(1, 6):  # every requirement kept verbatim
        assert f"FR-{n:03d}" in text
    assert "CONDENSED SUMMARY OF BACKGROUND." in text
    assert "Background prose with rationale" not in text  # narrative was condensed


@pytest.mark.asyncio
async def test_rung2_normative_retention_is_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge())
    out = await get_or_compress(_MIXED, 400, _FakeRedis(), PROVIDER, MODEL)
    retained, total = normative_retention(_MIXED, out)
    assert total == 5
    assert retained == total  # ~100% — the promotion-gate invariant, by construction


@pytest.mark.asyncio
async def test_rung2_fails_open_to_rung3_on_judge_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    judge = _FakeJudge(error=RuntimeError("provider 500"))
    monkeypatch.setattr(pc, "call_judge_model", judge)

    text, rung = await pc._compress(_MIXED, 400, PROVIDER, MODEL, None)

    assert rung == "3"  # fell open to the deterministic floor
    assert _tok(text) <= 400
    for n in range(1, 6):  # the floor is normative-first ⇒ requirements survive
        assert f"FR-{n:03d}" in text


@pytest.mark.asyncio
async def test_rung2_fails_open_to_rung3_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(
        pc.settings, "problem_statement_abstractive_timeout_seconds", 0.05
    )
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge(sleep=5.0))

    text, rung = await pc._compress(_MIXED, 400, PROVIDER, MODEL, None)

    assert rung == "3"
    assert _tok(text) <= 400


@pytest.mark.asyncio
async def test_rung2_all_normative_returns_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    judge = _FakeJudge(error=AssertionError("no narrative ⇒ judge must not be called"))
    monkeypatch.setattr(pc, "call_judge_model", judge)
    norms = "\n".join(
        f"- SEC-{n:03d}: the platform shall mitigate {n}." for n in range(1, 81)
    )

    text, rung = await pc._compress(norms, 150, PROVIDER, MODEL, None)

    assert rung == "3"  # no narrative to abstract ⇒ deterministic clamp
    assert judge.calls == []
    assert _tok(text) <= 150
    assert "SEC-001" in text


@pytest.mark.asyncio
async def test_rung2_over_chunk_cap_falls_to_rung3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "_RUNG2_MAX_CHUNKS", 1)  # narrative needs >1 chunk
    judge = _FakeJudge(error=AssertionError("over cap ⇒ judge must not be called"))
    monkeypatch.setattr(pc, "call_judge_model", judge)
    big_narrative = "word " * 6000  # ~30K chars ⇒ 2 chunks at the 4000-token window

    text, rung = await pc._compress(big_narrative, 1000, PROVIDER, MODEL, None)

    assert rung == "3"  # over the compressor's own input cap ⇒ floor (bounded cost)
    assert judge.calls == []
    assert _tok(text) <= 1000


@pytest.mark.asyncio
async def test_rung2_multichunk_runs_reduce_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "_RUNG2_CHUNK_TOKENS", 200)  # ~800-char chunks
    # Each map summary is large enough that the concatenation overflows the
    # narrative budget, forcing exactly one reduce pass.
    monkeypatch.setattr(pc, "call_judge_model", judge := _FakeJudge("filler " * 60))
    # Newlines so the chunk splitter snaps to a boundary rather than mid-window.
    narrative = "alpha beta gamma delta epsilon zeta.\n" * 120  # several chunks

    text, rung = await pc._compress(narrative, 300, PROVIDER, MODEL, None)

    assert rung == "2"
    assert judge.calls.count("problem_compression.map") >= 2  # mapped each chunk
    assert judge.calls.count("problem_compression.reduce") == 1  # one bounded reduce
    assert _tok(text) <= 300


@pytest.mark.asyncio
async def test_rung2_multichunk_skips_reduce_when_combined_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "_RUNG2_CHUNK_TOKENS", 200)  # force multiple chunks
    monkeypatch.setattr(pc, "call_judge_model", judge := _FakeJudge("tiny."))
    narrative = "alpha beta gamma delta epsilon zeta.\n" * 120

    text, rung = await pc._compress(narrative, 600, PROVIDER, MODEL, None)

    assert rung == "2"
    assert judge.calls.count("problem_compression.map") >= 2
    assert judge.calls.count("problem_compression.reduce") == 0  # combined already fit
    assert _tok(text) <= 600


@pytest.mark.asyncio
async def test_rung2_no_narrative_room_falls_to_rung3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Normative (nearly) fills the whole budget ⇒ no room for a useful summary ⇒
    # the deterministic floor is the better tool, judge is never called.
    _enable_abstractive(monkeypatch)
    judge = _FakeJudge(error=AssertionError("no narrative room ⇒ judge must not run"))
    monkeypatch.setattr(pc, "call_judge_model", judge)
    norms = "\n".join(
        f"- FR-{n:03d}: the system must do thing {n}." for n in range(1, 60)
    )
    raw = f"{norms}\n\nSome trailing narrative prose that cannot fit."

    text, rung = await pc._compress(raw, 120, PROVIDER, MODEL, None)

    assert rung == "3"
    assert judge.calls == []
    assert _tok(text) <= 120


@pytest.mark.asyncio
async def test_rung2_empty_judge_output_falls_to_rung3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge("   "))  # blank summary

    text, rung = await pc._compress(_MIXED, 400, PROVIDER, MODEL, None)

    assert rung == "3"  # empty/garbled judge output ⇒ floor
    assert _tok(text) <= 400
    for n in range(1, 6):
        assert f"FR-{n:03d}" in text


@pytest.mark.asyncio
async def test_rung2_multichunk_judge_error_falls_open_to_rung3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A chunk error must fall the whole pass open to the floor, not surface — the
    # parallel-map branch re-raises so siblings don't run detached.
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "_RUNG2_CHUNK_TOKENS", 200)  # force multiple chunks
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge(error=RuntimeError("503")))
    narrative = "alpha beta gamma delta epsilon zeta. " * 120

    text, rung = await pc._compress(narrative, 300, PROVIDER, MODEL, None)

    assert rung == "3"
    assert _tok(text) <= 300


@pytest.mark.asyncio
async def test_cache_key_separates_abstractive_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pc.settings, "problem_statement_compression", True)
    redis = _FakeRedis()

    # Flag off: deterministic floor cached under the "a0" mode key.
    monkeypatch.setattr(pc.settings, "problem_statement_abstractive", False)
    off = await get_or_compress(_MIXED, 400, redis, PROVIDER, MODEL)

    # Flip on with a working judge: must NOT serve the a0-cached floor; recompute.
    monkeypatch.setattr(pc.settings, "problem_statement_abstractive", True)
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge("ABSTRACTIVE."))
    on = await get_or_compress(_MIXED, 400, redis, PROVIDER, MODEL)

    assert "ABSTRACTIVE." in on
    assert on != off  # the two modes are isolated in the cache
    assert len([k for k in redis.store if ":a0:" in k]) == 1
    assert len([k for k in redis.store if ":a1:" in k]) == 1


@pytest.mark.asyncio
async def test_rung2_degraded_result_cached_with_short_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge(error=RuntimeError("down")))
    redis = _CapturingRedis()

    await get_or_compress(_MIXED, 400, redis, PROVIDER, MODEL)

    # Fell open to the floor ⇒ cached briefly so a transient outage self-heals.
    assert redis.last_ex == pc._CACHE_TTL_DEGRADED_SECONDS


@pytest.mark.asyncio
async def test_non_degraded_result_cached_with_full_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_abstractive(monkeypatch)
    monkeypatch.setattr(pc, "call_judge_model", _FakeJudge("OK."))
    redis = _CapturingRedis()

    await get_or_compress(_MIXED, 400, redis, PROVIDER, MODEL)

    assert redis.last_ex == pc._CACHE_TTL_SECONDS


class _CapturingRedis(_FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.last_ex: int | None = None

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self.last_ex = ex
        await super().set(key, value, ex=ex)


# --------------------------------------------------------------------------- #
# classify_compression_rung — pure, cache-hit-safe rung recovery (Phase D)
# --------------------------------------------------------------------------- #


def test_classify_rung0_when_unchanged() -> None:
    raw = "Build a todo app. FR-001: users must authenticate."
    assert classify_compression_rung(raw, raw, 8000, PROVIDER, MODEL) == "0"


def test_classify_rung1_when_lossless_cleanup() -> None:
    # A statement that only needs whitespace/comment cleanup to fit budget.
    raw = "FR-001: must auth.\n\n\n\n   \n\nBackground.   \n\n"
    cleaned = _rung1_cleanup(raw)
    assert cleaned != raw  # cleanup changed it
    assert classify_compression_rung(raw, cleaned, 8000, PROVIDER, MODEL) == "1"


def test_classify_rung3_matches_deterministic_clamp() -> None:
    budget = 200
    cleaned = _rung1_cleanup(_MIXED)
    clamped = _rung3_clamp(cleaned, budget, PROVIDER, MODEL)
    assert classify_compression_rung(_MIXED, clamped, budget, PROVIDER, MODEL) == "3"


def test_classify_rung2_for_any_other_over_budget_text() -> None:
    # An abstractive summary equals neither raw, nor the cleanup, nor the clamp,
    # so it is classified as the (lossy) abstractive rung.
    budget = 200
    summary = f"{_NORMS}\n\nA faithful one-line condensation of the narrative."
    assert classify_compression_rung(_MIXED, summary, budget, PROVIDER, MODEL) == "2"


def test_classify_matches_pure_ladder_rung() -> None:
    # The classifier re-derives exactly the rung the pure ladder reports.
    for raw, budget in [
        ("Small. FR-001 must auth.", 8000),
        (_MIXED, 200),
    ]:
        text, rung = compress_problem_statement(raw, budget, PROVIDER, MODEL)
        assert classify_compression_rung(raw, text, budget, PROVIDER, MODEL) == rung
