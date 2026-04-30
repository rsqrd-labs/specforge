# SpecForge Handoff

Date: 2026-04-29

## Current State

Work has been completed and pushed through T-010 in `tasks.md`.

Current branch:

```bash
main
```

Current remote state when this file was written:

```bash
940efa6 origin/main Add auth middleware dependency
```

Working tree was clean before this handoff file was created.

## Completed Tasks

- T-001: Initialized monorepo structure.
- T-002: Set up backend Python project with `uv`, Python 3.12, dependencies, and env example.
- T-003: Added backend config, async DB session, FastAPI app factory, and `/health`.
- T-004: Set up Vite React TypeScript frontend with Tailwind config.
- T-005: Added frontend shared TypeScript types and Axios API service foundation.
- T-006: Added SQLAlchemy ORM models.
- T-007: Added Alembic config and initial schema migration.
- T-008: Added backend Pydantic schemas.
- T-009: Added auth service with Google OAuth flow, RS256 JWTs, refresh rotation, Redis session tracking, and signup credit stub.
- T-010: Added auth middleware/dependencies for protected and optional user loading.

## Recent Commits

```bash
940efa6 Add auth middleware dependency
a7e64c5 Add auth service
c0b33df Add backend Pydantic schemas
cdfd1a7 Add initial Alembic migration
6121e87 Add SQLAlchemy data models
037b39a Add frontend API and shared types
6504d12 Set up frontend Vite project
4efbf9c Add backend app factory and health check
9618d8b Set up backend Python project
3aa7fbd Initialize monorepo structure
fe3eed9 Add SpecForge implementation harness
```

## Verification Already Run

Backend:

```bash
cd backend
uv sync
uv run python --version
uv run python -c "import fastapi, sqlalchemy, redis, anthropic"
uv run ruff check .
uv run black --check .
uv run pytest
```

Latest backend test result:

```bash
8 passed
```

Database and migrations:

```bash
docker compose up -d db redis
docker compose ps
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run alembic current
```

Latest Alembic state:

```bash
0001 (head)
```

Frontend:

```bash
cd frontend
pnpm install
pnpm tsc --noEmit
pnpm dev
```

Vite served the placeholder app on `127.0.0.1:5173` and rendered `SpecForge`.

## Local Tooling Notes

- `uv` was installed with Homebrew.
- `pnpm@9.15.9` was enabled through Corepack.
- Docker Desktop was opened and the Compose services were verified healthy.
- `backend/.env` exists locally and is intentionally ignored by Git.
- `frontend/node_modules/`, Python `__pycache__/`, and `.venv/` are ignored.

Local `backend/.env` used for verification points at Docker:

```bash
DATABASE_URL=postgresql+asyncpg://specforge:specforge@localhost:5432/specforge
REDIS_URL=redis://localhost:6379/0
```

Other secrets in local `.env` are placeholders. Do not commit `.env`.

## Important Implementation Notes

- The canonical pipeline order is `spec -> plan -> harness -> tasks`.
- The actual agentic harness is a directory at `harness/`, not a markdown file.
- Read `harness/instructions.txt` and `harness/manifest.json` before continuing.
- T-005 includes a conservative token approach: it can read an existing `localStorage` access token for bootstrap compatibility, but refreshed tokens are stored in module memory and are not written back to browser storage.
- T-008 uses `email: str` instead of Pydantic `EmailStr` because `email-validator` is not in the approved backend dependency list.
- T-009 added `backend/services/credit_service.py` as a narrow signup-credit stub because the full credit service is scheduled later.

## Next Task

Pick up with T-011: Auth Router.

Expected outputs:

- `backend/routers/auth.py`
- Update `backend/main.py` to include the auth router.

Task summary:

- `POST /auth/google` returns a Google redirect URL.
- `GET /auth/callback` exchanges code and sets refresh-token cookie.
- `POST /auth/refresh` rotates refresh token and returns a new access token.
- `POST /auth/logout` revokes and clears refresh cookie.
- `GET /auth/me` uses `get_current_user` and returns `UserResponse`.

Known dependency gap:

- `credit_service.get_balance(user.id)` is referenced by T-011, but the full credit service is later. Either add a minimal `get_balance` method to the current stub or keep the router implementation narrowly compatible with the future T-018 service.

Suggested verification after T-011:

```bash
cd backend
uv run pytest
uv run ruff check .
uv run black --check .
uv run uvicorn main:app --reload
curl -s http://127.0.0.1:8000/health
```

## Stop Point

No in-progress command should be running. The last completed task was T-010. The next engineer or agent can continue directly from T-011.
