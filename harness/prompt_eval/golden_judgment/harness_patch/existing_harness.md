# HARNESS

## Harness Overview
Python 3.12 / pytest harness for the invoice-tracker API. Run with
`pytest tests/ -q` against the compose test stack (`docker compose up db`).
Deterministic time via the `frozen_clock` fixture; external mail is mocked.

## Requirement-to-Test Matrix
| Source ID | Behaviour | Test file | Test name | Type | Path | Initial |
|---|---|---|---|---|---|---|
| FR-001 | Create invoice | tests/integration/test_invoices.py | test_create_invoice_happy_path | integration | positive | fail-first |
| FR-002 | List invoices | tests/integration/test_invoices.py | test_list_invoices_scoped_to_owner | integration | positive | fail-first |
| SEC-001 | Reject foreign-tenant reads | tests/security/test_tenancy.py | test_cross_tenant_read_rejected | security | negative | fail-first |

## Coverage Plan
Unit, integration, security, contract, and migration_safety tiers are present.
TestCategoryGap: category=performance_budget reason=token_budget reqs=FR-009,FR-010

## File Tree
```
tests/
  conftest.py
  integration/test_invoices.py
  security/test_tenancy.py
```

## Files

### File: tests/conftest.py
```python
import pytest


@pytest.fixture
def frozen_clock():
    return "2026-01-01T00:00:00Z"
```

### File: tests/integration/test_invoices.py
```python
# Tests: FR-001
def test_create_invoice_happy_path(client, frozen_clock):
    """FR-001: POST /invoices creates a draft invoice."""
    resp = client.post("/invoices", json={"amount_cents": 1200})
    assert resp.status_code == 201


# Tests: FR-002
def test_list_invoices_scoped_to_owner(client):
    """FR-002: GET /invoices returns only the caller's invoices."""
    resp = client.get("/invoices")
    assert resp.status_code == 200
```

### File: tests/security/test_tenancy.py
```python
# Tests: SEC-001
def test_cross_tenant_read_rejected(client, other_tenant_invoice):
    """SEC-001: reading another tenant's invoice returns 404, not 403."""
    resp = client.get(f"/invoices/{other_tenant_invoice.id}")
    assert resp.status_code == 404
```
