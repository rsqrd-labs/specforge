"""Thin, never-raises HTTP adapter over the Brave LLM Context API (issue #12).

Contract (verified 2026-06-16 against api-dashboard.search.brave.com):

    GET https://api.search.brave.com/res/v1/llm/context
    auth:   X-Subscription-Token: <key>
    query:  q (1–400 chars), country, search_lang, maximum_number_of_tokens,
            freshness, …
    body:   { "grounding": { "generic": [ {url, title, snippets[]} ] },
              "sources":   { "<url>": {title, hostname, age} } }

Design invariants (the spine of the integration — see plan §1, §6):

* **Never raises.** Every failure (timeout, connect error, 429/5xx after one
  retry, non-2xx, malformed body, unexpected parse error) returns ``None``. The
  caller can therefore always fall open to "no research" with no try/except.
* **Empty grounding is success, not failure.** A 2xx response whose grounding
  list is empty returns a valid (empty) ``BraveResult`` with outcome ``empty`` —
  distinct from ``None``.
* **Untrusted output.** ``snippets`` are arbitrary third-party web text. This
  adapter only parses and shape-validates them; sanitisation / prompt-injection
  scanning happens in the Phase 2 research service before anything reaches a
  prompt. Nothing here is treated as instructions.
* **The API key is never logged**, and raw snippets are never logged.

The adapter is wired to nothing in Phase 1; it is exercised only by its tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx

from config import settings
from services.observability import BRAVE_REQUEST_LATENCY, BRAVE_REQUESTS_TOTAL

logger = logging.getLogger(__name__)

BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"

# Contract: q is 1–400 chars.
_MAX_QUERY_CHARS = 400
# Initial request + exactly one retry on a retryable status (429 / 5xx).
_MAX_ATTEMPTS = 2
# Backoff is intentionally tiny: Brave's rate-limit window is 1s and Phase 3
# wraps this whole fetch in a ~4s budget, so a long sleep would eat the budget.
_DEFAULT_BACKOFF_SECONDS = 0.5
_MAX_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class BraveSnippet:
    """One grounded result: a source URL/title and its extracted text snippets."""

    url: str
    title: str
    snippets: tuple[str, ...]


@dataclass(frozen=True)
class BraveSource:
    """Provenance for a grounded URL (from the response ``sources`` map)."""

    url: str
    title: str
    hostname: str
    age: str | None


@dataclass(frozen=True)
class BraveResult:
    """Parsed, shape-validated Brave response. Content is still untrusted."""

    query: str
    results: tuple[BraveSnippet, ...]
    sources: tuple[BraveSource, ...]

    @property
    def is_empty(self) -> bool:
        return not self.results


async def fetch(
    query: str,
    *,
    max_tokens: int | None = None,
    freshness: str | None = None,
    timeout: float | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> BraveResult | None:
    """Fetch grounding context for ``query``. Never raises; ``None`` on failure.

    Returns a ``BraveResult`` (possibly empty) on a 2xx response, ``None`` on any
    failure. ``max_tokens`` / ``freshness`` / ``timeout`` default to the
    corresponding config values. Pass ``http_client`` to reuse/inject a client
    (the test seam for ``httpx.MockTransport``); otherwise a client is created
    and closed per call, mirroring the tech_safety advisory-lookup idiom.
    """
    api_key = settings.brave_search_api_key
    if not api_key:
        # Defensive: callers gate on ``brave_search_enabled``, but never issue a
        # keyless request that would just 401.
        return None

    normalized_query = query.strip()[:_MAX_QUERY_CHARS]
    if not normalized_query:
        return None

    params: dict[str, str | int] = {
        "q": normalized_query,
        "country": "us",
        "search_lang": "en",
        "maximum_number_of_tokens": (
            max_tokens if max_tokens is not None else settings.brave_max_tokens
        ),
    }
    effective_freshness = (
        freshness if freshness is not None else settings.brave_freshness
    )
    if effective_freshness:
        params["freshness"] = effective_freshness

    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }

    # NOTE (Phase 3 author): this timeout is *per HTTP request*, not the total
    # wall-clock of fetch(). A retry adds backoff + a second request on top, so
    # worst case ≈ timeout + backoff + timeout. To honour the plan's "+Ns worst
    # case" ceiling, wrap the whole fetch() call in an OUTER bound
    # (asyncio.wait_for / gather timeout) in the generate() preflight — do not
    # assume this inner per-request timeout caps total latency.
    effective_timeout = (
        timeout if timeout is not None else settings.brave_timeout_seconds
    )

    close_client = False
    client = http_client
    if client is None:
        close_client = True
        client = httpx.AsyncClient(timeout=effective_timeout)

    outcome = "error"
    start = time.perf_counter()
    try:
        result, outcome = await _request_with_retry(
            client, params, headers, timeout=effective_timeout
        )
        return result
    except Exception:
        # The acceptance bar is "raises nothing": even an unexpected error fails
        # open to no research. Log the event name only — never the key, params,
        # or snippets.
        logger.warning("brave.fetch_unexpected_error", exc_info=True)
        outcome = "error"
        return None
    finally:
        BRAVE_REQUEST_LATENCY.observe(time.perf_counter() - start)
        BRAVE_REQUESTS_TOTAL.labels(outcome=outcome).inc()
        if close_client:
            await client.aclose()


async def _request_with_retry(
    client: httpx.AsyncClient,
    params: dict[str, str | int],
    headers: dict[str, str],
    *,
    timeout: float,
) -> tuple[BraveResult | None, str]:
    """Issue the GET with one retry on 429/5xx. Returns (result_or_none, outcome).

    Outcomes: ``hit`` (content), ``empty`` (2xx, no grounding), ``timeout``,
    ``rate_limited`` (429 after retry), ``error`` (everything else).
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await client.get(
                BRAVE_LLM_CONTEXT_URL,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return None, "timeout"
        except httpx.HTTPError:
            return None, "error"

        status = response.status_code
        is_last = attempt + 1 >= _MAX_ATTEMPTS
        if status == 429 or 500 <= status < 600:
            if is_last:
                logger.warning(
                    "brave.fetch_retryable_status_exhausted",
                    extra={"status": status},
                )
                return None, ("rate_limited" if status == 429 else "error")
            await asyncio.sleep(_retry_delay(response))
            continue
        if status != 200:
            logger.warning("brave.fetch_unexpected_status", extra={"status": status})
            return None, "error"

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning("brave.fetch_malformed_body")
            return None, "error"

        result = _parse(payload, str(params["q"]))
        if result is None:
            logger.warning("brave.fetch_unexpected_schema")
            return None, "error"
        return result, ("empty" if result.is_empty else "hit")

    # Unreachable in practice (the loop returns on every branch), but keeps the
    # never-raises contract total.
    return None, "error"  # pragma: no cover


def _retry_delay(response: httpx.Response) -> float:
    """Honour ``Retry-After`` (seconds), clamped to a tiny ceiling."""
    retry_after = response.headers.get("Retry-After", "")
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), _MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return _DEFAULT_BACKOFF_SECONDS


def _parse(payload: object, query: str) -> BraveResult | None:
    """Shape-validate a 2xx body into a ``BraveResult``; ``None`` if malformed.

    A missing ``grounding``/``generic`` is treated as a valid *empty* result
    (Brave returns ``grounding.generic == []`` when it finds nothing), but a
    ``generic`` that is present and not a list is malformed → ``None``.
    """
    if not isinstance(payload, dict):
        return None

    grounding = payload.get("grounding")
    if grounding is None:
        generic: object = []
    elif isinstance(grounding, dict):
        generic = grounding.get("generic", [])
    else:
        return None
    if generic is None:
        generic = []
    if not isinstance(generic, list):
        return None

    results: list[BraveSnippet] = []
    for item in generic:
        if not isinstance(item, dict):
            continue
        raw_snippets = item.get("snippets")
        if not isinstance(raw_snippets, list):
            continue
        snippets = tuple(
            s.strip() for s in raw_snippets if isinstance(s, str) and s.strip()
        )
        if not snippets:
            continue
        results.append(
            BraveSnippet(
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                snippets=snippets,
            )
        )

    return BraveResult(
        query=query,
        results=tuple(results),
        sources=_parse_sources(payload.get("sources")),
    )


def _parse_sources(raw: object) -> tuple[BraveSource, ...]:
    if not isinstance(raw, dict):
        return ()
    sources: list[BraveSource] = []
    for url, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        age = meta.get("age")
        sources.append(
            BraveSource(
                url=str(url),
                title=str(meta.get("title") or ""),
                hostname=str(meta.get("hostname") or ""),
                age=str(age) if age else None,
            )
        )
    return tuple(sources)
