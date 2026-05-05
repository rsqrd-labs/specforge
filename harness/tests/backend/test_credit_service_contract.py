from __future__ import annotations

from conftest import import_backend, read_backend_file


def test_credit_service_is_append_only_ledger_based() -> None:
    module = import_backend("services.credit_service")
    assert hasattr(module, "CreditService")

    source = read_backend_file("services", "credit_service.py").lower()
    assert "credit_balance" in source
    assert "for update" in source or "with_for_update" in source
    assert "credit_ledger" in source or "creditledger" in source


def test_credit_cost_constants_match_v1_spec() -> None:
    module = import_backend("services.credit_service")
    costs = getattr(module, "CREDIT_COSTS", None)

    assert costs is not None, "Expose CREDIT_COSTS so routes and tests share one contract"
    assert costs["generate"] == 10
    assert costs["regenerate"] == 10
    assert costs["refine"] == 3
    assert costs["chat"] == 2
    assert costs["export"] == 0
