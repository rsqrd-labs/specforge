## Overview

PolicyQA Assistant lets authorized analysts upload policy documents, ask
questions, and receive cited answers. Because it has LLM-facing inputs, every
document chunk is untrusted content. Authentication, authorization, input
validation, rate limit controls, audit logging, and secret redaction are required.

## Functional Requirements

| ID | Requirement | Evidence |
|---|---|---|
| FR-001 | Users can upload documents and see indexed status. | Upload status becomes indexed. |
| FR-002 | Users can ask a question and receive an answer with citations. | Answer contains chunk IDs. |
| FR-003 | Users can flag a response for reviewer follow-up. | Review queue row is created. |
| FR-004 | Admins can delete documents and dependent embeddings. | Document is removed from search. |

## Non-Functional Requirements

| ID | Requirement | Evidence |
|---|---|---|
| NFR-001 | Answer p95 latency is below 2500 ms for indexed documents. | Latency test records p95. |
| NFR-002 | Indexing retries recover from transient provider failures. | Retry test records success. |

## Security, Privacy, and Abuse Expectations

| ID | Requirement | Evidence |
|---|---|---|
| SEC-001 | Authentication and authorization protect document access. | Tenant isolation tests pass. |
| SEC-002 | Input validation rejects oversized or unsafe uploads. | Validation tests pass. |
| SEC-003 | Prompt injection in untrusted content is neutralized. | Attack fixture stays data-only. |
| SEC-004 | Secret-shaped strings are redacted from answers and audit logs. | Secret scan returns zero hits. |
| SEC-005 | Rate limit controls protect question and upload routes. | Excess calls return 429. |

## Acceptance Criteria

| ID | Criterion | Source |
|---|---|---|
| AC-001 | Uploading a PDF creates an indexed document record. | FR-001 |
| AC-002 | Asking a question returns an answer with at least one citation. | FR-002 |
| AC-003 | A hostile instruction inside a document is not followed. | SEC-003 |
| AC-004 | Deleting a document removes its embeddings. | FR-004 |

## Risks

- Retrieval quality can hide missing citations unless the harness checks them.
- Prompt injection must be framed as hostile data, not operational guidance.
