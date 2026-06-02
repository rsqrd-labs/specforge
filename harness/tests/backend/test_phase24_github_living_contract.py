"""
Harness contracts for Phase 24 - GitHub Living System of Record.

These tests are RED before T-265 through T-286 are implemented and GREEN after.
They are the executable verifiability layer for the coding agent: each assertion
maps to a task in `Plan v1.md` §24 and a requirement in `V1 spec.md` v2.0.0 §4.14.

The contract is source-inspecting (it reads backend files and asserts structure,
tokens, ordering, and invariants) so it runs without booting the app, the queue,
or GitHub. It deliberately pins the load-bearing edge cases that are easy to get
subtly wrong:

  - export must move OFF the request path onto the worker (202, not inline);
  - the webhook must verify the HMAC and reject BEFORE any DB/queue work;
  - rotation must accept TWO webhook secrets;
  - a duplicate `X-GitHub-Delivery` must be idempotently skipped;
  - reconciliation must key on the immutable `repo_id`, never `repo_full_name`;
  - a confused-deputy event must not mutate another tenant's pushes;
  - out-of-order events must not regress a task already `done`;
  - backfill must filter out pull-request rows from the issues endpoint;
  - PR mode must handle the `Workflows: write` 403 and refetch-SHA on 409;
  - `AGENTS.md` generation must never clobber existing file content;
  - increments must pin stable, content-derived `task_ref`s (no duplicate issues);
  - the PR-diff evaluator must be a NEW module, fail-open, and NOT the critic;
  - installation tokens / the App private key / raw payloads must never be logged;
  - Phase 13 (the v1 OAuth path) must be RETAINED, not deleted (append-only).

Task map:
  T-265 migration 0016 (ALTER pushes/push_tasks + CREATE installs/webhook_events)
  T-266 ORM models + Pydantic schemas
  T-267 GitHub App auth + Redis-cached TokenProvider
  T-268 API client refactored to per-call installation tokens
  T-269 arq queue + worker; export enqueues + 202
  T-270 App install flow + lifecycle webhooks + v1-OAuth migration
  T-271 webhook ingest (verify -> dedup -> enqueue -> 2xx)
  T-272 reconcile job (issue/PR closed -> task done)
  T-273 drift detection + backfill + resync
  T-274 per-installation rate governor + per-repo write serialization
  T-275 frontend (see harness/tests/frontend/phase24-github-living.contract.test.ts)
  T-276 PR + harness-tests export mode
  T-277 agent-ready issues + AGENTS.md
  T-278 increments migration 0017 + models
  T-279 delta-aware increment generation + task_ref scheme
  T-280 incremental GitHub sync + idea backlog
  T-281 Projects v2 GraphQL board + milestones
  T-282 status checks + new fail-open PR-diff evaluator
  T-283 config/security/rate-limits
  T-284 observability
  T-285 this contract + frontend contract
  T-286 docs / runbook / release gate
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import BACKEND_ROOT, REPO_ROOT, read_backend_file


# ---------------------------------------------------------------------------
# Constants — the surface this phase is contracted to build
# ---------------------------------------------------------------------------

NEW_INTEGRATION_SERVICES = [
    ("services", "integrations", "github_app_auth.py"),
    ("services", "integrations", "github_reconcile.py"),
    ("services", "integrations", "github_governor.py"),
    ("services", "integrations", "pr_export_builder.py"),
    ("services", "integrations", "agents_md_builder.py"),
    ("services", "integrations", "pr_evaluator.py"),
]

WEBHOOK_PATH = "/integrations/github/webhook"
INSTALL_PATHS = [
    "/integrations/github/install",
    "/integrations/github/setup",
]
SYNC_PATHS = [
    "/workspaces/{id}/sync",
    "/workspaces/{id}/sync/resync",
    "/workspaces/{id}/sync/backfill",
]
INCREMENT_PATHS = [
    "/workspaces/{id}/increments",
    "/workspaces/{id}/ideas",
]

WORKER_JOBS = [
    "export_push",
    "reconcile_event",
    "backfill_repo",
    "increment_push",
    "projects_sync",
    "pr_check",
]

GITHUB_METRICS = [
    "specforge_github_webhook_received_total",
    "specforge_github_webhook_verified_total",
    "specforge_github_webhook_deduped_total",
    "specforge_github_webhook_failed_total",
    "specforge_github_reconcile_lag_seconds",
    "specforge_github_export_total",
    "specforge_github_pr_total",
    "specforge_github_check_total",
    "specforge_github_token_mint_total",
    "specforge_github_job_retries_total",
    "specforge_github_job_deadlettered_total",
    "specforge_github_queue_depth",
]

GITHUB_APP_CONFIG = [
    "github_app_id",
    "github_app_slug",
    "github_app_private_key",
    "github_app_webhook_secret",
]

REQUIRED_ISSUE_SECTIONS = [
    "Context",
    "Acceptance criteria",
    "Files",
    "The test that must pass",
    "Spec links",
]

AGENT_LABELS = ["specforge", "stage:tasks", "ready-for-agent"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_repo_file(*parts: str) -> str:
    path = REPO_ROOT.joinpath(*parts)
    assert path.exists(), f"Missing repository file: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _read_repo_optional(*parts: str) -> str | None:
    path = REPO_ROOT.joinpath(*parts)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _read_backend_optional(*parts: str) -> str | None:
    path = BACKEND_ROOT.joinpath(*parts)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _combined_migrations() -> str:
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    assert versions_dir.exists(), "backend/migrations/versions must exist."
    migration_files = sorted(versions_dir.glob("*.py"))
    assert migration_files, "backend/migrations/versions must contain migration files."
    return "\n\n".join(p.read_text(encoding="utf-8") for p in migration_files)


def _combined_github_services() -> str:
    """Concatenate the new + existing integration service files.

    RED-before / GREEN-after: fails with a clear message until the new service
    modules from T-267 through T-282 exist.
    """
    pieces: list[str] = []
    missing: list[str] = []
    for rel in NEW_INTEGRATION_SERVICES:
        path = BACKEND_ROOT.joinpath(*rel)
        if path.exists():
            pieces.append(path.read_text(encoding="utf-8"))
        else:
            missing.append("/".join(rel))
    # the pre-existing files this phase extends
    for rel in [
        ("services", "integrations", "github_api_client.py"),
        ("services", "integrations", "task_parser.py"),
        ("services", "pipeline", "github_export_service.py"),
        ("services", "pipeline", "increment_service.py"),
    ]:
        path = BACKEND_ROOT.joinpath(*rel)
        if path.exists():
            pieces.append(path.read_text(encoding="utf-8"))
    assert not missing, (
        "Expected Phase 24 integration service modules to exist (T-267..T-282): "
        f"{missing}"
    )
    return "\n\n".join(pieces)


def _routers_blob() -> str:
    """integrations + workspace routers, where the new endpoints live."""
    pieces = []
    for rel in [("routers", "integrations.py"), ("routers", "workspace.py")]:
        src = _read_backend_optional(*rel)
        if src:
            pieces.append(src)
    assert pieces, "Expected routers/integrations.py and routers/workspace.py to exist."
    return "\n\n".join(pieces)


def _function_source(src: str, async_def_name: str) -> str:
    """Return the body of a route handler from its `async def`/`def` to the next
    decorated handler. Used for token-ordering assertions within one handler."""
    m = re.search(rf"(async\s+def|def)\s+{re.escape(async_def_name)}\b", src)
    assert m, f"Expected a handler named {async_def_name!r} in the source."
    start = m.start()
    nxt = re.search(r"\n@router\.", src[start + 1 :])
    end = start + 1 + nxt.start() if nxt else len(src)
    return src[start:end]


def _assert_all(source: str, required: list[str], context: str) -> None:
    missing = [v for v in required if v not in source]
    assert not missing, f"{context} missing required tokens: {missing}"


def _assert_any(source: str, options: list[str], context: str) -> None:
    assert any(o in source for o in options), f"{context} must contain one of: {options}"


# ===========================================================================
# T-265 / T-278 — Data model & migrations
# ===========================================================================


def test_t265_github_installation_model_exists_with_core_fields() -> None:
    src = read_backend_file("models", "github_installation.py")
    assert "class GitHubInstallation" in src, "models/github_installation.py must define GitHubInstallation. T-265/T-266."
    assert "github_installations" in src, "GitHubInstallation must map to github_installations. T-265."
    _assert_all(
        src,
        [
            "installation_id",
            "account_login",
            "account_type",
            "repository_selection",
            "user_id",
            "suspended_at",
        ],
        "GitHubInstallation ORM model",
    )


def test_t265_github_webhook_event_model_exists_and_mirrors_stripe() -> None:
    src = _read_backend_optional("models", "github_webhook_event.py") or _read_backend_optional(
        "models", "integration_push.py"
    ) or ""
    # the model may live in its own file or beside the integration models
    blob = src + (read_backend_file("models", "__init__.py"))
    assert "GitHubWebhookEvent" in blob, (
        "A GitHubWebhookEvent model must exist (idempotency table mirroring StripeWebhookEvent). T-265/T-266."
    )
    full = "".join(
        _read_backend_optional("models", name) or ""
        for name in ["github_webhook_event.py", "integration_push.py"]
    )
    _assert_all(full or blob, ["delivery_id", "event_type", "received_at"], "GitHubWebhookEvent model")


def test_t265_models_init_exports_new_github_models() -> None:
    src = read_backend_file("models", "__init__.py")
    for symbol in ["GitHubInstallation", "GitHubWebhookEvent"]:
        assert symbol in src, f"models/__init__.py must export {symbol}. T-266."


def test_t265_integration_push_model_gains_repo_key_and_mode_fields() -> None:
    src = read_backend_file("models", "integration_push.py")
    _assert_all(
        src,
        [
            "repo_id",
            "export_mode",
            "branch_name",
            "pr_number",
            "source_stage_version_id",
            "increment_id",
            "installation_id",
        ],
        "IntegrationPush model (Phase 24 fields, spec §10)",
    )
    # the new stale status must be representable
    assert "stale" in src, "IntegrationPush.status must allow 'stale' (disconnect/drift). T-265."


def test_t265_integration_push_task_model_gains_sync_state_fields() -> None:
    src = read_backend_file("models", "integration_push_task.py")
    _assert_all(
        src,
        ["state", "done_at", "done_via", "synced_at", "increment_id"],
        "IntegrationPushTask model (sync fields, spec §10)",
    )
    assert "open" in src and "done" in src, "IntegrationPushTask.state must be open|done. T-265/T-266."
    assert "pr_merge" in src and "manual" in src, "IntegrationPushTask.done_via must be pr_merge|manual. T-265/T-272."


def test_t265_migration_0016_creates_install_and_webhook_tables() -> None:
    src = _combined_migrations()
    assert "github_installations" in src, "Migration 0016 must create github_installations. T-265."
    assert "github_webhook_events" in src, "Migration 0016 must create github_webhook_events. T-265."
    # unique keys for idempotency / identity
    assert re.search(r"installation_id", src) and re.search(r"unique", src, re.I), (
        "github_installations.installation_id must be unique. T-265."
    )
    assert "delivery_id" in src, "github_webhook_events.delivery_id must be unique (dedup). T-265."


def test_t265_migration_0016_alters_integration_pushes_with_new_columns() -> None:
    src = _combined_migrations()
    for col in [
        "repo_id",
        "export_mode",
        "branch_name",
        "pr_number",
        "source_stage_version_id",
        "installation_id",
    ]:
        assert col in src, f"Migration must add integration_pushes.{col}. T-265 (matches spec §10)."
    assert "add_column" in src or "ADD COLUMN" in src.upper(), (
        "Phase 24 migration must ALTER integration_pushes (add_column), not recreate it. T-265."
    )


def test_t265_migration_replaces_provider_unique_with_partial_live_repo_index() -> None:
    src = _combined_migrations()
    # the old one-active-push-per-provider constraint is dropped
    assert "uq_integration_push_workspace_provider" in src and re.search(
        r"drop_constraint|DROP CONSTRAINT", src, re.I
    ), (
        "Migration must DROP uq_integration_push_workspace_provider (was workspace+provider). T-265."
    )
    # Replaced with one-LIVE-push-per-repo partial unique index keyed on repo_id.
    # The status enum is pending/completed/failed/stale — there is NO 'active' literal,
    # so the predicate MUST be `status <> 'failed'`. A `status = 'active'` predicate matches
    # zero rows and silently disables the uniqueness guard. (Scoped to the integration_pushes
    # index by name so the legitimate stripe_credit_packs `status='active'` index is ignored.)
    m = re.search(
        r"create_index\(\s*[\"']uq_integration_push_workspace_repo_active[\"'].*?"
        r"postgresql_where\s*=\s*sa\.text\(\s*\"([^\"]+)\"",
        src,
        re.S,
    )
    assert m, (
        "Migration must create the (workspace_id, repo_id) partial unique index "
        "'uq_integration_push_workspace_repo_active' with a postgresql_where predicate. T-265."
    )
    predicate = m.group(1).lower()
    assert "failed" in predicate and "'active'" not in predicate, (
        f"The (workspace_id, repo_id) partial unique index predicate must be `status <> 'failed'` "
        f"(one live push per repo), not {m.group(1)!r}. A `status='active'` predicate matches zero "
        "rows and disables the guard. T-265."
    )
    assert re.search(r"create_index\([^\)]*repo_id|ix_integration_pushes_repo_id", src), (
        "Migration must index integration_pushes.repo_id for webhook reconciliation. T-265."
    )


def test_t265_migration_indexes_issue_number_for_webhook_lookups() -> None:
    src = _combined_migrations()
    # require an actual index *on* external_issue_number (not just the column,
    # which already exists from the Phase 13 migration 0007).
    assert re.search(r"ix_integration_push_tasks_issue_number", src) or re.search(
        r"create_index\([^)]{0,200}external_issue_number", src, re.S
    ), "Migration 0016 must index integration_push_tasks.external_issue_number for webhook lookups. T-265."


def test_t265_repo_id_backfill_leaves_legacy_rows_nullable() -> None:
    """Edge: legacy Phase-13 pushes have no repo_id. The new column must be
    nullable so the partial unique index tolerates them (nulls are distinct)."""
    src = _combined_migrations()
    # find the repo_id add_column and assert it is not NOT NULL
    m = re.search(r"add_column\(\s*[\"']integration_pushes[\"'].*?repo_id.*?\)", src, re.S)
    assert m, "Could not find the integration_pushes.repo_id add_column. T-265."
    assert "nullable=False" not in m.group(0), (
        "integration_pushes.repo_id must be nullable so legacy rows survive the "
        "partial unique index (backfill is lazy, on next App export). T-265."
    )


def test_t278_migration_0017_creates_increment_tables_and_fks() -> None:
    src = _combined_migrations()
    assert "increments" in src, "Migration 0017 must create the increments table. T-278."
    assert "increment_ideas" in src, "Migration 0017 must create increment_ideas. T-278."
    for col in ["sequence", "baseline_version_ids", "status"]:
        assert col in src, f"increments must have column {col}. T-278 (spec §10)."
    assert re.search(r"workspace_id.*sequence|sequence.*workspace_id", src, re.S) and re.search(
        r"unique", src, re.I
    ), "increments must be unique on (workspace_id, sequence). T-278."
    assert "increment_id" in src, "increment_id FK must be wired onto pushes/push_tasks. T-278."


def test_t278_increment_models_exist() -> None:
    src = read_backend_file("models", "increment.py")
    assert "class Increment" in src and "class IncrementIdea" in src, (
        "models/increment.py must define Increment and IncrementIdea. T-278."
    )
    _assert_all(src, ["source", "external_ref", "text", "status"], "IncrementIdea model")


# ===========================================================================
# T-266 — Schemas
# ===========================================================================


def test_t266_github_schemas_define_install_export_and_sync_models() -> None:
    src = read_backend_file("schemas", "github.py")
    _assert_any(src, ["InstallationStatus", "GitHubInstallationStatus"], "schemas/github.py install status")
    _assert_any(src, ["GitHubExportRequest", "ExportRequest"], "schemas/github.py export request")
    _assert_any(src, ["SyncStateResponse", "SyncState", "TaskCompletion"], "schemas/github.py sync state")
    for mode in ["files_to_default", "pr_with_tests"]:
        assert mode in src, f"GitHubExportRequest must accept export_mode {mode!r}. T-266/T-276."


def test_t266_export_request_targets_an_installation() -> None:
    """Audit gap: a user may install on several accounts; the export must name which
    installation/token to use, and GET must return the list to pick from."""
    schemas = read_backend_file("schemas", "github.py")
    assert "installation_id" in schemas, (
        "GitHubExportRequest must carry installation_id so a multi-install user's export resolves "
        "which installation (and token) to create/use the repo under. T-266/T-269."
    )
    integrations = read_backend_file("routers", "integrations.py")
    assert re.search(r"InstallationList|list\[|List\[", schemas + integrations), (
        "GET /integrations/github must return the LIST of the user's installations (org + personal) "
        "so the export picker can choose a target. T-266/T-270."
    )


def test_t266_find_live_push_helper_centralizes_live_push_lookup() -> None:
    """Audit gap: the 'live push' (non-failed row) lookup must live in ONE helper so the
    status<>'failed' rule cannot drift back into a `status='active'` query."""
    helper = _read_backend_optional("services", "integrations", "push_repo.py") or ""
    users = (
        (_read_backend_optional("services", "integrations", "github_reconcile.py") or "")
        + (_read_backend_optional("routers", "workspace.py") or "")
    )
    assert "find_live_push" in helper or "find_live_push" in users, (
        "T-266 must add a find_live_push(workspace_id, repo_id) helper (the single non-failed row) "
        "used by reconcile/sync/re-export, so the partial-index definition lives in one place. T-266/T-272/T-273."
    )


# ===========================================================================
# T-267 — GitHub App auth + token provider
# ===========================================================================


def test_t267_app_auth_defines_jwt_minting_and_cached_provider() -> None:
    src = read_backend_file("services", "integrations", "github_app_auth.py")
    assert "class GitHubAppAuth" in src or "def app_jwt" in src, (
        "github_app_auth.py must provide App JWT signing. T-267."
    )
    assert "mint_installation_token" in src or "access_tokens" in src, (
        "github_app_auth.py must mint installation tokens via /app/installations/{id}/access_tokens. T-267."
    )
    assert "TokenProvider" in src, "github_app_auth.py must expose a Redis-cached TokenProvider. T-267."


def test_t267_app_jwt_is_rs256_short_lived_and_key_from_settings_not_db() -> None:
    src = read_backend_file("services", "integrations", "github_app_auth.py")
    assert "RS256" in src, "App JWT must be RS256. T-267 (spec §8)."
    # short-lived: exp <= 10 minutes and iat backdated for clock skew
    assert re.search(r"\b(540|600)\b", src), "App JWT exp must be <= 600s. T-267."
    assert re.search(r"-\s*60|skew|iat", src), "App JWT iat must be backdated ~60s for clock skew. T-267."
    assert "github_app_private_key" in src, (
        "App private key must come from settings.github_app_private_key (secret manager), never the DB. T-267."
    )


def test_t267_token_cache_is_namespaced_and_refresh_ahead() -> None:
    src = read_backend_file("services", "integrations", "github_app_auth.py")
    assert "gh:inst_token" in src, "Installation tokens must be cached under gh:inst_token:{id}. T-267."
    assert re.search(r"refresh|ttl|expire", src, re.I), (
        "Token cache must be TTL'd / refresh-ahead so minting stays off the hot path. T-267."
    )
    assert "specforge_github_token_mint_total" in src, (
        "Token mint vs cache hit must increment specforge_github_token_mint_total. T-267/T-284."
    )


# ===========================================================================
# T-268 — API client refactor
# ===========================================================================


def test_t268_client_resolves_per_call_token_not_static_init() -> None:
    src = read_backend_file("services", "integrations", "github_api_client.py")
    assert "TokenProvider" in src or "installation_id" in src, (
        "github_api_client must resolve an installation token per call (TokenProvider + installation_id), "
        "not hold a static user token in __init__. T-268."
    )
    # re-mint once on a 401 (token may have rotated under it)
    assert "401" in src, "Client must re-mint the installation token once on a 401. T-268."


def test_t268_client_keeps_typed_errors_and_breaker() -> None:
    src = read_backend_file("services", "integrations", "github_api_client.py")
    for err in ["GitHubRateLimitError", "GitHubAPIError"]:
        assert err in src, f"Client must retain typed error {err}. T-268."
    assert re.search(r"timeout|breaker|circuit", src, re.I), (
        "Shared httpx client must have bounded timeouts / circuit breaker (spec §12 robustness). T-268."
    )


# ===========================================================================
# T-269 — Queue + worker (NEW infrastructure)
# ===========================================================================


def test_t269_worker_module_registers_all_jobs() -> None:
    src = read_backend_file("worker.py")
    assert "WorkerSettings" in src, "worker.py must define an arq WorkerSettings. T-269."
    for job in WORKER_JOBS:
        assert job in src, f"worker must register the {job!r} job. T-269."


def test_t269_arq_dependency_declared() -> None:
    reqs = (_read_backend_optional("requirements.txt") or "") + (
        _read_backend_optional("pyproject.toml") or ""
    )
    assert "arq" in reqs, "arq must be a declared backend dependency (planning decision §24.1). T-269."


def test_t269_docker_compose_defines_worker_service() -> None:
    compose = _read_repo_optional("docker-compose.yml") or _read_repo_optional("docker-compose.yaml") or ""
    assert "worker" in compose and "arq" in compose, (
        "docker-compose must add a 'worker' service running the arq worker. T-269 (spec §Y.6 dev env)."
    )


def test_t269_queue_helpers_and_dead_letter_exist() -> None:
    src = read_backend_file("services", "queue.py")
    assert re.search(r"enqueue|arq", src), "services/queue.py must expose enqueue helpers. T-269."
    blob = src + _combined_github_services()
    assert re.search(r"dead.?letter", blob, re.I), (
        "Jobs must dead-letter after max retries (alert + manual replay). T-269."
    )
    assert re.search(r"backoff|jitter|max_tries|retry", blob, re.I), (
        "Jobs must retry with exponential backoff + jitter and a max attempt count. T-269."
    )


def test_t269_outbound_jobs_are_idempotent_and_checkpointed() -> None:
    """Edge (spec §12 X.3 / plan T-269): killing the worker mid-export must
    resume without double-creating the repo or issues. Outbound jobs must be
    keyed by push_id/increment_id and record progress for checkpointed resume."""
    blob = read_backend_file("services", "queue.py") + _combined_github_services()
    assert re.search(r"push_id|increment_id|job_id|_job_key|key=", blob), (
        "Outbound jobs must be keyed (push_id/increment_id) so retries don't duplicate. T-269."
    )
    assert re.search(r"checkpoint|resume|idempotent|already.*(created|pushed)|existing", blob, re.I), (
        "Multi-step outbound jobs must checkpoint progress and resume without duplicating side effects. T-269."
    )


def test_t269_export_moves_off_request_path_and_returns_202() -> None:
    """Edge: the v1 export ran inline in the handler. It must now enqueue."""
    src = read_backend_file("routers", "workspace.py")
    handler = None
    for name in ["export_workspace_to_github", "export_to_github", "export_github", "github_export"]:
        if re.search(rf"def\s+{name}\b", src):
            handler = _function_source(src, name)
            break
    assert handler is not None, "Could not locate the GitHub export handler in workspace.py. T-269."
    assert re.search(r"enqueue|queue|arq", handler), (
        "The export handler must ENQUEUE a worker job, not run push_to_github inline. T-269."
    )
    assert "202" in handler, "The export handler must return 202 (accepted), not block on GitHub I/O. T-269."


def test_t269_export_persists_repo_id_installation_and_source_version() -> None:
    """Audit gap: without these three fields on the push row, token re-mint (reconcile),
    confused-deputy resolution, and drift-compare are all inert."""
    blob = (
        (_read_backend_optional("services", "pipeline", "github_export_service.py") or "")
        + (_read_backend_optional("worker.py") or "")
        + (_read_backend_optional("services", "queue.py") or "")
    )
    for field in ["repo_id", "source_stage_version_id", "installation_id"]:
        assert field in blob, (
            f"export_push must persist {field} on the IntegrationPush row on success "
            "(repo_id from repository.id) so reconcile/drift/token-mint work. T-269/T-273."
        )


# ===========================================================================
# T-270 — Install flow + lifecycle
# ===========================================================================


def test_t270_install_and_setup_routes_exist() -> None:
    src = read_backend_file("routers", "integrations.py")
    for path in INSTALL_PATHS:
        assert path in src, f"integrations router must register {path}. T-270."
    assert "installations/new" in src or "github_app_slug" in src or "GITHUB_APP_SLUG" in src, (
        "Install route must point at /apps/{slug}/installations/new. T-270."
    )


def test_t270_lifecycle_events_handled() -> None:
    blob = _read_backend_optional("routers", "integrations.py") or ""
    blob += _read_backend_optional("services", "integrations", "github_reconcile.py") or ""
    for token in ["installation_repositories", "suspend", "deleted"]:
        assert token in blob, f"Lifecycle handling must cover {token!r}. T-270."
    assert "suspended_at" in blob or "stale" in blob, (
        "On uninstall/suspend, affected pushes must be marked stale / disconnected. T-270."
    )


def test_t270_v1_oauth_path_retained_for_migration() -> None:
    """Append-only: the v1 OAuth integration must be RETAINED behind a flag,
    not deleted. Phase 24 supersedes Phase 13 (§17) without removing it."""
    assert (BACKEND_ROOT / "services" / "integrations" / "github_auth_service.py").exists(), (
        "github_auth_service.py (v1 OAuth) must be retained for migration. §24 Source note / Assumption 22."
    )
    assert (BACKEND_ROOT / "models" / "user_integration.py").exists(), (
        "UserIntegration (legacy token) must be retained. §24."
    )
    assert (REPO_ROOT / "harness" / "tests" / "backend" / "test_phase13_github_integration_contract.py").exists(), (
        "Phase 13 contract must remain (append-only). §24."
    )


# ===========================================================================
# T-271 — Webhook ingest
# ===========================================================================


def test_t271_webhook_route_registered() -> None:
    src = read_backend_file("routers", "integrations.py")
    assert WEBHOOK_PATH in src, f"integrations router must register {WEBHOOK_PATH}. T-271."
    assert "X-Hub-Signature-256" in src, "Webhook must read X-Hub-Signature-256. T-271."
    assert "X-GitHub-Delivery" in src, "Webhook must read X-GitHub-Delivery for dedup. T-271."


def test_t271_webhook_verifies_before_any_db_or_queue_work() -> None:
    """Edge (DoS guard): HMAC verify + reject must precede any enqueue/DB write."""
    src = read_backend_file("routers", "integrations.py")
    fn = _function_source(src, "github_webhook") if re.search(r"def\s+github_webhook\b", src) else src
    # raw body must be read before json parsing
    body_idx = min([i for i in [fn.find(".body()"), fn.find("await request.body")] if i != -1] or [10**9])
    parse_idx = min([i for i in [fn.find("json.loads"), fn.find(".json(")] if i != -1] or [10**9])
    assert body_idx < parse_idx, "Webhook must read raw bytes BEFORE parsing JSON. T-271."
    # signature check / 400 must precede enqueue
    verify_idx = min([i for i in [fn.find("Signature"), fn.lower().find("verify"), fn.find("400")] if i != -1] or [10**9])
    enqueue_idx = min([i for i in [fn.find("enqueue"), fn.find("queue")] if i != -1] or [10**9])
    assert verify_idx < enqueue_idx, (
        "Webhook must verify the HMAC (reject with 400) BEFORE any enqueue/DB work. T-271 (spec §12 DoS guard)."
    )


def test_t271_webhook_accepts_two_secrets_for_rotation() -> None:
    """Edge: secret rotation must accept BOTH the current and previous secret."""
    blob = _read_backend_optional("routers", "integrations.py") or ""
    blob += _read_backend_optional("services", "integrations", "github_app_auth.py") or ""
    blob += _read_backend_optional("config.py") or ""
    assert "github_app_webhook_secret_prev" in blob or re.search(
        r"webhook_secret.*prev|secrets\b|two secrets|both secrets", blob, re.I
    ), "Webhook verification must accept two signing secrets during rotation. T-271/T-283 (spec §12)."


def test_t271_webhook_dedup_is_idempotent() -> None:
    """Edge: a retried delivery (same X-GitHub-Delivery) must be skipped."""
    src = read_backend_file("routers", "integrations.py")
    fn = _function_source(src, "github_webhook") if re.search(r"def\s+github_webhook\b", src) else src
    assert "GitHubWebhookEvent" in fn and ("IntegrityError" in fn or "duplicate" in fn.lower()), (
        "Webhook must insert a GitHubWebhookEvent and treat a unique violation as a duplicate (idempotent). T-271."
    )
    assert re.search(r"enqueue|queue", fn), "Webhook must enqueue reconciliation, not run it inline. T-271."


def test_t271_webhook_exempt_from_csrf_and_rate_limit() -> None:
    csrf = read_backend_file("middleware", "csrf.py")
    rate = read_backend_file("middleware", "rate_limit.py")
    assert WEBHOOK_PATH in csrf or "integrations/github/webhook" in csrf, (
        "Webhook path must be CSRF-exempt (no Bearer token). T-271/T-283."
    )
    assert "integrations/github/webhook" in rate or WEBHOOK_PATH in rate, (
        "Webhook must be exempt from per-IP rate limiting (GitHub retry schedule must not be blocked). T-271/T-283."
    )


# ===========================================================================
# T-272 — Reconcile job
# ===========================================================================


def test_t272_reconcile_resolves_by_repo_id_not_full_name() -> None:
    """Edge: repos get renamed/transferred — reconcile on the immutable id."""
    src = read_backend_file("services", "integrations", "github_reconcile.py")
    assert "reconcile_event" in src, "github_reconcile.py must define reconcile_event. T-272."
    assert re.search(r"repository.*\bid\b|repo_id", src), (
        "Reconcile must resolve the push by repository.id / repo_id. T-272."
    )
    # must NOT key the match on the mutable full name
    assert not re.search(r"find.*repo_full_name|where.*repo_full_name|by_full_name", src, re.I), (
        "Reconcile must NOT match on repo_full_name (renames/transfers break it). T-272."
    )


def test_t272_issue_close_sets_task_done_with_attribution() -> None:
    src = read_backend_file("services", "integrations", "github_reconcile.py")
    for token in ["closed", "issues", "pull_request", "merged"]:
        assert token in src, f"Reconcile must handle {token!r} events. T-272."
    assert "pr_merge" in src and "manual" in src, (
        "Reconcile must set done_via=pr_merge when a merged PR closed it, else manual. T-272."
    )
    assert "done" in src, "Reconcile must flip the matching task state to done. T-272."


def test_t272_confused_deputy_authz_scopes_to_owner_installation() -> None:
    """Edge: an event for repo X may only mutate pushes under a recorded
    installation for that owner — payload identity is never trusted alone."""
    src = read_backend_file("services", "integrations", "github_reconcile.py")
    assert "installation" in src, (
        "Reconcile must scope mutations to the recorded installation (confused-deputy guard). T-272/T-283 (spec §12)."
    )


def test_t272_out_of_order_events_gated_on_timestamp() -> None:
    """Edge: a late 'reopened' must not regress a task closed by a newer event."""
    src = read_backend_file("services", "integrations", "github_reconcile.py")
    assert re.search(r"timestamp|updated_at|event_ts|_at\b", src), (
        "Reconcile must gate transitions on event timestamp (out-of-order safety). T-272 (spec §12)."
    )


def test_t272_dispatcher_routes_pr_and_check_events_to_pr_check() -> None:
    """Audit gap: the webhook enqueues ONE dispatcher; it must fan out by (event, action).
    pull_request fans out to BOTH reconcile (closed+merged) and pr_check (opened/synchronize)."""
    src = read_backend_file("services", "integrations", "github_reconcile.py")
    assert "pr_check" in src and "check_suite" in src, (
        "The reconcile_event dispatcher must route check_suite / pull_request(opened|synchronize) to "
        "pr_check — not blindly reconcile every delivery. T-271/T-272/T-282."
    )


# ===========================================================================
# T-273 — Drift, backfill, resync
# ===========================================================================


def test_t273_sync_endpoints_registered() -> None:
    src = read_backend_file("routers", "workspace.py")
    for path in SYNC_PATHS:
        assert path in src, f"workspace router must register {path}. T-273."


def test_t273_drift_compares_source_stage_version() -> None:
    blob = _combined_github_services() + (_read_backend_optional("services", "pipeline", "stage_manager.py") or "")
    blob += _read_backend_optional("routers", "workspace.py") or ""
    assert "source_stage_version_id" in blob, (
        "Drift detection must compare the push's source_stage_version_id to the current finalised Tasks version. T-273."
    )
    assert re.search(r"out.?of.?sync|stale", blob, re.I), (
        "A drifted push must be marked out-of-sync / stale. T-273."
    )


def test_t273_backfill_filters_pull_request_rows() -> None:
    """Edge: GitHub's issues endpoint returns PRs too — they must be filtered."""
    src = read_backend_file("services", "integrations", "github_reconcile.py")
    assert "state=all" in src or "since" in src, (
        "Backfill must list issues?state=all&since=... to recover missed events. T-273."
    )
    assert "pull_request" in src, (
        "Backfill must filter out rows carrying a 'pull_request' key (those are PRs, not issues). T-273."
    )


def test_t273_reconcile_drift_recovers_stuck_pending_pushes() -> None:
    """Audit gap: a crashed export leaves a 'pending' push which — under the working
    partial index — blocks ALL re-export of that repo. The cron must sweep stale-pending."""
    blob = (
        (_read_backend_optional("services", "integrations", "github_reconcile.py") or "")
        + (_read_backend_optional("worker.py") or "")
    )
    assert "pending" in blob and re.search(
        r"stuck|stale|older than|timeout|reconcile_drift|threshold", blob, re.I
    ), (
        "reconcile_drift must sweep pushes stuck in 'pending' (crashed worker) and fail/re-enqueue them "
        "so the repo is not permanently locked out of re-export. T-273."
    )


# ===========================================================================
# T-274 — Rate governor + per-repo serialization
# ===========================================================================


def test_t274_governor_reads_limit_headers_and_requeues() -> None:
    src = read_backend_file("services", "integrations", "github_governor.py")
    assert "X-RateLimit-Remaining" in src or "Retry-After" in src, (
        "Governor must read GitHub rate-limit headers. T-274 (spec §12)."
    )
    assert re.search(r"\b403\b|\b429\b", src), "Governor must back off on 403/429. T-274."
    assert re.search(r"requeue|retry|defer", src, re.I), (
        "Governor must requeue throttled jobs rather than failing them. T-274."
    )


def test_t274_per_repo_write_serialization() -> None:
    """Edge: concurrent content writes to one repo cause stale-SHA 409s and
    secondary-limit throttling — serialize per repo_id."""
    src = read_backend_file("services", "integrations", "github_governor.py")
    assert re.search(r"lock", src, re.I) and "repo" in src, (
        "Content writes must be serialized per repo (per-repo_id lock). T-274."
    )
    assert "specforge_github_queue_depth" in (src + _combined_github_services()), (
        "Backpressure must be observable via specforge_github_queue_depth. T-274/T-284."
    )


# ===========================================================================
# T-276 — PR + harness-tests export mode
# ===========================================================================


def test_t276_pr_builder_adds_branch_and_pr_plumbing() -> None:
    src = read_backend_file("services", "integrations", "pr_export_builder.py")
    client = read_backend_file("services", "integrations", "github_api_client.py")
    blob = src + client
    for method in ["create_branch", "create_pull_request"]:
        assert method in blob, f"PR mode requires client method {method}. T-276."
    assert re.search(r"get_ref|git/ref", blob), "PR mode must read the default branch base SHA (get_ref). T-276."
    assert "branch" in client, (
        "upsert_file must gain a `branch` param so files can be written on the increment branch. T-276."
    )


def test_t276_pr_mode_emits_ci_workflow_and_stack_scaffold() -> None:
    src = read_backend_file("services", "integrations", "pr_export_builder.py")
    assert "specforge.yml" in src or ".github/workflows" in src, (
        "PR mode must emit a CI workflow under .github/workflows. T-276."
    )
    _assert_any(src, ["pytest", "vitest"], "PR mode per-stack scaffold (start pytest/vitest)")
    assert "task_ref" in src, "PR mode must emit per-task stub files tagged with task_ref. T-276."
    assert "Closes #" in src or "Closes #N" in src or "closes #" in src.lower(), (
        "PR body must link issues to tests via 'Closes #N'. T-276."
    )


def test_t276_handles_workflows_403_and_content_409() -> None:
    """Edge: pushing .github/workflows/* without Workflows:write 403s on that
    path only; a content write can 409 on a stale SHA."""
    src = read_backend_file("services", "integrations", "pr_export_builder.py")
    blob = src + read_backend_file("services", "integrations", "github_api_client.py")
    assert re.search(r"Workflows.*write|workflows_write|403", blob), (
        "A Workflows:write 403 on .github/workflows/* must surface a clear, actionable error. T-276."
    )
    assert "409" in blob and re.search(r"refetch|re-fetch|retry|stale", blob, re.I), (
        "A content-write 409 (stale SHA) must refetch the SHA and retry. T-276."
    )


def test_t276_export_mode_persisted_and_idempotent() -> None:
    blob = _combined_github_services() + read_backend_file("models", "integration_push.py")
    assert "files_to_default" in blob and "pr_with_tests" in blob, (
        "export_mode must be a persisted per-workspace toggle, default files_to_default. T-276."
    )
    assert "branch_name" in blob and "pr_number" in blob, (
        "Re-export must reuse the existing branch_name/pr_number (never duplicate the PR). T-276."
    )


# ===========================================================================
# T-277 — Agent-ready issues + AGENTS.md
# ===========================================================================


def test_t277_issue_template_has_fixed_agent_sections_and_yaml_header() -> None:
    blob = _combined_github_services() + (_read_backend_optional("services", "integrations", "task_parser.py") or "")
    for section in REQUIRED_ISSUE_SECTIONS:
        assert section in blob, f"Agent-ready issue body must include the {section!r} section. T-277."
    for key in ["task_ref", "stage", "spec_anchors", "test_path"]:
        assert key in blob, f"Issue machine-readable header must include {key!r}. T-277."
    for label in AGENT_LABELS:
        assert label in blob, f"Issues must carry the {label!r} label. T-277."


def test_t277_agents_md_builder_never_clobbers_existing_content() -> None:
    """Edge: AGENTS.md/CLAUDE.md may already exist — write only inside markers."""
    src = read_backend_file("services", "integrations", "agents_md_builder.py")
    assert "AGENTS.md" in src or "CLAUDE.md" in src, "agents_md_builder must generate AGENTS.md/CLAUDE.md. T-277."
    assert re.search(r"specforge:start|specforge:end|managed|marker|delimit", src, re.I), (
        "AGENTS.md generation must write only inside delimited managed markers (never clobber). T-277."
    )
    assert re.search(r"clobber|preserve|existing", src, re.I), (
        "Generator must explicitly preserve pre-existing user content. T-277."
    )


def test_t277_spec_anchors_reuse_section_contracts() -> None:
    blob = _combined_github_services()
    assert "SECTION_CONTRACTS" in blob or "artifact_validator" in blob, (
        "Stable spec anchors must reuse artifact_validator SECTION_CONTRACTS headings. T-277."
    )


# ===========================================================================
# T-279 / T-280 — Increments
# ===========================================================================


def test_t279_increment_generation_treats_baseline_immutable_and_pins_refs() -> None:
    src = read_backend_file("services", "pipeline", "increment_service.py")
    assert re.search(r"baseline", src, re.I), "Increment generation must treat baseline stages as immutable context. T-279."
    assert "task_ref" in src, "Increment generation must pin stable task_refs. T-279."
    assert re.search(r"additive|delta|diff", src, re.I), (
        "Increment output must be a delta vs. baseline (additive append), not a full re-run. T-279."
    )


def test_t279_task_ref_scheme_is_content_derived_and_stable() -> None:
    """Edge: unstable task_refs duplicate issues across increments. Per the audit the scheme
    is DEFINED in Phase A (task_parser.compute_task_ref) and reused everywhere — not invented
    here in C′ — so export/agent-issues/increments all share one matching key."""
    parser = _read_backend_optional("services", "integrations", "task_parser.py") or ""
    blob = parser + read_backend_file("services", "pipeline", "increment_service.py")
    assert "compute_task_ref" in parser, (
        "task_parser must define compute_task_ref (the stable, content-derived task_ref) so the "
        "matching key is decided in Phase A and consumed by export (T-269), agent issues (T-277), "
        "and increments (T-279/T-280). T-266/T-279."
    )
    assert re.search(r"hash|content.?derived|stable|slug", blob, re.I), (
        "task_ref must be content-derived/stable so the same task updates the same issue (spec Assumption 23). T-279."
    )


def test_t280_incremental_sync_pushes_only_new_issues() -> None:
    blob = _combined_github_services()
    assert "increment_push" in blob, "An increment_push job must exist. T-280."
    assert re.search(r"new issue|only new|new tasks", blob, re.I), (
        "Incremental sync must create NEW issues only for new tasks. T-280."
    )
    assert re.search(r"milestone", blob, re.I), "Each increment must get its own milestone. T-280."
    assert re.search(r"close|obsolete", blob, re.I), (
        "Obsoleted tasks' issues must be closed with a note. T-280."
    )


def test_t280_idea_backlog_endpoints_and_github_flow_back() -> None:
    src = read_backend_file("routers", "workspace.py")
    assert "/workspaces/{id}/ideas" in src, "Idea backlog endpoints must exist. T-280."
    blob = _combined_github_services()
    assert "enhancement" in blob or "idea" in blob.lower(), (
        "GitHub issues labelled idea/enhancement must flow back into increment_ideas. T-280."
    )


def test_t280_increment_rest_endpoints_registered() -> None:
    """Audit gap: the frontend timeline (T-289) calls these; without them the
    increment surface is generation-only with no way to list or push."""
    src = read_backend_file("routers", "workspace.py")
    assert "/workspaces/{id}/increments" in src, (
        "Increment REST endpoints (GET/POST /workspaces/{id}/increments and "
        "POST /workspaces/{id}/increments/{inc_id}/push) must be registered. T-280."
    )
    assert re.search(r"increments/\{[^}]*\}/push|/push", src), (
        "An increment push endpoint (POST .../increments/{inc_id}/push) must enqueue increment_push. T-280."
    )


# ===========================================================================
# T-281 / T-282 — Projects board + status checks
# ===========================================================================


def test_t281_client_has_graphql_path_for_projects_v2() -> None:
    src = read_backend_file("services", "integrations", "github_api_client.py")
    assert "graphql" in src.lower(), "Projects v2 is GraphQL-only — the client needs a GraphQL path. T-281."
    assert "ProjectV2" in src or "add_project_v2_item" in src or "addProjectV2ItemById" in src, (
        "Client must support adding items to a Projects v2 board. T-281."
    )
    assert "milestone" in src.lower(), "Milestones use REST (POST /repos/{repo}/milestones). T-281."


def test_t282_pr_evaluator_is_new_module_failopen_and_not_the_critic() -> None:
    """Edge (spec Assumption 25): the PR-diff evaluator is a NEW evaluator that
    judges external code, NOT the existing artifact critic."""
    src = read_backend_file("services", "integrations", "pr_evaluator.py")
    assert "acceptance" in src.lower(), (
        "pr_evaluator must judge the PR diff against the task's acceptance criteria. T-282."
    )
    assert re.search(r"fail.?open", src, re.I), "pr_evaluator must be fail-open (judge error never blocks the PR). T-282."
    assert "import critic" not in src and "from services.pipeline.critic" not in src, (
        "pr_evaluator must be a distinct module, NOT services/pipeline/critic.py as the evaluator. T-282 (Assumption 25)."
    )
    assert re.search(r"debounce|budget|concurrency|cap", src, re.I), (
        "pr_evaluator cost must be capped/debounced (spec §12.2). T-282."
    )


def test_t282_check_run_posting_with_fallback() -> None:
    blob = read_backend_file("services", "integrations", "github_api_client.py") + _combined_github_services()
    assert "check-runs" in blob or "check_run" in blob, (
        "Status checks must post a check run (POST /repos/{repo}/check-runs). T-282."
    )
    assert re.search(r"status.*api|commit status|statuses", blob, re.I), (
        "A commit Status API fallback must exist for v1 of the check. T-282."
    )


# ===========================================================================
# T-283 — Config, security, rate limits
# ===========================================================================


def test_t283_config_defines_github_app_settings_and_prod_guard() -> None:
    src = read_backend_file("config.py")
    for key in GITHUB_APP_CONFIG:
        assert key in src, f"config.py must define {key}. T-283 (spec §Y.2)."
    assert re.search(r"validate_production_settings|production", src), (
        "Production validation must require the GitHub App settings when enabled. T-283."
    )


def test_t283_rate_limit_tiers_present() -> None:
    src = read_backend_file("middleware", "rate_limit.py")
    blob = src + (_read_backend_optional("config.py") or "")
    # sync + increment tiers (export tier already exists from Phase 13)
    assert re.search(r"sync", blob, re.I), "A GitHub Sync rate-limit tier must exist. T-283 (spec §12)."
    assert re.search(r"increment", blob, re.I), "A GitHub Increment Push rate-limit tier must exist. T-283."


def test_t283_secrets_scrubbed_from_logs() -> None:
    """Edge: the installation token and App private key are credentials."""
    blob = read_backend_file("services", "observability.py")
    extra = _read_backend_optional("services", "observability", "__init__.py") or ""
    blob += extra
    # github-specific tokens only — a generic `private_key` pattern already exists.
    assert re.search(r"github_app_private_key|inst_token|gh:inst_token|installation[_ ]token", blob, re.I), (
        "Secret scrubbing must explicitly cover the GitHub App private key and installation tokens. T-283."
    )


def test_t283_token_and_payload_never_logged_in_services() -> None:
    """Edge: no service may log a token, the private key, or a raw payload."""
    blob = _combined_github_services()
    # crude but effective: a logger call directly interpolating a token/key var
    assert not re.search(r"log[\w.]*\([^)]*(private_key|inst_token|access_token)\b", blob), (
        "No log call may emit the App private key or an installation token. T-283/T-284."
    )


# ===========================================================================
# T-284 — Observability
# ===========================================================================


def test_t284_all_github_metrics_defined() -> None:
    src = read_backend_file("services", "observability.py")
    for metric in GITHUB_METRICS:
        assert metric in src, f"observability.py must define {metric}. T-284 (spec §12)."


def test_t284_structlog_events_present() -> None:
    blob = read_backend_file("services", "observability.py") + _combined_github_services()
    for event in ["github.installed", "github.webhook", "github.reconcile", "github.sync.paused"]:
        assert event in blob, f"Structlog must emit {event!r}. T-284."


# ===========================================================================
# T-285 / T-286 — Harness + docs
# ===========================================================================


def test_t285_frontend_contract_exists() -> None:
    path = REPO_ROOT / "harness" / "tests" / "frontend" / "phase24-github-living.contract.test.ts"
    assert path.exists(), (
        "The frontend Phase 24 contract must exist (T-275/T-285): "
        "harness/tests/frontend/phase24-github-living.contract.test.ts."
    )


def test_t286_docs_updated_for_app_and_worker() -> None:
    runbook = _read_repo_optional("RUNBOOK.md") or _read_repo_optional("docs", "RUNBOOK.md") or ""
    claude = _read_repo_optional("CLAUDE.md") or ""
    blob = runbook + claude
    assert re.search(r"GITHUB_APP|installation token|webhook secret|worker|arq", blob), (
        "RUNBOOK/CLAUDE.md must document the GitHub App, worker, and rotation. T-286."
    )
