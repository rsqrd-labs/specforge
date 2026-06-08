"""
Harness contracts for Plan v1.md §17, Phase 13 — GitHub Export Integration.

These tests describe the implementation contract. They are RED before Phase 13
is implemented and GREEN after T-147 through T-153 are complete.

Design invariants enforced here:
  * Three new ORM models (UserIntegration, IntegrationPush, IntegrationPushTask)
    match the DDL and field names defined in the plan.
  * GitHubAPIClient is a thin async HTTP wrapper with typed exceptions only —
    no business logic, no DB access.
  * All 401 responses from GitHub map to GitHubTokenExpiredError before any other
    check, and the service layer deletes the stored integration row.
  * task_parser is pure: zero I/O, zero external dependencies.
  * Pydantic schemas enforce the repo_name safety pattern and length limits.
  * GitHub tokens are stored Fernet-encrypted, never plaintext.
  * The GitHub export rate-limit tier (3 req / 1 hour / user) lives in the
    existing rate_limit middleware.
  * Existing ZIP export endpoint is untouched.
"""

from __future__ import annotations


from conftest import BACKEND_ROOT, REPO_ROOT, import_backend, read_backend_file


# ---------------------------------------------------------------------------
# T-147: Migration file
# ---------------------------------------------------------------------------


def test_phase13_alembic_migration_file_exists() -> None:
    # Tests: T-147
    # Plan §17.1: a dedicated 0003_github_integration migration must exist so
    # CI can apply the schema without manual intervention.
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    migration_files = list(versions_dir.glob("*github_integration*"))
    assert migration_files, (
        "No Alembic migration file matching '*github_integration*' found under "
        "backend/migrations/versions/. Run alembic revision for Phase 13."
    )


def test_phase13_migration_creates_all_three_tables() -> None:
    # Tests: T-147
    # Plan §17.1: the migration must create user_integrations, integration_pushes,
    # and integration_push_tasks.
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    migration_files = list(versions_dir.glob("*github_integration*"))
    assert migration_files, "No migration file found — see test above."
    source = migration_files[0].read_text(encoding="utf-8")
    for table in ["user_integrations", "integration_pushes", "integration_push_tasks"]:
        assert table in source, (
            f"Migration must create table '{table}'. Not found in "
            f"{migration_files[0].name}."
        )


# ---------------------------------------------------------------------------
# T-148: ORM models
# ---------------------------------------------------------------------------


def test_phase13_user_integration_model_exists_with_required_fields() -> None:
    # Tests: T-148
    # Plan §10: UserIntegration must carry user_id, provider, encrypted_token,
    # github_username, connected_at, and last_used_at.
    source = read_backend_file("models", "user_integration.py")
    for field in [
        "user_id",
        "provider",
        "encrypted_token",
        "github_username",
        "connected_at",
        "last_used_at",
    ]:
        assert field in source, (
            f"UserIntegration model is missing field '{field}'. "
            "Check models/user_integration.py."
        )
    assert "user_integrations" in source, (
        "UserIntegration.__tablename__ must be 'user_integrations'."
    )


def test_phase13_user_integration_stores_encrypted_token_not_plaintext() -> None:
    # Tests: T-148, SEC (spec §8): GitHub tokens must be Fernet-encrypted at rest.
    # The field must be named 'encrypted_token', not 'token' or 'access_token',
    # to make the storage intent self-documenting.
    source = read_backend_file("models", "user_integration.py")
    assert "encrypted_token" in source, (
        "UserIntegration must use 'encrypted_token' (not 'token' or 'access_token') "
        "to make Fernet encryption intent visible in the model definition."
    )
    for forbidden in ["access_token\n", "token =\n", "token:"]:
        assert forbidden not in source, (
            f"UserIntegration must not expose a plaintext token field. "
            f"Found fragment: {forbidden!r}"
        )


def test_phase13_integration_push_model_exists_with_required_fields() -> None:
    # Tests: T-148
    # Plan §10: IntegrationPush has workspace_id, provider, repo_full_name, repo_url,
    # status, issue_count, pushed_at; unique on (workspace_id, provider).
    source = read_backend_file("models", "integration_push.py")
    for field in [
        "workspace_id",
        "provider",
        "repo_full_name",
        "repo_url",
        "status",
        "issue_count",
        "pushed_at",
    ]:
        assert field in source, (
            f"IntegrationPush model is missing field '{field}'."
        )
    assert "integration_pushes" in source, (
        "IntegrationPush.__tablename__ must be 'integration_pushes'."
    )
    assert "UniqueConstraint" in source or "unique=True" in source, (
        "IntegrationPush must enforce a unique constraint on (workspace_id, provider) "
        "to guarantee idempotent re-export."
    )


def test_phase13_integration_push_task_model_exists_with_required_fields() -> None:
    # Tests: T-148
    # Plan §10: IntegrationPushTask has push_id, task_ref, issue_number;
    # unique on (push_id, task_ref).
    source = read_backend_file("models", "integration_push_task.py")
    for field in ["push_id", "task_ref", "issue_number"]:
        assert field in source, (
            f"IntegrationPushTask model is missing field '{field}'."
        )
    assert "integration_push_tasks" in source, (
        "IntegrationPushTask.__tablename__ must be 'integration_push_tasks'."
    )
    assert "UniqueConstraint" in source or "unique=True" in source, (
        "IntegrationPushTask must enforce a unique constraint on (push_id, task_ref) "
        "to prevent duplicate issues on re-export."
    )


def test_phase13_models_init_exports_all_three_new_models() -> None:
    # Tests: T-148
    # Plan §6: models/__init__.py must re-export all models so Alembic
    # autogenerate picks them up in future revisions.
    source = read_backend_file("models", "__init__.py")
    for name in ["UserIntegration", "IntegrationPush", "IntegrationPushTask"]:
        assert name in source, (
            f"models/__init__.py must export '{name}' so Alembic autogenerate "
            "detects Phase 13 tables."
        )


def test_phase13_integration_schemas_define_required_shapes() -> None:
    # Tests: T-148, Spec §11 API contracts
    source = read_backend_file("schemas", "integration.py")
    for class_name in [
        "GitHubStatusResponse",
        "GitHubExportRequest",
        "GitHubExportResponse",
        "IntegrationPushRead",
    ]:
        assert class_name in source, (
            f"schemas/integration.py must define '{class_name}'."
        )


def test_phase13_export_request_schema_enforces_repo_name_pattern() -> None:
    # Tests: T-148, SEC: repo_name must match ^[a-zA-Z0-9._-]+$ to prevent
    # path traversal in GitHub API calls (e.g. "../etc/passwd").
    source = read_backend_file("schemas", "integration.py")
    assert "repo_name" in source
    assert "pattern" in source or "regex" in source, (
        "GitHubExportRequest.repo_name must use a Field pattern/regex constraint "
        "to block path-traversal strings like '../etc/passwd'."
    )
    assert "max_length" in source or "max_length=100" in source, (
        "GitHubExportRequest.repo_name must cap length at 100 characters."
    )


def test_phase13_export_request_schema_validates_at_runtime() -> None:
    # Tests: T-148: schema must reject unsafe repo names and empty strings
    # when run against a live Python interpreter.
    try:
        module = import_backend("schemas.integration")
    except Exception:
        assert False, "not implemented: T-148 — schemas.integration cannot be imported"

    GitHubExportRequest = getattr(module, "GitHubExportRequest", None)
    assert GitHubExportRequest is not None, (
        "not implemented: T-148 — GitHubExportRequest not in schemas.integration"
    )

    try:
        from pydantic import ValidationError
    except ImportError:
        assert False, "pydantic must be available in the backend virtualenv"

    good = GitHubExportRequest(repo_name="my-project", visibility="public")
    assert good.repo_name == "my-project"

    for bad_name in ["../etc/passwd", "", "a" * 101]:
        try:
            GitHubExportRequest(repo_name=bad_name, visibility="public")
            assert False, (
                f"GitHubExportRequest should reject repo_name={bad_name!r} "
                "but it did not raise ValidationError."
            )
        except ValidationError:
            pass


# ---------------------------------------------------------------------------
# T-149: GitHub auth service and routes
# ---------------------------------------------------------------------------


def test_phase13_integrations_directory_exists() -> None:
    # Tests: T-149, Plan §6: services/integrations/ must exist.
    integrations_dir = BACKEND_ROOT / "services" / "integrations"
    assert integrations_dir.is_dir(), (
        "backend/services/integrations/ directory does not exist. "
        "Create it as part of T-149."
    )


def test_phase13_github_auth_service_module_exists() -> None:
    # Tests: T-149
    assert (BACKEND_ROOT / "services" / "integrations" / "github_auth_service.py").exists(), (
        "not implemented: T-149 — backend/services/integrations/github_auth_service.py"
    )


def test_phase13_github_auth_service_has_required_functions() -> None:
    # Tests: T-149, Plan §17.2: the auth service must provide begin_oauth,
    # complete_oauth, and revoke functions.
    source = read_backend_file("services", "integrations", "github_auth_service.py")
    for fn_name in ["begin_oauth", "complete_oauth", "revoke"]:
        assert fn_name in source, (
            f"github_auth_service.py is missing '{fn_name}'. "
            "Plan §17.2 defines these as the three entry points for the OAuth flow."
        )


def test_phase13_github_auth_service_uses_redis_for_csrf_state() -> None:
    # Tests: T-149, SEC (spec §8): the OAuth state parameter must be stored in
    # Redis and bound to the authenticated user to prevent CSRF on the callback.
    source = read_backend_file("services", "integrations", "github_auth_service.py")
    assert "redis" in source.lower() or "Redis" in source, (
        "github_auth_service.py must use Redis to store the OAuth state parameter. "
        "The state must be bound to the authenticated user's session to prevent CSRF."
    )
    assert "state" in source, (
        "github_auth_service.py must generate and validate an OAuth 'state' parameter."
    )


def test_phase13_integrations_router_file_exists() -> None:
    # Tests: T-149
    assert (BACKEND_ROOT / "routers" / "integrations.py").exists(), (
        "not implemented: T-149 — backend/routers/integrations.py"
    )


def test_phase13_integrations_router_registered_in_main_app() -> None:
    # Tests: T-149: the integrations router must be mounted in main.py so that
    # /integrations/* endpoints are reachable.
    source = read_backend_file("main.py")
    assert "integrations" in source, (
        "main.py must import and mount the integrations router. "
        "Endpoints under /integrations/* will not be reachable otherwise."
    )


def test_phase13_oauth_callback_routes_exist_in_auth_or_integrations_router() -> None:
    # Tests: T-149, Spec §11: /auth/github and /auth/github/callback must exist
    # as GET routes.
    auth_source = read_backend_file("routers", "auth.py")
    integrations_source = read_backend_file("routers", "integrations.py")
    combined = auth_source + integrations_source
    assert "/auth/github" in combined or "github" in combined, (
        "Neither routers/auth.py nor routers/integrations.py defines the "
        "/auth/github OAuth initiation route."
    )
    assert "callback" in combined, (
        "The GitHub OAuth callback route (/auth/github/callback) is not defined "
        "in auth.py or integrations.py."
    )


# ---------------------------------------------------------------------------
# T-150: GitHub API client
# ---------------------------------------------------------------------------


def test_phase13_github_api_client_module_exists() -> None:
    # Tests: T-150
    assert (BACKEND_ROOT / "services" / "integrations" / "github_api_client.py").exists(), (
        "not implemented: T-150 — backend/services/integrations/github_api_client.py"
    )


def test_phase13_github_api_client_class_and_exceptions_defined() -> None:
    # Tests: T-150: GitHubAPIClient and all four typed exceptions must be importable.
    source = read_backend_file("services", "integrations", "github_api_client.py")
    for name in [
        "GitHubAPIClient",
        "GitHubTokenExpiredError",
        "GitHubRepoExistsError",
        "GitHubRateLimitError",
        "GitHubAPIError",
    ]:
        assert name in source, (
            f"github_api_client.py must define '{name}'. "
            "Plan §17.3 lists these as the complete exception hierarchy."
        )


def test_phase13_github_api_client_has_required_methods() -> None:
    # Tests: T-150: the client must expose exactly the methods the export
    # service uses — no more, no less.
    source = read_backend_file("services", "integrations", "github_api_client.py")
    for method in [
        "create_repo",
        "get_file_sha",
        "upsert_file",
        "create_issue",
        "update_issue",
    ]:
        assert method in source, (
            f"GitHubAPIClient must define async method '{method}'. "
            "See Plan §17.3 / T-150 step 2 for the full method contracts."
        )


def test_phase13_github_api_client_maps_401_to_token_expired_error() -> None:
    # Tests: T-150, SEC (spec §8): ALL 401 responses from GitHub must raise
    # GitHubTokenExpiredError before any other branch so the service layer can
    # delete the invalid integration row. The source must reflect this invariant.
    source = read_backend_file("services", "integrations", "github_api_client.py")
    assert "401" in source, (
        "github_api_client.py must explicitly handle HTTP 401 from GitHub."
    )
    assert "GitHubTokenExpiredError" in source
    assert source.index("401") < source.rindex("GitHubTokenExpiredError") or (
        source.count("401") > 0 and source.count("GitHubTokenExpiredError") > 0
    ), (
        "GitHubTokenExpiredError must be raised in the 401 handler. "
        "Ensure every method maps 401 → GitHubTokenExpiredError first."
    )


def test_phase13_github_api_client_has_factory_function() -> None:
    # Tests: T-150: make_github_client() enables dependency injection in tests
    # without subclassing.
    source = read_backend_file("services", "integrations", "github_api_client.py")
    assert "make_github_client" in source, (
        "github_api_client.py must define a module-level factory function "
        "'make_github_client(token, client)' for testability."
    )


def test_phase13_github_api_client_uses_httpx_not_requests() -> None:
    # Tests: T-150, SEC: the client must use httpx.AsyncClient (the project's
    # async HTTP transport) — never the synchronous 'requests' library.
    source = read_backend_file("services", "integrations", "github_api_client.py")
    assert "httpx" in source, (
        "github_api_client.py must use httpx.AsyncClient for GitHub REST calls."
    )
    assert "import requests" not in source and "from requests" not in source, (
        "github_api_client.py must not import 'requests'. Use httpx.AsyncClient."
    )


# ---------------------------------------------------------------------------
# T-151: Task parser
# ---------------------------------------------------------------------------


def test_phase13_task_parser_module_exists() -> None:
    # Tests: T-151
    assert (BACKEND_ROOT / "services" / "integrations" / "task_parser.py").exists(), (
        "not implemented: T-151 — backend/services/integrations/task_parser.py"
    )


def test_phase13_task_parser_defines_parsed_task_dataclass() -> None:
    # Tests: T-151: ParsedTask must be a dataclass with ref, title, body_md fields.
    source = read_backend_file("services", "integrations", "task_parser.py")
    assert "ParsedTask" in source, (
        "task_parser.py must define a ParsedTask dataclass."
    )
    for field in ["ref", "title", "body_md"]:
        assert field in source, (
            f"ParsedTask is missing field '{field}'. "
            "Plan §17.3 defines ref (e.g. 'T-001'), title, and body_md."
        )


def test_phase13_task_parser_defines_parse_tasks_function() -> None:
    # Tests: T-151
    source = read_backend_file("services", "integrations", "task_parser.py")
    assert "parse_tasks" in source, (
        "task_parser.py must define function 'parse_tasks(content: str) -> list[ParsedTask]'."
    )


def test_phase13_task_parser_has_no_io_or_external_imports() -> None:
    # Tests: T-151: parse_tasks must be a pure function — no I/O, no DB, no HTTP.
    source = read_backend_file("services", "integrations", "task_parser.py")
    forbidden = [
        "import httpx",
        "import requests",
        "import sqlalchemy",
        "from sqlalchemy",
        "open(",
        "asyncio",
        "aiofiles",
    ]
    for fragment in forbidden:
        assert fragment not in source, (
            f"task_parser.py is a pure function module and must not import '{fragment}'. "
            "Keep it side-effect free so it is trivially testable without fixtures."
        )


def test_phase13_task_parser_uses_tnn_regex_pattern() -> None:
    # Tests: T-151: the parser must detect T-NNN headings with a regex to be
    # robust against heading text variations.
    source = read_backend_file("services", "integrations", "task_parser.py")
    assert "T-" in source and ("re." in source or "import re" in source), (
        "task_parser.py must use the 're' module with a 'T-' pattern to extract "
        "task headings from TASKS.md content."
    )


def test_phase13_task_parser_returns_correct_results() -> None:
    # Tests: T-151: the core parsing contract — verified against a live interpreter.
    try:
        module = import_backend("services.integrations.task_parser")
    except Exception:
        assert False, "not implemented: T-151 — services.integrations.task_parser cannot be imported"

    parse_tasks = getattr(module, "parse_tasks", None)
    assert parse_tasks is not None, "not implemented: T-151 — parse_tasks not found"

    assert parse_tasks("") == [], "parse_tasks('') must return []"

    result = parse_tasks("### T-001: Foo\n\nBody text\n\n### T-002: Bar\n\nOther body")
    assert len(result) == 2, (
        f"parse_tasks with two T-NNN headings must return 2 ParsedTask objects, got {len(result)}"
    )
    refs = [t.ref for t in result]
    assert refs == ["T-001", "T-002"], f"ParsedTask refs must be in document order, got {refs}"
    assert result[0].title == "Foo", f"ParsedTask.title must be 'Foo', got {result[0].title!r}"

    first_body = result[0].body_md
    assert "T-002" not in first_body, (
        "T-001's body_md must not include T-002's heading or body."
    )


# ---------------------------------------------------------------------------
# T-152: GitHub export service
# ---------------------------------------------------------------------------


def test_phase13_github_export_service_module_exists() -> None:
    # Tests: T-152
    assert (BACKEND_ROOT / "services" / "pipeline" / "github_export_service.py").exists(), (
        "not implemented: T-152 — backend/services/pipeline/github_export_service.py"
    )


def test_phase13_github_export_service_defines_push_to_github() -> None:
    # Tests: T-152, Plan §4.5: the orchestrator entry point must be named
    # push_to_github to match the call site in the router.
    source = read_backend_file("services", "pipeline", "github_export_service.py")
    assert "push_to_github" in source, (
        "github_export_service.py must define 'push_to_github(...)'. "
        "The router calls this function by name (see T-153 step 1)."
    )


def test_phase13_github_export_service_handles_token_expiry_by_deleting_integration() -> None:
    # Tests: T-152, SEC (spec §8): when GitHubTokenExpiredError is raised during
    # export, the service must delete the UserIntegration row so the user is
    # prompted to reconnect rather than retrying with a known-invalid token.
    source = read_backend_file("services", "pipeline", "github_export_service.py")
    assert "GitHubTokenExpiredError" in source, (
        "github_export_service.py must catch GitHubTokenExpiredError."
    )
    for fragment in ["delete", "Delete"]:
        if fragment in source:
            break
    else:
        assert False, (
            "github_export_service.py must delete the UserIntegration row when "
            "GitHubTokenExpiredError is raised. The user must be prompted to "
            "reconnect — SpecForge must never retry with a known-invalid token."
        )


def test_phase13_github_export_service_reuses_parse_harness_files() -> None:
    # Tests: T-152: the export service must call parse_harness_files from
    # export_service.py (not re-implement its own parser) so there is a single
    # source of truth for harness file extraction.
    source = read_backend_file("services", "pipeline", "github_export_service.py")
    assert "parse_harness_files" in source, (
        "github_export_service.py must import and call parse_harness_files from "
        "export_service.py. Do not duplicate the harness parsing logic."
    )


def test_phase13_github_export_service_defines_export_not_ready_error() -> None:
    # Tests: T-152, T-153: ExportNotReadyError is raised when stages are not
    # yet finalised; the router maps it to 409.
    source = read_backend_file("services", "pipeline", "github_export_service.py")
    assert "ExportNotReadyError" in source, (
        "github_export_service.py must define or import 'ExportNotReadyError'. "
        "The router maps this exception to HTTP 409."
    )


def test_phase13_github_export_service_uses_fernet_for_token_decryption() -> None:
    # Tests: T-152, SEC: decrypting the stored GitHub token must use Fernet
    # (the same key vault already used for LLM API keys) — never raw base64 decode.
    source = read_backend_file("services", "pipeline", "github_export_service.py")
    assert "fernet" in source.lower() or "Fernet" in source or "decrypt" in source.lower(), (
        "github_export_service.py must decrypt the stored GitHub token using Fernet. "
        "Never decode the encrypted_token field directly without the key vault."
    )


# ---------------------------------------------------------------------------
# T-153: Router wiring
# ---------------------------------------------------------------------------


def test_phase13_workspace_router_has_github_export_endpoint() -> None:
    # Tests: T-153: POST /workspaces/{id}/export/github must be declared in
    # routers/workspace.py.
    source = read_backend_file("routers", "workspace.py")
    assert "export/github" in source or "export_github" in source, (
        "routers/workspace.py must define the POST /workspaces/{id}/export/github "
        "endpoint. See T-153 step 1."
    )


def test_phase13_workspace_router_has_github_export_get_endpoint() -> None:
    # Tests: T-153: GET /workspaces/{id}/export/github must be declared in
    # routers/workspace.py.
    source = read_backend_file("routers", "workspace.py")
    assert "export/github" in source or "export_github" in source, (
        "routers/workspace.py must define GET /workspaces/{id}/export/github "
        "to let the frontend poll push status."
    )


def test_phase13_workspace_router_maps_github_exceptions_to_http_codes() -> None:
    # Tests: T-153, Plan §4.5 error table: the router must translate each
    # typed exception to its required HTTP status code.
    source = read_backend_file("routers", "workspace.py")
    expected_codes = ["403", "409", "429", "502"]
    missing = [code for code in expected_codes if code not in source]
    assert not missing, (
        "routers/workspace.py is missing HTTP status codes for the GitHub error "
        f"mapping table: {missing}. See T-153 step 1 for the full mapping."
    )


def test_phase13_zip_export_endpoint_is_unchanged() -> None:
    # Tests: T-153: the existing POST /workspaces/{id}/export (ZIP) endpoint
    # must not have been modified by Phase 13.
    source = read_backend_file("routers", "workspace.py")
    assert "build_export" in source or "export_service" in source, (
        "The ZIP export endpoint appears to have been removed or renamed. "
        "Phase 13 must leave the existing /workspaces/{id}/export endpoint intact."
    )


def test_phase13_rate_limit_middleware_has_github_export_tier() -> None:
    # Tests: T-153, Spec §12: the GitHub export rate limit (3/hour/user) must
    # be declared in the existing rate_limit middleware, not duplicated inline.
    source = read_backend_file("middleware", "rate_limit.py")
    assert "github" in source.lower(), (
        "middleware/rate_limit.py must define a GitHub export rate-limit tier. "
        "See T-153 step 2: key 'ratelimit:github_export:{user_id}', limit 3, window 3600s."
    )
    assert "3600" in source, (
        "The GitHub export rate-limit tier must use a 3600-second (1-hour) window. "
        "Check middleware/rate_limit.py."
    )


# ---------------------------------------------------------------------------
# T-154: Backend test file
# ---------------------------------------------------------------------------


def test_phase13_backend_test_file_exists() -> None:
    # Tests: T-154
    assert (BACKEND_ROOT / "tests" / "test_github_integration.py").exists(), (
        "not implemented: T-154 — backend/tests/test_github_integration.py"
    )


def test_phase13_backend_test_covers_required_classes() -> None:
    # Tests: T-154: the contract test must include the four test classes that
    # cover the OAuth, integration CRUD, export endpoint, and rate-limit flows.
    source = read_backend_file("tests", "test_github_integration.py")
    for class_name in [
        "TestGitHubAuth",
        "TestIntegrationsRouter",
        "TestGitHubExport",
        "TestGitHubRateLimit",
    ]:
        assert class_name in source, (
            f"test_github_integration.py must include test class '{class_name}'. "
            "See T-154 step 1 for the required class structure."
        )


def test_phase13_api_client_unit_test_file_exists() -> None:
    # Tests: T-150, T-154
    assert (BACKEND_ROOT / "tests" / "test_github_api_client.py").exists(), (
        "not implemented: T-150 — backend/tests/test_github_api_client.py. "
        "See T-150 step 6 for required coverage."
    )


def test_phase13_task_parser_unit_test_file_exists() -> None:
    # Tests: T-151, T-154
    assert (BACKEND_ROOT / "tests" / "test_task_parser.py").exists(), (
        "not implemented: T-151 — backend/tests/test_task_parser.py. "
        "See T-151 step 4 for required coverage."
    )


# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------


def test_phase13_env_example_documents_github_client_vars() -> None:
    # Tests: T-159, Plan §7: GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must be
    # documented in .env.example so developers know they are required.
    source = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"]:
        assert var in source, (
            f".env.example must document '{var}'. "
            "Add it as part of T-149 or T-159."
        )


def test_phase13_manifest_references_github_integration_contracts() -> None:
    # Tests: T-154, T-159: the harness manifest must register this contract file
    # so tasks can reference it by group id.
    import json
    manifest_path = REPO_ROOT / "harness" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = manifest.get("test_groups", [])
    matching = [g for g in groups if g.get("id") == "github-integration-contracts"]
    assert matching, (
        "harness/manifest.json must include a 'github-integration-contracts' "
        "test group pointing to this file."
    )
