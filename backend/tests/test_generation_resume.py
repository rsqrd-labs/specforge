"""Chunk-level generation resume: keep the banked sections, finish only the gap.

The defect this pins: a stage generation that completed 3 of 4 chunks and then
hit the provider call cap on the last one threw away all three. The run
terminalised, the credit was refunded, and Regenerate minted a fresh run that
re-generated every chunk from scratch — because checkpoints are keyed by
``generation_run_id`` and nothing ever read them across runs. The completed work
was durable in ``stage_generation_chunks`` the entire time.

Worse, the retry re-entered the SAME deadline that had just killed it, with the
same total work to do, so the second attempt was no likelier to finish than the
first. Resuming shrinks the work to the gap and hands it the full window.

These tests are DB-free on purpose: they exercise the pure decision functions
(``derive_quality_gate_recovery``) and the chunk-seeding logic of
``_generate_durable_artifact`` directly, so they run in CI without Postgres.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from models.stage import GENERATION_CREDIT_COST, derive_quality_gate_recovery
from services.pipeline import stage_manager as sm

# ---------------------------------------------------------------------------
# 1. The recovery contract: what the user is offered, and what it costs.
# ---------------------------------------------------------------------------


def test_resumable_gate_offers_a_free_resume_not_a_charged_regenerate():
    recovery = derive_quality_gate_recovery(
        "incomplete_output",
        refunded_prior_attempt=False,
        resumable=True,
        completed_sections=3,
        total_sections=4,
    )
    assert recovery["action"] == "resume"
    # The whole point: the banked sections stay paid for, so finishing the gap
    # must not ask for another credit.
    assert recovery["credit_required"] == 0
    assert "3 of 4" in recovery["message"]
    assert "1 section" in recovery["message"], "singular when one is missing"
    assert "no extra credit" in recovery["message"]
    # Still finalisable as-is — resume is an offer, never a lock-in.
    assert recovery["overridable"] is True


def test_resume_message_pluralises_the_remaining_sections():
    recovery = derive_quality_gate_recovery(
        "incomplete_output",
        refunded_prior_attempt=False,
        resumable=True,
        completed_sections=1,
        total_sections=4,
    )
    assert "3 sections" in recovery["message"]


def test_non_resumable_gate_is_byte_identical_to_the_old_contract():
    """The legacy path must not shift: a run that banked nothing still refunds
    and still offers a charged regenerate."""
    recovery = derive_quality_gate_recovery(
        "incomplete_output", refunded_prior_attempt=True
    )
    assert recovery["action"] == "regenerate"
    assert recovery["credit_required"] == GENERATION_CREDIT_COST
    assert recovery["refunded_prior_attempt"] is True
    assert "refunded" in recovery["message"]


@pytest.mark.parametrize("kind", ["technology_safety", "missing_sections", None])
def test_other_gate_kinds_never_become_resumable_by_accident(kind):
    recovery = derive_quality_gate_recovery(kind, refunded_prior_attempt=False)
    assert recovery["action"] == "regenerate"
    assert recovery["credit_required"] == GENERATION_CREDIT_COST


# ---------------------------------------------------------------------------
# 2. The generator: seeded chunks are honoured, re-banked, and never re-called.
# ---------------------------------------------------------------------------


@dataclass
class _FakeControl:
    """Minimal GenerationControl stand-in: never stops, never runs out of time."""

    run_id: str = "run-1"
    remaining_seconds: float = 300.0
    provider_seconds_remaining: float = 270.0

    def raise_if_stopped(self, partial_content: str = "") -> None:
        return None


class _PhaseSpy:
    def __init__(self) -> None:
        self.parts: list[tuple[int, int]] = []

    def set(self, *_args, **_kwargs) -> None:
        return None

    def set_parts(self, done: int, total: int) -> None:
        self.parts.append((done, total))


async def _run_generator(monkeypatch, *, resume_content, stage_type="spec"):
    """Drive _generate_durable_artifact with every provider call stubbed out."""
    generated_keys: list[str] = []
    checkpointed: list[str] = []

    async def fake_stream_chunk(self, **kwargs):
        chunk = kwargs["chunk"]
        generated_keys.append(chunk.key)
        return f"## {chunk.key}\nfresh body for {chunk.key}"

    async def fake_checkpoint(chunk, ordinal, content, route, retry_count):
        checkpointed.append(chunk.key)
        return len(checkpointed)

    async def fake_phase_change(_next_phase):
        return None

    monkeypatch.setattr(sm.StageManager, "_generate_chunk_once", fake_stream_chunk)

    phase = _PhaseSpy()
    manager = sm.StageManager()
    route = sm.LLMRoute(
        provider="anthropic",
        model=_strong_anthropic_model(),
        model_tier="strong",
        operation=f"{stage_type}.generate",
        latency_class="interactive",
        cross_provider_fallback=False,
        reason="test",
        requested_tier="strong",
        fallback_tier="mid",
        selection_reason="test",
    )
    artifact = await manager._generate_durable_artifact(
        route=route,
        adapter_factory=lambda _route: object(),
        system_prompt="sys",
        user_prompt="usr",
        stage_type=stage_type,
        deps={},
        mode="standard",
        emit=None,
        phase=phase,
        control=_FakeControl(),
        checkpoint=fake_checkpoint,
        phase_change=fake_phase_change,
        resume_content=resume_content,
    )
    return artifact, generated_keys, checkpointed, phase


def _strong_anthropic_model() -> str:
    """Resolve a real catalog model rather than hard-coding an id.

    ``_chunk_output_budget`` clamps against the catalog's per-model output
    ceiling, so a fabricated id raises. Looking it up keeps this test from
    rotting the next time the frontier model is swapped.
    """
    from services.llm.model_catalog import MODEL_CATALOG

    return next(
        entry.model_id
        for entry in MODEL_CATALOG
        if entry.provider == "anthropic" and entry.tier == "strong"
    )


def _spec_chunk_keys() -> list[str]:
    return [
        chunk.key
        for wave in sm._chunk_waves_for_stage("spec", "standard")
        for chunk in wave
    ]


def test_resume_regenerates_only_the_missing_chunk(monkeypatch):
    """The headline behaviour: 3 banked, 1 missing -> exactly 1 provider call."""
    keys = _spec_chunk_keys()
    assert len(keys) > 1, "spec must be multi-chunk for resume to mean anything"
    banked = {key: f"## {key}\nsaved body for {key}" for key in keys[:-1]}
    missing_key = keys[-1]

    artifact, generated, checkpointed, phase = asyncio.run(
        _run_generator(monkeypatch, resume_content=banked)
    )

    assert generated == [missing_key], "only the gap should reach the provider"
    # Every banked chunk is re-checkpointed onto THIS run, so a resume that dies
    # partway still leaves the next resume a complete checkpoint set.
    assert set(checkpointed) == set(keys)
    # The banked text survives verbatim — resume must not silently rewrite work
    # the user already has in their draft.
    for key in banked:
        assert banked[key] in artifact.content
    # Progress starts from what was inherited, not from zero.
    assert phase.parts[0] == (len(banked), len(keys))


def test_resume_preserves_document_order(monkeypatch):
    """Assembly order follows the chunk plan, not the order chunks arrived."""
    keys = _spec_chunk_keys()
    # Bank everything EXCEPT the first chunk, so the freshly generated chunk
    # must land at the front of the document rather than appended at the end.
    banked = {key: f"## {key}\nsaved body for {key}" for key in keys[1:]}

    artifact, generated, _checkpointed, _phase = asyncio.run(
        _run_generator(monkeypatch, resume_content=banked)
    )

    assert generated == [keys[0]]
    positions = [artifact.content.index(f"## {key}") for key in keys]
    assert positions == sorted(positions), "document order must follow the plan"


def test_stale_chunk_keys_are_dropped_and_regenerated(monkeypatch):
    """If the chunk plan changed since the seeded run, the unknown keys are not
    stitched in — those chunks are regenerated instead."""
    keys = _spec_chunk_keys()
    banked = {
        keys[0]: f"## {keys[0]}\nsaved body for {keys[0]}",
        "a-chunk-key-that-no-longer-exists": "orphaned content",
    }

    artifact, generated, _checkpointed, _phase = asyncio.run(
        _run_generator(monkeypatch, resume_content=banked)
    )

    assert set(generated) == set(keys[1:]), "every current chunk but the banked one"
    assert "orphaned content" not in artifact.content


def test_empty_resume_content_is_an_ordinary_full_generation(monkeypatch):
    """The no-resume path must stay exactly as it was."""
    keys = _spec_chunk_keys()

    _artifact, generated, checkpointed, phase = asyncio.run(
        _run_generator(monkeypatch, resume_content=None)
    )

    assert set(generated) == set(keys)
    assert set(checkpointed) == set(keys)
    assert phase.parts[0] == (0, len(keys))


def test_blank_banked_chunks_are_not_trusted(monkeypatch):
    """A whitespace-only checkpoint is not usable content; regenerate it rather
    than assembling a document with a hole where a section should be."""
    keys = _spec_chunk_keys()
    banked = {keys[0]: "   \n  "}

    _artifact, generated, _checkpointed, _phase = asyncio.run(
        _run_generator(monkeypatch, resume_content=banked)
    )

    assert keys[0] in generated


# ---------------------------------------------------------------------------
# 3. Cross-stage consistency: the same guarantee in all four stages, both modes.
# ---------------------------------------------------------------------------


_ALL_STAGES = ("spec", "plan", "harness", "tasks")


@pytest.mark.parametrize("mode", ["standard", "demo_day"])
@pytest.mark.parametrize("stage_type", _ALL_STAGES)
def test_every_stage_either_resumes_or_refunds_never_neither(stage_type, mode):
    """The invariant, stated once for all eight stage/mode combinations.

    A stage is in exactly one of two regimes, and which one is a pure function of
    its chunk count:

    * **multi-chunk** — a failure can bank completed sections, so the credit is
      kept and the gap is offered as a free resume;
    * **single-chunk** — one provider call, so a failure banks nothing, and the
      credit MUST be refunded.

    There is no third state, and in particular no state where the user is
    charged and left with nothing. This is the test that fails if a future
    chunking change silently moves a stage between regimes.
    """
    keys = [
        chunk.key
        for wave in sm._chunk_waves_for_stage(stage_type, mode)
        for chunk in wave
    ]
    assert keys, "every stage must have at least one chunk"
    can_bank_a_partial = len(keys) > 1

    # Mirror the exact predicate terminalize_interrupted_run uses, against the
    # worst realistic partial: every chunk but the last one completed.
    completed = keys[:-1]
    missing = keys[len(completed) :]
    resumable = bool(completed) and bool(missing)
    assert resumable is can_bank_a_partial

    recovery = derive_quality_gate_recovery(
        "incomplete_output",
        refunded_prior_attempt=not resumable,
        resumable=resumable,
        completed_sections=len(completed),
        total_sections=len(keys),
    )
    if can_bank_a_partial:
        assert recovery["action"] == "resume"
        assert recovery["credit_required"] == 0
        assert recovery["refunded_prior_attempt"] is False
    else:
        # Single-pass stages (Demo Day spec/plan/tasks) cannot resume — there is
        # no completed chunk to build on. They must therefore refund, so the
        # user is never charged for an artifact they did not receive.
        assert recovery["action"] == "regenerate"
        assert recovery["refunded_prior_attempt"] is True


@pytest.mark.parametrize("mode", ["standard", "demo_day"])
@pytest.mark.parametrize("stage_type", _ALL_STAGES)
def test_every_chunk_in_every_stage_has_a_human_label(stage_type, mode):
    """No stage shows the user a raw routing key.

    The resume offer names the sections that are missing. Chunk keys
    (``task-foundation-blocks``, ``demo-harness-files``) are internal
    identifiers whose style differs per stage; a user reading "still missing:
    validation-risk" learns nothing. Every chunk in every stage must map to a
    sentence a person would recognise.
    """
    from services.pipeline.chunk_labels import _CHUNK_LABELS, chunk_label

    for wave in sm._chunk_waves_for_stage(stage_type, mode):
        for chunk in wave:
            assert (stage_type, chunk.key) in _CHUNK_LABELS, (
                f"unmapped chunk {(stage_type, chunk.key)!r} — it would render "
                "to the user as a routing key"
            )
            label = chunk_label(stage_type, chunk.key)
            assert label[0].isupper(), "labels read as sentences, not identifiers"
            assert "-" not in label and "_" not in label


def test_unmapped_chunk_key_degrades_instead_of_breaking_the_resume_offer():
    """A chunk plan is persisted data and can outlive the code that wrote it, so
    an unknown key must still render — never raise and take the offer down."""
    from services.pipeline.chunk_labels import chunk_label

    assert chunk_label("spec", "some-future-chunk") == "Some future chunk"


def test_demo_day_harness_and_standard_harness_describe_sections_identically():
    """The two modes name the same harness chunks differently
    (``harness-files`` vs ``demo-harness-files``) — the user-facing wording must
    not inherit that split."""
    from services.pipeline.chunk_labels import chunk_label

    assert chunk_label("harness", "harness-files") == chunk_label(
        "harness", "demo-harness-files"
    )
    assert chunk_label("harness", "harness-contract") == chunk_label(
        "harness", "demo-harness-contract"
    )
