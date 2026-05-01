from fastapi import APIRouter

from services.llm.provider_config import JUDGE_MODELS, PROVIDER_DISPLAY, PROVIDER_MODELS

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def list_providers() -> dict:
    providers = [
        {
            "id": provider_id,
            "name": PROVIDER_DISPLAY[provider_id],
            "models": models,
            "judge_model": JUDGE_MODELS[provider_id],
        }
        for provider_id, models in PROVIDER_MODELS.items()
    ]
    return {"providers": providers}
