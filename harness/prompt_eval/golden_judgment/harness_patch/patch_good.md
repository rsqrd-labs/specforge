## File: tests/performance/test_budget_patch.py
```python
import pytest


# Tests: FR-009
def test_invoice_list_p95_under_budget(client, seeded_invoices, timer):
    """FR-009: GET /invoices p95 stays under 300ms at 1k rows."""
    with timer() as t:
        resp = client.get("/invoices?limit=100")
    assert resp.status_code == 200
    assert t.p95_ms < 300


# Tests: FR-010
def test_invoice_export_streams_within_budget(client, seeded_invoices, timer):
    """FR-010: CSV export of 10k rows first-byte under 2s."""
    with timer() as t:
        resp = client.get("/invoices/export.csv")
    assert resp.status_code == 200
    assert t.first_byte_ms < 2000
```
