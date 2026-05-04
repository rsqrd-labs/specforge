import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import Response

from config import settings, validate_production_settings
from database import async_engine
from middleware.csrf import CsrfMiddleware
from middleware.rate_limit import RateLimitMiddleware
from routers import auth as auth_router
from routers import credits as credits_router
from routers import providers as providers_router
from routers import stage as stage_router
from routers import workspace as workspace_router
from services.observability import setup_observability
from services.pipeline.recovery_service import run_recovery_loop

HealthStatus = Literal["ok", "degraded"]
DependencyStatus = Literal["ok", "error"]
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
_HSTS_HEADER = "Strict-Transport-Security"
_HSTS_VALUE = "max-age=31536000; includeSubDomains"


def _apply_security_headers(response: Response) -> Response:
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if settings.environment == "production":
        response.headers.setdefault(_HSTS_HEADER, _HSTS_VALUE)
    return response


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_recovery_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def create_app(redis_client=None) -> FastAPI:
    validate_production_settings()
    _production = settings.environment.lower() == "production"
    app = FastAPI(
        title="SpecForge API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if _production else "/docs",
        redoc_url=None if _production else "/redoc",
        openapi_url=None if _production else "/openapi.json",
    )
    setup_observability(app, async_engine)

    app.add_middleware(RateLimitMiddleware, redis_client=redis_client)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers_middleware(
        request: Request,
        call_next,
    ) -> Response:
        response = await call_next(request)
        return _apply_security_headers(response)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return _apply_security_headers(
            JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal Server Error"},
            )
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

        content = {"status": overall_status, "version": "1.0.0"}
        if settings.environment.lower() != "production":
            content.update({"db": db_status, "redis": redis_status})

        return JSONResponse(status_code=status_code, content=content)

    app.include_router(auth_router.router)
    app.include_router(providers_router.router)
    app.include_router(workspace_router.router)
    app.include_router(stage_router.router)
    app.include_router(credits_router.router)

    return app


app = create_app()
