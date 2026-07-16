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
from database import _initialize_redis, async_engine, build_redis_client
from middleware.body_size import BodySizeLimitMiddleware
from middleware.csrf import CsrfMiddleware
from middleware.rate_limit import RateLimitMiddleware
from routers import auth as auth_router
from routers import billing as billing_router
from routers import credits as credits_router
from routers import integrations as integrations_router
from routers import public as public_router
from routers import retention as retention_router
from routers import stage as stage_router
from routers import storyboards as storyboards_router
from routers import templates as templates_router
from routers import workspace as workspace_router
from services import langfuse_service
from services.cpu_offload import shutdown_cpu_executor
from services.observability import run_event_loop_lag_sampler, setup_observability
from services.pipeline.pdf_export_service import shutdown_pdf_executor
from services.pipeline.recovery_service import run_recovery_loop

# setup_observability() owns the guarded sentry_sdk.init call and only enables
# it when settings.sentry_dsn is configured.

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

# Token/cookie-issuing responses that return credentials in the body but carry no
# request Authorization header, so the header-based rule below can't catch them.
_NO_STORE_PATHS = frozenset(
    {"/auth/callback", "/auth/refresh", "/auth/github/callback"}
)


def _apply_security_headers(response: Response) -> Response:
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if settings.environment == "production":
        response.headers.setdefault(_HSTS_HEADER, _HSTS_VALUE)
    return response


def _apply_no_store_if_sensitive(request: Request, response: Response) -> None:
    """Mark authenticated / credential-issuing responses as uncacheable.

    Keyed on the request so it also covers the token endpoints (which return a
    fresh access token / set a refresh cookie but carry no Authorization header).
    ``setdefault`` preserves an endpoint's deliberate Cache-Control (e.g. the
    unauthenticated public-share view's ``max-age=60``), which never enters this
    branch anyway. Blocks both shared-cache storage and the browser bfcache from
    retaining a signed-in user's data on a shared machine.
    """
    authed = request.headers.get("Authorization", "").startswith("Bearer ")
    if authed or request.url.path in _NO_STORE_PATHS:
        response.headers.setdefault("Cache-Control", "no-store")


async def check_database() -> DependencyStatus:
    try:
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return "error"

    return "ok"


async def check_redis(redis: Redis | None = None) -> DependencyStatus:
    _owns = redis is None
    if _owns:
        # Bounded, health-checked client (F8) via the single factory.
        redis = build_redis_client()
    try:
        pong = await redis.ping()
    except Exception:
        return "error"
    finally:
        if _owns:
            await redis.aclose()

    return "ok" if pong else "error"


def create_app(redis_client: Redis | None = None) -> FastAPI:
    validate_production_settings()
    _production = settings.environment.lower() == "production"

    # Lifespan is defined inside create_app so it closes over redis_client.
    # In tests redis_client is injected (FakeRedis); in production we create
    # one shared connection pool and store it on app.state for the health check.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _owns_redis = redis_client is None
        # Bounded, health-checked shared pool (F8) via the single factory.
        redis = redis_client or build_redis_client()
        app.state.redis = redis
        # Register the pool with the module-level helper so services and
        # background tasks can call database.get_shared_redis() without
        # holding a Request reference.  H-1 — T-177.
        _initialize_redis(redis)
        # Langfuse startup health check: verifies connectivity and key validity.
        # Converts silent SDK/server version-skew failures into a loud WARNING
        # so operators detect incompatibility on deploy rather than weeks later.
        # Never fatal — the result is logged only.  M-4 — T-221.
        langfuse_client = langfuse_service.get_langfuse_client()
        if langfuse_client.enabled:
            await langfuse_client.startup_check()
        task = asyncio.create_task(run_recovery_loop())
        # Event-loop lag sampler (F7 — scalability audit P2). One lightweight task
        # per process publishing specforge_event_loop_lag_seconds so the "loop
        # stays responsive under a generation storm" acceptance gate is observable.
        lag_sampler = asyncio.create_task(run_event_loop_lag_sampler())
        yield
        for background in (task, lag_sampler):
            background.cancel()
            try:
                await background
            except asyncio.CancelledError:
                # Expected: we just cancelled the loop during shutdown.
                pass
        # Drain any queued Langfuse events before the consumer thread is
        # dropped by interpreter shutdown. No-op when Langfuse is disabled.
        await langfuse_service.get_langfuse_client().flush()
        # Release the dedicated PDF thread pool.  wait=False lets the
        # lifespan exit immediately; any in-flight render drains naturally
        # at interpreter exit.  HF-4 — T-201.
        shutdown_pdf_executor()
        # Release the dedicated CPU-offload thread pool (F7) the same way.
        shutdown_cpu_executor()
        if _owns_redis:
            await redis.aclose()

    app = FastAPI(
        title="SpecForge API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if _production else "/docs",
        redoc_url=None if _production else "/redoc",
        openapi_url=None if _production else "/openapi.json",
    )
    setup_observability(app, async_engine)

    app.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
    )
    app.add_middleware(RateLimitMiddleware)
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
        _apply_security_headers(response)
        _apply_no_store_if_sensitive(request, response)
        return response

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
    async def health(request: Request) -> JSONResponse:
        db_status = await check_database()
        # Use the shared pool from lifespan when available; fall back to a
        # short-lived connection if lifespan hasn't run (e.g. unit tests).
        redis = getattr(request.app.state, "redis", None)
        redis_status = await check_redis(redis)
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
    app.include_router(workspace_router.router)
    app.include_router(stage_router.router)
    app.include_router(credits_router.router)
    app.include_router(integrations_router.router)
    # T-USE-09: unauthenticated read-only public view at /public/{slug}.
    # The route prefix is in the auth-middleware exemption list (see below).
    app.include_router(public_router.router)
    # T-USE-11: unauthenticated GET /templates — starter templates strip.
    app.include_router(templates_router.router)
    # Phase 18: Stripe Payments billing endpoints.
    app.include_router(billing_router.router)
    # Phase 20: Storyboard owner + public API surface (T-251).
    app.include_router(storyboards_router.router)
    # Issue #43: unauthenticated read-only data-retention policy metadata.
    app.include_router(retention_router.router)

    return app


app = create_app()
