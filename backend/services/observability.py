from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.responses import Response as StarletteResponse

from config import settings

logger = structlog.get_logger(__name__)


def get_structured_logger(name: str) -> Any:
    return structlog.get_logger(name)


REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
LLM_REQUEST_COUNT = Counter(
    "llm_request_total",
    "Total instrumented LLM requests",
    ["provider", "model_tier", "operation", "stage_type", "cache_hit"],
)
LLM_ESTIMATED_COST_USD = Counter(
    "llm_estimated_cost_usd_total",
    "Estimated LLM API cost in USD",
    ["provider", "model_tier", "operation", "stage_type"],
)
LLM_INPUT_TOKENS = Counter(
    "llm_input_tokens_total",
    "LLM input tokens",
    ["provider", "model_tier", "operation", "stage_type", "method"],
)
LLM_OUTPUT_TOKENS = Counter(
    "llm_output_tokens_total",
    "LLM output tokens",
    ["provider", "model_tier", "operation", "stage_type", "method"],
)
LLM_CACHED_INPUT_TOKENS = Counter(
    "llm_cached_input_tokens_total",
    "LLM cached input tokens",
    ["provider", "model_tier", "operation", "stage_type"],
)
LLM_LATENCY_SECONDS = Histogram(
    "llm_latency_seconds",
    "LLM request latency in seconds",
    ["provider", "model_tier", "operation", "stage_type"],
)
LLM_CROSS_PROVIDER_FALLBACK_COUNT = Counter(
    "llm_cross_provider_fallback_total",
    "LLM requests that used an explicit cross-provider fallback route",
    ["provider", "model_tier", "operation", "stage_type"],
)
LLM_PROVIDER_ERROR_COUNT = Counter(
    "llm_provider_errors_total",
    "LLM provider call failures",
    ["provider", "error_type"],
)
LLM_PROVIDER_CONFIGURED = Gauge(
    "llm_provider_configured",
    "Whether a provider API key is configured",
    ["provider"],
)
LLM_PROVIDER_HEALTH = Gauge(
    "llm_provider_health",
    "Provider health state: 0 not configured, 1 unhealthy, 2 degraded, 3 healthy",
    ["provider"],
)

# T-194: SSE, PDF, and eval instrumentation.
# -----------------------------------------
# SSE streaming failure counter — incremented when a stage-generation SSE
# stream terminates with an error before the client receives a completion
# event. This makes streaming failure rate visible in dashboards.
SSE_STREAM_FAILURES = Counter(
    "specforge_sse_stream_failures_total",
    "SSE stage-generation streams that terminated on error",
    ["stage_type"],
)

# PDF export duration histogram — WeasyPrint is CPU-bound and blocks the
# thread-pool executor thread for 0.5–3 s per render. Observing duration
# makes event-loop-blocking outliers (C-4) visible.
PDF_EXPORT_DURATION = Histogram(
    "specforge_pdf_export_duration_seconds",
    "Wall-clock duration of PDF export render calls",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)

# Eval polling failure counter — incremented when the eval poller gives up
# after max retries. Without this counter, silent eval drops are invisible.
EVAL_POLL_FAILURES = Counter(
    "specforge_eval_poll_failures_total",
    "Eval polling attempts that exhausted max retries and silently dropped",
    ["stage_type"],
)

# CSRF replay rejection counter — incremented when verify_csrf_token() detects
# a nonce that has already been claimed in Redis (i.e., the token was replayed).
# Distinguishes active replay attacks from token generation bugs.  HF-6 — T-203.
CSRF_REPLAY_REJECTIONS = Counter(
    "specforge_csrf_replay_rejections_total",
    "CSRF tokens rejected because the nonce was already consumed in Redis",
)

# Billing / Stripe counters (Phase 18) — T-236
# ---------------------------------------------
# These counters power the four Grafana alert rules documented in RUNBOOK §9.
BILLING_CHECKOUT_CREATED = Counter(
    "specforge_billing_checkout_created_total",
    "Stripe Checkout Sessions created via POST /billing/checkout",
)
BILLING_CHECKOUT_COMPLETED = Counter(
    "specforge_billing_checkout_completed_total",
    "checkout.session.completed webhook events received and processed",
)
BILLING_CREDITS_GRANTED = Counter(
    "specforge_billing_credits_granted_total",
    "Total credits granted to users via Stripe purchase",
)
BILLING_CREDITS_EXPIRED = Counter(
    "specforge_billing_credits_expired_total",
    "Credits swept by lazy expiry in _expire_user_packs()",
)
BILLING_CREDITS_CONSUMED = Counter(
    "specforge_billing_credits_consumed_total",
    "Credits drained by FIFO pack drain in _drain_packs()",
)
BILLING_PACK_DISPUTED = Counter(
    "specforge_billing_pack_disputed_total",
    "Credit packs revoked due to Stripe charge disputes",
)
BILLING_WEBHOOK_RECEIVED = Counter(
    "specforge_billing_webhook_received_total",
    "All webhook events received (before idempotency check)",
    ["event_type"],
)
BILLING_WEBHOOK_DUPLICATE = Counter(
    "specforge_billing_webhook_duplicate_total",
    "Webhook events rejected as duplicates by the idempotency guard",
)
BILLING_WEBHOOK_ERROR = Counter(
    "specforge_billing_webhook_error_total",
    "Webhook events that failed during handle_event processing",
    ["error_type"],
)
BILLING_CHECKOUT_RATE_LIMITED = Counter(
    "specforge_billing_checkout_rate_limited_total",
    "POST /billing/checkout requests rejected by the 5/hour rate limit",
)

# GitHub App installation-token resolutions (Phase 21 — T-267). The cache keeps
# minting off the hot path (GitHub rate-limits token minting), so the ratio of
# source="mint" to source="cache" is the cache-hit signal.
GITHUB_TOKEN_MINT_TOTAL = Counter(
    "specforge_github_token_mint_total",
    "GitHub installation token resolutions, by source: 'mint' = a new token "
    "minted from GitHub, 'cache' = served from the Redis token cache.",
    labelnames=["source"],
)

PIPELINE_UPSTREAM_SECTION_SKIPPED = Counter(
    "pipeline_upstream_section_skipped_total",
    "Count of upstream sections skipped during section-aware injection "
    "because the 200K budget was exhausted.  A non-zero value here means "
    "the downstream stage saw a summary instead of the verbatim section, "
    "which is a quality regression for large products.",
    labelnames=["stage", "section"],
)

BILLING_CREDITS_CRITIC_REGEN = Counter(
    "specforge_billing_credits_critic_regen_total",
    "Number of platform-funded stage regenerations triggered by the critic. "
    "Used to attribute the cost of the quality gate against operational P&L. "
    "T-247 (Phase 19).",
    labelnames=["stage"],
)

PIPELINE_VALIDATOR_FAILURES = Counter(
    "pipeline_validator_failures_total",
    "Count of stage generations rejected by the zero-LLM section-presence "
    "validator (a required heading was absent).  Tracks which stage's prompt "
    "most often omits mandatory sections.  T-248 (Phase 19).",
    labelnames=["stage"],
)

# ---------------------------------------------------------------------------
# Storyboard (Phase 20).  Counters and histograms are intentionally labelled
# only with bounded enums so a malicious title/slug/error cannot create
# unbounded Prometheus series.  T-262 owns the complete Storyboard metric set.
# ---------------------------------------------------------------------------
STORYBOARD_GENERATION_STARTED = Counter(
    "specforge_storyboard_generation_started_total",
    "Storyboard generations that acquired a placeholder row and debited credits. "
    "Labelled by action so full generation, full regeneration, and single-section "
    "regeneration can be told apart.  T-254 (Phase 20).",
    labelnames=["action"],
)

STORYBOARD_GENERATION_COMPLETED = Counter(
    "specforge_storyboard_generation_completed_total",
    "Storyboard generations that validated their LLM payload and reached the "
    "'ready' state.  T-254 (Phase 20).",
    labelnames=["action"],
)

STORYBOARD_GENERATION_FAILED = Counter(
    "specforge_storyboard_generation_failed_total",
    "Storyboard generations that failed after debiting and were refunded and "
    "marked 'failed'.  ``error_type`` is a coarse, content-free reason (e.g. "
    "'payload_parse', 'payload_schema', 'provider', 'timeout') — never raw "
    "generated text.  T-254 (Phase 20).",
    labelnames=["action", "error_type"],
)

STORYBOARD_SECTION_REGENERATED = Counter(
    "specforge_storyboard_section_regenerated_total",
    "Single-section Storyboard regenerations that reached the 'ready' state.  "
    "T-254 (Phase 20).",
)

STORYBOARD_GENERATION_DURATION = Histogram(
    "specforge_storyboard_generation_duration_seconds",
    "Wall-clock duration of the Storyboard LLM generation + validation phase "
    "(excludes the credit/placeholder transaction).  T-254 (Phase 20).",
    labelnames=["action"],
)

STORYBOARD_CREDITS_DEDUCTED = Counter(
    "specforge_storyboard_credits_deducted_total",
    "Total credits debited for Storyboard generation, by action.  T-254.",
    labelnames=["action"],
)

STORYBOARD_CREDITS_REFUNDED = Counter(
    "specforge_storyboard_credits_refunded_total",
    "Total credits refunded for failed/recovered Storyboard generations.  "
    "``reason`` is content-free (e.g. 'generation_failed', 'stuck_recovery').  "
    "T-254 (Phase 20).",
    labelnames=["action", "reason"],
)

STORYBOARD_DOWNLOAD = Counter(
    "specforge_storyboard_download_total",
    "Storyboard artifact downloads.  ``kind`` is the artifact (html, pdf, "
    "notes-md, notes-pdf, demo-script, appendix); ``public`` is 'true' for the "
    "unauthenticated share surface and 'false' for owner downloads.  T-255.",
    labelnames=["kind", "public"],
)

STORYBOARD_PUBLIC_VIEW = Counter(
    "specforge_storyboard_public_view_total",
    "Unauthenticated public Storyboard views served successfully. 404s and "
    "permission denials are intentionally not counted.  T-262 (Phase 20).",
)

STORYBOARD_SOURCE_MISSING = Counter(
    "specforge_storyboard_source_missing_total",
    "Expected finalised source sections absent during deterministic Storyboard "
    "source extraction. Labels are bounded source/section enums and never carry "
    "source excerpts.  T-262 (Phase 20).",
    labelnames=["source", "section"],
)

_STORYBOARD_ACTION_LABELS = frozenset({"generate", "regenerate", "regenerate_section"})
_STORYBOARD_ERROR_TYPE_LABELS = frozenset(
    {
        "payload_parse",
        "payload_schema",
        "provider",
        "timeout",
        "row_missing",
        "unexpected",
    }
)
_STORYBOARD_REFUND_REASON_LABELS = frozenset({"generation_failed", "stuck_recovery"})
_STORYBOARD_DOWNLOAD_KIND_LABELS = frozenset(
    {"html", "pdf", "notes-md", "notes-pdf", "demo-script", "appendix"}
)
_STORYBOARD_SOURCE_LABELS = frozenset({"spec", "plan", "harness", "tasks"})
_STORYBOARD_SECTION_LABELS = frozenset(
    {
        "overview",
        "architecture",
        "security-architecture",
        "capacity-model",
        "stride",
        "slo",
        "fmea",
        "coverage",
        "must",
    }
)

_sentry_configured = False
_otel_configured = False
_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "csrf_token",
    "google_api_key",
    "grafana_otlp_token",
    "jwt_private_key",
    "openai_api_key",
    "anthropic_api_key",
    "password",
    "private_key",
    "refresh_token",
    "refreshtoken",
    "secret",
    "set-cookie",
    "set_cookie",
    "stripe_secret_key",
    "stripe_webhook_secret",
    "token",
}
_LOG_RECORD_BUILTINS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"Basic\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"(?i)(refresh[_-]?token\s*[:=]\s*)['\"]?[^'\"\s,;}]+['\"]?"),
    re.compile(r"(?i)(authorization\s*[:=]\s*)['\"]?[^'\"\s,;}]+['\"]?"),
    # Stripe secret keys: sk_live_* (production) and sk_test_* (development)
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9_-]{24,}"),
    # Stripe webhook signing secrets
    re.compile(r"whsec_[A-Za-z0-9/+=]{24,}"),
)


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_data(record.getMessage())
        record.args = ()

        for key, value in list(record.__dict__.items()):
            if key in _LOG_RECORD_BUILTINS:
                continue
            record.__dict__[key] = redact_sensitive_data({key: value})[key]

        if record.exc_text:
            record.exc_text = redact_sensitive_data(record.exc_text)
        return True


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_sensitive_data(item)
        return redacted

    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)

    if isinstance(value, str):
        return _redact_string(value)

    return value


def redact_structlog_event(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    return redact_sensitive_data(event_dict)


def configure_logging() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            redact_structlog_event,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    _install_sensitive_data_filter()


def setup_sentry() -> None:
    global _sentry_configured

    if _sentry_configured or not _is_configured_url(settings.sentry_dsn):
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        before_send=_redact_sentry_event,
    )
    _sentry_configured = True


def setup_opentelemetry(app: FastAPI, engine: AsyncEngine) -> None:
    global _otel_configured

    if _otel_configured or not _is_configured_url(settings.grafana_otlp_endpoint):
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": "specforge-api",
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter_kwargs: dict[str, object] = {"endpoint": settings.grafana_otlp_endpoint}
    if settings.grafana_otlp_token:
        exporter_kwargs["headers"] = {
            "Authorization": f"Bearer {settings.grafana_otlp_token}"
        }
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    _otel_configured = True


def setup_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(
        request: Request,
        call_next: Callable[[Request], object],
    ) -> Response:
        start = time.perf_counter()
        status_code = 500
        route = request.url.path

        try:
            response = await call_next(request)
            status_code = response.status_code
            route = _route_path(request)
            return response
        except Exception:
            route = _route_path(request)
            logger.exception(
                "request_failed",
                method=request.method,
                path=route,
                status_code=status_code,
            )
            raise
        finally:
            duration = time.perf_counter() - start
            REQUEST_COUNT.labels(request.method, route, str(status_code)).inc()
            REQUEST_LATENCY.labels(request.method, route).observe(duration)
            logger.info(
                "request_completed",
                method=request.method,
                path=route,
                status_code=status_code,
                duration_ms=round(duration * 1000, 2),
            )

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> StarletteResponse:
        auth_header = request.headers.get("Authorization") or ""
        token = auth_header.removeprefix("Bearer ").strip()
        if settings.metrics_token:
            if token != settings.metrics_token:
                return StarletteResponse("Unauthorized", status_code=401)
        elif settings.environment.lower() == "production":
            return StarletteResponse("Metrics token required", status_code=503)
        else:
            # When no token is configured, restrict to loopback addresses only
            client_host = (request.client.host if request.client else "") or ""
            if client_host not in ("127.0.0.1", "::1", "localhost"):
                return StarletteResponse("Unauthorized", status_code=401)
        return StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def setup_observability(app: FastAPI, engine: AsyncEngine) -> None:
    configure_logging()
    setup_sentry()
    setup_opentelemetry(app, engine)
    setup_metrics(app)


def record_llm_cost_event(metadata: dict[str, Any]) -> None:
    provider = str(metadata.get("provider") or "unknown")
    model_tier = str(metadata.get("model_tier") or "unknown")
    operation = str(metadata.get("operation") or "unknown")
    stage_type = str(metadata.get("stage_type") or "unknown")
    method = str(metadata.get("usage_estimation_method") or "unknown")
    cache_hit = "true" if bool(metadata.get("cache_hit")) else "false"

    labels = (provider, model_tier, operation, stage_type)
    LLM_REQUEST_COUNT.labels(*labels, cache_hit).inc()
    _inc_counter(
        LLM_ESTIMATED_COST_USD.labels(*labels),
        metadata.get("estimated_cost_usd"),
    )
    _inc_counter(
        LLM_INPUT_TOKENS.labels(*labels, method),
        metadata.get("input_tokens"),
    )
    _inc_counter(
        LLM_OUTPUT_TOKENS.labels(*labels, method),
        metadata.get("output_tokens"),
    )
    _inc_counter(
        LLM_CACHED_INPUT_TOKENS.labels(*labels),
        metadata.get("cached_input_tokens"),
    )
    latency_ms = _as_float(metadata.get("latency_ms"))
    if latency_ms is not None and latency_ms >= 0:
        LLM_LATENCY_SECONDS.labels(*labels).observe(latency_ms / 1000)
    if bool(metadata.get("cross_provider_fallback")):
        LLM_CROSS_PROVIDER_FALLBACK_COUNT.labels(*labels).inc()


def record_llm_provider_failure(provider: str, error_type: str) -> None:
    LLM_PROVIDER_ERROR_COUNT.labels(provider, error_type or "unknown").inc()


def record_llm_provider_configured(provider: str, configured: bool) -> None:
    LLM_PROVIDER_CONFIGURED.labels(provider).set(1 if configured else 0)


def record_llm_provider_health(provider: str, health: str) -> None:
    values = {
        "not_configured": 0,
        "unhealthy": 1,
        "degraded": 2,
        "healthy": 3,
    }
    LLM_PROVIDER_HEALTH.labels(provider).set(values.get(health, 0))


def record_storyboard_generation_started(action: str) -> None:
    STORYBOARD_GENERATION_STARTED.labels(action=_storyboard_action(action)).inc()


def record_storyboard_generation_completed(action: str) -> None:
    STORYBOARD_GENERATION_COMPLETED.labels(action=_storyboard_action(action)).inc()


def record_storyboard_generation_failed(action: str, error_type: str) -> None:
    STORYBOARD_GENERATION_FAILED.labels(
        action=_storyboard_action(action),
        error_type=_storyboard_error_type(error_type),
    ).inc()


def record_storyboard_section_regenerated() -> None:
    STORYBOARD_SECTION_REGENERATED.inc()


def record_storyboard_generation_duration(action: str, duration_seconds: float) -> None:
    if duration_seconds >= 0:
        STORYBOARD_GENERATION_DURATION.labels(
            action=_storyboard_action(action)
        ).observe(duration_seconds)


def record_storyboard_credits_deducted(action: str, amount: int | float) -> None:
    _inc_counter(
        STORYBOARD_CREDITS_DEDUCTED.labels(action=_storyboard_action(action)),
        amount,
    )


def record_storyboard_credits_refunded(
    action: str, reason: str, amount: int | float
) -> None:
    _inc_counter(
        STORYBOARD_CREDITS_REFUNDED.labels(
            action=_storyboard_action(action),
            reason=_storyboard_refund_reason(reason),
        ),
        amount,
    )


def record_storyboard_public_view() -> None:
    STORYBOARD_PUBLIC_VIEW.inc()


def record_storyboard_download(kind: str, *, public: bool) -> str:
    kind_label = _storyboard_download_kind(kind)
    STORYBOARD_DOWNLOAD.labels(
        kind=kind_label,
        public="true" if public else "false",
    ).inc()
    return kind_label


def record_storyboard_source_missing(source: str, section: str) -> None:
    STORYBOARD_SOURCE_MISSING.labels(
        source=_storyboard_source(source),
        section=_storyboard_section(section),
    ).inc()


def _storyboard_action(action: str) -> str:
    value = str(action or "unknown")
    return value if value in _STORYBOARD_ACTION_LABELS else "unknown"


def _storyboard_error_type(error_type: str) -> str:
    value = str(error_type or "unexpected")
    return value if value in _STORYBOARD_ERROR_TYPE_LABELS else "unexpected"


def _storyboard_refund_reason(reason: str) -> str:
    value = str(reason or "generation_failed")
    return value if value in _STORYBOARD_REFUND_REASON_LABELS else "generation_failed"


def _storyboard_download_kind(kind: str) -> str:
    value = str(kind or "unknown")
    if value == "notes":
        value = "notes-md"
    return value if value in _STORYBOARD_DOWNLOAD_KIND_LABELS else "unknown"


def _storyboard_source(source: str) -> str:
    value = str(source or "").lower()
    return value if value in _STORYBOARD_SOURCE_LABELS else "unknown"


def _storyboard_section(section: str) -> str:
    value = str(section or "").split(":", 1)[-1].lower().replace("_", "-")
    return value if value in _STORYBOARD_SECTION_LABELS else "unknown"


def _inc_counter(counter, value: Any) -> None:
    numeric = _as_float(value)
    if numeric is not None and numeric > 0:
        counter.inc(numeric)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_configured_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _install_sensitive_data_filter() -> None:
    root_logger = logging.getLogger()
    if not any(isinstance(f, SensitiveDataFilter) for f in root_logger.filters):
        root_logger.addFilter(SensitiveDataFilter())

    for handler in root_logger.handlers:
        if not any(isinstance(f, SensitiveDataFilter) for f in handler.filters):
            handler.addFilter(SensitiveDataFilter())


def _redact_sentry_event(
    event: dict[str, Any], _hint: dict[str, Any]
) -> dict[str, Any]:
    return redact_sensitive_data(event)


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_replace_secret_match, redacted)
    return redacted


def _replace_secret_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}{_REDACTED}"
    return _REDACTED


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith("_secret")


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else request.url.path
