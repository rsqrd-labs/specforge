"""Gunicorn production config (F4 — scalability audit, docs/SCALABILITY_AUDIT.md).

The single source of truth for how the API process is launched, referenced by
``entrypoint.sh`` (the Docker image), ``Procfile`` (Railway/Heroku-style), and
``railway.json`` so the worker count is configured in exactly one place.

**Worker count is env-driven** via ``WEB_CONCURRENCY`` instead of the previous
hardcoded ``--workers 2`` literal, so the API can be scaled to the host's CPU
(``~2*cores+1`` for an I/O-bound async app) without a code change. The default
stays **2** — the prior hardcoded value — so existing deploys keep the same
Postgres connection footprint until PgBouncer (F3) is in front. Raising it
before the pooler lands multiplies ``pool_size+overflow`` per worker against
``max_connections`` (audit §F4: "sequence after F3"); the RUNBOOK §15 pool math
is the gate for bumping it.

**Deliberately no ``max_requests`` / worker recycling.** A recycled worker
severs every in-flight multi-minute SSE generation stream the moment it
restarts, so a routine recycle would kill live generations. The graceful
shutdown window (``WEB_GRACEFUL_TIMEOUT``) is the only restart lever, and it lets
in-flight short requests finish on a real (deploy) restart. Long SSE streams are
bounded by the stream watchdog (``LLM_STREAM_*``), never by gunicorn.
"""

from __future__ import annotations

import os


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Parse a positive int env var, falling back to ``default`` on any junk."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


# Async ASGI app → uvicorn worker class.
worker_class = "uvicorn.workers.UvicornWorker"

# Env-driven worker count. gunicorn natively honours WEB_CONCURRENCY, but we
# resolve it explicitly so the default is the prior 2 (not gunicorn's own
# default of 1, which would halve API capacity) and the value is visible in the
# config rather than implicit.
workers = _env_int("WEB_CONCURRENCY", 2)

# Bound how long a graceful restart waits for in-flight requests before
# force-closing, so a deploy never hangs indefinitely. Defaults to gunicorn's
# own 30s (no behaviour change) and is env-overridable.
graceful_timeout = _env_int("WEB_GRACEFUL_TIMEOUT", 30)

# Honour Railway's injected $PORT; default to 8000 for the Docker image / local.
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
