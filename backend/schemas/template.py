"""Pydantic schema for the starter templates endpoint (T-USE-11 / T-170).

Mirrors harness/schemas/template.schema.json exactly. `extra="forbid"`
locks the response shape so we can't accidentally leak future columns
through the unauthenticated GET /templates endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TemplateCategory = Literal[
    "auth",
    "payments",
    "content",
    "realtime",
    "agent",
    "tooling",
]


class TemplateRead(BaseModel):
    id: UUID
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=400)
    category: TemplateCategory
    # Starter templates intentionally stay at the original 10K ceiling, NOT the
    # raised workspace cap (PROBLEM_STATEMENT_MAX_CHARS). Templates are authored,
    # curated seed content — not user pastes — so they have no need for the large
    # input that the compression plan (§2/§10) raises the *workspace* cap for.
    problem_statement: str = Field(min_length=50, max_length=10_000)
    sort_order: int = Field(ge=0)
    active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, extra="forbid")
