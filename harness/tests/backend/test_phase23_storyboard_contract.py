"""
Harness contracts for Phase 23 - Storyboard Product Keynote Generation.

These tests are RED before T-250 through T-264 are implemented and GREEN after.

Every test maps to Plan v1.md Phase 23 and V1 spec.md v1.5.0:

  T-250  Storyboard DB migration + ORM model. One row per generated version,
         unique (workspace_id, version), partial unique public slug index,
         stale status, source-stage version IDs, credit ledger reference, and
         public permission booleans.

  T-251  Pydantic schemas and router. Owner endpoints for list/latest/generate,
         retrieve, regenerate, section regenerate, presenter, downloads, share,
         disable share, rotate slug; public endpoints for /storyboards/public.

  T-252  Source builder. Loads only finalised SPEC/PLAN/HARNESS/TASKS versions,
         captures immutable stage version IDs, bounds excerpts, prioritises
         architecture/security/reliability sections, excludes sensitive account
         and billing data, and emits missing-source findings.

  T-253  Prompt builder. Strict JSON schema, exactly six top-level acts,
         no top-level Validation or Execution Plan acts, architecture reveal,
         sparse slides, speaker notes, demo script, technical appendix, visual
         identity, source map, and one JSON-repair attempt.

  T-254  Service orchestration. 25-credit full generation, 5-credit section
         regeneration, idempotency lock, SELECT FOR UPDATE version assignment,
         refund-on-failure, previous-ready preservation, stale propagation, and
         stuck-job recovery.

  T-255  Renderer/downloads. Trusted renderer only, sanitisation, no generated
         scripts, no remote assets, no-network PDF fetcher, CSP, and stable
         download filenames.

  T-256  Public sharing. Independent /sb Storyboard slug, defaults that hide
         notes/appendix/source, permission filtering, slug rotation, noindex,
         CSP, and 404 for disabled/unknown links.

  T-257  Frontend owner flow is covered in
         harness/tests/frontend/phase23-storyboard.contract.test.ts.

  T-261  Security and rate limits. Storyboard-specific tiers, CSRF on mutations,
         owner-only 404 semantics, public allow-list responses, and no content
         logging.

  T-262  Observability. Prometheus metrics and structlog event names for the
         paid keynote flow.

  T-263  Harness contract. This file is the executable backend safety net for
         the new feature.

  T-264  Docs/smoke. Runbook, local testing, observability, production gate, and
         smoke checklist documentation must be updated before release.

The contract intentionally checks for edge cases that are easy to miss:
double charging, partial regeneration corrupting a ready Storyboard, public
notes/source leakage, stale Storyboards after source changes, generated script
injection, remote asset leakage, source maps drifting away from finalised stage
versions, and unsupported public HTML package downloads.
"""

from __future__ import annotations

import re

from conftest import BACKEND_ROOT, REPO_ROOT, read_backend_file


REQUIRED_ACTS = [
    "Opening Thesis",
    "Product Vision",
    "Product Walkthrough",
    "Technical Architecture",
    "Trust, Security, Reliability",
    "Launch Close",
]

REQUIRED_ARCHITECTURE_LAYERS = [
    "client",
    "frontend",
    "api",
    "data",
    "llm",
    "integrations",
    "trust",
    "recovery",
]

OWNER_ENDPOINT_SNIPPETS = [
    "/workspaces/{id}/storyboards",
    "/workspaces/{id}/storyboards/latest",
    "/storyboards/{id}",
    "/storyboards/{id}/regenerate",
    "/storyboards/{id}/sections/{section_id}/regenerate",
    "/storyboards/{id}/presenter",
    "/storyboards/{id}/download/html",
    "/storyboards/{id}/download/pdf",
    "/storyboards/{id}/download/notes",
    "/storyboards/{id}/download/demo-script",
    "/storyboards/{id}/download/appendix",
    "/storyboards/{id}/share",
    "/storyboards/{id}/share/rotate",
]

PUBLIC_ENDPOINT_SNIPPETS = [
    "/storyboards/public/{slug}",
    "/storyboards/public/{slug}/download/{kind}",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_repo_file(*parts: str) -> str:
    path = REPO_ROOT.joinpath(*parts)
    assert path.exists(), f"Missing repository file: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _read_backend_optional(*parts: str) -> str:
    path = BACKEND_ROOT.joinpath(*parts)
    assert path.exists(), f"Missing backend file: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _combined_migrations() -> str:
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    assert versions_dir.exists(), "backend/migrations/versions must exist."
    migration_files = sorted(versions_dir.glob("*.py"))
    assert migration_files, "backend/migrations/versions must contain migration files."
    return "\n\n".join(path.read_text(encoding="utf-8") for path in migration_files)


def _combined_storyboard_services() -> str:
    pieces: list[str] = []
    for rel in [
        ("services", "pipeline", "storyboard_source.py"),
        ("services", "pipeline", "storyboard_service.py"),
        ("services", "pipeline", "storyboard_renderer.py"),
        ("services", "pipeline", "storyboard_public_service.py"),
    ]:
        path = BACKEND_ROOT.joinpath(*rel)
        if path.exists():
            pieces.append(path.read_text(encoding="utf-8"))
    assert pieces, "Expected Storyboard pipeline service files to exist. T-252 through T-256."
    return "\n\n".join(pieces)


def _assert_contains_all(source: str, required: list[str], context: str) -> None:
    missing = [value for value in required if value not in source]
    assert not missing, f"{context} missing required tokens: {missing}"


def _assert_contains_any(source: str, options: list[str], context: str) -> None:
    assert any(option in source for option in options), (
        f"{context} must contain one of: {options}"
    )


def _source_has_word(source: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", source, re.IGNORECASE) is not None


# ===========================================================================
# T-250 - Data model and migration
# ===========================================================================


def test_t250_storyboard_model_exists_with_table_name_and_core_fields() -> None:
    src = read_backend_file("models", "storyboard.py")
    assert "class Storyboard" in src, "models/storyboard.py must define class Storyboard. T-250."
    assert "__tablename__" in src and "storyboards" in src, (
        "Storyboard model must map to the storyboards table. T-250."
    )
    _assert_contains_all(
        src,
        [
            "workspace_id",
            "user_id",
            "version",
            "status",
            "title",
            "theme",
            "content_json",
            "speaker_notes_md",
            "demo_script_md",
            "technical_appendix_md",
            "source_map_json",
            "source_stage_version_ids",
            "credit_ledger_id",
            "public_share_slug",
            "public_share_enabled",
            "allow_pdf_download",
            "allow_notes_download",
            "allow_appendix_download",
            "allow_source_layer",
        ],
        "Storyboard ORM model",
    )


def test_t250_models_init_exports_storyboard_model() -> None:
    src = read_backend_file("models", "__init__.py")
    assert "Storyboard" in src and "storyboard" in src.lower(), (
        "models/__init__.py must export Storyboard so migrations/tests can import it. T-250."
    )


def test_t250_migration_creates_storyboards_table_and_columns() -> None:
    src = _combined_migrations()
    assert "storyboards" in src, (
        "A migration must create the storyboards table. T-250."
    )
    for column in [
        "workspace_id",
        "user_id",
        "version",
        "status",
        "title",
        "content_json",
        "speaker_notes_md",
        "demo_script_md",
        "technical_appendix_md",
        "source_map_json",
        "source_stage_version_ids",
        "credit_ledger_id",
        "public_share_slug",
        "public_share_enabled",
        "allow_pdf_download",
        "allow_notes_download",
        "allow_appendix_download",
        "allow_source_layer",
    ]:
        assert column in src, f"storyboards migration missing column {column!r}. T-250."


def test_t250_migration_has_required_foreign_keys_and_cascade_delete() -> None:
    src = _combined_migrations()
    assert "workspaces" in src and "workspace_id" in src, (
        "storyboards.workspace_id must reference workspaces.id. T-250."
    )
    assert "users" in src and "user_id" in src, (
        "storyboards.user_id must reference users.id. T-250."
    )
    assert "credit_ledger" in src and "credit_ledger_id" in src, (
        "storyboards.credit_ledger_id must reference credit_ledger.id. T-250."
    )
    assert "CASCADE" in src.upper() or "ondelete=\"CASCADE\"" in src, (
        "storyboards workspace/user foreign keys must cascade on delete. T-250."
    )


def test_t250_migration_has_unique_version_and_public_slug_indexes() -> None:
    src = _combined_migrations()
    has_workspace_version_unique = (
        "workspace_id" in src
        and "version" in src
        and re.search(r"UniqueConstraint|unique=True|unique\s*=\s*True|UNIQUE", src, re.I)
    )
    assert has_workspace_version_unique, (
        "Migration must define unique (workspace_id, version). T-250."
    )
    has_public_slug_unique = (
        "public_share_slug" in src
        and re.search(r"postgresql_where|WHERE public_share_slug IS NOT NULL|isnot\(None\)", src, re.I)
        and re.search(r"unique\s*=\s*True|UNIQUE|UniqueConstraint", src, re.I)
    )
    assert has_public_slug_unique, (
        "Migration must define a partial unique index on public_share_slug when not null. T-250."
    )


def test_t250_migration_has_query_indexes_and_check_constraints() -> None:
    src = _combined_migrations()
    assert "created_at" in src and "workspace_id" in src, (
        "Migration must index (workspace_id, created_at DESC). T-250."
    )
    assert "user_id" in src and "created_at" in src, (
        "Migration must index (user_id, created_at DESC). T-250."
    )
    assert "version > 0" in src or "ck_storyboards_version" in src, (
        "Migration must constrain version > 0. T-250."
    )
    for status in ["generating", "ready", "failed", "stale"]:
        assert status in src, f"Migration status check must include {status!r}. T-250."
    assert "200" in src and "title" in src, (
        "Migration must constrain Storyboard title length to <= 200 chars. T-250."
    )


# ===========================================================================
# T-251 - Schemas and router
# ===========================================================================


def test_t251_storyboard_schemas_define_all_response_and_request_models() -> None:
    src = read_backend_file("schemas", "storyboard.py")
    _assert_contains_all(
        src,
        [
            "StoryboardSummary",
            "StoryboardDetail",
            "StoryboardGenerateRequest",
            "StoryboardRegenerateSectionRequest",
            "StoryboardShareRequest",
            "StoryboardShareResponse",
            "StoryboardPublicResponse",
            "StoryboardPresenterResponse",
        ],
        "schemas/storyboard.py",
    )
    for status in ["generating", "ready", "failed", "stale"]:
        assert status in src, f"Storyboard schemas must expose status {status!r}. T-251."


def test_t251_download_kind_schema_matches_owner_and_public_contracts() -> None:
    src = read_backend_file("schemas", "storyboard.py")
    for kind in ["html", "pdf", "notes", "demo-script", "appendix"]:
        assert kind in src, f"StoryboardDownloadKind must include {kind!r}. T-251."
    assert "md" in src and "pdf" in src and "StoryboardNotesFormat" in src, (
        "Notes download must support format=md|pdf. T-251."
    )
    assert "html" in src and "public" in src.lower(), (
        "Schemas or router must distinguish owner HTML downloads from public downloads. T-251."
    )


def test_t251_router_registers_all_owner_and_public_routes() -> None:
    src = read_backend_file("routers", "storyboards.py")
    _assert_contains_all(src, OWNER_ENDPOINT_SNIPPETS, "storyboards router")
    _assert_contains_all(src, PUBLIC_ENDPOINT_SNIPPETS, "storyboards router")
    for method in ["get", "post", "delete"]:
        assert f"@router.{method}" in src, f"storyboards router must define {method.upper()} routes. T-251."


def test_t251_main_registers_storyboards_router() -> None:
    src = read_backend_file("main.py")
    assert "storyboards" in src.lower() and "include_router" in src, (
        "main.py must import and include routers.storyboards.router. T-251."
    )


def test_t251_owner_routes_require_current_user_and_hide_idor_with_404() -> None:
    src = read_backend_file("routers", "storyboards.py")
    assert "get_current_user" in src, (
        "Owner Storyboard endpoints must depend on get_current_user. T-251/T-261."
    )
    assert "status.HTTP_404_NOT_FOUND" in src or "404" in src, (
        "Owner Storyboard lookups must return 404 for non-owned IDs. T-251/T-261."
    )
    assert "403" not in re.sub(r"HTTP_403_FORBIDDEN|status.HTTP_403_FORBIDDEN", "", src), (
        "Owner IDOR failures should not expose existence with 403. Use 404. T-251/T-261."
    )


def test_t251_mutating_storyboard_routes_are_csrf_protected_by_default() -> None:
    csrf_src = read_backend_file("middleware", "csrf.py")
    assert "/storyboards" not in csrf_src or "_EXEMPT_PATHS" not in csrf_src.split("/storyboards", 1)[0], (
        "Storyboard mutating endpoints must not be added to CSRF exemptions. T-251/T-261."
    )
    router_src = read_backend_file("routers", "storyboards.py")
    for verb in ["post", "delete"]:
        assert f"@router.{verb}" in router_src, (
            "Mutating Storyboard routes must be normal FastAPI routes so CsrfMiddleware protects them. T-251."
        )


def test_t251_public_responses_set_noindex_and_csp_headers() -> None:
    src = read_backend_file("routers", "storyboards.py")
    for token in ["X-Robots-Tag", "noindex", "Content-Security-Policy"]:
        assert token in src, f"Public Storyboard responses must set {token}. T-251/T-256."
    assert "frame-ancestors" in src and "none" in src, (
        "Public Storyboard CSP must prevent framing. T-251/T-256."
    )


def test_t251_download_routes_stream_bytes_with_content_disposition() -> None:
    src = read_backend_file("routers", "storyboards.py")
    assert "StreamingResponse" in src or "Response(" in src or "FileResponse" in src, (
        "Storyboard download routes must stream bytes. T-251/T-255."
    )
    assert "Content-Disposition" in src and "attachment" in src, (
        "Storyboard downloads must set Content-Disposition attachment filenames. T-251/T-255."
    )


# ===========================================================================
# T-252 - Source builder
# ===========================================================================


def test_t252_source_builder_exists_and_loads_only_finalised_stage_versions() -> None:
    src = _combined_storyboard_services()
    _assert_contains_any(
        src,
        ["StoryboardSourcePackage", "build_storyboard_source", "StoryboardSourceBuilder"],
        "Storyboard source builder",
    )
    for stage_type in ["spec", "plan", "harness", "tasks"]:
        assert stage_type in src.lower(), (
            f"Storyboard source builder must load finalised {stage_type.upper()} content. T-252."
        )
    assert "finalised" in src.lower(), (
        "Storyboard source builder must require all four source stages to be finalised. T-252."
    )
    assert "StageVersion" in src, (
        "Storyboard source builder must load exact StageVersion rows, not mutable Stage.content only. T-252."
    )


def test_t252_source_builder_records_immutable_source_stage_version_ids() -> None:
    src = _combined_storyboard_services()
    assert "source_stage_version_ids" in src, (
        "Storyboard generation must persist source_stage_version_ids. T-252/T-254."
    )
    for key in ["spec", "plan", "harness", "tasks"]:
        assert key in src.lower(), f"source_stage_version_ids must include {key}. T-252."


def test_t252_source_builder_bounds_excerpts_and_excludes_sensitive_data() -> None:
    src = _combined_storyboard_services()
    assert "1200" in src or "1_200" in src, (
        "Source excerpts must be bounded to 1,200 characters. T-252."
    )
    for forbidden in ["email", "credit", "billing", "jwt", "api key", "api_key", "draft"]:
        assert forbidden in src.lower(), (
            f"Source builder must explicitly exclude sensitive field {forbidden!r}. T-252."
        )


def test_t252_source_builder_prioritises_architecture_security_reliability_sections() -> None:
    src = _combined_storyboard_services()
    for section in ["architecture", "trust", "capacity", "STRIDE", "SLO", "FMEA"]:
        assert section.lower() in src.lower(), (
            f"Source builder must prioritize PLAN {section} evidence. T-252."
        )
    assert "missing_source_section" in src or "specforge_storyboard_source_missing" in src, (
        "Missing source sections must be represented explicitly, not invented. T-252/T-262."
    )


# ===========================================================================
# T-253 - Prompt builder and payload schema
# ===========================================================================


def test_t253_storyboard_prompt_exists_and_requires_exact_six_acts() -> None:
    src = read_backend_file("prompts", "storyboard.py")
    for act in REQUIRED_ACTS:
        assert act in src, f"Storyboard prompt must require act {act!r}. T-253."
    assert "exactly six" in src.lower() or "min_length=6" in src or "max_length=6" in src, (
        "Storyboard prompt/schema must require exactly six top-level acts. T-253."
    )


def test_t253_prompt_forbids_validation_and_execution_plan_as_top_level_acts() -> None:
    src = read_backend_file("prompts", "storyboard.py")
    assert "Validation" in src and "Execution Plan" in src, (
        "Prompt must explicitly forbid top-level Validation and Execution Plan acts. T-253."
    )
    assert "top-level" in src.lower() or "top level" in src.lower(), (
        "The Validation/Execution Plan ban must be scoped to top-level acts. T-253."
    )


def test_t253_prompt_requires_architecture_reveal_layers() -> None:
    src = read_backend_file("prompts", "storyboard.py")
    assert "architecture" in src.lower() and "reveal" in src.lower(), (
        "Storyboard prompt must require an architecture reveal diagram. T-253."
    )
    for layer in REQUIRED_ARCHITECTURE_LAYERS:
        assert layer in src.lower(), (
            f"Architecture reveal prompt/schema must include layer {layer!r}. T-253."
        )


def test_t253_prompt_requires_sparse_slides_notes_demo_appendix_sources_and_identity() -> None:
    src = read_backend_file("prompts", "storyboard.py")
    for phrase in [
        "18",
        "45",
        "speaker notes",
        "demo script",
        "technical appendix",
        "source map",
        "visual identity",
        "palette",
    ]:
        assert phrase.lower() in src.lower(), (
            f"Storyboard prompt must require {phrase!r}. T-253."
        )


def test_t253_payload_schema_rejects_arbitrary_html_css_js_and_remote_assets() -> None:
    src = read_backend_file("prompts", "storyboard.py")
    for forbidden in ["HTML", "CSS", "JavaScript", "iframe", "remote assets", "tracking"]:
        assert forbidden.lower() in src.lower(), (
            f"Prompt/schema must ban arbitrary {forbidden}. T-253/T-255."
        )
    assert "script" in src.lower(), (
        "Prompt/schema must explicitly forbid generated scripts. T-253/T-255."
    )


def test_t253_prompt_has_pydantic_payload_schema_and_one_repair_attempt() -> None:
    src = read_backend_file("prompts", "storyboard.py")
    for model in [
        "StoryboardPayload",
        "StoryboardTheme",
        "StoryboardSection",
        "StoryboardDiagram",
        "SourceRef",
        "SpeakerNote",
    ]:
        assert model in src, f"prompts/storyboard.py must define {model}. T-253."
    assert "repair" in src.lower() and ("one" in src.lower() or "1" in src), (
        "Invalid JSON must get one internal repair attempt before failure/refund. T-253."
    )


def test_t253_harness_schema_exists_for_storyboard_payload() -> None:
    schema = _read_repo_file("harness", "schemas", "storyboard-payload.schema.json")
    for token in [
        "Opening Thesis",
        "Product Vision",
        "Product Walkthrough",
        "Technical Architecture",
        "Trust, Security, Reliability",
        "Launch Close",
        "architecture_reveal",
        "source_map",
        "demo_script_md",
        "technical_appendix_md",
    ]:
        assert token in schema, (
            f"harness/schemas/storyboard-payload.schema.json must encode {token!r}. T-253/T-263."
        )


def test_t253_harness_schema_exists_for_public_storyboard_allow_list() -> None:
    schema = _read_repo_file("harness", "schemas", "storyboard-public-response.schema.json")
    for token in [
        "StoryboardPublicResponse",
        "allow_pdf_download",
        "allow_notes_download",
        "allow_appendix_download",
        "allow_source_layer",
        "user_id",
        "workspace_id",
        "credit_ledger_id",
        "source_stage_version_ids",
        "credit_balance",
        "previous_versions",
    ]:
        assert token in schema, (
            f"harness/schemas/storyboard-public-response.schema.json must encode {token!r}. T-253/T-256/T-263."
        )


# ===========================================================================
# T-254 - Service orchestration, credits, idempotency, recovery
# ===========================================================================


def test_t254_service_defines_generation_regeneration_section_and_stale_functions() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    for fn_name in [
        "generate_storyboard",
        "regenerate_storyboard",
        "regenerate_section",
        "mark_workspace_storyboards_stale",
    ]:
        assert fn_name in src, f"storyboard_service.py must define {fn_name}. T-254."


def test_t254_service_charges_25_for_full_and_5_for_section_regeneration() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    assert "25" in src and "storyboard_generate" in src, (
        "Full Storyboard generation/regeneration must deduct 25 credits with reason storyboard_generate:{id}. T-254."
    )
    assert "5" in src and "storyboard_section" in src, (
        "Section regeneration must deduct 5 credits with reason storyboard_section:{id}:{section_id}. T-254."
    )
    assert "credit_service.deduct" in src or ".deduct(" in src, (
        "Storyboard service must use CreditService.deduct. T-254."
    )


def test_t254_service_refunds_exactly_once_on_failure_and_keeps_failed_status() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    assert "refund" in src.lower() and "credit_service.refund" in src or ".refund(" in src, (
        "Storyboard service must refund credits when generation fails. T-254."
    )
    assert "failed" in src.lower(), (
        "Storyboard service must mark failed generations as status='failed'. T-254."
    )
    assert "refund:" in src or "existing_refund" in src or "credit_service.refund" in src, (
        "Refunds must be idempotent through the credit ledger refund path. T-254."
    )


def test_t254_service_uses_idempotency_lock_and_generating_reuse_to_avoid_double_charge() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    assert "storyboard:generate" in src or "idempotency" in src.lower(), (
        "Generate must acquire a Redis idempotency lock such as storyboard:generate:{workspace_id}:{user_id}. T-254."
    )
    assert "generating" in src.lower(), (
        "Duplicate generate requests must reuse an in-progress generating Storyboard instead of charging again. T-254."
    )
    assert "setnx" in src.lower() or ".set(" in src or "lock" in src.lower(), (
        "Idempotency must be backed by Redis lock semantics. T-254."
    )


def test_t254_service_uses_row_lock_and_unique_version_assignment() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    assert "with_for_update" in src or "FOR UPDATE" in src, (
        "Storyboard version assignment must lock the workspace row with SELECT FOR UPDATE. T-254."
    )
    assert "max(" in src.lower() and "version" in src.lower(), (
        "Storyboard service must assign version = max(version)+1 per workspace. T-254."
    )


def test_t254_regeneration_preserves_previous_ready_storyboard_until_replacement_ready() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    previous_ready_terms = [
        "previous_ready",
        "previous ready",
        "prior ready",
        "old_version",
        "replacement",
    ]
    _assert_contains_any(
        src.lower(),
        [term.lower() for term in previous_ready_terms],
        "Full/section regeneration",
    )
    assert "delete(" not in src.lower() or "storyboard" not in src.lower().split("delete(", 1)[1][:120], (
        "Regeneration must not delete the previous ready Storyboard while replacement is generating. T-254."
    )


def test_t254_stage_manager_marks_ready_storyboards_stale_on_source_refinalise() -> None:
    stage_manager = read_backend_file("services", "pipeline", "stage_manager.py")
    assert "mark_workspace_storyboards_stale" in stage_manager or "Storyboard" in stage_manager, (
        "StageManager.finalise() must call mark_workspace_storyboards_stale() when source stages are re-finalised. T-254."
    )
    assert "stale" in stage_manager.lower(), (
        "StageManager finalise path must mark existing ready Storyboards stale. T-254."
    )


def test_t254_recovery_handles_stuck_generating_storyboards_with_refund() -> None:
    recovery_src = read_backend_file("services", "pipeline", "recovery_service.py")
    service_src = read_backend_file("services", "pipeline", "storyboard_service.py")
    combined = recovery_src + "\n" + service_src
    assert "storyboard" in combined.lower() and "generating" in combined.lower(), (
        "Recovery must detect stuck Storyboards in status='generating'. T-254."
    )
    assert "30" in combined and "minute" in combined.lower(), (
        "Generating Storyboards older than 30 minutes must be failed/recovered. T-254."
    )
    assert "refund" in combined.lower(), (
        "Stuck generating Storyboards with a credit ledger ID must be refunded. T-254."
    )


def test_t254_credit_cache_invalidated_after_storyboard_credit_mutations() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_service.py")
    assert "invalidate_user_cache" in src or "clear_user_cache" in src or "delete(" in src and "credits" in src.lower(), (
        "Storyboard credit deduction/refund must invalidate stale credit cache after commit. T-254."
    )


# ===========================================================================
# T-255 - Renderer and downloads
# ===========================================================================


def test_t255_renderer_exists_and_uses_trusted_template_not_raw_llm_html() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_renderer.py")
    assert "render" in src.lower(), "storyboard_renderer.py must expose renderer functions. T-255."
    assert "template" in src.lower(), (
        "Storyboard HTML must be assembled from a trusted template. T-255."
    )
    assert "raw" not in src.lower() or "raw_html" not in src.lower(), (
        "Renderer must not write raw LLM HTML into output. T-255."
    )


def test_t255_renderer_sanitizes_markdown_labels_notes_and_appendix() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_renderer.py")
    assert "sanitize" in src.lower() or "bleach" in src.lower(), (
        "Renderer must sanitize generated markdown/labels/notes/appendix. T-255."
    )
    for field in ["speaker_notes", "demo_script", "technical_appendix"]:
        assert field in src.lower(), f"Renderer must handle and sanitize {field}. T-255."


def test_t255_renderer_bans_remote_scripts_styles_iframes_and_assets() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_renderer.py")
    for token in ["script", "iframe", "object", "embed", "remote", "http://", "https://"]:
        assert token.lower() in src.lower(), (
            f"Renderer must explicitly reject or avoid {token!r}. T-255."
        )
    assert "default-src 'self'" in src or "default-src" in src, (
        "Renderer/HTML package must define a restrictive CSP. T-255."
    )


def test_t255_pdf_rendering_uses_no_network_fetcher_or_equivalent() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_renderer.py")
    pdf_src = read_backend_file("services", "pipeline", "pdf_export_service.py")
    combined = src + "\n" + pdf_src
    assert "url_fetcher" in combined or "no_network" in combined.lower() or "blocked" in combined.lower(), (
        "Storyboard PDF rendering must use the existing no-network fetcher or equivalent. T-255."
    )


def test_t255_download_filenames_are_stable_and_product_specific() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_renderer.py")
    for filename in [
        "specforge-storyboard-",
        "speaker-notes",
        "demo-script",
        "technical-appendix",
    ]:
        assert filename in src, f"Renderer must produce stable filename token {filename!r}. T-255."


# ===========================================================================
# T-256 - Public sharing
# ===========================================================================


def test_t256_public_service_exists_with_independent_slug_and_defaults() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_public_service.py")
    assert "public_share_slug" in src, "Public Storyboard service must manage public_share_slug. T-256."
    assert "10" in src or "slug_length" in src.lower(), (
        "Public Storyboard slugs must be at least 10 random base36 chars. T-256."
    )
    assert "allow_pdf_download" in src and "True" in src, (
        "Default public PDF download permission should be enabled. T-256."
    )
    for field in ["allow_notes_download", "allow_appendix_download", "allow_source_layer"]:
        assert field in src and "False" in src, (
            f"Default public permission {field} must be disabled. T-256."
        )


def test_t256_public_service_uses_csprng_and_unambiguous_base36_like_slug() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_public_service.py")
    assert "secrets" in src or "token_urlsafe" in src or "SystemRandom" in src, (
        "Public Storyboard slug generation must use a cryptographic RNG. T-256."
    )
    assert "base36" in src.lower() or "ascii_lowercase" in src or "digits" in src, (
        "Public Storyboard slug generation must use base36/base62-like opaque tokens. T-256."
    )


def test_t256_public_response_filters_owner_private_fields_and_disabled_downloads() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_public_service.py")
    for private in [
        "user_id",
        "workspace_id",
        "credit_ledger_id",
        "source_stage_version_ids",
        "billing",
        "credit_balance",
        "email",
    ]:
        assert private in src.lower(), (
            f"Public Storyboard filtering must explicitly exclude {private}. T-256/T-261."
        )
    for permission in ["allow_notes_download", "allow_appendix_download", "allow_source_layer"]:
        assert permission in src, f"Public response must respect {permission}. T-256."


def test_t256_public_disabled_or_unknown_slug_returns_404_not_403() -> None:
    src = read_backend_file("services", "pipeline", "storyboard_public_service.py") + "\n" + read_backend_file("routers", "storyboards.py")
    assert "404" in src or "HTTP_404_NOT_FOUND" in src, (
        "Disabled or unknown public Storyboard slugs must return 404. T-256."
    )
    assert "403" not in src or "HTTP_403_FORBIDDEN" not in src, (
        "Public disabled/unknown Storyboard slugs must not return 403. T-256."
    )


def test_t256_public_html_package_download_is_not_exposed_by_default() -> None:
    src = read_backend_file("routers", "storyboards.py")
    public_download_body = src[src.find("/storyboards/public") :]
    assert "html" not in public_download_body or "allow_html_download" in public_download_body, (
        "Public download endpoint must not expose HTML package by default. T-256."
    )


# ===========================================================================
# T-261 - Security and rate limits
# ===========================================================================


def test_t261_rate_limit_middleware_defines_all_storyboard_tiers() -> None:
    src = read_backend_file("middleware", "rate_limit.py")
    for phrase in [
        "Storyboard Generate",
        "Storyboard Section Regenerate",
        "Storyboard Share Toggle",
        "Storyboard Public View",
        "Storyboard Download",
    ]:
        assert phrase in src or phrase.lower().replace(" ", "_") in src.lower(), (
            f"Rate limit middleware must define tier {phrase!r}. T-261."
        )
    for limit in ["3", "10", "20", "120", "30"]:
        assert limit in src, f"Storyboard rate limit value {limit} must appear. T-261."


def test_t261_public_storyboard_route_is_auth_exempt_but_owner_routes_are_not() -> None:
    router_src = read_backend_file("routers", "storyboards.py")
    assert "get_current_user" in router_src, "Owner routes must require auth. T-261."
    public_slice = router_src[router_src.find("/storyboards/public") :]
    assert "get_current_user" not in public_slice or "get_optional_user" in public_slice, (
        "Public Storyboard routes must not require authenticated owner dependency. T-261."
    )


def test_t261_no_storyboard_logs_include_generated_content_or_source_excerpts() -> None:
    src = _combined_storyboard_services()
    forbidden_log_fields = [
        "speaker_notes_md",
        "technical_appendix_md",
        "demo_script_md",
        "source_excerpt",
        "content_json",
        "raw_generated",
    ]
    log_calls = "\n".join(
        line for line in src.splitlines() if "logger." in line or "structlog" in line
    )
    for field in forbidden_log_fields:
        assert field not in log_calls, (
            f"Storyboard logs must not include generated content field {field}. T-261/T-262."
        )


def test_t261_renderer_schema_rejects_script_injection_from_source_artifacts() -> None:
    renderer_src = read_backend_file("services", "pipeline", "storyboard_renderer.py")
    tests_dir = BACKEND_ROOT / "tests"
    combined_tests = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tests_dir.glob("test_storyboard*.py")
    ) if tests_dir.exists() else ""
    combined = renderer_src + "\n" + combined_tests
    assert "<script>" in combined or "script" in combined.lower(), (
        "Renderer tests or implementation must cover script injection from source artifacts. T-261/T-263."
    )
    assert "remote" in combined.lower() or "http://evil" in combined.lower() or "https://evil" in combined.lower(), (
        "Renderer tests or implementation must cover remote asset injection. T-261/T-263."
    )


# ===========================================================================
# T-262 - Observability
# ===========================================================================


def test_t262_observability_defines_all_storyboard_metrics() -> None:
    src = read_backend_file("services", "observability.py")
    for metric in [
        "specforge_storyboard_generation_started_total",
        "specforge_storyboard_generation_completed_total",
        "specforge_storyboard_generation_failed_total",
        "specforge_storyboard_section_regenerated_total",
        "specforge_storyboard_generation_duration_seconds",
        "specforge_storyboard_credits_deducted_total",
        "specforge_storyboard_credits_refunded_total",
        "specforge_storyboard_public_view_total",
        "specforge_storyboard_download_total",
        "specforge_storyboard_source_missing_total",
    ]:
        assert metric in src, f"services/observability.py missing metric {metric}. T-262."


def test_t262_storyboard_structlog_event_names_are_present() -> None:
    src = _combined_storyboard_services()
    for event in [
        "storyboard.generate_started",
        "storyboard.generate_completed",
        "storyboard.generate_failed",
        "storyboard.section_regenerated",
        "storyboard.share_enabled",
        "storyboard.share_disabled",
        "storyboard.share_rotated",
        "storyboard.downloaded",
        "storyboard.public_viewed",
        "storyboard.marked_stale",
    ]:
        assert event in src, f"Storyboard service must emit structlog event {event}. T-262."


# ===========================================================================
# T-263/T-264 - Unit tests, docs, and smoke gate coverage
# ===========================================================================


def test_t263_backend_unit_tests_cover_storyboard_critical_paths() -> None:
    tests_dir = BACKEND_ROOT / "tests"
    assert tests_dir.exists(), "backend/tests must exist. T-263."
    combined = "\n".join(path.read_text(encoding="utf-8") for path in tests_dir.glob("test_storyboard*.py"))
    for test_name in [
        "test_storyboard_generation_requires_all_stages_finalised",
        "test_storyboard_generation_deducts_25_credits",
        "test_storyboard_generation_refunds_on_llm_failure",
        "test_storyboard_duplicate_generate_does_not_double_charge",
        "test_storyboard_full_regeneration_preserves_previous_ready_version_on_failure",
        "test_storyboard_section_regeneration_costs_5_credits",
        "test_storyboard_marks_stale_when_source_stage_refinalised",
        "test_storyboard_public_owner_permissions_filter_downloads",
        "test_storyboard_public_unknown_or_disabled_returns_404",
        "test_storyboard_source_map_contains_only_finalised_versions",
        "test_storyboard_schema_rejects_validation_or_execution_plan_top_level_acts",
        "test_storyboard_architecture_reveal_requires_layers",
        "test_storyboard_renderer_strips_script_and_remote_asset_references",
    ]:
        assert test_name in combined, f"Missing backend unit test {test_name}. T-263."


def test_t264_storyboard_documentation_is_updated_before_release() -> None:
    docs = {
        "docs/RUNBOOK.md": ["Storyboard", "refund", "stale", "slug", "disable"],
        "docs/LOCAL_TESTING_HANDBOOK.md": ["Storyboard", "/sb/", "download"],
        "docs/OBSERVABILITY_RUNBOOK.md": ["specforge_storyboard", "generation_failed", "refund"],
        "docs/PRODUCTION_RELEASE_GATE.md": ["Storyboard", "migration", "rate limit", "CSP", "sanitizer"],
        "docs/SMOKE_TEST_CHECKLIST.md": ["Storyboard", "incognito", "speaker notes", "appendix"],
    }
    for rel_path, required_terms in docs.items():
        src = _read_repo_file(*rel_path.split("/"))
        for term in required_terms:
            assert term.lower() in src.lower(), (
                f"{rel_path} must document Storyboard release/smoke requirement {term!r}. T-264."
            )


def test_t264_tasks_file_contains_implementation_tasks_for_t250_through_t264() -> None:
    src = _read_repo_file("tasks.md")
    for task_id in [f"T-{number}" for number in range(250, 265)]:
        assert task_id in src, f"tasks.md must contain implementation task {task_id}. T-264."
    assert "Storyboard" in src, "tasks.md Phase 23 tasks must be about Storyboard. T-264."
