"""Live-traffic contract test for the Langfuse integration.

Every other test in ``test_langfuse_contract.py`` relies on mocks, which means
a wrong kwarg name (e.g. ``usage_details=`` vs ``usage=``) inside our
``LangfuseClient`` wrapper would be silently swallowed by the wrapper's
exception handler — the integration would no-op in production with no
test failure.

This test boots a local recording HTTP server, points the **real** Langfuse
v2 SDK at it, exercises every public ``LangfuseClient`` method, calls
``flush()`` to drain the SDK's consumer-thread queue, and asserts the
expected HTTP endpoints were hit. Failures here mean the wrapper is no
longer talking to Langfuse, even though the unit/contract suites are green.

Run by CI alongside the rest of the harness contract tests. No real Langfuse
credentials required — the recording server accepts any auth and returns
canned 200 responses.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import socketserver
import threading
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import pytest
from conftest import import_backend

# ---------------------------------------------------------------------------
# Recording HTTP server
# ---------------------------------------------------------------------------


class _Recorder:
    """Thread-safe record of every HTTP request the server received."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[dict[str, Any]] = []

    def append(self, call: dict[str, Any]) -> None:
        with self._lock:
            self._calls.append(call)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._calls)


def _build_handler(recorder: _Recorder) -> type[http.server.BaseHTTPRequestHandler]:
    class _RecordingHandler(http.server.BaseHTTPRequestHandler):
        def _record(self, body: bytes) -> None:
            recorder.append(
                {
                    "method": self.command,
                    "path": urlparse(self.path).path,
                    "body": body,
                    "auth": self.headers.get("Authorization", ""),
                }
            )

        def _respond(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 — stdlib API
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            self._record(body)
            path = urlparse(self.path).path
            if path == "/api/public/dataset-items":
                # The SDK's Fern client parses this response into a
                # DatasetItem model. Returning an empty dict triggers a
                # noisy Pydantic ValidationError in the SDK (which the
                # wrapper swallows, but it pollutes CI logs). Return a
                # minimally shape-correct response.
                self._respond(
                    200,
                    {
                        "id": "ds-item-test",
                        "status": "ACTIVE",
                        "datasetId": "ds-test",
                        "datasetName": "high_quality_generations",
                        "createdAt": "2026-01-01T00:00:00.000Z",
                        "updatedAt": "2026-01-01T00:00:00.000Z",
                    },
                )
                return
            # Ingestion endpoint accepts a 207 multi-status with
            # per-event success/error arrays.
            self._respond(207, {"successes": [], "errors": []})

        def do_GET(self) -> None:  # noqa: N802 — stdlib API
            self._record(b"")
            path = urlparse(self.path).path
            # /api/public/v2/prompts/<name>?label=production etc.
            if path.startswith("/api/public/v2/prompts/"):
                prompt_name = path.rsplit("/", 1)[-1]
                self._respond(
                    200,
                    {
                        "prompt": "REMOTE PROMPT BODY FROM SERVER",
                        "name": prompt_name,
                        "version": 1,
                        "config": {},
                        "labels": ["production"],
                        "tags": [],
                        "type": "text",
                    },
                )
                return
            self._respond(200, {})

        def log_message(self, *_args: Any, **_kwargs: Any) -> None:
            # Silence stderr noise during the test.
            return

    return _RecordingHandler


@pytest.fixture
def langfuse_recording_server() -> Iterator[tuple[str, _Recorder]]:
    recorder = _Recorder()
    handler_cls = _build_handler(recorder)

    server = socketserver.ThreadingTCPServer(
        ("127.0.0.1", 0), handler_cls, bind_and_activate=False
    )
    server.daemon_threads = True
    server.allow_reuse_address = True
    server.server_bind()
    server.server_activate()
    host = f"http://127.0.0.1:{server.server_address[1]}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield host, recorder
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_langfuse_client_actually_reaches_the_network(
    langfuse_recording_server: tuple[str, _Recorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every LangfuseClient public method must produce real HTTP traffic
    against the configured host. If a kwarg-name drift or an SDK API change
    breaks one of them, the wrapper's exception handler would silently
    swallow it; without this test the integration would no-op in production.
    """
    host, recorder = langfuse_recording_server

    config = import_backend("config")
    langfuse_service = import_backend("services.langfuse_service")

    monkeypatch.setattr(config.settings, "langfuse_secret_key", "sk-recording-test")
    monkeypatch.setattr(config.settings, "langfuse_public_key", "pk-recording-test")
    monkeypatch.setattr(config.settings, "langfuse_host", host)
    monkeypatch.setattr(config.settings, "langfuse_prompt_cache_ttl", 0)
    monkeypatch.setattr(config.settings, "langfuse_prompt_fetch_timeout_seconds", 5.0)
    langfuse_service.reset_langfuse_client()

    client = langfuse_service.get_langfuse_client()

    async def exercise() -> str | None:
        trace_id = await client.create_trace(
            name="live-traffic-contract",
            user_id="user-live-1",
            metadata={"workspace_id": "ws-live-1", "stage_type": "spec"},
        )
        assert trace_id is not None

        span_id = await client.create_span(
            trace_id=trace_id,
            name="stage.spec.generate",
            metadata={"action": "generate"},
        )
        assert span_id is not None

        gen_id = await client.create_generation(
            span_id=span_id,
            trace_id=trace_id,
            name="anthropic.generate",
            provider="anthropic",
            model="claude-haiku-4-5",
            input={"system": "sys", "user": "u"},
            output="hello world",
            usage={"input": 12, "output": 4},
            metadata={"stage_type": "spec", "action": "generate"},
        )
        assert gen_id is not None

        await client.score_generation(generation_id=gen_id, name="overall", value=92.0)
        await client.add_to_dataset(
            dataset_name="high_quality_generations",
            item={"stage_type": "spec", "score": 92},
            source_observation_id=gen_id,
        )
        await client.end_span(span_id)

        body = await client.get_prompt(name="specforge.spec.system")
        await client.flush()
        return body

    body = asyncio.run(exercise())

    # ``get_prompt`` is a synchronous call: the value the SDK parsed from the
    # recording server's response must be threaded back to the caller. This
    # proves the GET path round-trips end-to-end, including JSON parsing.
    assert body == "REMOTE PROMPT BODY FROM SERVER"

    calls = recorder.snapshot()
    assert calls, (
        "No HTTP traffic reached the recording server. The LangfuseClient "
        "wrapper is silently swallowing every SDK call — its exception "
        "handler is hiding a real failure (e.g. wrong kwarg name, wrong "
        "method signature, or a constructor error)."
    )

    # Every call must carry HTTP Basic auth assembled from the configured
    # public/secret keys. A blank Authorization header would mean the SDK
    # never picked up the credentials we passed in.
    assert all(call["auth"].startswith("Basic ") for call in calls), (
        f"At least one Langfuse request was sent without auth: "
        f"{[c['auth'] for c in calls]}"
    )

    paths_seen = {call["path"] for call in calls}

    # Ingestion endpoint covers traces, spans, generations, scores. Without
    # this the entire observability story is broken in production.
    ingestion_calls = [
        c
        for c in calls
        if c["path"] == "/api/public/ingestion" and c["method"] == "POST"
    ]
    assert ingestion_calls, (
        f"No POSTs to /api/public/ingestion. Trace/span/generation/score "
        f"events never reached the server. Paths seen: {sorted(paths_seen)}"
    )

    # Dataset items have a separate endpoint; this is what catches the
    # specific failure mode of add_to_dataset() being silently no-op'd by a
    # wrong kwarg name in the wrapper.
    dataset_calls = [
        c
        for c in calls
        if c["path"] == "/api/public/dataset-items" and c["method"] == "POST"
    ]
    assert dataset_calls, (
        f"No POST to /api/public/dataset-items. add_to_dataset() never "
        f"made it onto the wire. Paths seen: {sorted(paths_seen)}"
    )

    # Prompt fetch is a synchronous GET, separate from the queued ingestion
    # path. This catches a regression in the asyncio.to_thread wrapping.
    prompt_calls = [
        c
        for c in calls
        if c["path"].startswith("/api/public/v2/prompts/") and c["method"] == "GET"
    ]
    assert prompt_calls, (
        f"No GET to /api/public/v2/prompts/. get_prompt() never made it "
        f"onto the wire. Paths seen: {sorted(paths_seen)}"
    )

    # Inspect the ingestion payload: the SDK serializes events into a
    # batch under "batch". A generation event must appear with our
    # provider/model metadata so the wrapper's create_generation kwargs are
    # actually flowing through (rather than being dropped silently).
    found_generation = False
    for call in ingestion_calls:
        try:
            payload = json.loads(call["body"].decode("utf-8"))
        except Exception:
            continue
        for event in payload.get("batch", []):
            event_body = event.get("body", {})
            if event_body.get("model") == "claude-haiku-4-5":
                found_generation = True
                break
        if found_generation:
            break
    assert found_generation, (
        "Ingestion traffic reached the server, but no generation event "
        "carrying the provider/model metadata was found. The wrapper's "
        "create_generation may be sending a malformed or empty payload."
    )

    # Cleanup so other tests don't see a dangling configured singleton.
    langfuse_service.reset_langfuse_client()
