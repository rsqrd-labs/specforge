from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GraderResult:
    """Deterministic score emitted by one prompt-eval grader.

    Scores are normalized to 0.0..1.0 where higher is better. Count-style
    graders expose raw hit counts in metadata while still returning a normalized
    score so baseline comparison is directionally consistent.
    """

    name: str
    axis: str
    score: float
    findings: tuple[str, ...] = ()
    metadata: Mapping[str, float | int | str] = field(default_factory=dict)


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def make_result(
    *,
    name: str,
    axis: str,
    score: float,
    findings: list[str] | tuple[str, ...] | None = None,
    metadata: Mapping[str, float | int | str] | None = None,
) -> GraderResult:
    return GraderResult(
        name=name,
        axis=axis,
        score=clamp_score(score),
        findings=tuple(findings or ()),
        metadata=dict(metadata or {}),
    )
