"""Idempotent starter-template seeder (T-USE-11 / T-170).

Runs at every container start *after* `alembic upgrade head` so the
templates strip is populated by the time the API accepts traffic.

Idempotency:
- Uses Postgres `INSERT ... ON CONFLICT (slug) DO UPDATE SET ...`.
- `created_at` is explicitly omitted from the UPDATE clause so re-runs
  do not bump it for already-existing rows. This matters because the
  schema requires `created_at` to remain stable for templates that
  workspaces reference via `Workspace.template_slug`.
- The script exits 0 against an empty database (the migration has
  already created the table) and against a fully-populated one.

To extend, add a new entry to STARTER_TEMPLATES below. The `slug` is
the stable identifier — never rename one in place; instead add a new
slug and mark the old one `active=False`.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import Template

logger = logging.getLogger(__name__)

# Eight hand-tuned starter templates. Each problem_statement is purposely
# generous (>200 chars) so the spec stage has enough signal to produce a
# high-quality first generation.
STARTER_TEMPLATES: list[dict[str, Any]] = [
    {
        "slug": "stripe-like-checkout",
        "name": "Subscription checkout flow",
        "description": "Stripe-style subscription billing with trial + dunning.",
        "category": "payments",
        "problem_statement": (
            "I want a subscription billing flow with a 14-day free trial. "
            "Users sign up with Google OAuth, pick a plan (Hobby $9 / Team "
            "$29 / Business $99), and enter a card. Cards are tokenised with "
            "Stripe Elements; the backend never sees raw PAN. On trial end "
            "we charge automatically. On a failed charge we retry per dunning "
            "schedule (day 0/3/7/14), then suspend. Admins can issue refunds "
            "and switch plans mid-cycle (proration handled by Stripe). The "
            "UI shows the current plan, next charge date, and an invoice "
            "history. Webhooks are idempotent and signature-verified."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 10,
    },
    {
        "slug": "linear-like-ticketing",
        "name": "Issue tracker",
        "description": (
            "Linear-style issue tracker with cycles, projects, and filters."
        ),
        "category": "tooling",
        "problem_statement": (
            "Build a fast issue tracker for engineering teams. Issues have "
            "title, description (markdown), assignee, status (Backlog/Todo/In "
            "Progress/Done/Cancelled), priority (Urgent/High/Medium/Low), "
            "estimate, labels, and a parent for sub-issues. Cycles are "
            "two-week iterations; projects are higher-level groupings. The "
            "left rail shows views; the centre is an inline-editable list "
            "with keyboard shortcuts (j/k navigate, e edit, c create). "
            "Real-time presence + cursor positions for collaborators. Search "
            "is sub-200ms via a server-side index. Multi-tenant: each "
            "workspace is isolated by org_id; invitations expire in 7 days."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 20,
    },
    {
        "slug": "slack-bot",
        "name": "Slack bot",
        "description": (
            "Stateful Slack bot with slash commands, modals, and OAuth."
        ),
        "category": "tooling",
        "problem_statement": (
            "I need a Slack bot that helps teams run weekly standups. The bot "
            "is installed per workspace via Slack's OAuth flow. A scheduled "
            "job posts a thread in the configured channel every Monday at "
            "10am local time asking three questions; replies are summarised "
            "and posted as a digest at 11am. A `/standup` slash command "
            "opens a modal where admins can configure the channel, schedule, "
            "and questions. The bot stores per-workspace tokens encrypted at "
            "rest. Rate limiting respects Slack's tier-2 limits. We persist "
            "responses for 90 days then prune."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 30,
    },
    {
        "slug": "ai-chat-assistant",
        "name": "AI chat assistant",
        "description": (
            "Streaming AI chat with citations, conversation history, and RAG."
        ),
        "category": "agent",
        "problem_statement": (
            "Build an AI chat assistant where users can paste a corpus of "
            "documents (PDFs, markdown, web URLs) and chat with them. "
            "Documents are chunked + embedded (1024-dim), stored in pgvector. "
            "Responses stream token-by-token, cite sources inline with "
            "footnote links, and reject questions that aren't grounded in "
            "the corpus. Conversations persist; users can branch from any "
            "turn. Costs are tracked per user and capped daily. The system "
            "uses Claude for synthesis; embedding is OpenAI text-embedding-3. "
            "Auth via Google OAuth; per-user vector namespaces."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 40,
    },
    {
        "slug": "internal-admin-panel",
        "name": "Internal admin panel",
        "description": "Retool-style admin with auth, audit log, and table editors.",
        "category": "tooling",
        "problem_statement": (
            "An internal admin panel for ops/support to look up users, "
            "credit accounts, refund charges, and toggle feature flags. "
            "Every mutation writes to an audit log (who/when/what/before/"
            "after) that is queryable but immutable. Access is gated by "
            "Google Workspace SSO and a role table (viewer/operator/admin). "
            "Operator and above can issue refunds up to $500; only admin can "
            "override the cap. Tables paginate at 50 rows and support "
            "server-side filters. The panel is internal-only — IP-allowlisted "
            "behind a VPN gateway. Idle sessions time out after 30 minutes."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 50,
    },
    {
        "slug": "rest-api-server",
        "name": "Production REST API server",
        "description": "FastAPI server with JWT auth, PostgreSQL, and OpenAPI docs.",
        "category": "tooling",
        "problem_statement": (
            "A production-ready REST API server for a multi-tenant SaaS. "
            "FastAPI on Python 3.12, async SQLAlchemy 2.0 with PostgreSQL, "
            "Alembic for migrations, JWT auth via RS256 with refresh tokens, "
            "and Pydantic schemas. Endpoints follow REST conventions with "
            "consistent error shapes ({error, message, request_id}). "
            "Rate-limited (100 req/min per user, 1000 req/hour). Structured "
            "logging with request IDs; OpenTelemetry traces. CI runs ruff, "
            "black, pytest with 80% coverage gate, pip-audit, and bandit. "
            "Deployed via Docker to a managed PaaS."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 60,
    },
    {
        "slug": "realtime-presence",
        "name": "Real-time collaborative cursors",
        "description": "Figma-style cursors + selection sync via WebSocket + CRDT.",
        "category": "realtime",
        "problem_statement": (
            "A real-time collaboration layer where multiple users see each "
            "other's cursors and selections on a shared document in <100ms. "
            "WebSocket transport with reconnect + exponential backoff. "
            "Document state syncs via a Yjs CRDT; presence is ephemeral and "
            "lives only in memory. Per-room sharding by document_id, scaled "
            "across multiple Node processes via Redis pubsub. Auth via short-"
            "lived JWT issued by the main app. Server gracefully drops idle "
            "rooms after 5 minutes with no participants. Operational dashboard "
            "shows live room count + p95 message latency."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 70,
    },
    {
        "slug": "agent-harness",
        "name": "LLM agent harness",
        "description": (
            "Tool-calling agent loop with traces, retries, and safety gates."
        ),
        "category": "agent",
        "problem_statement": (
            "Build an LLM agent harness that runs tool-calling loops on top "
            "of Claude. Tools are declared as Python functions with type "
            "hints and dosctrings; the harness auto-generates the JSON schema "
            "for the model. Each turn is traced (input/output/tokens/latency) "
            "and persisted. Retries with exponential backoff on provider 5xx. "
            "Safety gate: a content filter runs on every tool input/output. "
            "Token + dollar budget per session, hard-capped. Streaming UI "
            "shows the model's plan, each tool call, and the final answer. "
            "A replay mode lets developers re-run a session deterministically "
            "from the trace."
        ),
        "suggested_provider": "anthropic",
        "suggested_model": None,
        "sort_order": 80,
    },
]


async def seed(db: AsyncSession) -> int:
    """Upsert all known templates. Returns the number processed (always equal
    to the static count, since ON CONFLICT covers both new and existing rows).
    """
    for entry in STARTER_TEMPLATES:
        stmt = pg_insert(Template).values(**entry)
        # Important: omit `created_at` from the UPDATE clause so re-runs do
        # NOT bump it for already-existing rows.
        update_cols = {
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
            "category": stmt.excluded.category,
            "problem_statement": stmt.excluded.problem_statement,
            "suggested_provider": stmt.excluded.suggested_provider,
            "suggested_model": stmt.excluded.suggested_model,
            "sort_order": stmt.excluded.sort_order,
            "active": True,  # re-enable any soft-disabled row whose slug we re-seed
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[Template.slug],
            set_=update_cols,
        )
        await db.execute(stmt)
    await db.commit()
    return len(STARTER_TEMPLATES)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    async with AsyncSessionLocal() as db:
        count = await seed(db)
    logger.info("seeded_templates count=%d", count)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
