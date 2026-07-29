"""LLM provider credential guard + operator health probe.

Covers the three surfaces that stop a missing/placeholder provider key from
being discovered by a paying user's first failed generation:

* ``validate_production_settings`` refuses to boot production when EVERY
  provider in ``LLM_PROVIDER_PRIORITY`` is unconfigured.
* ``GET /providers/health`` live-probes the providers behind the admin
  allowlist, with an optional catalog-validated ``?model=``.
* The full-artifact tier policy keeps every provider on its strongest ACTIVE
  model, so a failover never silently downgrades a frontier-priced artifact.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

import config
from routers.providers import (
    _provider_for_model,
    get_provider_health,
    require_admin,
)

_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"


def _valid_production(**overrides: object):
    """Patch ``config.settings`` to an OTHERWISE-VALID production config.

    Every non-provider production check is satisfied, so a raised error can only
    come from the provider-credential guard under test.
    """
    base: dict[str, object] = {
        "environment": "production",
        "allowed_hosts": "app.example.com",
        "metrics_token": "metrics-token",
        "frontend_url": "https://app.thought2build.com",
        "jwt_private_key": _FAKE_PEM,
        "encryption_master_key": "a-real-non-ci-encryption-key",
        "langfuse_secret_key": "",
        "github_app_id": "",
        "github_app_slug": "",
        "lemonsqueezy_api_key": "",
        "lemonsqueezy_store_id": "",
        "lemonsqueezy_variant_id": "",
        "brave_search_flag": False,
        "brave_search_api_key": "",
        # Providers: all real by default; each test narrows this.
        "llm_provider_priority": "anthropic,openai,google",
        "anthropic_api_key": "sk-ant-real",
        "openai_api_key": "sk-real",
        "google_api_key": "AIza-real",
    }
    base.update(overrides)
    return [patch.object(config.settings, key, value) for key, value in base.items()]


def _apply(patches: list) -> None:
    for p in patches:
        p.start()


def _undo(patches: list) -> None:
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# A1 — production startup guard
# ---------------------------------------------------------------------------


def test_all_placeholder_keys_fail_production_startup() -> None:
    """The exact live misconfiguration: three placeholders, boots green today.

    Anthropic is the platform primary, so with every key placeholder-prefixed
    ``resolve_platform_route*`` exhausts its candidates and every generation
    raises LLMRoutingError — while /health still reports ok.
    """
    patches = _valid_production(
        anthropic_api_key="placeholder-anthropic-api-key",
        openai_api_key="placeholder-openai-api-key",
        google_api_key="placeholder-google-api-key",
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError) as excinfo:
            config.validate_production_settings()
    finally:
        _undo(patches)

    message = str(excinfo.value)
    assert "No LLM provider is configured" in message
    # The message must name the priority order and explain the placeholder
    # rule — that prefix IS the mistake being caught.
    assert "anthropic, openai, google" in message
    assert "placeholder-" in message


def test_blank_keys_fail_production_startup() -> None:
    """Blank is unconfigured too, not only the ``placeholder-`` prefix."""
    patches = _valid_production(
        anthropic_api_key="",
        openai_api_key="   ",
        google_api_key="",
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError, match="No LLM provider is configured"):
            config.validate_production_settings()
    finally:
        _undo(patches)


def test_one_real_key_passes_production_startup() -> None:
    """One configured provider is enough — routing skips the rest."""
    patches = _valid_production(
        anthropic_api_key="sk-ant-real",
        openai_api_key="placeholder-openai-api-key",
        google_api_key="placeholder-google-api-key",
    )
    _apply(patches)
    try:
        config.validate_production_settings()
    finally:
        _undo(patches)


def test_openai_only_deploy_passes_production_startup() -> None:
    """The guard is NOT Anthropic-specific.

    An OpenAI-only (or Google-only) deploy is a valid configuration — the
    documented cheap-platform escape hatch is an env-only LLM_PROVIDER_PRIORITY
    reorder — and must keep booting. This test exists to stop an
    Anthropic-specific check from sneaking in later.
    """
    patches = _valid_production(
        llm_provider_priority="openai,anthropic,google",
        anthropic_api_key="placeholder-anthropic-api-key",
        openai_api_key="sk-real",
        google_api_key="placeholder-google-api-key",
    )
    _apply(patches)
    try:
        config.validate_production_settings()
    finally:
        _undo(patches)


def test_guard_only_considers_providers_in_the_priority_list() -> None:
    """A configured provider absent from the priority list cannot rescue it.

    Routing only ever iterates ``platform_provider_priority()``, so a real
    GOOGLE_API_KEY is unreachable when the list names anthropic+openai only.
    The guard must model that, or it would pass a deploy that cannot route.
    """
    patches = _valid_production(
        llm_provider_priority="anthropic,openai",
        anthropic_api_key="placeholder-anthropic-api-key",
        openai_api_key="placeholder-openai-api-key",
        google_api_key="AIza-real",
    )
    _apply(patches)
    try:
        with pytest.raises(RuntimeError, match="No LLM provider is configured"):
            config.validate_production_settings()
    finally:
        _undo(patches)


def test_non_production_never_raises() -> None:
    """Local dev with placeholder keys must keep booting."""
    patches = _valid_production(
        environment="development",
        anthropic_api_key="placeholder-anthropic-api-key",
        openai_api_key="placeholder-openai-api-key",
        google_api_key="placeholder-google-api-key",
    )
    _apply(patches)
    try:
        config.validate_production_settings()
    finally:
        _undo(patches)


def test_ci_style_key_reads_as_configured() -> None:
    """CI sets ANTHROPIC_API_KEY=ci-test-anthropic-key — not placeholder-prefixed.

    Pinned deliberately: if the placeholder predicate ever grew a ``ci-``
    prefix, the guard would start failing every CI production-config test.
    """
    from services.llm.provider_status import is_provider_configured

    patches = _valid_production(anthropic_api_key="ci-test-anthropic-key")
    _apply(patches)
    try:
        assert is_provider_configured("anthropic") is True
        config.validate_production_settings()
    finally:
        _undo(patches)


# ---------------------------------------------------------------------------
# A3 — GET /providers/health
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, email: str) -> None:
        self.email = email


@pytest.mark.asyncio
async def test_require_admin_allows_allowlisted() -> None:
    with patch.object(config.settings, "admin_user_emails", "admin@example.com"):
        user = _FakeUser("Admin@Example.com")
        assert await require_admin(current_user=user) is user


@pytest.mark.asyncio
async def test_require_admin_denies_non_allowlisted() -> None:
    with patch.object(config.settings, "admin_user_emails", "admin@example.com"):
        with pytest.raises(HTTPException) as excinfo:
            await require_admin(current_user=_FakeUser("user@example.com"))
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_empty_allowlist_authorises_no_one() -> None:
    """Closed by default — the probe drives real outbound provider calls."""
    with patch.object(config.settings, "admin_user_emails", ""):
        with pytest.raises(HTTPException) as excinfo:
            await require_admin(current_user=_FakeUser("admin@example.com"))
    assert excinfo.value.status_code == 403


def test_route_is_registered_and_requires_authentication() -> None:
    """401, not 404 — proves the router is actually wired into the app.

    RUNBOOK §5 documented this endpoint for a long time while it did not exist,
    and scripts/production_smoke.py called a sibling path that had been removed.
    This test is what stops that from silently recurring.
    """
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as client:
        response = client.get("/providers/health")

    assert response.status_code == 401


def test_unknown_model_is_rejected_before_any_provider_call() -> None:
    """An arbitrary caller string must never reach a provider adapter."""
    with pytest.raises(HTTPException) as excinfo:
        _provider_for_model("gpt-9-turbo-ultra")
    assert excinfo.value.status_code == 400


def test_known_models_resolve_to_their_owning_provider() -> None:
    assert _provider_for_model("claude-opus-5") == "anthropic"
    assert _provider_for_model("gpt-5.5") == "openai"


@pytest.mark.asyncio
async def test_provider_health_probes_every_provider(monkeypatch) -> None:
    probed: list[tuple[str, str | None]] = []

    async def _fake_check(provider: str, model: str | None = None) -> dict:
        probed.append((provider, model))
        return {
            "id": provider,
            "name": provider.title(),
            "configured": True,
            "selectable": True,
            "health": "healthy",
            "message": "ok",
        }

    monkeypatch.setattr("routers.providers.check_provider_health", _fake_check)
    monkeypatch.setattr(
        config.settings, "llm_provider_priority", "anthropic,openai,google"
    )

    payload = await get_provider_health(model=None, _admin=_FakeUser("a@b.c"))

    assert [p for p, _ in probed] == ["anthropic", "openai", "google"]
    # No explicit model => each provider probes its own judge default.
    assert all(model is None for _, model in probed)
    assert payload["priority"] == ["anthropic", "openai", "google"]
    assert len(payload["providers"]) == 3


@pytest.mark.asyncio
async def test_explicit_model_targets_only_its_owning_provider(monkeypatch) -> None:
    """``?model=claude-opus-5`` probes Anthropic with Opus, others unchanged.

    Key validity and model PERMISSION differ: an Anthropic key can authenticate
    against the Haiku judge model and still be denied claude-opus-5, which is
    what full-artifact generation actually runs.
    """
    probed: dict[str, str | None] = {}

    async def _fake_check(provider: str, model: str | None = None) -> dict:
        probed[provider] = model
        return {
            "id": provider,
            "name": provider.title(),
            "configured": True,
            "selectable": True,
            "health": "healthy",
            "message": "ok",
        }

    monkeypatch.setattr("routers.providers.check_provider_health", _fake_check)

    payload = await get_provider_health(
        model="claude-opus-5",
        _admin=_FakeUser("a@b.c"),
    )

    assert probed["anthropic"] == "claude-opus-5"
    assert probed["openai"] is None
    assert probed["google"] is None

    by_id = {p["id"]: p for p in payload["providers"]}
    assert by_id["anthropic"]["probed_model"] == "claude-opus-5"
    # The others report the judge model they actually probed, not None.
    assert by_id["openai"]["probed_model"] is not None


@pytest.mark.asyncio
async def test_unconfigured_provider_reports_no_probed_model(monkeypatch) -> None:
    """probed_model is None when no probe was made — never a misleading id."""

    async def _fake_check(provider: str, model: str | None = None) -> dict:
        return {
            "id": provider,
            "name": provider.title(),
            "configured": False,
            "selectable": False,
            "health": "not_configured",
            "message": "API key is not configured.",
        }

    monkeypatch.setattr("routers.providers.check_provider_health", _fake_check)

    payload = await get_provider_health(model=None, _admin=_FakeUser("a@b.c"))

    assert all(p["probed_model"] is None for p in payload["providers"])


@pytest.mark.asyncio
async def test_check_provider_health_defaults_to_the_judge_model(monkeypatch) -> None:
    """Passing model=None is byte-identical to the historical behaviour."""
    from services.llm import provider_status
    from services.llm.provider_config import JUDGE_MODELS

    requested: list[str] = []

    class _Adapter:
        async def complete(self, *_args, **_kwargs):
            return "OK"

    def _fake_get_llm(provider: str, model: str, bypass_circuit: bool = False):
        requested.append(model)
        return _Adapter()

    monkeypatch.setattr("services.llm.gateway.get_llm", _fake_get_llm)
    monkeypatch.setattr(
        provider_status, "is_provider_configured", lambda _provider: True
    )

    await provider_status.check_provider_health("anthropic")
    await provider_status.check_provider_health("anthropic", model="claude-opus-5")

    assert requested == [JUDGE_MODELS["anthropic"], "claude-opus-5"]


# ---------------------------------------------------------------------------
# A5 — failover never downgrades the artifact tier
# ---------------------------------------------------------------------------


def test_every_provider_runs_frontier_tier_for_full_artifacts() -> None:
    """The fallback providers are reached exactly when quality matters most.

    OpenAI/Google are routed to only when Anthropic is unconfigured or its
    circuit is open — i.e. when a user charged for a frontier artifact is about
    to receive one from elsewhere. Leaving OpenAI on its cheap ``mini`` primary
    silently shipped a far weaker artifact at the same price.
    """
    from services.pipeline.stage_manager import (
        _CORE_ARTIFACT_TIER_POLICY,
        _DEMO_DAY_ARTIFACT_TIER_POLICY,
    )

    for policy in (_CORE_ARTIFACT_TIER_POLICY, _DEMO_DAY_ARTIFACT_TIER_POLICY):
        for provider in ("anthropic", "openai", "google"):
            assert policy[provider] == ("strong", "mid"), provider


def test_demo_day_is_never_weaker_than_standard() -> None:
    """The mode-parity invariant, asserted structurally rather than by table.

    Demo Day artifacts are guarantee-bearing, so promoting a provider in the
    standard table without promoting it in the Demo Day table would invert this.
    """
    from services.llm.model_catalog import _CORE_TIER_RANK
    from services.pipeline.stage_manager import (
        _CORE_ARTIFACT_TIER_POLICY,
        _DEMO_DAY_ARTIFACT_TIER_POLICY,
    )

    for provider, (standard_tier, _) in _CORE_ARTIFACT_TIER_POLICY.items():
        demo_tier, _ = _DEMO_DAY_ARTIFACT_TIER_POLICY[provider]
        assert _CORE_TIER_RANK[demo_tier] >= _CORE_TIER_RANK[standard_tier], provider


@pytest.mark.parametrize(
    ("priority", "expected_provider", "expected_model", "expected_tier"),
    [
        ("anthropic,openai,google", "anthropic", "claude-opus-5", "strong"),
        ("openai,anthropic,google", "openai", "gpt-5.5", "strong"),
        # Google's ``strong`` slot has no ACTIVE model (Pro Preview is
        # status="preview" and _model_for_operation filters non-active), so it
        # falls through to the mid slot — the same model it ran before. The
        # entry is a self-documenting no-op that auto-upgrades if Pro ships.
        ("google,anthropic,openai", "google", "gemini-3.6-flash", "mid"),
    ],
)
def test_artifact_routing_resolves_per_provider(
    monkeypatch,
    priority: str,
    expected_provider: str,
    expected_model: str,
    expected_tier: str,
) -> None:
    from services.llm.routing import resolve_platform_route_by_provider
    from services.pipeline.stage_manager import _CORE_ARTIFACT_TIER_POLICY

    monkeypatch.setattr(config.settings, "llm_provider_priority", priority)
    monkeypatch.setattr(
        "services.llm.provider_status.is_provider_configured", lambda _p: True
    )
    monkeypatch.setattr("services.llm.provider_status.can_route", lambda _p: True)

    route = resolve_platform_route_by_provider(
        operation="spec.generate",
        tier_policy=_CORE_ARTIFACT_TIER_POLICY,
        latency_class="interactive",
    )

    assert route.provider == expected_provider
    assert route.model == expected_model
    assert route.model_tier == expected_tier


def test_unconfigured_primary_falls_through_to_the_next_provider(
    monkeypatch,
) -> None:
    """The failover the user asked for: no Anthropic key ⇒ OpenAI wins.

    This is the ``placeholder-``/blank-key path, not the circuit-breaker path —
    no outage required, and no code beyond the tier tables is involved.
    """
    from services.llm.routing import resolve_platform_route_by_provider
    from services.pipeline.stage_manager import _CORE_ARTIFACT_TIER_POLICY

    monkeypatch.setattr(
        config.settings, "llm_provider_priority", "anthropic,openai,google"
    )
    monkeypatch.setattr(
        "services.llm.provider_status.is_provider_configured",
        lambda provider: provider != "anthropic",
    )
    monkeypatch.setattr("services.llm.provider_status.can_route", lambda _p: True)

    route = resolve_platform_route_by_provider(
        operation="spec.generate",
        tier_policy=_CORE_ARTIFACT_TIER_POLICY,
        latency_class="interactive",
    )

    assert route.provider == "openai"
    assert route.model == "gpt-5.5"


def test_open_circuit_falls_through_to_the_next_provider(monkeypatch) -> None:
    """The 'Claude is not responding' path: a tripped circuit sheds Anthropic.

    ``can_route`` is False once the breaker opens (3 failures / 600s, per
    process), and the SAME resolver skips it — so the next generation lands on
    the next configured provider with no in-generation rescue machinery.
    """
    from services.llm.routing import resolve_platform_route_by_provider
    from services.pipeline.stage_manager import _CORE_ARTIFACT_TIER_POLICY

    monkeypatch.setattr(
        config.settings, "llm_provider_priority", "anthropic,openai,google"
    )
    monkeypatch.setattr(
        "services.llm.provider_status.is_provider_configured", lambda _p: True
    )
    monkeypatch.setattr(
        "services.llm.provider_status.can_route",
        lambda provider: provider != "anthropic",
    )

    route = resolve_platform_route_by_provider(
        operation="spec.generate",
        tier_policy=_CORE_ARTIFACT_TIER_POLICY,
        latency_class="interactive",
    )

    assert route.provider == "openai"
    assert route.model == "gpt-5.5"


def test_no_configured_provider_raises_routing_error(monkeypatch) -> None:
    """What production does today — the failure A1 now catches at startup."""
    from services.llm.routing import LLMRoutingError, resolve_platform_route_by_provider
    from services.pipeline.stage_manager import _CORE_ARTIFACT_TIER_POLICY

    monkeypatch.setattr(
        config.settings, "llm_provider_priority", "anthropic,openai,google"
    )
    monkeypatch.setattr(
        "services.llm.provider_status.is_provider_configured", lambda _p: False
    )
    monkeypatch.setattr("services.llm.provider_status.can_route", lambda _p: True)

    with pytest.raises(LLMRoutingError):
        resolve_platform_route_by_provider(
            operation="spec.generate",
            tier_policy=_CORE_ARTIFACT_TIER_POLICY,
            latency_class="interactive",
        )
