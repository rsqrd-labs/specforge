from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import import_backend


def test_create_app_factory_returns_fastapi_app() -> None:
    main = import_backend("main")

    assert hasattr(main, "create_app"), "main.py must expose create_app()"
    app = main.create_app()

    assert app.title
    assert any(route.path == "/health" for route in app.routes)
    assert getattr(main, "app", None) is not None, "main.py must expose app for uvicorn"


def test_health_endpoint_shape() -> None:
    main = import_backend("main")
    client = TestClient(main.create_app())

    response = client.get("/health")

    assert response.status_code in {200, 503}
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert set(payload).issuperset({"status", "db", "redis", "version"})


def test_public_routes_include_auth_workspace_stage_credit_and_provider_contracts() -> None:
    main = import_backend("main")
    paths = {route.path for route in main.create_app().routes}

    expected = {
        "/auth/google",
        "/auth/callback",
        "/auth/refresh",
        "/auth/logout",
        "/auth/me",
        "/workspaces",
        "/workspaces/{id}",
        "/workspaces/{id}/export",
        "/stages/{id}",
        "/stages/{id}/generate",
        "/stages/{id}/refine",
        "/stages/{id}/regenerate",
        "/stages/{id}/finalise",
        "/stages/{id}/rollback",
        "/stages/{id}/versions",
        "/stages/{id}/eval",
        "/credits/balance",
        "/credits/history",
    }

    assert expected.issubset(paths), "Missing API routes: " + ", ".join(sorted(expected - paths))
