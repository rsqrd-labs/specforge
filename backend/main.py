from typing import Literal

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from config import settings
from database import async_engine
from middleware.rate_limit import RateLimitMiddleware
from routers import auth as auth_router
from routers import credits as credits_router
from routers import providers as providers_router
from routers import stage as stage_router
from routers import workspace as workspace_router
from services.observability import setup_observability

HealthStatus = Literal["ok", "degraded"]
DependencyStatus = Literal["ok", "error"]


async def check_database() -> DependencyStatus:
    try:
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return "error"

    return "ok"


async def check_redis() -> DependencyStatus:
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )

    try:
        pong = await redis.ping()
    except Exception:
        return "error"
    finally:
        await redis.aclose()

    return "ok" if pong else "error"


def create_app(redis_client=None) -> FastAPI:
    app = FastAPI(title="SpecForge API", version="1.0.0")
    setup_observability(app, async_engine)

    app.add_middleware(RateLimitMiddleware, redis_client=redis_client)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        db_status = await check_database()
        redis_status = await check_redis()
        overall_status: HealthStatus = (
            "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
        )
        status_code = (
            status.HTTP_200_OK
            if overall_status == "ok"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )

        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall_status,
                "db": db_status,
                "redis": redis_status,
                "version": "1.0.0",
            },
        )

    app.include_router(auth_router.router)
    app.include_router(providers_router.router)
    app.include_router(workspace_router.router)
    app.include_router(stage_router.router)
    app.include_router(credits_router.router)

    return app


app = create_app()
