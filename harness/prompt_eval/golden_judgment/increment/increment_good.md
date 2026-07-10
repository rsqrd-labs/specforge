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

### T-003: Invoice reminder emails

**Phase:** Notifications
**Spec refs:** FR-011
**Harness refs:** `tests/integration/test_reminders.py::test_overdue_invoice_sends_reminder`
**Priority:** SHOULD

**Description**
Send a reminder email when an invoice passes its due date, deduped per invoice per day.

**Acceptance Criteria**
1. `pytest tests/integration/test_reminders.py -v` passes.

### T-004: Reminder opt-out setting

**Phase:** Notifications
**Spec refs:** FR-012
**Harness refs:** `tests/integration/test_reminders.py::test_opt_out_suppresses_reminder`
**Priority:** SHOULD

**Description**
Per-customer reminder opt-out; suppressed reminders are audit-logged.

**Acceptance Criteria**
1. `pytest tests/integration/test_reminders.py::test_opt_out_suppresses_reminder -v` passes.
