"""Phase 5 credit-posture pins (Demo Day plan §11.2).

The §11.2 decision is **same per-stage credit cost as standard**; the operating
manual and the construction verifier are **free** (zero/near-zero LLM cost); the
one advisory construction regenerate is **platform-funded** (it mirrors the
critic-regen precedent). That decision required *no* credit_service code change —
Demo Day already routes through the same action-keyed ``CREDIT_COSTS`` and the
funded regen reuses the platform-funded ``_regenerate_with_findings``.

These tests **pin** that posture so a later change cannot silently start billing
Demo Day differently:

- the per-stage charge is keyed on the *action*, never the workspace mode, so a
  Demo Day generate/regenerate costs exactly what a standard one does;
- ``construction_regen`` is not a user-chargeable ``CREDIT_COSTS`` key, so the
  funded regenerate can never be debited to the user via the standard path;
- the verifier/verdict/manual modules never touch the credit ledger;
- the funded-regenerate orchestration body never calls ``credit_service.deduct``.
"""

from __future__ import annotations

import inspect

import services.pipeline.agent_manual_service as manual_mod
import services.pipeline.demo_day_plan_linter as linter_mod
import services.pipeline.demo_day_verdict as verdict_mod
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


def test_construction_regen_is_not_a_user_chargeable_action() -> None:
    # The funded construction regenerate tags its LLM *cost ledger* row with
    # credit_reason="construction_regen" (LLMCostContext) — never a CREDIT_COSTS
    # key. If it ever became one it could be billed to the user via deduct().
    assert "construction_regen" not in CREDIT_COSTS


def test_verifier_and_manual_are_free() -> None:
    # The zero-LLM verifier (+ its DB orchestration) and the operating-manual
    # generator are "free" per §11.2: they must never reference the credit ledger.
    for module in (linter_mod, verdict_mod, manual_mod):
        src = inspect.getsource(module)
        assert "credit_service" not in src, module.__name__
        assert "CreditLedger" not in src, module.__name__
        assert "deduct" not in src, module.__name__


def test_funded_regen_body_never_debits_user_credits() -> None:
    # The platform-funded construction regenerate goes through
    # _regenerate_with_findings (credit-free); its orchestration body must not add
    # a user-facing deduct. Source pin: a future deduct() in this path fails here.
    src = inspect.getsource(sm.StageManager._run_construction_regen)
    assert "credit_service" not in src
    assert "deduct" not in src
    # It does meter the LLM cost ledger as platform-funded work.
    assert "construction_regen" in src


def test_per_stage_charge_is_keyed_on_action_not_mode() -> None:
    # Pin the inline derivation in StageManager.generate: the credit reason/cost is
    # selected from the action alone. A mode-conditioned charge would break this.
    src = inspect.getsource(sm.StageManager.generate)
    assert (
        'credit_reason = "regenerate" if action == "regenerate" else "generate"' in src
    )
    assert "credit_cost = CREDIT_COSTS[credit_reason]" in src
