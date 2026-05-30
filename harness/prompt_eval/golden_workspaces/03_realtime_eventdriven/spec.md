## Overview

BoardSync is a realtime planning board for teams. Users create cards, move
cards, receive live updates, and replay missed events after reconnect. The
system requires authentication, authorization, input validation, rate limit
controls, audit logging, and secret-safe diagnostics.

## Functional Requirements

| ID | Requirement | Evidence |
|---|---|---|
| FR-001 | Users can create a card in a board column. | Card appears in column. |
| FR-002 | Users can move a card and all viewers receive the event. | WebSocket event is delivered. |
| FR-003 | Users can reconnect with last sequence and replay missed events. | Replay returns ordered events. |
| FR-004 | Users can archive cards without deleting audit history. | Card leaves active view. |

## Non-Functional Requirements

| ID | Requirement | Evidence |
|---|---|---|
| NFR-001 | Move events reach connected users within p95 300 ms. | Realtime latency test passes. |
| NFR-002 | Event replay supports 10k events per board per day. | Load test passes. |

## Security, Privacy, and Abuse Expectations

| ID | Requirement | Evidence |
|---|---|---|
| SEC-001 | Authentication and board authorization protect all routes. | Cross-board access returns 403. |
| SEC-002 | Input validation rejects malformed card titles and columns. | Validation errors return field codes. |
| SEC-003 | Rate limit controls protect card moves and reconnect attempts. | Excess calls return 429. |
| SEC-004 | Audit events record actor, board, card, action, and sequence. | Audit query shows event. |
| SEC-005 | Secret values are redacted from logs and realtime payloads. | Secret scan returns zero hits. |

## Acceptance Criteria

| ID | Criterion | Source |
|---|---|---|
| AC-001 | Creating a card persists it and emits a board event. | FR-001 |
| AC-002 | Moving a card broadcasts an ordered event to viewers. | FR-002 |
| AC-003 | Reconnect replay returns all events after the supplied sequence. | FR-003 |
| AC-004 | Archiving a card removes it from active lists and keeps audit. | FR-004 |

## Risks

- Concurrent card moves need ordering so clients do not render stale columns.
- Reconnect replay needs bounded retention and explicit rate limit controls.
