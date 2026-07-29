"""Operator-facing LLM provider health probe.

``GET /providers/health`` performs a live 1-token completion against every
configured provider and returns the resulting snapshot. It exists because the
platform's generation path depends on a provider credential that nothing else
validates: ``/health`` reports only db/redis, and a blank or ``placeholder-``
prefixed key boots green and surfaces only when a paying user's first
generation fails to route.

Two deliberate design points:

* **Admin-gated.** Each call makes a real outbound request per configured
  provider, so it is a (small) cost and load amplifier. It is scoped to the
  ``ADMIN_USER_EMAILS`` allowlist rather than to any logged-in user.
* **A successful probe closes an open circuit.** ``check_provider_health`` runs
  with ``bypass_circuit=True`` and funnels through
  ``record_provider_success``/``record_provider_failure``, so hitting this route
  doubles as the manual circuit reset documented in RUNBOOK §1 — no shell
  needed. Note the circuit is per-process, so one call resets one worker.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from config import settings
from middleware.auth import get_current_user
from models import User
from services.llm.model_catalog import MODEL_CATALOG
from services.llm.provider_config import JUDGE_MODELS
from services.llm.provider_status import check_provider_health, provider_ids
from services.llm.routing import platform_provider_priority

router = APIRouter(prefix="/providers", tags=["providers"])


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Authorise the admin allowlist, else 403.

    Mirrors ``routers.billing.require_admin``: ``settings.admin_emails`` is the
    only authorization surface (the ``User`` model has no role column) and an
    empty allowlist authorises no one.
    """
    if current_user.email.lower() not in settings.admin_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin authorization required",
        )
    return current_user


def _provider_for_model(model_id: str) -> str:
    """Return the provider that owns ``model_id``, or 400 if unknown.

    Validating against the catalog is what keeps an arbitrary caller-supplied
    string from being handed to a provider adapter.
    """
    for entry in MODEL_CATALOG:
        if entry.model_id == model_id:
            return entry.provider
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown model id: {model_id!r}",
    )


@router.get("/health")
async def get_provider_health(
    model: str | None = Query(
        default=None,
        description=(
            "Optional catalog model id to probe instead of the provider's "
            "judge model. Applies only to the provider that owns it; the "
            "others keep their default probe."
        ),
    ),
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """Live-probe every provider and return its snapshot.

    ``?model=`` targets a specific model because key validity and model
    *permission* are different things — an Anthropic key can authenticate
    against the Haiku judge model and still be denied ``claude-opus-5``, which
    is the model this deployment's full-artifact generation depends on.
    """
    target_provider = _provider_for_model(model) if model else None

    providers: list[dict[str, object]] = []
    for provider in provider_ids():
        probe_model = model if provider == target_provider else None
        snapshot = await check_provider_health(provider, model=probe_model)
        # probed_model is attached here rather than inside provider_snapshot()
        # so the snapshot shape used by other callers stays untouched. It is
        # None when the provider is unconfigured — no probe was made.
        snapshot["probed_model"] = (
            (probe_model or JUDGE_MODELS[provider]) if snapshot["configured"] else None
        )
        providers.append(snapshot)

    # The server-owned precedence, so a caller never has to guess which entry
    # of ``providers`` will actually win a route. Generation resolves the first
    # provider in this order that is both configured and circuit-closed.
    return {"providers": providers, "priority": list(platform_provider_priority())}
