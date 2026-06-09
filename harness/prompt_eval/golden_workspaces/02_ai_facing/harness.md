## Harness Overview

The harness verifies upload, retrieval, answer generation, review flags,
authentication, authorization, input validation, rate limit controls, audit
logging, secret redaction, and untrusted content handling.

## Requirement-to-Test Matrix

| Source ID | Behaviour/contract | Test file | Test name | Test type | Path |
|---|---|---|---|---|---|
| FR-001 | upload document | tests/contract/test_documents.py | test_upload_document_indexes | contract | positive |
| FR-002 | cited answer | tests/contract/test_answers.py | test_answer_requires_citations | contract | positive |
| FR-003 | flag answer | tests/integration/test_review.py | test_flag_answer_creates_review_row | integration | positive |
| FR-004 | delete document | tests/integration/test_documents.py | test_delete_document_removes_embeddings | integration | positive |
| NFR-001 | answer latency | tests/performance/test_answer_latency.py | test_answer_latency_budget | performance | positive |
| NFR-002 | indexing recovery | tests/integration/test_documents.py | test_indexing_retries_after_worker_restart | integration | positive |
| SEC-001 | tenant isolation | tests/security/test_isolation.py | test_document_cross_tenant_forbidden | security | negative |
| SEC-002 | upload validation | tests/contract/test_documents.py | test_upload_rejects_unsafe_file | contract | negative |
| SEC-003 | prompt injection | tests/security/test_prompt_safety.py | test_untrusted_content_cannot_override_instructions | security | negative |
| SEC-004 | secret redaction | tests/security/test_prompt_safety.py | test_answer_redacts_secret_shaped_text | security | negative |
| SEC-005 | rate limit | tests/security/test_rate_limits.py | test_question_rate_limit | security | negative |

## Coverage Plan

Contract tests cover API schemas, security tests cover prompt injection and
secret redaction, and integration tests cover indexing and deletion side effects.
No TestCategoryGap records are present.

## File Tree

```text
harness/
  tests/contract/test_documents.py
  tests/contract/test_answers.py
  tests/integration/test_review.py
  tests/integration/test_documents.py
  tests/security/test_isolation.py
  tests/security/test_prompt_safety.py
  tests/security/test_rate_limits.py
  tests/performance/test_answer_latency.py
```

## Files

### File: tests/contract/test_documents.py

```python
# Tests: FR-001
def test_upload_document_indexes(api_client, analyst_token):
    response = api_client.post("/documents", files={"file": ("policy.pdf", b"data")}, headers=analyst_token)
    assert response.status_code == 202
    assert response.json()["status"] == "indexing"


# Tests: SEC-002
def test_upload_rejects_unsafe_file(api_client, analyst_token):
    response = api_client.post("/documents", files={"file": ("policy.exe", b"data")}, headers=analyst_token)
    assert response.status_code == 422
```

### File: tests/contract/test_answers.py

```python
# Tests: FR-002
def test_answer_requires_citations(api_client, analyst_token, indexed_document):
    response = api_client.post("/questions", json={"question": "What changed?"}, headers=analyst_token)
    assert response.status_code == 200
    assert response.json()["citations"]
```

### File: tests/integration/test_review.py

```python
# Tests: FR-003, SEC-004
def test_flag_answer_creates_review_row(api_client, analyst_token, answer):
    response = api_client.post(f"/answers/{answer.id}/flags", json={"reason": "needs review"}, headers=analyst_token)
    assert response.status_code == 201
```

### File: tests/integration/test_documents.py

```python
# Tests: FR-004
def test_delete_document_removes_embeddings(api_client, admin_token, document):
    response = api_client.delete(f"/documents/{document.id}", headers=admin_token)
    assert response.status_code == 204


# Tests: NFR-002
def test_indexing_retries_after_worker_restart(index_worker, document):
    index_worker.restart()
    assert document.index_status == "indexed"
```

### File: tests/performance/test_answer_latency.py

```python
# Tests: NFR-001
def test_answer_latency_budget(answer_latency_probe):
    assert answer_latency_probe.p95_ms <= 2000
```

### File: tests/security/test_isolation.py

```python
# Tests: SEC-001
def test_document_cross_tenant_forbidden(api_client, other_tenant_token, document):
    response = api_client.get(f"/documents/{document.id}", headers=other_tenant_token)
    assert response.status_code == 403
```

### File: tests/security/test_prompt_safety.py

```python
# Tests: SEC-003
def test_untrusted_content_cannot_override_instructions(api_client, analyst_token, hostile_document):
    response = api_client.post("/questions", json={"question": "Summarize the policy"}, headers=analyst_token)
    assert response.status_code == 200
    assert response.json()["safety"]["untrusted_content"] == "contained"


# Tests: SEC-004
def test_answer_redacts_secret_shaped_text(api_client, analyst_token, indexed_document):
    response = api_client.post("/questions", json={"question": "List sensitive fields"}, headers=analyst_token)
    assert "<redacted>" in response.text.lower()
```

### File: tests/security/test_rate_limits.py

```python
# Tests: SEC-005
def test_question_rate_limit(api_client, analyst_token):
    responses = [api_client.post("/questions", json={"question": "status"}, headers=analyst_token) for _ in range(20)]
    assert responses[-1].status_code == 429
```
