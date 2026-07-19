from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from models import EvalResult
from services.evals import online_eval as online_eval_module
from services.evals.online_eval import (
    _build_eval_prompt,
    _score_comment,
    combine_tasks_eval_context,
    run_eval,
    run_eval_background,
)


def test_build_eval_prompt_does_not_recursively_rescan_substituted_text() -> None:
    # Audit finding #1 (SHIP-BLOCKER): a chained `.replace("{spec_content}", ctx)
    # .replace("{content}", artifact)` re-scans its own output, so when `ctx`
    # (spec/context content) itself contains the literal substring "{content}"
    # — plausible in ordinary generated output, e.g. an API Design section
    # showing an example JSON body with a "content" field — the second
    # `.replace()` wrongly matches inside the just-inserted context block and
    # splices the artifact into the wrong slot. This guards against that
    # regression by asserting `artifact` appears only in its own labelled slot,
    # never inside the spec/context block.
    # NOTE: the fixture must contain the EXACT placeholder token `{content}` —
    # a JSON-ish `{"content": ...}` does NOT contain it (the quotes break the
    # match) and would pass even against the old buggy chained .replace().
    spec_content = (
        "## API Design\nTemplates interpolate the {content} placeholder "
        "before send.\n"
    )
    assert "{content}" in spec_content  # the fixture exercises the bug
    artifact = "PLAN_ARTIFACT_UNIQUE_MARKER"
    rendered = _build_eval_prompt("plan", artifact, spec_content)

    # eval-v3 fences each substituted block, so the artifact sits inside the
    # artifact_under_evaluation fence in the Plan: slot.
    assert 'Plan:\n<untrusted_content source="artifact_under_evaluation"' in rendered
    assert "PLAN_ARTIFACT_UNIQUE_MARKER" in rendered
    # The literal "{content}" inside spec_content must survive untouched —
    # never overwritten by the second substitution.
    assert "interpolate the {content} placeholder" in rendered
    # The artifact marker must not have leaked into the Spec: block.
    spec_block = rendered.split("Spec:\n", 1)[1].split("\n\nPlan:\n", 1)[0]
    assert artifact not in spec_block


def test_build_eval_prompt_happy_path_spec_stage() -> None:
    rendered = _build_eval_prompt("spec", "a spec body", "")
    assert 'Content:\n<untrusted_content source="artifact_under_evaluation"' in rendered
    assert "a spec body" in rendered


def test_build_eval_prompt_fences_artifact_and_context() -> None:
    # eval-v3: the scored artifact and its context are wrapped in the same
    # nonce-keyed fences every other judge uses, so boundary-spoofing text in a
    # scored artifact cannot pose as the end of the artifact and smuggle
    # instructions ("score every dimension 100") into the judge prompt.
    rendered = _build_eval_prompt("plan", "plan body", "spec body")
    assert rendered.count('<untrusted_content source="eval_context"') == 1
    assert rendered.count('<untrusted_content source="artifact_under_evaluation"') == 1
    assert "BEGIN_UNTRUSTED_CONTENT:artifact_under_evaluation:" in rendered


def test_build_eval_prompt_adversarial_content_field_in_artifact() -> None:
    # The artifact itself containing the literal "{spec_content}" placeholder
    # token must not corrupt the rendered prompt either (adversarial input
    # case). In the tasks template {spec_content} is substituted BEFORE
    # {content} positionally, so an exact token here proves inserted values are
    # never rescanned regardless of substitution order.
    spec_content = "spec body"
    artifact = "tasks referencing the literal {spec_content} placeholder token"
    rendered = _build_eval_prompt("tasks", artifact, spec_content)
    assert "tasks referencing the literal {spec_content} placeholder token" in rendered
    assert (
        rendered.count('Reference context:\n<untrusted_content source="eval_context"')
        == 1
    )
    assert "spec body" in rendered


# ---------------------------------------------------------------------------
# Audit L14: per-stage rubric requests only the dimensions the stage consumes.
# ---------------------------------------------------------------------------
def test_stage_score_dimensions_derive_from_consuming_structures() -> None:
    """The requested-dimension list is derived from _SCORE_WEIGHTS ∪ the
    completeness roll-up ∪ clarity — the exact structures that consume the
    scores — so the request list cannot drift from the scoring code."""
    for stage in ("spec", "plan", "harness", "tasks"):
        dims = online_eval_module._stage_score_dimensions(stage)
        weights = online_eval_module._SCORE_WEIGHTS[stage]
        expected = (set(weights) | online_eval_module._COMPLETENESS_DIMENSIONS) | {
            "clarity"
        }
        expected.discard("coverage_percent")
        assert set(dims) == expected, stage
        # Order is the canonical _ALL_SCORE_DIMENSIONS order (stable prompts).
        assert dims == [
            d for d in online_eval_module._ALL_SCORE_DIMENSIONS if d in expected
        ]


def test_rubric_for_stage_omits_unconsumed_dimensions() -> None:
    """L14 concrete cases: the spec pipeline never reads feasibility, and the
    harness pipeline never reads goal_alignment or feasibility — their rubrics
    must not ask the judge to score them. coverage_percent is a top-level
    response field, never a scores key."""
    spec_rubric = online_eval_module._rubric_for_stage("spec")
    assert '"feasibility"' not in spec_rubric
    assert '"requirements_coverage": 0-100' in spec_rubric

    harness_rubric = online_eval_module._rubric_for_stage("harness")
    assert '"goal_alignment"' not in harness_rubric
    assert '"feasibility"' not in harness_rubric
    assert (
        '"coverage_percent": 0-100'
        not in harness_rubric.split('"scores"')[1].split("},")[0]
    )
    assert '"coverage_percent": null or 0-100' in harness_rubric

    plan_rubric = online_eval_module._rubric_for_stage("plan")
    assert '"feasibility": 0-100' in plan_rubric


def test_build_eval_prompt_substitutes_rubric_placeholder() -> None:
    """L13/L14: every stage template carries a {rubric} placeholder that the
    single-pass substitution must fill — no literal {rubric} may reach the
    judge, and the calibration header must be present."""
    for stage in ("spec", "plan", "harness", "tasks"):
        rendered = _build_eval_prompt(stage, "artifact body", "context body")
        assert "{rubric}" not in rendered, stage
        assert "Score each dimension from 0 to 100" in rendered, stage


def test_tasks_template_renders_example_object_as_real_json() -> None:
    """Audit L13: the tasks template's tasks_without_ref example previously
    used doubled braces inside a plain (non-f) string, leaking literal
    `{{"task_number" ...}}` to the judge. It must render as real JSON."""
    rendered = _build_eval_prompt("tasks", "tasks body", "context body")
    assert '{"task_number": int or null' in rendered
    assert '{{"task_number"' not in rendered


def test_rubric_header_is_elision_aware() -> None:
    """The rubric's elision rule must key on the exact marker phrase
    compact_text emits, so bounded texts are never graded as gappy."""
    from services.text_compaction import ELISION_MARKER_PHRASE

    assert ELISION_MARKER_PHRASE in online_eval_module._RUBRIC_HEADER
    assert "Absence from the visible text is NOT" in online_eval_module._RUBRIC_HEADER


# ---------------------------------------------------------------------------
# Audit H4: tasks eval context is bounded per part, never union-truncated.
# ---------------------------------------------------------------------------
def test_combine_and_split_tasks_eval_context_round_trip() -> None:
    spec = "## Spec\nSPEC_BODY_MARKER"
    harness = "## Harness\nHARNESS_BODY_MARKER"
    combined = combine_tasks_eval_context(spec, harness)
    spec_part, harness_part = online_eval_module._split_tasks_eval_context(combined)
    assert spec_part == f"Specification:\n{spec}"
    assert harness_part == f"Test harness:\n{harness}"

    # Degenerate shapes: one part empty.
    assert combine_tasks_eval_context(spec, "") == f"Specification:\n{spec}"
    only_harness = combine_tasks_eval_context("", harness)
    assert only_harness == f"Test harness:\n{harness}"


def test_split_tasks_eval_context_splits_on_first_boundary() -> None:
    """A 'Test harness:' line inside the harness body must not shift content
    into the spec part — the genuine boundary is the FIRST occurrence."""
    spec = "spec text"
    harness = "harness intro\n\nTest harness:\nnested same-shaped line"
    combined = combine_tasks_eval_context(spec, harness)
    spec_part, harness_part = online_eval_module._split_tasks_eval_context(combined)
    assert spec_part == "Specification:\nspec text"
    assert "nested same-shaped line" in harness_part


def test_bounded_eval_context_tasks_bounds_each_part_separately() -> None:
    """H4 regression: a huge spec must not consume the head budget and elide
    nearly the whole harness. With per-part budgets, distinctive text from the
    head AND tail of BOTH parts survives bounding."""
    spec = "SPEC_HEAD_MARKER\n" + ("s" * 60_000) + "\nSPEC_TAIL_MARKER"
    harness = "HARNESS_HEAD_MARKER\n" + ("h" * 60_000) + "\nHARNESS_TAIL_MARKER"
    combined = combine_tasks_eval_context(spec, harness)

    bounded = online_eval_module._bounded_eval_context(
        "tasks", combined, 16_000, compact=False
    )

    for marker in (
        "SPEC_HEAD_MARKER",
        "SPEC_TAIL_MARKER",
        "HARNESS_HEAD_MARKER",
        "HARNESS_TAIL_MARKER",
    ):
        assert marker in bounded, marker
    # Each part is elided independently (two markers), and the total respects
    # the summed per-part budget plus the joiner/marker overhead.
    assert bounded.count("characters omitted") == 2
    spec_limit, harness_limit = online_eval_module._TASKS_CONTEXT_LIMITS[False]
    assert len(bounded) < spec_limit + harness_limit + 500


def test_bounded_eval_context_tasks_without_harness_single_bound() -> None:
    """A tasks context with no harness part falls back to the single-bound
    behaviour instead of misapplying per-part budgets."""
    combined = combine_tasks_eval_context("SPEC_ONLY_MARKER " + "s" * 40_000, "")
    bounded = online_eval_module._bounded_eval_context(
        "tasks", combined, 16_000, compact=False
    )
    assert "SPEC_ONLY_MARKER" in bounded
    assert len(bounded) < 16_500


def test_bounded_eval_context_non_tasks_unchanged() -> None:
    """Other stages keep the existing single-bound behaviour byte-for-byte."""
    ctx = "small plan context"
    assert (
        online_eval_module._bounded_eval_context("plan", ctx, 10_000, compact=False)
        == ctx
    )


def test_score_comment_omits_unknown_route() -> None:
    # issue #27 Phase 5: no provider/model ⇒ no comment (don't write null noise).
    assert _score_comment("spec", None, None) is None
    assert _score_comment("plan", "anthropic", None) == "plan · anthropic"
    assert _score_comment("tasks", None, "gpt-5.4-mini") == "tasks · gpt-5.4-mini"
    assert (
        _score_comment("harness", "google", "gemini-3.5-flash")
        == "harness · google/gemini-3.5-flash"
    )


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self._committed = False

    def add(self, instance: Any) -> None:
        if isinstance(instance, EvalResult) and not hasattr(instance, "id"):
            instance.id = uuid4()
        self.added.append(instance)

    async def commit(self) -> None:
        self._committed = True

    async def refresh(self, instance: Any) -> None:
        if not hasattr(instance, "id") or instance.id is None:
            instance.id = uuid4()

    async def execute(self, statement: Any) -> Any:
        # Models an empty eval_results table: _get_or_create_eval finds no prior
        # row and creates a fresh EvalResult, preserving one row per run_eval.
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result


class _FakeJudge:
    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        *,
        cache_system: bool = False,
    ) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _FakeSessionContext:
    def __init__(self, db: _FakeDB) -> None:
        self.db = db
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> _FakeDB:
        self.entered = True
        return self.db

    async def __aexit__(self, *args: Any) -> None:
        self.exited = True


@pytest.mark.asyncio
async def test_run_eval_returns_eval_result_with_scores() -> None:
    db = _FakeDB()
    judge_response = (
        '{"scores": {"goal_alignment": 90, "requirements_coverage": 80, '
        '"specificity_testability": 70, "user_flow_coverage": 60, '
        '"non_functional_coverage": 50, "traceability": 65, '
        '"feasibility": 75, "clarity": 70}, "coverage_percent": null, '
        '"uncovered_reqs": [], "tasks_without_ref": [], "risks": []}'
    )
    judge = _FakeJudge(judge_response)

    with patch("services.evals.online_eval.get_llm", return_value=judge):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    assert result.overall_score == 71
    assert result.completeness == 64
    assert result.clarity == 70
    assert result.flagged is False
    assert db._committed
    assert "Do not default to 85" in judge.calls[0]["user"]


@pytest.mark.asyncio
async def test_run_eval_computes_overall_from_rubric_scores_not_claimed_score() -> None:
    db = _FakeDB()
    judge_response = (
        '{"overall_score": 85, "scores": {"goal_alignment": 40, '
        '"requirements_coverage": 50, "specificity_testability": 60, '
        '"user_flow_coverage": 70, "non_functional_coverage": 80, '
        '"traceability": 90, "feasibility": 100, "clarity": 50}, '
        '"coverage_percent": null, "uncovered_reqs": [], '
        '"tasks_without_ref": [], "risks": ["missing acceptance criteria"]}'
    )

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(judge_response),
    ):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    assert result.overall_score == 58
    assert result.overall_score != 85
    assert result.clarity == 50


@pytest.mark.asyncio
async def test_run_eval_scores_langfuse_generation_when_id_present() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )
        await asyncio.sleep(0)

    assert result is not None
    langfuse_client.score_generation.assert_awaited_once_with(
        generation_id="g-123", name="overall", value=85.0, comment=None
    )
    langfuse_client.add_to_dataset.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_eval_skips_langfuse_score_without_generation_id() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(uuid4(), "spec", "spec content", "", db)

    assert result is not None
    langfuse_client.score_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_eval_returns_result_when_langfuse_score_fails() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock(
        side_effect=RuntimeError("langfuse down")
    )
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )
        await asyncio.sleep(0)

    assert result is not None
    assert result.overall_score == 85
    assert db._committed
    langfuse_client.add_to_dataset.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "expected_dataset"),
    [
        (90, "high_quality_generations"),
        (59, "low_quality_generations"),
        (60, None),
        (84, None),
    ],
)
async def test_run_eval_collects_datasets_at_score_thresholds(
    score: int, expected_dataset: str | None
) -> None:
    db = _FakeDB()
    judge_response = f'{{"overall_score": {score}, "completeness": 90, "clarity": 80}}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )
        await asyncio.sleep(0)

    assert result is not None
    if expected_dataset is None:
        langfuse_client.add_to_dataset.assert_not_awaited()
    else:
        langfuse_client.add_to_dataset.assert_awaited_once()
        kwargs = langfuse_client.add_to_dataset.await_args.kwargs
        assert kwargs["dataset_name"] == expected_dataset
        assert kwargs["source_observation_id"] == "g-123"


@pytest.mark.asyncio
async def test_run_eval_attaches_generation_metadata_to_score_and_dataset() -> None:
    # issue #27 Phase 5: a sampled score must carry the *generation* route's
    # provider/model (not the judge model) so model/provider quality is
    # comparable.  A high score routes to a dataset whose item is denormalized
    # with provider+model; the score row's comment tags them too.
    db = _FakeDB()
    judge_response = '{"overall_score": 90, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
            generation_provider="anthropic",
            generation_model="claude-haiku-4-5",
        )
        await asyncio.sleep(0)

    assert result is not None
    score_kwargs = langfuse_client.score_generation.await_args.kwargs
    assert score_kwargs["comment"] == "spec · anthropic/claude-haiku-4-5"

    item = langfuse_client.add_to_dataset.await_args.kwargs["item"]
    assert item["generation_provider"] == "anthropic"
    assert item["generation_model"] == "claude-haiku-4-5"
    assert item["stage_type"] == "spec"
    assert item["overall_score"] == 90


@pytest.mark.asyncio
async def test_run_eval_mid_range_score_still_carries_provider_model() -> None:
    # The comprehensive comparison surface is the per-generation score, not the
    # high/low datasets (which only collect score extremes).  A mid-range score
    # (no dataset) must still tag provider/model on the score row so typical
    # generations remain comparable (issue #27 Phase 5).
    db = _FakeDB()
    judge_response = '{"overall_score": 72, "completeness": 70, "clarity": 75}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    langfuse_client.add_to_dataset = AsyncMock()

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
    ):
        result = await run_eval(
            uuid4(),
            "plan",
            "plan content",
            "spec content",
            db,
            content_generation_id="g-456",
            generation_provider="openai",
            generation_model="gpt-5.4-mini",
        )
        await asyncio.sleep(0)

    assert result is not None
    langfuse_client.add_to_dataset.assert_not_awaited()
    score_kwargs = langfuse_client.score_generation.await_args.kwargs
    assert score_kwargs["comment"] == "plan · openai/gpt-5.4-mini"


@pytest.mark.asyncio
async def test_run_eval_dataset_write_is_fire_and_forget() -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 90, "completeness": 90, "clarity": 80}'
    langfuse_client = MagicMock()
    langfuse_client.score_generation = AsyncMock()
    fake_task = MagicMock()

    def fake_create_task(coro):
        coro.close()
        return fake_task

    with (
        patch(
            "services.evals.online_eval.get_llm",
            return_value=_FakeJudge(judge_response),
        ),
        patch(
            "services.evals.online_eval.langfuse_service.get_langfuse_client",
            return_value=langfuse_client,
        ),
        patch("services.evals.online_eval.asyncio.create_task", fake_create_task),
    ):
        result = await run_eval(
            uuid4(),
            "spec",
            "spec content",
            "",
            db,
            content_generation_id="g-123",
        )

    assert result is not None
    fake_task.add_done_callback.assert_called_once()


@pytest.mark.asyncio
async def test_run_eval_harness_does_not_flag_on_judge_coverage() -> None:
    # Harness `flagged` is no longer derived from the judge's coverage_percent
    # (Fable #6): the eval compacts the harness to ~20K chars, so on a normal-size
    # harness the judge under-counts coverage and would set a "Needs attention"
    # badge the deterministic CoveragePanel (deferred_reqs) contradicts. The judge
    # coverage is still STORED for telemetry, just not authoritative for flagging.
    db = _FakeDB()
    judge_response = (
        '{"overall_score": 60, "completeness": 60, "clarity": 70, '
        '"coverage_percent": 65, "uncovered_reqs": ["auth", "export"]}'
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(uuid4(), "harness", "harness content", "spec", db)

    assert result is not None
    assert result.coverage_percent == 65
    assert result.flagged is False
    assert "auth" in result.uncovered_reqs


@pytest.mark.asyncio
async def test_run_eval_json_parse_failure_returns_none() -> None:
    db = _FakeDB()

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge("not valid json at all"),
    ):
        result = await run_eval(uuid4(), "spec", "content", "", db)

    assert result is None
    assert not db._committed


@pytest.mark.asyncio
async def test_run_eval_extracts_json_from_fenced_judge_response() -> None:
    db = _FakeDB()
    judge_response = (
        "Here is the evaluation:\n"
        "```json\n"
        '{"scores": {"requirements_coverage": 80, '
        '"specificity_testability": 75, "traceability": 70, "clarity": 85}, '
        '"coverage_percent": 78, "uncovered_reqs": ["FR-009"], '
        '"tasks_without_ref": [], "risks": []}'
        "\n```"
    )

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(judge_response),
    ):
        result = await run_eval(uuid4(), "harness", "harness content", "spec", db)

    assert result is not None
    assert result.coverage_percent == 78
    assert result.overall_score == 77
    # Harness no longer flags on judge coverage_percent < 80 (Fable #6).
    assert result.flagged is False
    assert db._committed


@pytest.mark.asyncio
async def test_run_eval_judge_exception_returns_none() -> None:
    db = _FakeDB()

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(Exception("network error")),
    ):
        result = await run_eval(uuid4(), "spec", "content", "", db)

    assert result is None
    assert not db._committed


@pytest.mark.asyncio
async def test_run_eval_tasks_flags_tasks_without_ref() -> None:
    db = _FakeDB()
    judge_response = (
        '{"overall_score": 70, "completeness": 75, "clarity": 80, '
        '"tasks_without_ref": [{"task": "T-01", "reason": "no test ref"}]}'
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(uuid4(), "tasks", "tasks content", "spec", db)

    assert result is not None
    assert result.flagged is True
    assert len(result.tasks_without_ref) == 1


@pytest.mark.asyncio
async def test_run_eval_retries_tasks_with_compact_prompt_after_timeout() -> None:
    db = _FakeDB()
    success = SimpleNamespace(
        output='{"overall_score": 72, "completeness": 76, "clarity": 80}'
    )
    content = "Task details.\n" + ("x" * 30_000)
    context = "Specification and harness.\n" + ("h" * 20_000)

    with patch(
        "services.evals.online_eval.complete_background_llm",
        new_callable=AsyncMock,
        side_effect=[TimeoutError(), success],
    ) as complete_background_llm:
        result = await run_eval(uuid4(), "tasks", content, context, db)

    assert result is not None
    assert result.overall_score == 72
    assert complete_background_llm.await_count == 2
    first_prompt = complete_background_llm.await_args_list[0].kwargs["user"]
    retry_prompt = complete_background_llm.await_args_list[1].kwargs["user"]
    assert "[..." in retry_prompt
    assert len(retry_prompt) < len(first_prompt)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "judge_model"),
    [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-5.4-mini"),
        ("google", "gemini-3.1-flash-lite"),
    ],
)
async def test_run_eval_uses_provider_specific_judge_model(
    provider: str, judge_model: str
) -> None:
    db = _FakeDB()
    judge_response = '{"overall_score": 85, "completeness": 90, "clarity": 80}'

    with patch(
        "services.evals.online_eval.get_llm",
        return_value=_FakeJudge(judge_response),
    ) as get_llm:
        await run_eval(uuid4(), "spec", "content", "", db, provider)

    get_llm.assert_called_once_with(provider, judge_model)


@pytest.mark.asyncio
async def test_run_eval_background_opens_its_own_session() -> None:
    db = _FakeDB()
    context = _FakeSessionContext(db)
    stage_version_id = uuid4()

    with (
        patch("services.evals.online_eval.AsyncSessionLocal", return_value=context),
        patch("services.evals.online_eval.run_eval") as run_eval_mock,
    ):
        run_eval_mock.return_value = None
        result = await run_eval_background(
            stage_version_id,
            "spec",
            "content",
            "",
            "openai",
            "gpt-5.4-mini",
        )

    assert result is None
    assert context.entered is True
    assert context.exited is True
    run_eval_mock.assert_awaited_once_with(
        stage_version_id,
        "spec",
        "content",
        "",
        db,
        "openai",
        "gpt-5.4-mini",
        None,
        harness_content=None,
        generation_provider=None,
        generation_model=None,
    )
