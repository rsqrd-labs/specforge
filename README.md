# SpecForge

SpecForge turns a product idea into an implementation-ready delivery package.

It guides a workspace through four stages:

```text
Problem statement -> Spec -> Plan -> Harness -> Tasks
```

The output is designed for teams and AI-assisted engineering workflows that need more than a generic prompt response. SpecForge produces structured product specifications, implementation plans, validation harnesses, and execution tasks with review gates, credit accounting, provider selection, and exportable artifacts.

## What The Product Does

SpecForge helps users move from vague product intent to a buildable software plan.

Core capabilities:

- Google OAuth sign-in and secure session management.
- Starter templates to bootstrap a workspace from common problem types.
- Workspace creation from a problem statement with optional clarification questions before generation.
- Streaming AI generation for `SPEC.md`, `PLAN.md`, harness coverage, and `tasks.md`.
- Human review gates between stages.
- Stage refinement with diff preview and accept/reject flow.
- Credit accounting for generation and accepted refinements.
- Paid credit packs through Lemon Squeezy hosted checkout (Phase 22), with signed webhooks, idempotent grants, and refund/dispute handling. See `docs/INTEGRATION_API_SETUP_HANDBOOK.md` for setup and `docs/RUNBOOK.md` §9 for billing ops. Leave the `LEMONSQUEEZY_*` keys blank to disable checkout.
- Provider-aware LLM routing for Anthropic, OpenAI, and Google.
- User-supplied provider API keys, encrypted at rest, with platform key fallback.
- Online evaluation and quality indicators for generated stages.
- Harness full-coverage badge when all spec requirements are mapped to tests.
- Task priority, time estimates, and effort summary across the task list.
- Export options: ZIP delivery package, PDF document, GitHub repository push, and public share link.

## Product Flow

1. User signs in with Google.
2. User creates a workspace from a problem statement, optionally selecting a starter template.
3. SpecForge may ask clarifying questions to sharpen the Spec before generation begins.
4. SpecForge generates the stages in order:
   - `Spec`: requirements, users, journeys, constraints, and acceptance criteria.
   - `Plan`: architecture, implementation strategy, risks, and sequencing.
   - `Harness`: validation assets and coverage expectations.
   - `Tasks`: traceable work items with priority and time estimates, ready for execution.
5. User reviews, refines, and accepts each stage before the next unlocks.
6. User exports the package: ZIP archive, PDF document, push to a GitHub repository, or a public share link.

## Architecture

SpecForge is a full-stack web application with a React frontend, FastAPI backend, PostgreSQL persistence, Redis-backed session/rate-limit state, and pluggable LLM providers.

```text
Browser
  |
  | React + Vite frontend
  v
FastAPI API
  |
  |-- PostgreSQL: users, workspaces, stages, credits, evals, templates
  |-- Redis: refresh sessions, rate limits, transient auth state
  |-- LLM gateway: Anthropic, OpenAI, Google Gemini
  |-- PDF renderer: WeasyPrint with no-network URL fetcher
  |-- Observability: Prometheus metrics, Sentry, optional OTLP
```

Important backend areas:

- `backend/routers`: HTTP API routes for auth, workspaces, stages, credits, providers, integrations, and public share.
- `backend/services/pipeline`: stage generation, diffing, PDF export, prompt building, and recovery.
- `backend/services/llm`: provider adapters and routing.
- `backend/services/evals`: online evaluation and quality scoring.
- `backend/services/security`: CSRF, prompt guard, output validator, sanitizer, and encrypted key handling.
- `backend/middleware`: rate limiting and CSRF enforcement.
- `backend/migrations`: Alembic database migrations.
- `backend/scripts/seed_templates.py`: idempotent starter-template seed, runs on every container start.

Important frontend areas:

- `frontend/src/pages`: landing, auth callback, dashboard, workspace, and public share (`/p/:slug`) screens.
- `frontend/src/components/workspace`: stage editor, navigator, streaming overlay, review gates, diff viewer, clarification modal, and validation panels.
- `frontend/src/services`: API and streaming clients.
- `frontend/src/store`: Zustand stores for user, workspace, and stage state.
- `frontend/src/types`: shared frontend TypeScript types.

### Public Share Route

`/p/:slug` is an unauthenticated React route served outside the auth guard. It reads from `GET /public/{slug}` with no CSRF or auth headers. Both surfaces inject `noindex, nofollow` metadata. The route prefix is disallowed in `frontend/public/robots.txt`.

### PDF Export

PDF rendering uses WeasyPrint. The backend Dockerfile installs the required native libraries (`libcairo2`, `libpango-1.0-0`, `libpangoft2-1.0-0`). The renderer is configured with a `no_network_url_fetcher` that refuses every non-`data:` URL at render time.

### Starter Templates

The `templates` table is populated automatically on every container start by `backend/scripts/seed_templates.py`, invoked from `backend/entrypoint.sh` after `alembic upgrade head`. The seed is idempotent. To add a new template, edit `STARTER_TEMPLATES` in the seed script — never rename a slug in place; add a new slug and mark the old one inactive.

## Tech Stack

Backend:

- Python 3.12
- FastAPI / Starlette
- SQLAlchemy async ORM
- Alembic migrations
- PostgreSQL 16
- Redis 7
- Authlib and python-jose for OAuth/JWT flows
- Anthropic, OpenAI, and Google Generative AI SDKs
- WeasyPrint for PDF rendering
- Structlog, Prometheus, Sentry, and OpenTelemetry
- Pytest, Ruff, Black, Bandit, pip-audit

Frontend:

- React 18
- TypeScript
- Vite 6
- Tailwind CSS
- Zustand
- Axios
- CodeMirror Markdown editor
- Vitest and Testing Library
- Optional Sentry browser tracing

Infrastructure:

- Docker Compose for local full-stack runtime
- Backend Dockerfile using `python:3.12-slim`, `uv`, Gunicorn, and Uvicorn workers
- Vite dev server for local frontend development

## Repository Layout

```text
.
├── backend/                  FastAPI app, services, migrations, tests
├── frontend/                 React/Vite app, components, stores, tests
├── harness/                  Contract and harness tests
├── docs/                     Operational and smoke-test documentation
├── docker-compose.yml        Local full-stack compose setup
├── Design.md                 Product design system notes
├── tasks.md                  Implementation task plan
└── README.md                 Project guide
```

## Prerequisites

Install these locally:

- Docker and Docker Compose
- Python 3.12
- `uv`
- Node.js 22
- `pnpm` 9.x through Corepack

Useful setup commands:

```bash
pip install uv
corepack enable
```

## Environment Configuration

Backend environment variables live in `backend/.env`.

Start from the example:

```bash
cp backend/.env.example backend/.env
```

Frontend environment variables can live in `frontend/.env`:

```bash
cp frontend/.env.example frontend/.env
```

See `docs/LOCAL_TESTING_HANDBOOK.md` for a step-by-step guide to generating secrets and configuring the stack for local development.

### Backend Variables

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Async PostgreSQL URL. Docker Compose overrides this to use the `db` service. |
| `REDIS_URL` | Redis URL. Docker Compose overrides this to use the `redis` service. |
| `JWT_PRIVATE_KEY` | RS256 private key used to sign access and refresh tokens. |
| `JWT_PUBLIC_KEY` | RS256 public key used to verify tokens. |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret. |
| `FRONTEND_URL` | Public frontend origin used for redirects and CORS. |
| `ANTHROPIC_API_KEY` | Anthropic API key. Leave blank to disable the Anthropic provider. |
| `OPENAI_API_KEY` | OpenAI API key. Leave blank to disable the OpenAI provider. |
| `GOOGLE_API_KEY` | Google Gemini API key. Leave blank to disable the Google provider. |
| `ENCRYPTION_MASTER_KEY` | Fernet-compatible key for encrypting user-stored provider keys and OAuth tokens. |
| `CSRF_SECRET` | HMAC secret for CSRF token signing. |
| `METRICS_TOKEN` | Bearer token protecting the `/metrics` endpoint. Leave blank to allow unauthenticated scraping (not recommended in production). |
| `MAX_ACTIVE_WORKSPACES_PER_USER` | Optional cap on active workspaces per user. Defaults to unlimited when unset. |
| `GITHUB_CLIENT_ID` | GitHub OAuth App client ID. Leave blank to disable the GitHub export integration. |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret. Required when `GITHUB_CLIENT_ID` is set. |
| `SENTRY_DSN` | Optional backend Sentry DSN. |
| `GRAFANA_OTLP_ENDPOINT` | Optional OTLP trace endpoint. |
| `GRAFANA_OTLP_TOKEN` | Optional OTLP auth token. |
| `LANGFUSE_SECRET_KEY` | Optional. Enables LLM-observability traces via Langfuse. Leave blank to disable. |
| `LANGFUSE_PUBLIC_KEY` | Optional. Required only when `LANGFUSE_SECRET_KEY` is set. |
| `LANGFUSE_HOST` | Optional. Defaults to `https://cloud.langfuse.com`. Point to a self-hosted Langfuse instance to keep prompts on-premises. |
| `LANGFUSE_PROMPT_CACHE_TTL` | Optional. In-process TTL (seconds) for Langfuse-managed prompt templates. Defaults to `300`. |
| `LANGFUSE_CONTENT_CAPTURE_ACK` | Required in production only when Langfuse is enabled. Set to `true` to acknowledge prompt/output telemetry export after redaction. |
| `ENVIRONMENT` | Runtime environment name, for example `development` or `production`. |

### Frontend Variables

| Variable | Purpose |
| --- | --- |
| `VITE_API_URL` | Browser-facing backend URL. |
| `VITE_SENTRY_DSN` | Optional frontend Sentry DSN. |

## Local Development With Docker

This is the fastest way to run the whole app locally.

The compose file is for local development only. It uses development datastore
credentials and binds PostgreSQL and Redis to `127.0.0.1` so they are not
published on every host interface. Production and shared environments must use
managed/private datastores with secrets injected by the deployment platform.

```bash
docker compose up --build
```

The compose stack starts:

- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`
- FastAPI API on `localhost:8000`
- Vite frontend on `localhost:5173`

Open:

```text
http://localhost:5173
```

Stop the stack:

```bash
docker compose down
```

Reset local database and Redis volumes:

```bash
docker compose down -v
```

### Optional: Langfuse Self-Hosted Observability

To run Langfuse locally and capture LLM traces from your dev workspace:

```bash
docker compose --profile langfuse up
```

Then set in `backend/.env`:

```bash
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_SECRET_KEY=...   # from Langfuse UI after first signup
LANGFUSE_PUBLIC_KEY=...
```

Without these set, the application runs identically with no Langfuse integration.

## Local Development Without Docker

Run PostgreSQL and Redis yourself, then configure `backend/.env` with their URLs.

Backend:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev
```

Default URLs:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:8000
Health:   http://localhost:8000/health
Metrics:  http://localhost:8000/metrics
```

## Database Migrations

Apply migrations:

```bash
cd backend
uv run alembic upgrade head
```

Create a new migration after model changes:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
```

Review autogenerated migrations before applying them.

## Verification

Backend:

```bash
cd backend
uv run pytest tests/ -q
uv run ruff check .
uv run black --check .
```

Frontend:

```bash
cd frontend
pnpm tsc --noEmit
pnpm test
pnpm build
```

Harness and contract tests:

```bash
cd backend
uv run pytest ../harness/tests/backend/ -q
```

Smoke-test guidance:

```text
docs/SMOKE_TEST_CHECKLIST.md
```

## Provider-Agnostic LLM Cost Optimization

SpecForge keeps cost optimization provider-neutral. `services.llm.cost_registry`
is the static source of truth for OpenAI, Anthropic, and Google model tiers,
costs, context limits, usage support, prompt-cache accounting, and batch support.
Stage logic routes by operation and tier (`strong`, `mid`, `mini`, `small`) via
`resolve_llm_route()` instead of hard-coding provider model names.

Key invariants:

- OpenAI, Anthropic, and Google keys are optional per environment, but configured
  providers must use `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GOOGLE_API_KEY`.
- Cross-provider fallback is never silent. It requires an explicit
  `allow_cross_provider=True` policy decision and is reported in telemetry.
- Prompt moat prefixes are versioned and stable so dynamic context can be cached
  and summarized without rewriting core instructions.
- Generation/refine cache keys include provider, model, tier, prompt version,
  operation, problem hash, upstream hashes, instruction hash, and output contract.
- `llm.cost_recorded` logs and Prometheus metrics include provider, model tier,
  operation, stage type, prompt version, token counts, estimated cost, cache hit,
  batch flag, latency, and cross-provider fallback. They must not include prompt
  or output text.
- Cheaper defaults require evidence from `scripts/run_llm_route_eval.py`, the
  golden prompt dataset, and manual operator approval.

## Security Model

SpecForge includes several controls intended for AI-assisted workflows:

- Access tokens are kept in frontend memory only.
- Refresh tokens are stored in secure, scoped HTTP-only cookies.
- Refresh-token reuse revokes all tracked sessions for the user.
- Mutating API calls require CSRF tokens.
- Login endpoints have short-term and hourly rate limits.
- Workspace ownership checks return 404 for cross-user access.
- User input is sanitized before persistence and refinement.
- Prompt guard checks reject prompt-injection attempts before LLM calls.
- Output validation blocks system-prompt leakage and unsafe model output.
- Logs and Sentry events are scrubbed for likely secrets before export.
- Langfuse payloads go through the shared redaction path before export.
- User-supplied provider API keys are encrypted with Fernet before storage.
- CI runs TruffleHog, Bandit, non-interactive `pip-audit`, and
  `pnpm audit --audit-level moderate`; no dependency scanner token is required.

Production deployments should also enforce HTTPS, secure cookies, strict CORS, strong secrets, provider key rotation, and database backups.

### Provider Key Rotation

LLM provider clients are cached inside each API worker for connection reuse.
After rotating `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`,
restart all API workers so cached clients are recreated with the new secret.

## Deployment Overview

SpecForge can be deployed as two application services plus managed PostgreSQL and Redis:

```text
Frontend static site/CDN
Backend container service
Managed PostgreSQL
Managed Redis
Optional observability: Sentry + OTLP/Grafana
```

Recommended production shape:

- Build the frontend with `pnpm build` and serve `frontend/dist` from a static host or CDN.
- Build the backend Docker image from `backend/Dockerfile`.
- Run migrations before starting or during a controlled release step.
- Use managed PostgreSQL and Redis rather than single-node containers.
- Store secrets in a platform secret manager.
- Configure Google OAuth redirect URIs for the production frontend/backend URLs.
- Configure `FRONTEND_URL` and `VITE_API_URL` to the public origins.
- Enable HTTPS and secure cookies.

See `docs/INTEGRATION_API_SETUP_HANDBOOK.md` for full deployment configuration instructions.

## Backend Container Deployment

Build:

```bash
docker build -t specforge-api ./backend
```

Run API:

```bash
docker run --rm \
  --env-file backend/.env \
  -p 8000:8000 \
  specforge-api
```

`entrypoint.sh` runs `alembic upgrade head` and the starter-template seed automatically before starting Gunicorn, so migrations and template data are applied on every container start. To run migrations separately without starting the server, override the entrypoint:

```bash
docker run --rm \
  --env-file backend/.env \
  --entrypoint uv \
  specforge-api \
  run --no-sync alembic upgrade head
```

The Dockerfile starts Gunicorn with Uvicorn workers:

```text
gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:8000
```

The Dockerfile also installs native libraries required for PDF rendering (`libcairo2`, `libpango-1.0-0`, `libpangoft2-1.0-0`). These must be present in the container image — do not strip them from a slimmed build.

Tune worker count and CPU/memory limits for your hosting platform.

## Frontend Deployment

Install and build:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
```

Deploy:

```text
frontend/dist
```

Set the production API URL before building:

```bash
VITE_API_URL=https://api.example.com pnpm build
```

For single-page app hosting, configure fallback routing so all unknown paths serve `index.html`. This is required for the public share route (`/p/:slug`) and the auth callback route to work correctly.

## Google OAuth Setup

In Google Cloud Console:

1. Create an OAuth 2.0 web client.
2. Add the frontend origin to authorized JavaScript origins.
3. Add the **frontend** callback URL to authorized redirect URIs (`{FRONTEND_URL}/auth/callback`). Google redirects back to the frontend, which then exchanges the code with the backend. Do not use the backend URL here.
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in backend secrets.

For local development, the expected frontend origin is:

```text
http://localhost:5173
```

The local redirect URI to register in Google Console:

```text
http://localhost:5173/auth/callback
```

## GitHub Export Setup

The GitHub export integration lets users push their delivery package to a GitHub repository. It is optional and disabled by default when `GITHUB_CLIENT_ID` is blank.

To enable it:

1. In GitHub → **Settings** → **Developer settings** → **OAuth Apps** → **New OAuth App**.
2. Set the **Authorization callback URL** to `{FRONTEND_URL}/integrations/github/callback`.
3. Copy the **Client ID** and generate a **Client Secret**.
4. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in backend secrets.

When `GITHUB_CLIENT_ID` is blank, the backend returns 503 for all GitHub integration routes and the frontend omits the GitHub export option. No partial configuration is needed to disable the feature.

## Observability

Available endpoints:

```text
GET /health
GET /metrics
```

Optional integrations:

- Backend Sentry through `SENTRY_DSN`.
- Frontend Sentry through `VITE_SENTRY_DSN`.
- OTLP tracing through `GRAFANA_OTLP_ENDPOINT` and `GRAFANA_OTLP_TOKEN`.
- Prometheus scraping through `/metrics`. Protect with `METRICS_TOKEN` in production.
- LLM-call observability through Langfuse (`LANGFUSE_SECRET_KEY`,
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`). With `LANGFUSE_SECRET_KEY` blank the
  Langfuse SDK is never imported and the application behaves identically to a
  build without Langfuse. No user-facing feature depends on Langfuse availability.

Provider-agnostic LLM cost metrics are emitted for instrumented calls:

- `llm_request_total{provider,model_tier,operation,stage_type,cache_hit}`
- `llm_estimated_cost_usd_total{provider,model_tier,operation,stage_type}`
- `llm_input_tokens_total{provider,model_tier,operation,stage_type,method}`
- `llm_output_tokens_total{provider,model_tier,operation,stage_type,method}`
- `llm_cached_input_tokens_total{provider,model_tier,operation,stage_type}`
- `llm_latency_seconds_bucket{provider,model_tier,operation,stage_type}`
- `llm_cross_provider_fallback_total{provider,model_tier,operation,stage_type}`

Suggested alerts:

- P95 LLM request cost rises above the provider/tier baseline.
- Output tokens approach or exceed the operation budget.
- Cache-hit ratio drops unexpectedly for repeated stage operations.
- Any cross-provider fallback occurs outside an approved rollout window.

Optional LLM observability via Langfuse:

- Set `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST` to
  enable per-generation trace, prompt-version, and eval-score capture.
- In production, also set `LANGFUSE_CONTENT_CAPTURE_ACK=true` after approving
  that prompts and model outputs may be sent to Langfuse after secret-shaped
  redaction.
- Run a self-hosted Langfuse locally with
  `docker compose --profile langfuse up`.
- Without these variables set, the application runs identically with zero
  Langfuse traffic. No user-facing feature depends on Langfuse availability.

Sensitive values are redacted before they are emitted through logging, Sentry, or Langfuse paths.

## Operational Notes

- Keep `backend/.env` and `frontend/.env` out of Git.
- Rotate provider keys and OAuth secrets regularly.
- Back up PostgreSQL before running migrations in production.
- Use Redis persistence or managed Redis if session durability matters.
- Do not deploy with placeholder JWT, CSRF, or encryption secrets.
- Do not commit `node_modules`, local caches, or generated test artifacts.
- Set `METRICS_TOKEN` in production to prevent unauthenticated metric scraping.
- Leave `GITHUB_CLIENT_ID` blank if you do not want to expose the GitHub export feature.

## Troubleshooting

Google sign-in does not start:

- Confirm `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
- Confirm the backend can reach Google OAuth endpoints.
- Confirm `FRONTEND_URL` matches the browser origin.
- Check backend logs for OAuth redirect errors.

Frontend cannot call the API:

- Confirm `VITE_API_URL`.
- Confirm the API is reachable at `/health`.
- Confirm CORS/frontend origin configuration.

Streaming generation fails:

- Confirm the selected LLM provider has a valid API key.
- Confirm Redis and PostgreSQL are reachable.
- Check rate limit and credit balance behavior.

CSRF failures:

- Ensure the frontend is using the API client that fetches `/auth/csrf-token`.
- Ensure access tokens are present in memory after authentication.
- Avoid manually calling mutating endpoints without `X-CSRF-Token`.

PDF export fails:

- Confirm the backend image includes the WeasyPrint native libraries (`libcairo2`, `libpango-1.0-0`, `libpangoft2-1.0-0`).
- Check backend logs for WeasyPrint rendering errors.

GitHub export returns 503:

- Confirm `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are set in the backend environment.
- Both variables must be non-blank to enable the integration.

Large frontend build warning:

- Vite may warn that a chunk exceeds 500 kB. The current build still succeeds. Route-level code splitting can address this later.

## License

No license file is currently included. Add one before distributing or accepting external contributions.
