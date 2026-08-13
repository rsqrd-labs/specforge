"""Diff the openrouter catalog entries against OpenRouter's live models API.

Why this exists (issue #152 review, finding F9). The catalog's openrouter rates
were originally transcribed by hand from ``GET /api/v1/models``, and two classes
of error followed that a human review cannot reliably catch:

1. **Alias vs pinned host.** ``/models`` reports one price per model *slug*, but
   a slug is served by many upstream hosts at different prices. Those differ
   materially — ``deepseek/deepseek-v4-pro`` is $0.435/$0.870 on DeepSeek's own
   host and $1.168/$2.336 at the alias. Because every openrouter entry pins its
   upstream host (``ModelCatalogEntry.upstream_providers``), the *pinned
   endpoint's* rates are the ones actually billed, and those are the ones this
   script compares. Reading the alias is how the retired ``z-ai/glm-5.2`` entry
   came to record $1.536/M output against a live $2.52.
2. **Silent drift.** Rates, real output ceilings, caching support and accepted
   parameters all change under a floating slug with no notification.

``docs/evals/CATALOG_HYGIENE.md`` mandates a quarterly + on-release catalog
review; this makes that review mechanical instead of manual.

Deliberately NOT wired into CI: it needs live network access, and on a private
repo GitHub bills a scheduled job ~1 full minute per firing regardless of
runtime (see CLAUDE.md's CI-minutes arithmetic). Run it on demand, or from a
``workflow_dispatch`` job.

Usage::

    uv run python ../scripts/check_openrouter_catalog_drift.py
    uv run python ../scripts/check_openrouter_catalog_drift.py --json

Exit codes: 0 = no drift, 1 = drift found, 2 = the API could not be reached.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.llm.model_catalog import (  # noqa: E402
    ModelCatalogEntry,
    iter_model_entries,
)

_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model_id}/endpoints"
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# Rates are compared as USD-per-million with a relative tolerance rather than
# exactly: OpenRouter publishes per-token strings like "0.000000435" whose
# round-trip through float carries representation error far below any amount
# that matters. 0.5% is well inside "same price", well outside a real change.
_RATE_TOLERANCE = 0.005

# Catalog field -> the pricing key on an OpenRouter endpoint payload.
_RATE_FIELDS = {
    "input_cost_per_million": "prompt",
    "output_cost_per_million": "completion",
    "cached_input_cost_per_million": "input_cache_read",
}


@dataclass
class Drift:
    model_id: str
    issues: list[str] = field(default_factory=list)


def _per_million(raw: Any) -> float | None:
    """OpenRouter prices are per-token decimal strings; the catalog is per-million."""
    if raw in (None, ""):
        return None
    try:
        return float(raw) * 1_000_000
    except (TypeError, ValueError):
        return None


def _rates_agree(catalog: float | None, live: float | None) -> bool:
    if catalog is None or live is None:
        return catalog == live
    if catalog == 0 or live == 0:
        return catalog == live
    return abs(catalog - live) / max(abs(catalog), abs(live)) <= _RATE_TOLERANCE


def _pinned_endpoint(payload: dict, entry: ModelCatalogEntry) -> dict | None:
    """The endpoint for the host this entry pins, or None if it is gone.

    A pinned host disappearing from the slug's endpoint list is the single most
    important thing this script can report: it means every request pinned to it
    now gets a permanent 503 ("no available model provider meets your routing
    requirements"), not a silent fallback — pinning is what removes the
    fallback.
    """
    wanted = {name.lower() for name in entry.upstream_providers}
    for endpoint in payload.get("endpoints", []):
        name = str(endpoint.get("provider_name") or "").lower()
        # OpenRouter's endpoint payload names hosts in display form ("DeepSeek")
        # while the routing allowlist takes slugs ("deepseek"); match on both.
        if name in wanted or name.replace(" ", "-") in wanted:
            return endpoint
    return None


def _check_entry(entry: ModelCatalogEntry, client: httpx.Client) -> Drift:
    drift = Drift(model_id=entry.model_id)

    if not entry.upstream_providers:
        drift.issues.append(
            "no upstream_providers pin — the balancer may serve this from any "
            "host, so no single set of live rates describes what is billed"
        )
        return drift

    response = client.get(_ENDPOINTS_URL.format(model_id=entry.model_id))
    if response.status_code == 404:
        drift.issues.append("slug no longer exists on OpenRouter")
        return drift
    response.raise_for_status()
    payload = response.json().get("data", {})

    endpoint = _pinned_endpoint(payload, entry)
    if endpoint is None:
        available = sorted(
            str(e.get("provider_name")) for e in payload.get("endpoints", [])
        )
        drift.issues.append(
            f"pinned host {list(entry.upstream_providers)} no longer serves this "
            f"slug — every request would 503. Available: {available}"
        )
        return drift

    pricing = endpoint.get("pricing") or {}
    for catalog_field, pricing_key in _RATE_FIELDS.items():
        catalog_rate = getattr(entry, catalog_field)
        live_rate = _per_million(pricing.get(pricing_key))
        if not _rates_agree(catalog_rate, live_rate):
            drift.issues.append(
                f"{catalog_field}: catalog={catalog_rate} live={live_rate}"
            )

    # A cache-WRITE premium must be priced, or estimate_cost_usd() returns None
    # with non-zero write tokens and the ledger records no cost at all.
    live_write = _per_million(pricing.get("input_cache_write"))
    if live_write is not None and not _rates_agree(
        entry.cache_write_5m_cost_per_million, live_write
    ):
        drift.issues.append(
            f"cache_write_5m_cost_per_million: catalog="
            f"{entry.cache_write_5m_cost_per_million} live={live_write}"
        )

    # Caching support is the whole reason these entries are pinned to this host.
    if not endpoint.get("supports_implicit_caching"):
        drift.issues.append(
            "pinned host no longer reports supports_implicit_caching — prompt "
            "caching is silently off, and cached_input rates below base become "
            "an under-estimate of real spend"
        )

    max_out = endpoint.get("max_completion_tokens")
    if max_out is not None and max_out < entry.default_max_output_tokens:
        drift.issues.append(
            f"pinned host max_completion_tokens={max_out} is below the catalog "
            f"ceiling {entry.default_max_output_tokens} — requests can 400 or "
            "truncate"
        )

    supported = set(endpoint.get("supported_parameters") or [])
    if entry.reasoning_effort is not None and "reasoning_effort" not in supported:
        drift.issues.append(
            f"catalog sets reasoning_effort={entry.reasoning_effort!r} but the "
            "pinned host does not accept that parameter"
        )

    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help="also check retired entries (they are unpinned by design, so this "
        "normally just reports the missing pin)",
    )
    args = parser.parse_args()

    entries = [
        entry
        for entry in iter_model_entries("openrouter")
        if args.include_deprecated or entry.status == "active"
    ]

    drifts: list[Drift] = []
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            for entry in entries:
                drift = _check_entry(entry, client)
                if drift.issues:
                    drifts.append(drift)
    except httpx.HTTPError as exc:
        print(f"Could not reach the OpenRouter models API: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "checked": [entry.model_id for entry in entries],
                    "drift": [
                        {"model_id": d.model_id, "issues": d.issues} for d in drifts
                    ],
                },
                indent=2,
            )
        )
    elif not drifts:
        print(f"No drift across {len(entries)} active openrouter entries.")
    else:
        for drift in drifts:
            print(f"\n{drift.model_id}")
            for issue in drift.issues:
                print(f"  - {issue}")
        print(f"\n{len(drifts)} of {len(entries)} entries drifted.")

    return 1 if drifts else 0


if __name__ == "__main__":
    raise SystemExit(main())
