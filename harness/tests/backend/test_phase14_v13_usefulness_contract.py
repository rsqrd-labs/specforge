"""
Harness contracts for Plan v1.md §18, Phase 14 — V1.3 Usefulness Improvements.

These tests describe the implementation contract for the six v1.3 features:
Spec Clarification, per-task Priority + Estimate, PDF Export, Public Share,
Starter Templates, and Harness Coverage Surfacing.

They are RED before T-USE-01 through T-USE-13 are implemented and GREEN after.

Design invariants enforced here:
  * Two new Alembic migrations apply cleanly: Workspace v1.3 fields, Template table.
  * Workspace model carries template_slug, clarification_qa, public_share_slug,
    public_share_enabled.
  * Template model is system-owned (no user_id FK) and has a unique slug.
  * Spec Clarification is judge-model backed, free, and best-effort — no credit
    deduction, sanitisation applied to answers, JSON-shape persisted on workspace.
  * PDF export uses WeasyPrint (no headless browser), explicit no-network resource
    fetcher, application/pdf media type, attachment Content-Disposition.
  * Public share endpoint is unauthenticated, returns an explicit allow-list
    response shape, sets noindex headers, requires all four stages finalised.
  * Slug generation uses an unambiguous alphabet (no 0/o/1/l/i) and is collision-
    resistant via DB unique constraint.
  * Templates endpoint is unauthenticated and returns only active templates.
  * Harness coverage figure is exposed in the workspace response shape (no DB
    schema change) and never raises if the harness stage is absent.
  * Existing Phase 13 GitHub export and ZIP export paths are unchanged.
"""

from __future__ import annotations


from conftest import BACKEND_ROOT, REPO_ROOT, read_backend_file


# ---------------------------------------------------------------------------
# T-USE-01: DB migrations
# ---------------------------------------------------------------------------


def test_phase14_workspace_v1_3_fields_migration_exists() -> None:
    # Tests: T-USE-01
    # Plan §18.3: dedicated migration adding template_slug, clarification_qa,
    # public_share_slug, public_share_enabled to the workspaces table.
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    matches = list(versions_dir.glob("*workspace_v1_3*"))
    assert matches, (
        "No Alembic migration file matching '*workspace_v1_3*' found. "
        "T-USE-01 step 1 requires '0009_workspace_v1_3_fields.py'."
    )


def test_phase14_workspace_v1_3_migration_adds_all_four_columns() -> None:
    # Tests: T-USE-01
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    matches = list(versions_dir.glob("*workspace_v1_3*"))
    assert matches, "migration file missing — see test above"
    source = matches[0].read_text(encoding="utf-8")
    for column in [
        "template_slug",
        "clarification_qa",
        "public_share_slug",
        "public_share_enabled",
    ]:
        assert column in source, (
            f"Workspace v1.3 migration must add column '{column}'. Not found in "
            f"{matches[0].name}."
        )


def test_phase14_workspace_v1_3_migration_creates_unique_constraint_on_share_slug() -> None:
    # Tests: T-USE-01, SEC: an active public_share_slug must be unique so two
    # workspaces cannot collide on /public/{slug}.
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    matches = list(versions_dir.glob("*workspace_v1_3*"))
    assert matches, "migration file missing — see test above"
    source = matches[0].read_text(encoding="utf-8")
    assert "public_share_slug" in source and (
        "unique" in source.lower() or "UniqueConstraint" in source
    ), (
        "Workspace v1.3 migration must declare a unique constraint on "
        "public_share_slug (or a partial unique index where enabled is true)."
    )


def test_phase14_templates_migration_exists() -> None:
    # Tests: T-USE-01
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    matches = list(versions_dir.glob("*templates*"))
    assert matches, (
        "No Alembic migration file matching '*templates*' found. "
        "T-USE-01 step 2 requires '0010_templates.py'."
    )


def test_phase14_templates_migration_creates_templates_table() -> None:
    # Tests: T-USE-01
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    matches = list(versions_dir.glob("*templates*"))
    assert matches, "templates migration missing — see test above"
    source = matches[0].read_text(encoding="utf-8")
    assert "templates" in source, "Templates migration must create table 'templates'."
    for field in [
        "slug",
        "name",
        "description",
        "category",
        "problem_statement",
        "sort_order",
        "active",
    ]:
        assert field in source, (
            f"Templates migration must define column '{field}'."
        )
    assert "unique" in source.lower() or "UniqueConstraint" in source, (
        "Templates migration must declare slug as unique."
    )


# ---------------------------------------------------------------------------
# T-USE-02: ORM models and schemas
# ---------------------------------------------------------------------------


def test_phase14_workspace_model_has_v1_3_fields() -> None:
    # Tests: T-USE-02
    # Plan §10: Workspace gains four new fields. The model file must reflect
    # these so SQLAlchemy can read and write them.
    source = read_backend_file("models", "workspace.py")
    for field in [
        "template_slug",
        "clarification_qa",
        "public_share_slug",
        "public_share_enabled",
    ]:
        assert field in source, (
            f"models/workspace.py must declare field '{field}'. "
            "See Plan §10 / Phase 14."
        )


def test_phase14_template_model_exists() -> None:
    # Tests: T-USE-02
    assert (BACKEND_ROOT / "models" / "template.py").exists(), (
        "not implemented: T-USE-02 — backend/models/template.py"
    )


def test_phase14_template_model_has_required_fields() -> None:
    # Tests: T-USE-02
    source = read_backend_file("models", "template.py")
    for field in [
        "slug",
        "name",
        "description",
        "category",
        "problem_statement",
        "sort_order",
        "active",
    ]:
        assert field in source, (
            f"Template model missing field '{field}'. See Plan §10."
        )
    assert "templates" in source, (
        "Template.__tablename__ must be 'templates'."
    )


def test_phase14_template_model_has_no_user_fk() -> None:
    # Tests: T-USE-02, Spec §4.11: templates are system-owned in V1. A
    # ForeignKey to users.id would imply user-authored templates which are
    # explicitly V2.
    source = read_backend_file("models", "template.py")
    assert "users.id" not in source and "user_id" not in source, (
        "Template model must not reference users.id. Templates are system-owned "
        "in V1 — user-authored templates are V2 (see Spec §14)."
    )


def test_phase14_models_init_exports_template() -> None:
    # Tests: T-USE-02: models/__init__.py must export Template so Alembic
    # autogenerate sees it on future revisions.
    source = read_backend_file("models", "__init__.py")
    assert "Template" in source, (
        "models/__init__.py must export 'Template' so Alembic autogenerate "
        "detects the Phase 14 templates table."
    )


def test_phase14_workspace_schema_exposes_v1_3_fields() -> None:
    # Tests: T-USE-02
    # Plan §11: the workspace response now includes the new optional fields
    # so the frontend can render the public-share toggle, template provenance,
    # and clarification Q&A.
    source = read_backend_file("schemas", "workspace.py")
    for field in [
        "template_slug",
        "public_share_slug",
        "public_share_enabled",
    ]:
        assert field in source, (
            f"schemas/workspace.py must expose '{field}' in the response model."
        )


# ---------------------------------------------------------------------------
# T-USE-03: Spec Clarification backend
# ---------------------------------------------------------------------------


def test_phase14_spec_clarifier_module_exists() -> None:
    # Tests: T-USE-03
    assert (BACKEND_ROOT / "services" / "pipeline" / "spec_clarifier.py").exists(), (
        "not implemented: T-USE-03 — backend/services/pipeline/spec_clarifier.py"
    )


def test_phase14_spec_clarifier_defines_required_functions() -> None:
    # Tests: T-USE-03
    source = read_backend_file("services", "pipeline", "spec_clarifier.py")
    for fn_name in ["request_clarifying_questions", "persist_answers"]:
        assert fn_name in source, (
            f"spec_clarifier.py is missing '{fn_name}'. "
            "Plan §18.3 / T-USE-03 lists these as the two entry points."
        )


def test_phase14_spec_clarifier_uses_judge_model_not_full_provider() -> None:
    # Tests: T-USE-03: clarification must use the cheap judge model (Haiku /
    # GPT-4o Mini / Gemini Flash), the same selector used by evals.
    source = read_backend_file("services", "pipeline", "spec_clarifier.py")
    lowered = source.lower()
    assert "judge" in lowered or "haiku" in lowered or "online_eval" in lowered, (
        "spec_clarifier.py must reuse the judge-model selection logic from "
        "services/evals (e.g. import the judge selector). A clarification call "
        "must not invoke the full-tier model."
    )


def test_phase14_spec_clarifier_is_best_effort_with_timeout() -> None:
    # Tests: T-USE-03: Plan §18.3 requires a ~5s timeout so the modal never
    # blocks the standard generate path.
    source = read_backend_file("services", "pipeline", "spec_clarifier.py")
    assert "timeout" in source.lower(), (
        "spec_clarifier.py must declare an asyncio timeout / httpx timeout on "
        "the judge-model call. Best-effort: failure flows through to standard generate."
    )


def test_phase14_spec_clarifier_does_not_charge_credits() -> None:
    # Tests: T-USE-03: the spec explicitly states clarification is free.
    # The service must not import the credit_service or call its deduction APIs.
    source = read_backend_file("services", "pipeline", "spec_clarifier.py")
    for forbidden in ["credit_service.deduct", "deduct_credits", "spend_credits"]:
        assert forbidden not in source, (
            f"spec_clarifier.py must not call '{forbidden}'. Clarification is free."
        )


def test_phase14_clarify_routes_declared_in_workspace_router() -> None:
    # Tests: T-USE-03, Spec §11: POST /workspaces/{id}/clarify and
    # PATCH /workspaces/{id}/clarify must be declared in routers/workspace.py.
    source = read_backend_file("routers", "workspace.py")
    assert "/clarify" in source or "clarify" in source, (
        "routers/workspace.py must define the clarify endpoints. See Spec §11."
    )


def test_phase14_clarify_persists_answers_through_sanitiser() -> None:
    # Tests: T-USE-03, SEC: clarification answers are user-supplied free text
    # and must pass through the same prompt-injection guard / sanitiser
    # pipeline as the problem statement.
    source = read_backend_file("services", "pipeline", "spec_clarifier.py")
    sanitises = (
        "sanitize_text" in source
        or "prompt_injection" in source
        or "PromptInjectionGuard" in source
        or "InputSanitiser" in source
    )
    assert sanitises, (
        "spec_clarifier.py must apply the sanitisation / prompt-injection guard "
        "to each answer before persisting it. Free text from users must never "
        "be stored or injected into prompts unchecked."
    )


def test_phase14_spec_prompt_accepts_optional_clarification_qa() -> None:
    # Tests: T-USE-03: prompts/spec.py (or equivalent prompt builder) must
    # accept an optional clarification_qa argument so the Q&A pairs land in
    # the user prompt without re-engineering the call site.
    candidates = [
        BACKEND_ROOT / "prompts" / "spec.py",
        BACKEND_ROOT / "prompts" / "spec_prompt.py",
        BACKEND_ROOT / "services" / "pipeline" / "prompt_builder.py",
    ]
    found = False
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if "clarification" in text.lower():
                found = True
                break
    assert found, (
        "Spec prompt builder must accept and render an optional clarification_qa "
        "argument. Checked: "
        + ", ".join(str(c.relative_to(REPO_ROOT)) for c in candidates)
    )


# ---------------------------------------------------------------------------
# T-USE-05: Task Priority + Estimate
# ---------------------------------------------------------------------------


def test_phase14_tasks_prompt_mandates_priority_and_estimate_fields() -> None:
    # Tests: T-USE-05, Spec §5.4: the tasks prompt template must mandate the
    # Priority and Estimate fields on every emitted task.
    candidates = [
        BACKEND_ROOT / "prompts" / "tasks.py",
        BACKEND_ROOT / "prompts" / "tasks_prompt.py",
        BACKEND_ROOT / "prompts" / "tasks.md",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text += path.read_text(encoding="utf-8")
    assert text, (
        "No tasks prompt file found under backend/prompts/. T-USE-05 must edit "
        "this file to require Priority and Estimate."
    )
    for keyword in ["Priority", "Estimate"]:
        assert keyword in text, (
            f"Tasks prompt template must mandate '{keyword}'. See Spec §5.4."
        )
    has_priority_enum = "MUST" in text and "SHOULD" in text and "COULD" in text
    assert has_priority_enum, (
        "Tasks prompt must constrain Priority to the MUST/SHOULD/COULD enum."
    )


def test_phase14_tasks_prompt_includes_effort_summary_block() -> None:
    # Tests: T-USE-05, Spec §5.4
    candidates = [
        BACKEND_ROOT / "prompts" / "tasks.py",
        BACKEND_ROOT / "prompts" / "tasks_prompt.py",
        BACKEND_ROOT / "prompts" / "tasks.md",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text += path.read_text(encoding="utf-8")
    assert "Effort Summary" in text or "effort_summary" in text.lower(), (
        "Tasks prompt must mandate the project-level '## Effort Summary' block "
        "at the top of TASKS.md."
    )


def test_phase14_online_eval_validates_priority_and_estimate() -> None:
    # Tests: T-USE-05, Spec §5.4: the online eval task-reference validator
    # must additionally check that each task carries Priority and Estimate.
    source = read_backend_file("services", "evals", "online_eval.py")
    has_priority_check = "Priority" in source or "MISSING_PRIORITY" in source
    has_estimate_check = "Estimate" in source or "MISSING_ESTIMATE" in source
    assert has_priority_check and has_estimate_check, (
        "services/evals/online_eval.py must validate Priority and Estimate per "
        "task. Add structural checks and emit MISSING_PRIORITY / MISSING_ESTIMATE "
        "issues into tasks_without_ref."
    )


# ---------------------------------------------------------------------------
# T-USE-07: PDF Export
# ---------------------------------------------------------------------------


def test_phase14_pdf_export_service_module_exists() -> None:
    # Tests: T-USE-07
    assert (BACKEND_ROOT / "services" / "pipeline" / "pdf_export_service.py").exists(), (
        "not implemented: T-USE-07 — backend/services/pipeline/pdf_export_service.py"
    )


def test_phase14_pdf_export_service_uses_weasyprint() -> None:
    # Tests: T-USE-07, Plan §18.3: WeasyPrint is the chosen renderer (no
    # headless browser). The service must not pull in playwright/puppeteer.
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")
    assert "weasyprint" in source.lower(), (
        "pdf_export_service.py must use WeasyPrint. Plan §18.3 selects "
        "WeasyPrint over Playwright/Chromium for the V1 PDF renderer."
    )
    for forbidden in ["playwright", "pyppeteer", "selenium"]:
        assert forbidden not in source.lower(), (
            f"pdf_export_service.py must not import '{forbidden}'. "
            "Phase 14 ships WeasyPrint only."
        )


def test_phase14_pdf_export_service_defines_render_function() -> None:
    # Tests: T-USE-07
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")
    assert "render" in source or "build_pdf" in source, (
        "pdf_export_service.py must expose a render/build entry point used by "
        "the route handler."
    )


def test_phase14_pdf_export_service_disables_network_resource_fetching() -> None:
    # Tests: T-USE-07, SEC (Plan §18.4): WeasyPrint must be configured with a
    # no-network resource fetcher so a malicious <img src> cannot exfiltrate.
    source = read_backend_file("services", "pipeline", "pdf_export_service.py")
    has_fetcher_guard = (
        "url_fetcher" in source
        or "URLFetcher" in source
        or "no_network" in source.lower()
        or "no-network" in source
    )
    assert has_fetcher_guard, (
        "pdf_export_service.py must pass a no-network url_fetcher to WeasyPrint "
        "so external HTTP fetches during PDF render are blocked. See Plan §18.4."
    )


def test_phase14_pdf_export_template_exists() -> None:
    # Tests: T-USE-07
    candidates = [
        BACKEND_ROOT / "templates" / "export.html.j2",
        BACKEND_ROOT / "templates" / "export_pdf.html.j2",
        BACKEND_ROOT / "templates" / "pdf_export.html.j2",
    ]
    assert any(c.exists() for c in candidates), (
        "PDF export Jinja template missing. Expected one of: "
        + ", ".join(str(c.relative_to(REPO_ROOT)) for c in candidates)
    )


def test_phase14_pdf_export_endpoint_declared_in_workspace_router() -> None:
    # Tests: T-USE-07, Spec §11
    source = read_backend_file("routers", "workspace.py")
    assert "export/pdf" in source or "export_pdf" in source, (
        "routers/workspace.py must define POST /workspaces/{id}/export/pdf."
    )


def test_phase14_pdf_export_returns_application_pdf_media_type() -> None:
    # Tests: T-USE-07: the route must set Content-Type to application/pdf so
    # browsers download / inline-render correctly.
    source = read_backend_file("routers", "workspace.py")
    assert "application/pdf" in source, (
        "PDF export route must return Content-Type: application/pdf."
    )


def test_phase14_pdf_export_rate_limit_tier_declared() -> None:
    # Tests: T-USE-07, Spec §12: PDF export tier is 10 per user per hour.
    source = read_backend_file("middleware", "rate_limit.py")
    assert "pdf" in source.lower(), (
        "middleware/rate_limit.py must define a PDF export rate-limit tier. "
        "See Spec §12: 10 PDF exports per user per hour."
    )


# ---------------------------------------------------------------------------
# T-USE-09: Public Share backend
# ---------------------------------------------------------------------------


def test_phase14_public_share_service_module_exists() -> None:
    # Tests: T-USE-09
    candidates = [
        BACKEND_ROOT / "services" / "sharing" / "public_share_service.py",
        BACKEND_ROOT / "services" / "pipeline" / "public_share_service.py",
    ]
    assert any(c.exists() for c in candidates), (
        "Public share service missing. Expected one of: "
        + ", ".join(str(c.relative_to(REPO_ROOT)) for c in candidates)
    )


def test_phase14_public_share_service_defines_enable_disable_rotate() -> None:
    # Tests: T-USE-09
    candidates = [
        BACKEND_ROOT / "services" / "sharing" / "public_share_service.py",
        BACKEND_ROOT / "services" / "pipeline" / "public_share_service.py",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            break
    for fn_name in ["enable", "disable", "rotate"]:
        assert fn_name in text, (
            f"public_share_service.py must define '{fn_name}'. "
            "Plan §18.3 lists these as the three lifecycle entry points."
        )


def test_phase14_public_share_slug_alphabet_excludes_ambiguous_chars() -> None:
    # Tests: T-USE-09, SEC: slug alphabet must omit 0/o/1/l/i so users can
    # read the URL off a screen without confusion.
    candidates = [
        BACKEND_ROOT / "services" / "sharing" / "public_share_service.py",
        BACKEND_ROOT / "services" / "pipeline" / "public_share_service.py",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            break
    assert "ALPHABET" in text or "alphabet" in text or "string." in text, (
        "public_share_service.py must define a slug alphabet constant."
    )
    has_filtered_alphabet = (
        "abcdefghjkmnpqrstuvwxyz" in text
        or "ABCDEFGHJKLMNPQRSTUVWXYZ" in text
        or "no ambiguous" in text.lower()
    )
    assert has_filtered_alphabet, (
        "public_share_service.py must use an unambiguous alphabet "
        "(no 0/o/1/l/i). Plan §18.3 specifies the 31-character alphabet."
    )


def test_phase14_public_share_slug_uses_secrets_module() -> None:
    # Tests: T-USE-09, SEC: slug generation must use 'secrets' (CSPRNG), not
    # 'random' (predictable).
    candidates = [
        BACKEND_ROOT / "services" / "sharing" / "public_share_service.py",
        BACKEND_ROOT / "services" / "pipeline" / "public_share_service.py",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            break
    assert "import secrets" in text or "from secrets" in text or "secrets." in text, (
        "public_share_service.py must use the 'secrets' module for slug "
        "generation. The 'random' module is not cryptographically secure."
    )


def test_phase14_public_share_requires_all_stages_finalised() -> None:
    # Tests: T-USE-09, Spec §4.8: enabling sharing on a workspace with any
    # non-finalised stage must be rejected.
    candidates = [
        BACKEND_ROOT / "services" / "sharing" / "public_share_service.py",
        BACKEND_ROOT / "services" / "pipeline" / "public_share_service.py",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            break
    assert "finalised" in text.lower() or "finalized" in text.lower(), (
        "public_share_service.py must check that all four stages are finalised "
        "before enabling sharing. See Spec §4.8 / Plan §18.3."
    )


def test_phase14_public_router_exists() -> None:
    # Tests: T-USE-09
    assert (BACKEND_ROOT / "routers" / "public.py").exists(), (
        "not implemented: T-USE-09 — backend/routers/public.py (the "
        "unauthenticated read-only public-view router)."
    )


def test_phase14_public_router_registered_in_main_app() -> None:
    # Tests: T-USE-09
    source = read_backend_file("main.py")
    assert "public" in source.lower(), (
        "main.py must import and mount the public router. "
        "/public/{slug} will not be reachable otherwise."
    )


def test_phase14_public_router_uses_allow_list_response_shape() -> None:
    # Tests: T-USE-09, SEC (Plan §18.4): the public endpoint must build its
    # response from an explicit allow-list helper, not by serialising the
    # Workspace ORM model directly. This prevents leaking new fields.
    source = read_backend_file("routers", "public.py")
    # The endpoint must NOT use a generic Workspace ORM dump.
    risky_serialisation = (
        ".dict()" in source and "Workspace" in source and "exclude" not in source
    )
    assert not risky_serialisation, (
        "routers/public.py must not serialise the Workspace ORM model directly. "
        "Build the response from an allow-list dict so future fields don't leak "
        "into the public view. See Plan §18.4."
    )
    # And must reference a helper or explicit field list.
    has_explicit_shape = (
        "build_public_view" in source
        or "PublicWorkspaceResponse" in source
        or "allow_list" in source.lower()
        or "{\"name\"" in source
    )
    assert has_explicit_shape, (
        "routers/public.py must build the response from a named allow-list "
        "function or Pydantic model (e.g. PublicWorkspaceResponse / "
        "build_public_view)."
    )


def test_phase14_public_router_sets_noindex_headers() -> None:
    # Tests: T-USE-09, SEC (Plan §18.4): the public route must signal noindex
    # to crawlers via headers, in addition to the frontend meta tag.
    source = read_backend_file("routers", "public.py")
    assert "noindex" in source.lower() or "X-Robots-Tag" in source, (
        "routers/public.py must set 'X-Robots-Tag: noindex, nofollow' (or "
        "equivalent) so crawlers ignore the route even if a meta tag is missing."
    )


def test_phase14_share_routes_declared_in_workspace_router() -> None:
    # Tests: T-USE-09, Spec §11
    source = read_backend_file("routers", "workspace.py")
    for fragment in ["/share", "share"]:
        if fragment in source:
            break
    else:
        assert False, (
            "routers/workspace.py must define the share endpoints "
            "(POST /workspaces/{id}/share, DELETE, POST /share/rotate)."
        )


def test_phase14_public_view_rate_limit_tier_declared() -> None:
    # Tests: T-USE-09, Spec §12: per-IP limit of 120/min on /public reads.
    source = read_backend_file("middleware", "rate_limit.py")
    assert "public" in source.lower(), (
        "middleware/rate_limit.py must define a public-view rate-limit tier "
        "(120 reads / minute / IP). See Spec §12."
    )


# ---------------------------------------------------------------------------
# T-USE-11: Starter Templates backend
# ---------------------------------------------------------------------------


def test_phase14_templates_router_exists() -> None:
    # Tests: T-USE-11
    assert (BACKEND_ROOT / "routers" / "templates.py").exists(), (
        "not implemented: T-USE-11 — backend/routers/templates.py"
    )


def test_phase14_templates_router_registered_in_main_app() -> None:
    # Tests: T-USE-11
    source = read_backend_file("main.py")
    assert "templates" in source.lower(), (
        "main.py must import and mount the templates router. "
        "GET /templates will not be reachable otherwise."
    )


def test_phase14_templates_router_get_returns_active_only() -> None:
    # Tests: T-USE-11: GET /templates returns active=true templates sorted by
    # sort_order so the dashboard strip is stable across deploys.
    source = read_backend_file("routers", "templates.py")
    assert "active" in source, (
        "routers/templates.py must filter on Template.active == True."
    )
    assert "sort_order" in source, (
        "routers/templates.py must order results by sort_order."
    )


def test_phase14_templates_seed_script_exists() -> None:
    # Tests: T-USE-11, Plan §18.3
    candidates = [
        BACKEND_ROOT / "scripts" / "seed_templates.py",
        BACKEND_ROOT / "seed_templates.py",
    ]
    assert any(c.exists() for c in candidates), (
        "Templates seed script missing. Plan §18.3 specifies "
        "backend/scripts/seed_templates.py."
    )


def test_phase14_templates_seed_script_is_idempotent() -> None:
    # Tests: T-USE-11: seed script must upsert on slug so running it multiple
    # times (across deploys) does not produce duplicate rows.
    candidates = [
        BACKEND_ROOT / "scripts" / "seed_templates.py",
        BACKEND_ROOT / "seed_templates.py",
    ]
    text = ""
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            break
    has_upsert = (
        "on_conflict" in text.lower()
        or "ON CONFLICT" in text
        or "upsert" in text.lower()
        or "merge(" in text.lower()
    )
    assert has_upsert, (
        "seed_templates.py must upsert on slug (e.g. INSERT ... ON CONFLICT "
        "(slug) DO UPDATE) so re-running the seed is safe."
    )


def test_phase14_templates_endpoint_is_unauthenticated() -> None:
    # Tests: T-USE-11, Plan §18.3: GET /templates is served without auth so
    # the unauthenticated landing/marketing page can preview the gallery.
    source = read_backend_file("routers", "templates.py")
    has_auth_dependency = (
        "get_current_user" in source or "require_auth" in source
    )
    assert not has_auth_dependency, (
        "routers/templates.py must not require authentication. "
        "GET /templates is a public read so the marketing site / landing "
        "page can preview the gallery before signup."
    )


def test_phase14_workspaces_post_accepts_template_slug() -> None:
    # Tests: T-USE-11, Spec §11: POST /workspaces accepts an optional
    # template_slug that is recorded on Workspace.template_slug for provenance.
    source = read_backend_file("schemas", "workspace.py")
    assert "template_slug" in source, (
        "schemas/workspace.py (CreateWorkspaceRequest) must accept an optional "
        "template_slug field. See Spec §11."
    )


# ---------------------------------------------------------------------------
# T-USE-13: Harness coverage surfacing
# ---------------------------------------------------------------------------


def test_phase14_workspace_response_includes_coverage_summary() -> None:
    # Tests: T-USE-13, Spec §7: the workspace response must surface the
    # harness coverage figure so the header chip, dashboard card, and public
    # share view can render it without a separate API call.
    source = read_backend_file("schemas", "workspace.py")
    assert "coverage_summary" in source or "harness_coverage" in source, (
        "schemas/workspace.py must expose 'coverage_summary' (or "
        "'harness_coverage') in the workspace response so the UI can render "
        "the coverage chip. See Spec §7."
    )


def test_phase14_workspace_endpoint_computes_coverage_summary_from_eval() -> None:
    # Tests: T-USE-13: the value is derived from the harness stage's latest
    # EvalResult, not stored on the workspace row (no migration needed).
    source = read_backend_file("routers", "workspace.py")
    has_derivation = (
        "coverage_summary" in source
        or "harness_coverage" in source
        or "coverage_percent" in source
    )
    assert has_derivation, (
        "routers/workspace.py must derive coverage_summary from the harness "
        "stage's latest EvalResult when building the workspace response. "
        "No new DB column is required."
    )


# ---------------------------------------------------------------------------
# Existing pre-Phase-14 paths must remain unchanged
# ---------------------------------------------------------------------------


def test_phase14_zip_export_endpoint_is_unchanged() -> None:
    # Tests: Phase 14 must leave the existing ZIP export endpoint intact.
    source = read_backend_file("routers", "workspace.py")
    assert "build_export" in source or "export_service" in source, (
        "The ZIP export endpoint appears to have been removed or renamed. "
        "Phase 14 must leave /workspaces/{id}/export intact."
    )


def test_phase14_github_export_endpoint_is_unchanged() -> None:
    # Tests: Phase 14 must leave the Phase 13 GitHub export endpoint intact.
    source = read_backend_file("routers", "workspace.py")
    assert "export/github" in source or "export_github" in source, (
        "The Phase 13 /workspaces/{id}/export/github endpoint appears to have "
        "been removed or renamed. Phase 14 must leave it intact."
    )


def test_phase14_stage_gap_patch_is_a_paid_operation() -> None:
    # Tests: the /regenerate-gaps harness patch is a paid, repeatable operation.
    # The original free-regen abuse vector was a one-shot free patch gated on
    # stage.gap_patch_used; that gate was deliberately replaced by an up-front
    # credit charge (deferred-coverage reframe), which is the new abuse defence —
    # the patch is gated on the user's balance, not a one-shot flag. The charge
    # must therefore exist in generate_harness_patch.
    source = read_backend_file("services", "pipeline", "stage_manager.py")
    fn_start = source.find("async def generate_harness_patch")
    assert fn_start != -1, "stage_manager.py must define generate_harness_patch."
    fn_body = source[fn_start : fn_start + 4000]
    assert 'credit_service.deduct(' in fn_body and '"regenerate_gaps"' in fn_body, (
        "generate_harness_patch must charge credits (credit_service.deduct with "
        "the 'regenerate_gaps' reason). The free-regen abuse vector is now "
        "prevented by charging, not by a one-shot gap_patch_used gate."
    )


# ---------------------------------------------------------------------------
# Manifest registration
# ---------------------------------------------------------------------------


def test_phase14_manifest_references_v1_3_usefulness_contracts() -> None:
    # Tests: T-USE-01 through T-USE-13: the harness manifest must register this
    # contract file so tasks can reference it by group id.
    import json
    manifest_path = REPO_ROOT / "harness" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = manifest.get("test_groups", [])
    matching = [g for g in groups if g.get("id") == "v1-3-usefulness-contracts"]
    assert matching, (
        "harness/manifest.json must include a 'v1-3-usefulness-contracts' "
        "test group pointing to this file."
    )
