# TASKS

## Traceability Overview
FR-001 → T-001; FR-002 → T-002.

### T-001: Create invoice endpoint (now with reminders!)

**Phase:** API Layer
**Spec refs:** FR-001, FR-011
**Harness refs:** `tests/integration/test_invoices.py::test_create_invoice_happy_path`
**Priority:** MUST

**Description**
Implement POST /invoices creating a draft invoice and wire reminder emails.

**Acceptance Criteria**
1. `pytest tests/integration/test_invoices.py::test_create_invoice_happy_path -v` passes.

### T-005: Reminder opt-out setting

**Phase:** Notifications
**Spec refs:** FR-012
**Priority:** SHOULD

**Description**
Per-customer reminder opt-out.

**Acceptance Criteria**
1. Manual check.
