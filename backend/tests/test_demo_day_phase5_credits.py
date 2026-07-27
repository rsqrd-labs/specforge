"""Demo Day credit-posture pins.

Demo Day uses the same per-stage credit cost as standard. The operating manual
and construction verifier are deterministic, zero-LLM work and never touch the
credit ledger. Any regeneration is an explicit normal stage action.

These tests **pin** that posture so a later change cannot silently start billing
Demo Day differently:

- the per-stage charge is keyed on the *action*, never the workspace mode, so a
  Demo Day generate/regenerate costs exactly what a standard one does;
- the verifier/verdict/manual modules never touch the credit ledger;
"""

from __future__ import annotations

import inspect

import services.pipeline.agent_manual_service as manual_mod
import services.pipeline.construction_verdict_service as verdict_mod
import services.pipeline.demo_day_plan_linter as linter_mod
import services.pipeline.stage_manager as sm
from services.credit_service import CREDIT_COSTS


def test_credit_costs_are_mode_agnostic() -> None:
    # The charge map has no Demo Day dimension: generate/regenerate cost the same
    # for every workspace mode. Pinning the exact key set means adding a
    # mode-specific cost is a deliberate, test-breaking change.
    assert set(CREDIT_COSTS) == {"generate", "refine", "regenerate", "chat", "export"}
    # Generate and (full) regenerate are the headline per-stage costs Demo Day
    # inherits unchanged.
    assert CREDIT_COSTS["generate"] == 10
    assert CREDIT_COSTS["regenerate"] == 10


def test_verifier_and_manual_are_free() -> None:
    # The zero-LLM verifier (+ its DB orchestration) and the operating-manual
    # generator are "free" per §11.2: they must never reference the credit ledger.
    for module in (linter_mod, verdict_mod, manual_mod):
        src = inspect.getsource(module)
        assert "credit_service" not in src, module.__name__
        assert "CreditLedger" not in src, module.__name__
        assert "deduct" not in src, module.__name__


def test_per_stage_charge_is_keyed_on_action_not_mode() -> None:
    # Pin the inline derivation in StageManager.generate: the credit reason/cost is
    # selected from the action alone. A mode-conditioned charge would break this.
    src = inspect.getsource(sm.StageManager.generate)
    assert (
        'credit_reason = "regenerate" if action == "regenerate" else "generate"' in src
    )
    assert "credit_cost = CREDIT_COSTS[credit_reason]" in src
