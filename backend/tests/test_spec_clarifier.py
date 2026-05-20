"""Unit tests for the Spec Clarification service (Phase 14 / T-162).

Covers:
  - Best-effort timeout behaviour (5-second wrap)
  - JSON-parse fallback to [] on malformed model output
  - Prompt-injection sanitisation on persisted answers
  - Round-key validation in persist_answers
  - That clarification is free (no credit deduction imports)
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from services.pipeline import spec_clarifier
from services.pipeline.spec_clarifier import (
    ClarificationValidationError,
    _parse_questions,
    persist_answers,
    request_clarifying_questions,
)


def _workspace(problem_statement: str = "Build a thing for a person.") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        provider="anthropic",
        problem_statement=problem_statement,
    )


class _FakeRedis:
    """Minimal in-memory stand-in for the bits of Redis the clarifier touches."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[int, str]] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = (ttl, value)

    async def get(self, key: str) -> str | None:
        entry = self.store.get(key)
        return entry[1] if entry else None

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def test_parse_questions_accepts_clean_json() -> None:
    raw = json.dumps(
        [
            {"question": "Who is the primary user?", "why_it_matters": "Drives FRs."},
            {"question": "What is the hard constraint?", "why_it_matters": "Scope."},
        ]
    )
    result = _parse_questions(raw)
    assert len(result) == 2
    assert result[0]["question"] == "Who is the primary user?"


def test_parse_questions_strips_markdown_fences() -> None:
    raw = (
        "Here are the questions:\n"
        '```json\n[{"question":"Q1","why_it_matters":"W1"}]\n```'
    )
    result = _parse_questions(raw)
    assert result == [{"question": "Q1", "why_it_matters": "W1"}]


def test_parse_questions_returns_empty_on_garbled_output() -> None:
    assert _parse_questions("") == []
    assert _parse_questions("not json at all") == []
    assert _parse_questions("[{not valid json}]") == []
    assert _parse_questions("[]") == []  # empty array, below min


def test_parse_questions_drops_malformed_entries() -> None:
    raw = json.dumps(
        [
            {"question": "ok", "why_it_matters": "ok"},
            {"question": ""},  # empty question — drop
            "not a dict",
            {"why_it_matters": "missing question"},  # missing field — drop
        ]
    )
    result = _parse_questions(raw)
    assert len(result) == 1
    assert result[0]["question"] == "ok"


def test_parse_questions_caps_at_five() -> None:
    raw = json.dumps(
        [
            {"question": f"Q{i}", "why_it_matters": f"W{i}"} for i in range(20)
        ]
    )
    assert len(_parse_questions(raw)) == 5


@pytest.mark.asyncio
async def test_request_clarifying_questions_returns_empty_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An LLM call that exceeds the 5s timeout must fail-soft to []."""

    async def slow_complete(*args, **kwargs):
        await asyncio.sleep(0.5)
        return "ignored"

    # Pin the timeout extremely short so the test stays fast.
    monkeypatch.setattr(spec_clarifier, "_JUDGE_TIMEOUT_SECONDS", 0.01)
    fake_adapter = SimpleNamespace(complete=slow_complete)
    monkeypatch.setattr(spec_clarifier, "get_llm", lambda *a, **k: fake_adapter)

    redis = _FakeRedis()
    result = await request_clarifying_questions(_workspace(), redis)
    assert result == []
    # Nothing should have been cached.
    assert not redis.store


@pytest.mark.asyncio
async def test_request_clarifying_questions_swallows_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("provider exploded")

    fake_adapter = SimpleNamespace(complete=boom)
    monkeypatch.setattr(spec_clarifier, "get_llm", lambda *a, **k: fake_adapter)

    redis = _FakeRedis()
    result = await request_clarifying_questions(_workspace(), redis)
    assert result == []


@pytest.mark.asyncio
async def test_request_clarifying_questions_caches_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.dumps(
        [{"question": "Who?", "why_it_matters": "Persona drives FRs."}]
    )
    fake_adapter = SimpleNamespace(complete=AsyncMock(return_value=raw))
    monkeypatch.setattr(spec_clarifier, "get_llm", lambda *a, **k: fake_adapter)

    redis = _FakeRedis()
    workspace = _workspace()
    questions = await request_clarifying_questions(workspace, redis)
    assert len(questions) == 1
    cached_key = f"clarify_round:{workspace.id}"
    assert cached_key in redis.store
    ttl, payload = redis.store[cached_key]
    assert ttl == 900
    assert json.loads(payload) == ["Who?"]


@pytest.mark.asyncio
async def test_persist_answers_rejects_unknown_question() -> None:
    workspace_id = uuid4()
    redis = _FakeRedis()
    await redis.setex(
        f"clarify_round:{workspace_id}", 900, json.dumps(["legitimate question"])
    )
    db = MagicMock()
    with pytest.raises(ClarificationValidationError):
        await persist_answers(
            workspace_id,
            [{"question": "smuggled", "answer": "payload"}],
            db,
            redis,
        )
    # Nothing should have been written to the database.
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_persist_answers_sanitises_html_in_answers() -> None:
    workspace_id = uuid4()
    redis = _FakeRedis()
    question = "What is the constraint?"
    await redis.setex(
        f"clarify_round:{workspace_id}", 900, json.dumps([question])
    )

    captured: dict = {}

    class _CapturingDB:
        async def execute(self, statement):
            captured["statement"] = statement

        async def commit(self):
            captured["committed"] = True

    db = _CapturingDB()
    await persist_answers(
        workspace_id,
        [
            {
                "question": question,
                "answer": "Latency under <script>alert(1)</script> 200ms.",
            }
        ],
        db,
        redis,
    )
    # The committed update statement has the values bound. Pull them out
    # via the SQLAlchemy parameters mapping rather than re-running it.
    compiled = captured["statement"].compile()
    params = compiled.params
    assert "clarification_qa" in params
    stored = params["clarification_qa"]
    assert isinstance(stored, list) and len(stored) == 1
    assert "<script>" not in stored[0]["answer"]
    assert "Latency under" in stored[0]["answer"]
    # And the round key is dropped after persistence.
    assert f"clarify_round:{workspace_id}" not in redis.store


@pytest.mark.asyncio
async def test_persist_answers_raises_when_round_expired() -> None:
    workspace_id = uuid4()
    redis = _FakeRedis()  # Empty — no round cached.
    db = MagicMock()
    with pytest.raises(ClarificationValidationError):
        await persist_answers(
            workspace_id,
            [{"question": "anything", "answer": "anything"}],
            db,
            redis,
        )


def test_spec_clarifier_module_has_no_credit_charges() -> None:
    """Hard contract: clarification is FREE; the file must not import or call any credit-deduction API."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "services"
        / "pipeline"
        / "spec_clarifier.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("credit_service.deduct", "deduct_credits", "spend_credits"):
        assert forbidden not in source, (
            f"spec_clarifier.py must NEVER call '{forbidden}'."
        )
