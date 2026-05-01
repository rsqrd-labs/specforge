# SpecForge

SpecForge turns a plain-English software idea into a four-stage, testable build package:

```text
Problem Statement
      |
      v
SPEC.md -> PLAN.md -> HARNESS -> TASKS.md
```

The app combines a FastAPI backend, React workspace UI, streaming LLM generation, credit accounting, online evals, and exportable project artifacts.

## Self-Hosting

1. Clone the repository.

   ```bash
   git clone https://github.com/rsqrd-labs/specforge.git
   cd specforge
   ```

2. Create the backend environment file and fill in real secrets.

   ```bash
   cp backend/.env.example backend/.env
   ```

3. Start the stack.

   ```bash
   docker compose up --build
   ```

4. Open the app.

   ```text
   http://localhost:5173
   ```

The compose stack starts PostgreSQL, Redis, the FastAPI API on `localhost:8000`, and the Vite frontend on `localhost:5173`.

## Development Setup

Backend:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev
```

Default local URLs:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:8000
Health:   http://localhost:8000/health
Metrics:  http://localhost:8000/metrics
```

## Environment Variables

Backend variables live in `backend/.env`.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Async PostgreSQL URL. Compose overrides this to use the `db` service. |
| `REDIS_URL` | Redis URL. Compose overrides this to use the `redis` service. |
| `JWT_PRIVATE_KEY` | RS256 private key for access and refresh tokens. |
| `JWT_PUBLIC_KEY` | RS256 public key for token verification. |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret. |
| `FRONTEND_URL` | Public frontend origin for CORS and OAuth redirects. |
| `ANTHROPIC_API_KEY` | Anthropic provider key. |
| `OPENAI_API_KEY` | OpenAI provider key. |
| `GOOGLE_API_KEY` | Google Gemini provider key. |
| `ENCRYPTION_MASTER_KEY` | Fernet-compatible master key for encrypted secrets. |
| `CSRF_SECRET` | HMAC secret for CSRF tokens. |
| `SENTRY_DSN` | Optional backend Sentry DSN. |
| `GRAFANA_OTLP_ENDPOINT` | Optional OTLP trace endpoint. |
| `GRAFANA_OTLP_TOKEN` | Optional OTLP auth token. |
| `ENVIRONMENT` | Runtime environment name. |

Frontend variables live in `frontend/.env.example` for local development.

| Variable | Purpose |
| --- | --- |
| `VITE_API_URL` | Browser-facing backend URL. |
| `VITE_SENTRY_DSN` | Optional frontend Sentry DSN. |

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
```

Manual staging validation lives in `docs/SMOKE_TEST_CHECKLIST.md`.
