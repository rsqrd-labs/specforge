from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user
from services.llm.provider_status import (
    all_provider_snapshots,
    check_provider_health,
    provider_ids,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def list_providers() -> dict:
    return {"providers": all_provider_snapshots()}


@router.get("/health")
async def provider_health(_: object = Depends(get_current_user)) -> dict:
    providers = []
    for provider in provider_ids():
        try:
            providers.append(await check_provider_health(provider))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"providers": providers}
