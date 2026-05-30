## Harness Overview

The harness uses pytest-style contract and service tests. It verifies
authentication, authorization, input validation, rate limit behavior, audit
events, and secret redaction for every tenant workflow.

## Requirement-to-Test Matrix

| Source ID | Behaviour/contract | Test file | Test name | Test type | Path |
|---|---|---|---|---|---|
| FR-001 | create tenant | tests/contract/test_tenants.py | test_create_tenant | contract | positive |
| FR-002 | update plan | tests/contract/test_tenants.py | test_update_plan_requires_authorization | security | negative |
| FR-003 | credit idempotency | tests/integration/test_credits.py | test_credit_adjustment_idempotent | concurrency | positive |
| FR-004 | export redaction | tests/security/test_exports.py | test_export_redacts_secret_fields | security | negative |
| SEC-001 | auth and authz | tests/contract/test_tenants.py | test_update_plan_requires_authorization | security | negative |
| SEC-002 | input validation | tests/contract/test_tenants.py | test_create_tenant_rejects_bad_name | contract | negative |
| SEC-003 | rate limit | tests/security/test_rate_limits.py | test_export_rate_limit | security | negative |
| SEC-004 | audit | tests/integration/test_audit.py | test_plan_change_writes_audit_event | integration | positive |

## Coverage Plan

Contract tests cover API shapes, integration tests cover database side effects,
security tests cover authorization and secret redaction, and performance tests
cover NFR-001. No TestCategoryGap records are present.

## File Tree

```text
harness/
  tests/contract/test_tenants.py
  tests/integration/test_credits.py
  tests/integration/test_audit.py
  tests/security/test_exports.py
  tests/security/test_rate_limits.py
```

## Files

### File: tests/contract/test_tenants.py

```python
# Tests: FR-001, FR-002, SEC-001, SEC-002
def test_create_tenant(api_client, owner_token):
    response = api_client.post("/tenants", json={"name": "Example Tenant"}, headers=owner_token)
    assert response.status_code == 201


# Tests: FR-002, SEC-001
def test_update_plan_requires_authorization(api_client, operator_token):
    response = api_client.patch("/tenants/tnt_001/plan", json={"plan": "pro"}, headers=operator_token)
    assert response.status_code == 403


# Tests: SEC-002
def test_create_tenant_rejects_bad_name(api_client, owner_token):
    response = api_client.post("/tenants", json={"name": ""}, headers=owner_token)
    assert response.status_code == 422
```

### File: tests/integration/test_credits.py

```python
# Tests: FR-003, SEC-004
def test_credit_adjustment_idempotent(api_client, owner_token):
    payload = {"delta": 10, "reason": "support correction", "idempotency_key": "idem-001"}
    first = api_client.post("/tenants/tnt_001/credits", json=payload, headers=owner_token)
    second = api_client.post("/tenants/tnt_001/credits", json=payload, headers=owner_token)
    assert first.json()["ledger_id"] == second.json()["ledger_id"]
```

### File: tests/integration/test_audit.py

```python
# Tests: FR-002, SEC-004
def test_plan_change_writes_audit_event(api_client, owner_token):
    response = api_client.patch("/tenants/tnt_001/plan", json={"plan": "team"}, headers=owner_token)
    assert response.status_code == 200
    assert response.json()["audit_event"]["action"] == "tenant.plan_changed"
```

### File: tests/security/test_exports.py

```python
# Tests: FR-004, SEC-004
def test_export_redacts_secret_fields(api_client, owner_token):
    response = api_client.post("/tenants/tnt_001/export", headers=owner_token)
    body = response.text.lower()
    assert "secret" not in body
    assert "<redacted>" in body
```

### File: tests/security/test_rate_limits.py

```python
# Tests: SEC-003
def test_export_rate_limit(api_client, owner_token):
    responses = [api_client.post("/tenants/tnt_001/export", headers=owner_token) for _ in range(12)]
    assert responses[-1].status_code == 429
```
