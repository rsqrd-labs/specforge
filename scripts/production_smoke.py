#!/usr/bin/env python3
"""Run a live SpecForge production/staging smoke test.

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
from urllib.parse import urljoin
from urllib.request import Request, urlopen

TIMEOUT_SECONDS = 20
PROBLEM_STATEMENT = (
    "Build a production smoke test workspace that validates authentication, "
    "credits, persistence, and stage wiring without touching customer data."
)


class SmokeFailure(Exception):
    pass


@dataclass
class SmokeConfig:
    api_url: str
    access_token: str | None
    metrics_token: str | None
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
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
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
            with urlopen(request, timeout=120) as response:
                if response.status != 200:
                    raise SmokeFailure(
                        f"POST /stages/{stage_id}/generate returned "
                        f"HTTP {response.status}"
                    )
                for raw_line in response:
                    if time.monotonic() - started > 120:
                        raise SmokeFailure("LLM stream exceeded 120 seconds")
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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> SmokeConfig:
    api_url = os.getenv("SPECFORGE_API_URL")
    if not api_url:
        raise SmokeFailure("SPECFORGE_API_URL is required")

    return SmokeConfig(
        api_url=api_url,
        access_token=os.getenv("SPECFORGE_ACCESS_TOKEN"),
        metrics_token=os.getenv("SPECFORGE_METRICS_TOKEN"),
        provider=os.getenv("SPECFORGE_SMOKE_PROVIDER"),
        model=os.getenv("SPECFORGE_SMOKE_MODEL"),
        run_llm_smoke=_env_bool("SPECFORGE_RUN_LLM_SMOKE"),
        public_only=_env_bool("SPECFORGE_PUBLIC_ONLY_SMOKE"),
    )


def check(name: str) -> None:
    print(f"[smoke] {name}")


def choose_provider(config: SmokeConfig, catalog: dict[str, Any]) -> tuple[str, str]:
    providers = catalog.get("providers")
    if not isinstance(providers, list) or not providers:
        raise SmokeFailure("/providers returned no providers")

    provider = config.provider or providers[0]["id"]
    selected = next((p for p in providers if p.get("id") == provider), None)
    if selected is None:
        raise SmokeFailure(f"Provider {provider!r} is not in /providers response")

    models = selected.get("models")
    if not isinstance(models, list) or not models:
        raise SmokeFailure(f"Provider {provider!r} has no models")

    model = config.model or models[0]["id"]
    if not any(m.get("id") == model for m in models):
        raise SmokeFailure(f"Model {model!r} is not available for {provider!r}")
    return provider, model


def run() -> None:
    config = load_config()
    client = SmokeClient(config)

    check("health")
    _, health, _ = client.request("GET", "/health", use_auth=False)
    if health.get("status") != "ok":
        raise SmokeFailure(f"Unexpected health response: {health}")

    check("provider catalog")
    _, catalog, _ = client.request("GET", "/providers", use_auth=False)
    provider, model = choose_provider(config, catalog)

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
            "SPECFORGE_ACCESS_TOKEN is required unless "
            "SPECFORGE_PUBLIC_ONLY_SMOKE=1 is set"
        )

    check("authenticated user")
    _, user, _ = client.request("GET", "/auth/me")
    if not user.get("id") or not user.get("email"):
        raise SmokeFailure("/auth/me did not return an authenticated user")

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
            "provider": provider,
            "model": model,
        },
        use_csrf=True,
        expected={201},
    )
    workspace_id = workspace.get("id")
    stages = workspace.get("stages")
    if not workspace_id or not isinstance(stages, list) or len(stages) != 4:
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
        check("live LLM stream")
        spec_stage = next((s for s in stages if s.get("type") == "spec"), None)
        if spec_stage is None:
            raise SmokeFailure("Created workspace has no spec stage")
        client.stream_stage(spec_stage["id"])

    check("workspace archive")
    client.request(
        "DELETE",
        f"/workspaces/{workspace_id}",
        use_csrf=True,
        expected={204},
    )

    print("[smoke] production smoke passed")


if __name__ == "__main__":
    try:
        run()
    except SmokeFailure as exc:
        print(f"[smoke] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
