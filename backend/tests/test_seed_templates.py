"""Unit tests for the starter-template seed script (T-USE-11 / T-170).

The script depends on Postgres for `ON CONFLICT DO UPDATE`, so we don't
exercise the SQL here. Instead we validate the catalog itself:

- 6+ entries, each with a slug from the documented set.
- Slugs are unique and match the regex contract.
- Problem statements meet the 200-char floor that makes for high-quality
  first generations.
- Categories are in the enum locked by the model's CHECK constraint.
"""
from __future__ import annotations

import re

import pytest

from scripts.seed_templates import STARTER_TEMPLATES

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ALLOWED_CATEGORIES = {"auth", "payments", "content", "realtime", "agent", "tooling"}
_REQUIRED_SLUGS = {
    "stripe-like-checkout",
    "linear-like-ticketing",
    "slack-bot",
    "ai-chat-assistant",
    "internal-admin-panel",
    "rest-api-server",
    "realtime-presence",
    "agent-harness",
}


def test_at_least_six_starter_templates() -> None:
    assert len(STARTER_TEMPLATES) >= 6


def test_required_slugs_are_present() -> None:
    present = {t["slug"] for t in STARTER_TEMPLATES}
    missing = _REQUIRED_SLUGS - present
    assert not missing, f"Missing required template slugs: {missing}"


def test_slugs_are_unique_and_kebab_case() -> None:
    slugs = [t["slug"] for t in STARTER_TEMPLATES]
    assert len(set(slugs)) == len(slugs), "Duplicate slug in seed catalog."
    for slug in slugs:
        assert _SLUG_RE.match(slug), f"{slug!r} is not lowercase-kebab."


def test_categories_match_enum() -> None:
    for entry in STARTER_TEMPLATES:
        assert entry["category"] in _ALLOWED_CATEGORIES, (
            f"{entry['slug']}: category {entry['category']!r} not in enum"
        )


def test_problem_statements_meet_minimum_length() -> None:
    # Spec contract: at least 50 chars per the schema; the task spec asks
    # for 200+ to produce a high-quality spec on first generation.
    for entry in STARTER_TEMPLATES:
        assert len(entry["problem_statement"]) >= 200, (
            f"{entry['slug']}: problem_statement is {len(entry['problem_statement'])} "
            "chars; need >=200 for good first-generation quality."
        )


def test_sort_orders_are_unique() -> None:
    # Ties on sort_order fall back to alphabetical name, which is unstable
    # for a curated strip. Enforce uniqueness so the dashboard order is
    # deterministic across deploys.
    orders = [t["sort_order"] for t in STARTER_TEMPLATES]
    assert len(set(orders)) == len(orders)


@pytest.mark.parametrize("entry", STARTER_TEMPLATES, ids=lambda e: e["slug"])
def test_entry_has_minimal_marketing_fields(entry: dict) -> None:
    # Every card on the strip needs both a name and a short description.
    assert entry["name"]
    assert 1 <= len(entry["description"]) <= 400
