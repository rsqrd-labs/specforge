"""``eval_score_sample_rate`` config validation (issue #27 Phase 2).

The sample rate is a probability: a value outside ``[0.0, 1.0]`` is a
misconfiguration in *any* environment, so the ``field_validator`` fails startup
fast rather than silently clamping and quietly under/over-sampling the judge.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import config


def test_default_sample_rate_is_zero() -> None:
    # Default 0.0 ⇒ the score-only judge call is never issued for non-harness
    # stages; the cost win ships off, like every other adaptive eval flag.
    assert config.settings.eval_score_sample_rate == 0.0


@pytest.mark.parametrize("rate", [0.0, 0.25, 0.5, 1.0])
def test_in_range_rates_accepted(rate: float) -> None:
    assert config.Settings(eval_score_sample_rate=rate).eval_score_sample_rate == rate


@pytest.mark.parametrize("rate", [-0.1, -1.0, 1.1, 2.0])
def test_out_of_range_rates_rejected(rate: float) -> None:
    with pytest.raises(ValidationError):
        config.Settings(eval_score_sample_rate=rate)
