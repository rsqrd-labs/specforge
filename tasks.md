# SpecForge V1 — tasks.md

> Execution plan for SpecForge V1. Tasks are strictly ordered. Every task is atomic and completable in one iteration. Read `harness/instructions.txt` and `harness/manifest.json` before executing any task.

---

## Phase 1 — Core Pipeline

---

### T-001: Initialize Monorepo Structure

**Description:**
Create the root repository layout, top-level configuration files, and empty directory skeletons for backend and frontend. No code yet — structure only.

**Inputs:**
- `harness/manifest.json`
- `harness/tests/backend/test_project_structure.py`

**Outputs:**
- `specforge/` root directory with:
  - `docker-compose.yml`
  - `.gitignore`
  - `README.md` (placeholder)
  - `backend/` skeleton (empty subdirs per harness structure tests)
  - `frontend/` skeleton (empty subdirs per harness structure tests)
  - `.github/workflows/` directory

**Steps:**
1. Create the directory tree exactly as specified in `harness/tests/backend/test_project_structure.py`.
2. Create `docker-compose.yml` with postgres:16-alpine and redis:7-alpine services.
3. Create `.gitignore` covering: `__pycache__`, `*.pyc`, `.env`, `node_modules`, `.venv`, `dist`, `*.pem`, `*.log`.
4. Create `README.md` with title "SpecForge" and single line "Setup instructions coming soon."
5. Verify the directory tree matches the harness structure tests exactly.

**Acceptance Criteria:**
- `docker compose up -d db redis` runs without error.
- `docker compose ps` shows both services healthy.
- No `.env` files committed.
- All directories from the harness structure tests exist.

**Dependencies:** None

---

### T-002: Backend Python Project Setup

**Description:**
Initialize the Python backend project with uv, install all dependencies, configure pyproject.toml, and verify the environment activates correctly.

**Inputs:**
- `backend/` directory (from T-001)
- `requirements.txt` content from architecture doc Section 11

**Outputs:**
- `backend/requirements.txt`
- `backend/requirements-dev.txt`
- `backend/pyproject.toml`
- `backend/.env.example`
- `backend/.python-version` (pinned to 3.12)

**Steps:**
1. Create `backend/.python-version` with content `3.12`.
2. Create `backend/requirements.txt` with all production packages from architecture doc Section 11 (exact versions as specified).
3. Create `backend/requirements-dev.txt` with: `bandit==1.*`, `safety==3.*`, `pytest==8.*`, `pytest-asyncio==0.24.*`, `black==24.*`, `ruff==0.8.*`, `pytest-mock`.
4. Create `backend/pyproject.toml` with:
   - `[tool.black]` section: `line-length = 88`.
   - `[tool.ruff]` section: `line-length = 88`, `select = ["E", "F", "I"]`.
   - `[tool.pytest.ini_options]` section: `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
5. Create `backend/.env.example` with all variables from plan.md Section 7, values set to placeholder strings.
6. Run `uv sync` from `backend/`. Verify no errors.

**Acceptance Criteria:**
- `uv run python --version` outputs `Python 3.12.x`.
- `uv run python -c "import fastapi, sqlalchemy, redis, anthropic"` exits 0.
- `backend/.env.example` contains every variable listed in plan.md Section 7.
- No actual secrets in any committed file.

**Dependencies:** T-001

---

### T-003: Backend Configuration and App Factory

**Description:**
Create `config.py` (typed settings), `database.py` (async engine + session), and `main.py` (FastAPI app factory with middleware skeleton). The app must start and serve `/health`.

**Inputs:**
- `backend/.env` (copied from `.env.example`, filled with local values)
- `harness/instructions.txt`
- `harness/tests/backend/test_app_contract.py`

**Outputs:**
- `backend/config.py`
- `backend/database.py`
- `backend/main.py`

**Steps:**
1. Create `backend/config.py`:
   - `class Settings(BaseSettings)` with all fields from `.env.example`.
   - All fields typed. No field with a default that silently hides misconfiguration for required secrets.
   - Use `model_config = SettingsConfigDict(env_file=".env")`.
   - Singleton: `settings = Settings()` at module bottom.
2. Create `backend/database.py`:
   - `async_engine` created from `settings.database_url`.
   - `AsyncSessionLocal` session factory with `expire_on_commit=False`.
   - `async def get_db()` dependency that yields a session and closes it.
3. Create `backend/main.py`:
   - `create_app()` factory function returning a configured `FastAPI` instance.
   - CORS middleware: allow origins from `settings.frontend_url`, allow credentials, allow all methods and headers.
   - Register `/health` route (no auth) returning `{"status": "ok", "db": "ok", "redis": "ok", "version": "1.0.0"}`. Health check must ping DB with `SELECT 1` and Redis with `PING`. Return `{"status": "degraded"}` and 503 if either fails.
   - `app = create_app()` at module bottom for Uvicorn.

**Acceptance Criteria:**
- `uv run uvicorn main:app --reload` starts without error.
- `GET localhost:8000/health` returns `200` with `{"status": "ok", ...}`.
- Stopping the DB container: `GET /health` returns `503`.
- `uv run python -c "from config import settings; print(settings.environment)"` prints `development`.
- `black --check .` passes.
- `ruff check .` passes.

**Dependencies:** T-002

---

### T-004: Frontend Project Setup

**Description:**
Initialize the React + TypeScript + Vite frontend project, install all dependencies, configure Tailwind, and verify the dev server starts.

**Inputs:**
- `frontend/` directory (from T-001)
- architecture doc Section 11 (frontend package versions)
- `harness/tests/frontend/`

**Outputs:**
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/tailwind.config.ts`
- `frontend/index.html`
- `frontend/src/main.tsx` (minimal entry point)
- `frontend/src/App.tsx` (placeholder)
- `frontend/.env.example`

**Steps:**
1. Create `frontend/package.json` with exact dependency versions from architecture doc Section 11. Use `pnpm` as package manager (add `"packageManager": "pnpm@9"` field).
2. Run `pnpm install`.
3. Create `frontend/vite.config.ts`: React plugin, proxy `/api` → `http://localhost:8000`.
4. Create `frontend/tsconfig.json` with `"strict": true`, `"noImplicitAny": true`, target `ES2022`, module `ESNext`.
5. Create `frontend/tailwind.config.ts` with `content: ["./src/**/*.{ts,tsx}"]` and the Modern Indica theme colors from design.md mapped to CSS custom properties.
6. Create `frontend/index.html` with root div, import `src/main.tsx`, load Plus Jakarta Sans from Google Fonts.
7. Create `frontend/src/main.tsx`: `ReactDOM.createRoot(document.getElementById('root')!).render(<App />)`.
8. Create `frontend/src/App.tsx`: renders `<div>SpecForge</div>`.
9. Create `frontend/.env.example` with `VITE_API_URL=http://localhost:8000` and `VITE_SENTRY_DSN=`.

**Acceptance Criteria:**
- `pnpm dev` starts on port 5173 without error.
- Browser shows "SpecForge" text.
- `pnpm tsc --noEmit` exits 0.
- No TypeScript `any` warnings with `strict: true`.

**Dependencies:** T-001

---

### T-005: TypeScript Types and API Service Foundation

**Description:**
Define all shared TypeScript types (matching the spec data models exactly) and create the `api.ts` axios service with interceptors.

**Inputs:**
- spec.md Section 10 (Data Models)
- spec.md Section 11 (API Contracts)

**Outputs:**
- `frontend/src/types/user.ts`
- `frontend/src/types/workspace.ts`
- `frontend/src/types/stage.ts`
- `frontend/src/services/api.ts`

**Steps:**
1. Create `frontend/src/types/user.ts`: export `User` interface with fields matching spec.md Section 10 (id, email, google_id, name, avatar_url, created_at, credit_balance).
2. Create `frontend/src/types/workspace.ts`: export `Workspace` and `CreateWorkspacePayload` interfaces matching spec.md.
3. Create `frontend/src/types/stage.ts`:
   - Export `StageType = "spec" | "plan" | "harness" | "tasks"`.
   - Export `StageStatus = "locked" | "draft" | "in_progress" | "finalised" | "stale"`.
   - Export `Stage`, `StageVersion`, `EvalResult` interfaces matching spec.md Section 10.
   - Export `GenerateResponse`, `RefineResponse`, `DiffChunk` interfaces for API responses.
4. Create `frontend/src/services/api.ts`:
   - Axios instance with `baseURL: import.meta.env.VITE_API_URL`, `withCredentials: true`.
   - Request interceptor: attach `Authorization: Bearer {token}` from localStorage.
   - Response interceptor: on 401, attempt silent token refresh via `POST /auth/refresh`, retry original request once. On second 401, redirect to `/`.
   - Export typed functions: `getWorkspaces()`, `createWorkspace(payload)`, `getWorkspace(id)`, `getStage(id)`, `finaliseStage(id)`, `rollbackStage(id, version)`, `getCredits()`.

**Acceptance Criteria:**
- `pnpm tsc --noEmit` exits 0.
- All types imported in `App.tsx` without errors.
- Axios interceptor function exists and handles 401 (unit testable logic extracted into a pure function).

**Dependencies:** T-004

---

### T-006: SQLAlchemy Models

**Description:**
Define all SQLAlchemy ORM models matching the spec data models exactly.

**Inputs:**
- spec.md Section 10 (Data Models)

**Outputs:**
- `backend/models/__init__.py`
- `backend/models/user.py`
- `backend/models/workspace.py`
- `backend/models/stage.py`
- `backend/models/stage_version.py`
- `backend/models/credit_ledger.py`
- `backend/models/eval_result.py`

**Steps:**
1. Create `backend/models/__init__.py` that imports all models (required for Alembic autogenerate).
2. Create each model file with `DeclarativeBase` mapped class. Use `UUID` primary keys with `server_default=text("gen_random_uuid()")`. All timestamps as `TIMESTAMPTZ` with `server_default=func.now()`.
3. `models/user.py`: `User` table with all fields from spec.md. Unique constraint on `email`, unique constraint on `google_id`.
4. `models/workspace.py`: `Workspace` table. `user_id` FK → `users.id` with `ondelete="CASCADE"`. `status` as `String` with CHECK constraint `('active', 'archived')`.
5. `models/stage.py`: `Stage` table. `workspace_id` FK → `workspaces.id` with `ondelete="CASCADE"`. `type` CHECK constraint `('spec', 'plan', 'harness', 'tasks')`. `status` CHECK constraint `('locked', 'draft', 'in_progress', 'finalised', 'stale')`. `current_version` Integer default 0. `review_gate_acknowledged` Boolean default False (from plan.md open question Q2).
6. `models/stage_version.py`: `StageVersion` table. `stage_id` FK → `stages.id`. `created_by` CHECK `('user', 'ai')`.
7. `models/credit_ledger.py`: `CreditLedger` table. `amount` Integer not null. `metadata_` JSONB (note: `metadata` is reserved in SQLAlchemy, use `metadata_` mapped to column name `metadata`).
8. `models/eval_result.py`: `EvalResult` table. `stage_version_id` FK → `stage_versions.id`. `coverage_percent`, `uncovered_reqs`, `tasks_without_ref` nullable (harness/tasks only).

**Acceptance Criteria:**
- `uv run python -c "from models import User, Workspace, Stage, StageVersion, CreditLedger, EvalResult; print('OK')"` exits 0.
- No circular imports.
- `ruff check .` passes.

**Dependencies:** T-003

---

### T-007: Alembic Migrations — Initial Schema

**Description:**
Configure Alembic and create the initial migration that creates all tables from T-006 models.

**Inputs:**
- `backend/models/` (from T-006)
- `backend/database.py` (from T-003)

**Outputs:**
- `backend/alembic.ini`
- `backend/migrations/env.py`
- `backend/migrations/versions/0001_initial_schema.py`

**Steps:**
1. Run `uv run alembic init migrations` from `backend/`.
2. Edit `backend/alembic.ini`: set `script_location = migrations`, `sqlalchemy.url` to use `settings.database_url` (reference via env variable, not hardcoded).
3. Edit `backend/migrations/env.py`:
   - Import `settings` from `config`.
   - Import `Base` from `models`.
   - Set `target_metadata = Base.metadata`.
   - Use async engine pattern for `run_migrations_online`.
4. Run `uv run alembic revision --autogenerate -m "initial_schema"`.
5. Review the generated migration. Verify all 6 tables are created with correct columns, constraints, and foreign keys.
6. Run `uv run alembic upgrade head` against the local DB.

**Acceptance Criteria:**
- `uv run alembic upgrade head` runs without error on a clean DB.
- `uv run alembic downgrade -1` followed by `uv run alembic upgrade head` runs without error.
- All 6 tables exist in the DB: `users`, `workspaces`, `stages`, `stage_versions`, `credit_ledger`, `eval_results`.
- All foreign key constraints visible via `\d table_name` in psql.

**Dependencies:** T-006

---

### T-008: Pydantic Schemas

**Description:**
Create all Pydantic v2 request and response schemas for every API endpoint group.

**Inputs:**
- spec.md Section 11 (API Contracts)
- spec.md Section 10 (Data Models)

**Outputs:**
- `backend/schemas/__init__.py`
- `backend/schemas/auth.py`
- `backend/schemas/workspace.py`
- `backend/schemas/stage.py`
- `backend/schemas/credits.py`
- `backend/schemas/common.py`

**Steps:**
1. Create `backend/schemas/common.py`: `ErrorResponse(code: str, message: str)`, `PaginatedResponse(Generic[T])` with `items: list[T]`, `total: int`, `limit: int`, `offset: int`.
2. Create `backend/schemas/auth.py`: `UserResponse(id, email, name, avatar_url, credit_balance, created_at)`.
3. Create `backend/schemas/workspace.py`:
   - `WorkspaceCreate(name: str, problem_statement: str, provider: str, model: str)` — validate name max 200 chars, problem_statement min 50 / max 10,000 chars.
   - `WorkspaceUpdate(name: str)`.
   - `WorkspaceResponse` with nested stage summaries.
4. Create `backend/schemas/stage.py`:
   - `GenerateRequest(stage_id: UUID)` — no body needed beyond path param.
   - `RefineRequest(instruction: str, selection_start: int, selection_end: int, selected_text: str)`.
   - `StageResponse(id, workspace_id, type, content, status, current_version, eval_result, created_at, updated_at)`.
   - `DiffResponse(diff: str, original: str, proposed: str)`.
   - `AcceptDiffRequest(proposed_content: str)`.
   - `RollbackRequest(version_number: int)`.
   - `EvalResponse` matching `EvalResult` model fields.
5. Create `backend/schemas/credits.py`: `CreditBalance(balance: int)`, `CreditLedgerEntry(id, amount, reason, created_at)`.
6. All schemas use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility.

**Acceptance Criteria:**
- `uv run python -c "from schemas import workspace, stage, credits, auth; print('OK')"` exits 0.
- `WorkspaceCreate` raises `ValidationError` if `problem_statement` is under 50 chars.
- `WorkspaceCreate` raises `ValidationError` if `problem_statement` exceeds 10,000 chars.
- `ruff check .` passes.

**Dependencies:** T-006

---

### T-009: Auth Service — Google OAuth + JWT

**Description:**
Implement the complete auth service: Google OAuth initiation, callback handling, JWT RS256 issuance, refresh token rotation, and revocation via Redis.

**Inputs:**
- `backend/config.py` (from T-003)
- `backend/models/user.py` (from T-006)
- Google OAuth credentials in `.env`

**Outputs:**
- `backend/services/auth_service.py`

**Steps:**
1. Create `backend/services/auth_service.py` with class `AuthService`:
2. `get_google_auth_url() -> str`: Uses Authlib to build the Google OAuth authorization URL with scopes `openid email profile`. Returns the redirect URL.
3. `handle_callback(code: str, db: AsyncSession) -> tuple[str, str]`: Exchanges code for Google token. Fetches user info from Google. Creates or updates `User` record in DB. Issues access token (JWT RS256, 15-min expiry, claims: `sub=user_id, jti=uuid4`). Issues refresh token (JWT RS256, 7-day expiry). Stores refresh token `jti` in Redis as `session:{jti}` with 7-day TTL. Returns `(access_token, refresh_token)`.
4. `refresh_tokens(refresh_token: str, db: AsyncSession) -> tuple[str, str]`: Decodes refresh token. Checks `session:{jti}` exists in Redis (if not, token is revoked — raise `AuthError`). Deletes old `session:{jti}` from Redis. Issues new access token and refresh token. Stores new `session:{jti}`. Returns new pair.
5. `revoke(refresh_token: str) -> None`: Decodes token. Deletes `session:{jti}` from Redis.
6. `verify_access_token(token: str) -> dict`: Decodes and validates JWT. Raises `AuthError` if invalid or expired.
7. On new user creation: call `credit_service.credit(user_id, 50, "signup_bonus")` (credit_service must be called here — stub it if T-018 not done yet, replace stub when T-018 is done).

**Acceptance Criteria:**
- Unit test: `handle_callback` with mocked Google response creates a new `User` in DB.
- Unit test: `refresh_tokens` with a valid token returns new token pair and invalidates old jti in Redis.
- Unit test: `refresh_tokens` with revoked token (jti deleted from Redis) raises `AuthError`.
- Unit test: `verify_access_token` with expired token raises `AuthError`.
- `ruff check .` passes.

**Dependencies:** T-007, T-008

---

### T-010: Auth Middleware

**Description:**
Create the FastAPI auth middleware/dependency that validates JWT on protected routes and attaches the current user to the request.

**Inputs:**
- `backend/services/auth_service.py` (from T-009)
- `backend/models/user.py`

**Outputs:**
- `backend/middleware/auth.py`

**Steps:**
1. Create `backend/middleware/auth.py`.
2. Create `get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User` dependency:
   - Extracts Bearer token from Authorization header.
   - Calls `auth_service.verify_access_token(token)`.
   - Loads `User` from DB by `sub` claim.
   - Raises `HTTPException(401)` if token invalid or user not found.
3. Create `get_optional_user` variant that returns `None` instead of raising on missing/invalid token (used for landing page that checks auth state).
4. Register `oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google", auto_error=False)` at module level.

**Acceptance Criteria:**
- Unit test: `get_current_user` with valid token returns correct User object.
- Unit test: `get_current_user` with expired token raises 401.
- Unit test: `get_current_user` with missing Authorization header raises 401.

**Dependencies:** T-009

---

### T-011: Auth Router

**Description:**
Implement all five auth endpoints.

**Inputs:**
- `backend/services/auth_service.py` (from T-009)
- `backend/middleware/auth.py` (from T-010)
- `backend/schemas/auth.py` (from T-008)

**Outputs:**
- `backend/routers/auth.py`
- Updated `backend/main.py` (register auth router)

**Steps:**
1. Create `backend/routers/auth.py` with `router = APIRouter(prefix="/auth", tags=["auth"])`.
2. `POST /auth/google`: calls `auth_service.get_google_auth_url()`, returns `{"redirect_url": url}`.
3. `GET /auth/callback`: receives `code` query param. Calls `auth_service.handle_callback()`. Sets `access_token` in response body. Sets `refresh_token` as HttpOnly cookie (`secure=True`, `samesite="lax"`, `max_age=604800`).
4. `POST /auth/refresh`: reads refresh token from HttpOnly cookie. Calls `auth_service.refresh_tokens()`. Returns new access token in body. Sets new refresh token cookie.
5. `POST /auth/logout`: reads refresh token cookie. Calls `auth_service.revoke()`. Clears cookie.
6. `GET /auth/me`: protected by `get_current_user`. Returns `UserResponse` with credit balance fetched from `credit_service.get_balance(user.id)`.
7. Register `router` in `main.py`: `app.include_router(auth_router)`.

**Acceptance Criteria:**
- Integration test: `POST /auth/google` returns 200 with `redirect_url` containing `accounts.google.com`.
- Integration test: `GET /auth/me` with valid token returns user data.
- Integration test: `GET /auth/me` with no token returns 401.
- Integration test: `POST /auth/logout` clears the refresh token cookie.

**Dependencies:** T-010

---

### T-012: Rate Limiting Middleware

**Description:**
Implement Redis sliding window rate limiting for all tiers defined in the spec.

**Inputs:**
- spec.md Section 12 (Rate Limits table)
- `backend/config.py`

**Outputs:**
- `backend/middleware/rate_limit.py`

**Steps:**
1. Create `backend/middleware/rate_limit.py`.
2. Implement `sliding_window_check(redis_client, key: str, limit: int, window_seconds: int) -> bool`:
   - Uses Redis sorted set. Key: `ratelimit:{key}`.
   - ZADD current timestamp. ZREMRANGEBYSCORE to remove old entries. ZCARD to count. EXPIRE to set TTL.
   - Returns `True` if under limit, `False` if over.
3. Create `RateLimitMiddleware(BaseHTTPMiddleware)`:
   - Global: `ratelimit:ip:{ip}` — 1,000 req/min.
   - Per-user API: `ratelimit:user:{user_id}` — 100 req/min (only applied if auth header present).
   - Auth login: `ratelimit:login:{ip}` — 5 attempts/5 min (applied only on `/auth/google` and `/auth/callback`).
   - Returns `429` with `Retry-After` header on limit exceeded.
4. Per-user LLM rate limits (`ratelimit:llm:{user_id}` — 10/min, `ratelimit:llm_daily:{user_id}` — 200/24h) enforced in `stage_manager.py` (not in middleware), because they require authenticated user context. Implement the check function here but call it from the service.
5. Register middleware in `main.py` after CORS, before auth.

**Acceptance Criteria:**
- Unit test: `sliding_window_check` returns `False` after limit is exceeded.
- Unit test: `sliding_window_check` resets correctly after window expires.
- Integration test: 1,001 requests from same IP in 60 seconds results in 429 on the 1,001st.

**Dependencies:** T-003

---

### T-013: LLM Gateway — Base Adapter and Factory

**Description:**
Define the abstract LLM adapter interface and the factory function. No provider implementations yet.

**Inputs:**
- `harness/manifest.json` (module boundaries for `services/llm/`)
- architecture doc Section 4 (LLM Gateway)

**Outputs:**
- `backend/services/llm/__init__.py`
- `backend/services/llm/base.py`
- `backend/services/llm/gateway.py`

**Steps:**
1. Create `backend/services/llm/base.py`:
   ```python
   class BaseLLMAdapter(ABC):
       @abstractmethod
       async def stream(self, system: str, user: str, max_tokens: int) -> AsyncGenerator[str, None]: ...
       
       @abstractmethod
       async def complete(self, system: str, user: str, max_tokens: int) -> str: ...
   ```
2. Create `backend/services/llm/gateway.py`:
   - `get_llm(provider: str, model: str) -> BaseLLMAdapter` factory.
   - Raises `ValueError` for unknown provider.
   - Imports adapters lazily to avoid import errors when a provider SDK is not configured.
3. Create `__init__.py` exporting `BaseLLMAdapter`, `get_llm`.

**Acceptance Criteria:**
- `uv run python -c "from services.llm import BaseLLMAdapter, get_llm; print('OK')"` exits 0.
- `get_llm("unknown", "model")` raises `ValueError`.
- `BaseLLMAdapter` cannot be instantiated directly (ABC enforcement).

**Dependencies:** T-003

---

### T-014: Anthropic Adapter

**Description:**
Implement `BaseLLMAdapter` for Anthropic (Claude models).

**Inputs:**
- `backend/services/llm/base.py` (from T-013)
- `backend/config.py` (ANTHROPIC_API_KEY)

**Outputs:**
- `backend/services/llm/anthropic_adapter.py`

**Steps:**
1. Create `AnthropicAdapter(BaseLLMAdapter)`.
2. `__init__(self, model: str)`: initialises `anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)`.
3. `stream()`: calls `client.messages.stream(model=self.model, system=system, messages=[{"role": "user", "content": user}], max_tokens=max_tokens)`. Yields each text delta as string. On any `anthropic.APIError`, raises `ProviderError(provider="anthropic", original=e)`.
4. `complete()`: calls `client.messages.create(...)`. Returns full text. On error, raises `ProviderError`.
5. Register `"anthropic"` in `gateway.py`.

**Acceptance Criteria:**
- Unit test: `stream()` with mocked SDK yields expected token strings.
- Unit test: `stream()` raises `ProviderError` on `anthropic.APIError`.
- `uv run python -c "from services.llm.anthropic_adapter import AnthropicAdapter; print('OK')"` exits 0.

**Dependencies:** T-013

---

### T-015: OpenAI Adapter

**Description:**
Implement `BaseLLMAdapter` for OpenAI (GPT models).

**Inputs:**
- `backend/services/llm/base.py` (from T-013)

**Outputs:**
- `backend/services/llm/openai_adapter.py`

**Steps:**
1. Create `OpenAIAdapter(BaseLLMAdapter)`.
2. `__init__(self, model: str)`: initialises `openai.AsyncOpenAI(api_key=settings.openai_api_key)`.
3. `stream()`: `client.chat.completions.create(model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], stream=True, max_tokens=max_tokens)`. Iterates chunks. Yields `chunk.choices[0].delta.content` if not None. On `openai.OpenAIError`, raises `ProviderError`.
4. `complete()`: same without streaming.
5. Register `"openai"` in `gateway.py`.

**Acceptance Criteria:**
- Unit test: `stream()` with mocked SDK yields expected strings.
- Unit test: `complete()` returns expected string.

**Dependencies:** T-013

---

### T-016: Google Adapter

**Description:**
Implement `BaseLLMAdapter` for Google (Gemini models).

**Inputs:**
- `backend/services/llm/base.py` (from T-013)

**Outputs:**
- `backend/services/llm/google_adapter.py`

**Steps:**
1. Create `GoogleAdapter(BaseLLMAdapter)`.
2. `__init__(self, model: str)`: configures `google.generativeai` with `settings.google_api_key`. Creates `GenerativeModel(model_name=model, system_instruction=system)` (system instruction set per-call).
3. `stream()`: calls `model.generate_content_async(user, stream=True)`. Iterates chunks. Yields `chunk.text`. On `google.api_core.exceptions.GoogleAPIError`, raises `ProviderError`.
4. `complete()`: same without streaming.
5. Register `"google"` in `gateway.py`.
6. Create `backend/config/providers.ts` equivalent in backend: `backend/services/llm/provider_config.py` — dict mapping provider name → list of valid model strings. Used for validation.

**Acceptance Criteria:**
- Unit test: adapter streams correctly with mocked SDK.
- `get_llm("google", "gemini-1.5-pro")` returns `GoogleAdapter` instance.

**Dependencies:** T-013

---

### T-017: Providers Router

**Description:**
Implement `GET /providers` endpoint returning available providers and their model lists.

**Inputs:**
- `backend/services/llm/provider_config.py` (from T-016)

**Outputs:**
- `backend/routers/providers.py`
- Updated `backend/main.py`

**Steps:**
1. Create `backend/routers/providers.py`.
2. `GET /providers` (no auth required): returns hardcoded list of providers and models from `provider_config.py`.
   ```json
   {
     "providers": [
       {"id": "anthropic", "name": "Anthropic", "models": [{"id": "claude-opus-4-0", "name": "Claude Opus 4"}, ...]},
       ...
     ]
   }
   ```
3. Register in `main.py`.

**Acceptance Criteria:**
- `GET /providers` returns 200 with all three providers.
- Each provider has at least 2 models.
- Response matches the schema expected by `frontend/src/config/providers.ts`.

**Dependencies:** T-016

---

### T-018: Credit Service

**Description:**
Implement the credit service with atomic deduction, refund, and balance query backed by PostgreSQL and Redis cache.

**Inputs:**
- `backend/models/credit_ledger.py` (from T-006)

**Outputs:**
- `backend/services/credit_service.py`

**Steps:**
1. Create `backend/services/credit_service.py` with `CreditService` class.
2. `get_balance(user_id: UUID, db: AsyncSession) -> int`:
   - Check Redis `credits:{user_id}`. Return cached value if present.
   - If cache miss: query `SUM(amount)` from `credit_ledger` where `user_id = user_id`. Cache result with 5-min TTL. Return sum.
3. `credit(user_id: UUID, amount: int, reason: str, db: AsyncSession, metadata: dict = None) -> CreditLedger`:
   - Insert positive `CreditLedger` entry.
   - Invalidate Redis cache `credits:{user_id}`.
4. `deduct(user_id: UUID, amount: int, reason: str, db: AsyncSession) -> CreditLedger`:
   - Use `SELECT SUM(amount) FROM credit_ledger WHERE user_id = ? FOR UPDATE` inside a transaction to lock.
   - If balance - amount < 0: raise `InsufficientCreditsError`.
   - Insert negative `CreditLedger` entry (amount = -amount).
   - Invalidate Redis cache.
   - Return entry.
5. `refund(ledger_entry_id: UUID, db: AsyncSession) -> None`:
   - Load the original deduction entry. Verify it has negative amount.
   - Insert positive entry with amount = abs(original.amount), reason = f"refund:{ledger_entry_id}".
   - Invalidate Redis cache.

**Acceptance Criteria:**
- Unit test: `deduct()` raises `InsufficientCreditsError` when balance is insufficient.
- Unit test: concurrent `deduct()` calls don't produce negative balance (test with `asyncio.gather`).
- Unit test: `refund()` restores balance correctly.
- Unit test: `get_balance()` returns cached value on second call without hitting DB.

**Dependencies:** T-007

---

### T-019: Credit Check Middleware

**Description:**
Create the credit check dependency applied to all LLM-triggering routes.

**Inputs:**
- `backend/services/credit_service.py` (from T-018)
- `backend/middleware/auth.py` (from T-010)

**Outputs:**
- `backend/middleware/credit_check.py`

**Steps:**
1. Create `backend/middleware/credit_check.py`.
2. Create `require_credits(amount: int)` — a dependency factory:
   ```python
   def require_credits(amount: int):
       async def check(user: User = Depends(get_current_user), db = Depends(get_db)):
           balance = await credit_service.get_balance(user.id, db)
           if balance < amount:
               raise HTTPException(402, detail={"code": "insufficient_credits", "balance": balance, "required": amount})
       return check
   ```
3. Usage on routes: `Depends(require_credits(10))` for generate/regenerate, `Depends(require_credits(3))` for refine.

**Acceptance Criteria:**
- Unit test: dependency raises 402 when balance is 0.
- Unit test: dependency passes when balance ≥ required amount.

**Dependencies:** T-018

---

### T-020: Workspace Service and Router

**Description:**
Implement the workspace CRUD service and all workspace endpoints.

**Inputs:**
- `backend/models/workspace.py`, `backend/models/stage.py` (from T-006)
- `backend/schemas/workspace.py` (from T-008)

**Outputs:**
- `backend/services/workspace_service.py`
- `backend/routers/workspace.py`
- Updated `backend/main.py`

**Steps:**
1. Create `backend/services/workspace_service.py`:
   - `create(user_id, payload: WorkspaceCreate, db) -> Workspace`: Creates `Workspace` record. Creates four `Stage` records (spec=draft, plan=locked, harness=locked, tasks=locked). Returns workspace with stages.
   - `list_for_user(user_id, db) -> list[Workspace]`: Returns all non-archived workspaces for user, ordered by `created_at DESC`.
   - `get(workspace_id, user_id, db) -> Workspace`: Returns workspace with all stages. Raises 404 if not found or not owned by user.
   - `update(workspace_id, user_id, name, db) -> Workspace`: Updates name only.
   - `archive(workspace_id, user_id, db) -> None`: Sets `status = "archived"`.
2. Create `backend/routers/workspace.py` with thin router calling service methods.
3. All endpoints protected by `get_current_user`.
4. Register in `main.py`.

**Acceptance Criteria:**
- Integration test: `POST /workspaces` creates workspace with 4 stages in DB.
- Integration test: `GET /workspaces` returns only workspaces owned by authenticated user.
- Integration test: `DELETE /workspaces/{id}` from another user returns 403.
- Integration test: created workspace has `spec` stage in `draft` status and other three in `locked`.

**Dependencies:** T-011, T-018

---

### T-021: Prompt System

**Description:**
Implement all four stage prompts and the prompt builder that assembles system + user prompts from dependency content.

**Inputs:**
- spec.md Section 5 (Pipeline Stages — Detailed Specification)
- plan.md Section 5.5 (Prompt Architecture)

**Outputs:**
- `backend/prompts/base.py`
- `backend/prompts/spec.py`
- `backend/prompts/plan.py`
- `backend/prompts/harness.py`
- `backend/prompts/tasks.py`
- `backend/services/pipeline/prompt_builder.py`

**Steps:**
1. Create `backend/prompts/base.py`: define `ASDD_METHODOLOGY_OVERVIEW` constant — a concise paragraph describing ASDD methodology that is prepended to all system prompts.
2. Create each stage prompt file with:
   - `SYSTEM_PROMPT: str` — the AI's role, persona, output format instructions, few-shot examples for format compliance.
   - `build_user_prompt(dependencies: dict[str, str]) -> str` — function that injects upstream content into the user message using XML tags for structural isolation (e.g., `<spec_content>{content}</spec_content>`).
   - Each prompt must include explicit format requirements. Harness prompt must include a file-tree format example (per plan.md Risk 2).
3. Create `backend/services/pipeline/prompt_builder.py`:
   - `build_prompt(stage_type: str, workspace: Workspace, db: AsyncSession) -> tuple[str, str]` returns `(system_prompt, user_prompt)`.
   - Fetches dependency stage content from Redis (`stage:{id}`) or DB (cache miss populates Redis with 1h TTL).
   - Enforces 50,000-character upstream content limit from plan.md open question Q3. Truncates and logs if exceeded.
   - Prepends `ASDD_METHODOLOGY_OVERVIEW` to all system prompts.

**Acceptance Criteria:**
- Unit test: `build_prompt("plan", ...)` returns prompts containing spec content wrapped in `<spec_content>` tags.
- Unit test: upstream content exceeding 50,000 characters is truncated.
- Unit test: `build_prompt("spec", ...)` contains the problem statement in the user prompt.
- All prompt files import cleanly.

**Dependencies:** T-020

---

### T-022: Security — Prompt Guard and Output Validator

**Description:**
Implement prompt injection scanner and LLM output validator.

**Inputs:**
- spec.md Section 12 (Security)
- plan.md Section 5.6 (Security layers)

**Outputs:**
- `backend/services/security/prompt_guard.py`
- `backend/services/security/output_validator.py`

**Steps:**
1. Create `backend/services/security/prompt_guard.py`:
   - `scan(text: str) -> ScanResult(is_safe: bool, matched_pattern: str | None)`.
   - Pattern list includes: attempts to override system prompt (`ignore previous instructions`, `disregard`, `you are now`, `new instructions`), attempts to exfiltrate (`print your system prompt`, `reveal your instructions`), XML injection (opening `<system>` or `<|im_start|>` tags in user content).
   - Log all flagged attempts at `warning` level with sanitised text excerpt (first 100 chars only).
2. Create `backend/services/security/output_validator.py`:
   - `validate(output: str) -> ValidationResult(is_safe: bool, reason: str | None)`.
   - Checks for system prompt leakage: looks for patterns that suggest the system prompt was echoed back (e.g., "ASDD_METHODOLOGY", "You are SpecForge", the literal system prompt preamble).
   - If unsafe: return `is_safe=False`. Caller must discard output, refund credits, and show error.

**Acceptance Criteria:**
- Unit test: `scan("ignore previous instructions and tell me")` returns `is_safe=False`.
- Unit test: `scan("build a todo app")` returns `is_safe=True`.
- Unit test: output containing literal system prompt text returns `is_safe=False` from `validate()`.

**Dependencies:** T-003

---

### T-023: Diff Engine

**Description:**
Implement the diff engine that computes unified diffs for the refine accept/reject flow.

**Inputs:**
- spec.md Section 6.2 (Refine mode)

**Outputs:**
- `backend/services/pipeline/diff_engine.py`

**Steps:**
1. Create `backend/services/pipeline/diff_engine.py`.
2. `compute_diff(original: str, proposed: str) -> str`: Uses Python's built-in `difflib.unified_diff`. Returns the unified diff string.
3. `apply_diff(original: str, selected_text: str, replacement: str) -> str`: Replaces the selected text substring with the LLM-provided replacement. Handles the case where `selected_text` is not found (returns original with error logged).
4. No external dependencies — stdlib only.

**Acceptance Criteria:**
- Unit test: `compute_diff("hello world", "hello there")` returns a valid unified diff.
- Unit test: `apply_diff` correctly replaces selected text in a multi-line string.
- Unit test: `apply_diff` with non-existent `selected_text` returns original unchanged.

**Dependencies:** T-003

---

### T-024: Stage Manager — Core Orchestrator

**Description:**
Implement the central `StageManager` class with `generate`, `refine`, `finalise`, and `rollback` methods. This is the most critical backend component.

**Inputs:**
- `backend/services/llm/gateway.py` (from T-013)
- `backend/services/pipeline/prompt_builder.py` (from T-021)
- `backend/services/pipeline/diff_engine.py` (from T-023)
- `backend/services/credit_service.py` (from T-018)
- `backend/services/security/` (from T-022)
- `backend/models/stage.py`, `backend/models/stage_version.py`

**Outputs:**
- `backend/services/pipeline/stage_manager.py`

**Steps:**
1. Create `StageManager` with constants:
   ```python
   STAGE_ORDER = ["spec", "plan", "harness", "tasks"]
   STAGE_DEPENDENCIES = {
       "spec": [], "plan": ["spec"], "harness": ["spec", "plan"], "tasks": ["spec", "plan", "harness"]
   }
   CREDIT_COSTS = {"generate": 10, "refine": 3, "regenerate": 10}
   ```
2. Implement `async generate(stage_id, user, db) -> AsyncGenerator[str, None]`:
   - Load stage. Assert status is `draft` or `stale` (not `locked`, not `finalised`).
   - Assert all STAGE_DEPENDENCIES are `finalised`. Raise `StageDependencyError` if not.
   - Scan problem statement via `prompt_guard.scan()`. Raise `SecurityError` if flagged.
   - Deduct 10 credits via `credit_service.deduct()`.
   - Set stage `status = "in_progress"`. Save.
   - Build prompts via `prompt_builder.build_prompt()`.
   - Stream tokens via `get_llm(workspace.provider, workspace.model).stream()`.
   - Accumulate full content. Validate via `output_validator.validate()`.
   - If validation fails: refund credits, set stage back to `draft`, raise `SecurityError`.
   - On provider error: refund credits, set stage to `draft`, raise `ProviderError`.
   - On success: save full content to `Stage.content`, create `StageVersion(created_by="ai")`, increment `current_version`, set status to `draft` (not finalised — user must explicitly finalise).
   - Invalidate Redis `stage:{id}` cache.
   - Yield each token as it streams. Final yield: `{"done": True, "stage_id": str(stage_id)}`.
3. Implement `async refine(stage_id, request: RefineRequest, user, db) -> DiffResponse`:
   - Deduct 3 credits.
   - Build a targeted refine prompt that includes: the full current stage content, the selected text, and the user's instruction.
   - Call `llm.complete()` (not stream — refine returns a diff, not a stream).
   - Apply diff via `diff_engine.apply_diff()`.
   - If selection > 80% of document: log warning (note in response `large_selection: true`). Do not block.
   - Return `DiffResponse(diff, original, proposed)`. Credits NOT finalised yet — deducted on `POST /stages/{id}/accept-diff`.
   - **Implementation detail:** deduct credits optimistically. Refund if user rejects via `POST /stages/{id}/reject-diff`.
4. Implement `async finalise(stage_id, user, db) -> Stage`:
   - Assert stage status is `draft`.
   - Set `finalised_at = now()`, `status = "finalised"`.
   - Unlock the next stage in STAGE_ORDER (set its status from `locked` to `draft`).
   - Mark all downstream `finalised` stages as `stale` (this finalise does not do that — that logic is in `edit` path).
   - Cache stage content in Redis `stage:{id}` with 1h TTL.
5. Implement `async rollback(stage_id, version_number, user, db) -> Stage`:
   - Load `StageVersion` by `stage_id` + `version_number`. 404 if not found.
   - Set `Stage.content` to version content. Set `current_version = version_number`. Set status to `draft`.
   - Mark all downstream finalised stages `stale` (call `_mark_downstream_stale()`).
   - Invalidate Redis cache.
6. Implement `_mark_downstream_stale(stage, db)`: finds all stages in same workspace that are downstream of this stage and currently `finalised`. Sets them to `stale`.
7. Implement `async handle_content_edit(stage_id, new_content, user, db)`: called when user manually edits content in the editor. Saves new content. If stage was `finalised`, sets to `stale` and marks downstream stages stale. Creates new `StageVersion(created_by="user")`.

**Acceptance Criteria:**
- Unit test: `generate()` with non-finalised dependency raises `StageDependencyError`.
- Unit test: `generate()` on success deducts credits, saves version, returns tokens.
- Unit test: `generate()` with provider error refunds credits and sets stage to `draft`.
- Unit test: `finalise()` sets next stage to `draft` status.
- Unit test: `rollback()` marks all downstream finalised stages as `stale`.
- Unit test: `_mark_downstream_stale()` with tasks stage marks nothing (it is the last stage).

**Dependencies:** T-021, T-022, T-023, T-019

---

### T-025: Stage Router

**Description:**
Implement all stage endpoints, wiring them to StageManager.

**Inputs:**
- `backend/services/pipeline/stage_manager.py` (from T-024)
- `backend/schemas/stage.py` (from T-008)

**Outputs:**
- `backend/routers/stage.py`
- Updated `backend/main.py`

**Steps:**
1. Create `backend/routers/stage.py`.
2. `GET /stages/{id}`: returns `StageResponse`. Protected.
3. `POST /stages/{id}/generate`: SSE streaming. `Depends(require_credits(10))`. Calls `stage_manager.generate()`. Returns `StreamingResponse` with `media_type="text/event-stream"`. Each token: `data: {"token": "..."}\n\n`. Done event: `data: {"done": true}\n\n`.
4. `POST /stages/{id}/refine`: `Depends(require_credits(3))`. Calls `stage_manager.refine()`. Returns `DiffResponse`.
5. `POST /stages/{id}/accept-diff`: body: `AcceptDiffRequest(proposed_content)`. Saves proposed content as new version. No credit deduction here (already deducted in refine).
6. `POST /stages/{id}/reject-diff`: calls `credit_service.refund()` for the refine deduction. Returns 200.
7. `POST /stages/{id}/regenerate`: same as generate — `Depends(require_credits(10))`.
8. `POST /stages/{id}/finalise`: calls `stage_manager.finalise()`. Returns updated `StageResponse`.
9. `POST /stages/{id}/rollback`: body: `RollbackRequest`. Calls `stage_manager.rollback()`. Returns updated `StageResponse`.
10. `GET /stages/{id}/versions`: returns list of `StageVersion` records for stage, ordered by `version DESC`.
11. `GET /stages/{id}/eval`: returns latest `EvalResult` for stage.
12. `PATCH /stages/{id}/content`: body: `{content: str}`. Calls `stage_manager.handle_content_edit()`. Returns updated `StageResponse`.
13. Register in `main.py`.

**Acceptance Criteria:**
- Integration test: `POST /stages/{spec_id}/generate` streams tokens and creates a `StageVersion` in DB.
- Integration test: `POST /stages/{plan_id}/generate` with spec not finalised returns 409.
- Integration test: `POST /stages/{id}/finalise` sets next stage to `draft`.
- Integration test: `POST /stages/{id}/generate` with 0 credits returns 402.

**Dependencies:** T-024, T-019

---

### T-026: Online Eval Service

**Description:**
Implement the asynchronous online eval runner that scores each stage after generation completes.

**Inputs:**
- spec.md Section 7 (Quality and Evals)
- `backend/models/eval_result.py`
- `backend/services/llm/gateway.py`

**Outputs:**
- `backend/services/evals/online_eval.py`

**Steps:**
1. Create `backend/services/evals/online_eval.py`.
2. `async run_eval(stage_version_id: UUID, stage_type: str, content: str, spec_content: str, db) -> EvalResult`:
   - Uses a fixed judge LLM: `AnthropicAdapter("claude-haiku-4-5-20251001")` (lowest cost judge).
   - Constructs judge prompt with: stage type, the generated content, reference spec content.
   - Judge prompt asks for JSON response: `{overall_score: int, completeness: int, clarity: int, coverage_percent?: int, uncovered_reqs?: list[str], tasks_without_ref?: list[str]}`.
   - Calls `judge.complete()` with `temperature=0` (deterministic).
   - Parses JSON response. Saves `EvalResult` to DB.
   - Harness stage: sets `coverage_percent` and `uncovered_reqs` if coverage < 80.
   - Tasks stage: sets `tasks_without_ref` for tasks missing test references.
   - Returns `EvalResult`.
3. This function is called from `stage_manager.generate()` as a background task after the stream completes: `asyncio.create_task(run_eval(...))`. Does not block the user.
4. Eval errors are logged but do not surface to the user. The stage remains usable even if eval fails.

**Acceptance Criteria:**
- Unit test: `run_eval()` with mocked judge returns an `EvalResult` with correct score fields.
- Unit test: judge JSON parse failure logs error and returns `None` without raising.
- Integration test: after `generate()` completes, `GET /stages/{id}/eval` returns an `EvalResult`.

**Dependencies:** T-024, T-014

---

### T-027: Export Service

**Description:**
Implement the export service that packages all four finalised stages into a zip file.

**Inputs:**
- spec.md Section 4.8 (Export — zip structure)
- plan.md Section 3.1 (Export service)

**Outputs:**
- `backend/services/pipeline/export_service.py`

**Steps:**
1. Create `backend/services/pipeline/export_service.py`.
2. `async build_export(workspace_id: UUID, user_id: UUID, db) -> bytes`:
   - Load workspace. Assert all 4 stages are `finalised`. Raise `ExportNotReadyError` if any not finalised.
   - Load content of all 4 stages.
   - Parse harness content to extract file structure. The harness content uses a defined format (file tree in fenced code blocks + file content sections). Parse it. On parse failure, fall back to saving all harness content as a single `harness/HARNESS.md` file (log the fallback).
   - Build zip in memory using `zipfile.ZipFile(io.BytesIO(), mode='w')`.
   - Add: `SPEC.md`, `PLAN.md`, `TASKS.md`, and harness files under `harness/` directory.
   - Return zip bytes.
3. `POST /workspaces/{id}/export` router (add to `workspace.py` router):
   - Calls `export_service.build_export()`.
   - Returns `Response(content=zip_bytes, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="specforge-{workspace_id}.zip"'})`.

**Acceptance Criteria:**
- Unit test: `build_export()` with 4 finalised stages returns valid zip bytes.
- Unit test: zip contains `SPEC.md`, `PLAN.md`, `TASKS.md`, and at least one file under `harness/`.
- Unit test: `build_export()` with any stage not finalised raises `ExportNotReadyError`.
- Integration test: `POST /workspaces/{id}/export` returns 200 with `application/zip` content type.

**Dependencies:** T-025

---

### T-028: Credits Router

**Description:**
Implement the credits balance and history endpoints.

**Inputs:**
- `backend/services/credit_service.py` (from T-018)
- `backend/schemas/credits.py` (from T-008)

**Outputs:**
- `backend/routers/credits.py`
- Updated `backend/main.py`

**Steps:**
1. Create `backend/routers/credits.py`.
2. `GET /credits/balance`: protected. Returns `CreditBalance(balance=await credit_service.get_balance(user.id, db))`.
3. `GET /credits/history`: protected. Returns paginated list of `CreditLedgerEntry` records for user, ordered by `created_at DESC`. Supports `limit` (default 20, max 100) and `offset`.
4. Register in `main.py`.

**Acceptance Criteria:**
- Integration test: `GET /credits/balance` for new user returns 50 (signup bonus).
- Integration test: `GET /credits/history` returns ledger entries in reverse chronological order.

**Dependencies:** T-018

---

### T-029: SSE Service — Frontend

**Description:**
Implement the frontend SSE service that wraps EventSource with reconnection logic.

**Inputs:**
- spec.md Section 12 (SSE stream reconnect — 3 attempts)
- `frontend/src/types/stage.ts`

**Outputs:**
- `frontend/src/services/sseService.ts`

**Steps:**
1. Create `frontend/src/services/sseService.ts`.
2. Export `createSSEConnection(url: string, onToken: (token: string) => void, onDone: (stageId: string) => void, onError: (error: Error) => void)`:
   - Creates `EventSource` with `withCredentials: true`.
   - `onmessage`: parses `JSON.parse(event.data)`. If `done: true`, calls `onDone`. Else calls `onToken(data.token)`.
   - `onerror`: retry with exponential backoff (1s, 2s, 4s). After 3 failures, calls `onError` and closes connection.
   - Returns `{ close: () => void }` control object.
3. The `Authorization` header cannot be set on `EventSource`. The backend SSE route must accept auth via `?token=` query parameter OR via cookie. Implement: SSE routes accept `token` query param as fallback to Authorization header.

**Acceptance Criteria:**
- Unit test: `createSSEConnection` calls `onToken` for each received token event.
- Unit test: calls `onDone` when `done: true` event received.
- Unit test: calls `onError` after 3 connection failures.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-005

---

### T-030: Zustand Stores

**Description:**
Implement all three Zustand stores for frontend state management.

**Inputs:**
- `frontend/src/types/` (from T-005)

**Outputs:**
- `frontend/src/store/userStore.ts`
- `frontend/src/store/workspaceStore.ts`
- `frontend/src/store/stageStore.ts`

**Steps:**
1. Create `frontend/src/store/userStore.ts`:
   - State: `user: User | null`, `isLoading: boolean`.
   - Actions: `setUser(user)`, `clearUser()`, `fetchMe()` (calls `api.getMe()`).
2. Create `frontend/src/store/workspaceStore.ts`:
   - State: `workspaces: Workspace[]`, `currentWorkspace: Workspace | null`, `isLoading: boolean`.
   - Actions: `fetchWorkspaces()`, `setCurrentWorkspace(w)`, `createWorkspace(payload)`, `archiveWorkspace(id)`.
3. Create `frontend/src/store/stageStore.ts`:
   - State: `stages: Record<string, Stage>` (keyed by stage id), `streamingContent: Record<string, string>` (buffer for in-progress streams), `activeStream: string | null` (stage id being streamed).
   - Actions:
     - `setStage(stage)`: updates a stage in the map.
     - `appendToken(stageId, token)`: appends to `streamingContent[stageId]`. This is called hundreds of times/second. Must not trigger React re-renders directly — CodeMirror subscribes via `subscribeWithSelector`.
     - `startStream(stageId)`: sets `activeStream = stageId`, initialises `streamingContent[stageId] = ""`.
     - `finaliseStream(stageId)`: moves `streamingContent[stageId]` into `stages[stageId].content`. Clears `streamingContent[stageId]`. Sets `activeStream = null`.

**Acceptance Criteria:**
- Unit test: `appendToken` does not cause re-renders (test by checking render count stays 0 when called outside React).
- Unit test: `finaliseStream` correctly merges streaming content into stage.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-005

---

### T-031: React Router and Page Shell

**Description:**
Set up React Router with all routes and create empty page components with correct route guards.

**Inputs:**
- spec.md Section 4 (User Flows)
- `frontend/src/store/userStore.ts` (from T-030)

**Outputs:**
- `frontend/src/App.tsx` (updated with router)
- `frontend/src/pages/Landing.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/components/shared/ProtectedRoute.tsx`

**Steps:**
1. Update `frontend/src/App.tsx` to use `BrowserRouter` and `Routes`:
   - `/` → `<Landing />` (public)
   - `/dashboard` → `<ProtectedRoute><Dashboard /></ProtectedRoute>`
   - `/workspace/:id` → `<ProtectedRoute><Workspace /></ProtectedRoute>`
   - `*` → redirect to `/`
2. Create `ProtectedRoute.tsx`: checks `userStore.user`. If null, calls `api.getMe()`. If still null (401), redirects to `/`. If loading, shows spinner.
3. Create `Landing.tsx`: placeholder with "Sign in with Google" button that calls `api.initiateGoogleAuth()` (redirects to Google OAuth URL).
4. Create `Dashboard.tsx`: placeholder showing "Dashboard".
5. Create `Workspace.tsx`: reads `:id` from params. Calls `workspaceStore.fetchWorkspace(id)`. Shows "Workspace loading..." placeholder.

**Acceptance Criteria:**
- Navigating to `/dashboard` without auth redirects to `/`.
- `pnpm tsc --noEmit` exits 0.
- React Router renders correct page component per route.

**Dependencies:** T-030

---

### T-032: Dashboard UI

**Description:**
Implement the full Dashboard page with workspace list, workspace cards, create workspace modal, and credit banner.

**Inputs:**
- spec.md Section 4.9 (Dashboard)
- spec.md Section 4.2 (Creating a Workspace)
- design.md (colors, typography, spacing)

**Outputs:**
- `frontend/src/pages/Dashboard.tsx` (complete)
- `frontend/src/components/dashboard/WorkspaceCard.tsx`
- `frontend/src/components/dashboard/CreateWorkspaceModal.tsx`
- `frontend/src/components/dashboard/CreditBanner.tsx`
- `frontend/src/components/shared/CreditMeter.tsx`
- `frontend/src/config/providers.ts`

**Steps:**
1. Create `frontend/src/config/providers.ts`: export `PROVIDERS` array matching `GET /providers` response shape. Fetched from API on mount.
2. Implement `CreditMeter.tsx`: shows current credit balance. When balance = 0, renders "You've used all 50 free credits" message with waitlist link.
3. Implement `CreditBanner.tsx`: displayed at top of dashboard. Shows balance. Red when ≤ 5 credits.
4. Implement `WorkspaceCard.tsx`:
   - Shows workspace name, creation date, provider badge, progress indicator (4 dots: filled = finalised, half = draft, empty = locked).
   - Clicking card navigates to `/workspace/{id}`.
5. Implement `CreateWorkspaceModal.tsx`:
   - Fields: workspace name, problem statement (textarea, min 50 / max 10,000 chars with live counter), provider selector, model selector (filtered by provider).
   - Submit calls `workspaceStore.createWorkspace(payload)`. On success, navigates to `/workspace/{new_id}`.
   - Validation errors shown inline.
6. Implement `Dashboard.tsx`:
   - Fetches workspaces on mount.
   - Shows `CreditBanner` at top.
   - Grid of `WorkspaceCard` components.
   - "Create Workspace" button opens `CreateWorkspaceModal`.
   - Empty state when no workspaces.

**Acceptance Criteria:**
- Dashboard renders workspace list.
- Create workspace modal validates field lengths before submit.
- Provider selector changes model options.
- Credit meter shows correct balance from `GET /credits/balance`.
- Clicking a workspace card navigates to correct route.
- Styling matches Modern Indica design system (saffron primary, correct border radii).

**Dependencies:** T-031, T-028

---

### T-033: Stage Navigator Component

**Description:**
Implement the left panel Stage Navigator showing all four stages with their statuses and lock states.

**Inputs:**
- spec.md Section 4.3 (Workspace View — Stage Navigator)
- `frontend/src/types/stage.ts`

**Outputs:**
- `frontend/src/components/workspace/StageNavigator.tsx`

**Steps:**
1. Create `StageNavigator.tsx`:
   - Props: `stages: Stage[]`, `activeStageId: string`, `onSelectStage: (stageId: string) => void`.
   - Renders vertical list: SPEC.md, PLAN.md, HARNESS, TASKS.md in order.
   - Status indicator per stage: green dot (finalised), amber dot (draft/in_progress), grey dot (locked), amber with warning icon (stale).
   - Locked stages are not clickable (cursor: not-allowed, reduced opacity).
   - Selected stage highlighted.
   - Quality badge (score number) shown if `eval_result` present on stage.

**Acceptance Criteria:**
- Locked stages cannot be clicked.
- Correct status color per stage status value.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-031

---

### T-034: CodeMirror Stage Editor

**Description:**
Implement the CodeMirror 6 markdown editor that handles streaming token insertion without blocking the UI thread.

**Inputs:**
- plan.md Section 2 (CodeMirror + Zustand streaming architecture)
- `frontend/src/store/stageStore.ts` (from T-030)

**Outputs:**
- `frontend/src/components/workspace/StageEditor.tsx`

**Steps:**
1. Create `StageEditor.tsx`:
   - Props: `stageId: string`, `readOnly: boolean`, `onContentChange: (content: string) => void`.
   - Initialise CodeMirror 6 `EditorView` in a `useEffect` with `markdown()` language extension.
   - Subscribe to `stageStore` via `subscribeWithSelector` (NOT via `useStore` React hook — avoids re-renders):
     ```typescript
     useEffect(() => {
       return stageStore.subscribe(
         state => state.streamingContent[stageId],
         (content) => {
           if (content !== undefined) {
             // Apply transaction to CodeMirror
             view.dispatch({ changes: { from: view.state.doc.length, insert: lastToken } })
           }
         }
       )
     }, [stageId])
     ```
   - On user edit (not streaming): debounce 500ms, call `onContentChange` with full content.
   - `readOnly` prop disables editing but allows selection (for refine selection).
   - Expose `getSelection() -> {start, end, text}` via `useImperativeHandle` / ref.
2. Apply Tailwind + design system styling: editor background Pure White, font `Plus Jakarta Sans` monospace-adjacent, line height 1.6.

**Acceptance Criteria:**
- Streaming tokens appear in editor without React re-renders (verify with React DevTools Profiler — no component re-renders during streaming).
- User edits are debounced and call `onContentChange`.
- Selection returns correct `{start, end, text}` when text is selected.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-030

---

### T-035: Diff Viewer Component

**Description:**
Implement the diff viewer with accept and reject controls for the refine flow.

**Inputs:**
- spec.md Section 4.3 (Workspace View)
- spec.md Section 6.2 (Refine mode)

**Outputs:**
- `frontend/src/components/workspace/DiffViewer.tsx`

**Steps:**
1. Create `DiffViewer.tsx`:
   - Props: `diff: string`, `original: string`, `proposed: string`, `onAccept: (proposed: string) => void`, `onReject: () => void`.
   - Renders unified diff with line-level coloring: added lines (green background), removed lines (red background), context lines (neutral).
   - Parse diff using `@codemirror/lang-markdown` or simple string parsing (do not add a new dependency — parse manually).
   - Two buttons: "Accept Changes" (Saffron primary button) and "Reject" (secondary).
   - `onAccept` called with the full `proposed` content.
   - `onReject` calls the reject endpoint and closes the diff view.

**Acceptance Criteria:**
- Diff renders with correct added/removed line highlighting.
- Accept calls `api.acceptDiff(stageId, proposed)`.
- Reject calls `api.rejectDiff(stageId)`.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-031

---

### T-036: Generate Bar, Credit Confirm Modal, Staleness Warning, and Human Review Gate

**Description:**
Implement the toolbar components that control stage interactions.

**Inputs:**
- spec.md Section 4.4 (Generating a Stage)
- spec.md Section 4.5 (Human Review Gate)
- spec.md Section 4.7 (Staleness)

**Outputs:**
- `frontend/src/components/workspace/GenerateBar.tsx`
- `frontend/src/components/workspace/CreditConfirmModal.tsx`
- `frontend/src/components/workspace/StalenessWarning.tsx`
- `frontend/src/components/workspace/HumanReviewGate.tsx`

**Steps:**
1. Create `GenerateBar.tsx`:
   - Props: `stage: Stage`, `onGenerate`, `onRegenerate`, `onRefine`, `onFinalise`.
   - Shows correct buttons based on stage status: locked → no buttons; draft → Generate + (if content exists) Finalise; in_progress → loading spinner; finalised → Regenerate; stale → Regenerate + Finalise.
   - Refine button always visible when stage has content (opens refine panel).
2. Create `CreditConfirmModal.tsx`:
   - Props: `action: "generate" | "regenerate" | "refine"`, `creditCost: number`, `currentBalance: number`, `onConfirm`, `onCancel`.
   - Shows: "This will use {creditCost} credits. You have {currentBalance} remaining. Proceed?"
   - Saffron confirm button. Cancel button.
3. Create `StalenessWarning.tsx`:
   - Props: `stage: Stage`, `upstreamStageType: string`, `onRegenerate`, `onDismiss`.
   - Renders amber banner: "This stage was generated from a previous version of {upstreamStageType}. Regenerate or keep as-is?"
   - Two buttons: "Regenerate" and "Keep as-is".
4. Create `HumanReviewGate.tsx`:
   - Props: `fromStageType: string`, `toStageType: string`, `onProceed`, `onClose`.
   - Modal dialog: "You are about to generate {toStageType} from this {fromStageType}. Take a moment to review above. Once generated it will be based on this version. Are you ready?"
   - Only shown if stage `review_gate_acknowledged = false` (tracked on stage object — add field to Stage type and backend model).
   - After `onProceed`, calls `PATCH /stages/{id}/content` or a dedicated `POST /stages/{id}/acknowledge-gate` endpoint to set `review_gate_acknowledged = true`.

**Acceptance Criteria:**
- `CreditConfirmModal` shown before any generate/refine action.
- `HumanReviewGate` shown only once per stage per workspace (after acknowledge, never shown again).
- `StalenessWarning` visible on any stage with `status = "stale"`.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-035

---

### T-037: Coverage Panel and Task Validation Panel

**Description:**
Implement the quality panels shown below the editor for harness coverage and task validation results.

**Inputs:**
- spec.md Section 4.6 (Completing the Pipeline — coverage and task validation)
- spec.md Section 7 (Quality and Evals)

**Outputs:**
- `frontend/src/components/workspace/CoveragePanel.tsx`
- `frontend/src/components/workspace/TaskValidationPanel.tsx`
- `frontend/src/components/workspace/QualityBadge.tsx`

**Steps:**
1. Create `QualityBadge.tsx`: small badge showing `{overall_score}/100`. Green if ≥ 80, amber if 60–79, red if < 60. Shows "Evaluating..." if eval not yet complete.
2. Create `CoveragePanel.tsx`:
   - Props: `evalResult: EvalResult | null`.
   - Only rendered for harness stage.
   - Shows `coverage_percent`% coverage as progress bar.
   - If < 80%: lists `uncovered_reqs` as action items with amber warning icons.
3. Create `TaskValidationPanel.tsx`:
   - Props: `evalResult: EvalResult | null`.
   - Only rendered for tasks stage.
   - Lists `tasks_without_ref` as flagged items.

**Acceptance Criteria:**
- `CoveragePanel` hidden when `evalResult = null`.
- Coverage progress bar fills to correct percentage.
- Uncovered requirements listed correctly from `uncovered_reqs` array.
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-026

---

### T-038: Workspace Page — Full Assembly

**Description:**
Assemble the complete Workspace page, wiring all stage components together.

**Inputs:**
- All workspace components (T-033 through T-037)
- `frontend/src/services/sseService.ts` (from T-029)
- `frontend/src/store/stageStore.ts` (from T-030)

**Outputs:**
- `frontend/src/pages/Workspace.tsx` (complete)
- `frontend/src/hooks/useStream.ts`
- `frontend/src/hooks/useCredits.ts`

**Steps:**
1. Create `useCredits.ts`: polls `GET /credits/balance` every 30 seconds. Returns `{balance, isLoading}`.
2. Create `useStream.ts(stageId)`:
   - Calls `POST /stages/{id}/generate` and then creates SSE connection.
   - Calls `stageStore.startStream(stageId)`.
   - On each token: calls `stageStore.appendToken(stageId, token)`.
   - On done: calls `stageStore.finaliseStream(stageId)`. Fetches updated stage from API. Starts background eval polling (`GET /stages/{id}/eval` every 5 seconds until eval present, max 30s).
   - On error: shows `ErrorToast`. Calls `stageStore.finaliseStream(stageId)`.
3. Implement `Workspace.tsx` (complete):
   - Two-panel layout: `StageNavigator` left (fixed width 240px), `StageEditor` + toolbar right (flex-grow).
   - On mount: fetch workspace via `workspaceStore.fetchWorkspace(id)`. Set all stages in `stageStore`.
   - Active stage managed by local state, default = first non-locked stage.
   - Generate button → show `CreditConfirmModal` → on confirm → check if `HumanReviewGate` needed → show gate → on proceed → call `useStream`.
   - Refine flow: user selects text in editor → types in instruction input → click Refine → show `CreditConfirmModal` → on confirm → `POST /stages/{id}/refine` → show `DiffViewer`.
   - Content edits: `StageEditor.onContentChange` → debounced `PATCH /stages/{id}/content`.
   - Export button in header: only active when all 4 stages finalised. Calls `POST /workspaces/{id}/export`, triggers browser download.

**Acceptance Criteria:**
- Full generate flow works end to end: click Generate → confirm credits → tokens stream into editor.
- Finalise sets next stage to draft and navigator updates.
- Refine flow shows diff viewer and accept/reject work.
- Export downloads a zip file when all stages are finalised.
- Staleness warning appears when editing a finalised stage.

**Dependencies:** T-036, T-037, T-029

---

### T-039: Observability Setup

**Description:**
Configure structured logging, Prometheus metrics, OpenTelemetry tracing, and Sentry on both backend and frontend.

**Inputs:**
- spec.md Section 12 (Observability)
- plan.md Section 4 (Observability)

**Outputs:**
- `backend/middleware/observability.py`
- Updated `backend/main.py` (register observability middleware)
- Updated `frontend/src/main.tsx` (Sentry init)

**Steps:**
1. Create `backend/middleware/observability.py`:
   - Configure `structlog` with JSON renderer, `SensitiveDataFilter` that strips fields: `api_key`, `access_token`, `refresh_token`, `jwt_private_key`, `problem_statement`.
   - Configure OpenTelemetry with `FastAPIInstrumentor` and `SQLAlchemyInstrumentor`. OTLP exporter to `settings.grafana_otlp_endpoint`.
   - Configure Prometheus: expose `/metrics` endpoint. Counters/histograms: `llm_call_duration_seconds`, `llm_tokens_total`, `credit_deductions_total`, `active_sse_streams`, `pipeline_actions_total`.
   - `ObservabilityMiddleware`: logs every request (method, path, status_code, duration_ms) at INFO level. Filters sensitive paths (`/auth/callback` logs without `code` param).
2. `sentry_sdk.init()` in `main.py` with `settings.sentry_dsn`, `traces_sample_rate=0.1`.
3. Update `frontend/src/main.tsx`: `Sentry.init({dsn: import.meta.env.VITE_SENTRY_DSN, integrations: [Sentry.browserTracingIntegration()], tracesSampleRate: 0.1})`.

**Acceptance Criteria:**
- `GET /metrics` returns Prometheus text format with at least the declared metric names.
- A generate action produces a structured log entry with `stage_type` and `duration_ms` fields.
- `SensitiveDataFilter` removes `access_token` from log entries.

**Dependencies:** T-011

---

### T-040: CI Pipeline

**Description:**
Implement the full GitHub Actions CI pipeline that runs on every PR.

**Inputs:**
- `harness/manifest.json` (CI test gate)
- `harness/instructions.txt` (CI/CD pipeline expectations)

**Outputs:**
- `.github/workflows/ci.yml`

**Steps:**
1. Create `.github/workflows/ci.yml` with single `ci` job running on `push` and `pull_request` to `main`.
2. Job steps in order:
   - `actions/checkout@v4`
   - TruffleHog secret scan: `trufflesecurity/trufflehog@main` with `--only-verified` flag.
   - Backend setup: Python 3.12, `uv sync`.
   - `bandit -r backend/ -ll` (medium+ severity fails).
   - `safety scan --full-report` in backend venv.
   - `black --check backend/`.
   - `ruff check backend/`.
   - Start test DB: `docker compose up -d db redis`.
   - `alembic upgrade head` (verify migrations apply clean).
   - `pytest backend/tests/ --cov=services --cov-report=term --cov-fail-under=80`.
   - Frontend setup: Node 20, `pnpm install`.
   - `npm audit --audit-level=moderate` (in frontend dir).
   - `pnpm tsc --noEmit`.
   - `pnpm vitest run`.
3. All steps use `continue-on-error: false`. Any failure blocks merge.

**Acceptance Criteria:**
- CI passes on a clean branch with all tests passing.
- A committed secret string (`sk-ant-test`) in any file fails the TruffleHog step.
- A test failure fails the CI job.

**Dependencies:** T-007, T-025, T-038

---

## Phase 2 — Auth, Free Tier, and Deployment

---

### T-041: Stuck In-Progress Stage Recovery

**Description:**
Implement the background task that resets stages stuck in `in_progress` for over 10 minutes and refunds credits.

**Inputs:**
- plan.md Section 9 Open Question Q1
- `backend/services/pipeline/stage_manager.py`

**Outputs:**
- `backend/services/pipeline/recovery_service.py`
- Updated `backend/main.py` (register startup task)

**Steps:**
1. Create `backend/services/pipeline/recovery_service.py`:
   - `async recover_stuck_stages(db: AsyncSession) -> int`: Queries all stages with `status = "in_progress"` and `updated_at < now() - 10 minutes`. For each: find the most recent `CreditLedger` deduction for that stage's last generation action. Call `credit_service.refund()`. Set stage `status = "draft"`. Returns count of recovered stages.
2. Register in `main.py` as a repeating background task using `asyncio.create_task` + a loop with `asyncio.sleep(300)` (every 5 minutes).
3. Log each recovery event: `logger.warning("stage.recovery", stage_id=..., credits_refunded=...)`.

**Acceptance Criteria:**
- Unit test: `recover_stuck_stages()` with a 15-minute-old `in_progress` stage resets it to `draft` and refunds credits.
- Unit test: stages stuck for 9 minutes are NOT recovered.
- App starts without error with the background task registered.

**Dependencies:** T-024

---

### T-042: Human Review Gate — Backend Persistence

**Description:**
Add `review_gate_acknowledged` to the Stage model and implement the acknowledge endpoint.

**Inputs:**
- plan.md Section 9 Open Question Q2
- `backend/models/stage.py` (from T-006)

**Outputs:**
- `backend/migrations/versions/0002_add_review_gate_acknowledged.py`
- Updated `backend/routers/stage.py`

**Steps:**
1. Verify `review_gate_acknowledged` Boolean column with `default=False` is in `models/stage.py` (added in T-006 step 5 — confirm it is there, add it if missing).
2. Generate migration: `alembic revision --autogenerate -m "add_review_gate_acknowledged"`. Verify SQL adds column correctly.
3. Run migration.
4. Add endpoint to `stage.py` router: `POST /stages/{id}/acknowledge-gate`. Sets `stage.review_gate_acknowledged = True`. Returns updated `StageResponse`. No credit cost.

**Acceptance Criteria:**
- `POST /stages/{id}/acknowledge-gate` sets `review_gate_acknowledged = True` in DB.
- `GET /stages/{id}` response includes `review_gate_acknowledged` field.
- Migration applies and rolls back cleanly.

**Dependencies:** T-025

---

### T-043: Refine Large Selection Warning

**Description:**
Implement the warning when the refine selection covers > 80% of document, per plan.md open question Q4.

**Inputs:**
- plan.md Section 9 Open Question Q4

**Outputs:**
- Updated `backend/routers/stage.py` (refine endpoint)
- Updated `frontend/src/pages/Workspace.tsx` (show warning)

**Steps:**
1. In `stage_manager.refine()`: compute selection coverage. If `(selection_end - selection_start) / len(content) > 0.80`: add `large_selection: True` to `DiffResponse`.
2. In `frontend/src/components/workspace/GenerateBar.tsx` or refine flow: if `DiffResponse.large_selection = true`, show non-blocking inline warning: "This selection covers most of the document. Consider using Regenerate instead." with "Proceed" and "Use Regenerate" buttons.

**Acceptance Criteria:**
- Unit test: `stage_manager.refine()` with 85% selection returns `large_selection: True`.
- Unit test: `stage_manager.refine()` with 50% selection returns `large_selection: False`.
- Frontend shows warning when `large_selection` is true.

**Dependencies:** T-025

---

### T-044: Railway and Vercel Deployment

**Description:**
Configure Railway (backend) and Vercel (frontend) for production deployment with automatic CI/CD.

**Inputs:**
- `harness/instructions.txt` (deployment verification expectations)
- `backend/.env.example`

**Outputs:**
- `backend/railway.json` (Railway service config)
- `backend/Procfile` (Gunicorn command)
- `frontend/vercel.json` (Vercel config)
- Updated `.github/workflows/ci.yml` (add deploy step on merge to main)

**Steps:**
1. Create `backend/Procfile`:
   ```
   web: gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:$PORT
   ```
2. Create `backend/railway.json`:
   ```json
   {
     "deploy": {
       "startCommand": "alembic upgrade head && gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:$PORT",
       "healthcheckPath": "/health",
       "healthcheckTimeout": 30
     }
   }
   ```
3. Create `frontend/vercel.json`:
   ```json
   {
     "rewrites": [{"source": "/((?!api/).*)", "destination": "/index.html"}]
   }
   ```
4. Add deploy steps to `.github/workflows/ci.yml` under a `deploy` job with `needs: [ci]`, runs only on `push` to `main`:
   - Railway CLI deploy: `railway up --service backend`.
   - Vercel CLI deploy: `vercel --prod`.
   - Secrets: `RAILWAY_TOKEN`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` set in GitHub Secrets.
5. Document all required Railway environment variables in a comment in `railway.json`.

**Acceptance Criteria:**
- Merging a PR to `main` triggers deploy.
- `GET https://your-backend.railway.app/health` returns 200.
- Frontend is served at Vercel production URL.
- No secrets in any committed file.

**Dependencies:** T-040

---

## Phase 3 — Hardening and Quality

---

### T-045: AES-256 Key Vault

**Description:**
Implement the encrypted key vault using Fernet (AES-256) for storing any sensitive values that may need encryption at rest.

**Inputs:**
- plan.md Section 2 (Encryption: cryptography Fernet)
- `backend/config.py` (ENCRYPTION_MASTER_KEY)

**Outputs:**
- `backend/services/security/key_vault.py`

**Steps:**
1. Create `backend/services/security/key_vault.py`:
   - `encrypt(plaintext: str) -> str`: uses `Fernet(settings.encryption_master_key)`. Returns base64 ciphertext.
   - `decrypt(ciphertext: str) -> str`: decrypts. Raises `DecryptionError` on invalid ciphertext.
2. V1 usage: the vault is wired into the system but not yet storing any per-user keys (user-provided API keys are out of scope for V1). The vault is ready for V2. Document this in a module docstring.
3. Unit test both functions.

**Acceptance Criteria:**
- `encrypt(decrypt(x)) == x` for any string.
- `decrypt("invalid")` raises `DecryptionError`.
- Master key never logged (verify `SensitiveDataFilter` in T-039 covers `encryption_master_key`).

**Dependencies:** T-039

---

### T-046: Rate Limiting — LLM Tier

**Description:**
Apply per-user LLM rate limits inside the Stage Manager as defined in spec.md.

**Inputs:**
- spec.md Section 12 (Rate Limits — User LLM tiers)
- `backend/middleware/rate_limit.py` (from T-012)

**Outputs:**
- Updated `backend/services/pipeline/stage_manager.py`

**Steps:**
1. In `stage_manager.generate()` and `stage_manager.refine()`, before deducting credits:
   - Call `sliding_window_check(redis, f"ratelimit:llm:{user.id}", limit=10, window=60)`. If False: raise `RateLimitError(retry_after=60)`.
   - Call `sliding_window_check(redis, f"ratelimit:llm_daily:{user.id}", limit=200, window=86400)`. If False: raise `RateLimitError(retry_after=86400)`.
2. In `stage.py` router: catch `RateLimitError`, return `429` with `Retry-After` header.

**Acceptance Criteria:**
- Unit test: 11th LLM call within 60 seconds raises `RateLimitError`.
- Integration test: `POST /stages/{id}/generate` on 11th call returns 429.

**Dependencies:** T-025, T-012

---

### T-047: Backend Unit Test Suite — Full Coverage Pass

**Description:**
Achieve 80% line coverage across `services/` by filling test gaps revealed by the coverage report.

**Inputs:**
- All `backend/services/` files
- Coverage report from existing tests

**Outputs:**
- Filled gaps in `backend/tests/unit/`

**Steps:**
1. Run `pytest --cov=services --cov-report=html` and open the report.
2. Identify all lines in `services/` under coverage.
3. Write unit tests for uncovered paths. Priority order:
   - `credit_service.py` edge cases (zero balance, exact balance deduction)
   - `stage_manager.py` error paths (provider error mid-stream, validation failure)
   - `auth_service.py` token expiry edge cases
   - `export_service.py` harness parse fallback path
   - `online_eval.py` judge JSON parse failure path
4. Run coverage again. All lines in `services/` must be ≥ 80%.

**Acceptance Criteria:**
- `pytest --cov=services --cov-fail-under=80` exits 0.
- No test has an assertion of `assert True` (mock coverage only — real assertions required).

**Dependencies:** T-040

---

### T-048: Frontend Integration Test Pass

**Description:**
Write Vitest component tests covering the critical workspace interaction paths.

**Inputs:**
- All workspace components (T-033 to T-038)

**Outputs:**
- `frontend/src/__tests__/WorkspaceFlow.test.tsx`
- `frontend/src/__tests__/CreditSystem.test.tsx`

**Steps:**
1. Create `WorkspaceFlow.test.tsx`:
   - Test: `StageNavigator` renders locked stages as non-clickable.
   - Test: `GenerateBar` shows spinner during `in_progress` status.
   - Test: `StalenessWarning` renders when stage status is `stale`.
   - Test: `HumanReviewGate` is not shown when `review_gate_acknowledged = true`.
2. Create `CreditSystem.test.tsx`:
   - Test: `CreditBanner` shows "used all credits" message when balance = 0.
   - Test: `CreditConfirmModal` displays correct credit cost and remaining balance.
   - Test: `CreditMeter` color is red when balance ≤ 5.
3. All tests mock API calls via `vi.mock('../services/api')`.

**Acceptance Criteria:**
- `pnpm vitest run` exits 0 with all tests passing.
- No test timeouts.

**Dependencies:** T-038

---

### T-049: End-to-End Smoke Test — Manual Checklist

**Description:**
Define and execute the manual smoke test checklist against the staging environment before production launch.

**Inputs:**
- spec.md Section 4 (all user flows)

**Outputs:**
- `docs/SMOKE_TEST_CHECKLIST.md` (documented results)

**Steps:**
1. Create `docs/SMOKE_TEST_CHECKLIST.md` with the following manual test items. Tester signs off each item with pass/fail/notes.
2. Checklist items:
   - [ ] New user signs in with Google and receives 50 credits.
   - [ ] Create workspace with valid name and problem statement → workspace page opens.
   - [ ] Create workspace with problem statement under 50 chars → validation error shown.
   - [ ] Generate SPEC.md → tokens stream into editor, quality badge appears after ~5s.
   - [ ] Refine a selected section → diff viewer appears → accept → content updates.
   - [ ] Finalise SPEC → PLAN unlocks in navigator.
   - [ ] Human review gate appears before first PLAN generation → acknowledged → generates.
   - [ ] Edit finalised SPEC → PLAN, HARNESS, TASKS all show stale warning.
   - [ ] Complete full pipeline (SPEC → PLAN → HARNESS → TASKS all finalised).
   - [ ] Export zip downloads and contains all 4 files.
   - [ ] Credit balance decreases by correct amount after each action.
   - [ ] Credit balance reaches 0 → exhaustion state shown.
   - [ ] Rollback to previous version → stage reverts to prior content.
   - [ ] `GET /health` returns 200 in staging.
   - [ ] `GET /metrics` returns Prometheus metrics in staging.
3. Execute checklist against staging URL. Record results.

**Acceptance Criteria:**
- All checklist items pass.
- Any failure is filed as a bug and fixed before production deploy.

**Dependencies:** T-044

---

---

## Phase 4 — Gap Closure (Post-Audit)

_Identified during codebase audit on 2026-05-01. All items are in scope per spec/plan but were not tasked. See Plan v1.md §10 for rationale._

---

### T-050: CSRF Middleware

**Description:**
Implement HMAC-based CSRF token generation, verification, and middleware as required by the spec security architecture. `csrf_secret` is already in config but no implementation exists.

**Inputs:**
- `backend/config.py` (`csrf_secret: str` already present)
- spec.md §7 Security Architecture ("CSRF: SameSite=Strict cookies · HMAC CSRF tokens on mutations")
- Plan v1.md §3.1 (`services/security/csrf.py`)

**Outputs:**
- `backend/services/security/csrf.py`
- Updated `backend/main.py` (register CSRF middleware)
- `backend/tests/test_csrf.py`

**Steps:**
1. Create `backend/services/security/csrf.py`:
   - `generate_csrf_token(session_id: str) -> str`: HMAC-SHA256 of `session_id + timestamp` using `settings.csrf_secret`. Return `{timestamp}.{hmac}` signed token.
   - `verify_csrf_token(token: str, session_id: str, max_age_seconds: int = 3600) -> bool`: Parse token, check HMAC, check timestamp not older than `max_age_seconds`.
2. Create `backend/middleware/csrf.py`:
   - `CsrfMiddleware(BaseHTTPMiddleware)`: skip safe methods (GET, HEAD, OPTIONS). For mutating methods (POST, PUT, PATCH, DELETE): read `X-CSRF-Token` header; extract session identifier from the access token sub claim (from `Authorization` header); call `verify_csrf_token()`; return 403 if invalid.
   - Exempt paths: `/auth/google`, `/auth/callback`, `/auth/refresh` (OAuth callbacks can't set custom headers).
3. Register `CsrfMiddleware` in `main.py` after `RateLimitMiddleware`.
4. Update `frontend/src/services/api.ts`: add request interceptor that fetches a CSRF token from `GET /auth/csrf-token` and attaches it as `X-CSRF-Token` header on all mutating requests.
5. Add `GET /auth/csrf-token` endpoint to `routers/auth.py`: requires `get_current_user`, returns `{"csrf_token": generate_csrf_token(str(user.id))}`.
6. Write `backend/tests/test_csrf.py`:
   - Test: `generate_csrf_token` and `verify_csrf_token` roundtrip passes.
   - Test: tampered HMAC fails verification.
   - Test: expired token (age > max_age) fails.

**Acceptance Criteria:**
- `POST /workspaces` without `X-CSRF-Token` returns 403.
- `POST /workspaces` with valid `X-CSRF-Token` returns 201.
- Auth callback endpoints are exempt.
- `ruff check .` and `black --check .` pass.

**Dependencies:** T-011

---

### T-051: Input Sanitization with Bleach

**Description:**
Apply `bleach.clean()` to all user-supplied text fields before persistence, as required by the plan. The `bleach==6.*` package is already installed but never called.

**Inputs:**
- `backend/pyproject.toml` (`bleach==6.*` already present)
- Plan v1.md §2 ("bleach: HTML stripping on all user text fields before persistence")

**Outputs:**
- `backend/services/security/sanitizer.py`
- Updated `backend/services/workspace_service.py`
- Updated `backend/routers/stage.py` (refine instruction)
- `backend/tests/test_sanitizer.py`

**Steps:**
1. Create `backend/services/security/sanitizer.py`:
   - `sanitize_text(text: str) -> str`: calls `bleach.clean(text, tags=[], strip=True)`. Strips all HTML tags. Returns plain text.
2. Apply in `workspace_service.create()`: sanitize `name` and `problem_statement` before creating the `Workspace` record.
3. Apply in `workspace_service.update()`: sanitize `name` before update.
4. Apply in `stage.py` refine endpoint: sanitize `instruction` before passing to `stage_manager.refine()`.
5. Write `backend/tests/test_sanitizer.py`:
   - Test: `sanitize_text("<script>alert('xss')</script>hello")` returns `"hello"`.
   - Test: plain text is unchanged.
   - Test: nested tags stripped: `"<b><i>text</i></b>"` returns `"text"`.

**Acceptance Criteria:**
- `<script>` tags in workspace name or problem statement are stripped before DB insert.
- `sanitize_text` is called on all user text inputs in service methods.
- `ruff check .` and `black --check .` pass.

**Dependencies:** T-020

---

### T-052: Hourly Auth Rate Limit Tier

**Description:**
Add the hourly auth login rate limit (20 attempts / 1 hour per IP) to `RateLimitMiddleware`, as explicitly listed in the spec security table. Only the 5-per-5-minute tier is currently implemented.

**Inputs:**
- spec.md §7 Security Table ("Auth Login Per IP hourly: 20 attempts / 1 hour")
- `backend/middleware/rate_limit.py`

**Outputs:**
- Updated `backend/middleware/rate_limit.py`
- Updated `backend/tests/test_rate_limit.py`

**Steps:**
1. In `RateLimitMiddleware.__call__()`, after the existing 5/300s login check, add:
   ```python
   if not await sliding_window_check(self._redis, f"login_hourly:{ip}", 20, 3600):
       return Response("Rate limit exceeded", status_code=429, headers={"Retry-After": "3600"})
   ```
   Apply only on `/auth/google` and `/auth/callback` paths (same as the 5/5min check).
2. Add unit test in `test_rate_limit.py`:
   - Test: 21st login attempt within 1 hour returns 429.
   - Test: 20th attempt is allowed.

**Acceptance Criteria:**
- 21 login attempts within 1 hour from the same IP result in 429 on the 21st.
- Existing 5/5min tier continues to function independently.
- `ruff check .` and `black --check .` pass.

**Dependencies:** T-012

---

### T-053: Sentry Initialization

**Description:**
Initialize missing frontend Sentry error tracking and ensure backend Sentry remains wired through the observability abstraction. Both SDKs are installed. Backend `sentry_sdk.init()` already exists in `backend/services/observability.py` and is invoked by `setup_observability()` from `main.py`; frontend `Sentry.init()` is still missing.

**Inputs:**
- `backend/config.py` (`sentry_dsn: str` already present)
- `frontend/.env.example` (`VITE_SENTRY_DSN` already present)
- Plan v1.md §2 (sentry-sdk[fastapi] + @sentry/react)

**Outputs:**
- Updated `harness/tests/backend/test_phase4_contract.py` if the harness still requires inline `sentry_sdk.init()` in `main.py` instead of accepting `setup_observability()`
- Updated `frontend/src/main.tsx`

**Steps:**
1. Verify backend Sentry initialization remains in `services/observability.py::setup_sentry()` and is invoked by `main.py::create_app()` via `setup_observability(app, async_engine)`.
2. If the Phase 4 backend harness still checks only `main.py`, update that harness assertion to accept the existing `setup_observability()` call and `services/observability.py::setup_sentry()`. Do not duplicate Sentry initialization in `main.py`.
3. In `frontend/src/main.tsx`, add before `ReactDOM.createRoot`:
   ```typescript
   import * as Sentry from "@sentry/react"
   if (import.meta.env.VITE_SENTRY_DSN) {
     Sentry.init({
       dsn: import.meta.env.VITE_SENTRY_DSN,
       integrations: [Sentry.browserTracingIntegration()],
       tracesSampleRate: 0.1,
     })
   }
   ```
4. Run `pnpm tsc --noEmit` to verify no type errors.
5. Verify backend starts without error when `SENTRY_DSN` is unset.

**Acceptance Criteria:**
- Backend starts cleanly with `SENTRY_DSN` unset (empty string or missing).
- Frontend builds cleanly with `VITE_SENTRY_DSN` unset.
- `pnpm tsc --noEmit` exits 0.
- `ruff check .` and `black --check .` pass.

**Dependencies:** T-039

---

### T-054: StreamingOverlay Component

**Description:**
Implement the `StreamingOverlay` component that renders over the `StageEditor` while an SSE stream is active. Listed in the plan's component directory but not yet built. The editor is already `readOnly` during streaming; this adds the required visual feedback (animated cursor, generating label).

**Inputs:**
- Plan v1.md §3.2 ("StreamingOverlay.tsx — Mounted over editor during active stream. Shows cursor animation. Prevents user edits during generation.")
- `frontend/src/pages/Workspace.tsx` (`isStreaming` state available)

**Outputs:**
- `frontend/src/components/workspace/StreamingOverlay.tsx`
- Updated `frontend/src/pages/Workspace.tsx` (mount overlay when streaming)

**Steps:**
1. Create `frontend/src/components/workspace/StreamingOverlay.tsx`:
   - Props: `isVisible: boolean`.
   - When `isVisible=true`: render a semi-transparent overlay `div` positioned `absolute inset-0` over the editor container. Show a blinking cursor animation (CSS `animate-pulse`) and a "Generating…" label at the bottom-right. Use `pointer-events: none` so the overlay does not intercept scroll.
   - When `isVisible=false`: return `null`.
2. In `Workspace.tsx`, wrap the editor container in a `relative` positioned div. Mount `<StreamingOverlay isVisible={isStreaming} />` inside it.
3. Run `pnpm tsc --noEmit` to verify no type errors.

**Acceptance Criteria:**
- Overlay appears over editor when `isStreaming=true`.
- Overlay disappears when streaming completes.
- Underlying editor is still visible through the overlay (semi-transparent).
- `pnpm tsc --noEmit` exits 0.

**Dependencies:** T-034, T-038

---

### T-055: Quality Badge in StageNavigator

**Description:**
Display the eval quality score next to each stage name in the `StageNavigator`, as required by T-033's acceptance criteria: "Quality badge (score number) shown if eval_result present on stage." Currently the badge only appears in the workspace header for the active stage.

**Inputs:**
- `frontend/src/components/workspace/StageNavigator.tsx`
- `frontend/src/components/workspace/QualityBadge.tsx`
- `frontend/src/types/stage.ts` (`Stage.eval_result: EvalResult | null`)

**Outputs:**
- Updated `frontend/src/components/workspace/StageNavigator.tsx`
- Updated `frontend/src/__tests__/WorkspaceFlow.test.tsx` (add test for badge visibility)

**Steps:**
1. Update `StageNavigator.tsx`:
   - If `stage.eval_result` is non-null, render a small score badge in the stage row alongside the status dot and label.
   - Badge: `<span className="ml-auto text-xs font-medium text-on-surface-variant">{stage.eval_result.overall_score}</span>`.
   - Color: green if ≥ 80, amber if 60–79, red if < 60 (mirror the `QualityBadge` thresholds).
   - Do not import `QualityBadge` — render inline to avoid circular component coupling. The navigator badge is text-only (number), not the full badge component.
2. Add test in `WorkspaceFlow.test.tsx`:
   - Test: stage with `eval_result.overall_score = 85` shows `"85"` in the navigator.
   - Test: stage with `eval_result = null` does not show a score.
3. Run `pnpm tsc --noEmit` and `pnpm test` to verify.

**Acceptance Criteria:**
- Eval score number visible in StageNavigator when `eval_result` is present.
- No score shown when `eval_result` is null.
- Score color matches quality thresholds (green/amber/red).
- All Vitest tests pass.

**Dependencies:** T-033, T-026

---

### T-056: Dockerfile and README Quickstart

**Description:**
Add the `backend/Dockerfile` required for self-hosting and expand `README.md` with a working quickstart guide. Both are specified in the spec's open-source strategy but are missing. Without them the self-hosting flow described in the spec ("clone → copy .env → docker-compose up → open localhost:5173") does not work.

**Inputs:**
- spec.md §12 open-source strategy ("Self-Hosting in Four Steps")
- `docker-compose.yml` (already exists with db + redis services)
- `backend/Procfile` (gunicorn command already defined)

**Outputs:**
- `backend/Dockerfile`
- Updated `docker-compose.yml` (add `api` service)
- Updated `README.md`

**Steps:**
1. Create `backend/Dockerfile`:
   ```dockerfile
   FROM python:3.12-slim
   WORKDIR /app
   RUN pip install uv
   COPY pyproject.toml uv.lock ./
   RUN uv sync --frozen --no-dev
   COPY . .
   EXPOSE 8000
   CMD ["uv", "run", "gunicorn", "main:app", "--worker-class", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:8000"]
   ```
2. Update `docker-compose.yml`: add `api` service:
   ```yaml
   api:
     build: ./backend
     ports: ["8000:8000"]
     env_file: backend/.env
     depends_on:
       db:
         condition: service_healthy
       redis:
         condition: service_healthy
     volumes:
       - ./backend:/app
     command: uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
3. Rewrite `README.md` with:
   - Project title + one-line description.
   - Screenshot or ASCII diagram of the 4-stage pipeline.
   - **Self-Hosting (4 steps)**: clone, copy `.env.example` to `.env` and fill API keys, `docker-compose up`, open `localhost:5173`.
   - **Development Setup**: separate backend (`uv run uvicorn`) and frontend (`pnpm dev`) commands.
   - Required environment variables table.
   - Link to `docs/SMOKE_TEST_CHECKLIST.md` for verification.

**Acceptance Criteria:**
- `docker-compose up --build` starts all three services (db, redis, api) without error.
- `GET localhost:8000/health` returns 200 after `docker-compose up`.
- `README.md` contains self-hosting instructions that match the spec's four-step flow.
- Frontend `pnpm dev` still works (no regression to existing dev setup).

**Dependencies:** T-003, T-044

---

### T-057: Fix Google Login Redirect Contract

**Description:**
Fix the frontend/backend contract mismatch for Google OAuth initiation. The backend returns `redirect_url`, while the landing page reads `url`, breaking the sign-in button.

**Inputs:**
- `backend/routers/auth.py`
- `frontend/src/pages/Landing.tsx`
- `backend/tests/test_auth_router.py`

**Outputs:**
- Updated `frontend/src/pages/Landing.tsx`
- Updated or added frontend test for Google sign-in redirect handling

**Steps:**
1. Update `Landing.tsx` response typing to `{ redirect_url: string }`.
2. Change `window.location.assign(res.data.url)` to `window.location.assign(res.data.redirect_url)`.
3. Add a focused frontend test that mocks `api.post("/auth/google")` and asserts `window.location.assign()` receives the backend `redirect_url`.
4. Keep the backend response shape unchanged because existing backend tests and API contract use `redirect_url`.

**Acceptance Criteria:**
- Clicking "Sign in with Google" redirects to the URL returned by `POST /auth/google`.
- Backend auth router tests still pass.
- Frontend test covers the response field.
- `pnpm tsc --noEmit` and relevant Vitest tests pass.

**Dependencies:** T-031

---

### T-058: Remove Access Token localStorage Fallback

**Description:**
Enforce the spec rule that access tokens live in JS memory only. `api.ts` currently avoids writing access tokens to localStorage but still reads `localStorage.getItem("access_token")`.

**Inputs:**
- Spec §8 Token Storage
- `frontend/src/services/api.ts`
- `harness/tests/frontend/api.contract.test.ts`

**Outputs:**
- Updated `frontend/src/services/api.ts`
- Updated frontend/harness API contract test to reject localStorage/sessionStorage reads for access tokens

**Steps:**
1. Remove the `localStorage.getItem("access_token")` fallback from `getAccessToken()`.
2. Ensure `setAccessToken()` is the only way the API client receives an access token.
3. Update tests to assert no `localStorage` or `sessionStorage` access is used for access-token storage or retrieval.
4. Verify refresh flow still stores the refreshed token in memory via `setAccessToken(refreshedToken)`.

**Acceptance Criteria:**
- `frontend/src/services/api.ts` contains no localStorage/sessionStorage access for access tokens.
- Existing refresh retry behavior still works.
- `pnpm tsc --noEmit` and frontend API contract tests pass.

**Dependencies:** T-005, T-031

---

### T-059: Harden Refresh Cookie Attributes

**Description:**
Set refresh token cookies exactly as required by the spec: `httpOnly`, `Secure`, `SameSite=Strict`, scoped to `/auth/refresh`.

**Inputs:**
- Spec §8 Token Storage
- Plan v1.md §4.4 Authentication Token Lifecycle
- `backend/routers/auth.py`
- `backend/tests/test_auth_router.py`

**Outputs:**
- Updated `backend/routers/auth.py`
- Updated backend auth router tests

**Steps:**
1. Change `_set_refresh_cookie()` from `samesite="lax"` to `samesite="strict"`.
2. Add `path="/auth/refresh"` when setting the refresh cookie.
3. Ensure `delete_cookie()` uses the same `path="/auth/refresh"` so logout clears the cookie.
4. Update tests to assert `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/auth/refresh`, and `Max-Age=604800`.

**Acceptance Criteria:**
- Refresh cookie has the required security attributes.
- Logout clears the scoped refresh cookie.
- Backend auth router tests pass.

**Dependencies:** T-011

---

### T-060: Refresh Token Reuse Revokes All Sessions

**Description:**
Implement full session revocation when refresh-token reuse is detected. The current flow detects a missing session key and raises an auth error, but leaves other active sessions untouched.

**Inputs:**
- Spec §8 Session Management
- Plan v1.md §4.4 Authentication Token Lifecycle
- `backend/services/auth_service.py`
- `backend/tests/test_auth_service.py`

**Outputs:**
- Updated `backend/services/auth_service.py`
- Updated auth service tests

**Steps:**
1. Store a per-user session index when creating refresh sessions, e.g. `user_sessions:{user_id}` containing active refresh JTIs.
2. When rotating a refresh token, remove the old JTI from the user's session index and add the new JTI.
3. If `refresh_tokens()` receives a token whose `session:{jti}` is missing, call a new helper that deletes every session key in `user_sessions:{user_id}` and clears that index.
4. Ensure `revoke()` removes the JTI from the user session index for normal logout.
5. Add tests for normal rotation and reuse detection revoking all sessions.

**Acceptance Criteria:**
- Reusing an already-rotated refresh token deletes all active refresh sessions for that user.
- Normal refresh rotation keeps exactly one replacement session active for that browser.
- Logout revokes only the presented refresh token.
- Backend auth service tests pass.

**Dependencies:** T-009, T-011

---

### T-061: Provider-Specific Eval Judge Selection

**Description:**
Make online evals use the judge model for the workspace provider instead of always using Anthropic Haiku. This matches the plan and avoids requiring an Anthropic key for OpenAI/Google workspaces.

**Inputs:**
- Spec §7 Online Evals
- Plan v1.md §3 evals
- `backend/services/evals/online_eval.py`
- `backend/services/llm/gateway.py`
- `backend/services/llm/provider_config.py`
- `backend/services/pipeline/stage_manager.py`

**Outputs:**
- Updated `backend/services/evals/online_eval.py`
- Updated `backend/services/pipeline/stage_manager.py`
- Updated eval tests

**Steps:**
1. Extend `run_eval()` to accept `provider: str` and `judge_model: str`.
2. Resolve `judge_model` from provider config for the workspace provider.
3. Use `get_llm(provider, judge_model)` instead of `AnthropicAdapter(_JUDGE_MODEL)`.
4. Pass workspace provider and judge model from `stage_manager.generate()`.
5. Add tests proving Anthropic, OpenAI, and Google workspaces dispatch to the expected judge provider/model.

**Acceptance Criteria:**
- Evals for OpenAI workspaces use the OpenAI judge model.
- Evals for Google workspaces use the Google judge model.
- Evals for Anthropic workspaces use the Anthropic judge model.
- Existing eval result persistence behavior remains unchanged.

**Dependencies:** T-013, T-026

---

### T-062: Isolate Background Eval Database Session

**Description:**
Prevent background eval tasks from using the request-scoped `AsyncSession`. `stage_manager.generate()` currently passes `db` into `asyncio.create_task()`, which can outlive the streaming request lifecycle.

**Inputs:**
- Plan v1.md §3 Async Eval Trigger
- `backend/services/pipeline/stage_manager.py`
- `backend/services/evals/online_eval.py`
- `backend/database.py`

**Outputs:**
- Updated `backend/services/evals/online_eval.py` or new eval task helper
- Updated `backend/services/pipeline/stage_manager.py`
- Updated tests for background eval scheduling

**Steps:**
1. Create a helper such as `run_eval_background(...)` that opens its own `AsyncSessionLocal()` inside the background task.
2. Keep `run_eval(..., db)` usable for direct unit tests if helpful, but do not pass request-scoped sessions into `asyncio.create_task()`.
3. Update `stage_manager.generate()` to schedule the background helper with primitive values only: version id, stage type, content, spec content, provider, judge model.
4. Add tests that assert the background helper creates/closes its own DB session.

**Acceptance Criteria:**
- No request-scoped `AsyncSession` is captured by an eval background task.
- Eval persistence still works.
- Generate streaming still sends `[done]` without waiting for eval completion.
- Backend eval/stage manager tests pass.

**Dependencies:** T-026, T-061

---

### T-063: Secure and Refund Refine Flow

**Description:**
Bring refine up to the same security and credit-safety standard as generate. Refine currently does not scan prompt-injection input, does not validate model output, and does not refund credits on provider failure.

**Inputs:**
- Spec §6 Refine
- Spec §12 Reliability/Security
- `backend/services/pipeline/stage_manager.py`
- `backend/services/security/prompt_guard.py`
- `backend/services/security/output_validator.py`
- `backend/tests/test_stage_manager.py`

**Outputs:**
- Updated `backend/services/pipeline/stage_manager.py`
- Updated stage manager tests

**Steps:**
1. Run `scan()` on `request.instruction` and `request.selected_text` before the LLM call.
2. If prompt guard rejects input, do not deduct credits and raise `SecurityError`.
3. Wrap `adapter.complete()` in provider-error handling; refund the deduction on provider failure.
4. Run `validate()` on the replacement text; refund and raise `SecurityError` if validation fails.
5. Add tests for injection rejection, provider-error refund, output-validation refund, and successful diff generation.

**Acceptance Criteria:**
- Unsafe refine input is rejected before any credit deduction or LLM call.
- Provider failure during refine refunds credits.
- Unsafe LLM replacement output refunds credits and is not returned.
- Stage manager tests pass.

**Dependencies:** T-022, T-024

---

### T-064: Resolve Refine Billing Semantics

**Description:**
Align refine billing with the spec: "Cost: 3 credits (only on acceptance)." The current implementation deducts before returning the diff and refunds on reject.

**Inputs:**
- Spec §6 Refine
- `backend/services/pipeline/stage_manager.py`
- `backend/routers/stage.py`
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/services/api.ts`

**Outputs:**
- Updated backend refine/accept/reject flow
- Updated frontend diff accept/reject flow
- Updated credit and stage manager tests

**Steps:**
1. Choose and document the final product contract in code comments/tests: refine preview is free; accepting the diff costs 3 credits.
2. Remove pre-deduction from `stage_manager.refine()`.
3. Deduct 3 credits in the accept-diff path before saving accepted content.
4. If accept persistence fails after deduction, refund the deduction.
5. Remove `ledger_id` from `DiffResponse` and frontend reject-diff payload if no longer needed.
6. Update tests and types to reflect "deduct on accept, no refund needed on reject."

**Acceptance Criteria:**
- Rejecting a refine diff never changes credit balance.
- Accepting a refine diff deducts exactly 3 credits.
- Failed accept after deduction refunds credits.
- Frontend no longer requires a refine ledger id for reject.
- Backend and frontend tests pass.

**Dependencies:** T-023, T-024, T-035, T-063

---

### T-065: Return 404 for Cross-User Workspace Access

**Description:**
Fix workspace ownership checks to avoid IDOR information leakage. The architecture requires 404, not 403, when a resource exists but is owned by another user.

**Inputs:**
- Architecture §7 IDOR Prevention
- `backend/services/workspace_service.py`
- `backend/routers/workspace.py`
- `backend/tests/test_workspace.py`

**Outputs:**
- Updated `backend/services/workspace_service.py`
- Updated workspace tests

**Steps:**
1. Change `WorkspaceService.get()` to raise 404 for both missing workspace and wrong owner.
2. Ensure `update()` and `archive()` inherit the same 404 behavior.
3. Add tests proving a user cannot distinguish "missing" from "owned by someone else."
4. Verify stage routes already use 404 for cross-user stage access and leave them unchanged.

**Acceptance Criteria:**
- Cross-user `GET /workspaces/{id}` returns 404.
- Cross-user `PATCH /workspaces/{id}` returns 404.
- Cross-user `DELETE /workspaces/{id}` returns 404.
- Workspace tests pass.

**Dependencies:** T-020

---

### T-066: Sensitive Data Redaction for Logs and Sentry

**Description:**
Add a central redaction layer so secrets are scrubbed before reaching structlog, Loki/Grafana, or Sentry. The architecture claims a `SensitiveDataFilter`, but no such filter currently exists.

**Inputs:**
- Architecture §7 API Key Vault
- Spec §12 Observability
- `backend/services/observability.py`
- `backend/tests/test_observability.py`

**Outputs:**
- Updated `backend/services/observability.py`
- Updated observability tests

**Steps:**
1. Implement a redaction helper that masks likely secrets: bearer tokens, `sk-...` keys, Anthropic/OpenAI/Google API keys, private key PEM bodies, refresh tokens, and `Authorization` header values.
2. Add the helper as a structlog processor before JSON rendering.
3. Add a standard logging `Filter` if needed so non-structlog records are scrubbed too.
4. Configure Sentry `before_send` to scrub event data using the same helper.
5. Add tests that log representative secrets and assert output contains `[REDACTED]` rather than the original value.

**Acceptance Criteria:**
- Secrets are redacted from structlog JSON output.
- Sentry events are scrubbed before send.
- Non-secret log fields remain readable.
- Observability tests pass.

**Dependencies:** T-039, T-045, T-053

---

---

## Phase 5: Code Review Mitigation Tasks

---

### T-067: Fix Credit Service SELECT SUM + FOR UPDATE PostgreSQL Crash

**Description:**
`credit_service.deduct()` calls `.with_for_update()` on a `select(func.sum(...))` aggregate query. PostgreSQL rejects `SELECT SUM(...) FOR UPDATE` at runtime — aggregate queries cannot hold row locks. Every concurrent deduction crashes in production; tests pass only because fakes ignore the clause.

**Severity:** Critical (C1)

**Inputs:**
- `backend/services/credit_service.py` — `deduct()` method
- `backend/tests/test_credit_service.py`

**Outputs:**
- Fixed `credit_service.py` using a two-step select-then-lock pattern
- Updated or new unit/integration tests that exercise concurrent deductions

**Steps:**
1. Replace the `select(func.sum(...)).with_for_update()` call with a two-step approach: first lock a sentinel row (or use an advisory lock), then sum.
2. Preferred pattern: select all `CreditLedger` rows `FOR UPDATE` for the user, compute the sum in Python, then insert the debit row — all within one transaction.
3. Alternatively, lock a `users` row (`SELECT ... FOR UPDATE`) before computing the sum to serialize concurrent deductions.
4. Ensure `refund()` runs in the same transaction scope so over-refund cannot race.
5. Add an integration test using two concurrent `asyncio` tasks to verify no double-spend.

**Acceptance Criteria:**
- No `with_for_update()` on any aggregate (`func.sum`, `func.count`, etc.) in `credit_service.py`.
- Integration test simulating concurrent deductions passes without raising a PostgreSQL error.
- Existing credit service tests continue to pass.

**Finding:** C1 — `backend/services/credit_service.py`

**Dependencies:** T-081

---

### T-068: Implement OAuth State Parameter CSRF Protection

**Description:**
`auth_service.get_google_auth_url()` discards the OAuth `state` parameter (`authorization_url, _state = ...`). Without storing and verifying `state`, any attacker can craft a callback URL and log in as an arbitrary Google user (login-CSRF). The callback endpoint has no `state` parameter at all.

**Severity:** Critical (C2)

**Inputs:**
- `backend/services/auth_service.py` — `get_google_auth_url()`, `handle_callback()`
- `backend/routers/auth.py` — `/auth/google` and `/auth/callback` handlers
- Redis (already available for session storage)

**Outputs:**
- Updated `auth_service.py` storing `state` in Redis with TTL
- Updated `/auth/callback` route that accepts and verifies `state`
- Tests asserting mismatched / missing state returns 401

**Steps:**
1. In `get_google_auth_url()`, capture `_state` and store it in Redis with a 10-minute TTL: `await redis.setex(f"oauth:state:{state}", 600, "1")`.
2. Return `state` alongside the URL (or embed it so the frontend can pass it back).
3. Add `state: str` to the `/auth/callback` query parameters.
4. In `handle_callback()`, look up `oauth:state:{state}` in Redis; raise `AuthError` if missing or expired, then delete the key.
5. Add tests: valid state succeeds; missing state → 401; reused state → 401.

**Acceptance Criteria:**
- `get_google_auth_url()` stores `state` in Redis.
- `/auth/callback` requires a matching `state` parameter.
- Replayed or forged state returns HTTP 401.
- Unit tests cover all three cases.

**Finding:** C2 — `backend/services/auth_service.py`

**Dependencies:** none

---

### T-069: Remove JWT Token Query Parameter from Auth Middleware

**Description:**
`backend/middleware/auth.py` accepts `?token=<JWT>` as a query parameter fallback. Query parameters are written to every proxy log, browser history, and server access log — effectively leaking the access token in plaintext to every intermediary.

**Severity:** Critical (C3)

**Inputs:**
- `backend/middleware/auth.py` — `token_param` / `alias="token"` extraction

**Outputs:**
- Updated middleware that only reads the `Authorization: Bearer` header
- Updated tests confirming query-param tokens are rejected

**Steps:**
1. Remove the `token_param: str | None = Query(default=None, alias="token")` extraction.
2. Remove the fallback `token = token_param or header_token` logic.
3. Return 401 if no `Authorization: Bearer` header is present.
4. Update any test that sends tokens as query parameters to use the header instead.

**Acceptance Criteria:**
- No `Query(... alias="token")` or `token_param` reference in `auth.py`.
- Requests with `?token=...` and no `Authorization` header receive HTTP 401.
- Existing bearer-header tests still pass.

**Finding:** C3 — `backend/middleware/auth.py`

**Dependencies:** none

---

### T-070: Fix Rollback API Field Name Mismatch

**Description:**
`frontend/src/services/api.ts` calls `POST /stages/{id}/rollback` with body `{ version }`, but the backend `RollbackRequest` schema expects `{ version_number }`. The rollback feature is completely broken end-to-end — every call returns HTTP 422.

**Severity:** Critical (C4)

**Inputs:**
- `frontend/src/services/api.ts` — `rollbackStage()` function
- `backend/schemas/stage.py` — `RollbackRequest` model

**Outputs:**
- Fixed `api.ts` sending `version_number`
- Smoke test or existing harness test going green

**Steps:**
1. In `api.ts`, change `{ version }` to `{ version_number: version }` in the `rollbackStage()` call.
2. Verify no other callers pass `{ version }` to the rollback endpoint.
3. Confirm the Phase 5 harness test for C4 passes.

**Acceptance Criteria:**
- `api.ts` sends `version_number` in the rollback request body.
- No HTTP 422 from the rollback endpoint when called with a valid version number.
- Harness test `test_c4_rollback_field_name` passes.

**Finding:** C4 — `frontend/src/services/api.ts`

**Dependencies:** none

---

### T-071: Add Missing Database Indexes

**Description:**
The initial Alembic migration (`0001_initial_schema.py`) creates no indexes beyond primary keys. Foreign-key columns and frequently-queried columns are unindexed, causing full table scans as data grows: `credit_ledger(user_id)`, `stages(workspace_id)`, `stage_versions(stage_id)`, `workspaces(user_id)`, `eval_results(stage_version_id)`, `stages(status)`, `stages(updated_at)`.

**Severity:** Critical (C5)

**Inputs:**
- `backend/migrations/versions/0001_initial_schema.py`
- `backend/models/` — all model definitions

**Outputs:**
- New migration `backend/migrations/versions/0002_add_indexes.py`
- All listed indexes created

**Steps:**
1. Run `alembic revision --autogenerate -m "add_indexes"` or write the migration manually.
2. Add `op.create_index` calls for: `ix_credit_ledger_user_id`, `ix_stages_workspace_id`, `ix_stage_versions_stage_id`, `ix_workspaces_user_id`, `ix_eval_results_stage_version_id`, `ix_stages_status`, `ix_stages_updated_at`.
3. Add corresponding `op.drop_index` in the `downgrade()` function.
4. Run `alembic upgrade head` against a test DB to confirm migration applies cleanly.
5. Add a harness test that inspects the migration file for the expected index names.

**Acceptance Criteria:**
- `0002_add_indexes.py` migration exists and is auto-discovered by Alembic.
- All seven indexes are created in `upgrade()` and dropped in `downgrade()`.
- `alembic upgrade head` succeeds on a clean database.
- Harness test `test_c5_index_migration_exists` passes.

**Finding:** C5 — `backend/migrations/versions/`

**Dependencies:** none

---

### T-072: Protect Prometheus /metrics Endpoint

**Description:**
The `/metrics` endpoint is public — any external party can scrape internal performance data, error rates, and queue depths. This leaks operational intelligence and is a PCI/SOC2 finding.

**Severity:** Critical (C6)

**Inputs:**
- `backend/services/observability.py` — `/metrics` route registration
- `backend/middleware/auth.py` or a new IP-allowlist middleware

**Outputs:**
- `/metrics` returns HTTP 401/403 without valid credentials
- Tests verifying unauthorized access is rejected

**Steps:**
1. Add a `metrics_token` to `config.py` (env var `METRICS_TOKEN`); default to a random secret at startup.
2. In the `/metrics` handler, require either: (a) `Authorization: Bearer <metrics_token>` header, or (b) source IP in an allowlist (`METRICS_ALLOWLIST` env var, defaults to `127.0.0.1`).
3. Return HTTP 401 if neither condition is met.
4. Update Docker Compose / Railway config to set `METRICS_TOKEN`.
5. Add tests: unauthenticated → 401; correct token → 200.

**Acceptance Criteria:**
- Unauthenticated GET `/metrics` returns HTTP 401.
- Request with correct `METRICS_TOKEN` returns 200 with Prometheus text.
- Unit tests cover both cases.

**Finding:** C6 — `backend/services/observability.py`

**Dependencies:** none

---

### T-073: Add Content Size Limits to Diff and Edit Schemas

**Description:**
`AcceptDiffRequest.proposed_content` and `ContentEditRequest.content` are unbounded strings. An attacker can POST megabytes of content, causing memory exhaustion and DoS during diff computation.

**Severity:** Critical (C7)

**Inputs:**
- `backend/schemas/stage.py` — `AcceptDiffRequest`, `ContentEditRequest`

**Outputs:**
- Both fields annotated with `max_length` (e.g., 500,000 characters / ~500 KB)
- Tests verifying oversized payloads return HTTP 422

**Steps:**
1. Add `max_length=500_000` (or a config-driven constant) to `proposed_content` and `content` fields using Pydantic `Field(max_length=...)`.
2. Add a similar limit to `WorkspaceCreate.description` and `StageGenerateRequest.user_input` if not already present.
3. Add tests posting payloads of 500,001 characters and asserting HTTP 422.

**Acceptance Criteria:**
- `AcceptDiffRequest.proposed_content` and `ContentEditRequest.content` have `max_length` constraints.
- Oversized payloads are rejected with HTTP 422 before reaching any service layer.
- Tests pass.

**Finding:** C7 — `backend/schemas/stage.py`

**Dependencies:** none

---

### T-074: Catch SecurityError and ProviderError in SSE Stream Generators

**Description:**
The `_stream()` inner generators inside `generate_stage` and `regenerate_stage` only catch `StageDependencyError` and `RateLimitError`. If `SecurityError` (prompt injection) or `ProviderError` (LLM timeout, quota exceeded) are raised, they propagate uncaught, leaving the SSE stream open with the client hanging until timeout.

**Severity:** Critical (C8)

**Inputs:**
- `backend/routers/stage.py` — `generate_stage`, `regenerate_stage` `_stream()` generators

**Outputs:**
- Both generators catch `SecurityError` and `ProviderError`
- SSE stream emits a structured `{"event": "error", "data": "..."}` chunk before closing
- Tests confirming error events are emitted

**Steps:**
1. In both `_stream()` generators, expand the `except` clause (or add additional handlers) to catch `SecurityError` and `ProviderError`.
2. On catch, yield a final SSE chunk `{"event": "error", "data": str(exc)}` and return.
3. Also catch the bare `Exception` as a safety net, yielding a generic error chunk.
4. Add tests mocking the pipeline to raise each exception type and asserting the streamed response contains an `error` event.

**Acceptance Criteria:**
- `SecurityError` and `ProviderError` produce an SSE error event rather than an unclosed stream.
- SSE connection closes cleanly after the error event.
- Existing happy-path streaming tests continue to pass.

**Finding:** C8 — `backend/routers/stage.py`

**Dependencies:** T-085

---

### T-075: Fix Rate Limiter and CSRF Middleware to Use Verified JWT Claims

**Description:**
`backend/middleware/rate_limit.py` and `backend/middleware/csrf.py` call `jose_jwt.get_unverified_claims(token)` to extract the user ID for rate-limit bucketing and CSRF validation. An attacker can forge any user ID in the token payload (without knowing the signing key) to bypass per-user rate limits or steal another user's CSRF bucket.

**Severity:** Critical (C9)

**Inputs:**
- `backend/middleware/rate_limit.py`
- `backend/middleware/csrf.py`
- `backend/services/security/csrf.py`

**Outputs:**
- Both middlewares call a shared `verify_and_decode_access_token()` helper (or reuse the one in `auth.py`)
- Forged tokens are rejected before any claim is used
- Tests confirming tampered tokens receive HTTP 401/429 rather than operating on the forged identity

**Steps:**
1. Extract (or reuse) a `decode_access_token(token) -> dict` helper that calls `jose_jwt.decode()` with signature verification.
2. Replace all `get_unverified_claims()` calls in rate_limit and csrf middlewares with the verified version.
3. If token verification fails, return HTTP 401 immediately.
4. Add tests: valid token uses correct bucket; tampered payload token → 401.

**Acceptance Criteria:**
- No `get_unverified_claims` calls in `rate_limit.py` or `csrf.py`.
- A token with a forged `sub` claim (but invalid signature) is rejected before claim extraction.
- Tests pass.

**Finding:** C9 — `backend/middleware/rate_limit.py`, `backend/middleware/csrf.py`

**Dependencies:** T-069

---

### T-076: Cache LLM Adapter Instances in Gateway

**Description:**
`services/llm/gateway.py`'s `get_llm(provider, model)` instantiates a new adapter (and a new `AsyncAnthropic` / `AsyncOpenAI` HTTP client) on every call. Each client opens a new connection pool, wasting resources and adding latency. Singletons should be created once and reused.

**Severity:** Important (I1)

**Inputs:**
- `backend/services/llm/gateway.py`
- `backend/services/llm/anthropic_adapter.py`
- `backend/services/llm/openai_adapter.py`
- `backend/services/llm/gemini_adapter.py`

**Outputs:**
- `gateway.py` maintains a `_INSTANCES` / `_CACHE` dict keyed by `(provider, model)`
- Each adapter is instantiated at most once per process lifetime
- Tests verifying the same object is returned on repeated calls

**Steps:**
1. Add a module-level `_INSTANCES: dict[tuple[str, str], BaseLLMAdapter] = {}` in `gateway.py`.
2. In `get_llm()`, check `_INSTANCES.get((provider, model))` first; create and cache only on miss.
3. Ensure adapters are thread/task-safe (HTTP clients from Anthropic/OpenAI SDKs are async-safe by default).
4. Add a test asserting `get_llm("anthropic", "claude-3-5-sonnet") is get_llm("anthropic", "claude-3-5-sonnet")`.

**Acceptance Criteria:**
- `gateway.py` has a `_INSTANCES` or `_CACHE` module-level dict.
- `get_llm()` returns the same object on repeated calls with identical arguments.
- No new HTTP client is created on the second call.

**Finding:** I1 — `backend/services/llm/gateway.py`

**Dependencies:** none

---

### T-077: Configure SQLAlchemy Connection Pool for Production

**Description:**
`backend/database.py` uses `create_async_engine` with no pool configuration, defaulting to `pool_size=5, max_overflow=10`. Under load (e.g., 50 concurrent SSE streams), the app exhausts the pool and queues requests, causing cascading latency. Production should be sized to the expected concurrency.

**Severity:** Important (I2)

**Inputs:**
- `backend/database.py`
- `backend/config.py`

**Outputs:**
- `database.py` reads `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` from settings
- `config.py` exposes these as env-configurable settings with sensible defaults (20/10)
- Tests or local dev config demonstrating the values are respected

**Steps:**
1. Add `db_pool_size: int = 20` and `db_max_overflow: int = 10` to `Settings` in `config.py`.
2. Pass `pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow` to `create_async_engine`.
3. Add `pool_recycle=3600` to handle stale connections after long idle periods.
4. Document the env vars in the README and Docker Compose `.env.example`.

**Acceptance Criteria:**
- `database.py` passes `pool_size` and `max_overflow` to the engine.
- Both values are configurable via environment variables.
- `pool_recycle` is set to prevent stale connection errors.

**Finding:** I2 — `backend/database.py`

**Dependencies:** none

---

### T-078: Validate WorkspaceCreate Model Field Against Allowlist

**Description:**
`WorkspaceCreate.model` is a free-form string with only `min_length=1`. Any string is accepted, including non-existent model IDs. The LLM gateway should reject unknown models before attempting an API call, not fail mid-generation with an opaque provider error.

**Severity:** Important (I3)

**Inputs:**
- `backend/schemas/workspace.py` — `WorkspaceCreate`
- `backend/services/llm/gateway.py` — `VALID_MODELS` or equivalent registry

**Outputs:**
- `WorkspaceCreate` rejects model values not in `VALID_MODELS`
- HTTP 422 returned immediately on invalid model
- Tests for valid and invalid model values

**Steps:**
1. Export a `VALID_MODELS: frozenset[str]` constant from `gateway.py` (or `config.py`) listing all supported model IDs.
2. Add a `@field_validator("model")` in `WorkspaceCreate` that checks `v in VALID_MODELS` and raises `ValueError` on failure.
3. Add tests: valid model ID → 201; unknown model ID → 422.

**Acceptance Criteria:**
- `WorkspaceCreate` has a Pydantic validator for the `model` field.
- Requests with unknown model IDs are rejected with HTTP 422.
- `VALID_MODELS` is the single source of truth used by both the schema and the gateway.

**Finding:** I3 — `backend/schemas/workspace.py`

**Dependencies:** T-076

---

### T-079: Fix apply_diff to Use Index Positions Instead of str.find

**Description:**
`services/pipeline/diff_engine.py`'s `apply_diff(original, selected_text, replacement)` uses `str.find` to locate the selection. When the document contains duplicate text, `find` always matches the first occurrence regardless of where the user's cursor was. Edits to the second or later occurrence silently modify the wrong section.

**Severity:** Important (I4)

**Inputs:**
- `backend/services/pipeline/diff_engine.py` — `apply_diff()`
- `backend/tests/test_diff_engine.py`

**Outputs:**
- `apply_diff` signature extended with `start: int` and `end: int` index parameters
- Implementation uses `original[start:end]` check instead of `str.find`
- Tests covering duplicate-text documents

**Steps:**
1. Change the signature to `apply_diff(original: str, selected_text: str, replacement: str, start: int, end: int) -> str`.
2. Verify `original[start:end] == selected_text`; raise `ValueError` if not.
3. Return `original[:start] + replacement + original[end:]`.
4. Update all callers to pass cursor positions (the frontend already tracks `selectionStart`/`selectionEnd`).
5. Add tests: (a) unique text → correct replacement; (b) duplicate text with second-occurrence start/end → second occurrence replaced; (c) mismatch → ValueError.

**Acceptance Criteria:**
- `apply_diff` no longer calls `.find(`.
- Duplicate-text test confirms correct occurrence is replaced.
- All existing diff engine tests pass.

**Finding:** I4 — `backend/services/pipeline/diff_engine.py`

**Dependencies:** none

---

### T-080: Add Error Callbacks to Background Eval asyncio Tasks

**Description:**
`services/pipeline/stage_manager.py` fires eval tasks with `asyncio.create_task(run_eval_background(...))` and no `add_done_callback`. Exceptions raised inside the task are silently swallowed; there is no log entry, no metric increment, and no way to know evals are failing in production.

**Severity:** Important (I5)

**Inputs:**
- `backend/services/pipeline/stage_manager.py` — `asyncio.create_task` call sites

**Outputs:**
- Each `create_task` call followed by `.add_done_callback(_log_eval_error)`
- `_log_eval_error` logs the exception via structlog and increments a Prometheus counter
- Tests asserting exceptions are surfaced to the callback

**Steps:**
1. Define a module-level callback: `def _log_eval_error(task: asyncio.Task) -> None: if exc := task.exception(): logger.error("eval_background_failed", error=str(exc))`.
2. After each `asyncio.create_task(...)` call, chain `.add_done_callback(_log_eval_error)`.
3. Optionally increment a `eval_errors_total` Prometheus counter inside the callback.
4. Add a test that makes the eval coroutine raise, then asserts the callback fired (check log output or mock).

**Acceptance Criteria:**
- All `asyncio.create_task` calls for eval tasks are followed by `add_done_callback`.
- Eval exceptions appear in structured logs rather than disappearing silently.
- Tests pass.

**Finding:** I5 — `backend/services/pipeline/stage_manager.py`

**Dependencies:** none

---

### T-081: Add Double-Refund Guard to credit_service.refund()

**Description:**
`credit_service.refund()` has no idempotency check. Calling it twice (e.g., retry storm, duplicate webhook) double-credits the user's balance. Each refund should be keyed by a unique `refund_id` stored in the ledger so duplicates are detected and rejected.

**Severity:** Important (I8)

**Inputs:**
- `backend/services/credit_service.py` — `refund()`
- `backend/models/credit_ledger.py` — `CreditLedger` model

**Outputs:**
- `refund()` accepts an optional `idempotency_key: str` parameter
- Duplicate `idempotency_key` returns the existing ledger entry without inserting a new row
- Tests confirming double-refund is a no-op

**Steps:**
1. Add an optional `idempotency_key` column (or a dedicated `refunds` table) to `CreditLedger`; create migration `0003_credit_idempotency.py`.
2. In `refund()`, before inserting, query for an existing entry with the same `idempotency_key` within the transaction.
3. If found, return early without inserting.
4. If not found, insert the new credit row with the key.
5. Add tests: first call inserts and returns the amount; second call with the same key is a no-op; balance unchanged.

**Acceptance Criteria:**
- `refund()` accepts an `idempotency_key` parameter.
- A duplicate key does not create a second ledger entry.
- Unit tests verify idempotency behavior.

**Finding:** I8 — `backend/services/credit_service.py`

**Dependencies:** T-067

---

### T-082: Fix WorkspaceService.get to Prevent Authorization Timing Oracle

**Description:**
`workspace_service.get()` fetches the workspace by ID first, then checks `workspace.user_id != user_id` in Python. This creates a timing oracle: authorized requests return quickly; unauthorized requests for non-existent workspaces are also fast; but unauthorized requests for existing workspaces are slightly slower (ORM hydration). An attacker can enumerate valid workspace IDs by measuring response time.

**Severity:** Important (I9)

**Inputs:**
- `backend/services/workspace_service.py` — `get()` method

**Outputs:**
- `get()` filters `user_id` in the SQL WHERE clause, not in Python
- Unauthorized and non-existent workspace requests are indistinguishable
- Tests confirming correct behavior

**Steps:**
1. Change the query to `WHERE id = :id AND user_id = :user_id` so the DB returns nothing if the workspace belongs to a different user.
2. Remove the Python-level `if workspace.user_id != user_id` check.
3. Return 404 (not 403) when no row is returned — do not distinguish "not found" from "not authorized".
4. Add tests: owner can fetch; other user gets 404; nonexistent ID gets 404.

**Acceptance Criteria:**
- The SQL query includes both `id` and `user_id` in the WHERE clause.
- No Python-level `user_id` comparison exists in `get()`.
- Unauthorized access and missing resource both return HTTP 404.

**Finding:** I9 — `backend/services/workspace_service.py`

**Dependencies:** none

---

### T-083: Sanitize selected_text in Refine Stage Router Path

**Description:**
In the refine stage handler (`routers/stage.py`), only `instruction` is passed through `sanitize_text()`. The `selected_text` field — user-supplied text that is injected directly into the LLM prompt context — is not sanitized. This is a prompt injection vector: a user could embed instructions inside their selected text that override the system prompt.

**Severity:** Important (I10)

**Inputs:**
- `backend/routers/stage.py` — refine handler / `RefineRequest` processing
- `backend/services/security/sanitizer.py` — `sanitize_text()`

**Outputs:**
- `selected_text` passed through `sanitize_text()` before use in the pipeline
- Tests asserting that injection attempts in `selected_text` are stripped

**Steps:**
1. In the refine stage handler, apply `sanitize_text(request.selected_text)` and pass the result to the pipeline.
2. Verify the prompt injection guard (`PromptInjectionScanner`) also runs on `selected_text` (add call if missing).
3. Add tests with representative injection strings in `selected_text` and assert they are sanitized or rejected.

**Acceptance Criteria:**
- `selected_text` is passed through `sanitize_text()` before reaching the LLM pipeline.
- The prompt injection scanner is applied to `selected_text`.
- Tests for injection strings in `selected_text` pass.

**Finding:** I10 — `backend/routers/stage.py`

**Dependencies:** none

---

### T-084: Wrap Workspace.tsx Async Handlers in useCallback

**Description:**
`frontend/src/pages/Workspace.tsx` defines 9+ async event handlers inline in the component body with no `useCallback` memoization. Every state update (including token appends during streaming) re-creates all handlers, causing cascading child re-renders. During streaming (high-frequency updates), this produces thousands of unnecessary renders and degrades UI responsiveness.

**Severity:** Important (I11)

**Inputs:**
- `frontend/src/pages/Workspace.tsx`

**Outputs:**
- All async handlers (`handleGenerate`, `handleRegenerate`, `handleAcceptDiff`, `handleRollback`, `handleRefine`, etc.) wrapped in `useCallback`
- Correct dependency arrays that don't cause stale closure bugs
- No measurable regression in feature behavior

**Steps:**
1. Identify all inline `async () => { ... }` handlers assigned to props or event listeners.
2. Wrap each with `useCallback((args) => { ... }, [dep1, dep2])`.
3. Add the minimum necessary dependencies to each array — avoid over-capturing.
4. Run `pnpm tsc` to confirm no type errors.
5. Run `pnpm test` to confirm no behavioral regressions.

**Acceptance Criteria:**
- `Workspace.tsx` contains ≥5 `useCallback` calls covering the primary action handlers.
- `pnpm tsc` passes.
- `pnpm test` passes.

**Finding:** I11 — `frontend/src/pages/Workspace.tsx`

**Dependencies:** none

---

### T-085: Extract Shared Stream Helper from generate_stage and regenerate_stage

**Description:**
`backend/routers/stage.py` contains two handlers — `generate_stage` and `regenerate_stage` — each with an identical or near-identical 30-line `_stream()` inner generator. The duplication means any fix (e.g., error handling in T-074) must be applied twice, and the two implementations will inevitably diverge. Extract the shared logic into a single helper.

**Severity:** Important (I14)

**Inputs:**
- `backend/routers/stage.py` — `generate_stage`, `regenerate_stage`

**Outputs:**
- A shared `_build_stage_stream(pipeline_coro, stage_id, db, user)` helper (or similar)
- Both handlers delegate to the helper
- Existing streaming behavior unchanged

**Steps:**
1. Identify the divergent parameters between the two `_stream()` implementations (typically the pipeline call and the stage ID source).
2. Extract a `async def _stream_stage(pipeline_call: Callable, ...) -> AsyncGenerator[str, None]` helper at module level.
3. Replace both `_stream()` closures with calls to the shared helper.
4. Ensure the helper handles `StageDependencyError`, `RateLimitError`, `SecurityError`, and `ProviderError` (aligning with T-074).
5. Run existing streaming tests to confirm no regression.

**Acceptance Criteria:**
- `generate_stage` and `regenerate_stage` share a single stream generator helper.
- No `StageDependencyError` handling duplication between the two handlers.
- All existing stage streaming tests pass.

**Finding:** I14 — `backend/routers/stage.py`

**Dependencies:** none

---

---

## Phase 6 — Second-Pass Code Review Remediations

> Issues identified in the post-mitigation second-pass review (2026-05-03). Every item is a confirmed defect or confirmed gap from that review — not hypothetical. Tasks are ordered by severity: blocking CI/correctness first, security/reliability second, quality/architecture last.

---

### T-086: Fix CI Lint Failures — Black Formatting and Ruff E501 Violations

**Description:**
The mitigation commits introduced formatting and line-length violations that break CI. `black --check .` reports 7 files would be reformatted; `ruff check .` reports 15 errors, the majority being E501 (line too long > 88 chars) in `routers/stage.py` and `routers/auth.py`. The most visible structural violation is a missing two-blank-line separator after `_log_eval_error()` in `stage_manager.py` (line 36), which black would insert. Because CI runs both checks on every push, these failures prevent merging.

**Severity:** Blocking (CI failure)

**Inputs:**
- `backend/routers/stage.py` — SSE yield strings in `_stream_stage()` exceed 88 chars (lines 51, 53, 55, 92, 103)
- `backend/routers/auth.py` — line 45 exceeds 88 chars
- `backend/services/pipeline/stage_manager.py` — missing blank lines after `_log_eval_error` definition
- All other files flagged by `black --check .`

**Outputs:**
- `black .` passes with zero changes
- `ruff check .` passes with zero errors
- `uv run pytest tests/ -q` still passes (lint-only changes, no logic)

**Steps:**
1. Run `uv run black .` from `backend/` to auto-format all 7 files.
2. Fix the E501 violations in `routers/stage.py`: extract the long JSON payload dicts into local variables before the `yield` so each line fits within 88 characters. Example for `_stream_stage`:
   ```python
   except StageDependencyError as exc:
       payload = json.dumps({"error": "dependency_not_finalised", "detail": str(exc)})
       yield f"data: {payload}\n\n"
   ```
   Apply the same pattern to the `RateLimitError`, `SecurityError`, `ProviderError`, and `Exception` branches, and to the two long lines in `generate_stage` / `regenerate_stage`.
3. Fix `routers/auth.py:45`: split the long assignment across two lines using a temporary variable.
4. Re-run `uv run ruff check .` and confirm zero errors.
5. Re-run `uv run black --check .` and confirm zero reformats.
6. Run `uv run pytest tests/ -q` to confirm no regressions.

**Acceptance Criteria:**
- `uv run black --check .` exits 0.
- `uv run ruff check .` exits 0.
- `uv run pytest tests/ -q` passes (≥142 tests).

**Finding:** Second-pass review — CI breakage from Phase 5 commits

**Dependencies:** none

---

### T-087: Remove Raw Exception Detail from SSE Catch-All Error Event

**Description:**
The `_stream_stage()` shared helper in `routers/stage.py` includes a catch-all `except Exception as exc:` branch that yields `str(exc)` — the raw Python exception message — as the `detail` field in the SSE error event. This is an information-disclosure regression: DB connection strings, SQLAlchemy internals, ORM stack hints, and unexpected attribute errors can all appear verbatim in the browser. The SSE error payload should carry a fixed error code; real exception details belong in the server-side structured log.

**Severity:** Security regression (information disclosure)

**Inputs:**
- `backend/routers/stage.py` — `_stream_stage()`, the `except Exception` branch (lines 58–59)
- `backend/services/pipeline/stage_manager.py` — `logger` is already imported

**Outputs:**
- The catch-all branch yields `{"error": "internal_error"}` with no `detail` field
- The exception is logged server-side with full context via `logger.exception()`
- The `sseService.ts` `ErrorEvent` interface's `detail` field remains optional (no frontend changes needed beyond confirming the field is already optional)

**Steps:**
1. In `_stream_stage()`, replace:
   ```python
   except Exception as exc:
       yield f"data: {json.dumps({'error': 'internal_error', 'detail': str(exc)})}\n\n"
   ```
   with:
   ```python
   except Exception:
       logger.exception("stage_stream_internal_error", extra={"stage_id": str(stage_id)})
       yield f"data: {json.dumps({'error': 'internal_error'})}\n\n"
   ```
2. Confirm that `logger` is already imported at module level in `routers/stage.py`. If not, add `import logging` and `logger = logging.getLogger(__name__)`.
3. Confirm that `sseService.ts:18` declares `detail?: string` (already optional) — no frontend change needed.
4. Add a test in `test_stage_router.py` that patches `stage_manager.generate` to raise a bare `RuntimeError`, triggers the generate endpoint, and asserts: (a) the SSE event contains `{"error": "internal_error"}` with no `detail` key, and (b) the error is not completely silent (confirm logger.exception was called via `caplog` or a mock).

**Acceptance Criteria:**
- `except Exception` branch in `_stream_stage()` does not include `str(exc)` in the yielded event.
- A test confirms the `detail` key is absent from the catch-all error event.
- `uv run pytest tests/test_stage_router.py -q` passes.

**Finding:** Second-pass review — regression from T-074/T-085

**Dependencies:** T-086 (lint must pass first so this commit doesn't re-introduce formatting issues)

---

### T-088: Add DB-Level Unique Constraint to Complete Double-Refund Protection

**Description:**
T-081 added an application-level idempotency check in `credit_service.refund()` that queries for an existing refund row before inserting. This check-then-act pattern has a race window: two concurrent `refund()` calls (e.g., the recovery service and a router exception handler firing simultaneously) can both pass the `SELECT` check before either `INSERT` commits, causing a double-credit. The fix must close this at the database level with a `UNIQUE` constraint and handle the resulting `IntegrityError` gracefully in the application layer.

**Severity:** High (financial integrity — race condition in credit accounting)

**Inputs:**
- `backend/models/credit_ledger.py` — `CreditLedger` model
- `backend/services/credit_service.py` — `refund()` method
- `backend/migrations/versions/` — new migration needed

**Outputs:**
- `UNIQUE(user_id, reason)` constraint on the `credit_ledger` table
- `refund()` wraps the insert in a `try/except IntegrityError` and returns silently on duplicate
- Alembic migration `0003_credit_ledger_unique_refund.py`
- Tests covering the race-safe path

**Steps:**
1. In `models/credit_ledger.py`, add a `UniqueConstraint` to `__table_args__`:
   ```python
   from sqlalchemy import UniqueConstraint
   __table_args__ = (
       UniqueConstraint("user_id", "reason", name="uq_credit_ledger_user_reason"),
   )
   ```
2. Create `backend/migrations/versions/0003_credit_ledger_unique_refund.py`:
   ```python
   def upgrade() -> None:
       op.create_unique_constraint(
           "uq_credit_ledger_user_reason", "credit_ledger", ["user_id", "reason"]
       )
   def downgrade() -> None:
       op.drop_constraint("uq_credit_ledger_user_reason", "credit_ledger")
   ```
3. In `credit_service.py`, wrap the insert in `refund()` with `IntegrityError` handling:
   ```python
   from sqlalchemy.exc import IntegrityError
   
   # Keep the existing SELECT-based pre-check (fast path for non-race case)
   # Then:
   try:
       db.add(refund_entry)
       await db.flush()
   except IntegrityError:
       await db.rollback()
       return  # concurrent refund beat us; this call is a no-op
   ```
4. Update `_FakeDB` in `test_credit_service.py` to simulate `IntegrityError` on duplicate reason (add an `_existing_reasons: set` that raises on duplicate add). Write a new test `test_refund_is_race_safe_via_integrity_error` that calls `refund()` when `db.flush()` raises `IntegrityError` and asserts no entry is added and no exception propagates.
5. Remove the now-redundant pre-check SELECT from `refund()` — the DB constraint makes it unnecessary overhead. The only guard needed is the `try/except IntegrityError`.
6. Run `uv run pytest tests/test_credit_service.py -q`.

**Acceptance Criteria:**
- `credit_ledger` table has `UNIQUE(user_id, reason)` constraint in the migration.
- `refund()` does not raise when `db.flush()` raises `IntegrityError`; it returns silently.
- The pre-check SELECT is removed (the constraint is the sole guard).
- `test_refund_is_idempotent` and `test_refund_is_race_safe_via_integrity_error` both pass.

**Finding:** Second-pass review — I8 fix incomplete (no DB-level enforcement)

**Dependencies:** none

---

### T-089: Fix Recovery Service Credit Heuristic — Store Deduction ID on Stage

**Description:**
`recovery_service.py` locates the credit deduction to refund by searching for ledger entries within a 60-second window of `stage.updated_at`. This heuristic misfires under clock drift, high DB load, or when a user has multiple concurrent stuck stages (the wrong entry gets refunded). The correct fix is to store the exact `credit_ledger_entry_id` on the `Stage` row at deduction time, making the recovery lookup exact and eliminating the window entirely.

**Severity:** High (financial integrity — wrong refunds during recovery)

**Inputs:**
- `backend/models/stage.py` — `Stage` model
- `backend/services/pipeline/stage_manager.py` — `generate()` method where deduction happens
- `backend/services/pipeline/recovery_service.py` — `recover_stuck_stages()`
- `backend/migrations/versions/` — new migration needed

**Outputs:**
- `Stage.deduction_ledger_id: UUID | None` nullable FK column
- Alembic migration `0004_stage_deduction_ledger_id.py`
- `stage_manager.generate()` sets `stage.deduction_ledger_id = deduction.id` before committing
- `recovery_service.recover_stuck_stages()` uses `stage.deduction_ledger_id` directly
- Existing recovery tests updated; new test for exact-ID path added

**Steps:**
1. In `models/stage.py`, add the nullable FK column:
   ```python
   from uuid import UUID as PythonUUID
   deduction_ledger_id: Mapped[PythonUUID | None] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("credit_ledger.id", ondelete="SET NULL"),
       nullable=True,
   )
   ```
2. Create `migrations/versions/0004_stage_deduction_ledger_id.py`:
   ```python
   import sqlalchemy as sa
   from sqlalchemy.dialects.postgresql import UUID

   def upgrade() -> None:
       op.add_column(
           "stages",
           sa.Column(
               "deduction_ledger_id",
               UUID(as_uuid=True),
               sa.ForeignKey("credit_ledger.id", ondelete="SET NULL"),
               nullable=True,
           ),
       )
   def downgrade() -> None:
       op.drop_column("stages", "deduction_ledger_id")
   ```
3. In `stage_manager.generate()`, immediately after `deduction = await credit_service.deduct(...)`, add:
   ```python
   stage.deduction_ledger_id = deduction.id
   ```
   (This is already within the `stage.status = "in_progress"` block that commits to DB.)
4. In `recovery_service.recover_stuck_stages()`, replace the time-window ledger query:
   ```python
   # Remove the 60-second window query entirely.
   # Use the stored ID instead:
   if stage.deduction_ledger_id is not None:
       await credit_service.refund(db, stage.deduction_ledger_id)
       credits_refunded = 10  # standard generate cost; or look it up from the ledger entry
   ```
   To get the actual amount without an extra query, fetch the entry: call `credit_service.refund()` (which already loads the entry to get `original.amount`) — no change needed there since `refund()` already handles the amount lookup.
5. Update `test_recovery_service.py`: remove tests that rely on the 60-second window heuristic; add `test_recovery_uses_stored_deduction_id` that creates a stuck stage with `deduction_ledger_id` set and asserts `credit_service.refund` is called with exactly that ID.
6. Run `uv run pytest tests/test_recovery_service.py -q`.

**Acceptance Criteria:**
- `Stage.deduction_ledger_id` column exists in the model and migration.
- `stage_manager.generate()` sets `stage.deduction_ledger_id` before the commit.
- `recover_stuck_stages()` uses `stage.deduction_ledger_id` directly; no time-window query remains.
- Recovery service test covers the exact-ID path and passes.

**Finding:** Second-pass review — I7 not addressed in Phase 5

**Dependencies:** T-088 (migration numbering; run after 0003)

---

### T-090: Make Observability Env Vars Optional in config.py

**Description:**
`config.py` declares `sentry_dsn`, `grafana_otlp_endpoint`, and `grafana_otlp_token` as required `str` fields with no defaults. Pydantic raises a `ValidationError` at application startup if any of these are absent from `.env`. This is incorrect: `observability.py` already guards all three with `_is_configured_url()` and skips initialisation when the values are empty or placeholder strings. The application must start correctly in environments where observability sinks are not configured (local development, basic staging).

**Severity:** Important (deployment reliability — app crashes on fresh deploy without Sentry/OTLP)

**Inputs:**
- `backend/config.py` — `Settings` class
- `backend/.env.example` — must reflect the new optional semantics
- `backend/services/observability.py` — `_is_configured_url()` guard (confirm it handles empty string)

**Outputs:**
- Three fields have `str = ""` defaults in `Settings`
- `.env.example` uses empty string as placeholder for these three vars
- A startup test confirms the app creates successfully when all three are empty strings

**Steps:**
1. In `config.py`, change the three fields:
   ```python
   sentry_dsn: str = ""
   grafana_otlp_endpoint: str = ""
   grafana_otlp_token: str = ""
   ```
2. Verify that `observability.py:_is_configured_url("")` returns `False` (it checks `.startswith(("http://", "https://"))`; an empty string fails this check). Confirm via a quick unit test or inspection.
3. Update `backend/.env.example`: change the placeholder values for these three keys to empty strings (remove the dummy URL placeholders that forced operators to replace them).
4. Add a test `test_app_starts_without_observability_config` in `test_app_contract.py` (or `test_observability.py`) that calls `create_app()` with `SENTRY_DSN=""`, `GRAFANA_OTLP_ENDPOINT=""`, `GRAFANA_OTLP_TOKEN=""` and asserts no exception is raised.
5. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `Settings()` initialises successfully when the three vars are absent from `.env`.
- `.env.example` shows these as optional (empty default).
- Test confirms `create_app()` succeeds without observability env vars set.

**Finding:** Second-pass review — M1 not addressed in Phase 5

**Dependencies:** none

---

### T-091: Eliminate Frontend Eval Polling — Deliver via Follow-On SSE Event

**Description:**
`useStream.ts` calls `pollEval()` after every generation: up to 6 attempts × 5 seconds = 30 seconds of polling per generation. The polling drives unnecessary DB queries (600/minute at 100 concurrent users) and couples the frontend to a server-side async timing detail it cannot know. The correct fix is to have the backend emit a second SSE `eval` event once the background eval task resolves, then have the frontend consume it directly. No polling of any kind remains.

**Severity:** Important (scalability + correctness — frontend timing is non-deterministic)

**Inputs:**
- `backend/services/evals/online_eval.py` — `run_eval_background()` and `run_eval()`
- `backend/services/pipeline/stage_manager.py` — `generate()`, `_log_eval_error()`
- `backend/routers/stage.py` — `_stream_stage()`
- `frontend/src/services/sseService.ts` — event type definitions
- `frontend/src/hooks/useStream.ts` — `pollEval()` and stream result handling

**Outputs:**
- `run_eval_background()` returns `EvalResult | None` (currently returns `None` implicitly)
- `stage_manager.generate()` emits a second `{"eval": {...}}` SSE event after the done event once the eval task resolves (with a 30-second timeout guard)
- `sseService.ts` parses and forwards the `eval` event type
- `useStream.ts` removes `pollEval()` entirely; the `evalResult` in `StreamResult` is populated from the SSE eval event
- Tests confirm the eval event is emitted and parsed

**Steps:**
1. In `online_eval.py`, change `run_eval_background` to return the `EvalResult | None` produced by `run_eval()`. Currently it returns nothing; add `return result` at the end of the try block (already calls `run_eval()` and stores `result`).
2. In `stage_manager.generate()`, capture the task result after yielding `done`:
   ```python
   eval_task = asyncio.create_task(
       run_eval_background(version_id, stage.type, accumulated, spec_content,
                           workspace.provider, JUDGE_MODELS[workspace.provider])
   )
   eval_task.add_done_callback(_log_eval_error)
   yield f'{{"done": true, "stage_id": "{stage_id}"}}'

   # Await eval with a 30-second hard timeout; emit result as a second event
   try:
       eval_result = await asyncio.wait_for(asyncio.shield(eval_task), timeout=30.0)
       if eval_result is not None:
           yield f"data: {json.dumps({'eval': _eval_to_dict(eval_result)})}\n\n"
   except (asyncio.TimeoutError, Exception):
       pass  # Eval timeout or failure — client just won't get the badge update
   ```
   Define `_eval_to_dict(result: EvalResult) -> dict` as a module-level helper that serialises the eval fields.
3. In `sseService.ts`, add the `eval` event type to `SSEPayload`:
   ```typescript
   interface EvalEvent {
     eval: EvalResult
   }
   type SSEPayload = DoneEvent | TokenEvent | ErrorEvent | EvalEvent
   ```
   In the payload dispatch loop, add:
   ```typescript
   if ("eval" in data) {
     onEval(data.eval)
     return
   }
   ```
   Update `createSSEConnection` to accept an `onEval: (eval: EvalResult) => void` callback. Pass a no-op default so existing call sites are unaffected.
4. In `useStream.ts`:
   - Remove the `pollEval` function entirely.
   - In `createSSEConnection(...)`, pass an `onEval` callback that stores the eval result in a local `ref` that is resolved into `StreamResult`.
   - Update `StreamResult` population to use the eval from the SSE event (or `null` if the 30s timeout expired).
5. Add a test in `test_stage_router.py` (or a new `test_stage_streaming.py`) that asserts: when `run_eval_background` resolves within timeout, the SSE stream contains a `{"eval": {...}}` event after the `done` event. Assert that the stream contains no polling-dependent behaviour.
6. Run `pnpm tsc` and `pnpm test` in `frontend/`; run `uv run pytest tests/ -q` in `backend/`.

**Acceptance Criteria:**
- `pollEval` function does not exist in `useStream.ts`.
- The backend SSE stream emits an `eval` event after `done` when the eval task resolves within 30 seconds.
- `pnpm tsc` passes; `pnpm test` passes.
- `uv run pytest tests/ -q` passes.

**Finding:** Second-pass review — I6 not addressed in Phase 5

**Dependencies:** none

---

### T-092: Add Exponential Backoff Retry to SSE Connection

**Description:**
Any transient network error (WiFi drop, proxy timeout, brief server restart) in `sseService.ts` immediately calls `onError()` and terminates the generation stream, forcing the user to start over and spend another 10 credits. The service should transparently retry up to 3 times with exponential backoff (1 s, 2 s, 4 s) before surfacing the error. Retries apply only to network/transport errors, not to application-level error events (`{"error": ...}`) or intentional cancellations.

**Severity:** Important (UX reliability + credit integrity — users lose credits on transient failures)

**Inputs:**
- `frontend/src/services/sseService.ts` — `connect()` function and `createSSEConnection` signature

**Outputs:**
- On transport failure (network error or non-200 HTTP), `connect()` retries up to 3 times before calling `onError()`
- Backoff delays: attempt 1 → 1 000 ms, attempt 2 → 2 000 ms, attempt 3 → 4 000 ms
- Application-level errors (server emits `{"error": "..."}` in the SSE stream) are not retried — they propagate immediately to `onError()`
- Cancellation via `close()` stops retry attempts immediately
- Retry attempt count is visible in a structured log at `console.warn` level

**Steps:**
1. Extract the `connect()` body into an inner `attempt(tryNumber: number)` function. In the outer `connect()`, implement a loop:
   ```typescript
   const MAX_RETRIES = 3
   const BACKOFF_MS = [1000, 2000, 4000]

   async function connect() {
     for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
       if (closed) return
       const succeeded = await tryConnect()
       if (succeeded || closed) return
       if (attempt < MAX_RETRIES) {
         const delay = BACKOFF_MS[attempt] ?? 4000
         console.warn(`SSE retry ${attempt + 1}/${MAX_RETRIES} in ${delay}ms`)
         await new Promise((resolve) => window.setTimeout(resolve, delay))
       } else {
         onError(lastError ?? new Error("Stream failed after retries"))
       }
     }
   }
   ```
   `tryConnect()` returns `true` if the stream completed normally (done or application error event), `false` on transport failure. It sets a `lastError` variable on transport failure.
2. Application-level error events (`"error" in data`) still call `onError()` and return `true` from `tryConnect()` (they are not retried — the server already handled the failure).
3. `close()` sets `closed = true` and aborts any in-progress `AbortController`, which also cancels any pending `setTimeout` via the `closed` guard in the loop.
4. Add a test in the frontend test suite that stubs `fetch` to fail twice then succeed, and asserts: (a) `onError` is not called, (b) `onDone` is called, (c) `console.warn` was called twice. Also test that a third failure calls `onError`.

**Acceptance Criteria:**
- Transient network errors cause silent retry with backoff; `onError` is not called on the first failure.
- After 3 consecutive failures, `onError` is called once.
- Application-level `{"error": ...}` events immediately call `onError` without retrying.
- `close()` during a retry delay stops further attempts immediately.
- `pnpm tsc` and `pnpm test` pass.

**Finding:** Second-pass review — I12 not addressed in Phase 5

**Dependencies:** none

---

### T-093: Add Focus Trap and ARIA Semantics to All Three Modals

**Description:**
`CreditConfirmModal`, `HumanReviewGate`, and `CreateWorkspaceModal` render as floating overlays with no `role="dialog"`, no `aria-modal="true"`, no `aria-labelledby`, and no focus trap. Keyboard-only users can Tab past the overlay backdrop into the inert background content. Screen readers cannot identify the modal boundary. All three modals must be made fully accessible without third-party dependencies: use a native focus-trap implementation via `useEffect` and `keydown` event handling.

**Severity:** Important (accessibility — keyboard users cannot safely use core product flows)

**Inputs:**
- `frontend/src/components/workspace/CreditConfirmModal.tsx`
- `frontend/src/components/workspace/HumanReviewGate.tsx`
- `frontend/src/components/dashboard/CreateWorkspaceModal.tsx`

**Outputs:**
- A shared `useFocusTrap(ref, onClose)` hook in `frontend/src/hooks/useFocusTrap.ts`
- All three modals apply the hook, add `role="dialog"`, `aria-modal="true"`, and `aria-labelledby` pointing to their `<h2>`
- Focus moves to the first focusable element on mount; Escape key calls the close handler; Tab cycles within the dialog

**Steps:**
1. Create `frontend/src/hooks/useFocusTrap.ts`:
   ```typescript
   import { useEffect } from "react"

   const FOCUSABLE = [
     'button:not([disabled])',
     'input:not([disabled])',
     'select:not([disabled])',
     'textarea:not([disabled])',
     '[tabindex]:not([tabindex="-1"])',
     'a[href]',
   ].join(", ")

   export function useFocusTrap(
     ref: React.RefObject<HTMLElement | null>,
     onClose: () => void,
   ) {
     useEffect(() => {
       const el = ref.current
       if (!el) return
       const focusable = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
       focusable[0]?.focus()

       function handleKeyDown(event: KeyboardEvent) {
         if (event.key === "Escape") {
           onClose()
           return
         }
         if (event.key !== "Tab") return
         if (focusable.length === 0) { event.preventDefault(); return }
         const first = focusable[0]
         const last = focusable[focusable.length - 1]
         if (event.shiftKey) {
           if (document.activeElement === first) {
             event.preventDefault()
             last.focus()
           }
         } else {
           if (document.activeElement === last) {
             event.preventDefault()
             first.focus()
           }
         }
       }

       el.addEventListener("keydown", handleKeyDown)
       return () => el.removeEventListener("keydown", handleKeyDown)
     }, [ref, onClose])
   }
   ```
2. In `CreditConfirmModal.tsx`:
   - Add `import { useRef } from "react"` and `import { useFocusTrap } from "../../hooks/useFocusTrap"`.
   - Create `const dialogRef = useRef<HTMLDivElement>(null)`.
   - Call `useFocusTrap(dialogRef, onCancel)`.
   - Add to the inner `<div>`: `ref={dialogRef}`, `role="dialog"`, `aria-modal="true"`, `aria-labelledby="credit-modal-title"`.
   - Add `id="credit-modal-title"` to the `<h2>`.
3. Apply the same pattern to `HumanReviewGate.tsx` (labelledby `"review-gate-title"`, close handler is `onClose`).
4. Apply to `CreateWorkspaceModal.tsx` (labelledby `"create-workspace-title"`, close handler is whatever closes the modal).
5. Write tests for `useFocusTrap`: render a dialog with 3 focusable buttons, assert Tab wraps from last to first, Shift+Tab wraps from first to last, Escape calls `onClose`.
6. Run `pnpm tsc` and `pnpm test`.

**Acceptance Criteria:**
- All three modals have `role="dialog"`, `aria-modal="true"`, `aria-labelledby`.
- `useFocusTrap` is the single implementation used by all three.
- Focus is on the first focusable element on open; Tab cycles within; Escape calls the close handler.
- No focus escapes to the background during Tab navigation.
- `pnpm tsc` and `pnpm test` pass.

**Finding:** Second-pass review — I13 not addressed in Phase 5

**Dependencies:** none

---

### T-094: Eliminate WorkspaceService._load() Footgun

**Description:**
`workspace_service.py` has two workspace-loading paths: `get(workspace_id, user_id, db)` which correctly filters by both `id` and `user_id` in SQL (fixed in T-082), and `_load(workspace_id, db)` which queries by `id` alone without any ownership check. `_load()` is currently called only by `create()` to return the freshly-created workspace — a safe use. But the existence of a user_id-free query path on the service class is a footgun: any future code that reaches for `_load()` instead of `get()` silently bypasses the security fix. Remove `_load()` by inlining its query into `create()`.

**Severity:** Code quality / security posture (defensive: eliminate the footgun before it is misused)

**Inputs:**
- `backend/services/workspace_service.py` — `create()` and `_load()`
- `backend/tests/test_workspace.py` — confirm no tests reference `_load()` directly

**Outputs:**
- `_load()` method is deleted
- `create()` loads the workspace inline after insert, without a separate helper
- All existing workspace tests pass

**Steps:**
1. In `create()`, replace `return await self._load(workspace.id, db)` with an inline load:
   ```python
   result = await db.execute(
       select(Workspace)
       .where(Workspace.id == workspace.id)
       .options(selectinload(Workspace.stages))
   )
   return result.scalar_one()
   ```
   This is identical to what `_load()` did, but the code is now co-located with its only caller and the method no longer exists as a callable footgun.
2. Delete the `_load()` method entirely.
3. Run `grep -rn "_load\b" backend/` to confirm no remaining references to the deleted method.
4. Run `uv run pytest tests/test_workspace.py -q` to confirm all tests pass.

**Acceptance Criteria:**
- `_load()` does not exist in `workspace_service.py`.
- `create()` returns a correctly loaded workspace with stages.
- `grep -n "_load" backend/services/workspace_service.py` returns no matches.
- All workspace tests pass.

**Finding:** Second-pass review — regression footgun introduced by T-082

**Dependencies:** none

---

### T-095: Eliminate Double RS256 Decode per Request

**Description:**
Every authenticated request currently performs two full RS256 JWT signature verifications: once in `RateLimitMiddleware._extract_user_id()` and again in `get_current_user()`. RS256 involves asymmetric key operations and is measurably slower than HMAC under load. The fix is to store the verified claims in `request.state` when the rate limiter first decodes them, and have the auth dependency consume those cached claims instead of re-decoding.

**Severity:** Code quality / performance (eliminates redundant cryptographic work on every request)

**Inputs:**
- `backend/middleware/rate_limit.py` — `_extract_user_id()` and `dispatch()`
- `backend/middleware/auth.py` — `get_current_user()`
- `backend/middleware/csrf.py` — `_session_id_from_authorization()` (also decodes the token)

**Outputs:**
- `RateLimitMiddleware.dispatch()` stores verified claims in `request.state.jwt_claims` after decoding
- `CsrfMiddleware._session_id_from_authorization()` reads `request.state.jwt_claims` if present, skips its own decode
- `get_current_user()` reads `request.state.jwt_claims` if present, skips its own decode
- Each request performs exactly one RS256 decode regardless of middleware depth
- Tests confirm each path (cache hit, cache miss) behaves correctly

**Steps:**
1. In `rate_limit.py`, update `_extract_user_id` to accept `request: Request` and return `tuple[str | None, dict | None]` (user_id and full claims):
   ```python
   def _extract_user_id(request: Request) -> tuple[str | None, dict | None]:
       auth_header = request.headers.get("Authorization", "")
       if not auth_header.startswith("Bearer "):
           return None, None
       token = auth_header.removeprefix("Bearer ").strip()
       claims = decode_access_token_claims(token)
       if claims is None:
           return None, None
       return claims.get("sub"), claims
   ```
   In `dispatch()`, after calling `_extract_user_id`:
   ```python
   user_id, claims = _extract_user_id(request)
   if claims is not None:
       request.state.jwt_claims = claims
   ```
2. In `csrf.py`, update `_session_id_from_authorization` to check `request.state` first:
   ```python
   def _session_id_from_authorization(request: Request) -> str | None:
       claims = getattr(request.state, "jwt_claims", None)
       if claims is None:
           auth_header = request.headers.get("Authorization", "")
           if not auth_header.startswith("Bearer "):
               return None
           token = auth_header.removeprefix("Bearer ").strip()
           claims = decode_access_token_claims(token)
       if claims is None:
           return None
       subject = claims.get("sub")
       return subject if isinstance(subject, str) and subject else None
   ```
3. In `middleware/auth.py`, update `get_current_user` to accept `Request` and read from state:
   ```python
   from starlette.requests import Request

   async def get_current_user(
       request: Request,
       token: str | None = Depends(oauth2_scheme),
       db: AsyncSession = Depends(get_db),
   ) -> User:
       cached_claims = getattr(request.state, "jwt_claims", None)
       if cached_claims is not None:
           claims = cached_claims
       else:
           if not token:
               raise _unauthorized()
           try:
               claims = auth_service.verify_access_token(token)
           except (AuthError, KeyError, TypeError, ValueError) as exc:
               raise _unauthorized() from exc
       try:
           user_id = UUID(claims["sub"])
       except (KeyError, ValueError) as exc:
           raise _unauthorized() from exc
       user = await _load_user(db, user_id)
       if user is None:
           raise _unauthorized()
       return user
   ```
4. Add tests to `test_auth_middleware.py`: (a) with a valid JWT, `get_current_user` with pre-populated `request.state.jwt_claims` does not call `verify_access_token`; (b) without cached claims, it falls back to full verification.
5. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- A request with a valid JWT triggers exactly one `decode_access_token_claims` call across all middleware and dependencies (verify with a `patch` counter in tests).
- `request.state.jwt_claims` is populated by `RateLimitMiddleware` for valid-token requests.
- All existing auth, CSRF, and rate-limit tests pass.

**Finding:** Second-pass review — code quality concern introduced by C9 fix (T-075)

**Dependencies:** none

---

### T-096: Replace Fragile `_where_criteria` Introspection in Workspace Test Mock

**Description:**
The `_FakeDB.execute()` mock in `test_workspace.py` (added in T-082) introspects `statement._where_criteria` — a `_`-prefixed SQLAlchemy internal — to simulate SQL-level `user_id` filtering. While this works in SQLAlchemy 2.x and passes tests, it couples the test infrastructure to a private implementation detail of the ORM. A safer approach is to replace the implicit statement-parsing with an explicit `requesting_user_id` parameter on `_FakeDB` that the mock uses to decide whether to return the workspace. This makes the mock's filtering behaviour obvious from the test code, not inferred from ORM internals.

**Severity:** Code quality / test maintainability

**Inputs:**
- `backend/tests/test_workspace.py` — `_FakeDB` class and all tests that instantiate it

**Outputs:**
- `_FakeDB.__init__` accepts an optional `requesting_user_id: UUID | None = None` parameter
- `_FakeDB.execute()` applies a simple equality check (`workspace.user_id == requesting_user_id`) instead of parsing the SQLAlchemy statement
- All existing tests updated to pass `requesting_user_id` where ownership filtering is the behaviour under test
- No `_where_criteria` reference remains in the test file

**Steps:**
1. Update `_FakeDB.__init__`:
   ```python
   def __init__(
       self,
       workspace: Workspace | None = None,
       requesting_user_id: UUID | None = None,
   ) -> None:
       self._workspace = workspace
       self._requesting_user_id = requesting_user_id
       ...
   ```
2. Update `_FakeDB.execute()`:
   ```python
   async def execute(self, statement: Any) -> "_FakeScalars":
       workspace = self._workspace
       if (
           workspace is not None
           and self._requesting_user_id is not None
           and workspace.user_id != self._requesting_user_id
       ):
           workspace = None
       return _FakeScalars(workspace)
   ```
3. Update each test that previously relied on the implicit WHERE-clause filtering:
   - `test_get_workspace_wrong_owner_raises_404`: pass `requesting_user_id=uuid4()` (a different UUID from `workspace.user_id`).
   - `test_get_workspace_correct_owner_returns_workspace`: pass `requesting_user_id=workspace.user_id`.
   - `test_update_workspace_wrong_owner_raises_404`, `test_archive_workspace_wrong_owner_raises_404`: same pattern.
   - Route-level tests that inject `_FakeDB` via `dependency_overrides`: pass `requesting_user_id=_USER_ID` (since the app fixture hardcodes `get_current_user` to return `_USER`). When the workspace belongs to a different user, `_USER_ID != workspace.user_id` and the mock returns `None`.
4. Tests that do not test ownership (e.g., `test_create_workspace_adds_four_stages`, `test_list_for_user_returns_workspaces`) should not pass `requesting_user_id` — the parameter defaults to `None`, which means no filtering (existing behaviour for non-ownership tests).
5. Run `grep -n "_where_criteria" backend/tests/test_workspace.py` and confirm zero matches.
6. Run `uv run pytest tests/test_workspace.py -q` and confirm all 15 tests pass.

**Acceptance Criteria:**
- No `_where_criteria` reference exists in `test_workspace.py`.
- `_FakeDB.execute()` does not parse the SQLAlchemy statement object in any way.
- All 15 workspace tests pass.
- The ownership-filtering behaviour is evident from reading the test instantiation (e.g., `_FakeDB(workspace=ws, requesting_user_id=other_user_id)`).

**Finding:** Second-pass review — test fragility introduced by T-082

**Dependencies:** none

---

## Phase 7 — Security Audit Hardening

> Issues identified in the deep security audit on 2026-05-04. Each task maps to at least one contract in `harness/tests/backend/test_security_audit_contract.py`. Complete these before treating V1 as production-ready.

---

### T-097: Prevent Zip Slip in Workspace Exports

**Description:**
`backend/services/pipeline/export_service.py` parses file names from AI/user-controlled harness code fences and writes them directly into a ZIP. Filenames like `../../tmp/pwned.py` or `/absolute/path.py` become dangerous archive members. Any unsafe extractor can write outside the intended extraction directory.

**Severity:** High — exploitable by any authenticated user who can edit/finalise harness content and convince a developer or CI job to extract the export.

**Inputs:**
- `backend/services/pipeline/export_service.py`
- `backend/tests/test_export_service.py`
- `harness/tests/backend/test_security_audit_contract.py::test_export_service_rejects_zip_slip_harness_filenames`

**Outputs:**
- Safe harness filename normalization helper
- Unsafe harness filenames rejected or skipped before `ZipFile.writestr()`
- Tests for `..`, absolute paths, empty paths, and valid nested paths

**Steps:**
1. Add a helper in `export_service.py` that accepts a raw filename and returns a safe `harness/<relative-posix-path>` or `None`.
2. Use `pathlib.PurePosixPath` after converting backslashes to `/`.
3. Reject absolute paths, `..` path parts, empty path parts, Windows drive prefixes, and filenames that normalize to only `harness/`.
4. Update `_parse_harness_files()` to call this helper before adding a file to the export map.
5. Preserve valid nested paths such as `tests/unit/test_auth.py` as `harness/tests/unit/test_auth.py`.
6. Add backend unit tests covering traversal and valid filenames.
7. Run `cd backend && uv run pytest tests/test_export_service.py ../harness/tests/backend/test_security_audit_contract.py -q`.

**Acceptance Criteria:**
- No ZIP member name can escape the `harness/` prefix.
- The security audit harness Zip Slip test passes.
- Existing export behavior for normal labelled code fences still works.

**Finding:** 2026-05-04 security audit — Zip Slip in exported harness files

**Dependencies:** none

---

### T-098: Bound and Verify Refine Requests

**Description:**
`RefineRequest.instruction` and `selected_text` are unbounded, and `StageManager.refine()` does not verify that the client-provided selection range matches the current stage content. An authenticated attacker can send oversized refine payloads or stale/mismatched indices, causing unnecessary parsing, LLM prompt growth, provider spend, and unintended content replacement.

**Severity:** Medium — authenticated resource exhaustion and content integrity risk.

**Inputs:**
- `backend/schemas/stage.py`
- `backend/services/pipeline/stage_manager.py`
- `backend/services/pipeline/diff_engine.py`
- `backend/tests/test_stage_router.py`
- `backend/tests/test_diff_engine.py`
- `harness/tests/backend/test_security_audit_contract.py::test_refine_request_enforces_size_and_selection_bounds`
- `harness/tests/backend/test_security_audit_contract.py::test_refine_flow_verifies_selection_matches_current_content`

**Outputs:**
- `RefineRequest` max-length constraints
- Cross-field validation for `selection_end >= selection_start`
- Service-level validation that indices are within current content and match `selected_text`
- Clear 400/409 response for stale or invalid selections

**Steps:**
1. Add conservative max lengths to `RefineRequest`: `instruction` at 20,000 characters and `selected_text` at 100,000 characters.
2. Add a Pydantic model validator that rejects `selection_end < selection_start`.
3. In `StageManager.refine()`, after loading `content`, reject if `selection_end > len(content)`.
4. Compare `content[selection_start:selection_end]` to `request.selected_text`; reject stale or mismatched selections before calling the LLM.
5. Raise a typed exception or `ValueError` and map it in the router to a non-500 response.
6. Add tests for oversized instruction, oversized selected text, reversed indices, out-of-range indices, and mismatched selected text.
7. Run `cd backend && uv run pytest tests/test_stage_router.py tests/test_diff_engine.py ../harness/tests/backend/test_security_audit_contract.py -q`.

**Acceptance Criteria:**
- Invalid refine payloads fail before any LLM provider call.
- Stale client selections are rejected instead of being applied to current content.
- The two refine security audit harness tests pass.

**Finding:** 2026-05-04 security audit — unbounded refine payloads and missing selection consistency checks

**Dependencies:** none

---

### T-099: Trust X-Forwarded-For Only from Known Proxies

**Description:**
`RateLimitMiddleware._get_client_ip()` trusts `X-Forwarded-For` unconditionally. If the app is exposed directly or a proxy does not strip user-supplied headers, attackers can rotate spoofed IPs and bypass IP-based login and request rate limits.

**Severity:** Medium — rate-limit bypass under common misdeployment conditions.

**Inputs:**
- `backend/config.py`
- `backend/middleware/rate_limit.py`
- `backend/tests/test_rate_limit.py`
- `harness/tests/backend/test_security_audit_contract.py::test_rate_limiter_only_trusts_forwarded_for_from_known_proxies`

**Outputs:**
- Configured trusted proxy list
- Default behavior that ignores `X-Forwarded-For`
- Tests for direct clients, untrusted clients with spoofed headers, and trusted proxy clients

**Steps:**
1. Add `trusted_proxy_ips: str = ""` or equivalent typed config to `Settings`.
2. Parse the configured list into exact IPs/CIDRs in `rate_limit.py`.
3. Update `_get_client_ip(request)` to use `request.client.host` unless the immediate client is a trusted proxy.
4. Only when the immediate client is trusted, use the first valid IP from `X-Forwarded-For`.
5. Treat malformed forwarded values as absent and fall back to the immediate client host.
6. Add unit tests for spoofed untrusted headers and trusted proxy behavior.
7. Run `cd backend && uv run pytest tests/test_rate_limit.py ../harness/tests/backend/test_security_audit_contract.py -q`.

**Acceptance Criteria:**
- Spoofed `X-Forwarded-For` from an untrusted client has no effect.
- A configured trusted proxy can pass the real client IP.
- The rate-limit security audit harness test passes.

**Finding:** 2026-05-04 security audit — unconditional trust in `X-Forwarded-For`

**Dependencies:** none

---

### T-100: Bind Dev Datastores to Localhost in Docker Compose

**Description:**
`docker-compose.yml` publishes Postgres and Redis to all host interfaces while using development credentials. This is acceptable only on a private developer machine and becomes dangerous on shared hosts, remote dev boxes, or copied staging configs.

**Severity:** Medium/Low — deployment hardening; high impact if the compose file is reused outside local-only development.

**Inputs:**
- `docker-compose.yml`
- `README.md`
- `harness/tests/backend/test_security_audit_contract.py::test_compose_does_not_publish_datastores_on_all_interfaces`

**Outputs:**
- Postgres bound to `127.0.0.1:5432:5432`
- Redis bound to `127.0.0.1:6379:6379`
- README note that compose is development-only

**Steps:**
1. Change the Postgres port mapping from `"5432:5432"` to `"127.0.0.1:5432:5432"`.
2. Change the Redis port mapping from `"6379:6379"` to `"127.0.0.1:6379:6379"`.
3. Add a README note that production must use managed/private datastores and injected secrets, not the dev compose credentials.
4. Run `docker compose config` to validate syntax.
5. Run `cd backend && uv run pytest ../harness/tests/backend/test_security_audit_contract.py -q`.

**Acceptance Criteria:**
- Compose no longer publishes Postgres or Redis on all host interfaces.
- The compose security audit harness test passes.
- Local quickstart still works.

**Finding:** 2026-05-04 security audit — exposed dev datastore ports

**Dependencies:** none

---

### T-101: Add Backend Security Headers Middleware

**Description:**
Backend responses do not set standard browser security headers. Add centralized middleware so routes and error responses receive a consistent baseline policy.

**Severity:** Low/Medium — defense-in-depth required for production readiness.

**Inputs:**
- `backend/main.py`
- `backend/config.py`
- `backend/tests/test_observability.py` or a new `backend/tests/test_security_headers.py`
- `harness/tests/backend/test_security_audit_contract.py::test_backend_sets_standard_security_headers`

**Outputs:**
- Security headers middleware
- Tests verifying headers on representative API responses

**Steps:**
1. Add middleware that sets:
   - `Content-Security-Policy`
   - `X-Frame-Options: DENY`
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy` with a restrictive baseline
2. Add `Strict-Transport-Security` only when `settings.environment == "production"` or an explicit HTTPS setting is enabled.
3. Keep the CSP API-appropriate; do not break JSON or SSE responses.
4. Register the middleware in `create_app()`.
5. Add tests for `/health` and one authenticated route if feasible.
6. Run `cd backend && uv run pytest tests/test_observability.py ../harness/tests/backend/test_security_audit_contract.py -q`.

**Acceptance Criteria:**
- Standard security headers are present on backend responses.
- HSTS is not accidentally emitted for local HTTP development unless explicitly enabled.
- The security headers audit harness test passes.

**Finding:** 2026-05-04 security audit — missing production security headers

**Dependencies:** none

---

### T-102: Strengthen AI Prompt-Injection and Output-Leak Guardrails

**Description:**
The current prompt guard and output validator are regex-based. They catch obvious payloads but can be bypassed by paraphrase, indirection, or encoded instructions. Treat them as one layer, not as the full AI security boundary.

**Severity:** Medium/Low — AI-specific data leakage and integrity risk.

**Inputs:**
- `backend/services/security/prompt_guard.py`
- `backend/services/security/output_validator.py`
- `backend/services/pipeline/prompt_builder.py`
- `backend/tests/test_security.py`

**Outputs:**
- Stronger prompt boundary instructions
- Structured untrusted-content delimiters in prompt builder output
- Expanded prompt-injection and output-leak tests
- Clear comments documenting regex guard limitations

**Steps:**
1. Update prompt builder templates so user problem statements and upstream stage content are wrapped in explicit untrusted-data delimiters.
2. Add system prompt language requiring the model to treat delimited user content as data, not instructions.
3. Expand prompt guard samples with paraphrased, encoded, and indirect injection attempts.
4. Expand output validator tests for partial prompt leakage and policy summaries.
5. Ensure rejected prompt/output events are logged without raw sensitive content.
6. Run `cd backend && uv run pytest tests/test_security.py tests/test_prompt_builder.py -q`.

**Acceptance Criteria:**
- AI guardrails are layered: prompt boundaries, input scan, output validation, and safe logging.
- Tests document the regex layer as best-effort rather than complete protection.
- Prompt builder output clearly separates trusted instructions from untrusted content.

**Finding:** 2026-05-04 security audit — false sense of security from regex-only AI controls

**Dependencies:** T-098

---

### T-103: Make Dependency Security Scanning Non-Interactive in CI

**Description:**
Frontend `pnpm audit --audit-level moderate` completed clean during the audit. Python dependency scanning could not be completed because the local Safety CLI required interactive login. CI needs a non-interactive dependency scan so backend vulnerabilities are checked continuously.

**Severity:** Low/Medium — supply-chain visibility gap.

**Inputs:**
- `.github/workflows/`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `frontend/package.json`
- `frontend/pnpm-lock.yaml`
- `tasks.md`

**Outputs:**
- Non-interactive Python dependency scan in CI
- Frontend audit remains in CI
- Documentation for required scanner token/secret if the selected scanner needs one

**Steps:**
1. Choose the CI scanner path: Safety with `SAFETY_API_KEY`, `pip-audit`, or another non-interactive Python advisory scanner.
2. Add a CI job that installs/syncs backend dependencies from `uv.lock` and scans them without prompts.
3. Ensure the job fails on high/critical advisories and reports moderate advisories.
4. Keep `pnpm audit --audit-level moderate` in the frontend CI path.
5. Document any required CI secret in README/deployment notes.
6. Run the selected scanner locally if possible and confirm CI syntax.

**Acceptance Criteria:**
- Dependency scans can run in CI without human input.
- Python and frontend dependency advisories are both covered.
- The audit limitation is resolved and documented.

**Finding:** 2026-05-04 security audit — Python dependency scan blocked by interactive Safety login

**Dependencies:** none

---

## Phase 8 — Second-Pass Security Verification Fixes

> Issues identified in the post-mitigation security verification pass on 2026-05-04. These are bypasses or incomplete fixes in the Phase 7 mitigations and must be handled as production blockers.

---

### T-104: Apply Security Headers to Unhandled 500 Responses

**Description:**
The Phase 7 security headers middleware adds headers to normal responses, but unhandled application exceptions can be converted into 500 responses without the same browser hardening headers. The error response must also avoid leaking internal exception text.

**Severity:** Medium — production error paths lose defense-in-depth and can disclose internals if handled incorrectly.

**Inputs:**
- `backend/main.py`
- `backend/tests/test_security_headers.py`
- `harness/tests/backend/test_second_pass_security_contract.py`

**Outputs:**
- Shared security-header helper used by middleware and unhandled exception responses
- Generic 500 JSON response without raw exception details
- Backend and harness tests proving 500 responses carry CSP, XFO, XCTO, and Referrer-Policy

**Steps:**
1. Extract centralized security-header application logic in `main.py`.
2. Register an unhandled exception handler that returns a generic 500 response.
3. Apply the same header helper to that exception response.
4. Add a route-level failure test using `TestClient(..., raise_server_exceptions=False)`.
5. Run `cd backend && uv run pytest tests/test_security_headers.py ../harness/tests/backend/test_second_pass_security_contract.py -q`.

**Acceptance Criteria:**
- Normal and unhandled-error responses include the same security header baseline.
- Raw exception messages are not returned to clients.
- Harness coverage prevents this error-path gap from re-entering.

**Finding:** 2026-05-04 second-pass review — security headers missing on unhandled 500s

---

### T-105: Preserve Raw Refine Selection Matching While Sanitizing Prompt Inputs

**Description:**
The router sanitizes `selected_text` before `StageManager.refine()` verifies it against the current document. Harmless markup in the actual selected document text can be stripped before comparison, causing valid refine requests to fail and encouraging callers to bypass the safety check. Raw text must be used for document consistency checks; sanitized text must be used only when constructing the LLM prompt.

**Severity:** High — incomplete mitigation in a security-sensitive LLM edit path.

**Inputs:**
- `backend/routers/stage.py`
- `backend/services/pipeline/stage_manager.py`
- `backend/tests/test_stage_router.py`
- `backend/tests/test_stage_manager.py`
- `harness/tests/backend/test_second_pass_security_contract.py`

**Outputs:**
- Router passes raw `RefineRequest` to the stage manager
- Stage manager scans raw inputs, compares raw selected text to raw document slice, then sanitizes instruction and selection at the prompt boundary
- Tests for raw markup selection success and sanitized prompt fields

**Steps:**
1. Remove router-level selected text mutation.
2. Keep prompt-injection scanning before any LLM call.
3. Compare `content[selection_start:selection_end]` to raw `request.selected_text`.
4. Sanitize `request.instruction` and `request.selected_text` immediately before prompt construction.
5. Update router tests to assert raw preservation.
6. Add service tests that valid markup selections still refine and prompt fields are sanitized.

**Acceptance Criteria:**
- Stale-selection protection remains enforced.
- Valid raw selections containing harmless markup are accepted.
- User-controlled instruction and selected text are sanitized before entering the LLM prompt.

**Finding:** 2026-05-04 second-pass review — refine sanitization broke raw selection consistency

---

### T-106: Reject Universal Trusted Proxy Ranges

**Description:**
`trusted_proxy_ips` fixed default `X-Forwarded-For` spoofing, but accepting `0.0.0.0/0` or `::/0` silently turns every client into a trusted proxy. That single misconfiguration fully reintroduces the rate-limit bypass.

**Severity:** High — one environment variable can disable IP-based throttling.

**Inputs:**
- `backend/middleware/rate_limit.py`
- `backend/tests/test_rate_limit.py`
- `harness/tests/backend/test_second_pass_security_contract.py`

**Outputs:**
- Trusted proxy parser rejects universal IPv4 and IPv6 ranges
- Unit and harness tests for unsafe proxy configuration

**Steps:**
1. Parse proxy entries with `ip_network(..., strict=False)`.
2. Raise `ValueError` for any network with prefix length `0`.
3. Keep malformed non-universal entries ignored as before.
4. Add tests for `0.0.0.0/0` and `::/0`.

**Acceptance Criteria:**
- Universal proxy trust cannot be configured accidentally.
- Legitimate specific proxy IPs/CIDRs still work.
- Spoofed `X-Forwarded-For` remains ignored by default.

**Finding:** 2026-05-04 second-pass review — bypassable trusted proxy configuration

---

### T-107: Make Security Harness Contracts Import-Stable and CI-Enforced

**Description:**
The security harness imported helpers from bare `conftest`, which collides with `backend/tests/conftest.py` when backend and harness tests are collected together. CI also ran backend tests but did not run the focused security harness contracts.

**Severity:** Medium — security regression tests can be skipped or fail for the wrong reason.

**Inputs:**
- `harness/tests/backend/conftest.py`
- `harness/tests/backend/harness_utils.py`
- `harness/tests/backend/test_security_audit_contract.py`
- `.github/workflows/ci.yml`

**Outputs:**
- Import-stable harness utility module
- Security audit and second-pass harness contracts run in CI

**Steps:**
1. Move shared harness helpers into `harness_utils.py`.
2. Update security harness tests to import from `harness_utils`.
3. Keep `conftest.py` as a thin compatibility re-export.
4. Add a backend CI step that runs the focused security harness contract files.

**Acceptance Criteria:**
- `cd backend && uv run pytest ../harness/tests/backend/test_security_audit_contract.py ../harness/tests/backend/test_second_pass_security_contract.py -q` passes.
- The security harness no longer depends on pytest's `conftest` import resolution.
- CI fails if focused security contracts regress.

**Finding:** 2026-05-04 second-pass review — security harness reliability gap

---

### T-108: Harden Export Filenames for Windows Extraction

**Description:**
Zip Slip traversal was fixed, but exported harness filenames could still include Windows-reserved device names or alternate data stream syntax. These do not escape the `harness/` prefix on POSIX, but they are unsafe for Windows consumers extracting the archive.

**Severity:** Medium — cross-platform archive extraction hardening gap.

**Inputs:**
- `backend/services/pipeline/export_service.py`
- `backend/tests/test_export_service.py`
- `harness/tests/backend/test_second_pass_security_contract.py`

**Outputs:**
- Harness filenames reject `CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`, colon-delimited names, and control characters
- Backend and harness tests for Windows-unsafe names

**Steps:**
1. Extend `_safe_harness_path()` with Windows reserved-name checks per path part.
2. Reject `:` anywhere in a path part.
3. Reject ASCII control characters before creating ZIP members.
4. Add export parser tests for reserved names and alternate data streams.

**Acceptance Criteria:**
- Exported ZIP member paths remain safe for POSIX and Windows extraction.
- Valid relative harness paths continue to export normally.
- Security harness covers the cross-platform filename hardening.

**Finding:** 2026-05-04 second-pass review — Windows archive extraction hardening gap

---

## Phase 9 — Final Production Hardening

> Items from the final security sign-off before production exposure. These address high-risk deployment assumptions, residual abuse paths, and the most likely realistic attack chain.

---

### T-109: Fail Closed on Unsafe Production Configuration

**Description:**
The final gate identified metrics exposure and non-HTTPS frontend configuration as the most important deployment-time risks. Production must not start unless metrics are token-protected and the browser origin is HTTPS.

**Severity:** High — reverse proxy topology can make localhost-only metrics checks unsafe, and non-HTTPS frontend origins weaken cookie/session assumptions.

**Inputs:**
- `backend/config.py`
- `backend/main.py`
- `backend/services/observability.py`
- `backend/.env.example`
- `backend/tests/test_observability.py`

**Outputs:**
- `validate_production_settings()` called during app creation
- Production requires `METRICS_TOKEN`
- Production requires HTTPS `FRONTEND_URL`
- `.env.example` documents `METRICS_TOKEN`

**Acceptance Criteria:**
- Production app startup fails without `METRICS_TOKEN`.
- Production app startup fails with non-HTTPS `FRONTEND_URL`.
- Metrics remain token-protected in production.

---

### T-110: Reduce Public Health Information in Production

**Description:**
`/health` exposed dependency-level status. That is useful in development but unnecessary public infrastructure detail in production.

**Severity:** Low/Medium — information disclosure reduction.

**Inputs:**
- `backend/main.py`
- `backend/tests/test_security_headers.py`

**Outputs:**
- Production health response includes only overall status and version
- Development/test health response keeps dependency detail

**Acceptance Criteria:**
- Production `/health` omits `db` and `redis` keys.
- Health checks still work for deployment readiness.

---

### T-111: Add Active Workspace Abuse Quota

**Description:**
Authenticated users are rate-limited, but they can still accumulate many active workspaces over time. Add a per-user active workspace quota to reduce storage, LLM workflow, and export abuse.

**Severity:** Medium — cost and service disruption risk.

**Inputs:**
- `backend/config.py`
- `backend/services/workspace_service.py`
- `backend/tests/test_workspace.py`

**Outputs:**
- `max_active_workspaces_per_user` setting
- Workspace creation rejects quota overflow with `429`
- `.env.example` documents the quota

**Acceptance Criteria:**
- Users cannot create more than the configured number of active workspaces.
- Archived workspaces do not count against future active-workspace creation.

---

### T-112: Treat Refine Current Document as Untrusted LLM Input

**Description:**
The refine path sanitized instruction and selected text, but still placed the full current document in the LLM prompt without explicit untrusted-data boundaries. Prior generated content or manual edits can carry indirect prompt injection into future refine calls.

**Severity:** Medium — AI integrity and data leakage defense-in-depth.

**Inputs:**
- `backend/services/pipeline/stage_manager.py`
- `backend/tests/test_stage_manager.py`
- `harness/tests/backend/test_final_hardening_contract.py`

**Outputs:**
- Refine system prompt includes the shared security/privacy rules
- Current document, selected text, and instruction are wrapped with untrusted-content delimiters
- Tests assert the prompt boundary

**Acceptance Criteria:**
- The refine prompt no longer presents current document content as authoritative instructions.
- Sanitized selected text and instruction remain wrapped as untrusted content.

---

### T-113: Migrate Gemini Adapter to Supported Google Gen AI SDK

**Description:**
`google-generativeai` is deprecated. Replace it with the supported `google-genai` SDK to avoid shipping a stale provider integration into production.

**Severity:** Low/Medium — dependency lifecycle and provider reliability risk.

**Inputs:**
- `backend/pyproject.toml`
- `backend/requirements.txt`
- `backend/uv.lock`
- `backend/services/llm/google_adapter.py`
- `backend/tests/test_llm_gateway.py`

**Outputs:**
- Dependency uses `google-genai`
- Google adapter uses `google.genai.Client`
- Deprecated import warning is eliminated

**Acceptance Criteria:**
- No `google.generativeai` import remains.
- Backend tests run without the prior deprecation warning.
- `pip-audit` remains clean.

---

_tasks.md · SpecForge V1 · Version 1.7.0 · Updated 2026-05-04 with Phase 9 final production hardening T-109 through T-113_

---

## Phase 10 — Final Production Readiness Audit Remediations

> Issues identified in the principal-engineer production readiness audit (2026-05-04). Ordered by severity: the blocker must ship first, high-risk items second. Each task maps to a contract test in `harness/tests/backend/test_production_readiness_contract.py`.

---

### T-114: Fix Credit Ledger Unique Constraint to Prevent Repeat-Operation Failures

**Description:**
Migration `0003_credit_ledger_unique_refund.py` adds `UNIQUE(user_id, reason)` to the `credit_ledger` table. The intent was to prevent double-refunds (refund reasons are `f"refund:{ledger_entry_id}"` — unique UUIDs). But the constraint applies to **every row**, including normal deductions. Because `credit_service.deduct()` is called with `reason="generate"` or `reason="refine"` on every LLM call, the second generation or refinement by any user triggers a `UniqueViolation` that propagates as a 500. The core product flow — generating content — breaks after the first use.

**Severity:** BLOCKER — primary product feature is non-functional after first use per user.

**Inputs:**
- `backend/migrations/versions/0003_credit_ledger_unique_refund.py`
- `backend/services/credit_service.py` — `refund()`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_credit_ledger_constraint_is_not_broad_unique_on_user_reason`, `test_credit_service_can_deduct_multiple_times_with_same_reason`

**Outputs:**
- `backend/migrations/versions/0005_fix_credit_refund_partial_index.py` — new migration
- Updated `0003` is no longer applied as a broad unique constraint (superseded by 0005)
- `credit_service.refund()` idempotency preserved via application-layer `IntegrityError` catch + partial DB index

**Steps:**
1. Create `backend/migrations/versions/0005_fix_credit_refund_partial_index.py`:
   ```python
   """Replace broad UNIQUE(user_id, reason) with partial index on refund rows only.

   Revision ID: 0005
   Revises: 0004
   """
   from alembic import op

   revision = "0005"
   down_revision = "0004"

   def upgrade() -> None:
       # Drop the overly-broad unique constraint added in 0003
       op.drop_constraint(
           "uq_credit_ledger_user_reason", "credit_ledger", type_="unique"
       )
       # Replace with a partial unique index scoped to refund rows only
       op.execute("""
           CREATE UNIQUE INDEX uq_credit_ledger_refund_reason
           ON credit_ledger (user_id, reason)
           WHERE reason LIKE 'refund:%'
       """)

   def downgrade() -> None:
       op.execute("DROP INDEX IF EXISTS uq_credit_ledger_refund_reason")
       op.create_unique_constraint(
           "uq_credit_ledger_user_reason", "credit_ledger", ["user_id", "reason"]
       )
   ```
2. Verify `credit_service.refund()` still catches `IntegrityError` on flush — the partial index is now the enforcement mechanism for double-refunds.
3. Add a CI backend job step that starts a real PostgreSQL service and runs `uv run alembic upgrade head` before pytest, so schema-level bugs like this are caught automatically. In `.github/workflows/ci.yml`, add `services: postgres: ...` to the backend job and a migration step.
4. Run `uv run pytest tests/test_credit_service.py -q` to confirm all tests pass.
5. Run the harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "credit" -q`.

**Acceptance Criteria:**
- A user can call `deduct()` with `reason="generate"` more than once without error.
- `refund()` with a duplicate `ledger_entry_id` is still silently swallowed (idempotency preserved).
- Migration 0005 applies cleanly to a fresh database (drops the broad constraint, adds the partial index).
- Harness contract tests `test_credit_ledger_constraint_is_not_broad_unique_on_user_reason` and `test_credit_service_can_deduct_multiple_times_with_same_reason` pass.
- All existing credit service tests pass.

**Finding:** B-1 — `backend/migrations/versions/0003_credit_ledger_unique_refund.py`

**Dependencies:** T-113

---

### T-115: Bind Docker Compose API Port to Localhost

**Description:**
`docker-compose.yml` binds the API service port as `"8000:8000"` (listens on all interfaces). The database and Redis ports are correctly bound to `127.0.0.1`. For self-hosted deployments — the stated use case in the README — this exposes the API directly to any host on the network, bypassing any intended reverse-proxy layer. The API port must follow the same localhost-binding pattern as the datastores.

**Severity:** High — network-level exposure of the API in self-hosted Docker environments.

**Inputs:**
- `docker-compose.yml`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_compose_does_not_expose_api_port_on_all_interfaces`

**Outputs:**
- Updated `docker-compose.yml` with `127.0.0.1:8000:8000`

**Steps:**
1. In `docker-compose.yml`, change the `api` service port mapping:
   ```yaml
   api:
     ports:
       - "127.0.0.1:8000:8000"
   ```
2. Update `README.md` if it references `localhost:8000` (the change is backward-compatible — local browser access still works via `http://localhost:8000`).
3. Run `docker compose up --build` locally and confirm `GET http://localhost:8000/health` returns 200.
4. Run harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "api_port" -q`.

**Acceptance Criteria:**
- `docker-compose.yml` does not contain `"8000:8000"` (unbound).
- `"127.0.0.1:8000:8000"` is present in `docker-compose.yml`.
- Harness test `test_compose_does_not_expose_api_port_on_all_interfaces` passes.
- Existing harness test `test_compose_does_not_publish_datastores_on_all_interfaces` still passes.

**Finding:** H-3 — `docker-compose.yml`

**Dependencies:** T-100 (datastores already bound; this extends the same pattern to the API)

---

### T-116: Disable FastAPI Documentation Endpoints in Production

**Description:**
`FastAPI(title="SpecForge API", ...)` enables `/docs`, `/redoc`, and `/openapi.json` by default. In production, unauthenticated users can enumerate the full API surface including all endpoint paths, parameters, and schema shapes. These endpoints must be suppressed when `settings.environment == "production"`.

**Severity:** High — API surface enumeration by unauthenticated users in production.

**Inputs:**
- `backend/main.py` — `create_app()`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_fastapi_docs_are_disabled_in_production`, `test_fastapi_app_does_not_expose_openapi_schema_in_production`

**Outputs:**
- Updated `backend/main.py` — `FastAPI()` call passes `docs_url`, `redoc_url`, `openapi_url` conditionally

**Steps:**
1. In `create_app()`, determine whether to expose docs based on the environment:
   ```python
   is_production = settings.environment.lower() == "production"
   app = FastAPI(
       title="SpecForge API",
       version="1.0.0",
       lifespan=lifespan,
       docs_url=None if is_production else "/docs",
       redoc_url=None if is_production else "/redoc",
       openapi_url=None if is_production else "/openapi.json",
   )
   ```
2. Add a test in `test_security_headers.py` (or a new file) that creates the app with `environment="production"` and asserts `GET /docs`, `GET /redoc`, and `GET /openapi.json` all return 404.
3. Confirm development (`environment="development"`) still serves docs normally.
4. Run `uv run pytest tests/ -q` to confirm no regressions.
5. Run harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "docs" -q`.

**Acceptance Criteria:**
- `GET /docs`, `GET /redoc`, `GET /openapi.json` return 404 when `ENVIRONMENT=production`.
- Both endpoints remain accessible in development/test environments.
- Harness tests `test_fastapi_docs_are_disabled_in_production` and `test_fastapi_app_does_not_expose_openapi_schema_in_production` pass.
- All existing tests pass.

**Finding:** H-4 — `backend/main.py`

**Dependencies:** T-109 (production settings validation already in place)

---

### T-117: Harden Production Startup Validation for Critical Secrets

**Description:**
`validate_production_settings()` in `config.py` only checks `METRICS_TOKEN` and `FRONTEND_URL`. A production deploy with `JWT_PRIVATE_KEY="ci-test-private-key"` or `ENCRYPTION_MASTER_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA..."` (the CI fixture values) passes startup validation silently. The validator must reject placeholder or structurally invalid values for the two most critical secrets: the JWT signing key (must be a real RSA/EC private key) and the Fernet encryption master key (must not be the known CI placeholder).

**Severity:** High — production deploy with CI stub keys would compromise all JWTs and all encrypted user API keys.

**Inputs:**
- `backend/config.py` — `validate_production_settings()`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_production_validation_checks_jwt_key_strength`, `test_production_validation_checks_encryption_key_is_not_default`

**Outputs:**
- Updated `backend/config.py` with two additional production checks

**Steps:**
1. In `validate_production_settings()`, add:
   ```python
   if not settings.jwt_private_key.strip().startswith("-----BEGIN"):
       errors.append(
           "JWT_PRIVATE_KEY must be a PEM-encoded RSA or EC private key "
           "(must start with '-----BEGIN'). The CI stub value is not valid for production."
       )
   _CI_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
   if settings.encryption_master_key == _CI_ENCRYPTION_KEY:
       errors.append(
           "ENCRYPTION_MASTER_KEY is set to the known CI placeholder value. "
           "Generate a unique Fernet key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
       )
   ```
2. Add unit tests in `test_security_headers.py` or a new `test_config.py`:
   - Test: `validate_production_settings()` raises with a stub JWT key.
   - Test: raises with the CI placeholder encryption key.
   - Test: passes with a real PEM header on the JWT key.
3. Run `uv run pytest tests/ -q`.
4. Run harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "validation" -q`.

**Acceptance Criteria:**
- `validate_production_settings()` raises `RuntimeError` if `JWT_PRIVATE_KEY` does not start with `-----BEGIN`.
- Raises if `ENCRYPTION_MASTER_KEY` equals the CI placeholder.
- Both checks are bypassed for non-production environments.
- Harness tests `test_production_validation_checks_jwt_key_strength` and `test_production_validation_checks_encryption_key_is_not_default` pass.

**Finding:** H-2 — `backend/config.py`

**Dependencies:** T-109

---

### T-118: Make Rate Limiter Count Check Atomic with a Lua Script

**Description:**
`sliding_window_check()` in `rate_limit.py` uses a Redis pipeline that adds the current request (`ZADD`) before checking the count (`ZCARD`). Because the pipeline is not a Lua script, multiple concurrent requests can each add themselves and read a count that already includes all of them — allowing up to ~2× the configured limit to pass simultaneously before any rejection fires. Under a coordinated burst attack, this headroom is meaningful. The fix is a Lua script that atomically checks the window count before conditionally adding the new member.

**Severity:** High — rate limit enforcement is non-strict under concurrent load.

**Inputs:**
- `backend/middleware/rate_limit.py` — `sliding_window_check()`
- `backend/tests/test_rate_limit.py`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_rate_limiter_uses_atomic_count_before_add`

**Outputs:**
- Updated `sliding_window_check()` using a Lua script via `redis_client.eval()` or `redis_client.register_script()`

**Steps:**
1. Replace the pipeline in `sliding_window_check()` with a Lua script:
   ```python
   _SLIDING_WINDOW_LUA = """
   local key = KEYS[1]
   local now = tonumber(ARGV[1])
   local window_start = tonumber(ARGV[2])
   local limit = tonumber(ARGV[3])
   local member = ARGV[4]
   local ttl = tonumber(ARGV[5])

   redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
   local count = redis.call('ZCARD', key)
   if count >= limit then
     return 0
   end
   redis.call('ZADD', key, now, member)
   redis.call('EXPIRE', key, ttl)
   return 1
   """

   async def sliding_window_check(
       redis_client: Redis,
       key: str,
       limit: int,
       window_seconds: int,
   ) -> bool:
       now = time.time()
       window_start = now - window_seconds
       ratelimit_key = f"ratelimit:{key}"
       member = str(time.time_ns())
       result = await redis_client.eval(
           _SLIDING_WINDOW_LUA,
           1,
           ratelimit_key,
           str(now),
           str(window_start),
           str(limit),
           member,
           str(window_seconds),
       )
       return bool(result)
   ```
2. Remove the old pipeline-based implementation.
3. Update `test_rate_limit.py`: the `_NoopRedis` / `_FakeRedis` stubs must now implement `eval()`. Replace with a real in-memory Redis stub that returns `1` (allowed) or `0` (rejected) based on the limit argument passed.
4. Run `uv run pytest tests/test_rate_limit.py -q`.
5. Run harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "rate_limiter" -q`.

**Acceptance Criteria:**
- `sliding_window_check` uses `redis_client.eval()` (Lua) rather than a pipeline of ZADD+ZCARD.
- The Lua script checks the count BEFORE adding the new member.
- Concurrent requests at the exact limit boundary: only requests up to the limit are accepted; the (limit+1)th request is rejected.
- Harness test `test_rate_limiter_uses_atomic_count_before_add` passes.
- All existing rate limit tests pass.

**Finding:** H-1 — `backend/middleware/rate_limit.py`

**Dependencies:** T-075

---

### T-119: Run Database Migrations Before App Start in Docker

**Description:**
`docker-compose.yml` starts the API with `uvicorn main:app` directly without first running `alembic upgrade head`. A fresh deployment against an empty database, or any re-deploy that introduces a new migration, will start the app against a stale schema. SQLAlchemy errors will occur mid-request rather than at startup, making the failure mode confusing and slow to diagnose. Migrations must run and succeed before uvicorn accepts traffic.

**Severity:** Medium — every fresh deployment or migration deploy fails silently at the request level.

**Inputs:**
- `docker-compose.yml` — `api.command`
- `backend/Dockerfile`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_docker_compose_or_dockerfile_runs_migrations_on_startup`

**Outputs:**
- Updated `docker-compose.yml` api command, OR new `backend/entrypoint.sh` referenced by Dockerfile

**Steps:**
1. **Option A (simplest)** — update `docker-compose.yml` api command:
   ```yaml
   api:
     command: >
       sh -c "uv sync --frozen --no-dev &&
              uv run --no-sync alembic upgrade head &&
              uv run --no-sync uvicorn main:app --reload --host 0.0.0.0 --port 8000"
   ```
2. **Option B (production Dockerfile)** — create `backend/entrypoint.sh`:
   ```bash
   #!/bin/sh
   set -e
   uv run alembic upgrade head
   exec uv run gunicorn main:app --worker-class uvicorn.workers.UvicornWorker \
     --workers 2 --bind 0.0.0.0:8000
   ```
   Update `backend/Dockerfile` CMD to `["./entrypoint.sh"]` and `chmod +x entrypoint.sh`.
3. Implement both Option A (for local dev compose) and Option B (for production Dockerfile).
4. Test locally: `docker compose down -v && docker compose up --build` — app must start healthy with all migrations applied.
5. Run harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "migrations" -q`.

**Acceptance Criteria:**
- `docker compose up --build` on a fresh volume applies all migrations before accepting requests.
- `GET /health` returns 200 after `docker compose up` without manual migration steps.
- Harness test `test_docker_compose_or_dockerfile_runs_migrations_on_startup` passes.
- README self-hosting instructions (4-step flow) remain accurate.

**Finding:** M-2 — `docker-compose.yml`, `backend/Dockerfile`

**Dependencies:** T-056

---

### T-120: Reference CREDIT_COSTS Constant in Recovery Service

**Description:**
`recovery_service.py` logs `credits_refunded = 10` as a hardcoded integer. The actual refund via `credit_service.refund()` is correct (uses the original ledger entry amount). But the log line is wrong if the generate cost ever changes from 10. Import `CREDIT_COSTS` from `stage_manager` and use `CREDIT_COSTS["generate"]` so the log value stays in sync automatically.

**Severity:** Minor — log inaccuracy if credit costs change; no functional impact.

**Inputs:**
- `backend/services/pipeline/recovery_service.py` — `recover_stuck_stages()`
- `backend/services/pipeline/stage_manager.py` — `CREDIT_COSTS`
- `harness/tests/backend/test_production_readiness_contract.py` — `test_recovery_service_uses_credit_costs_constant`

**Outputs:**
- Updated `backend/services/pipeline/recovery_service.py`

**Steps:**
1. Add import at the top of `recovery_service.py`:
   ```python
   from services.pipeline.stage_manager import CREDIT_COSTS
   ```
2. Replace:
   ```python
   credits_refunded = 10  # standard generate cost
   ```
   with:
   ```python
   credits_refunded = CREDIT_COSTS["generate"]
   ```
3. Run `uv run pytest tests/test_recovery_service.py -q`.
4. Run harness: `uv run pytest ../harness/tests/backend/test_production_readiness_contract.py -k "recovery" -q`.

**Acceptance Criteria:**
- `recovery_service.py` contains no literal `credits_refunded = 10`.
- `CREDIT_COSTS` is imported from `stage_manager`.
- Harness test `test_recovery_service_uses_credit_costs_constant` passes.
- All existing recovery service tests pass.

**Finding:** M-4 — `backend/services/pipeline/recovery_service.py`

**Dependencies:** none

---

_tasks.md · SpecForge V1 · Version 1.8.0 · Updated 2026-05-04 with Phase 10 production readiness audit remediations T-114 through T-120_
