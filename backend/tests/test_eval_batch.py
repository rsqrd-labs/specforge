from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from models import LLMBatchJob
from services.evals import eval_batch
from services.llm.base import (
    BaseLLMAdapter,
    BatchRequest,
    BatchResultItem,
    BatchUnsupportedError,
)
from services.llm.usage import NormalizedUsage, estimate_cost_usd

# --- cost halving ---------------------------------------------------------


def test_estimate_cost_halved_for_batch() -> None:
    usage = NormalizedUsage(
        input_tokens=1_000_000,
        cached_input_tokens=0,
        output_tokens=1_000_000,
        provider_usage_raw=None,
        usage_estimation_method="provider_reported",
    )
    full = estimate_cost_usd("anthropic", "claude-haiku-4-5-20251001", usage)
    batched = estimate_cost_usd(
        "anthropic", "claude-haiku-4-5-20251001", usage, batch=True
    )
    assert full is not None and batched is not None
    assert batched == full / 2
    assert batched * 2 == full


# --- adapter batch interface ---------------------------------------------


class _MinimalAdapter(BaseLLMAdapter):
    async def stream(  # type: ignore[override]
        self, system, user, max_tokens, *, cache_system=False, cache_user_prefix=None
    ):
        yield ""

    async def complete(  # type: ignore[override]
        self, system, user, max_tokens, *, cache_system=False, cache_user_prefix=None
    ):
        return ""


@pytest.mark.asyncio
async def test_base_adapter_batch_methods_raise_unsupported() -> None:
    adapter = _MinimalAdapter()
    with pytest.raises(BatchUnsupportedError):
        await adapter.submit_batch([])
    with pytest.raises(BatchUnsupportedError):
        await adapter.poll_batch("b")
    with pytest.raises(BatchUnsupportedError):
        await adapter.fetch_batch_results("b")


def _make_anthropic_adapter():
    from services.llm.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter("claude-haiku-4-5-20251001", api_key="test")
    adapter._client = MagicMock()
    # Batches live under the beta namespace in the installed SDK (0.40).
    adapter._client.beta.messages.batches = MagicMock()
    return adapter


@pytest.mark.asyncio
async def test_anthropic_submit_and_poll_batch() -> None:
    adapter = _make_anthropic_adapter()
    batches = adapter._client.beta.messages.batches
    batches.create = AsyncMock(return_value=SimpleNamespace(id="msgbatch_1"))
    batches.retrieve = AsyncMock(
        return_value=SimpleNamespace(processing_status="ended")
    )

    batch_id = await adapter.submit_batch(
        [BatchRequest(custom_id="eval-1", system="sys", user="u", max_tokens=64)]
    )
    assert batch_id == "msgbatch_1"
    # Request body carries no client-level extra_body (effort) field.
    sent = batches.create.call_args.kwargs["requests"]
    assert sent[0]["custom_id"] == "eval-1"
    assert "extra_body" not in sent[0]["params"]

    assert await adapter.poll_batch("msgbatch_1") == "ended"


@pytest.mark.asyncio
async def test_anthropic_fetch_batch_results_maps_succeeded_and_errored() -> None:
    adapter = _make_anthropic_adapter()
    succeeded = SimpleNamespace(
        custom_id="eval-ok",
        result=SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"overall_score": 90}')],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                stop_reason="end_turn",
            ),
        ),
    )
    errored = SimpleNamespace(
        custom_id="eval-bad",
        result=SimpleNamespace(
            type="errored", error=SimpleNamespace(type="overloaded")
        ),
    )

    async def _aiter():
        for entry in (succeeded, errored):
            yield entry

    # The async SDK's results() is a coroutine returning an async iterator, so
    # the adapter must `await` it before iterating. Mocking it as an AsyncMock
    # (not a plain function) is what asserts that protocol is honoured.
    adapter._client.beta.messages.batches.results = AsyncMock(return_value=_aiter())

    results = await adapter.fetch_batch_results("msgbatch_1")
    assert results["eval-ok"].status == "succeeded"
    assert results["eval-ok"].text == '{"overall_score": 90}'
    assert results["eval-ok"].usage == {"input_tokens": 10, "output_tokens": 5}
    assert results["eval-bad"].status == "errored"
    assert results["eval-bad"].error == "overloaded"


# --- provider gating ------------------------------------------------------


def test_provider_supports_real_batch_only_anthropic() -> None:
    assert eval_batch.provider_supports_real_batch("anthropic") is True
    assert eval_batch.provider_supports_real_batch("openai") is False
    assert eval_batch.provider_supports_real_batch("google") is False


# --- orchestration: a fake session + AsyncSessionLocal --------------------


class _FakeSession:
    def __init__(self, row: LLMBatchJob | None) -> None:
        self._row = row
        self.committed = False
        self.deleted: list[Any] = []
        self.added: list[Any] = []

    async def get(self, _model, _id):
        return self._row

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, LLMBatchJob) and obj.id is None:
            obj.id = uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def delete(self, obj):
        self.deleted.append(obj)


def _session_local(session: _FakeSession):
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    return MagicMock(return_value=_Ctx())


def _row(**overrides) -> LLMBatchJob:
    row = LLMBatchJob(
        status=overrides.get("status", "submitted"),
        operation="eval.score",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        model_tier="small",
        prompt_version="eval-v2",
        custom_id="eval-1",
        request_system="sys",
        request_user="user",
        max_tokens=64,
        context={
            "stage_version_id": str(uuid4()),
            "stage_type": "spec",
            "content": "artifact",
            "spec_content": "",
            "harness_content": None,
            "content_generation_id": None,
            "provider": "anthropic",
            "judge_model": "claude-haiku-4-5-20251001",
        },
        workspace_id=None,
    )
    row.id = overrides.get("id", uuid4())
    row.provider_batch_id = overrides.get("provider_batch_id")
    row.attempts = 0
    row.created_at = overrides.get("created_at", datetime.now(UTC))
    return row


@pytest.mark.asyncio
async def test_run_submit_creates_batch_and_checkpoints_id() -> None:
    row = _row(status="pending", provider_batch_id=None)
    session = _FakeSession(row)
    adapter = MagicMock()
    adapter.submit_batch = AsyncMock(return_value="msgbatch_42")

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "get_llm", return_value=adapter),
    ):
        await eval_batch.run_submit({}, str(row.id))

    adapter.submit_batch.assert_awaited_once()
    assert row.provider_batch_id == "msgbatch_42"
    assert row.status == "submitted"
    assert session.committed is True


@pytest.mark.asyncio
async def test_run_submit_is_idempotent_when_already_submitted() -> None:
    row = _row(status="submitted", provider_batch_id="msgbatch_existing")
    session = _FakeSession(row)
    adapter = MagicMock()
    adapter.submit_batch = AsyncMock()

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "get_llm", return_value=adapter),
    ):
        await eval_batch.run_submit({}, str(row.id))

    adapter.submit_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_collect_returns_while_processing() -> None:
    row = _row(provider_batch_id="msgbatch_1")
    session = _FakeSession(row)
    adapter = MagicMock()
    adapter.poll_batch = AsyncMock(return_value="in_progress")
    adapter.fetch_batch_results = AsyncMock()

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "get_llm", return_value=adapter),
    ):
        await eval_batch.run_collect({}, str(row.id))

    adapter.fetch_batch_results.assert_not_awaited()
    assert session.deleted == []
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_run_collect_persists_and_deletes_on_success() -> None:
    row = _row(provider_batch_id="msgbatch_1")
    session = _FakeSession(row)
    adapter = MagicMock()
    adapter.poll_batch = AsyncMock(return_value="ended")
    adapter.fetch_batch_results = AsyncMock(
        return_value={
            "eval-1": BatchResultItem(
                custom_id="eval-1",
                status="succeeded",
                text='{"overall_score": 88}',
                usage={"input_tokens": 10, "output_tokens": 4},
            )
        }
    )

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "get_llm", return_value=adapter),
        patch.object(
            eval_batch, "persist_eval_from_raw", new=AsyncMock(return_value=MagicMock())
        ) as persist,
    ):
        await eval_batch.run_collect({}, str(row.id))

    persist.assert_awaited_once()
    assert row in session.deleted
    assert session.committed is True


@pytest.mark.asyncio
async def test_run_collect_falls_back_to_sync_on_errored_result() -> None:
    row = _row(provider_batch_id="msgbatch_1")
    session = _FakeSession(row)
    adapter = MagicMock()
    adapter.poll_batch = AsyncMock(return_value="ended")
    adapter.fetch_batch_results = AsyncMock(
        return_value={
            "eval-1": BatchResultItem(custom_id="eval-1", status="errored", error="x")
        }
    )

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "get_llm", return_value=adapter),
        patch.object(eval_batch, "run_eval", new=AsyncMock()) as run_eval_mock,
        patch.object(eval_batch, "persist_eval_from_raw", new=AsyncMock()) as persist,
    ):
        await eval_batch.run_collect({}, str(row.id))

    persist.assert_not_awaited()
    run_eval_mock.assert_awaited_once()
    assert row in session.deleted


@pytest.mark.asyncio
async def test_enqueue_eval_batch_commits_row_and_enqueues() -> None:
    session = _FakeSession(None)
    enqueue_mock = AsyncMock()

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "enqueue", enqueue_mock),
    ):
        row_id = await eval_batch.enqueue_eval_batch(
            stage_version_id=uuid4(),
            stage_type="spec",
            content="artifact",
            spec_content="",
            provider="anthropic",
            judge_model="claude-haiku-4-5-20251001",
            content_generation_id=None,
            harness_content=None,
            workspace_id=None,
        )

    assert session.committed is True
    assert len(session.added) == 1
    enqueue_mock.assert_awaited_once()
    assert enqueue_mock.await_args.args[0] == "llm_batch_submit"
    assert enqueue_mock.await_args.kwargs["job_id"] == str(row_id)


@pytest.mark.asyncio
async def test_enqueue_eval_batch_persists_generation_route_metadata() -> None:
    # issue #27 Phase 5: the deferred-batch checkpoint must carry the generation
    # route's provider/model so a batched score reaches Langfuse with the same
    # comparison metadata the synchronous path attaches.
    session = _FakeSession(None)

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "enqueue", AsyncMock()),
    ):
        await eval_batch.enqueue_eval_batch(
            stage_version_id=uuid4(),
            stage_type="spec",
            content="artifact",
            spec_content="",
            provider="anthropic",
            judge_model="claude-haiku-4-5-20251001",
            content_generation_id="g-1",
            harness_content=None,
            workspace_id=None,
            generation_provider="anthropic",
            generation_model="claude-haiku-4-5",
        )

    row = session.added[0]
    assert row.context["generation_provider"] == "anthropic"
    assert row.context["generation_model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_enqueue_eval_batch_swallows_enqueue_failure() -> None:
    # Row is committed before enqueue; a queue blip must not raise (the sweep
    # cron recovers), or the caller would double-score via its sync fallback.
    session = _FakeSession(None)

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(
            eval_batch, "enqueue", AsyncMock(side_effect=RuntimeError("down"))
        ),
    ):
        row_id = await eval_batch.enqueue_eval_batch(
            stage_version_id=uuid4(),
            stage_type="spec",
            content="artifact",
            spec_content="",
            provider="anthropic",
            judge_model="claude-haiku-4-5-20251001",
            content_generation_id=None,
            harness_content=None,
            workspace_id=None,
        )

    assert row_id is not None
    assert session.committed is True


@pytest.mark.asyncio
async def test_run_collect_stale_batch_scores_inline() -> None:
    row = _row(
        provider_batch_id="msgbatch_1",
        created_at=datetime.now(UTC) - timedelta(hours=30),
    )
    session = _FakeSession(row)
    adapter = MagicMock()
    adapter.poll_batch = AsyncMock(return_value="in_progress")

    with (
        patch.object(eval_batch, "AsyncSessionLocal", _session_local(session)),
        patch.object(eval_batch, "get_llm", return_value=adapter),
        patch.object(eval_batch, "run_eval", new=AsyncMock()) as run_eval_mock,
    ):
        await eval_batch.run_collect({}, str(row.id))

    run_eval_mock.assert_awaited_once()
    assert row in session.deleted
