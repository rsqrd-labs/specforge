"""
Harness contracts for Phase 4 gap-closure tasks T-050 through T-056.
Every test in this file is RED before the corresponding task is implemented
and GREEN after. Do not edit unless the spec or plan has changed.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import time
from pathlib import Path

from conftest import import_backend, read_backend_file


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"


# ---------------------------------------------------------------------------
# T-050: CSRF middleware
# ---------------------------------------------------------------------------


def test_csrf_module_exists_with_generate_and_verify_functions() -> None:
    """services/security/csrf.py must expose generate_csrf_token and verify_csrf_token."""
    module = import_backend("services.security.csrf")
    assert hasattr(module, "generate_csrf_token"), (
        "csrf.py must expose generate_csrf_token(session_id: str) -> str"
    )
    assert hasattr(module, "verify_csrf_token"), (
        "csrf.py must expose verify_csrf_token(token: str, session_id: str) -> bool"
    )


def test_csrf_token_roundtrip_passes_verification() -> None:
    """A freshly generated token must verify successfully against the same session_id."""
    module = import_backend("services.security.csrf")
    generate = module.generate_csrf_token
    verify = module.verify_csrf_token

    token = generate("user-session-abc")
    assert verify(token, "user-session-abc") is True


def test_csrf_token_fails_verification_with_different_session() -> None:
    """Token generated for session A must not verify against session B."""
    module = import_backend("services.security.csrf")
    generate = module.generate_csrf_token
    verify = module.verify_csrf_token

    token = generate("session-alpha")
    assert verify(token, "session-beta") is False


def test_csrf_token_fails_verification_when_hmac_is_tampered() -> None:
    """Altering any byte of the HMAC portion must cause verification to return False."""
    module = import_backend("services.security.csrf")
    generate = module.generate_csrf_token
    verify = module.verify_csrf_token

    token = generate("legit-session")
    # Flip the last character of the token to tamper with the HMAC
    tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
    assert verify(tampered, "legit-session") is False


def test_csrf_route_registered_in_app() -> None:
    """GET /auth/csrf-token must be present in the FastAPI app's route table."""
    main = import_backend("main")
    paths = {route.path for route in main.create_app().routes}
    assert "/auth/csrf-token" in paths, (
        "GET /auth/csrf-token must be registered so the frontend can fetch a CSRF token"
    )


def test_csrf_middleware_source_validates_x_csrf_token_header() -> None:
    """middleware/csrf.py must read X-CSRF-Token and reject requests that fail verification."""
    source = read_backend_file("middleware", "csrf.py").lower()
    assert "x-csrf-token" in source, (
        "CSRF middleware must read the X-CSRF-Token header"
    )
    assert "403" in source or "forbidden" in source, (
        "CSRF middleware must return 403 on invalid tokens"
    )


def test_csrf_middleware_exempts_oauth_callback_paths() -> None:
    """Auth callback and refresh paths must be exempt from CSRF checking."""
    source = read_backend_file("middleware", "csrf.py").lower()
    for path in ["/auth/callback", "/auth/refresh", "/auth/google"]:
        assert path in source or path.lstrip("/") in source, (
            f"CSRF middleware must exempt {path} — OAuth callbacks cannot set custom headers"
        )


# ---------------------------------------------------------------------------
# T-051: Input sanitization with bleach
# ---------------------------------------------------------------------------


def test_sanitizer_module_exists_with_sanitize_text() -> None:
    """services/security/sanitizer.py must expose sanitize_text(text: str) -> str."""
    module = import_backend("services.security.sanitizer")
    assert hasattr(module, "sanitize_text"), (
        "sanitizer.py must expose sanitize_text(text: str) -> str"
    )


def test_sanitize_text_strips_script_tags() -> None:
    """HTML <script> injection must be stripped to plain text."""
    module = import_backend("services.security.sanitizer")
    result = module.sanitize_text("<script>alert('xss')</script>hello")
    assert "<script>" not in result
    assert "alert" not in result
    assert "hello" in result


def test_sanitize_text_strips_nested_html_tags() -> None:
    """Nested HTML tags must be stripped, preserving only the inner text."""
    module = import_backend("services.security.sanitizer")
    result = module.sanitize_text("<b><i>bold italic</i></b>")
    assert "<b>" not in result
    assert "<i>" not in result
    assert "bold italic" in result


def test_sanitize_text_leaves_plain_text_unchanged() -> None:
    """Plain text without HTML must pass through unchanged."""
    module = import_backend("services.security.sanitizer")
    plain = "Build a task management SaaS with recurring billing."
    assert module.sanitize_text(plain) == plain


def test_workspace_service_calls_sanitize_before_persistence() -> None:
    """workspace_service.py must import and call sanitize_text on user inputs."""
    source = read_backend_file("services", "workspace_service.py")
    assert "sanitize" in source.lower(), (
        "workspace_service.py must call sanitize_text() on name and problem_statement "
        "before persisting to the database"
    )


# ---------------------------------------------------------------------------
# T-052: Hourly auth rate limit tier
# ---------------------------------------------------------------------------


def test_rate_limit_middleware_implements_hourly_login_tier() -> None:
    """RateLimitMiddleware must enforce the 20-attempts-per-hour login tier from spec §7."""
    source = read_backend_file("middleware", "rate_limit.py")

    assert "3600" in source, (
        "rate_limit.py must include a 3600-second (1-hour) window for the hourly login tier"
    )
    assert "20" in source, (
        "rate_limit.py must enforce a limit of 20 login attempts per hour"
    )


def test_rate_limit_both_login_tiers_present_in_source() -> None:
    """Both the 5/5min and 20/hour tiers must coexist in RateLimitMiddleware."""
    source = read_backend_file("middleware", "rate_limit.py")

    assert "300" in source, "5-minute window (300s) tier must be present"
    assert "3600" in source, "1-hour window (3600s) tier must be present"
    assert "5" in source, "Limit of 5 per 5 min must be present"
    assert "20" in source, "Limit of 20 per hour must be present"


# ---------------------------------------------------------------------------
# T-053: Sentry initialization — backend
# ---------------------------------------------------------------------------


def test_backend_main_calls_sentry_sdk_init() -> None:
    """main.py must call sentry_sdk.init() for production error tracking."""
    source = read_backend_file("main.py")
    assert "sentry_sdk" in source, (
        "main.py must import sentry_sdk"
    )
    assert "sentry_sdk.init" in source or "sentry_sdk.init(" in source, (
        "main.py must call sentry_sdk.init() — see T-039 step 2 and T-053"
    )


def test_backend_sentry_init_is_guarded_by_dsn_check() -> None:
    """sentry_sdk.init() must only run when SENTRY_DSN is configured (guard for local dev)."""
    source = read_backend_file("main.py")
    # The init must be inside a conditional that checks for the DSN
    assert "sentry_dsn" in source.lower() or "sentry_dsn" in source, (
        "sentry_sdk.init() must be guarded by a settings.sentry_dsn check "
        "so the app starts cleanly without a DSN in local dev"
    )


# ---------------------------------------------------------------------------
# T-056: Dockerfile + README quickstart
# ---------------------------------------------------------------------------


def test_backend_dockerfile_exists() -> None:
    """backend/Dockerfile must exist for the self-hosting docker-compose flow."""
    dockerfile = BACKEND_ROOT / "Dockerfile"
    assert dockerfile.exists(), (
        "backend/Dockerfile is required for the self-hosting quickstart — "
        "see spec §12 open-source strategy and T-056"
    )


def test_dockerfile_uses_python_312_base_image() -> None:
    """Dockerfile must pin to Python 3.12 to match the project's .python-version."""
    source = read_backend_file("Dockerfile")
    assert "python:3.12" in source, (
        "Dockerfile must use a python:3.12 base image to match .python-version"
    )


def test_dockerfile_runs_gunicorn_with_uvicorn_worker() -> None:
    """Dockerfile CMD must run gunicorn with UvicornWorker (matches Procfile and railway.json)."""
    source = read_backend_file("Dockerfile")
    assert "gunicorn" in source, "Dockerfile must use gunicorn as the process manager"
    assert "UvicornWorker" in source or "uvicorn.workers" in source, (
        "Dockerfile must use gunicorn with UvicornWorker for ASGI support"
    )


def test_docker_compose_includes_api_service() -> None:
    """docker-compose.yml must define an api service so self-hosters can run a single command."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.exists()
    compose = compose_path.read_text(encoding="utf-8")
    assert "api:" in compose or "  api:" in compose, (
        "docker-compose.yml must include an api service for self-hosting — "
        "currently only db and redis are defined"
    )


def test_readme_contains_selfhosting_quickstart() -> None:
    """README.md must contain the four self-hosting steps from spec §12."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "docker-compose" in readme or "docker compose" in readme, (
        "README.md must reference docker-compose for the self-hosting quickstart"
    )
    assert ".env" in readme, (
        "README.md must instruct users to copy .env.example to .env"
    )
    assert "localhost" in readme or "5173" in readme, (
        "README.md must tell users which port to open after starting services"
    )


def test_readme_is_not_placeholder() -> None:
    """README.md must contain more than the placeholder text from T-001."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "setup instructions coming soon" not in readme.lower(), (
        "README.md still contains the placeholder text from T-001. "
        "Replace it with the real quickstart guide as required by T-056."
    )
