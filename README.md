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
- Workspace creation from a problem statement.
- Streaming AI generation for `SPEC.md`, `PLAN.md`, harness coverage, and `tasks.md`.
- Human review gates between stages.
- Stage refinement with diff preview and accept/reject flow.
- Credit accounting for generation and accepted refinements.
- Provider-aware LLM routing for Anthropic, OpenAI, and Google.
- Online evaluation and quality indicators for generated stages.
- Exportable delivery artifacts for handoff to engineers or coding agents.

## Product Flow

1. User signs in with Google.
2. User creates a workspace with a product/problem statement.
3. SpecForge generates the stages in order:
   - `Spec`: requirements, users, journeys, constraints, and acceptance criteria.
   - `Plan`: architecture, implementation strategy, risks, and sequencing.
   - `Harness`: validation assets and coverage expectations.
   - `Tasks`: traceable work items ready for execution.
4. User reviews, refines, accepts, and exports the package.

## Architecture

SpecForge is a full-stack web application with a React frontend, FastAPI backend, PostgreSQL persistence, Redis-backed session/rate-limit state, and pluggable LLM providers.

```text
Browser
  |
  | React + Vite frontend
  v
FastAPI API
  |
  |-- PostgreSQL: users, workspaces, stages, credits, evals
  |-- Redis: refresh sessions, rate limits, transient auth state
  |-- LLM gateway: Anthropic, OpenAI, Google Gemini
  |-- Observability: Prometheus metrics, Sentry, optional OTLP
```

Important backend areas:

- `backend/routers`: HTTP API routes for auth, workspaces, stages, credits, and providers.
- `backend/services/pipeline`: stage generation, diffing, exports, prompt building, and recovery.
- `backend/services/llm`: provider adapters and routing.
- `backend/services/evals`: online evaluation and quality scoring.
- `backend/services/security`: CSRF, prompt guard, output validator, sanitizer, and encrypted key handling.
- `backend/middleware`: rate limiting and CSRF enforcement.
- `backend/migrations`: Alembic database migrations.

Important frontend areas:

- `frontend/src/pages`: landing, auth callback, dashboard, and workspace screens.
- `frontend/src/components/workspace`: stage editor, navigator, streaming overlay, review gates, diff viewer, and validation panels.
- `frontend/src/services`: API and streaming clients.
- `frontend/src/store`: Zustand stores for user, workspace, and stage state.
- `frontend/src/types`: shared frontend TypeScript types.

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
- Structlog, Prometheus, Sentry, and OpenTelemetry
- Pytest, Ruff, Black, Bandit, Safety

Frontend:

- React 18
- TypeScript
- Vite
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
| `ANTHROPIC_API_KEY` | Anthropic API key. |
| `OPENAI_API_KEY` | OpenAI API key. |
| `GOOGLE_API_KEY` | Google Gemini API key. |
| `ENCRYPTION_MASTER_KEY` | Fernet-compatible key for encrypted secrets. |
| `CSRF_SECRET` | HMAC secret for CSRF token signing. |
| `SENTRY_DSN` | Optional backend Sentry DSN. |
| `GRAFANA_OTLP_ENDPOINT` | Optional OTLP trace endpoint. |
| `GRAFANA_OTLP_TOKEN` | Optional OTLP auth token. |
| `ENVIRONMENT` | Runtime environment name, for example `development` or `production`. |

### Frontend Variables

| Variable | Purpose |
| --- | --- |
| `VITE_API_URL` | Browser-facing backend URL. |
| `VITE_SENTRY_DSN` | Optional frontend Sentry DSN. |

## Local Development With Docker

This is the fastest way to run the whole app locally.

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

Landing page targeted check:

```bash
cd frontend
pnpm vitest run src/__tests__/Landing.test.tsx
```

Smoke-test guidance:

```text
docs/SMOKE_TEST_CHECKLIST.md
```

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

Production deployments should also enforce HTTPS, secure cookies, strict CORS, strong secrets, provider key rotation, and database backups.

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

## Backend Container Deployment

Build:

```bash
docker build -t specforge-api ./backend
```

Run migrations against the production database:

```bash
docker run --rm \
  --env-file backend/.env \
  specforge-api \
  uv run --no-sync alembic upgrade head
```

Run API:

```bash
docker run --rm \
  --env-file backend/.env \
  -p 8000:8000 \
  specforge-api
```

The Dockerfile starts Gunicorn with Uvicorn workers:

```text
gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:8000
```

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

For single-page app hosting, configure fallback routing so all unknown paths serve `index.html`.

## Google OAuth Setup

In Google Cloud Console:

1. Create an OAuth 2.0 web client.
2. Add the frontend origin to authorized JavaScript origins.
3. Add the backend callback URL to authorized redirect URIs.
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in backend secrets.

For local development, the expected frontend origin is:

```text
http://localhost:5173
```

The backend callback route is implemented by the auth router. Match the deployed callback URL to the route configured in the backend.

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
- Prometheus scraping through `/metrics`.

Sensitive values are redacted before they are emitted through logging and Sentry paths.

## Operational Notes

- Keep `backend/.env` and `frontend/.env` out of Git.
- Rotate provider keys and OAuth secrets regularly.
- Back up PostgreSQL before running migrations in production.
- Use Redis persistence or managed Redis if session durability matters.
- Do not deploy with placeholder JWT, CSRF, or encryption secrets.
- Do not commit `node_modules`, local caches, or generated test artifacts.

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

Large frontend build warning:

- Vite may warn that a chunk exceeds 500 kB. The current build still succeeds. Route-level code splitting can address this later.

## License

No license file is currently included. Add one before distributing or accepting external contributions.
