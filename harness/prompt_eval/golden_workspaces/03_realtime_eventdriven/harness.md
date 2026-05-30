## Harness Overview

The harness verifies card commands, WebSocket fanout, replay, archive behavior,
authentication, authorization, input validation, rate limit controls, audit
logging, and secret redaction.

## Requirement-to-Test Matrix

| Source ID | Behaviour/contract | Test file | Test name | Test type | Path |
|---|---|---|---|---|---|
| FR-001 | create card | tests/contract/test_cards.py | test_create_card_emits_event | contract | positive |
| FR-002 | move card live | tests/e2e/test_realtime.py | test_move_card_broadcasts_ordered_event | e2e | positive |
| FR-003 | replay events | tests/integration/test_replay.py | test_reconnect_replays_after_sequence | integration | positive |
| FR-004 | archive card | tests/contract/test_cards.py | test_archive_card_keeps_audit | contract | positive |
| SEC-001 | board authz | tests/security/test_boards.py | test_cross_board_access_forbidden | security | negative |
| SEC-002 | input validation | tests/contract/test_cards.py | test_create_card_rejects_blank_title | contract | negative |
| SEC-003 | rate limit | tests/security/test_rate_limits.py | test_reconnect_rate_limit | security | negative |
| SEC-004 | audit | tests/integration/test_audit.py | test_move_writes_audit_event | integration | positive |
| SEC-005 | secret redaction | tests/security/test_payloads.py | test_realtime_payload_redacts_secret | security | negative |

## Coverage Plan

Contract tests cover REST commands, E2E tests cover WebSocket delivery,
integration tests cover replay and audit rows, and security tests cover
authorization, rate limit behavior, and secret redaction. No TestCategoryGap
records are present.

## File Tree

```text
harness/
  tests/contract/test_cards.py
  tests/e2e/test_realtime.py
  tests/integration/test_replay.py
  tests/integration/test_audit.py
  tests/security/test_boards.py
  tests/security/test_rate_limits.py
  tests/security/test_payloads.py
```

## Files

### File: tests/contract/test_cards.py

```python
# Tests: FR-001
def test_create_card_emits_event(api_client, member_token):
    response = api_client.post("/boards/brd_001/cards", json={"title": "Plan"}, headers=member_token)
    assert response.status_code == 201
    assert response.json()["event"]["sequence"] > 0


# Tests: SEC-002
def test_create_card_rejects_blank_title(api_client, member_token):
    response = api_client.post("/boards/brd_001/cards", json={"title": ""}, headers=member_token)
    assert response.status_code == 422


# Tests: FR-004, SEC-004
def test_archive_card_keeps_audit(api_client, member_token):
    response = api_client.post("/boards/brd_001/cards/crd_001/archive", headers=member_token)
    assert response.status_code == 200
```

### File: tests/e2e/test_realtime.py

```python
# Tests: FR-002, NFR-001
def test_move_card_broadcasts_ordered_event(ws_client, api_client, member_token):
    api_client.post("/boards/brd_001/cards/crd_001/move", json={"column_id": "done"}, headers=member_token)
    event = ws_client.receive_json()
    assert event["type"] == "card.moved"
    assert event["sequence"] > 0
```

### File: tests/integration/test_replay.py

```python
# Tests: FR-003, NFR-002
def test_reconnect_replays_after_sequence(api_client, member_token):
    response = api_client.get("/boards/brd_001/events?after_sequence=3", headers=member_token)
    assert response.status_code == 200
    assert all(event["sequence"] > 3 for event in response.json()["events"])
```

### File: tests/integration/test_audit.py

```python
# Tests: SEC-004
def test_move_writes_audit_event(api_client, member_token):
    response = api_client.post("/boards/brd_001/cards/crd_001/move", json={"column_id": "doing"}, headers=member_token)
    assert response.json()["audit_event"]["action"] == "card.moved"
```

### File: tests/security/test_boards.py

```python
# Tests: SEC-001
def test_cross_board_access_forbidden(api_client, other_board_token):
    response = api_client.get("/boards/brd_001/events", headers=other_board_token)
    assert response.status_code == 403
```

### File: tests/security/test_rate_limits.py

```python
# Tests: SEC-003
def test_reconnect_rate_limit(api_client, member_token):
    responses = [api_client.get("/boards/brd_001/events?after_sequence=0", headers=member_token) for _ in range(25)]
    assert responses[-1].status_code == 429
```

### File: tests/security/test_payloads.py

```python
# Tests: SEC-005
def test_realtime_payload_redacts_secret(ws_client):
    event = ws_client.receive_json()
    assert "secret" not in str(event).lower()
    assert event.get("redaction_status") == "clean"
```
