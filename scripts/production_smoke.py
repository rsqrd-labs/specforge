#!/usr/bin/env python3
"""Run a live Thought2Build production/staging smoke test.

The script intentionally uses only the Python standard library so it can run
from CI runners, release laptops, or a bastion without installing project deps.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TIMEOUT_SECONDS = 20
LLM_STREAM_TIMEOUT_SECONDS = 12 * 60
QUALITY_GATE_TIMEOUT_SECONDS = 2 * 60
PROBLEM_STATEMENT = (
    "Build a production smoke test workspace that validates authentication, "
    "credits, persistence, and stage wiring without touching customer data."
)


class SmokeFailure(Exception):
    pass


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def validate_api_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise SmokeFailure("THOUGHT2BUILD_API_URL must not contain userinfo")
    if not parsed.hostname or parsed.query or parsed.fragment:
        raise SmokeFailure(
            "THOUGHT2BUILD_API_URL must be an origin without query/fragment"
        )
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise SmokeFailure(
            "THOUGHT2BUILD_API_URL must use HTTPS (except loopback testing)"
        )
    return url.rstrip("/")


class SameOriginRedirectHandler(HTTPRedirectHandler):
    """Reject redirects that could forward smoke credentials cross-origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if _origin(req.full_url) != _origin(newurl):
            raise SmokeFailure(f"Refusing cross-origin redirect to {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_URL_OPENER = build_opener(SameOriginRedirectHandler())


@dataclass
class SmokeConfig:
    api_url: str
    access_token: str | None
    metrics_token: str | None
    # provider/model scope the LLM provider-health probe only. Workspaces no
    # longer carry a provider/model (routing is server-owned policy), so these
    # are not sent to POST /workspaces.
    #   THOUGHT2BUILD_SMOKE_PROVIDER — which provider must be healthy
    #                                  (default: first in the server's priority)
    #   THOUGHT2BUILD_SMOKE_MODEL    — catalog model id to probe instead of the
    #                                  provider's judge model
    provider: str | None
    model: str | None
    run_llm_smoke: bool
    public_only: bool


class SmokeClient:
    def __init__(self, config: SmokeConfig) -> None:
        self.config = config
        self.csrf_token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        use_auth: bool = True,
        use_csrf: bool = False,
        expected: set[int] | None = None,
    ) -> tuple[int, Any, dict[str, str]]:
        expected = expected or {200}
        headers = {"Accept": "application/json"}
        data = None

        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        auth_token = token if token is not None else self.config.access_token
        if use_auth and auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if use_csrf:
            headers["X-CSRF-Token"] = self.get_csrf_token()

        request = Request(
            urljoin(self.config.api_url.rstrip("/") + "/", path.lstrip("/")),
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with _URL_OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as exc:
            status = exc.code
            raw = exc.read()
            content_type = exc.headers.get("Content-Type", "")
        except URLError as exc:
            raise SmokeFailure(f"{method} {path} failed to connect: {exc}") from exc

        if status not in expected:
            snippet = raw[:300].decode("utf-8", errors="replace")
            raise SmokeFailure(
                f"{method} {path} returned HTTP {status}, expected "
                f"{sorted(expected)}: {snippet}"
            )

        if "application/json" in content_type and raw:
            return status, json.loads(raw), dict(request.header_items())
        return (
            status,
            raw.decode("utf-8", errors="replace"),
            dict(request.header_items()),
        )

    def get_csrf_token(self) -> str:
        if self.csrf_token:
            return self.csrf_token
        _, payload, _ = self.request("GET", "/auth/csrf-token")
        token = payload.get("csrf_token")
        if not isinstance(token, str) or not token:
            raise SmokeFailure("/auth/csrf-token did not return csrf_token")
        self.csrf_token = token
        return token

    def stream_stage(self, stage_id: str) -> None:
        request = Request(
            urljoin(
                self.config.api_url.rstrip("/") + "/",
                f"stages/{stage_id}/generate",
            ),
            data=b"",
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.config.access_token}",
                "X-CSRF-Token": self.get_csrf_token(),
            },
            method="POST",
        )

        started = time.monotonic()
        saw_token = False
        try:
            with _URL_OPENER.open(
                request, timeout=LLM_STREAM_TIMEOUT_SECONDS
            ) as response:
                if response.status != 200:
                    raise SmokeFailure(
                        f"POST /stages/{stage_id}/generate returned "
                        f"HTTP {response.status}"
                    )
                for raw_line in response:
                    if time.monotonic() - started > LLM_STREAM_TIMEOUT_SECONDS:
                        raise SmokeFailure(
                            "LLM stream exceeded the 12-minute settlement bound"
                        )
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = json.loads(line[5:].strip())
                    if "error" in payload:
                        raise SmokeFailure(f"LLM stream emitted error: {payload}")
                    if "token" in payload:
                        saw_token = True
                    if payload.get("done") is True:
                        if not saw_token:
                            raise SmokeFailure("LLM stream completed without tokens")
                        return
        except HTTPError as exc:
            raise SmokeFailure(
                f"POST /stages/{stage_id}/generate returned HTTP {exc.code}: "
                f"{exc.read()[:300].decode('utf-8', errors='replace')}"
            ) from exc
        except URLError as exc:
            raise SmokeFailure(f"LLM stream failed to connect: {exc}") from exc

        raise SmokeFailure("LLM stream ended before done event")

    def wait_until_finalisable(self, stage_id: str) -> dict[str, Any]:
        """Wait for detached technology/quality checks to leave ``checking``."""

        deadline = time.monotonic() + QUALITY_GATE_TIMEOUT_SECONDS
        while True:
            _, stage, _ = self.request("GET", f"/stages/{stage_id}")
            gate = stage.get("quality_gate")
            gate_status = gate.get("status") if isinstance(gate, dict) else None
            if gate_status != "checking":
                return stage
            if time.monotonic() >= deadline:
                raise SmokeFailure(
                    "SPEC quality verification did not settle within two minutes"
                )
            time.sleep(2)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> SmokeConfig:
    api_url = os.getenv("THOUGHT2BUILD_API_URL")
    if not api_url:
        raise SmokeFailure("THOUGHT2BUILD_API_URL is required")

    return SmokeConfig(
        api_url=validate_api_url(api_url),
        access_token=os.getenv("THOUGHT2BUILD_ACCESS_TOKEN"),
        metrics_token=os.getenv("THOUGHT2BUILD_METRICS_TOKEN"),
        provider=os.getenv("THOUGHT2BUILD_SMOKE_PROVIDER"),
        model=os.getenv("THOUGHT2BUILD_SMOKE_MODEL"),
        run_llm_smoke=_env_bool("THOUGHT2BUILD_RUN_LLM_SMOKE"),
        public_only=_env_bool("THOUGHT2BUILD_PUBLIC_ONLY_SMOKE"),
    )


def check(name: str) -> None:
    print(f"[smoke] {name}")


def assert_provider_health(config: SmokeConfig, payload: dict[str, Any]) -> None:
    """Assert the provider that will actually win a route is usable.

    ``GET /providers/health`` live-probes each provider and returns the
    server-owned ``priority`` order alongside the snapshots. The provider that
    matters is the first configured one in that order — that is the one every
    generation resolves to. A ``placeholder-`` prefixed key reads as
    ``configured: false``, which is exactly the misconfiguration this catches.
    """
    providers = payload.get("providers")
    priority = payload.get("priority")
    if not isinstance(providers, list) or not providers:
        raise SmokeFailure("/providers/health returned no providers")
    if not isinstance(priority, list) or not priority:
        raise SmokeFailure("/providers/health returned no priority order")

    by_id = {p.get("id"): p for p in providers if isinstance(p, dict)}
    target = config.provider or priority[0]
    snapshot = by_id.get(target)
    if snapshot is None:
        raise SmokeFailure(f"Provider {target!r} is not in /providers/health response")

    if not snapshot.get("configured"):
        raise SmokeFailure(
            f"Provider {target!r} is not configured — its API key is blank or "
            "'placeholder-' prefixed, so every generation will fail to route"
        )
    if snapshot.get("health") == "unhealthy":
        raise SmokeFailure(
            f"Provider {target!r} probed unhealthy "
            f"(model={snapshot.get('probed_model')!r}): {snapshot.get('message')}"
        )
    print(
        f"[smoke]   {target} configured, health="
        f"{snapshot.get('health')}, probed={snapshot.get('probed_model')}"
    )


def run() -> None:
    config = load_config()
    client = SmokeClient(config)

    check("health")
    _, health, _ = client.request("GET", "/health", use_auth=False)
    if health.get("status") != "ok":
        raise SmokeFailure(f"Unexpected health response: {health}")

    if config.metrics_token:
        check("metrics")
        status, metrics, _ = client.request(
            "GET",
            "/metrics",
            token=config.metrics_token,
            expected={200},
        )
        if status != 200 or "http_requests_total" not in metrics:
            raise SmokeFailure("/metrics did not return Prometheus metrics")

    if config.public_only:
        print("[smoke] public-only smoke passed")
        return

    if not config.access_token:
        raise SmokeFailure(
            "THOUGHT2BUILD_ACCESS_TOKEN is required unless "
            "THOUGHT2BUILD_PUBLIC_ONLY_SMOKE=1 is set"
        )

    check("authenticated user")
    _, user, _ = client.request("GET", "/auth/me")
    if not user.get("id") or not user.get("email"):
        raise SmokeFailure("/auth/me did not return an authenticated user")

    # LLM provider health. Admin-gated (each call makes a real outbound request
    # per configured provider), so a non-admin smoke token gets a 403 — that is
    # a skip, not a failure. Set THOUGHT2BUILD_SMOKE_MODEL=claude-opus-5 to also
    # prove the key is *permitted* that model, not merely valid.
    check("llm provider health")
    path = "/providers/health"
    if config.model:
        path = f"{path}?model={quote(config.model)}"
    status_code, provider_health, _ = client.request(
        "GET",
        path,
        expected={200, 403},
    )
    if status_code == 403:
        print("[smoke]   skipped: smoke user is not in ADMIN_USER_EMAILS")
    else:
        assert_provider_health(config, provider_health)

    check("credit balance")
    _, credits, _ = client.request("GET", "/credits/balance")
    if not isinstance(credits.get("balance"), int):
        raise SmokeFailure("/credits/balance did not return an integer balance")

    check("workspace persistence")
    workspace_name = f"smoke-{int(time.time())}"
    _, workspace, _ = client.request(
        "POST",
        "/workspaces",
        body={
            "name": workspace_name,
            "problem_statement": PROBLEM_STATEMENT,
        },
        use_csrf=True,
        expected={201},
    )
    workspace_id = workspace.get("id")
    stages = workspace.get("stages")
    if not workspace_id:
        raise SmokeFailure(f"Workspace response missing id or stages: {workspace}")

    try:
        if not isinstance(stages, list) or len(stages) != 4:
            raise SmokeFailure(f"Workspace response missing id or stages: {workspace}")
        _, fetched, _ = client.request("GET", f"/workspaces/{workspace_id}")
        if fetched.get("id") != workspace_id:
            raise SmokeFailure("Created workspace could not be fetched by id")

        _, updated, _ = client.request(
            "PATCH",
            f"/workspaces/{workspace_id}",
            body={"name": f"{workspace_name}-verified"},
            use_csrf=True,
        )
        if updated.get("name") != f"{workspace_name}-verified":
            raise SmokeFailure("Workspace update did not persist")

        if config.run_llm_smoke:
            check("live SPEC generation")
            spec_stage = next((s for s in stages if s.get("type") == "spec"), None)
            plan_stage = next((s for s in stages if s.get("type") == "plan"), None)
            if spec_stage is None or plan_stage is None:
                raise SmokeFailure("Created workspace is missing SPEC or PLAN")
            client.stream_stage(spec_stage["id"])
            generated_spec = client.wait_until_finalisable(spec_stage["id"])
            if generated_spec.get("status") != "draft" or not generated_spec.get(
                "content"
            ):
                raise SmokeFailure(
                    "SPEC generation did not persist a draft "
                    f"(status={generated_spec.get('status')!r}, "
                    f"content_present={bool(generated_spec.get('content'))})"
                )

            check("finalise generated SPEC")
            _, finalised_spec, _ = client.request(
                "POST",
                f"/stages/{spec_stage['id']}/finalise",
                use_csrf=True,
            )
            if finalised_spec.get("status") != "finalised":
                raise SmokeFailure(
                    "SPEC did not finalise "
                    f"(status={finalised_spec.get('status')!r})"
                )

            # This is the revenue-critical path the old smoke missed: dependency
            # loading after charge, the dedicated generation worker, PLAN's
            # four-chunk wave/checkpoints, validation, persistence and SSE observer.
            check("live PLAN generation")
            client.stream_stage(plan_stage["id"])
            _, generated_plan, _ = client.request("GET", f"/stages/{plan_stage['id']}")
            if generated_plan.get("status") != "draft" or not generated_plan.get(
                "content"
            ):
                raise SmokeFailure(
                    "PLAN generation did not persist a draft "
                    f"(status={generated_plan.get('status')!r}, "
                    f"content_present={bool(generated_plan.get('content'))})"
                )
    finally:
        # Smoke resources must never accumulate after a mid-pipeline failure.
        # Preserve the primary failure when best-effort cleanup also fails; on a
        # successful run, cleanup failure is itself a smoke failure.
        active_failure = sys.exc_info()[0] is not None
        try:
            check("workspace archive")
            client.request(
                "DELETE",
                f"/workspaces/{workspace_id}",
                use_csrf=True,
                expected={204},
            )
        except Exception as cleanup_error:
            if not active_failure:
                raise
            print(
                f"[smoke]   cleanup warning: {cleanup_error}",
                file=sys.stderr,
            )

    print("[smoke] production smoke passed")


if __name__ == "__main__":
    try:
        run()
    except SmokeFailure as exc:
        print(f"[smoke] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
