# Integration & API Setup Handbook

## 1. Overview of Required Services

SpecForge is a React/Vite frontend plus FastAPI backend that turns a user
problem statement into a staged AI workflow:

```text
SPEC -> PLAN -> HARNESS -> TASKS
```

Runtime configuration is loaded from:

- Backend: `backend/.env`, parsed by `backend/config.py`
- Frontend: `frontend/.env`, consumed by Vite
- Local Docker overrides: `docker-compose.yml`
- Production deployment secrets: Railway, Vercel, and GitHub Actions

Required runtime integrations:

| Service | Required? | Purpose | Main code paths |
| --- | --- | --- | --- |
| PostgreSQL | Yes | Primary relational DB | `backend/database.py`, `backend/models/*`, `backend/migrations/*` |
| Redis | Yes | OAuth state, refresh sessions, rate limits, cache, recovery lock | `backend/services/auth_service.py`, `backend/middleware/rate_limit.py`, `backend/services/pipeline/stage_manager.py` |
| Google OAuth | Yes | User sign-in | `backend/services/auth_service.py`, `backend/routers/auth.py`, `frontend/src/pages/Landing.tsx`, `frontend/src/pages/AuthCallback.tsx` |
| Anthropic | Yes for Anthropic provider | LLM generation/evaluation | `backend/services/llm/anthropic_adapter.py`, `backend/services/llm/gateway.py` |
| OpenAI | Yes for OpenAI provider | LLM generation/evaluation | `backend/services/llm/openai_adapter.py` |
| Google Gemini | Yes for Google provider | LLM generation/evaluation | `backend/services/llm/google_adapter.py` |
| Sentry | Optional | Backend/frontend error reporting | `backend/services/observability.py`, `frontend/src/main.tsx` |
| Grafana OTLP | Optional | Distributed tracing | `backend/services/observability.py` |
| Prometheus-compatible metrics | Built in | `/metrics` endpoint | `backend/services/observability.py` |
| Railway | Production backend deploy | API, Postgres, Redis hosting | `.github/workflows/ci.yml` |
| Vercel | Production frontend deploy | Static frontend hosting | `.github/workflows/ci.yml` |
| GitHub Actions secrets | Production CI/CD | Deploy and smoke credentials | `.github/workflows/ci.yml`, `.github/workflows/production-smoke.yml` |

Installed but not currently wired into runtime credentials:

- `stripe`, `@stripe/stripe-js`: dependencies exist, but no Stripe environment
  variables are consumed by `backend/config.py`.
- `resend`: dependency exists, but no Resend environment variables are consumed.
- `supabase`: dependency exists, but no Supabase environment variables are
  consumed.

## 2. API Setup Service-by-Service

### PostgreSQL

Purpose: primary database for users, workspaces, stages, credit ledger, versions,
and evals.

Used in:

- `backend/database.py`
- `backend/models/*.py`
- `backend/migrations/versions/*.py`
- `backend/routers/*`
- `backend/services/*`

Required setting:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB_NAME
```

Local Docker value is supplied by `docker-compose.yml`:

```env
DATABASE_URL=postgresql+asyncpg://specforge:specforge@db:5432/specforge
```

How to obtain production credentials:

1. Create a managed PostgreSQL database. Railway Postgres is already implied by
   the CI/deploy flow. Railway docs: https://docs.railway.com/guides/postgresql
2. In Railway, add a PostgreSQL service to the project.
3. Copy the private/internal connection URL for the backend service.
4. Ensure it uses the async SQLAlchemy driver prefix in SpecForge:
   `postgresql+asyncpg://...`

Validation:

```bash
cd backend
uv run alembic upgrade head
uv run python - <<'PY'
from database import async_engine
import asyncio
from sqlalchemy import text

async def main():
    async with async_engine.connect() as c:
        print((await c.execute(text("SELECT 1"))).scalar())

asyncio.run(main())
PY
```

Common errors:

- `No module named asyncpg`: run `uv sync`.
- Connection refused: wrong host/port or DB is not running.
- `password authentication failed`: wrong database password.
- Migration failure: run from `backend/` and verify `DATABASE_URL`.

### Redis

Purpose: OAuth state storage, refresh-token session store, rate limiting, stage
cache, credit balance cache, and stuck-stage recovery lock.

Used in:

- `backend/services/auth_service.py`
- `backend/middleware/rate_limit.py`
- `backend/services/pipeline/stage_manager.py`
- `backend/services/pipeline/prompt_builder.py`
- `backend/services/pipeline/recovery_service.py`
- `backend/services/credit_service.py`
- `backend/main.py`

Required setting:

```env
REDIS_URL=redis://HOST:PORT/0
```

Use `rediss://...` for managed TLS Redis if your provider requires TLS.

Local Docker value:

```env
REDIS_URL=redis://redis:6379/0
```

How to obtain production credentials:

1. Create a managed Redis instance. Railway Redis docs:
   https://docs.railway.com/databases/redis
2. Copy the internal/private Redis URL into Railway backend variables.
3. Prefer private networking between API and Redis.

Validation:

```bash
redis-cli -u "$REDIS_URL" ping
```

Expected:

```text
PONG
```

Common errors:

- `/health` returns degraded: Redis is unreachable or URL is wrong.
- Login callback fails with OAuth state error: Redis may not be storing OAuth
  state.
- Rate limits behave oddly: check Redis connectivity and backend logs for
  `rate_limit.redis_unavailable_fallback`.

### Google OAuth

Purpose: user login. The backend starts the OAuth flow; Google redirects back to
the frontend `/auth/callback`; the frontend then calls backend `/auth/callback`.

Used in:

- `backend/services/auth_service.py`
- `backend/routers/auth.py`
- `frontend/src/pages/Landing.tsx`
- `frontend/src/pages/AuthCallback.tsx`

Required settings:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
FRONTEND_URL=http://localhost:5173
```

Official Google OAuth docs:
https://developers.google.com/identity/protocols/oauth2/web-server

How to get credentials:

1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Create or select a project.
3. Configure the OAuth consent screen.
4. Create an OAuth Client ID.
5. Application type: `Web application`.
6. Add Authorized JavaScript origins:
   - Local: `http://localhost:5173`
   - Production: `https://your-frontend-domain`
7. Add Authorized redirect URIs:
   - Local: `http://localhost:5173/auth/callback`
   - Production: `https://your-frontend-domain/auth/callback`
8. Copy client ID and secret into backend env.

Important repo-specific detail: `backend/services/auth_service.py` sets the
OAuth redirect URI to:

```python
f"{settings.frontend_url.rstrip('/')}/auth/callback"
```

So the Google redirect URI must be the frontend callback URL, not
`/auth/callback` on the backend.

Validation:

1. Start backend and frontend.
2. Visit `http://localhost:5173`.
3. Click `Sign in with Google`.
4. After consent, the browser should land on `/dashboard`.
5. Backend should create/update a `User` row and issue a refresh cookie.

Common errors:

- `redirect_uri_mismatch`: Google Console redirect URI does not exactly match
  `FRONTEND_URL/auth/callback`.
- “Google sign-in failed”: check backend logs, `GOOGLE_CLIENT_SECRET`, and
  `FRONTEND_URL`.
- OAuth state error: Redis is down or state expired.

### Anthropic

Purpose: Anthropic model generation/evaluation.

Used in:

- `backend/services/llm/anthropic_adapter.py`
- `backend/services/llm/provider_config.py`
- `backend/services/llm/gateway.py`

Required setting:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

Official console/docs:

- https://console.anthropic.com/
- https://docs.anthropic.com/

How to get credentials:

1. Create/log into an Anthropic Console account.
2. Enable billing/usage as required.
3. Create an API key in the Console.
4. Copy it into `backend/.env` or Railway backend variables.

Validation:

1. Start the app.
2. Create a workspace using provider `anthropic`.
3. Generate SPEC.
4. Expected: SSE token stream appears; credit balance decreases by 10.

Common errors:

- Provider error in SSE stream: invalid key, model unavailable, rate limit, or
  billing issue.
- Model mismatch: check allowed Anthropic model IDs in
  `backend/services/llm/provider_config.py`.

### OpenAI

Purpose: OpenAI model generation/evaluation.

Used in:

- `backend/services/llm/openai_adapter.py`
- `backend/services/llm/provider_config.py`
- `backend/services/llm/gateway.py`

Required setting:

```env
OPENAI_API_KEY=sk-...
```

Official setup docs:

- https://platform.openai.com/docs/quickstart
- https://help.openai.com/en/articles/4936850-how-to-create-and-use-an-api-key

How to get credentials:

1. Go to https://platform.openai.com/
2. Create or select a project.
3. Ensure billing and usage limits are configured.
4. Create an API key.
5. Store it only in backend environment variables.

Validation:

1. Create a workspace with provider `openai`.
2. Select an allowed model from `backend/services/llm/provider_config.py`.
3. Generate SPEC.

Common errors:

- `401`: wrong key or key revoked.
- `429`: rate limit or quota exhaustion.
- Empty/failed stream: inspect backend logs for `ProviderError("openai", ...)`.

### Google Gemini

Purpose: Gemini model generation/evaluation.

Used in:

- `backend/services/llm/google_adapter.py`
- `backend/services/llm/provider_config.py`
- `backend/services/llm/gateway.py`

Required setting:

```env
GOOGLE_API_KEY=...
```

Official Gemini API key docs:

- https://ai.google.dev/gemini-api/docs/api-key
- https://ai.google.dev/aistudio

How to get credentials:

1. Go to Google AI Studio.
2. Create/select a Google Cloud project.
3. Generate a Gemini API key.
4. Enable billing/quota controls for production.
5. Put the key in backend environment only.

Validation:

1. Create a workspace with provider `google`.
2. Select `gemini-1.5-pro`, `gemini-1.5-flash`, or `gemini-2.0-flash` as
   configured.
3. Generate SPEC.

Common errors:

- Key works in AI Studio but not app: confirm the key belongs to the same project
  and Gemini API access is enabled.
- Large bill risk: set quota/billing alerts; never expose `GOOGLE_API_KEY` to
  the frontend.

### Sentry

Purpose: optional backend and frontend error reporting.

Used in:

- Backend: `backend/services/observability.py`
- Frontend: `frontend/src/main.tsx`

Required settings:

```env
SENTRY_DSN=https://...
VITE_SENTRY_DSN=https://...
```

Official docs:

- https://docs.sentry.io/
- https://sentry.zendesk.com/hc/en-us/articles/17407166516635-Sentry-DSN-Data-Source-Name

How to get credentials:

1. Create a Sentry organization/project.
2. Create one backend project and optionally one frontend project.
3. Copy each project DSN.
4. Set backend `SENTRY_DSN`.
5. Set frontend `VITE_SENTRY_DSN`.

Validation:

- Backend starts without Sentry if unset.
- Frontend builds without Sentry if unset.
- With DSN set, force an error in staging and confirm a Sentry event arrives.

Common errors:

- No events: DSN missing, environment blocked, ad blocker for frontend, or Sentry
  project mismatch.
- Sensitive data: this repo redacts common secrets in
  `backend/services/observability.py`.

### Grafana OTLP / OpenTelemetry

Purpose: optional distributed tracing.

Used in:

- `backend/services/observability.py`

Required settings:

```env
GRAFANA_OTLP_ENDPOINT=https://...
GRAFANA_OTLP_TOKEN=...
```

Official Grafana OTLP docs: https://grafana.com/docs/grafana-cloud/send-data/otlp/

How to get credentials:

1. Create/log into Grafana Cloud.
2. Open OpenTelemetry / OTLP integration.
3. Copy the OTLP endpoint.
4. Generate an access token with telemetry ingest permissions.
5. Configure backend env.

Validation:

1. Set `GRAFANA_OTLP_ENDPOINT`.
2. Set `GRAFANA_OTLP_TOKEN` if the endpoint requires bearer auth.
3. Start backend and make API requests.
4. Confirm traces in Grafana Cloud.

Common errors:

- No traces: endpoint wrong, token missing, or outbound traffic blocked.
- Backend still starts if these vars are empty by design.

### Prometheus Metrics

Purpose: internal metrics endpoint at `/metrics`.

Used in:

- `backend/services/observability.py`
- `scripts/production_smoke.py`

Required production token:

```env
METRICS_TOKEN=long-random-token
```

Generate:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Validation:

```bash
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/metrics
```

Expected output includes:

```text
http_requests_total
```

Production rule: `backend/config.py` rejects production startup if
`METRICS_TOKEN` is empty.

### Railway

Purpose: backend/API deployment and likely managed PostgreSQL/Redis hosting.

Used in:

- `.github/workflows/ci.yml`
- `docker-compose.yml` for local analog

Required GitHub secret:

```text
RAILWAY_TOKEN
```

Official Railway docs: https://docs.railway.com/

How to get credentials:

1. Create Railway account and project.
2. Add backend service.
3. Add PostgreSQL and Redis services.
4. In Railway service variables, set all backend env vars from section 3.
5. Generate Railway token from Railway account/project settings.
6. Add it to GitHub repository secrets as `RAILWAY_TOKEN`.

Validation:

- Push to `main`.
- GitHub Actions `Deploy backend to Railway` should pass.
- Visit backend `/health`.

### Vercel

Purpose: frontend deployment.

Used in:

- `.github/workflows/ci.yml`

Required GitHub secrets:

```text
VERCEL_TOKEN
VERCEL_ORG_ID
VERCEL_PROJECT_ID
```

Required Vercel env vars:

```env
VITE_API_URL=https://your-api-domain
VITE_SENTRY_DSN=https://... # optional
```

Official Vercel docs:

- https://vercel.com/docs/projects/environment-variables
- https://vercel.com/docs/cli

How to get credentials:

1. Create/import project in Vercel.
2. Set project root to `frontend` if deploying from this monorepo.
3. Add frontend env vars in Vercel Project Settings.
4. Create a Vercel token from account settings.
5. Get org/team ID and project ID from Vercel project settings or
   `.vercel/project.json`.
6. Add GitHub secrets.

Validation:

- GitHub Actions deploy step succeeds.
- Open frontend URL.
- Browser can call `${VITE_API_URL}/health`.

### GitHub Actions Production Smoke

Purpose: live post-deploy smoke test.

Used in:

- `.github/workflows/production-smoke.yml`
- `scripts/production_smoke.py`

Required GitHub secrets:

```text
SPECFORGE_SMOKE_ACCESS_TOKEN
SPECFORGE_METRICS_TOKEN
```

How to obtain `SPECFORGE_SMOKE_ACCESS_TOKEN`:

1. Create or designate a smoke-test Google account.
2. Sign into the deployed frontend.
3. In browser DevTools Network tab, inspect the backend `/auth/callback`
   response.
4. Copy the short-lived `access_token`.
5. Store temporarily as `SPECFORGE_SMOKE_ACCESS_TOKEN` before running the smoke
   workflow.

Because access tokens are short-lived, refresh this secret immediately before a
production smoke run.

Run manually from GitHub Actions:

1. Open Actions.
2. Select `Production Smoke`.
3. Enter API URL.
4. Enable `run_llm_smoke` if you want a live paid LLM generation check.
5. Run workflow.

## 3. Environment Configuration

Backend file:

```bash
cp backend/.env.example backend/.env
```

Frontend file:

```bash
cp frontend/.env.example frontend/.env
```

Minimum local backend `.env`:

```env
DATABASE_URL=postgresql+asyncpg://specforge:specforge@localhost:5432/specforge
REDIS_URL=redis://localhost:6379/0

JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"

GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
FRONTEND_URL=http://localhost:5173

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

ENCRYPTION_MASTER_KEY=your-fernet-key
CSRF_SECRET=long-random-secret

METRICS_TOKEN=
SENTRY_DSN=
GRAFANA_OTLP_ENDPOINT=
GRAFANA_OTLP_TOKEN=

ENVIRONMENT=development
MAX_ACTIVE_WORKSPACES_PER_USER=50
```

Frontend `.env`:

```env
VITE_API_URL=http://localhost:8000
VITE_SENTRY_DSN=
```

Generate JWT keys:

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

Convert PEMs to `.env`-friendly escaped values:

```bash
python3 - <<'PY'
from pathlib import Path

for name, file in [
    ("JWT_PRIVATE_KEY", "jwt_private.pem"),
    ("JWT_PUBLIC_KEY", "jwt_public.pem"),
]:
    value = Path(file).read_text().replace("\n", "\\n")
    print(f'{name}="{value}"')
PY
```

Generate Fernet encryption key:

```bash
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generate CSRF and metrics secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Production-only requirements enforced by `backend/config.py`:

- `ENVIRONMENT=production`
- `METRICS_TOKEN` must be set.
- `FRONTEND_URL` must be HTTPS.
- `JWT_PRIVATE_KEY` must be a real PEM key.
- `ENCRYPTION_MASTER_KEY` must not be the CI placeholder.

## 4. End-to-End Test Guide

### Local Setup

1. Install tooling:

```bash
pip install uv
corepack enable
```

1. Create env files:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

1. Fill all backend keys listed above.

1. Start everything with Docker:

```bash
docker compose up --build
```

1. Apply migrations if running backend manually:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

1. Run frontend manually if not using Docker:

```bash
cd frontend
pnpm install
pnpm dev
```

### Basic Validation

Backend health:

```bash
curl http://localhost:8000/health
```

Expected in development:

```json
{"status":"ok","version":"1.0.0","db":"ok","redis":"ok"}
```

Provider catalog:

```bash
curl http://localhost:8000/providers
```

Expected: providers array containing `anthropic`, `openai`, and `google`.

Metrics:

```bash
curl http://localhost:8000/metrics
```

In development from localhost this should return Prometheus text. In production
use:

```bash
curl -H "Authorization: Bearer $METRICS_TOKEN" https://api.example.com/metrics
```

### Browser Workflow

1. Open `http://localhost:5173`.
2. Click `Sign in with Google`.
3. Complete Google OAuth.
4. Expect redirect to `/dashboard`.
5. Confirm user has 50 starter credits.
6. Create a workspace:
   - Name: `Smoke Workspace`
   - Problem statement: at least 50 characters
   - Provider: choose one with a valid key
   - Model: choose a model listed in the UI
7. Open SPEC stage.
8. Click Generate.
9. Confirm:
   - token stream appears
   - SPEC becomes draft
   - quality/eval appears
   - credits decrease by 10
10. Finalise SPEC.
11. Confirm PLAN unlocks.

### Automated Production Smoke

From repo root:

```bash
SPECFORGE_API_URL=https://api.example.com \
SPECFORGE_ACCESS_TOKEN=short-lived-smoke-access-token \
SPECFORGE_METRICS_TOKEN=your-metrics-token \
SPECFORGE_RUN_LLM_SMOKE=1 \
python3 scripts/production_smoke.py
```

Expected:

```text
[smoke] health
[smoke] provider catalog
[smoke] metrics
[smoke] authenticated user
[smoke] credit balance
[smoke] workspace persistence
[smoke] live LLM stream
[smoke] workspace archive
[smoke] production smoke passed
```

## 5. Troubleshooting Guide

### Backend fails at startup

Check:

```bash
cd backend
uv run python -c "from config import settings; print(settings.environment)"
```

Common causes:

- Missing required env var.
- Invalid `JWT_PRIVATE_KEY` formatting.
- `ENVIRONMENT=production` with non-HTTPS `FRONTEND_URL`.
- `ENVIRONMENT=production` without `METRICS_TOKEN`.
- Invalid Fernet `ENCRYPTION_MASTER_KEY`.

### Google sign-in fails

Check:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `FRONTEND_URL`
- Google OAuth redirect URI exactly equals `FRONTEND_URL/auth/callback`
- Redis is reachable for OAuth state storage
- Browser URL includes both `code` and `state` on `/auth/callback`

### Frontend cannot call API

Check:

- `frontend/.env`: `VITE_API_URL=http://localhost:8000`
- Backend CORS uses `FRONTEND_URL`
- `curl http://localhost:8000/health`
- Browser console/network tab for CORS or 401 errors

### CSRF failures

Symptoms: mutating requests return `403`.

Fix:

- Ensure frontend has a valid access token.
- Ensure frontend can call `GET /auth/csrf-token`.
- Do not manually POST without `X-CSRF-Token`.
- Confirm `CSRF_SECRET` is stable across backend restarts.

### LLM generation fails

Check:

- Correct provider API key.
- Provider billing/quota.
- Model is allowed in `backend/services/llm/provider_config.py`.
- Redis and Postgres are healthy.
- Backend logs for `ProviderError`.

### Redis problems

Symptoms:

- `/health` degraded.
- OAuth state failures.
- Rate limiter logs fallback warning.
- Stage cache/recovery issues.

Check:

```bash
redis-cli -u "$REDIS_URL" ping
```

### Database problems

Check:

```bash
cd backend
uv run alembic current
uv run alembic upgrade head
```

If migrations fail, verify `DATABASE_URL` and that Postgres has required
permissions.

### Sentry or Grafana not receiving data

Check:

- DSN/endpoint starts with `http://` or `https://`.
- Token is present for Grafana OTLP if required.
- Outbound network access from backend is allowed.
- `SENTRY_DSN` is backend-only; `VITE_SENTRY_DSN` is frontend build-time.

### Deployment failures

Railway:

- Verify `RAILWAY_TOKEN` GitHub secret.
- Verify backend service exists and name matches workflow.
- Verify Railway env vars include all backend required vars.

Vercel:

- Verify `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.
- Verify Vercel project has `VITE_API_URL`.
- Rebuild frontend after changing Vite env vars.

### Secret safety

Never commit:

- `backend/.env`
- `frontend/.env`
- JWT PEM files
- API keys
- Railway/Vercel/GitHub tokens

CI runs TruffleHog with verified secret detection in `.github/workflows/ci.yml`,
but do not rely on CI as the first line of defense.
