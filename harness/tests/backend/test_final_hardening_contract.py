from __future__ import annotations

from harness_utils import read_backend_file


def test_production_requires_metrics_token_and_https_frontend() -> None:
    config_source = read_backend_file("config.py")
    main_source = read_backend_file("main.py")

    assert "validate_production_settings()" in main_source
    assert "METRICS_TOKEN must be set in production" in config_source
    assert "FRONTEND_URL must use HTTPS in production" in config_source


def test_gemini_adapter_uses_supported_google_genai_sdk() -> None:
    pyproject = read_backend_file("pyproject.toml")
    adapter_source = read_backend_file("services", "llm", "google_adapter.py")

    assert "google-genai" in pyproject
    assert "google-generativeai" not in pyproject
    assert "google.generativeai" not in adapter_source
    assert "from google import genai" in adapter_source


def test_workspace_creation_has_active_quota() -> None:
    config_source = read_backend_file("config.py")
    service_source = read_backend_file("services", "workspace_service.py")

    assert "max_active_workspaces_per_user" in config_source
    assert "_active_workspace_count" in service_source
    assert "workspace_quota_exceeded" in service_source


def test_refine_prompt_wraps_current_document_as_untrusted_content() -> None:
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert "SECURITY_AND_PRIVACY_RULES" in source
    assert "wrap_untrusted_content('current_document', content)" in source
    # Refinement inputs are intentionally fenced raw after injection scanning.
    # Sanitizing them would corrupt code-bearing Markdown and selection offsets.
    assert "wrap_untrusted_content('selected_text', request.selected_text)" in source
    assert "wrap_untrusted_content('instruction', request.instruction)" in source
    assert "scan_result = await scan_async(text)" in source
    assert "validation = await validate_async(replacement)" in source
