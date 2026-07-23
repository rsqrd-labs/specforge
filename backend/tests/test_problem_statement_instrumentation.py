"""Phase-A instrumentation for the problem-statement compression plan (§8).

Covers the two histogram helpers and the bounded label normalisation, so a stray
provider/stage value can never explode Prometheus cardinality.
"""

from __future__ import annotations

from prometheus_client import REGISTRY

from services import observability


def _count(name: str, labels: dict[str, str]) -> float:
    return float(REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0)


def _sum(name: str, labels: dict[str, str]) -> float:
    return float(REGISTRY.get_sample_value(f"{name}_sum", labels) or 0.0)


def test_problem_statement_tokens_observes_into_provider_series() -> None:
    name = "thought2build_problem_statement_tokens"
    labels = {"provider": "anthropic"}
    count_before = _count(name, labels)
    sum_before = _sum(name, labels)

    observability.record_problem_statement_tokens("anthropic", 1234)

    assert _count(name, labels) == count_before + 1
    assert _sum(name, labels) == sum_before + 1234


def test_assembled_prompt_tokens_observes_into_provider_stage_series() -> None:
    name = "thought2build_assembled_prompt_tokens"
    labels = {"provider": "openai", "stage_type": "plan"}
    count_before = _count(name, labels)
    sum_before = _sum(name, labels)

    observability.record_assembled_prompt_tokens("openai", "plan", 50_000)

    assert _count(name, labels) == count_before + 1
    assert _sum(name, labels) == sum_before + 50_000


def test_none_and_negative_token_sizes_are_dropped() -> None:
    name = "thought2build_problem_statement_tokens"
    labels = {"provider": "google"}
    count_before = _count(name, labels)

    observability.record_problem_statement_tokens("google", None)
    observability.record_problem_statement_tokens("google", -5)

    assert _count(name, labels) == count_before


def test_unknown_labels_collapse_to_bounded_enum() -> None:
    # A stray provider/stage value must not create a new series.
    observability.record_problem_statement_tokens("evil-provider", 10)
    observability.record_assembled_prompt_tokens("evil-provider", "evil-stage", 10)

    assert (
        _count("thought2build_problem_statement_tokens", {"provider": "unknown"}) >= 1
    )
    assert (
        _count(
            "thought2build_assembled_prompt_tokens",
            {"provider": "unknown", "stage_type": "unknown"},
        )
        >= 1
    )
