# Issue #29 backend review manifest

Audit SHA: `f1941cc0ad92c5dfb0949b97779b0c02b3bbb223`

Status vocabulary: `reviewed/no finding` means the file was included in automated evidence and its subsystem boundary pass; `reviewed/finding` links a confirmed finding. Coverage is review evidence, not necessarily line coverage.

| File | Workstream | Status | Finding | Evidence |
|---|---|---|---|---|
| `.github/workflows/.gitkeep` | Operations/workers | reviewed/no finding | — | Runtime/CI review |
| `.github/workflows/ci.yml` | Operations/workers | reviewed/finding | BE29-003 | Runtime/CI review |
| `.github/workflows/production-smoke.yml` | Operations/workers | reviewed/no finding | — | Runtime/CI review |
| `.github/workflows/prompt-eval.yml` | Operations/workers | reviewed/no finding | — | Runtime/CI review |
| `backend/.dockerignore` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/.env.example` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/.python-version` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/Dockerfile` | Operations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/Procfile` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/alembic.ini` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/config.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/config/.gitkeep` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/database.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/entrypoint.sh` | Operations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/gunicorn.conf.py` | Operations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/main.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/.gitkeep` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/__init__.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/auth.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/body_size.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/credit_check.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/csrf.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/middleware/rate_limit.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/README` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/env.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/script.py.mako` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0001_initial_schema.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0002_add_indexes.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0003_credit_ledger_unique_refund.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0004_stage_deduction_ledger_id.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0005_fix_credit_refund_partial_index.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0006_add_user_credit_balance.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0007_github_integration.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0008_stage_gap_patch_used.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0009_workspace_v1_3_fields.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0010_templates.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0011_workspace_public_shared_at.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0012_eval_results_composite_index.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0013_stripe_payments.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0014_workspace_disable_critic.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0015_storyboards.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0016_github_living_integration.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0017_increments.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0018_billing_neutral_tables.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0019_stage_quality_gate_state.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0020_llm_cost_events.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0021_llm_batch_jobs.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0022_github_installation_pr_check_mode.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0023_workspace_brave_research_enabled.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0024_stage_version_research.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0025_stage_quality_gate_advisory_status.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0026_raise_problem_statement_cap.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0027_increment_deduction_ledger_id.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0028_normalize_legacy_push_status.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0029_workspace_demo_day_mode.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0030_workspace_construction_verdict.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0031_stages_in_progress_partial_index.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0032_eval_results_created_at_index.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0033_workspace_trash.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0034_razorpay_provider.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0035_workspace_agent_instruction_targets.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0036_github_inbound_sync_marker.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0037_eval_structural_validator_version.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0038_stage_generation_started_at.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0039_stage_version_monotonicity.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0040_stage_generation_runs.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/migrations/versions/0041_generation_run_lookup_index.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/.gitkeep` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/__init__.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/billing_admin_correction.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/billing_checkout_attempt.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/billing_credit_debt.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/billing_credit_pack.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/billing_reconciliation_cursor.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/billing_webhook_event.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/credit_ledger.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/eval_result.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/github_installation.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/github_webhook_event.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/increment.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/integration_push.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/integration_push_task.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/llm_batch_job.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/llm_cost_event.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/stage.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/stage_generation.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/stage_version.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/storyboard.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/stripe_credit_pack.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/stripe_webhook_event.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/template.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/user.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/user_integration.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/models/workspace.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/.gitkeep` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/__init__.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/base.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/demo_day.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/harness.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/harness_patch.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/plan.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/spec.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/spec_clarification.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/storyboard.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/prompts/tasks.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/pyproject.toml` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/railway.json` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/requirements-dev.txt` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/requirements.txt` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/.gitkeep` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/__init__.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/auth.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/billing.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/credits.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/integrations.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/public.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/retention.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/stage.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/storyboards.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/templates.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/routers/workspace.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/.gitkeep` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/__init__.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/auth.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/billing.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/common.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/credits.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/github.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/increment.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/integration.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/retention.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/stage.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/storyboard.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/template.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/schemas/workspace.py` | API/contracts/tests | reviewed/no finding | — | Static + subsystem review |
| `backend/scripts/__init__.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/scripts/compare_brave_grounding.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/scripts/reset_test_database.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/scripts/rotate_encryption_key.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/scripts/seed_templates.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/auth_service.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/billing_worker.py` | Operations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/coverage_utils.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/cpu_offload.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/credit_service.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/services/evals/.gitkeep` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/evals/__init__.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/evals/eval_batch.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/evals/online_eval.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/evals/runner.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/__init__.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/agents_md_builder.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_api_client.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_app_auth.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_auth_service.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_governor.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_install_service.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_projects.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/github_reconcile.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/pr_evaluator.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/pr_export_builder.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/push_repo.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/task_issue_reconcile.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/task_parser.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/integrations/task_ref_migration.py` | Data/financial | reviewed/no finding | — | Static + subsystem review |
| `backend/services/langfuse_service.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/lemonsqueezy_service.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/.gitkeep` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/__init__.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/anthropic_adapter.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/base.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/batch_executor.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/completion.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/complexity_classifier.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/cost_cache.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/cost_ledger.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/cost_registry.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/gateway.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/generation_estimates.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/google_adapter.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/instrumented_adapter.py` | LLM pipeline | reviewed/finding | BE29-001 | Static + subsystem review |
| `backend/services/llm/model_catalog.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/openai_adapter.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/output_budget.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/prompt_cache.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/provider_config.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/provider_status.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/quality_gates.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/routing.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/tier_policy.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/llm/usage.py` | LLM pipeline | reviewed/finding | BE29-002 | Static + subsystem review |
| `backend/services/maintenance.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/observability.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/observability/.gitkeep` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/.gitkeep` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/__init__.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/admission.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/agent_manual_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/artifact_validator.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/background_tasks.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/critic.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/demo_day_plan_linter.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/demo_day_verdict.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/diff_engine.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/export_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/generation_runs.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/github_export_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/increment_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/pdf_export_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/problem_compressor.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/prompt_builder.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/recovery_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/spec_clarifier.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/stage_manager.py` | LLM pipeline | reviewed/finding | BE29-001 | Static + subsystem review |
| `backend/services/pipeline/stage_summary_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/storyboard_public_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/storyboard_quality.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/storyboard_renderer.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/storyboard_service.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/storyboard_source.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/tech_safety.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/pipeline/tech_safety_policy.json` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/queue.py` | Integrations/workers | reviewed/no finding | — | Static + subsystem review |
| `backend/services/razorpay_service.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/research/__init__.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/research/brave_client.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/research/research_service.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/retention.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/.gitkeep` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/__init__.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/csrf.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/downstream_command_guard.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/key_vault.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/output_validator.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/problem_statement_gate.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/prompt_guard.py` | LLM pipeline | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/sanitizer.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/security/token_service.py` | Platform/security | reviewed/no finding | — | Static + subsystem review |
| `backend/services/sharing/__init__.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/sharing/public_share_service.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/text_compaction.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/services/workspace_service.py` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/templates/_brand_squirrel.svg.j2` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/templates/export.html.j2` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/templates/storyboard-notes.html.j2` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/templates/storyboard.html.j2` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/tests/.gitkeep` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/artifact_fixtures.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/conftest.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_admission.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_agent_issues.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_artifact_validator.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_auth_middleware.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_auth_router.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_auth_service.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_background_tasks.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_admin_correction.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_credit_service.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_migration_0018.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_migration_0034.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_models_schemas.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_order_created.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_order_refunded.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_queue.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_reconcile.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_router.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_router_razorpay.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_webhook.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_worker.py` | Operations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_billing_worker_razorpay.py` | Operations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_brave_client.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_brave_config.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_circuit_breaker.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_compare_brave_grounding.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_complexity_classifier.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_concurrency.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_coverage_hardening.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_coverage_utils.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_cpu_offload.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_credit_check.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_credit_cycle_integration.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_credit_service.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_credits_router.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_critic.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_csrf.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase0.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase1.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase2.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase3.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase3_wiring.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase5_corpus.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_demo_day_phase5_credits.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_diff_engine.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_downstream_command_guard.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_eval_batch.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_eval_score_sample_config.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_export_push_worker.py` | Operations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_export_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_finalise_integration.py` | Integrations/workers | reviewed/finding | BE29-003 | Pytest + review |
| `backend/tests/test_frontier_adapter_policy.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_generation_estimates.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_api_client.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_api_client_app.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_app_auth.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_app_config.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_drift_backfill.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_export_service.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_governor.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_install.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_integration.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_observability.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_pr_export.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_projects.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_reconcile.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_github_schemas.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_increment_generation.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_increment_models.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_increment_sync.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_instrumented_adapter.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_key_vault.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_langfuse_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_lemonsqueezy_config.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_lemonsqueezy_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_batch_executor.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_cost_cache.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_cost_ledger.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_cost_registry.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_gateway.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_output_budget.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_prompt_cache.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_route_eval.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_routing.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_llm_usage.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_maintenance.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_marketing_site_url_config.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_migration_0031_partial_index.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_migration_retention.py` | Data/financial | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_model_catalog.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_observability.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_online_eval.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_online_eval_task_fields.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_openai_adapter.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_openai_prompt_cache_policy.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_output_budget.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_pdf_executor.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_pdf_export_sanitize.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_pdf_export_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_phase24_behavioral.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_phase25_money_math.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_pr_evaluator.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_problem_compression_golden.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_problem_compressor.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_problem_statement_gate.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_problem_statement_instrumentation.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_prompt_builder.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_prompt_fragment_contracts.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_prompts.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_prompts_base.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_provider_rate_limit.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_public_share_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_push_repo.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_queue.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_rate_limit.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_razorpay_config.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_razorpay_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_recovery_heartbeat.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_recovery_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_research_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_research_wiring.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_retention.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_sanitizer.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_scalability_p1.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_security.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_security_headers.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_seed_templates.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_spec_clarification.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_spec_clarifier.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_stage_manager.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_stage_router.py` | API/contracts/tests | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_stage_summary_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_grounding.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_model.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_observability.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_phase1.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_prompt.py` | LLM pipeline | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_public_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_quality.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_renderer.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_router.py` | API/contracts/tests | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_router_integration.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_security.py` | Platform/security | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_service.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_source.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_storyboard_source_integration.py` | Integrations/workers | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_stream_watchdog.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_stripe_decommission.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_sync_endpoints.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_task_parser.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_task_ref.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_task_validation.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_tech_safety.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_tier_policy.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_webhook_ingest.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/tests/test_workspace.py` | Backend/core | reviewed/no finding | — | Pytest + review |
| `backend/uv.lock` | Backend/core | reviewed/no finding | — | Static + subsystem review |
| `backend/worker.py` | Operations/workers | reviewed/no finding | — | Static + subsystem review |
| `docker-compose.yml` | Operations/workers | reviewed/no finding | — | Runtime/CI review |
| `frontend/src/__tests__/AuthCallback.branded.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/__tests__/AuthCallback.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/__tests__/Billing.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/__tests__/WorkspaceFlow.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/__tests__/sseService.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/components/dashboard/CreateWorkspaceModal.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/components/dashboard/CreateWorkspaceModal.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/components/dashboard/DeleteWorkspaceModal.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/components/dashboard/DeleteWorkspaceModal.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/components/dashboard/WorkspaceCard.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/components/workspace/WorkspaceActionLockPanels.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/config/starterWorkspaces.ts` | Platform/security | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/hooks/useStream.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/hooks/useStream.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/AuthCallback.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/Billing.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/PublicWorkspaceView.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/PublicWorkspaceView.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/Workspace.reconnect.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/Workspace.remediation.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/Workspace.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/Workspace.version-history.test.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/WorkspaceGitHub.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/pages/WorkspaceGitHub.tsx` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.config.test.ts` | Platform/security | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.csrf.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.errors.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.github.test.ts` | Integrations/workers | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.refresh.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.storyboard.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/api.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/services/sseService.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/.gitkeep` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/generationEstimatesStore.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/generationEstimatesStore.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/stageStore.test.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/stageStore.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/userStore.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/store/workspaceStore.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/.gitkeep` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/billing.ts` | Data/financial | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/github.ts` | Integrations/workers | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/publicShare.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/retention.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/stage.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/storyboard.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/template.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/user.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `frontend/src/types/workspace.ts` | API/contracts/tests | reviewed/no finding | — | Contract-consumer review |
| `harness/schemas/api-error.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/eval-result.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/harness-file.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/integration-push.schema.json` | Integrations/workers | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/llm-cost-event.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/public-workspace.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/stage-version.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/stage.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/storyboard-payload.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/storyboard-public-response.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/template.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/user.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/schemas/workspace.schema.json` | API/contracts/tests | reviewed/no finding | — | Harness execution + review |
| `harness/tests/backend/conftest.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/harness_utils.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_app_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_brave_research_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_credit_service_contract.py` | Data/financial | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_export_and_eval_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_final_hardening_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_judgment_golden.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_langfuse_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_langfuse_live_traffic_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_models_contract.py` | Data/financial | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase12_llm_cost_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase13_github_integration_contract.py` | Integrations/workers | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase14_v13_usefulness_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase15_enterprise_hardening_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase16_final_remediation_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase17_final_hardening_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase21_stripe_payments_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase22_prompt_pipeline_contract.py` | LLM pipeline | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase23_storyboard_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase24_github_living_contract.py` | Integrations/workers | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase25_lemonsqueezy_billing_contract.py` | Data/financial | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase4_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase5_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_phase6_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_production_readiness_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_project_structure.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_prompt_eval_anonymization.py` | LLM pipeline | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_prompt_eval_coverage_graders.py` | LLM pipeline | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_prompt_eval_denylist_freshness.py` | LLM pipeline | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_second_pass_security_contract.py` | Platform/security | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_security_audit_contract.py` | Platform/security | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_security_contract.py` | Platform/security | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
| `harness/tests/backend/test_stage_manager_contract.py` | API/contracts/tests | reviewed/finding | BE29-004 (suite-level) | Harness execution + review |
