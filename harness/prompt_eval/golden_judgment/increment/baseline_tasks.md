# TASKS

## Traceability Overview
FR-001 → T-001; FR-002 → T-002.

### T-001: Create invoice endpoint

**Phase:** API Layer
**Spec refs:** FR-001
**Harness refs:** `tests/integration/test_invoices.py::test_create_invoice_happy_path`
**Priority:** MUST

**Description**
Implement POST /invoices creating a draft invoice.

**Acceptance Criteria**
1. `pytest tests/integration/test_invoices.py::test_create_invoice_happy_path -v` passes.

### T-002: List invoices endpoint

**Phase:** API Layer
**Spec refs:** FR-002
**Harness refs:** `tests/integration/test_invoices.py::test_list_invoices_scoped_to_owner`
**Priority:** MUST

**Description**
Implement GET /invoices scoped to the calling owner.

**Acceptance Criteria**
1. `pytest tests/integration/test_invoices.py::test_list_invoices_scoped_to_owner -v` passes.
