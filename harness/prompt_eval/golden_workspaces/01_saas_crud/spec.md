## Overview

TenantOps Console is a web UI for support teams that manage customer tenants,
plans, credit balances, and audit history. It must preserve authentication,
authorization, input validation, rate limit controls, audit evidence, and secret
redaction across every workflow.

## Functional Requirements

| ID | Requirement | Evidence |
|---|---|---|
| FR-001 | Operators can create a tenant with name, plan, and owner role. | Tenant appears in the dashboard list. |
| FR-002 | Operators can update a tenant plan after authorization succeeds. | Plan change appears in tenant detail. |
| FR-003 | Operators can adjust credits with a required reason. | Credit ledger row records the delta. |
| FR-004 | Operators can export tenant records with secret fields redacted. | Export file contains no secret-shaped strings. |

## Non-Functional Requirements

| ID | Requirement | Evidence |
|---|---|---|
| NFR-001 | Dashboard create and update flows respond within p95 450 ms. | Load test records p95 latency. |
| NFR-002 | Audit events are retained for 365 days. | Retention job preserves active rows. |

## Security, Privacy, and Abuse Expectations

| ID | Requirement | Evidence |
|---|---|---|
| SEC-001 | Every mutation requires authentication and tenant-scoped authorization. | Unauthorized calls return 403. |
| SEC-002 | User input validation rejects malformed tenant names and credit deltas. | Validation errors return field codes. |
| SEC-003 | Rate limit controls protect create, update, and export endpoints. | Excess requests return 429. |
| SEC-004 | Audit records include actor, tenant, action, and redacted secret fields. | Audit query returns complete records. |

## Acceptance Criteria

| ID | Criterion | Source |
|---|---|---|
| AC-001 | A support operator creates a tenant and sees it in the list. | FR-001 |
| AC-002 | A plan update creates an audit event and preserves authorization. | FR-002, SEC-001, SEC-004 |
| AC-003 | A credit adjustment records the reason and cannot underflow balance. | FR-003 |
| AC-004 | An export excludes tokens, API keys, and webhook secrets. | FR-004, SEC-004 |

## Risks

- Credit adjustments need idempotency so retries do not double-credit tenants.
- Export jobs need strict redaction because support files can leave the system.
