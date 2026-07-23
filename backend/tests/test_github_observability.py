"""GitHub observability tests (Phase 21 — T-284).

Covers the new metrics (registered + exposed on /metrics once observed), the
structured-audit helper's field schema (the documented id-shaped fields, with
``None`` dropped and any non-schema/content field ignored), and that the worker
process installs the redacting log config on startup.
"""

from __future__ import annotations

import asyncio
from typing import Any

from prometheus_client import generate_latest

import services.observability as observability

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_new_github_metrics_registered() -> None:
    for metric in ["GITHUB_EXPORT_TOTAL", "GITHUB_PR_TOTAL", "GITHUB_CHECK_TOTAL"]:
        assert hasattr(observability, metric)


def test_new_github_counters_exposed_on_metrics_after_observation() -> None:
    """A labelled Prometheus counter has no series until a label set is observed;
    once incremented it appears in the /metrics scrape (AC#2)."""
    observability.GITHUB_EXPORT_TOTAL.labels(
        export_mode="pr_with_tests", outcome="completed"
    ).inc()
    observability.GITHUB_PR_TOTAL.labels(outcome="opened").inc()
    observability.GITHUB_CHECK_TOTAL.labels(verdict="success").inc()

    body = generate_latest().decode()
    assert "thought2build_github_export_total" in body
    assert "thought2build_github_pr_total" in body
    assert "thought2build_github_check_total" in body


# ---------------------------------------------------------------------------
# Structured audit helper
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kw: Any) -> None:
        self.calls.append((event, kw))


def test_github_audit_emits_event_with_present_fields(monkeypatch) -> None:
    rec = _Recorder()
    monkeypatch.setattr(observability, "_github_audit_logger", rec)

    observability.github_audit(
        observability.GITHUB_AUDIT_EXPORT_COMPLETED,
        installation_id=42,
        workspace_id="w1",
        repo_id=99,
        push_id="p1",
        status="completed",
    )

    event, fields = rec.calls[0]
    assert event == "github.export.completed"
    assert fields == {
        "installation_id": 42,
        "workspace_id": "w1",
        "repo_id": 99,
        "push_id": "p1",
        "status": "completed",
    }


def test_github_audit_drops_none_fields(monkeypatch) -> None:
    """Fields are emitted "where available" — a None field is omitted entirely."""
    rec = _Recorder()
    monkeypatch.setattr(observability, "_github_audit_logger", rec)

    observability.github_audit(
        observability.GITHUB_AUDIT_WEBHOOK_RECEIVED,
        delivery_id="d-1",
        event_type="issues",
        repo_id=None,
        installation_id=None,
        status="queued",
    )

    _event, fields = rec.calls[0]
    assert fields == {"delivery_id": "d-1", "event_type": "issues", "status": "queued"}
    assert "repo_id" not in fields and "installation_id" not in fields


def test_github_audit_ignores_non_schema_content_fields(monkeypatch) -> None:
    """A caller cannot smuggle a diff/token/payload into an audit row: only the
    recognised id-shaped fields pass through (T-284 no-content rule)."""
    rec = _Recorder()
    monkeypatch.setattr(observability, "_github_audit_logger", rec)

    observability.github_audit(
        observability.GITHUB_AUDIT_CHECK_POSTED,
        push_id="p1",
        diff="diff --git a/secret b/secret\n+leaked",
        token="ghs_abcdefghijklmnopqrstuvwxyz",
        payload={"raw": "stuff"},
    )

    _event, fields = rec.calls[0]
    assert fields == {"push_id": "p1"}
    assert "diff" not in fields and "token" not in fields and "payload" not in fields


def test_all_audit_event_names_are_namespaced() -> None:
    names = [
        observability.GITHUB_AUDIT_INSTALLED,
        observability.GITHUB_AUDIT_UNINSTALLED,
        observability.GITHUB_AUDIT_WEBHOOK_RECEIVED,
        observability.GITHUB_AUDIT_WEBHOOK_DUPLICATE_SKIPPED,
        observability.GITHUB_AUDIT_RECONCILE_TASK_DONE,
        observability.GITHUB_AUDIT_EXPORT_COMPLETED,
        observability.GITHUB_AUDIT_PR_OPENED,
        observability.GITHUB_AUDIT_CHECK_POSTED,
        observability.GITHUB_AUDIT_INCREMENT_PUSHED,
        observability.GITHUB_AUDIT_SYNC_PAUSED,
    ]
    assert len(set(names)) == 10
    assert all(name.startswith("github.") for name in names)


# ---------------------------------------------------------------------------
# Worker installs the redacting log config
# ---------------------------------------------------------------------------


def test_worker_startup_configures_logging(monkeypatch) -> None:
    """The worker is a separate process; _on_startup must run configure_logging()
    so worker audit rows are structured + redacted (never leak a token)."""
    import worker

    called = {"configure_logging": False}
    monkeypatch.setattr(
        observability,
        "configure_logging",
        lambda: called.__setitem__("configure_logging", True),
    )
    monkeypatch.setattr("database._initialize_redis", lambda client: None)

    class _FakeRedis:
        @staticmethod
        def from_url(*_args: Any, **_kwargs: Any) -> object:
            return object()

    monkeypatch.setattr("redis.asyncio.Redis", _FakeRedis)
    # sentry_dsn defaults to "" so Sentry init is skipped.

    asyncio.run(worker._on_startup({}))

    assert called["configure_logging"] is True
