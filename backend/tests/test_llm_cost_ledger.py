"""Phase 0 (issue #26) LLM cost ledger — unit tests.

Covers the three pieces that are hard to change later:
* real provider-reported usage (incl. a reasoning breakout that never inflates
  cost) flowing into the cost event,
* the fire-and-forget DB persist (best-effort, exception-swallowed, gated), and
* the read-side rollup helper's allowlist + aggregation shape.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from config import settings
from services.llm.cost_ledger import (
    LLMCostContext,
    cost_rollup,
    persist_cost_event,
    update_cost_event_quality_outcome,
)
from services.llm.usage import estimate_cost_usd, normalize_provider_usage


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeSession:
    def __init__(self, sink: list, *, raise_on_commit: bool = False) -> None:
        self._sink = sink
        self._raise_on_commit = raise_on_commit
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def add(self, obj) -> None:
        self._sink.append(obj)

    async def execute(self, stmt) -> None:
        self._sink.append(stmt)

    async def commit(self) -> None:
        if self._raise_on_commit:
            raise RuntimeError("db down")
        self.committed = True


def _fake_session_local(sink, **kw):
    return lambda: _FakeSession(sink, **kw)


@pytest.fixture
def _ledger_enabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_cost_ledger_enabled", True, raising=False)


# --------------------------------------------------------------------------- #
# LLMCostContext
# --------------------------------------------------------------------------- #
def test_cost_context_as_metadata_drops_none_fields() -> None:
    ctx = LLMCostContext(workspace_id="w", product_surface="storyboard")
    assert ctx.as_metadata() == {
        "workspace_id": "w",
        "product_surface": "storyboard",
    }


# --------------------------------------------------------------------------- #
# persist_cost_event
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_persist_disabled_is_noop(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_cost_ledger_enabled", False, raising=False)
    sink: list = []
    monkeypatch.setattr("database.AsyncSessionLocal", _fake_session_local(sink))
    await persist_cost_event({"provider": "openai", "model": "gpt-5.4"})
    assert sink == []


@pytest.mark.asyncio
async def test_persist_builds_row_coerces_types_and_ignores_extras(
    monkeypatch, _ledger_enabled
) -> None:
    sink: list = []
    monkeypatch.setattr("database.AsyncSessionLocal", _fake_session_local(sink))
    workspace_id = uuid4()
    await persist_cost_event(
        {
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "operation": "spec.generate",
            "input_tokens": 1200,
            "reasoning_tokens": 300,
            "estimated_cost_usd": 0.0123,
            "workspace_id": str(workspace_id),
            "generation_id": "gen-1",
            # not a column — must be dropped, not crash:
            "provider_usage_raw": {"x": 1},
        }
    )
    assert len(sink) == 1
    row = sink[0]
    assert row.provider == "anthropic"
    assert row.operation == "spec.generate"
    assert row.input_tokens == 1200
    assert row.reasoning_tokens == 300
    assert isinstance(row.estimated_cost_usd, Decimal)
    assert row.workspace_id == workspace_id  # coerced str -> UUID
    assert not hasattr(row, "provider_usage_raw")


@pytest.mark.asyncio
async def test_persist_skips_without_provider_or_model(
    monkeypatch, _ledger_enabled
) -> None:
    sink: list = []
    monkeypatch.setattr("database.AsyncSessionLocal", _fake_session_local(sink))
    await persist_cost_event({"operation": "spec.generate", "input_tokens": 5})
    assert sink == []


@pytest.mark.asyncio
async def test_persist_swallows_db_errors(monkeypatch, _ledger_enabled) -> None:
    sink: list = []
    monkeypatch.setattr(
        "database.AsyncSessionLocal",
        _fake_session_local(sink, raise_on_commit=True),
    )
    # Must not raise.
    await persist_cost_event({"provider": "openai", "model": "gpt-5.4-mini"})


@pytest.mark.asyncio
async def test_quality_outcome_update_noop_without_generation_id(
    monkeypatch, _ledger_enabled
) -> None:
    sink: list = []
    monkeypatch.setattr("database.AsyncSessionLocal", _fake_session_local(sink))
    await update_cost_event_quality_outcome(None, "passed")
    assert sink == []


@pytest.mark.asyncio
async def test_quality_outcome_update_executes(monkeypatch, _ledger_enabled) -> None:
    sink: list = []
    monkeypatch.setattr("database.AsyncSessionLocal", _fake_session_local(sink))
    await update_cost_event_quality_outcome("gen-1", "critic_failed")
    assert len(sink) == 1  # one UPDATE statement executed


# --------------------------------------------------------------------------- #
# cost_rollup
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cost_rollup_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError):
        await cost_rollup(object(), group_by="workspace_id")  # not allowlisted


@pytest.mark.asyncio
async def test_cost_rollup_aggregation_shape() -> None:
    class _Row:
        dimension = "spec.generate"
        calls = 3
        input_tokens = 100
        cached_input_tokens = 10
        cache_write_input_tokens = 20
        output_tokens = 50
        reasoning_tokens = 5
        estimated_cost_usd = Decimal("0.5")

    class _DB:
        async def execute(self, stmt):
            return [_Row()]

    rows = await cost_rollup(_DB(), group_by="operation")
    assert rows == [
        {
            "dimension": "spec.generate",
            "calls": 3,
            "input_tokens": 100,
            "cached_input_tokens": 10,
            "cache_write_input_tokens": 20,
            "output_tokens": 50,
            "reasoning_tokens": 5,
            "estimated_cost_usd": 0.5,
        }
    ]


# --------------------------------------------------------------------------- #
# reasoning_tokens: observability-only, never double-counted into cost
# --------------------------------------------------------------------------- #
def test_openai_reasoning_tokens_extracted_and_not_costed() -> None:
    usage = normalize_provider_usage(
        "openai",
        {
            "prompt_tokens": 1000,
            "completion_tokens": 800,
            "completion_tokens_details": {"reasoning_tokens": 600},
        },
    )
    assert usage.output_tokens == 800
    assert usage.reasoning_tokens == 600

    # Cost uses output_tokens at the output rate; reasoning is already inside it,
    # so two usages that differ ONLY in the reasoning breakout cost the same.
    no_breakout = normalize_provider_usage(
        "openai", {"prompt_tokens": 1000, "completion_tokens": 800}
    )
    assert estimate_cost_usd("openai", "gpt-5.4", usage) == estimate_cost_usd(
        "openai", "gpt-5.4", no_breakout
    )


def test_google_thoughts_are_reasoning_tokens() -> None:
    usage = normalize_provider_usage(
        "google",
        {
            "promptTokenCount": 500,
            "candidatesTokenCount": 300,
            "thoughtsTokenCount": 200,
        },
    )
    # output_tokens folds candidates + thoughts; reasoning breaks thoughts out.
    assert usage.output_tokens == 500
    assert usage.reasoning_tokens == 200


def test_anthropic_has_no_reasoning_breakout() -> None:
    usage = normalize_provider_usage(
        "anthropic", {"input_tokens": 10, "output_tokens": 20}
    )
    assert usage.reasoning_tokens is None


# --------------------------------------------------------------------------- #
# InstrumentedAdapter threads real provider usage + cost context
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_instrumented_adapter_records_provider_usage_and_context(
    monkeypatch,
) -> None:
    from services.llm.completion import LLMCompletionInfo
    from services.llm.instrumented_adapter import InstrumentedAdapter

    class _Wrapped:
        def __init__(self) -> None:
            self.last_completion = LLMCompletionInfo(
                provider="openai",
                model="gpt-5.4-mini",
                max_tokens=1000,
                finish_reason="stop",
                usage={
                    "prompt_tokens": 900,
                    "completion_tokens": 400,
                    "completion_tokens_details": {"reasoning_tokens": 120},
                },
            )

        async def complete(
            self,
            system,
            user,
            max_tokens,
            *,
            cache_system=False,
        ):
            return "ok"

        async def stream(  # pragma: no cover
            self,
            system,
            user,
            max_tokens,
            *,
            cache_system=False,
        ):
            yield "ok"

    captured: dict = {}
    monkeypatch.setattr(
        "services.llm.instrumented_adapter.record_llm_cost_event",
        lambda md: captured.update(md),
    )

    persisted: dict = {}

    async def _fake_persist(md):
        persisted.update(md)

    monkeypatch.setattr(
        "services.llm.instrumented_adapter.persist_cost_event", _fake_persist
    )

    adapter = InstrumentedAdapter(
        _Wrapped(),
        provider="openai",
        model="gpt-5.4-mini",
        stage_type="spec",
        action="generate",
        model_tier="mini",
        operation="spec.generate",
        cost_context=LLMCostContext(
            workspace_id="ws-1", product_surface="stage_generation"
        ),
        retry_count=1,
        repair_count=1,
    )
    out = await adapter.complete("sys", "user", 1000)
    assert out == "ok"

    # Provider-reported usage, not the tokenizer estimate.
    assert captured["usage_estimation_method"] == "provider_reported"
    assert captured["input_tokens"] == 900
    assert captured["output_tokens"] == 400
    assert captured["reasoning_tokens"] == 120
    assert captured["finish_reason"] == "stop"
    assert captured["retry_count"] == 1
    assert captured["repair_count"] == 1
    # Cost context merged in.
    assert captured["product_surface"] == "stage_generation"
    assert captured["workspace_id"] == "ws-1"
    # The persisted row carries the same data plus the (here None) generation id.
    assert persisted["input_tokens"] == 900
    assert "generation_id" in persisted


@pytest.mark.asyncio
async def test_instrumented_adapter_stream_records_provider_usage(monkeypatch) -> None:
    """Generation — the dominant spend — runs through stream(); its cost is
    recorded in the finally after the stream closes."""
    from services.llm.completion import LLMCompletionInfo
    from services.llm.instrumented_adapter import InstrumentedAdapter

    class _Wrapped:
        def __init__(self) -> None:
            self.last_completion = LLMCompletionInfo(
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                max_tokens=24576,
                finish_reason="end_turn",
                usage={"input_tokens": 1500, "output_tokens": 900},
            )

        async def stream(
            self,
            system,
            user,
            max_tokens,
            *,
            cache_system=False,
        ):
            for tok in ("hel", "lo"):
                yield tok

        async def complete(  # pragma: no cover
            self,
            system,
            user,
            max_tokens,
            *,
            cache_system=False,
        ):
            return "x"

    captured: dict = {}
    monkeypatch.setattr(
        "services.llm.instrumented_adapter.record_llm_cost_event",
        lambda md: captured.update(md),
    )
    persisted: dict = {}

    async def _fake_persist(md):
        persisted.update(md)

    monkeypatch.setattr(
        "services.llm.instrumented_adapter.persist_cost_event", _fake_persist
    )

    adapter = InstrumentedAdapter(
        _Wrapped(),
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        stage_type="spec",
        action="generate",
        model_tier="small",
        operation="spec.generate",
        cost_context=LLMCostContext(
            workspace_id="ws-9", stage_id="st-9", product_surface="stage_generation"
        ),
    )

    tokens = [tok async for tok in adapter.stream("sys", "user", 24576)]
    assert tokens == ["hel", "lo"]  # pass-through unchanged

    assert captured["usage_estimation_method"] == "provider_reported"
    assert captured["input_tokens"] == 1500
    assert captured["output_tokens"] == 900
    assert captured["finish_reason"] == "end_turn"
    assert captured["stage_id"] == "st-9"
    assert persisted["output_tokens"] == 900
