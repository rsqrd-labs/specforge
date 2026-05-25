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

---

## Phase 11 — Langfuse LLM Observability

> Adds an **optional** complementary LLM observability layer alongside the existing Grafana Cloud + Sentry stack. Architecture lives in `SpecForge — Complete System Architecture.md` §8a. Plan rationale lives in `Plan v1.md` §15. Every task here maps to a contract in `harness/tests/backend/test_langfuse_contract.py`.
>
> **Non-negotiables for every task in this phase:**
> 1. The integration is gated by `LANGFUSE_SECRET_KEY`. When unset/empty, zero Langfuse SDK calls are made. The check lives only in `services/langfuse_service.py`.
> 2. `BaseLLMAdapter` interface remains unchanged. Provider adapters never import Langfuse.
> 3. All Langfuse calls are exception-swallowing — a Langfuse outage cannot break stage generation, refine, eval, or credits.
> 4. Sensitive data redaction reuses `services.observability.redact_sensitive_data()`. No new regex patterns.
> 5. Streams are accumulated and recorded once per call, never per token.
> 6. CI must remain green: 172+ unit tests + 26 harness CI tests + new Langfuse contract tests.

---

### T-121: Add Langfuse to Requirements and Config

**Description:**
Install the Langfuse Python SDK and add four optional configuration fields to `Settings`. Document the new variables in `.env.example` and the README. The application must continue to start and operate normally when none of the new variables are set.

**Severity:** Setup — prerequisite for all subsequent Phase 11 work.

**Inputs:**
- `backend/pyproject.toml` (or `backend/requirements.txt`)
- `backend/config.py` — `Settings`
- `backend/.env.example`
- `README.md` — Backend Variables table and Observability section
- `harness/tests/backend/test_langfuse_contract.py` — `test_langfuse_is_in_backend_requirements`, `test_settings_has_optional_langfuse_fields`

**Outputs:**
- `langfuse==2.*` added to `pyproject.toml` / `requirements.txt`
- Four new optional fields on `Settings`:
  - `langfuse_secret_key: str = ""`
  - `langfuse_public_key: str = ""`
  - `langfuse_host: str = "https://cloud.langfuse.com"`
  - `langfuse_prompt_cache_ttl: int = 300`
- `.env.example` updated with documented blanks for each
- `README.md` Backend Variables table extended
- `README.md` Observability section mentions optional Langfuse integration

**Steps:**
1. Add `langfuse>=2.60,<3` to `backend/pyproject.toml` `[project] dependencies` (use `uv add 'langfuse>=2.60,<3'`). Pin rationale: see Plan §15.9 Q5. v3/v4 moved to an OTel context-manager API and require bumping `opentelemetry-instrumentation-* == 0.49.*`; both are deferred follow-ups.
2. Run `uv sync` in `backend/` and confirm `uv run python -c "import langfuse; print(langfuse.__version__)"` prints `2.60.x`.
3. In `backend/config.py`, append the four new fields to `Settings` after the existing observability fields (`grafana_otlp_token`). Each must have a safe default and never be required.
4. In `backend/.env.example`, add the four variables under a new `# LLM Observability (optional)` section. Comment: `# Leave LANGFUSE_SECRET_KEY blank to disable instrumentation.`
5. In `README.md`, add four rows to the Backend Variables table and add a paragraph in the Observability section explaining: "Langfuse is an optional LLM-observability sink. With `LANGFUSE_SECRET_KEY` unset the application runs identically to today."
6. Run `uv run python -c "from main import app; print('ok')"` with **all four Langfuse variables unset** to confirm the app starts.
7. Run `uv run pytest tests/ -q` — all 172+ existing tests must pass.

**Acceptance Criteria:**
- `uv run python -c "import langfuse"` exits 0.
- `Settings.model_fields` contains `langfuse_secret_key`, `langfuse_public_key`, `langfuse_host`, `langfuse_prompt_cache_ttl`.
- The app starts cleanly with no Langfuse env vars set.
- All existing 172+ unit tests pass.
- Harness tests `test_langfuse_is_in_backend_requirements` and `test_settings_has_optional_langfuse_fields` pass.

**Dependencies:** none (entrypoint for Phase 11)

---

### T-122: Implement LangfuseClient Service Wrapper

**Description:**
Create the single integration point `backend/services/langfuse_service.py` containing `LangfuseClient` and a `get_langfuse_client()` singleton factory. The client provides one no-op implementation when `LANGFUSE_SECRET_KEY` is empty and a real SDK-backed implementation when configured. Every public method is async-safe and exception-swallowing — errors are logged via structlog and never re-raised.

**Severity:** Foundational — every subsequent task depends on this module.

**Inputs:**
- `backend/services/observability.py` — `redact_sensitive_data()`
- `backend/config.py` — `settings.langfuse_*` (from T-121)
- `harness/tests/backend/test_langfuse_contract.py` — `test_langfuse_service_module_exists`, `test_langfuse_client_makes_zero_sdk_calls_when_unconfigured`, `test_langfuse_client_swallows_all_exceptions`, `test_langfuse_service_redacts_sensitive_data_via_observability_helper`, `test_no_op_path_makes_zero_network_calls`

**Outputs:**
- New `backend/services/langfuse_service.py` exporting `LangfuseClient` and `get_langfuse_client()`
- Six public async methods, each redacting input via `redact_sensitive_data()` and wrapped in `try/except Exception:` with a `logger.error(...)`:
  - `create_trace(name, metadata) -> str | None`
  - `create_span(trace_id, name, metadata) -> str | None`
  - `create_generation(span_id, **kwargs) -> str | None`
  - `score_generation(generation_id, name, value) -> None`
  - `add_to_dataset(dataset_name, item) -> None`
  - `get_prompt(name, version=None) -> str | None`
- Unit tests in `backend/tests/test_langfuse_service.py` covering both configured and unconfigured paths

**Steps:**
1. Create `backend/services/langfuse_service.py`:
   - Import `redact_sensitive_data` from `services.observability`.
   - Define `class LangfuseClient` with `_enabled = bool(settings.langfuse_secret_key)`. SDK client is constructed lazily inside `_ensure_client()`; when disabled, return `None` and never import `langfuse`.
   - Each public method: redact inputs first, then `client = self._ensure_client(); if client is None: return None`, then `try/except Exception:` around the SDK call.
   - Module-level `_INSTANCE: LangfuseClient | None = None` and `def get_langfuse_client() -> LangfuseClient` returning the singleton.
2. Create `backend/tests/test_langfuse_service.py`:
   - Test the no-op path: `monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")`, reload config, assert all six methods return without raising and never construct the SDK client.
   - Test the configured path: replace `client._client` with a `MagicMock` whose methods raise. Assert all six public methods still return without raising.
   - Test redaction: pass a string containing `sk-ant-abc123def456` to `create_generation` as part of `user`. Assert the SDK call (mocked) receives a redacted version.
3. Run `uv run pytest tests/test_langfuse_service.py -q` — must pass.
4. Run `uv run pytest tests/ -q` — all 172+ existing tests must pass (new tests bring the count up).
5. Run `uv run ruff check . && uv run black --check .`.
6. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "langfuse_service or langfuse_client or no_op" -q`.

**Acceptance Criteria:**
- `services/langfuse_service.py` exists, defines `LangfuseClient` and `get_langfuse_client()`.
- With `LANGFUSE_SECRET_KEY=""`, every public method returns without raising and `_client` remains `None` after the calls (proving the SDK is never imported).
- With a configured key but a raising SDK mock, every public method returns without raising.
- The module imports `redact_sensitive_data` from `services.observability`. It does not redefine `_SECRET_PATTERNS` or any redaction regex.
- All existing tests pass; ruff and black are clean.
- Harness tests `test_langfuse_service_module_exists`, `test_langfuse_client_makes_zero_sdk_calls_when_unconfigured`, `test_langfuse_client_swallows_all_exceptions`, `test_langfuse_service_redacts_sensitive_data_via_observability_helper`, and `test_no_op_path_makes_zero_network_calls` all pass.

**Dependencies:** T-121

---

### T-123: Implement InstrumentedAdapter

**Description:**
Create `backend/services/llm/instrumented_adapter.py` defining `InstrumentedAdapter`, a `BaseLLMAdapter` subclass that composes any other `BaseLLMAdapter` and records each call as a Langfuse `generation`. The wrapper must be a true pass-through: `stream()` yields identical tokens, `complete()` returns the identical string, both methods preserve their existing signatures. For `stream()`, the full response is accumulated and recorded **once** after the stream closes — never token-by-token.

**Severity:** Critical — this is the integration point where prompts and outputs are captured.

**Inputs:**
- `backend/services/llm/base.py` — `BaseLLMAdapter`
- `backend/services/langfuse_service.py` (from T-122)
- `backend/services/observability.py` — `redact_sensitive_data()`
- `harness/tests/backend/test_langfuse_contract.py` — `test_base_llm_adapter_signature_unchanged`, `test_provider_adapters_do_not_import_langfuse`, `test_instrumented_adapter_module_exists`, `test_instrumented_adapter_passes_through_to_wrapped_adapter`, `test_instrumented_adapter_records_provider_and_model_metadata`, `test_instrumented_adapter_records_full_accumulated_stream`, `test_existing_adapter_tests_remain_green_when_instrumentation_enabled`

**Outputs:**
- New `backend/services/llm/instrumented_adapter.py` exporting `InstrumentedAdapter(BaseLLMAdapter)`
- Constructor: `(wrapped: BaseLLMAdapter, *, span_id: str | None, provider: str, model: str, stage_type: str, action: str)`
- `stream()`: accumulates all tokens, yields each unchanged, calls `langfuse_service.create_generation(...)` once after the stream closes with the full accumulated output, model, provider, system+user prompts (redacted), latency, and token counts (when available)
- `complete()`: records latency around the wrapped call, calls `create_generation(...)` once with the input/output and metadata
- Unit tests in `backend/tests/test_instrumented_adapter.py`

**Steps:**
1. Create `backend/services/llm/instrumented_adapter.py`:
   - Subclass `BaseLLMAdapter`. **Do not modify `BaseLLMAdapter` itself.**
   - In `stream()`: open a `try/finally` block. Record `t0 = time.perf_counter()`. Iterate the wrapped adapter's stream, append each token to a list, `yield` each token to the caller. On stream completion (or in `finally` on early exit), call `await langfuse_service.create_generation(span_id=..., model=..., provider=..., input={"system": ..., "user": ...}, output="".join(accumulated), latency_ms=..., metadata={"stage_type": ..., "action": ...})`. Wrap that call in its own `try/except Exception:` so a Langfuse failure cannot bleed into the generator path.
   - In `complete()`: same recording pattern, no streaming.
   - Inputs (system, user, output) must be passed through `redact_sensitive_data()` before being submitted (this is also done inside `LangfuseClient`, but defense-in-depth here keeps the wrapper safe even if `LangfuseClient` is bypassed).
2. Verify provider adapter files are unchanged: `git diff backend/services/llm/anthropic_adapter.py backend/services/llm/openai_adapter.py backend/services/llm/google_adapter.py` must return no output.
3. Create `backend/tests/test_instrumented_adapter.py`:
   - Define a `FakeAdapter` subclass of `BaseLLMAdapter` with deterministic outputs.
   - Test pass-through: stream yields identical tokens; complete returns identical string.
   - Test single-recording: with `stream()` over 5 tokens, exactly one `create_generation` call is made with `output == "".join(tokens)`.
   - Test span_id forwarding, provider/model metadata, stage_type, action.
   - Test that an exception inside `create_generation` does not break the stream.
4. Run `uv run pytest tests/test_instrumented_adapter.py -q`.
5. Run `uv run pytest tests/ -q` — all 172+ existing tests + new tests pass.
6. Run `uv run ruff check . && uv run black --check .`.
7. Run harness tests: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "instrumented or base_llm or provider_adapters or accumulated" -q`.

**Acceptance Criteria:**
- `BaseLLMAdapter.stream()` and `.complete()` signatures unchanged (parameters: `self, system, user, max_tokens`).
- No reference to "langfuse" in `anthropic_adapter.py`, `openai_adapter.py`, or `google_adapter.py`.
- `InstrumentedAdapter.stream()` yields the same token sequence as the wrapped adapter.
- `InstrumentedAdapter.complete()` returns the same string as the wrapped adapter and forwards args unchanged.
- For a stream that yields N tokens, `create_generation` is called exactly **once** with the full accumulated output.
- Exceptions inside `create_generation` do not propagate to the caller.
- All existing tests pass; ruff and black are clean.
- All listed harness contract tests pass.

**Dependencies:** T-122

---

### T-124: Wire Trace ID Propagation Through Stage Manager

**Description:**
Add an optional `trace_id: str | None = None` keyword parameter to `StageManager.generate()`, `.refine()`, and `.regenerate()`. Generate the `trace_id` (a `uuid4()` string) at the start of each request inside `routers/stage.py`. Pass it through to the stage manager. When a `trace_id` is present, the stage manager wraps the adapter returned by `get_llm()` with `InstrumentedAdapter` before calling `stream()` or `complete()`. When `trace_id` is `None`, behaviour is unchanged.

**Severity:** Critical — this is how Langfuse traces get associated with the right adapter calls.

**Inputs:**
- `backend/services/pipeline/stage_manager.py` — `generate`, `refine`, `regenerate`
- `backend/routers/stage.py` — `_stream_stage()` and any helper that currently calls `stage_manager.generate/refine/regenerate`
- `backend/services/llm/instrumented_adapter.py` (from T-123)
- `harness/tests/backend/test_langfuse_contract.py` — `test_stage_manager_generate_accepts_trace_id`, `test_stage_manager_refine_accepts_trace_id`

**Outputs:**
- Updated `StageManager.generate(self, stage_id, user, db, *, trace_id: str | None = None)`
- Updated `StageManager.refine(self, stage_id, request, user, db, *, trace_id: str | None = None)`
- Updated `StageManager.regenerate(...)` (if a separate method exists; otherwise the same generate path)
- `routers/stage.py` generates `trace_id = str(uuid4())` at the top of each handler and passes it to the manager
- Existing test suite passes unchanged because `trace_id` defaults to `None`

**Steps:**
1. In `backend/services/pipeline/stage_manager.py`:
   - Add `trace_id: str | None = None` as a keyword-only parameter (after `db`) to `generate`, `refine`, and any `regenerate` method.
   - Inside `generate()`, after `adapter = get_llm(workspace.provider, workspace.model)`, add:
     ```python
     if trace_id:
         from services.llm.instrumented_adapter import InstrumentedAdapter
         adapter = InstrumentedAdapter(
             adapter,
             span_id=None,  # populated by T-125
             provider=workspace.provider,
             model=workspace.model,
             stage_type=stage.type,
             action="generate",
         )
     ```
   - Apply the same pattern in `refine` (action="refine") and `regenerate` (action="regenerate").
2. In `backend/routers/stage.py`:
   - At the top of the `generate_stage`, `regenerate_stage`, and `refine_stage` handlers (or the shared `_stream_stage` helper), generate `trace_id = str(uuid4())`.
   - Pass `trace_id=trace_id` to the corresponding `stage_manager` call.
3. Run `uv run pytest tests/ -q` — all 172+ existing tests must pass unchanged because `trace_id` is optional.
4. Run `uv run ruff check . && uv run black --check .`.
5. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "trace_id" -q`.

**Acceptance Criteria:**
- `inspect.signature(StageManager.generate).parameters` includes `trace_id` with default `None`.
- `inspect.signature(StageManager.refine).parameters` includes `trace_id` with default `None`.
- All 172+ existing tests pass without modification (because `trace_id` is optional).
- When called with `trace_id=None` (the existing call sites in tests), the wrapped `InstrumentedAdapter` is **not** instantiated — verified by mocking `InstrumentedAdapter` and asserting it was not called.
- Harness tests `test_stage_manager_generate_accepts_trace_id` and `test_stage_manager_refine_accepts_trace_id` pass.

**Dependencies:** T-123

---

### T-125: Create Langfuse Traces and Spans Per Stage Generation

**Description:**
Inside `StageManager.generate()`, when `trace_id` is present, call `langfuse_service.create_trace()` once at generation start with `workspace_id`, `user_id`, `stage_type`, and `action` as metadata. Then call `create_span()` for the stage and pass the resulting `span_id` into `InstrumentedAdapter` so each generation lands inside the right span. On stream completion, mark the span as ended. On stream failure, mark the span as failed. All Langfuse calls must be exception-swallowing — a Langfuse failure cannot break the streaming flow.

**Severity:** Critical — completes the trace hierarchy described in Architecture §8a.

**Inputs:**
- `backend/services/pipeline/stage_manager.py` — `generate`, `refine`, `regenerate`
- `backend/services/langfuse_service.py` (from T-122)
- `backend/services/llm/instrumented_adapter.py` (from T-123)
- `harness/tests/backend/test_langfuse_contract.py` — `test_stage_manager_creates_langfuse_trace_when_trace_id_present`

**Outputs:**
- `StageManager.generate()` calls `create_trace()` and `create_span()` when `trace_id` is present
- Span ID is forwarded into `InstrumentedAdapter`
- Span end / failure mark on completion / error
- Updated unit tests in `backend/tests/test_stage_manager.py` covering the happy path and the Langfuse-failure path

**Steps:**
1. In `backend/services/pipeline/stage_manager.py`:
   - Import `langfuse_service` (a top-level module import is fine because the no-op path is free).
   - At the top of `generate()` after the dependency assertion and credit deduction, when `trace_id` is present:
     ```python
     await langfuse_service.get_langfuse_client().create_trace(
         name=f"workspace.{workspace.id}",
         metadata={
             "trace_id": trace_id,
             "workspace_id": str(workspace.id),
             "user_id": str(user.id),
             "stage_type": stage.type,
             "action": "generate",
         },
     )
     span_id = await langfuse_service.get_langfuse_client().create_span(
         trace_id=trace_id,
         name=f"stage.{stage.type}.generate",
         metadata={"workspace_id": str(workspace.id)},
     )
     ```
   - Pass `span_id` into `InstrumentedAdapter(...)`.
   - On generation success, the LangfuseClient SDK call (e.g. `span.end()`) is best wrapped inside the LangfuseClient itself; the manager just calls a fire-and-forget `langfuse_service.get_langfuse_client().end_span(span_id)` if implemented, or relies on the SDK's auto-end.
   - On exception inside the streaming block, a similar `mark_span_failed(span_id, exc)` call (best-effort).
2. Apply the same pattern to `refine` and `regenerate`.
3. Add a unit test in `backend/tests/test_stage_manager.py`:
   - Patch `langfuse_service.get_langfuse_client` to return a `MagicMock` whose `create_trace` and `create_span` are `AsyncMock`s.
   - Call `stage_manager.generate(..., trace_id="t-1")` against the existing fake DB/redis fixtures.
   - Assert `create_trace.assert_awaited_once()` with the correct metadata.
   - Assert `create_span.assert_awaited_once()`.
   - Add a separate test where `create_trace` raises `RuntimeError("langfuse down")` — the generation must still complete successfully (the Langfuse error is swallowed inside `LangfuseClient`).
4. Run `uv run pytest tests/test_stage_manager.py -q`.
5. Run `uv run pytest tests/ -q` — all existing tests pass.
6. Run `uv run ruff check . && uv run black --check .`.
7. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "creates_langfuse_trace" -q`.

**Acceptance Criteria:**
- When `trace_id` is non-`None`, `create_trace` is called exactly once with `workspace_id`, `user_id`, `stage_type`, and `action` in metadata.
- When `trace_id` is non-`None`, `create_span` is called exactly once for the stage.
- A simulated Langfuse failure (e.g. `create_trace` raises) does **not** abort the stream — the generation still completes and content is persisted.
- All existing tests pass; ruff and black are clean.
- Harness test `test_stage_manager_creates_langfuse_trace_when_trace_id_present` passes.

**Dependencies:** T-124

---

### T-126: Register Prompt Templates with Langfuse

**Description:**
Add a runtime prompt-loader pattern that consults Langfuse on first use, caches the result in process memory for `LANGFUSE_PROMPT_CACHE_TTL` seconds, and falls back **silently** to the local `SYSTEM_PROMPT` constant when Langfuse is unconfigured, returns a non-200, or returns `None`. The fallback is invisible to callers — they always receive a string. Build a small loader in `prompts/base.py` and use it from each stage's prompt module.

**Severity:** Medium — enables the prompt-versioning story but the local fallback ensures the system works without it.

**Inputs:**
- `backend/prompts/base.py`, `prompts/spec.py`, `prompts/plan.py`, `prompts/harness.py`, `prompts/tasks.py`
- `backend/services/langfuse_service.py` (from T-122)
- `backend/config.py` — `langfuse_prompt_cache_ttl`
- `harness/tests/backend/test_langfuse_contract.py` — `test_prompt_builders_use_langfuse_with_local_fallback`, `test_prompt_fetch_falls_back_silently_on_langfuse_error`

**Outputs:**
- `prompts/base.py` exports `async def load_prompt(name: str, fallback: str) -> str` with TTL cache
- Each `prompts/{stage}.py` keeps `SYSTEM_PROMPT = "..."` as the local fallback **and** exposes `async def get_system_prompt() -> str` that returns `await load_prompt("specforge.{stage}.system", SYSTEM_PROMPT)`
- Callers (`prompts/__init__.py`, `prompt_builder.py`, etc.) updated to use `get_system_prompt()` where appropriate; otherwise `SYSTEM_PROMPT` continues to work
- Unit tests covering both the cache-hit path and the Langfuse-unavailable path

**Steps:**
1. In `backend/prompts/base.py`:
   - Add a module-level `_PROMPT_CACHE: dict[str, tuple[float, str]] = {}` for in-memory TTL caching.
   - Define:
     ```python
     async def load_prompt(name: str, fallback: str) -> str:
         now = time.time()
         cached = _PROMPT_CACHE.get(name)
         if cached and now - cached[0] < settings.langfuse_prompt_cache_ttl:
             return cached[1]
         remote = await get_langfuse_client().get_prompt(name)
         value = remote if isinstance(remote, str) and remote else fallback
         _PROMPT_CACHE[name] = (now, value)
         return value
     ```
2. In each `backend/prompts/{stage}.py`:
   - Keep the existing `SYSTEM_PROMPT = "..."` constant (this is the canonical fallback).
   - Add `async def get_system_prompt() -> str: return await load_prompt(f"specforge.{stage}.system", SYSTEM_PROMPT)`.
3. In `backend/services/pipeline/prompt_builder.py` (or wherever the system prompt is composed), use the async loader. If the call site is currently sync, switch it to await the loader; the build_prompt call is already async.
4. Add unit tests in `backend/tests/test_prompts.py`:
   - With Langfuse unconfigured, `get_system_prompt()` returns the local `SYSTEM_PROMPT`.
   - With Langfuse configured but `get_prompt` returning `None`, the local fallback is used.
   - With Langfuse configured and `get_prompt` returning `"REMOTE"`, the loader returns `"REMOTE"`.
   - The cache is honoured (a second call within TTL does not invoke `get_prompt` again).
5. Run `uv run pytest tests/test_prompts.py -q`.
6. Run `uv run pytest tests/ -q` — all 172+ existing tests still pass.
7. Run `uv run ruff check . && uv run black --check .`.
8. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "prompt" -q`.

**Acceptance Criteria:**
- `prompts/base.py` defines `load_prompt(name, fallback)` with TTL caching.
- Each stage prompt module still exports `SYSTEM_PROMPT` (the fallback) and additionally exports `get_system_prompt()`.
- A simulated Langfuse 503 (raises inside `get_prompt`) results in the local fallback being returned. No exception reaches the caller.
- Cache TTL respects `settings.langfuse_prompt_cache_ttl` (default 300s).
- All existing tests pass; ruff and black are clean.
- Harness tests `test_prompt_builders_use_langfuse_with_local_fallback` and `test_prompt_fetch_falls_back_silently_on_langfuse_error` pass.

**Dependencies:** T-122

---

### T-127: Link Eval Scores Back to Langfuse Generations

**Description:**
After `online_eval.run_eval()` produces an `EvalResult`, submit `overall_score` to Langfuse via `score_generation()` so the score appears on the same generation that produced the content. The generation ID must be threaded from the `InstrumentedAdapter` (T-123) through the stage manager (T-125) into the eval call so the score lands on the correct generation. A failure inside `score_generation()` must not surface to the user — `LangfuseClient` already swallows the exception, but `online_eval.py` must also be defensive.

**Severity:** Medium — closes the loop between content and score in Langfuse.

**Inputs:**
- `backend/services/evals/online_eval.py`
- `backend/services/pipeline/stage_manager.py` (passes generation_id into eval)
- `backend/services/llm/instrumented_adapter.py` (returns generation_id from create_generation)
- `backend/services/langfuse_service.py` (from T-122)
- `harness/tests/backend/test_langfuse_contract.py` — `test_online_eval_links_score_to_generation`, `test_online_eval_score_failure_does_not_surface_to_user`

**Outputs:**
- Updated `run_eval` and `run_eval_background` accepting an optional `content_generation_id: str | None = None`
- After `EvalResult` is computed and committed, `await langfuse_service.get_langfuse_client().score_generation(generation_id=content_generation_id, name="overall", value=overall_score)` is called when both are present
- Updated `stage_manager.generate()` captures the generation_id returned by `InstrumentedAdapter` and passes it into the background eval task
- `redact_sensitive_data` is applied to anything submitted (already done inside `LangfuseClient`)

**Steps:**
1. In `backend/services/llm/instrumented_adapter.py`, expose the generation_id that `create_generation()` returns. Cache the most recent value on the wrapper instance: `self.last_generation_id: str | None = None`. Set it after each `create_generation` call.
2. In `backend/services/pipeline/stage_manager.py`, after the streaming block completes, capture `content_generation_id = adapter.last_generation_id if isinstance(adapter, InstrumentedAdapter) else None` and pass it through `run_eval_background(..., content_generation_id=content_generation_id)`.
3. In `backend/services/evals/online_eval.py`:
   - Add `content_generation_id: str | None = None` to `run_eval` and `run_eval_background`.
   - After the EvalResult is committed and the row has its `overall_score`, call:
     ```python
     if content_generation_id and eval_result.overall_score is not None:
         await get_langfuse_client().score_generation(
             generation_id=content_generation_id,
             name="overall",
             value=float(eval_result.overall_score),
         )
     ```
   - The LangfuseClient already swallows exceptions; do not add an extra try/except (single-source-of-truth principle).
4. Add unit tests in `backend/tests/test_online_eval.py`:
   - Patch the LangfuseClient. Call `run_eval(..., content_generation_id="g-123")` with a successful judge response. Assert `score_generation.assert_awaited_once()` with value matching `overall_score`.
   - With `content_generation_id=None`, `score_generation` is **not** called.
   - With `score_generation` raising, the EvalResult is still returned to the caller.
5. Run `uv run pytest tests/test_online_eval.py tests/test_stage_manager.py -q`.
6. Run `uv run pytest tests/ -q` — all 172+ existing tests pass.
7. Run `uv run ruff check . && uv run black --check .`.
8. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "eval or score" -q`.

**Acceptance Criteria:**
- `online_eval.run_eval()` and `run_eval_background()` accept `content_generation_id: str | None = None`.
- When `content_generation_id` is present and the judge produced an `overall_score`, `score_generation` is called exactly once with `name="overall"` and `value=overall_score`.
- When `content_generation_id` is `None`, `score_generation` is not called.
- A failure inside `score_generation` does not prevent the EvalResult from being returned or persisted.
- All existing tests pass; ruff and black are clean.
- Harness tests `test_online_eval_links_score_to_generation` and `test_online_eval_score_failure_does_not_surface_to_user` pass.

**Dependencies:** T-123, T-125

---

### T-128: Implement Automatic Dataset Collection

**Description:**
After `online_eval.py` scores a generation, fire-and-forget add it to a Langfuse dataset based on score thresholds: `>= 85` → `high_quality_generations`, `< 60` → `low_quality_generations`. Generations in the 60–84 range are not collected. The dataset write is a background `asyncio.create_task` with the same `_log_eval_error`-style done-callback used elsewhere in `stage_manager.py`. It must never block the user-facing flow.

**Severity:** Low — quality-of-life enhancement for offline eval improvement.

**Inputs:**
- `backend/services/evals/online_eval.py`
- `backend/services/langfuse_service.py` (from T-122)
- `harness/tests/backend/test_langfuse_contract.py` — `test_dataset_call_only_at_correct_thresholds`, `test_dataset_call_is_fire_and_forget`

**Outputs:**
- Updated `run_eval` (or `run_eval_background`) calls `add_to_dataset` only for outlier scores
- Background task with done-callback that logs failures via structlog at `logger.error`

**Steps:**
1. In `backend/services/evals/online_eval.py`, after the EvalResult commit and the score_generation call (T-127):
   ```python
   if eval_result.overall_score is not None:
       if eval_result.overall_score >= 85:
           dataset = "high_quality_generations"
       elif eval_result.overall_score < 60:
           dataset = "low_quality_generations"
       else:
           dataset = None
       if dataset:
           item = {
               "generation_id": content_generation_id,
               "stage_type": stage_type,
               "score": eval_result.overall_score,
               "content": content,
           }
           task = asyncio.create_task(
               get_langfuse_client().add_to_dataset(dataset, item)
           )
           task.add_done_callback(_log_dataset_error)
   ```
   Define `_log_dataset_error` matching the existing `_log_eval_error` pattern in `stage_manager.py`.
2. Add unit tests in `backend/tests/test_online_eval.py`:
   - Score 90 → `add_to_dataset` called with `"high_quality_generations"`.
   - Score 50 → `add_to_dataset` called with `"low_quality_generations"`.
   - Score 70 → `add_to_dataset` is **not** called.
   - Verify the call is wrapped in `asyncio.create_task` (use `inspect.getsource` or a structural check).
3. Run `uv run pytest tests/test_online_eval.py -q`.
4. Run `uv run pytest tests/ -q` — all 172+ existing tests pass.
5. Run `uv run ruff check . && uv run black --check .`.
6. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "dataset" -q`.

**Acceptance Criteria:**
- `add_to_dataset` is called exactly when `overall_score >= 85` or `overall_score < 60`. Never for 60–84 inclusive.
- The dataset write happens via `asyncio.create_task` and never awaits in the eval flow.
- A failure inside the dataset task is captured by `_log_dataset_error` and logged at ERROR level.
- All existing tests pass; ruff and black are clean.
- Harness tests `test_dataset_call_only_at_correct_thresholds` and `test_dataset_call_is_fire_and_forget` pass.

**Dependencies:** T-127

---

### T-129: Add Langfuse to Docker Compose Under Optional Profile

**Description:**
Add a `langfuse` service and its required `langfuse-db` PostgreSQL service to `docker-compose.yml`, both gated by a `langfuse` Compose profile so they do **not** start by default. Document `docker compose --profile langfuse up` in the README. The default `docker compose up` invocation must continue to start exactly the same containers it does today.

**Severity:** Low — operational convenience for self-hosted local dev.

**Inputs:**
- `docker-compose.yml`
- `README.md`
- `harness/tests/backend/test_langfuse_contract.py` — `test_docker_compose_langfuse_is_under_optional_profile`

**Outputs:**
- New `langfuse` and `langfuse-db` services in `docker-compose.yml` with `profiles: ["langfuse"]`
- README updated with a `## Optional: Langfuse Self-Hosted Observability` subsection

**Steps:**
1. Append to `docker-compose.yml`:
   ```yaml
   langfuse:
     image: langfuse/langfuse:latest
     profiles: ["langfuse"]
     ports:
       - "127.0.0.1:3000:3000"
     environment:
       DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
       NEXTAUTH_SECRET: dev-secret-change-me
       SALT: dev-salt-change-me
       NEXTAUTH_URL: http://localhost:3000
     depends_on:
       langfuse-db:
         condition: service_healthy

   langfuse-db:
     image: postgres:16-alpine
     profiles: ["langfuse"]
     environment:
       POSTGRES_USER: langfuse
       POSTGRES_PASSWORD: langfuse
       POSTGRES_DB: langfuse
     volumes:
       - langfuse_data:/var/lib/postgresql/data
     healthcheck:
       test: ["CMD-SHELL", "pg_isready -U langfuse -d langfuse"]
       interval: 5s
       timeout: 5s
       retries: 5
   ```
   Also add `langfuse_data:` to the top-level `volumes:` block.
2. In `README.md`, add a section under **Local Development With Docker**:
   ```markdown
   ### Optional: Langfuse Self-Hosted Observability

   To run Langfuse locally and capture LLM traces from your dev workspace:

       docker compose --profile langfuse up

   Then set in `backend/.env`:

       LANGFUSE_HOST=http://localhost:3000
       LANGFUSE_SECRET_KEY=...   # from Langfuse UI after first signup
       LANGFUSE_PUBLIC_KEY=...

   Without these set, the application runs identically with no Langfuse integration.
   ```
3. Verify default behaviour: `docker compose config --services` must NOT list `langfuse` or `langfuse-db`. `docker compose --profile langfuse config --services` must list them.
4. Run `docker compose up -d db redis` (default) and confirm only db and redis (and api/frontend) start, no Langfuse containers.
5. Run harness: `uv run pytest ../harness/tests/backend/test_langfuse_contract.py -k "compose" -q`.

**Acceptance Criteria:**
- `docker compose config --services` (no profile) does not include `langfuse` or `langfuse-db`.
- `docker compose --profile langfuse config --services` includes both.
- `docker compose up` (default) starts the same containers as today.
- README documents the opt-in command.
- Harness test `test_docker_compose_langfuse_is_under_optional_profile` passes.

**Dependencies:** T-121

---

### T-130: Update CI Pipeline for Langfuse

**Description:**
Update `.github/workflows/ci.yml` so the backend job installs `langfuse` (covered by T-121's `pyproject.toml` change + `uv sync --frozen --all-groups`) and runs `harness/tests/backend/test_langfuse_contract.py` with `LANGFUSE_SECRET_KEY` **unset** to enforce the no-op contract. All 172+ existing unit tests and 26+ harness CI tests must continue to pass.

**Severity:** High — without CI enforcement the no-op invariant can silently regress.

**Inputs:**
- `.github/workflows/ci.yml`
- `harness/tests/backend/test_langfuse_contract.py`
- `harness/tests/backend/test_langfuse_contract.py` — `test_ci_runs_langfuse_contract_tests`

**Outputs:**
- Updated `.github/workflows/ci.yml` with `test_langfuse_contract.py` added to the security harness step (or a new "LLM observability harness" step)
- No `LANGFUSE_SECRET_KEY` env var is exported in CI (the no-op path must be the one verified in CI)

**Steps:**
1. In `.github/workflows/ci.yml`, locate the `Security harness contracts` step in the `backend` job. Append `../harness/tests/backend/test_langfuse_contract.py` to its `pytest` command. Do NOT add `LANGFUSE_SECRET_KEY` to the env block — the contract tests deliberately exercise the unconfigured no-op path.
2. Confirm `uv sync --frozen --all-groups` (already in the workflow) installs `langfuse` because T-121 added it to `pyproject.toml`.
3. Locally, run the exact CI command:
   ```
   cd backend && uv run pytest ../harness/tests/backend/test_security_audit_contract.py ../harness/tests/backend/test_second_pass_security_contract.py ../harness/tests/backend/test_final_hardening_contract.py ../harness/tests/backend/test_production_readiness_contract.py ../harness/tests/backend/test_langfuse_contract.py -q
   ```
   All must pass.
4. Locally, run `uv run pytest tests/ --cov=services --cov-fail-under=80 -q`. Coverage must remain ≥80%.
5. Push the change on a branch and verify the GitHub Actions run is green.

**Acceptance Criteria:**
- `.github/workflows/ci.yml` references `test_langfuse_contract.py` in the security harness step.
- The CI workflow does not export `LANGFUSE_SECRET_KEY`.
- All 172+ unit tests still pass under CI.
- All harness CI tests (security_audit + second_pass + final_hardening + production_readiness + langfuse) pass under CI.
- Backend coverage remains ≥80%.
- Harness test `test_ci_runs_langfuse_contract_tests` passes.

**Dependencies:** T-122, T-123, T-124, T-125, T-126, T-127, T-128

---

### T-131: End-to-End Smoke Test and Documentation

**Description:**
Update the manual smoke-test checklist with Langfuse verification steps. Update the README observability section. Update HANDOFF.md to document the Langfuse integration, the no-op design decision, the dataset-collection thresholds, and the explicit invariant that no user-facing feature depends on Langfuse availability.

**Severity:** Operational — closes out Phase 11 with reproducible verification and documented design decisions.

**Inputs:**
- `docs/SMOKE_TEST_CHECKLIST.md`
- `README.md`
- `HANDOFF.md`

**Outputs:**
- New section in `docs/SMOKE_TEST_CHECKLIST.md`: "Langfuse Integration"
- Updated README Observability section
- New addendum in HANDOFF.md describing Phase 11

**Steps:**
1. In `docs/SMOKE_TEST_CHECKLIST.md`, append a new section:
   ```markdown
   ## Langfuse Integration (optional)

   With Langfuse configured (`docker compose --profile langfuse up` and the
   four LANGFUSE_* env vars set in backend/.env):

   - [ ] Sign in and create a workspace.
   - [ ] Generate a SPEC stage. Confirm streaming works normally.
   - [ ] Open Langfuse UI at http://localhost:3000.
   - [ ] Confirm a trace appears with the workspace_id and user_id metadata.
   - [ ] Confirm one generation is recorded inside the trace with provider,
         model, full system prompt, full user prompt, and accumulated output.
   - [ ] Wait for the eval to complete. Confirm the overall score is attached
         to the same generation in the Langfuse UI.
   - [ ] Trigger a generation that scores >=85 or <60. Confirm a dataset item
         appears in the corresponding Langfuse dataset.

   With Langfuse unconfigured (LANGFUSE_SECRET_KEY blank):

   - [ ] Sign in, create a workspace, generate a SPEC stage.
   - [ ] Confirm the application behaves identically — same latency, same
         streaming, same eval scoring, same credit accounting.
   - [ ] Confirm zero requests to any Langfuse host appear in `tcpdump`/proxy
         logs during the generation.
   ```
2. In `README.md`, update the **Observability** section to add a paragraph:
   ```markdown
   Optional LLM observability via Langfuse:

   - Set `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST` to
     enable per-generation trace, prompt-version, and eval-score capture.
   - Run a self-hosted Langfuse locally with `docker compose --profile langfuse up`.
   - Without these variables set, the application runs identically with zero
     Langfuse traffic. No user-facing feature depends on Langfuse availability.
   ```
3. In `HANDOFF.md`, append a new section after the existing post-audit addendum:
   ```markdown
   ## Phase 11 — Langfuse LLM Observability

   **Date:** 2026-05-07 | **CI status:** ✅ Green (existing 172 unit tests, 26+
   harness CI tests, plus new test_langfuse_contract.py all pass)

   Phase 11 added an **optional** LLM observability layer using Langfuse,
   alongside the existing Grafana Cloud + Sentry stack which remains unchanged.

   Key design decisions:

   1. The integration is gated by `LANGFUSE_SECRET_KEY`. With it unset, the
      application behaves identically to the pre-Phase-11 baseline.
   2. The no-op branch lives in exactly one place: `services/langfuse_service.py`.
   3. `BaseLLMAdapter` was not modified. Instrumentation is composed via
      `InstrumentedAdapter` above the adapters, not inside them.
   4. Every Langfuse call is exception-swallowing. A Langfuse outage cannot
      break stage generation, refine, eval, or credit accounting.
   5. Sensitive data redaction reuses `services.observability.redact_sensitive_data`.
      No new regex patterns were introduced.
   6. Streams are accumulated and recorded once per call, never per token.
   7. Dataset collection thresholds: scores >=85 go to `high_quality_generations`,
      scores <60 go to `low_quality_generations`. Mid-quality (60-84) is not
      collected.
   8. CI runs the contract tests with LANGFUSE_SECRET_KEY unset to enforce the
      no-op invariant.
   ```
4. Manual verification: walk through both checklists end-to-end on a clean checkout.

**Acceptance Criteria:**
- `docs/SMOKE_TEST_CHECKLIST.md` includes the Langfuse section.
- `README.md` Observability section documents Langfuse as optional.
- `HANDOFF.md` includes the Phase 11 addendum capturing the eight key design decisions.
- A reviewer can read HANDOFF.md and understand: (a) Langfuse is optional; (b) the no-op design; (c) the dataset thresholds; (d) the invariant that no user-facing feature depends on Langfuse.

**Dependencies:** T-130

---

---

## Phase 12 — Provider-Agnostic LLM API Cost Optimization

> Source: `Plan v1.md` §16 and `harness/tests/backend/test_phase12_llm_cost_contract.py`.
>
> Objective: reduce average LLM API cost per completed workspace by at least 50%
> without weakening ASDD artifact quality. OpenAI is the current test provider,
> but the implementation must be provider agnostic across OpenAI, Anthropic, and
> Google. Provider-specific pricing, token usage, batch behavior, prompt caching,
> and model names belong in LLM registry/adapter layers — never in pipeline logic.

---

### T-132: Add Provider Capability and Cost Registry

**Description:**
Create a provider-agnostic capability and cost registry for OpenAI, Anthropic, and Google. The registry maps concrete provider models to provider-neutral tiers (`strong`, `mid`, `mini`, `small`, plus optional `judge` / `embedding`) and declares the cost/capability fields needed by routing, telemetry, cache, and dashboards.

**Severity:** Critical — every later cost optimization depends on a single source of truth for provider capabilities and pricing.

**Inputs:**
- `Plan v1.md` §16.4
- `backend/services/llm/provider_config.py`
- `harness/tests/backend/test_phase12_llm_cost_contract.py` — `test_provider_capability_cost_registry_exists_for_all_llm_providers`

**Outputs:**
- New `backend/services/llm/cost_registry.py`
- Optional update to `backend/services/llm/provider_config.py` to share model IDs/display names with the cost registry
- Unit tests for registry shape, provider coverage, and cost validation

**Steps:**
1. Create `backend/services/llm/cost_registry.py`.
2. Define typed constants:
   - `MODEL_TIERS = {"strong", "mid", "mini", "small", "judge", "embedding"}`
   - `PROVIDER_CAPABILITY_REGISTRY`
3. For each provider (`openai`, `anthropic`, `google`), define:
   - `supports_streaming`
   - `supports_prompt_cache_accounting`
   - `supports_batch`
   - `supports_usage_tokens`
   - `models`
4. For each model entry, define:
   - `tier`
   - `input_cost_per_million`
   - `cached_input_cost_per_million` (`None` if unsupported/unknown)
   - `output_cost_per_million`
   - `max_context_tokens`
   - `default_max_output_tokens`
   - `recommended_operations`
5. Do not encode provider secrets or environment-specific availability in this registry. It is static capability/cost metadata.
6. Add helper functions:
   - `get_provider_capabilities(provider: str) -> dict`
   - `get_model_cost(provider: str, model: str) -> dict`
   - `models_for_tier(provider: str, tier: str) -> list[str]`
   - `model_tier(provider: str, model: str) -> str`
7. Make registry validation fail at import time if:
   - a required provider is missing,
   - a model is missing cost fields,
   - a tier is invalid,
   - or a recommended operation is malformed.
8. Add unit tests under `backend/tests/test_llm_cost_registry.py`.
9. Run the narrow harness test:
   ```
   cd backend && uv run pytest ../harness/tests/backend/test_phase12_llm_cost_contract.py -k "registry" -q
   ```

**Acceptance Criteria:**
- `services.llm.cost_registry.PROVIDER_CAPABILITY_REGISTRY` exists.
- OpenAI, Anthropic, and Google are all represented.
- At least one model exists for every required tier: `strong`, `mid`, `mini`, `small`.
- Every model entry has all required cost-routing fields.
- Harness test `test_provider_capability_cost_registry_exists_for_all_llm_providers` passes.

**Dependencies:** T-131

---

### T-133: Implement Provider-Neutral Routing Policy

**Description:**
Create a routing layer that resolves an operation/tier request into a concrete provider/model using the registry from T-132. The routing policy must prefer the workspace's selected provider, require explicit permission for cross-provider fallback, and keep concrete model names out of Stage Manager logic.

**Severity:** Critical — this is the core mechanism that lets SpecForge optimize cost without coupling ASDD stages to OpenAI/Anthropic/Google details.

**Inputs:**
- `Plan v1.md` §16.3, §16.5, §16.15
- `backend/services/llm/cost_registry.py` from T-132
- `backend/services/pipeline/stage_manager.py`
- `harness/tests/backend/test_phase12_llm_cost_contract.py` — `test_llm_routing_policy_requires_explicit_cross_provider_fallback`, `test_stage_logic_uses_provider_neutral_routing_not_model_names`

**Outputs:**
- New `backend/services/llm/routing.py`
- Updated `backend/services/pipeline/stage_manager.py`
- Unit tests for routing behavior and fallback safety

**Steps:**
1. Create `backend/services/llm/routing.py`.
2. Define a dataclass:
   ```python
   @dataclass(frozen=True)
   class LLMRoute:
       provider: str
       model: str
       model_tier: str
       operation: str
       latency_class: str
       cross_provider_fallback: bool
       reason: str
   ```
3. Implement:
   ```python
   def resolve_llm_route(
       *,
       operation: str,
       preferred_provider: str,
       requested_tier: str,
       fallback_tier: str | None = None,
       latency_class: str,
       allow_cross_provider: bool = False,
       preferred_model: str | None = None,
   ) -> LLMRoute:
       ...
   ```
4. Routing rules:
   - If `preferred_model` is provided and supports the operation/tier, use it.
   - Otherwise choose the cheapest model in the preferred provider that supports the operation and requested tier.
   - If no model matches and `fallback_tier` is provided, try the fallback tier within the same provider.
   - If still no match and `allow_cross_provider=False`, raise a routing error.
   - Cross-provider fallback may only happen when `allow_cross_provider=True`; the returned route must set `cross_provider_fallback=True`.
5. Add `LLMRoutingError` with a user-safe message and internal details for logging.
6. Update Stage Manager generation/refine/eval entry points to call `resolve_llm_route()` before `get_llm()`.
7. Stage Manager must pass `route.provider` and `route.model` into `get_llm()`. It must not contain hard-coded fragments like `gpt-`, `claude-`, `gemini-`, or `o1-`.
8. Operation mapping:
   - `spec.generate` → strong
   - `plan.generate` → strong or mid
   - `harness.generate` → mini or mid
   - `tasks.generate` → mini
   - `refine.focused` → mini or mid
   - `refine.section` → mid
   - `regenerate.full` → strong
   - `eval.score` → judge/small
   - `summary.create` → small/mini
9. Add unit tests for:
   - same-provider preferred route,
   - fallback tier in same provider,
   - cross-provider fallback rejected by default,
   - cross-provider fallback explicit and visible,
   - invalid provider/model rejected.
10. Run:
   ```
   cd backend && uv run pytest tests/test_llm_routing.py ../harness/tests/backend/test_phase12_llm_cost_contract.py -k "routing or stage_logic" -q
   ```

**Acceptance Criteria:**
- `services.llm.routing.resolve_llm_route()` exists with required parameters.
- `allow_cross_provider` exists and defaults to `False`.
- Stage Manager delegates provider/model selection to routing.
- Stage Manager contains no hard-coded provider model names.
- Harness tests `test_llm_routing_policy_requires_explicit_cross_provider_fallback` and `test_stage_logic_uses_provider_neutral_routing_not_model_names` pass.

**Dependencies:** T-132

---

### T-134: Add Provider-Normalized Usage and Cost Estimation

**Description:**
Implement provider-normalized usage accounting so all LLM calls can produce comparable cost events regardless of whether the provider reports exact token usage, partial usage, cached-token usage, or no usage for streaming calls.

**Severity:** Critical — without normalized cost telemetry, there is no way to prove cost optimization works.

**Inputs:**
- `Plan v1.md` §16.13
- `backend/services/llm/cost_registry.py`
- Existing provider adapters
- `harness/schemas/llm-cost-event.schema.json`
- `harness/tests/backend/test_phase12_llm_cost_contract.py` — `test_adapters_expose_or_normalize_usage_without_changing_base_interface`

**Outputs:**
- New `backend/services/llm/usage.py`
- Unit tests for usage normalization and cost estimation
- No change to `BaseLLMAdapter.stream()` / `.complete()` signatures

**Steps:**
1. Create `backend/services/llm/usage.py`.
2. Define:
   ```python
   @dataclass(frozen=True)
   class NormalizedUsage:
       input_tokens: int | None
       cached_input_tokens: int | None
       output_tokens: int | None
       provider_usage_raw: dict | None
       usage_estimation_method: Literal["provider_reported", "tokenizer_estimated", "unknown"]
   ```
3. Implement:
   - `normalize_provider_usage(provider: str, raw_usage: Any) -> NormalizedUsage`
   - `estimate_tokens(provider: str, model: str, text: str) -> int | None`
   - `estimate_cost_usd(provider: str, model: str, usage: NormalizedUsage) -> Decimal | None`
4. Provider usage rules:
   - Use provider-reported input/output/cached tokens when available.
   - For streaming calls where usage is unavailable, estimate output tokens from accumulated output and mark `usage_estimation_method="tokenizer_estimated"`.
   - If no reliable tokenizer/usage is available, return `None` token fields and `usage_estimation_method="unknown"` rather than pretending precision.
5. Cost rules:
   - Use `input_cost_per_million`, `cached_input_cost_per_million`, and `output_cost_per_million` from the registry.
   - If token usage is unknown, `estimated_cost_usd=None`.
   - Use `Decimal` internally to avoid floating point drift.
6. Keep `BaseLLMAdapter` unchanged. Any raw provider usage capture must be done in adapter internals, wrapper metadata, or a side-channel that does not change the abstract interface.
7. Add unit tests for OpenAI-shaped, Anthropic-shaped, Google-shaped, estimated, and unknown usage payloads.
8. Run:
   ```
   cd backend && uv run pytest tests/test_llm_usage.py ../harness/tests/backend/test_phase12_llm_cost_contract.py -k "usage or adapters" -q
   ```

**Acceptance Criteria:**
- `services.llm.usage` exports `normalize_provider_usage`, `estimate_tokens`, and `estimate_cost_usd`.
- Usage events can distinguish provider-reported, tokenizer-estimated, and unknown values.
- `BaseLLMAdapter` signatures remain exactly `(system, user, max_tokens)`.
- Harness test `test_adapters_expose_or_normalize_usage_without_changing_base_interface` passes.

**Dependencies:** T-132

---

### T-135: Add Generation Cache Key Builder and Cache Service

**Description:**
Add a provider-safe cache key builder for repeatable LLM generation inputs. The key must include prompt version, stage type, operation, concrete provider/model, provider-neutral model tier, problem statement hash, upstream artifact hashes, user instruction hash, and output contract version.

**Severity:** High — prevents repeated local/dev and duplicate production generations from wasting provider spend while avoiding stale or cross-provider replay.

**Inputs:**
- `Plan v1.md` §16.11
- `harness/tests/backend/test_phase12_llm_cost_contract.py` — `test_generation_cache_key_includes_provider_model_tier_and_prompt_version`

**Outputs:**
- New `backend/services/llm/cost_cache.py`
- Optional Redis-backed cache methods for completed outputs
- Unit tests for key isolation and invalidation

**Steps:**
1. Create `backend/services/llm/cost_cache.py`.
2. Implement:
   ```python
   def build_generation_cache_key(
       *,
       prompt_version: str,
       stage_type: str,
       operation: str,
       provider: str,
       model: str,
       model_tier: str,
       problem_statement_hash: str,
       upstream_artifact_hashes: Mapping[str, str],
       user_instruction_hash: str,
       output_contract_version: str,
   ) -> str:
       ...
   ```
3. Canonicalize inputs:
   - sort `upstream_artifact_hashes` keys,
   - JSON encode with stable separators,
   - hash the canonical payload using SHA-256,
   - prefix with `llmcache:v1:`.
4. Implement optional helpers:
   - `async get_cached_generation(redis, key: str) -> str | None`
   - `async set_cached_generation(redis, key: str, output: str, ttl_seconds: int) -> None`
5. Do not cache partial streaming output. Cache only after a full response completes and passes validation.
6. Add tests proving the key changes when any of these change:
   - provider,
   - model,
   - model tier,
   - prompt version,
   - upstream artifact hash,
   - instruction hash,
   - output contract version.
7. Run:
   ```
   cd backend && uv run pytest tests/test_llm_cost_cache.py ../harness/tests/backend/test_phase12_llm_cost_contract.py -k "cache_key" -q
   ```

**Acceptance Criteria:**
- `build_generation_cache_key()` exists with all required parameters.
- Cache keys are stable for identical input and different for any semantic change.
- Concrete provider/model and provider-neutral tier are both included.
- Harness test `test_generation_cache_key_includes_provider_model_tier_and_prompt_version` passes.

**Dependencies:** T-132

---

### T-136: Extend InstrumentedAdapter With Provider-Normalized Cost Metadata

**Description:**
Update `InstrumentedAdapter` so every LLM call records provider-normalized cost metadata in Langfuse and structured logs. Preserve pass-through behavior and keep provider adapters Langfuse-free. The wrapper should record usage/cost metadata even when Langfuse is disabled, via structured logs or an internal telemetry hook.

**Severity:** Critical — this makes cost visible and measurable without changing user-facing generation behavior.

**Inputs:**
- `Plan v1.md` §16.12-§16.13
- `backend/services/llm/instrumented_adapter.py`
- `backend/services/llm/usage.py` from T-134
- `backend/services/llm/routing.py` from T-133
- `harness/tests/backend/test_phase12_llm_cost_contract.py` — `test_instrumented_adapter_records_provider_normalized_cost_metadata`

**Outputs:**
- Updated `backend/services/llm/instrumented_adapter.py`
- Unit tests covering cost metadata on `stream()` and `complete()`

**Steps:**
1. Extend `InstrumentedAdapter.__init__` with optional metadata:
   - `model_tier`
   - `prompt_version`
   - `operation`
   - `cache_hit`
   - `batch`
   - `cross_provider_fallback`
2. Preserve backward compatibility for existing call sites by providing safe defaults where needed, then update Stage Manager to pass real values from `LLMRoute`.
3. During `stream()`, accumulate output as today. After stream close, estimate or normalize usage using `services.llm.usage`.
4. During `complete()`, normalize usage if raw provider usage is available; otherwise estimate from input/output text.
5. Add metadata fields to every generation record:
   - `model_tier`
   - `prompt_version`
   - `input_tokens`
   - `cached_input_tokens`
   - `output_tokens`
   - `provider_usage_raw`
   - `usage_estimation_method`
   - `estimated_cost_usd`
   - `cache_hit`
   - `batch`
   - `cross_provider_fallback`
6. Emit a structured log event `llm.cost_recorded` with the same metadata, redacting prompts/content.
7. Ensure all Langfuse and logging failures are exception-swallowing and cannot break streaming.
8. Add tests proving:
   - stream tokens are unchanged,
   - complete output is unchanged,
   - metadata includes all required cost fields,
   - a metadata/logging failure does not interrupt generation.
9. Run:
   ```
   cd backend && uv run pytest tests/test_instrumented_adapter.py ../harness/tests/backend/test_phase12_llm_cost_contract.py -k "instrumented_adapter" -q
   ```

**Acceptance Criteria:**
- InstrumentedAdapter includes all provider-normalized cost fields.
- Existing Langfuse behavior still works.
- Provider adapters still do not import Langfuse.
- Streaming pass-through remains unchanged.
- Harness test `test_instrumented_adapter_records_provider_normalized_cost_metadata` passes.

**Dependencies:** T-133, T-134

---

### T-137: Reorder Prompt Builders for Stable Cacheable Prefixes

**Description:**
Audit and enforce the prompt-builder structure so ASDD methodology, security rules, professional output rules, and stage contracts remain a stable static prefix before any dynamic workspace context. This improves provider-side prompt caching where available and keeps the product moat portable across providers.

**Severity:** High — prompt caching/reuse only works if static content is stable and separated from dynamic content.

**Inputs:**
- `Plan v1.md` §16.6
- `backend/prompts/base.py`
- `backend/prompts/spec.py`
- `backend/prompts/plan.py`
- `backend/prompts/harness.py`
- `backend/prompts/tasks.py`
- `harness/tests/backend/test_phase12_llm_cost_contract.py` — `test_prompt_builders_keep_static_moat_prefix_before_dynamic_context`

**Outputs:**
- Updated prompt modules if any dynamic interpolation exists in static system prompts
- New prompt-version constants
- Unit tests for prompt prefix stability

**Steps:**
1. Add prompt version constants in `backend/prompts/base.py`, for example:
   ```python
   ASDD_PROMPT_VERSION = "asdd-v1.7.1"
   ```
2. Confirm each stage prompt builds `SYSTEM_PROMPT` from static blocks only:
   - `ASDD_METHODOLOGY_OVERVIEW`
   - `SECURITY_AND_PRIVACY_RULES`
   - `PROFESSIONAL_OUTPUT_RULES`
   - stage-specific static contract
3. Move all workspace names, problem statements, prior stage content, user refinements, timestamps, and provider/model data into `build_user_prompt()`.
4. Ensure every dependency block uses `wrap_untrusted_content()`.
5. Add tests that call each `get_system_prompt()` twice with different dependencies and assert the system prompt is identical.
6. Add tests that dynamic content appears only in user prompts.
7. Run:
   ```
   cd backend && uv run pytest tests/test_prompt_builder.py ../harness/tests/backend/test_phase12_llm_cost_contract.py -k "prompt_builders" -q
   ```

**Acceptance Criteria:**
- Static prompt prefixes are byte-stable for the same prompt version.
- Dynamic workspace content appears only in user prompt blocks.
- Prompt version is available for telemetry.
- Harness test `test_prompt_builders_keep_static_moat_prefix_before_dynamic_context` passes.

**Dependencies:** T-126

---

### T-138: Add Finalized Stage Summaries for Context Compression

**Description:**
Create a stage-summary service that compresses finalized artifacts into structured, downstream-safe summaries. Later stages should prefer summaries and targeted excerpts over always passing full upstream artifacts, reducing provider context cost while preserving traceability.

**Severity:** High — downstream prompt bloat is one of the main cost drivers in ASDD.

**Inputs:**
- `Plan v1.md` §16.7
- `backend/services/pipeline/stage_manager.py`
- `backend/prompts/*`
- Existing stage models/version tables

**Outputs:**
- New `backend/services/pipeline/stage_summary_service.py`
- Optional DB field/table for persisted summaries, or Redis cache if summaries are deterministic and recoverable
- Tests for summary creation, invalidation, and downstream prompt usage

**Steps:**
1. Define summary schema:
   ```markdown
   ## Decisions
   ## Entities
   ## APIs
   ## Security Requirements
   ## Data Constraints
   ## Open Questions
   ## Downstream Constraints
   ```
2. Implement deterministic extraction where possible:
   - parse markdown headings,
   - collect requirement IDs,
   - collect API endpoint blocks,
   - collect security sections.
3. For content that cannot be summarized deterministically, use the routing policy with `operation="summary.create"` and tier `small` or `mini`.
4. Store summary metadata:
   - source stage id,
   - source stage version,
   - source content hash,
   - prompt version,
   - provider/model used if an LLM was needed.
5. Invalidate summaries whenever a finalized stage changes or rolls back.
6. Update downstream prompt builders to accept either:
   - full artifact,
   - summary + targeted excerpts,
   - or full artifact fallback when validation fails.
7. Add tests for:
   - summary structure,
   - summary invalidation on content hash change,
   - downstream prompt uses summary when full artifact exceeds threshold,
   - downstream prompt falls back to full content when below threshold.

**Acceptance Criteria:**
- Finalized stages can produce structured summaries.
- Summaries are invalidated by stage version/content changes.
- PLAN/HARNESS/TASKS prompt building can use summaries by default when upstream context is large.
- No requirement IDs are silently dropped from summary metadata.

**Dependencies:** T-133, T-137

---

### T-139: Add Output Budgets and Patch-Based Refine Modes

**Description:**
Implement per-operation output budgets and make refinement patch-based by default. Focused refine should send selected text plus minimal surrounding context and return replacement text only; section refine should return one section; full regenerate remains explicit and more expensive.

**Severity:** High — output tokens are a major cost driver and full-document refine is wasteful.

**Inputs:**
- `Plan v1.md` §16.8-§16.9
- `backend/services/pipeline/stage_manager.py`
- `backend/prompts/*`
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/components/workspace/*`

**Outputs:**
- Output-budget configuration per operation
- Refine mode selection in backend request handling
- UI copy/actions for focused refine vs full regenerate
- Tests for budget selection and patch-only refine output

**Steps:**
1. Define output budget config in backend, keyed by operation:
   - `spec.generate`
   - `plan.generate`
   - `harness.generate`
   - `tasks.generate`
   - `refine.focused`
   - `refine.section`
   - `regenerate.full`
   - `eval.score`
   - `summary.create`
2. Route Stage Manager calls through the operation budget instead of ad hoc `max_tokens`.
3. Extend refine request schema with `mode: "focused" | "section" | "full"` defaulting to `"focused"`.
4. Focused refine prompt:
   - include selected text,
   - include small surrounding context,
   - include relevant stage summary/dependency snippets,
   - require replacement text only.
5. Section refine prompt:
   - include the selected markdown section,
   - return the full replacement section only.
6. Full regenerate remains a separate action, not the default refine path.
7. If the user selects more than 80% of the artifact, frontend recommends full regenerate but allows deliberate focused refine.
8. Add tests for:
   - output budget lookup,
   - focused refine uses smaller budget than full regenerate,
   - focused refine does not send all upstream artifacts,
   - focused refine returns replacement only,
   - frontend displays full-regenerate recommendation on whole-document selection.

**Acceptance Criteria:**
- All LLM calls use operation-specific output budgets.
- Focused refine is the default.
- Full artifact regeneration is explicit.
- Selection >80% triggers a UI recommendation.
- Existing refine safety tests still pass.

**Dependencies:** T-133, T-138

---

### T-140: Wire Generation Cache Into Stage Operations

**Description:**
Use the cache key builder from T-135 to avoid repeated identical generation/refine/summary calls. Cache only completed, validated outputs. Do not cache partial streams. On a cache hit, replay cached content through the existing stage update path and mark telemetry with `cache_hit=True`.

**Severity:** Medium-High — especially valuable for local testing, prompt iteration, accidental double-clicks, and repeated generation attempts.

**Inputs:**
- `Plan v1.md` §16.10-§16.11
- `backend/services/llm/cost_cache.py`
- `backend/services/pipeline/stage_manager.py`
- Redis dependency

**Outputs:**
- Stage Manager cache lookup/write integration
- Cache hit telemetry
- Tests for cache hit/miss/invalidation behavior

**Steps:**
1. Before calling a provider, build a generation cache key from:
   - prompt version,
   - stage type,
   - operation,
   - provider,
   - model,
   - model tier,
   - problem statement hash,
   - upstream artifact hashes,
   - user instruction hash,
   - output contract version.
2. Check Redis for a completed cached output.
3. On cache hit:
   - skip provider call,
   - apply cached output to the stage through the same persistence/validation path,
   - emit telemetry with `cache_hit=True`,
   - do not deduct provider-cost credits if the product credit model distinguishes cached output.
4. On cache miss:
   - call provider,
   - validate output,
   - persist output,
   - then cache full completed output with TTL.
5. Do not cache failed, partial, rejected, or security-flagged outputs.
6. Include `prompt_version` and output contract version in the key to avoid stale cache after prompt changes.
7. Add tests for:
   - cache hit skips adapter call,
   - cache miss calls adapter once,
   - prompt version change misses cache,
   - provider/model/tier change misses cache,
   - partial stream failure does not write cache.

**Acceptance Criteria:**
- Identical repeat calls can hit cache safely.
- Cache keys isolate provider/model/tier/prompt/artifact changes.
- Partial or failed generations are never cached.
- Telemetry distinguishes cache hits from provider calls.

**Dependencies:** T-135, T-136, T-139

---

### T-141: Add Deterministic Pre-LLM Cost Gates

**Description:**
Consolidate all no-LLM gates before provider calls. The system must reject invalid or unnecessary work before spending tokens: invalid problem statements, prompt injection, missing dependencies, duplicate in-progress generation, invalid provider/model, zero credits, unchanged refine submissions, and stale selections.

**Severity:** High — no-call gates save cost and strengthen security.

**Inputs:**
- `Plan v1.md` §16.10
- Existing `backend/services/security/problem_statement_gate.py`
- Existing prompt guard, stage dependency checks, credit checks, refine selection checks

**Outputs:**
- Shared preflight service or clearly ordered Stage Manager preflight functions
- Tests proving provider adapters are not called when gates fail

**Steps:**
1. Create or consolidate a preflight function:
   ```python
   async def assert_llm_call_allowed(...): ...
   ```
2. Ensure this function runs before credit deduction and before provider adapter lookup wherever possible.
3. Check:
   - authentication already resolved,
   - workspace ownership,
   - problem statement valid,
   - prompt guard clean,
   - stage dependencies finalized,
   - stage not already in progress,
   - provider/model route valid,
   - credit balance sufficient,
   - refine selected text matches current content,
   - refine instruction changes something meaningful.
4. On failure, return structured error codes that frontend can render clearly.
5. Add tests using adapter mocks that assert the adapter is never called on each failure path.
6. Preserve refund behavior for failures that happen after credit deduction/provider start.

**Acceptance Criteria:**
- Invalid/duplicate/no-op requests do not call any provider.
- Existing security and problem-statement gate tests still pass.
- Refine stale-selection and unchanged-selection cases are blocked before provider spend.
- Error messages are user-safe and actionable.

**Dependencies:** T-133, T-139

---

### T-142: Add Provider Cost Dashboards, Logs, and Alerts

**Description:**
Expose normalized LLM cost metrics through structured logs and Prometheus metrics. Dashboards must answer: cost per workspace, cost per stage, cost by provider, cost by tier, cache-hit savings, output-token growth, and cost per accepted artifact.

**Severity:** High — optimization without measurement will regress.

**Inputs:**
- `Plan v1.md` §16.13, §16.18-§16.19
- `backend/services/observability.py`
- `backend/services/llm/usage.py`
- `backend/services/llm/instrumented_adapter.py`

**Outputs:**
- New Prometheus metrics for normalized LLM usage/cost
- Structured log event `llm.cost_recorded`
- README/internal docs for cost dashboards
- Tests for metric labels and no prompt-content leakage

**Steps:**
1. Add Prometheus metrics:
   - `llm_request_total{provider,model_tier,operation,stage_type,cache_hit}`
   - `llm_estimated_cost_usd_total{provider,model_tier,operation,stage_type}`
   - `llm_input_tokens_total{provider,model_tier,operation,stage_type,method}`
   - `llm_output_tokens_total{provider,model_tier,operation,stage_type,method}`
   - `llm_cached_input_tokens_total{provider,model_tier,operation,stage_type}`
   - `llm_latency_seconds_bucket{provider,model_tier,operation,stage_type}`
2. Emit structured logs with the normalized cost event fields but no prompt text, output text, API keys, bearer tokens, or PII.
3. Add cost anomaly alert suggestions:
   - P95 request cost above provider baseline,
   - output tokens above budget,
   - cache-hit ratio unexpectedly drops,
   - cross-provider fallback occurs.
4. Add tests proving:
   - metrics are emitted on provider calls,
   - cache hits are labelled,
   - prompt/output content is not logged,
   - cost fields match the normalized usage/cost service.
5. Update README Observability section with the cost metrics.

**Acceptance Criteria:**
- Cost metrics are emitted for every instrumented LLM call.
- Logs contain provider/model/tier/operation/cost fields but no prompt or output content.
- Dashboards can aggregate by provider and tier.
- Cross-provider fallback is observable.

**Dependencies:** T-136, T-140

---

### T-143: Add Golden Dataset and Quality Gates for Routing Changes

**Description:**
Build an evaluation harness that compares provider/model tiers on a golden dataset of product prompts. Cheaper routes may become defaults only when they meet quality gates for the specific operation and provider family.

**Severity:** Critical — cost reduction must not erode the prompt moat or ASDD artifact quality.

**Inputs:**
- `Plan v1.md` §16.14-§16.15
- Existing eval service
- Langfuse optional dataset support from Phase 11

**Outputs:**
- `backend/tests/fixtures/golden_prompts/*.json` or `docs/evals/golden_prompts/*.json`
- Script `scripts/run_llm_route_eval.py`
- Quality-gate config per operation/provider/tier
- Documentation for promoting cheaper routes

**Steps:**
1. Create a golden dataset with representative product prompts:
   - simple CRUD SaaS,
   - multi-tenant B2B workflow,
   - AI-heavy product,
   - regulated/security-sensitive product,
   - vague prompt that should be rejected,
   - prompt-injection attempt,
   - large upstream artifact chain.
2. For each prompt, define expected traits:
   - required sections,
   - requirement traceability,
   - security coverage,
   - API/schema specificity,
   - markdown/code fence validity,
   - max verbosity/length constraints.
3. Implement `scripts/run_llm_route_eval.py`:
   - runs selected operation/provider/tier routes,
   - records cost,
   - records latency,
   - runs deterministic validators,
   - optionally runs LLM-as-judge,
   - outputs JSON/Markdown report.
4. Add promotion rules:
   - no deterministic validator regressions,
   - average quality score no worse than baseline threshold,
   - human acceptance on sampled outputs,
   - cost reduction target met,
   - no security coverage regression.
5. Add CI-safe tests that validate the dataset and script structure without making live provider calls.
6. Document that live route promotion is manual/operator-approved, not automatic.

**Acceptance Criteria:**
- Golden dataset exists and covers all major ASDD operations.
- Eval script can run in dry-run mode without provider calls.
- Promotion rules are explicit and provider-specific.
- Cheaper provider/tier defaults cannot be promoted without quality evidence.

**Dependencies:** T-132, T-133, T-142

---

### T-144: Add Batch/Background Cost Optimization for Non-Interactive Work

**Description:**
Move eligible non-interactive LLM work behind a provider-capability-aware background/batch executor. Use provider batch discounts where available; otherwise run background work normally with the same telemetry and safety controls.

**Severity:** Medium — useful savings for evals, audits, summaries, and prompt regression runs, but must not affect interactive first-token latency.

**Inputs:**
- `Plan v1.md` §16.12
- `backend/services/llm/cost_registry.py`
- Existing eval/summary/prompt regression flows

**Outputs:**
- New `backend/services/llm/batch_executor.py`
- Background execution path for eligible operations
- Tests proving interactive operations never use batch

**Steps:**
1. Define eligible operations:
   - `eval.score`
   - `summary.create`
   - `audit.artifact_quality`
   - `prompt_regression.run`
2. Define ineligible operations:
   - `spec.generate`
   - `plan.generate`
   - `harness.generate`
   - `tasks.generate`
   - `refine.focused`
   - `refine.section`
   - `regenerate.full`
3. Implement provider capability check:
   - if `supports_batch=True`, use provider-specific batch adapter,
   - if `supports_batch=False` or provider-specific unsupported, enqueue normal background task,
   - always emit telemetry with `batch=True/False`.
4. Add dead-letter/error handling for failed background jobs.
5. Add tests proving:
   - interactive operations reject batch path,
   - eligible operations use batch only when provider supports it,
   - unsupported providers fall back to normal background execution,
   - telemetry marks batch state.

**Acceptance Criteria:**
- Batch is capability-aware, not OpenAI-specific.
- Interactive operations never go through batch.
- Background jobs remain observable and failure-tolerant.
- Cost telemetry distinguishes batch vs non-batch.

**Dependencies:** T-132, T-136, T-142

---

### T-145: Add Product UX Controls for Cost-Aware Generation

**Description:**
Add frontend affordances that expose cost-aware behavior as quality/scope choices, not raw token anxiety. Users should see focused refine, full regenerate, deep architecture pass, fast draft, and final quality pass where appropriate.

**Severity:** Medium — improves user trust and reduces accidental expensive actions.

**Inputs:**
- `Plan v1.md` §16.16
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/components/workspace/*`
- Backend refine mode and routing support from T-139

**Outputs:**
- UI controls for focused refine and full regenerate
- Optional quality/scope mode controls
- Updated credit confirmation copy
- Frontend tests for mode selection and warnings

**Steps:**
1. Make focused refine the default UI action for selected text.
2. Keep full regenerate as a visually distinct, deliberate action.
3. Add selection-size warning when selected text exceeds 80% of artifact content.
4. Update credit modal copy to describe value:
   - "Focused patch"
   - "Section rewrite"
   - "Full stage regenerate"
   - "Final quality pass"
5. Do not expose raw token counts to normal users.
6. Include provider/model details only in internal/debug surfaces, not the main workflow.
7. Add frontend tests for:
   - focused refine default,
   - full regenerate confirmation,
   - large-selection warning,
   - request payload includes refine mode,
   - credit modal copy matches selected mode.

**Acceptance Criteria:**
- Users can choose focused refine vs full regenerate.
- Large selection prompts a recommendation, not a hard block.
- Cost-aware actions feel product-native and value-based.
- Frontend sends refine mode to backend.

**Dependencies:** T-139

---

### T-146: Update CI, Documentation, and Smoke Tests for Phase 12

**Description:**
Wire the Phase 12 harness into CI and document how to validate provider-agnostic LLM cost optimization locally and in production. Include smoke-test steps for OpenAI now and Anthropic/Google when keys are configured.

**Severity:** High — prevents the cost layer from drifting or becoming OpenAI-only again.

**Inputs:**
- `.github/workflows/ci.yml`
- `harness/manifest.json`
- `harness/tests/backend/test_phase12_llm_cost_contract.py`
- `harness/schemas/llm-cost-event.schema.json`
- `README.md`
- `docs/SMOKE_TEST_CHECKLIST.md`
- `HANDOFF.md`

**Outputs:**
- CI step for Phase 12 harness
- README section for provider-agnostic cost optimization
- Smoke-test checklist section
- HANDOFF Phase 12 addendum

**Steps:**
1. Add `../harness/tests/backend/test_phase12_llm_cost_contract.py` to the backend harness CI command.
2. Add schema validation for `harness/schemas/llm-cost-event.schema.json`.
3. README: document:
   - provider capability registry,
   - route tiers,
   - cost telemetry fields,
   - cache behavior,
   - cross-provider fallback policy,
   - required env vars for OpenAI/Anthropic/Google.
4. Smoke-test checklist:
   - run with OpenAI key only,
   - generate SPEC/PLAN/HARNESS/TASKS,
   - verify `llm.cost_recorded` logs,
   - verify provider/tier/cost fields,
   - verify no cross-provider fallback,
   - repeat with Anthropic/Google when keys exist.
5. HANDOFF: add Phase 12 summary with invariants:
   - provider agnostic,
   - stage logic tier-based,
   - no silent cross-provider fallback,
   - prompt moat remains static/cacheable,
   - quality gates required before cheaper default promotion.
6. Run:
   ```
   cd backend && uv run pytest ../harness/tests/backend/test_phase12_llm_cost_contract.py -q
   python3 -m json.tool harness/schemas/llm-cost-event.schema.json >/dev/null
   ```

**Acceptance Criteria:**
- CI references the Phase 12 harness file.
- Documentation explains provider-agnostic operation clearly.
- Smoke checklist covers OpenAI now and Anthropic/Google later.
- All Phase 12 harness tests pass after T-132 through T-145 are complete.

**Dependencies:** T-132, T-133, T-134, T-135, T-136, T-137, T-138, T-139, T-140, T-141, T-142, T-143, T-144, T-145

---

---

## Phase 13 — GitHub Export Integration

---

### T-147: Alembic Migration — GitHub Integration Tables

**Description:**
Create the database migration that adds the three tables required by the GitHub integration feature: `user_integrations`, `integration_pushes`, and `integration_push_tasks`. This migration is the foundation for every other task in Phase 13 — nothing else can be built until these tables exist.

**Inputs:**
- `backend/migrations/versions/` (existing migration chain)
- `backend/models/` (existing model conventions)
- Plan §17.3 (T-GH-01 migration DDL)

**Outputs:**
- `backend/migrations/versions/0003_github_integration.py`

**Steps:**
1. Generate a new Alembic migration: `uv run alembic revision --autogenerate -m "github_integration"`.
2. Replace the autogenerated body with the explicit DDL from Plan §17.3 — do not rely on autogenerate because the models do not exist yet.
3. `user_integrations` table:
   - `id` UUID PK, `user_id` UUID FK→users.id NOT NULL, `provider` TEXT NOT NULL, `encrypted_token` TEXT NOT NULL, `github_username` TEXT, `connected_at` TIMESTAMPTZ NOT NULL, `last_used_at` TIMESTAMPTZ.
   - Unique constraint `uq_user_integration_provider` on `(user_id, provider)`.
   - B-tree index on `user_id`.
4. `integration_pushes` table:
   - `id` UUID PK, `workspace_id` UUID FK→workspaces.id NOT NULL, `user_id` UUID FK→users.id NOT NULL, `provider` TEXT NOT NULL, `repo_full_name` TEXT, `repo_url` TEXT, `status` TEXT NOT NULL DEFAULT `'pending'`, `pushed_at` TIMESTAMPTZ, `created_at` TIMESTAMPTZ NOT NULL.
   - Unique constraint `uq_integration_push_workspace_provider` on `(workspace_id, provider)`.
   - B-tree index on `workspace_id`.
5. `integration_push_tasks` table:
   - `id` UUID PK, `push_id` UUID FK→integration_pushes.id NOT NULL, `task_ref` TEXT NOT NULL, `external_issue_number` INTEGER NOT NULL, `created_at` TIMESTAMPTZ NOT NULL.
   - Unique constraint `uq_push_task_ref` on `(push_id, task_ref)`.
   - B-tree index on `push_id`.
6. Implement a correct `downgrade()` that drops all three tables in reverse dependency order.
7. Run `uv run alembic upgrade head` and confirm it applies cleanly against the dev database.
8. Run `uv run alembic downgrade -1` and confirm it rolls back cleanly.
9. Run `uv run alembic upgrade head` again to leave the schema in the upgraded state.

**Acceptance Criteria:**
- `uv run alembic upgrade head` exits 0 with no errors.
- `uv run alembic downgrade -1` drops all three tables without error.
- Re-upgrading produces the same schema as the first upgrade.
- All three unique constraints and all B-tree indexes are present in the upgraded schema.

**Dependencies:** T-146

---

### T-148: ORM Models and Pydantic Schemas for GitHub Integration

**Description:**
Create the three SQLAlchemy ORM models and the `schemas/integration.py` file with all request and response shapes used by the GitHub integration endpoints. Every other backend task in Phase 13 imports from these files.

**Inputs:**
- `backend/models/` (existing model conventions — see `user.py`, `workspace.py`)
- `backend/schemas/` (existing schema conventions — see `workspace.py`, `auth.py`)
- `backend/migrations/versions/0003_github_integration.py` (T-147)
- Plan §10 (data model field definitions), Spec §9 API contracts

**Outputs:**
- `backend/models/user_integration.py`
- `backend/models/integration_push.py`
- `backend/models/integration_push_task.py`
- `backend/schemas/integration.py`
- Updated `backend/models/__init__.py` to export all three new models

**Steps:**
1. Create `backend/models/user_integration.py`:
   ```python
   class UserIntegration(Base):
       __tablename__ = "user_integrations"
       id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
       user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
       provider: Mapped[str] = mapped_column(Text, nullable=False)
       encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
       github_username: Mapped[str | None] = mapped_column(Text)
       connected_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=lambda: datetime.now(UTC))
       last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
   ```
2. Create `backend/models/integration_push.py` with fields matching the migration DDL exactly.
3. Create `backend/models/integration_push_task.py` with fields matching the migration DDL exactly.
4. Update `backend/models/__init__.py` to import and re-export all three models so they are picked up by Alembic autogenerate in future revisions.
5. Create `backend/schemas/integration.py`:
   - `GitHubStatusResponse`: `connected: bool`, `github_username: str | None`
   - `GitHubExportRequest`: `repo_name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")`, `visibility: Literal["public", "private"]`
   - `GitHubExportResponse`: `push_id: UUID`, `status: str`, `repo_full_name: str | None`, `repo_url: str | None`, `issue_count: int`
   - `IntegrationPushRead`: full read-shape for GET /workspaces/{id}/export/github response
6. Run `uv run python -c "from models import UserIntegration, IntegrationPush, IntegrationPushTask"` to verify imports.
7. Run `uv run python -c "from schemas.integration import GitHubExportRequest, GitHubExportResponse"` to verify schemas.

**Acceptance Criteria:**
- All imports resolve without error.
- `GitHubExportRequest(repo_name="my-project", visibility="public")` validates successfully.
- `GitHubExportRequest(repo_name="../etc/passwd", visibility="public")` raises `ValidationError`.
- `GitHubExportRequest(repo_name="", visibility="public")` raises `ValidationError`.
- `GitHubExportRequest(repo_name="a" * 101, visibility="public")` raises `ValidationError`.

**Dependencies:** T-147

---

### T-149: GitHub Auth Service and OAuth Routes

**Description:**
Implement the GitHub OAuth connect/disconnect flow: `/auth/github` initiates the OAuth redirect, `/auth/github/callback` completes it (exchanges code for token, encrypts it, stores in `UserIntegration`), and `DELETE /integrations/github` removes the connection. The GitHub OAuth state parameter is bound to the authenticated user to prevent CSRF on the callback.

**Inputs:**
- `backend/services/auth_service.py` (existing Google OAuth pattern to follow)
- `backend/services/security/key_vault.py` (existing Fernet encrypt/decrypt)
- `backend/routers/auth.py` (extend with two new routes)
- `backend/models/user_integration.py` (T-148)
- `backend/schemas/integration.py` (T-148)
- `backend/config.py` (add `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`)

**Outputs:**
- `backend/services/integrations/__init__.py`
- `backend/services/integrations/github_auth_service.py`
- `backend/routers/integrations.py`
- Updated `backend/routers/auth.py` (two new routes)
- Updated `backend/config.py` (two new optional env vars)
- Updated `backend/main.py` (register integrations router)
- Updated `backend/.env.example`

**Steps:**
1. Add to `backend/config.py`:
   ```python
   github_client_id: str = ""
   github_client_secret: str = ""
   ```
   Both are optional (empty string = GitHub integration disabled). Add to `.env.example` with placeholder values and a comment: `# GitHub OAuth App — leave blank to disable GitHub export`.
2. Create `backend/services/integrations/github_auth_service.py` with two async functions:
   - `get_github_oauth_url(user_id: UUID, redis: Redis) -> str`: generates `secrets.token_urlsafe(32)` state, stores `{"user_id": str(user_id)}` in Redis key `oauth_github_state:{state}` with 10-minute TTL, returns the GitHub authorize URL with `client_id`, `scope=repo,read:user`, `state`.
   - `handle_github_callback(code: str, state: str, user_id: UUID, db: AsyncSession, redis: Redis) -> UserIntegration`: validates the Redis state key exists and its `user_id` matches the authenticated user's ID (delete the key on match, raise `AuthError("invalid_state")` on mismatch or miss); exchanges code for access token via `POST https://github.com/login/oauth/access_token` using `httpx.AsyncClient`; fetches `GET https://api.github.com/user` to get the login; encrypts token via `key_vault.encrypt()`; upserts `UserIntegration(provider="github", ...)` using SQLAlchemy `insert ... on conflict do update`.
   - `disconnect_github(user_id: UUID, db: AsyncSession) -> None`: deletes the `UserIntegration` row for `(user_id, "github")`. No error if not found.
3. Add two routes to `backend/routers/auth.py`:
   - `GET /auth/github`: requires authenticated user (JWT middleware); calls `github_auth_service.get_github_oauth_url`; returns `RedirectResponse` to the GitHub authorize URL. Returns 503 if `settings.github_client_id` is empty.
   - `GET /auth/github/callback`: requires authenticated user; calls `github_auth_service.handle_github_callback`; on success redirects to `{settings.frontend_url}/settings?github_connected=true`; on `AuthError("invalid_state")` returns 400; on any other error returns 502.
4. Create `backend/routers/integrations.py`:
   - `GET /integrations/github`: requires auth; queries `UserIntegration` for `(user.id, "github")`; returns `GitHubStatusResponse(connected=True/False, github_username=...)`.
   - `DELETE /integrations/github`: requires auth; calls `disconnect_github`; returns 204.
5. Register the integrations router in `backend/main.py` with prefix `/integrations`.
6. Run `uv run ruff check .` and `uv run black --check .` — fix all issues.

**Acceptance Criteria:**
- `GET /auth/github` without a valid JWT returns 401.
- `GET /auth/github` with a valid JWT redirects to `https://github.com/login/oauth/authorize?...` containing `client_id`, `scope`, and `state`.
- `GET /auth/github/callback` with a tampered or missing `state` returns 400.
- `GET /integrations/github` for a user with no connection returns `{"connected": false, "github_username": null}`.
- `DELETE /integrations/github` for a user with no connection returns 204 (idempotent).
- `GITHUB_CLIENT_ID` empty → `GET /auth/github` returns 503.

**Dependencies:** T-148

---

### T-150: GitHub API Client

**Description:**
Implement `backend/services/integrations/github_api_client.py` — a focused async wrapper around the GitHub REST API with typed exceptions. This class has no knowledge of business logic, database, or SpecForge models. It receives a plaintext token and performs exactly the operations the export service needs.

**Inputs:**
- `backend/services/integrations/__init__.py` (T-149)
- Plan §17.3 (T-GH-04 method signatures and exception types)

**Outputs:**
- `backend/services/integrations/github_api_client.py`

**Steps:**
1. Define typed exception classes at the top of the file:
   ```python
   class GitHubNotConnectedError(Exception): pass
   class GitHubRepoExistsError(Exception): pass
   class GitHubTokenExpiredError(Exception): pass
   class GitHubRateLimitError(Exception): pass
   class GitHubAPIError(Exception):
       def __init__(self, status: int, message: str): ...
   ```
2. Implement `GitHubAPIClient` as a class that accepts `token: str` and `client: httpx.AsyncClient`:
   - `async def create_repo(self, name: str, private: bool) -> dict`: POST to `https://api.github.com/repos` — raise `GitHubRepoExistsError` on 422 with "already exists" message, map 401 → `GitHubTokenExpiredError`, 429 → `GitHubRateLimitError`, other errors → `GitHubAPIError`.
   - `async def get_file_sha(self, repo: str, path: str) -> str | None`: GET `https://api.github.com/repos/{repo}/contents/{path}` — return `response["sha"]` if 200, `None` if 404, raise on other errors.
   - `async def upsert_file(self, repo: str, path: str, content: str, sha: str | None, commit_message: str) -> None`: PUT `https://api.github.com/repos/{repo}/contents/{path}` with base64-encoded content. Includes `sha` when updating an existing file. Raise on non-2xx.
   - `async def create_issue(self, repo: str, title: str, body: str) -> int`: POST `https://api.github.com/repos/{repo}/issues` — return `response["number"]`.
   - `async def update_issue(self, repo: str, number: int, title: str, body: str) -> None`: PATCH `https://api.github.com/repos/{repo}/issues/{number}`.
3. All methods set `Authorization: Bearer {token}` and `Accept: application/vnd.github+json` headers.
4. All methods map HTTP 401 from GitHub to `GitHubTokenExpiredError` before any other check.
5. Add a module-level factory function `make_github_client(token: str, client: httpx.AsyncClient) -> GitHubAPIClient` for dependency injection in tests.
6. Write unit tests in `backend/tests/test_github_api_client.py` using `respx` or `httpx.MockTransport` to mock all HTTP calls. Cover: successful create_repo, 422 repo-exists, 401 token-expired, successful upsert_file (new and update paths), successful create_issue, update_issue.
7. Run `uv run pytest tests/test_github_api_client.py -q` — all tests pass.

**Acceptance Criteria:**
- A 401 response from any GitHub API method raises `GitHubTokenExpiredError` — never returns normally.
- `get_file_sha` returns `None` on 404 without raising.
- `upsert_file` includes the correct `sha` field in the PUT body when updating.
- All unit tests pass.
- No direct `httpx` or `requests` imports exist outside `github_api_client.py` for GitHub calls.

**Dependencies:** T-148

---

### T-151: Task Parser

**Description:**
Implement `backend/services/integrations/task_parser.py` — a pure, deterministic function that extracts structured task data from TASKS.md content. No I/O, no database access, no LLM calls. Takes a string, returns a list. Fully testable with inline string fixtures.

**Inputs:**
- `backend/services/integrations/__init__.py` (T-149)
- Spec §5 (GitHub Issue body format), Plan §17.3 (T-GH-05)
- Actual TASKS.md format: `### T-NNN: Task Title` headings with Phase, Description, Steps, Acceptance Criteria, Harness refs subsections

**Outputs:**
- `backend/services/integrations/task_parser.py`
- `backend/tests/test_task_parser.py`

**Steps:**
1. Define a dataclass:
   ```python
   @dataclass
   class ParsedTask:
       ref: str        # "T-001"
       title: str      # "Set up project structure"
       body_md: str    # Formatted GitHub Issue markdown body
   ```
2. Implement `parse_tasks(content: str) -> list[ParsedTask]`:
   - Match headings with `re.compile(r"^###\s+(T-\d+):\s+(.+)$", re.MULTILINE)`.
   - For each match, capture all text between this heading and the next `###`-level heading (or end of document).
   - Format `body_md` as a GitHub Issue body using this template:
     ```markdown
     ## {title}

     {raw task body verbatim — preserves all subsections}

     ---
     *Generated by [SpecForge](https://specforge.ai)*
     ```
   - Return tasks in document order.
3. Handle edge cases: empty content returns `[]`; content with no `T-NNN` headings returns `[]`; a task with no body below the heading returns a `ParsedTask` with minimal body.
4. Write `backend/tests/test_task_parser.py` covering:
   - Normal TASKS.md excerpt with two tasks → returns two `ParsedTask` objects with correct refs and titles.
   - Task body captures everything up to (but not including) the next task heading.
   - Empty string → empty list.
   - No T-NNN headings → empty list.
   - Task title with special characters is preserved verbatim.
5. Run `uv run pytest tests/test_task_parser.py -q` — all tests pass.

**Acceptance Criteria:**
- `parse_tasks("")` returns `[]`.
- `parse_tasks("### T-001: Foo\n\nBody text\n\n### T-002: Bar\n\nOther body")` returns two `ParsedTask` objects with refs `"T-001"` and `"T-002"`.
- The body of T-001 does not include T-002's heading or body.
- All tests pass.
- The function has zero external dependencies and zero I/O.

**Dependencies:** T-148

---

### T-152: GitHub Export Service

**Description:**
Implement `backend/services/pipeline/github_export_service.py` — the orchestrator that drives the full export sequence: validate the user's GitHub connection, create or reuse a repo, push all four stage files (same layout as ZIP), parse and create/update GitHub Issues for every task. This is the core business logic of the GitHub integration.

**Inputs:**
- `backend/services/integrations/github_api_client.py` (T-150)
- `backend/services/integrations/task_parser.py` (T-151)
- `backend/services/pipeline/export_service.py` (reuse `parse_harness_files`)
- `backend/services/security/key_vault.py` (decrypt token)
- `backend/models/` (T-148)
- Spec §4.8 (export layout), Plan §17.3 (T-GH-06 orchestration steps)

**Outputs:**
- `backend/services/pipeline/github_export_service.py`
- `backend/tests/test_github_export_service.py`

**Steps:**
1. Implement `async def push_to_github(workspace_id: UUID, user_id: UUID, repo_name: str, visibility: str, db: AsyncSession) -> IntegrationPush`.
2. Step 1 — Load and decrypt token:
   - Query `UserIntegration` for `(user_id, "github")`. Raise `GitHubNotConnectedError` if absent.
   - Decrypt via `key_vault.decrypt(integration.encrypted_token)`. The plaintext token is held in a local variable only for the lifetime of this function — never logged or stored.
3. Step 2 — Load or create push record:
   - Upsert `IntegrationPush(workspace_id, user_id, provider="github", status="pending")` — on conflict update `status="pending"`.
   - If `push.repo_full_name` is already set, this is a re-export: skip `create_repo`.
4. Step 3 — Fetch stage contents:
   - Load all four stages from DB. Raise `ExportNotReadyError` (imported from `export_service`) if any stage is not `"finalised"`.
5. Step 4 — Create repo (first export only):
   - Call `client.create_repo(repo_name, private=(visibility=="private"))`.
   - Set `push.repo_full_name = f"{github_username}/{repo_name}"` and `push.repo_url = f"https://github.com/{push.repo_full_name}"`.
   - Commit the push record with these fields before proceeding — so that re-export knows the repo on partial failure.
6. Step 5 — Push files:
   - Files to push: `{"SPEC.md": spec_content, "PLAN.md": plan_content, "TASKS.md": tasks_content}` plus all entries from `parse_harness_files(harness_content)`.
   - For each path: call `client.get_file_sha(repo, path)` then `client.upsert_file(repo, path, content, sha, commit_message)`. Commit message: `"chore: SpecForge export — {workspace_name}"`.
7. Step 6 — Create/update issues:
   - Parse tasks via `task_parser.parse_tasks(tasks_content)`.
   - For each `ParsedTask`: query `IntegrationPushTask` for `(push.id, task.ref)`.
     - Found: `client.update_issue(repo, push_task.external_issue_number, task.title, task.body_md)`.
     - Not found: `number = await client.create_issue(repo, task.title, task.body_md)`; insert `IntegrationPushTask(push_id, task.ref, number)`.
8. Step 7 — Finalise:
   - Set `push.status = "completed"`, `push.pushed_at = datetime.now(UTC)`.
   - Set `integration.last_used_at = datetime.now(UTC)`.
   - Commit.
9. On any `GitHubTokenExpiredError`: delete the `UserIntegration` row, set `push.status = "failed"`, commit, re-raise.
10. On any other exception after the push record is created: set `push.status = "failed"`, commit, re-raise.
11. Write `backend/tests/test_github_export_service.py` using mocked `GitHubAPIClient` and a fake DB session (following the pattern in `test_export_service.py`). Cover: first export creates repo and issues; re-export skips create_repo and updates existing issues; `GitHubTokenExpiredError` deletes the integration row; stage not finalised raises `ExportNotReadyError`.

**Acceptance Criteria:**
- Re-export to the same repo never calls `create_repo`.
- A 401 from GitHub deletes the `UserIntegration` row before re-raising.
- Partial failure (files pushed, issue creation fails) leaves `push.status = "failed"` and `push.repo_full_name` set, so re-export retries from the issue-creation step.
- All tests pass.

**Dependencies:** T-150, T-151

---

### T-153: Integrations Router and Workspace GitHub Export Endpoints

**Description:**
Wire the GitHub export service into the HTTP layer. Add `POST /workspaces/{id}/export/github` and `GET /workspaces/{id}/export/github` to `workspace.py`, add the GitHub export rate limit (3 per user per hour) to the rate limit middleware, and verify that the existing ZIP export endpoint is completely unchanged.

**Inputs:**
- `backend/routers/workspace.py` (existing export endpoint)
- `backend/middleware/rate_limit.py` (existing rate limit tiers)
- `backend/services/pipeline/github_export_service.py` (T-152)
- `backend/schemas/integration.py` (T-148)

**Outputs:**
- Updated `backend/routers/workspace.py`
- Updated `backend/middleware/rate_limit.py`

**Steps:**
1. Add to `backend/routers/workspace.py`:
   - `POST /workspaces/{id}/export/github`:
     - Requires authenticated user.
     - Accepts `GitHubExportRequest` body.
     - Calls `github_export_service.push_to_github(id, user.id, body.repo_name, body.visibility, db)`.
     - Returns `GitHubExportResponse` with status 202 on success.
     - Maps exceptions to HTTP responses:
       - `GitHubNotConnectedError` → 403 `{"detail": "GitHub not connected. Connect from Settings."}`
       - `GitHubTokenExpiredError` → 403 `{"detail": "GitHub connection expired. Reconnect from Settings."}`
       - `GitHubRepoExistsError` → 409 `{"detail": "A repo with that name already exists in your GitHub account."}`
       - `GitHubRateLimitError` → 429 `{"detail": "GitHub API rate limit reached. Wait a few minutes and try again."}`
       - `ExportNotReadyError` → 409 `{"detail": str(exc)}`
       - `GitHubAPIError` → 502 `{"detail": "GitHub returned an unexpected error."}`
   - `GET /workspaces/{id}/export/github`:
     - Requires authenticated user, asserts workspace ownership (same pattern as existing GET /workspaces/{id}).
     - Queries `IntegrationPush` for `(workspace_id, "github")`.
     - Returns `IntegrationPushRead` if found, 404 if not.
2. Add GitHub export rate limit to `backend/middleware/rate_limit.py`:
   - New tier: key `ratelimit:github_export:{user_id}`, limit 3 requests, window 3600 seconds.
   - Apply only to `POST /workspaces/{id}/export/github` — match by route pattern, not prefix.
   - On limit exceeded return 429 with `{"detail": "GitHub export rate limit reached. Maximum 3 exports per hour."}`.
3. Verify the existing `POST /workspaces/{id}/export` (ZIP) route is unchanged — no new imports, no new logic, same response shape.
4. Run `uv run ruff check .` and `uv run black --check .` — fix all issues.
5. Run `uv run pytest tests/ -q` — all existing tests still pass.

**Acceptance Criteria:**
- `POST /workspaces/{id}/export` (ZIP) still returns a ZIP blob — not modified.
- `POST /workspaces/{id}/export/github` without auth returns 401.
- `POST /workspaces/{id}/export/github` for a workspace the user does not own returns 404.
- `POST /workspaces/{id}/export/github` for an un-finalised workspace returns 409.
- After 3 successful calls, the 4th returns 429.
- All existing tests pass.

**Dependencies:** T-152

---

### T-154: Backend Tests — GitHub Integration Contract Suite

**Description:**
Write a focused contract test file that verifies the end-to-end GitHub integration backend behaviour against the running app (not mocks) — covering the OAuth routes, integrations router, workspace export endpoints, rate limit, and error-mapping table. These tests are the "T-GH-XX done" gate — every sub-task from T-149 through T-153 must be green here before the frontend work begins.

**Inputs:**
- All T-147 through T-153 outputs
- `backend/tests/conftest.py` (existing app + DB fixtures)
- `backend/tests/test_export_service.py` (reference for fake DB pattern)

**Outputs:**
- `backend/tests/test_github_integration.py`

**Steps:**
1. Structure the file with four test classes: `TestGitHubAuth`, `TestIntegrationsRouter`, `TestGitHubExport`, `TestGitHubRateLimit`.
2. `TestGitHubAuth`:
   - `GET /auth/github` without JWT → 401.
   - `GET /auth/github` with valid JWT and `GITHUB_CLIENT_ID` empty → 503.
   - `GET /auth/github/callback` with missing `state` → 400.
   - `GET /auth/github/callback` with tampered `state` (not in Redis) → 400.
   - `DELETE /integrations/github` with no connection → 204 (idempotent).
3. `TestIntegrationsRouter`:
   - `GET /integrations/github` for unconnected user → `{"connected": false, "github_username": null}`.
   - After inserting a `UserIntegration` row directly, `GET /integrations/github` → `{"connected": true, "github_username": "testuser"}`.
   - `DELETE /integrations/github` for connected user → 204, row deleted.
4. `TestGitHubExport` (patch `github_export_service.push_to_github` with `AsyncMock`):
   - `POST .../export/github` without auth → 401.
   - `POST .../export/github` for another user's workspace → 404.
   - `POST .../export/github` with `GitHubNotConnectedError` → 403.
   - `POST .../export/github` with `GitHubRepoExistsError` → 409.
   - `POST .../export/github` with `GitHubTokenExpiredError` → 403.
   - `POST .../export/github` with `ExportNotReadyError` → 409.
   - `POST .../export/github` with `GitHubRateLimitError` → 429.
   - `POST .../export/github` success → 202 with `push_id`, `repo_url`, `issue_count`.
   - `GET .../export/github` with no prior push → 404.
   - `GET .../export/github` after inserting a push row → 200 with correct fields.
5. `TestGitHubRateLimit`:
   - Make 3 successful calls → all succeed.
   - 4th call → 429 with rate limit message.
   - Confirm existing ZIP `POST .../export` is NOT rate-limited by the GitHub tier.
6. Run `uv run pytest tests/test_github_integration.py -v` — all tests pass.
7. Run `uv run pytest tests/ --cov=services --cov-fail-under=80 -q` — coverage threshold maintained.

**Acceptance Criteria:**
- All tests in `test_github_integration.py` pass.
- Coverage does not drop below 80%.
- No test shares state — each test either uses transactions or cleans up its rows.

**Dependencies:** T-153

---

### T-155: Frontend TypeScript Types and API Client Functions

**Description:**
Add all TypeScript interfaces and `api.ts` functions needed by the GitHub integration frontend. This task produces no visible UI — it is the data layer that T-156, T-157, and T-158 depend on.

**Inputs:**
- `frontend/src/services/api.ts` (existing Axios client and patterns)
- `frontend/src/types/workspace.ts` (reference for type conventions)
- `backend/schemas/integration.py` (T-148 — source of truth for shapes)

**Outputs:**
- Updated `frontend/src/services/api.ts`
- Updated `frontend/src/types/` or inline in `api.ts` (follow existing convention)

**Steps:**
1. Add TypeScript interfaces to `api.ts` (or `types/integration.ts` if the project uses separate type files — match existing convention):
   ```typescript
   export interface GitHubIntegration {
     connected: boolean
     github_username: string | null
   }

   export interface GitHubExportRequest {
     repo_name: string
     visibility: "public" | "private"
   }

   export interface GitHubExportResponse {
     push_id: string
     status: string
     repo_full_name: string | null
     repo_url: string | null
     issue_count: number
   }

   export interface IntegrationPushRead {
     push_id: string
     status: string
     repo_full_name: string | null
     repo_url: string | null
     issue_count: number
     pushed_at: string | null
   }
   ```
2. Add four functions to `api.ts`:
   ```typescript
   export async function getGitHubIntegration(): Promise<GitHubIntegration>
   // GET /integrations/github — returns {connected: false, github_username: null} on 404

   export async function deleteGitHubIntegration(): Promise<void>
   // DELETE /integrations/github

   export async function exportWorkspaceToGitHub(
     id: string,
     body: GitHubExportRequest
   ): Promise<GitHubExportResponse>
   // POST /workspaces/{id}/export/github

   export async function getGitHubPush(id: string): Promise<IntegrationPushRead | null>
   // GET /workspaces/{id}/export/github — returns null on 404
   ```
3. `getGitHubIntegration` must catch 404 and return `{ connected: false, github_username: null }` rather than throwing, so callers can use it unconditionally.
4. `getGitHubPush` must catch 404 and return `null` rather than throwing.
5. Both mutating functions (`deleteGitHubIntegration`, `exportWorkspaceToGitHub`) must go through the existing Axios instance (which automatically attaches the CSRF token and auth header).
6. Run `pnpm tsc` — no TypeScript errors.
7. Run `pnpm test` — all existing Vitest tests still pass.

**Acceptance Criteria:**
- `pnpm tsc` exits 0.
- All four functions are exported and callable from other modules.
- `getGitHubIntegration` does not throw on 404 — returns the disconnected shape.
- `getGitHubPush` does not throw on 404 — returns `null`.
- No changes to any existing API functions.

**Dependencies:** T-154

---

### T-156: Settings Page with GitHub Integration Panel

**Description:**
Create `frontend/src/pages/Settings.tsx`, add a `/settings` route to `App.tsx`, and add a navigation link in the Dashboard and Workspace headers. The Settings page shows one integration card: GitHub. The card displays either a "Connect GitHub" button or the connected state with a "Disconnect" action. The page must fully match the Modern Indica design system — glassmorphism background, saffron primary, lotus pink secondary, Plus Jakarta Sans typography — using the same CSS variable and class naming conventions as the rest of the app.

**Inputs:**
- `frontend/src/index.css` (existing CSS classes — reference `create-modal`, `workspace-header`, `.modal-submit`, `.modal-cancel`, `.provider-pill`)
- `frontend/src/pages/Dashboard.tsx` (page layout reference)
- `frontend/src/services/api.ts` (T-155 — `getGitHubIntegration`, `deleteGitHubIntegration`)
- `frontend/src/App.tsx` (add route)
- `Design.md` (color tokens, typography, glassmorphism rules)

**Outputs:**
- `frontend/src/pages/Settings.tsx`
- Updated `frontend/src/App.tsx` (new `/settings` protected route)
- Updated `frontend/src/index.css` (new CSS classes for settings page)
- Navigation link additions in Dashboard and Workspace headers

**Steps:**
1. Add new CSS classes to `frontend/src/index.css` **after** the existing `.workspace-export-btn` block, following the exact same naming convention and design tokens:
   ```css
   /* ─── Settings page ─────────────────────────────────────── */
   .settings-page {
     min-height: 100vh;
     background: var(--color-background);
     display: flex;
     flex-direction: column;
   }

   .settings-header {
     min-height: 72px;
     display: flex;
     align-items: center;
     justify-content: space-between;
     padding: 0 28px;
     background:
       linear-gradient(135deg, rgba(255,255,255,0.86), rgba(253,246,238,0.70)),
       rgba(253, 246, 238, 0.78);
     border-bottom: 1px solid rgba(143, 78, 0, 0.09);
     backdrop-filter: blur(20px);
     -webkit-backdrop-filter: blur(20px);
     flex-shrink: 0;
   }

   .settings-header-title {
     font-size: 18px;
     font-weight: 800;
     letter-spacing: -0.02em;
     background: linear-gradient(115deg, var(--color-primary) 0%, var(--color-secondary) 100%);
     -webkit-background-clip: text;
     -webkit-text-fill-color: transparent;
     background-clip: text;
   }

   .settings-back-link {
     display: inline-flex;
     align-items: center;
     gap: 6px;
     font-size: 13px;
     font-weight: 600;
     color: var(--color-on-surface-variant);
     text-decoration: none;
     padding: 6px 10px;
     border-radius: 8px;
     transition: background 0.15s, color 0.15s;
   }

   .settings-back-link:hover {
     background: rgba(143, 78, 0, 0.07);
     color: var(--color-primary);
   }

   .settings-content {
     max-width: 720px;
     margin: 40px auto;
     padding: 0 24px;
     width: 100%;
   }

   .settings-section-label {
     font-size: 11px;
     font-weight: 700;
     letter-spacing: 0.07em;
     text-transform: uppercase;
     color: var(--color-on-surface-variant);
     margin-bottom: 12px;
   }

   .settings-card {
     background: rgba(255, 255, 255, 0.82);
     border: 1px solid rgba(143, 78, 0, 0.12);
     border-radius: 16px;
     padding: 20px 24px;
     display: flex;
     align-items: center;
     justify-content: space-between;
     gap: 16px;
     box-shadow: 0 2px 12px rgba(143, 78, 0, 0.06);
     backdrop-filter: blur(12px);
     -webkit-backdrop-filter: blur(12px);
   }

   .settings-card-info {
     display: flex;
     flex-direction: column;
     gap: 3px;
   }

   .settings-card-name {
     font-size: 15px;
     font-weight: 700;
     color: var(--color-on-surface);
   }

   .settings-card-desc {
     font-size: 13px;
     color: var(--color-on-surface-variant);
     line-height: 1.5;
   }

   .settings-card-status-connected {
     display: flex;
     align-items: center;
     gap: 6px;
     font-size: 13px;
     font-weight: 600;
     color: #166534;
   }

   .settings-card-status-dot {
     width: 8px;
     height: 8px;
     border-radius: 50%;
     background: #22c55e;
     flex-shrink: 0;
   }

   .settings-card-actions {
     display: flex;
     align-items: center;
     gap: 10px;
     flex-shrink: 0;
   }

   .settings-btn-connect {
     height: 36px;
     padding: 0 18px;
     border-radius: 10px;
     background: var(--color-primary);
     color: var(--color-on-primary);
     border: none;
     font-size: 13px;
     font-weight: 700;
     font-family: inherit;
     cursor: pointer;
     transition: background 0.15s, transform 0.15s, box-shadow 0.15s;
     box-shadow: 0 2px 8px rgba(143, 78, 0, 0.20);
   }

   .settings-btn-connect:hover {
     background: #7a4200;
     transform: translateY(-1px);
     box-shadow: 0 4px 14px rgba(143, 78, 0, 0.28);
   }

   .settings-btn-connect:active {
     transform: translateY(0);
   }

   .settings-btn-disconnect {
     height: 36px;
     padding: 0 16px;
     border-radius: 10px;
     background: transparent;
     border: 1px solid rgba(186, 26, 26, 0.22);
     color: var(--color-error);
     font-size: 13px;
     font-weight: 600;
     font-family: inherit;
     cursor: pointer;
     transition: background 0.15s;
   }

   .settings-btn-disconnect:hover {
     background: rgba(186, 26, 26, 0.06);
   }

   .settings-disconnect-confirm {
     display: flex;
     align-items: center;
     gap: 8px;
     flex-shrink: 0;
   }

   .settings-disconnect-confirm span {
     font-size: 13px;
     color: var(--color-on-surface-variant);
   }

   /* Gear icon link in workspace/dashboard headers */
   .header-settings-link {
     height: 34px;
     width: 34px;
     border-radius: 9px;
     display: flex;
     align-items: center;
     justify-content: center;
     background: transparent;
     border: none;
     color: var(--color-on-surface-variant);
     cursor: pointer;
     text-decoration: none;
     transition: background 0.15s, color 0.15s;
     flex-shrink: 0;
   }

   .header-settings-link:hover {
     background: rgba(143, 78, 0, 0.08);
     color: var(--color-primary);
   }
   ```

2. Create `frontend/src/pages/Settings.tsx`:
   - Fetch `getGitHubIntegration()` on mount into local state `{ connected, github_username }`.
   - Add local state `disconnectConfirm: boolean` for the inline confirm UI.
   - "Connect GitHub": calls `window.location.href = "/api/auth/github"` (the backend redirect). Note: use the Vite proxy path `/api/auth/github` so it routes correctly in dev.
   - "Disconnect" → sets `disconnectConfirm = true`. Shows inline: `"Remove access?"` with a small `[Yes, disconnect]` button (`settings-btn-disconnect`) and `[Cancel]` link.
   - `[Yes, disconnect]` calls `deleteGitHubIntegration()` then re-fetches the status.
   - On error from `getGitHubIntegration` during disconnect, show `modal-error` text: "Disconnect failed. Please try again."
   - Back link uses `useNavigate()` to go to `/dashboard`.
   - Render the page with: `.settings-page` wrapper → `.settings-header` (title "Settings" + back link "← Dashboard") → `.settings-content` → `.settings-section-label` "Integrations" → one `.settings-card` for GitHub.
   - The GitHub card shows: left side `.settings-card-info` with name "GitHub" and desc "Export workspaces to a new repo with tasks as Issues"; right side `.settings-card-actions` showing either the connect button or the connected state + disconnect.
   - Connected state: `.settings-card-status-connected` with `.settings-card-status-dot` + text `Connected as @{github_username}` + disconnect button (or confirm).

3. Add `/settings` route to `App.tsx` as a protected route rendering `<Settings />`.

4. Add a gear icon `⚙` link to the settings page in:
   - **Dashboard header**: add a `<Link to="/settings" className="header-settings-link" aria-label="Settings">⚙</Link>` next to the existing user avatar/actions area.
   - **Workspace header**: add the same link inside `.workspace-header-actions` to the right of the export buttons.

5. Run `pnpm tsc` — no TypeScript errors.
6. Start the dev server and navigate to `/settings`. Verify: page renders with correct glassmorphism styling; gear icon in Dashboard and Workspace headers routes to `/settings`; GitHub shows "not connected" state by default; clicking "Connect GitHub" redirects to the GitHub OAuth URL.

**Acceptance Criteria:**
- Settings page uses only existing CSS variables (`--color-primary`, `--color-secondary`, `--color-error`, `--color-on-surface`, `--color-on-surface-variant`, `--color-on-primary`, `--color-background`) and the new CSS classes from step 1 — no inline `style={{}}` props for colors or spacing.
- All new CSS classes follow the `settings-` naming prefix and the same declaration style as existing classes (property order: position → display → sizing → spacing → border → background → font → transition).
- The page header matches the visual language of `.workspace-header` (same glassmorphism, same saffron gradient title).
- The integration card matches the visual language of `.create-modal` cards (white glass surface, saffron border, 16px radius).
- "Connect GitHub" button is visually consistent with `.modal-submit` (saffron fill, white text, 10px radius).
- "Disconnect" button is visually consistent with `.modal-cancel` (transparent, error-color border and text).
- `pnpm tsc` exits 0.

**Dependencies:** T-155

---

### T-157: ExportGitHubModal Component

**Description:**
Create `frontend/src/components/workspace/ExportGitHubModal.tsx` — the modal that appears when the user clicks "Export to GitHub". It has four distinct visual states: configure (repo name + visibility + issue count), in-progress (animated dots + status text), success (green check + repo URL + open link), and not-connected (message with link to Settings). The modal must use existing CSS modal classes as its structural foundation and add only the minimum new CSS classes required for the GitHub-specific UI elements.

**Inputs:**
- `frontend/src/index.css` (existing modal classes: `create-modal-backdrop`, `create-modal`, `create-modal-header`, `create-modal-title`, `create-modal-close`, `create-modal-body`, `modal-label`, `modal-input`, `modal-submit`, `modal-cancel`, `modal-footer`, `modal-error`)
- `frontend/src/hooks/useFocusTrap.ts` (existing focus trap hook — use the same pattern as `CreateWorkspaceModal`)
- `frontend/src/services/api.ts` (T-155 — `exportWorkspaceToGitHub`, `getGitHubPush`)
- `frontend/src/components/workspace/CreditConfirmModal.tsx` (reference for modal structure)

**Outputs:**
- `frontend/src/components/workspace/ExportGitHubModal.tsx`
- New CSS classes added to `frontend/src/index.css` (after the settings CSS block from T-156)

**Steps:**
1. Add new CSS classes to `frontend/src/index.css` after the settings block:
   ```css
   /* ─── GitHub Export Modal ───────────────────────────────── */
   .github-modal-visibility-grid {
     display: grid;
     grid-template-columns: 1fr 1fr;
     gap: 8px;
   }

   .github-modal-visibility-btn {
     height: 44px;
     border-radius: 10px;
     border: 1px solid rgba(143, 78, 0, 0.18);
     background: rgba(255, 255, 255, 0.55);
     font-size: 14px;
     font-weight: 600;
     font-family: inherit;
     color: var(--color-on-surface-variant);
     cursor: pointer;
     transition: border-color 0.15s, background 0.15s, color 0.15s, box-shadow 0.15s;
   }

   .github-modal-visibility-btn:hover {
     border-color: rgba(143, 78, 0, 0.30);
     background: rgba(143, 78, 0, 0.05);
     color: var(--color-on-surface);
   }

   .github-modal-visibility-btn.selected {
     border-color: var(--color-primary);
     background: rgba(143, 78, 0, 0.10);
     color: var(--color-primary);
     box-shadow: 0 0 0 3px rgba(143, 78, 0, 0.10);
   }

   .github-modal-issue-pill {
     display: inline-flex;
     align-items: center;
     gap: 5px;
     padding: 5px 12px;
     border-radius: 9999px;
     background: rgba(143, 78, 0, 0.07);
     border: 1px solid rgba(143, 78, 0, 0.14);
     font-size: 12px;
     font-weight: 700;
     letter-spacing: 0.01em;
     color: var(--color-primary);
     align-self: flex-start;
   }

   .github-modal-progress {
     display: flex;
     flex-direction: column;
     align-items: center;
     gap: 14px;
     padding: 20px 0;
   }

   .github-modal-progress-label {
     font-size: 14px;
     color: var(--color-on-surface-variant);
   }

   .github-modal-dots {
     display: flex;
     gap: 7px;
   }

   .github-modal-dots span {
     width: 9px;
     height: 9px;
     border-radius: 50%;
     background: var(--color-primary);
     animation: gh-bounce 1.3s ease-in-out infinite;
   }

   .github-modal-dots span:nth-child(2) { animation-delay: 0.22s; }
   .github-modal-dots span:nth-child(3) { animation-delay: 0.44s; }

   @keyframes gh-bounce {
     0%, 80%, 100% { transform: scale(0.65); opacity: 0.35; }
     40%            { transform: scale(1.0);  opacity: 1; }
   }

   .github-modal-success {
     display: flex;
     flex-direction: column;
     align-items: center;
     gap: 14px;
     padding: 16px 0;
     text-align: center;
   }

   .github-modal-success-icon {
     width: 46px;
     height: 46px;
     border-radius: 50%;
     background: rgba(34, 197, 94, 0.10);
     border: 1.5px solid rgba(34, 197, 94, 0.30);
     display: flex;
     align-items: center;
     justify-content: center;
     color: #166534;
     font-size: 22px;
   }

   .github-modal-success-title {
     font-size: 15px;
     font-weight: 700;
     color: var(--color-on-surface);
   }

   .github-modal-success-url {
     font-size: 13px;
     color: var(--color-primary);
     text-decoration: underline;
     word-break: break-all;
     cursor: pointer;
   }

   .github-modal-not-connected {
     display: flex;
     flex-direction: column;
     align-items: center;
     gap: 12px;
     padding: 16px 0;
     text-align: center;
   }

   .github-modal-not-connected p {
     font-size: 14px;
     color: var(--color-on-surface-variant);
     line-height: 1.5;
   }
   ```

2. Create `frontend/src/components/workspace/ExportGitHubModal.tsx`:
   - Props: `{ workspaceId: string, workspaceName: string, isConnected: boolean, taskCount: number, onClose: () => void }`.
   - Local state: `repoName` (pre-filled to kebab-case of `workspaceName`), `visibility: "public" | "private"` (default `"public"`), `phase: "configure" | "progress" | "success" | "error"`, `progressLabel: string`, `result: GitHubExportResponse | null`, `error: string | null`.
   - Use `useFocusTrap` (same import and usage pattern as `CreateWorkspaceModal`).
   - Wrap in `create-modal-backdrop` (click outside → `onClose()`).
   - Inner container: `create-modal` with `role="dialog" aria-modal="true"`.
   - Header: `create-modal-header` with title "Export to GitHub" in `create-modal-title` (gets the saffron-to-pink gradient for free), close button in `create-modal-close`.
   - Body: `create-modal-body`. Switch on `phase`:
     - **`"configure"`** (default when `isConnected`):
       - Repo name: `modal-label` + `modal-input` (type `text`, `maxLength={100}`, validate against `^[a-zA-Z0-9._-]+$` on blur — show `modal-error` if invalid).
       - Visibility: `modal-label` "Visibility" + `github-modal-visibility-grid` with two `github-modal-visibility-btn` buttons (Public / Private), the selected one gets the `selected` class.
       - Issue count: `github-modal-issue-pill` showing `{taskCount} issue{taskCount !== 1 ? "s" : ""} will be created`.
       - Footer: `modal-footer` with `modal-cancel` ("Cancel") and `modal-submit` ("Export →", disabled while `repoName` is invalid or empty).
     - **`"progress"`**: `github-modal-progress` with `.github-modal-dots` (three `<span>`s) and `.github-modal-progress-label` showing `progressLabel` state (update from "Creating repo…" → "Pushing files…" → "Creating issues…" with a `setInterval` every 3s).
     - **`"success"`**: `github-modal-success` with `.github-modal-success-icon` (✓), `.github-modal-success-title` ("Exported successfully"), `.github-modal-success-url` as an `<a href={result.repo_url} target="_blank">` showing the repo URL, and a `modal-submit` button ("Open on GitHub ↗", opens same link, then calls `onClose()`).
     - **`"error"`**: shows `modal-error` text (`error` state value), and a `modal-footer` with `modal-cancel` ("Close") and `modal-submit` ("Try again") that resets to `"configure"` phase.
     - **`isConnected === false`**: `github-modal-not-connected` with text "Connect your GitHub account in Settings to export to a repo" and a `modal-submit` button ("Go to Settings →") that navigates to `/settings` via `useNavigate()` and calls `onClose()`.
   - On `modal-submit` click in configure phase: set `phase = "progress"`, call `exportWorkspaceToGitHub(workspaceId, { repo_name: repoName, visibility })`, handle result or catch error → set `phase = "success"/"error"`.
   - `repoName` pre-fill: convert `workspaceName` to lowercase, replace spaces and non-alphanumeric with `-`, collapse multiple `-`, trim leading/trailing `-`. Max 100 chars.

3. Run `pnpm tsc` — no TypeScript errors.
4. Start dev server. Open any finalised workspace. Trigger the GitHub export modal (requires wiring from T-158 — can test in isolation by rendering the component temporarily in Workspace.tsx with `isConnected={false}` first).

**Acceptance Criteria:**
- The modal uses only existing `create-modal-*` / `modal-*` classes for its structural shell — no new CSS for the backdrop, container, header, input, footer, submit, or cancel elements.
- New CSS classes use the `github-modal-` prefix and follow the exact same property-order convention as the rest of `index.css`.
- The visibility selector uses two pill buttons (not a `<select>` or `<input type="radio">`) — consistent with the `.provider-pill` pattern used in `CreateWorkspaceModal`.
- The progress state shows three animated dots using `var(--color-primary)` (saffron) — not a spinner.
- All four phases render without TypeScript errors.
- `pnpm tsc` exits 0.

**Dependencies:** T-155, T-156

---

### T-158: Workspace Header — Split Export Buttons and GitHub Export Flow

**Description:**
Update `Workspace.tsx` and `index.css` to split the single "Export" button into two: "↓ ZIP" (existing behaviour, renamed) and "↑ GitHub" (new). Fetch the GitHub connection status on workspace load. Wire the GitHub button to open `ExportGitHubModal`. Add a disabled tooltip on the GitHub button when not connected. The existing ZIP export path must not change in any way.

**Inputs:**
- `frontend/src/pages/Workspace.tsx` (existing export button at line ~835)
- `frontend/src/index.css` (existing `.workspace-export-btn` CSS)
- `frontend/src/components/workspace/ExportGitHubModal.tsx` (T-157)
- `frontend/src/services/api.ts` (T-155 — `getGitHubIntegration`)

**Outputs:**
- Updated `frontend/src/pages/Workspace.tsx`
- New CSS classes in `frontend/src/index.css`
- `ExportGitHubModal` integrated into the workspace

**Steps:**
1. Add new CSS to `frontend/src/index.css` after the GitHub modal block (from T-157):
   ```css
   /* ─── Workspace GitHub export button ───────────────────── */
   .workspace-github-btn {
     position: relative;
     height: 46px;
     padding: 0 18px;
     border-radius: 14px;
     border: 1px solid rgba(86, 94, 116, 0.20);
     background:
       linear-gradient(135deg, rgba(255,255,255,0.94), rgba(218,226,253,0.60)),
       rgba(255, 255, 255, 0.72);
     font-size: 14px;
     font-weight: 700;
     color: var(--color-on-surface-variant);
     cursor: pointer;
     transition: background 0.18s, border-color 0.18s, box-shadow 0.18s, transform 0.18s;
     box-shadow: 0 2px 8px rgba(86, 94, 116, 0.07);
     display: flex;
     align-items: center;
     gap: 6px;
     white-space: nowrap;
   }

   .workspace-github-btn:hover:not(:disabled) {
     background:
       linear-gradient(135deg, rgba(86, 94, 116, 0.10), rgba(143, 78, 0, 0.05)),
       rgba(255, 255, 255, 0.88);
     border-color: rgba(86, 94, 116, 0.34);
     box-shadow: 0 6px 18px rgba(86, 94, 116, 0.12);
     transform: translateY(-1px);
     color: var(--color-on-surface);
   }

   .workspace-github-btn.ready:not(:disabled) {
     border-color: rgba(34, 197, 94, 0.28);
     background:
       linear-gradient(135deg, rgba(34, 197, 94, 0.09), rgba(86, 94, 116, 0.05)),
       rgba(255, 255, 255, 0.82);
     color: #166534;
   }

   .workspace-github-btn:disabled {
     opacity: 0.38;
     cursor: not-allowed;
   }

   /* Tooltip on disabled GitHub button */
   .workspace-github-btn-wrap {
     position: relative;
     display: inline-flex;
   }

   .workspace-github-btn-wrap[data-tooltip]:hover::after {
     content: attr(data-tooltip);
     position: absolute;
     bottom: calc(100% + 8px);
     right: 0;
     padding: 6px 10px;
     border-radius: 8px;
     background: rgba(26, 28, 28, 0.90);
     color: #f0f1f1;
     font-size: 12px;
     font-weight: 500;
     white-space: nowrap;
     pointer-events: none;
     z-index: 100;
   }
   ```

2. In `Workspace.tsx`, add state and effect:
   ```typescript
   const [isGitHubConnected, setIsGitHubConnected] = useState(false)
   const [showGitHubExport, setShowGitHubExport] = useState(false)

   useEffect(() => {
     getGitHubIntegration()
       .then((g) => setIsGitHubConnected(g.connected))
       .catch(() => setIsGitHubConnected(false))
   }, [])
   ```

3. Count tasks for the issue count preview: derive `taskCount` by counting `### T-` occurrences in the tasks stage content (or pass `0` if tasks stage not finalised) — pure string operation, no API call.
   ```typescript
   const taskCount = useMemo(() => {
     const tasksStage = stages.find(s => s.type === "tasks")
     if (!tasksStage?.content) return 0
     return (tasksStage.content.match(/^###\s+T-\d+:/gm) ?? []).length
   }, [stages])
   ```

4. Replace the existing single export button in the workspace header with the two-button layout:
   ```tsx
   <div className="workspace-header-actions">
     {/* existing non-export actions stay here unchanged */}

     {/* ZIP download — existing behaviour, keep all existing logic */}
     <button
       disabled={!canExport || isExporting}
       onClick={() => void handleExport()}
       className={`workspace-export-btn ${allFinalised ? "ready" : ""}`}
       aria-label="Download ZIP"
     >
       {isExporting ? "Exporting…" : "↓ ZIP"}
     </button>

     {/* GitHub export */}
     <div
       className="workspace-github-btn-wrap"
       data-tooltip={!isGitHubConnected ? "Connect GitHub in Settings to export" : undefined}
     >
       <button
         disabled={!canExport || !isGitHubConnected}
         onClick={() => setShowGitHubExport(true)}
         className={`workspace-github-btn ${allFinalised && isGitHubConnected ? "ready" : ""}`}
         aria-label="Export to GitHub"
       >
         ↑ GitHub
       </button>
     </div>

     {/* Settings gear */}
     <Link to="/settings" className="header-settings-link" aria-label="Settings">
       ⚙
     </Link>
   </div>
   ```

5. Render `ExportGitHubModal` conditionally:
   ```tsx
   {showGitHubExport && (
     <ExportGitHubModal
       workspaceId={id!}
       workspaceName={currentWorkspace?.name ?? ""}
       isConnected={isGitHubConnected}
       taskCount={taskCount}
       onClose={() => setShowGitHubExport(false)}
     />
   )}
   ```

6. Import `Link` from `react-router-dom` (add to existing import if not present), import `ExportGitHubModal` from `../components/workspace/ExportGitHubModal`, import `getGitHubIntegration` from `../services/api`.

7. Run `pnpm tsc` — no errors. Run `pnpm test` — all tests pass.
8. Start dev server. Open a finalised workspace:
   - Both "↓ ZIP" and "↑ GitHub" buttons are visible in the header.
   - ZIP button behaves exactly as before.
   - GitHub button shows a tooltip "Connect GitHub in Settings to export" when hovered while disconnected.
   - After connecting GitHub (via Settings), GitHub button becomes active on workspace load.
   - Clicking active GitHub button opens `ExportGitHubModal` in configure phase.
   - Settings gear icon (⚙) navigates to `/settings`.

**Acceptance Criteria:**
- The existing `handleExport` function and `exportWorkspace` API call are unchanged.
- `workspace-export-btn` class is unchanged — no edits to its CSS or its usage for ZIP.
- `workspace-github-btn` uses `--color-tertiary`-family tints (`rgba(86, 94, 116, ...)`) to visually distinguish it from the saffron ZIP button without breaking the design language.
- Tooltip appears only on the GitHub button when `disabled` — the ZIP button has no tooltip.
- `pnpm tsc` exits 0 and `pnpm test` passes.

**Dependencies:** T-157

---

### T-159: CI Update and Integration Smoke Test Checklist

**Description:**
Wire the new backend tests into CI, update `.env.example` and `CLAUDE.md` with the two new GitHub env vars, and add a GitHub integration section to the smoke test checklist. Confirm the full test suite passes in Docker.

**Inputs:**
- `.github/workflows/ci.yml`
- `backend/.env.example` (should already have GITHUB_CLIENT_ID from T-149 — verify)
- `CLAUDE.md` (project instructions)
- `docs/SMOKE_TEST_CHECKLIST.md` (if present) or `README.md`
- All T-147 through T-158 outputs

**Outputs:**
- Updated `.github/workflows/ci.yml`
- Verified `backend/.env.example`
- Updated `CLAUDE.md` environment variables section
- Updated smoke test checklist

**Steps:**
1. Add to the backend CI job in `.github/workflows/ci.yml`:
   ```yaml
   - name: GitHub integration tests
     run: cd backend && uv run pytest tests/test_github_integration.py tests/test_github_api_client.py tests/test_task_parser.py -q
   ```
   Place this step after the existing `pytest` step, before the coverage step.
2. Verify `backend/.env.example` contains:
   ```bash
   # GitHub OAuth App — leave blank to disable GitHub export
   GITHUB_CLIENT_ID=
   GITHUB_CLIENT_SECRET=
   ```
   Add if missing.
3. Update `CLAUDE.md` environment variables section to list `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` as optional backend vars.
4. Add a "GitHub Export Integration" smoke test section to the checklist (create `docs/SMOKE_TEST_CHECKLIST.md` if it does not exist, appending to it if it does):
   ```
   ## GitHub Export Integration

   Prerequisites: GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET configured.

   1. Sign in. Navigate to Settings. Verify GitHub shows "not connected".
   2. Click "Connect GitHub". Complete GitHub OAuth. Verify Settings shows "Connected as @username".
   3. Open a fully-finalised workspace.
   4. Verify "↓ ZIP" and "↑ GitHub" buttons are both visible in the workspace header.
   5. Click "↓ ZIP". Verify the download completes and the ZIP contains SPEC.md, PLAN.md, TASKS.md, and harness/ files.
   6. Click "↑ GitHub". Verify the modal opens with pre-filled repo name and correct issue count.
   7. Set visibility to Private. Click "Export →". Verify progress dots appear.
   8. Verify success screen shows repo URL. Click "Open on GitHub ↗". Verify the repo exists on GitHub with correct files and issues.
   9. Close modal. Click "↑ GitHub" again. Verify re-export modal shows "Previously exported" note with read-only repo name.
   10. Re-export. Verify issues are updated, not duplicated.
   11. Navigate to Settings. Click "Disconnect". Confirm. Verify "not connected" state.
   12. Return to the workspace. Verify "↑ GitHub" button is disabled with tooltip.
   ```
5. Run `docker compose down && docker compose up --build -d` and wait for all containers healthy.
6. Run `docker compose exec api uv run pytest tests/ -q --cov=services --cov-fail-under=80` — all tests pass, coverage ≥ 80%.
7. Run `docker compose exec frontend pnpm tsc` — no TypeScript errors.

**Acceptance Criteria:**
- CI references `test_github_integration.py`, `test_github_api_client.py`, and `test_task_parser.py`.
- `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are documented in `.env.example` and `CLAUDE.md`.
- The smoke test checklist covers the full connect → export → re-export → disconnect cycle.
- All backend tests pass inside Docker.
- `pnpm tsc` exits 0 inside Docker.

**Dependencies:** T-158

---

## Phase 14 — V1.3 Usefulness Improvements

> Source: `V1 spec.md` v1.3.0 §4.4.1, §4.8, §4.11, §5.1, §5.4, §7, §10, §11, §12; `Plan v1.md` §18. Harness: `harness/tests/backend/test_phase14_v13_usefulness_contract.py`, `harness/tests/frontend/phase14-v13-usefulness.contract.test.ts`. Phases 1–13 must be complete and green before starting this phase. Every UI element must align with the Modern Indica design system already established in `frontend/src/index.css` — saffron / lotus / slate palette, Plus Jakarta Sans, glassmorphism — no new visual identity.

> [!important] **Design Directive — applies to every frontend task in Phase 14 (T-163, T-165, T-167, T-169, T-171, T-172).**
>
> The earlier mistake on the Settings page was a screen that satisfied every CSS-class lint and still felt generic. Re-using tokens is the floor, not the ceiling. For each frontend task in this phase the implementing agent **must** do the following BEFORE writing a single line of TSX:
>
> 1. **Observe.** Open the closest existing screen in the running app and look at it. For modals → `Workspace.tsx` action modals + the post-Phase-13 Settings page. For chips → the existing stage-status chips and quality badges. For cards → the dashboard workspace cards. For full-page reads → the workspace editor. Note what feels considered (microcopy tone, spacing rhythm, where saffron is used vs. slate, how motion is used) and what feels phoned-in. Match the former, not the latter.
> 2. **Design before code.** Each frontend task carries a **Design Brief** subsection that names the *moment-of-use feeling* the component must produce. Read it. Sketch the component on paper or in a comment block at the top of the file. State the visual hierarchy in one sentence ("the URL is the hero; the toggle is secondary; the rotate control is hidden behind a disclosure"). State the one tiny delight the component contributes ("the copy button briefly says 'Copied ✓' in lotus pink"). Until you can answer these two questions in writing, do not start coding.
> 3. **Introspect, then build.** After the first pass renders in the browser, take a screenshot, look at it next to an existing screen, and ask: *does this look like it belongs in this app, or like it was added by someone who had never seen the app?* If the answer is the second, iterate before claiming the task is done. Visual consistency comes from FEELING, not from passing the CSS-class harness checks alone.
> 4. **Honour the design system.** Plus Jakarta Sans only. Saffron `--color-primary` for primary actions, lotus `--color-secondary` for confirmations / celebratory accents, slate `--color-tertiary` for neutral / secondary affordances. Glass card surfaces (`--color-glass-bg`, `--color-glass-border`). Spacing on the existing 4 / 8 / 12 / 16 / 24 / 32 rhythm. Motion uses the existing easing tokens, not random `transition: all`. No new colours, no new font families, no new shadow tokens — if you feel you need one, you do not.
> 5. **Microcopy is product.** Empty states, loading states, error states, button labels, modal titles — write them like a senior PM, not like an engineer leaving placeholder text. "Connecting…" beats "Loading…". "Linked as @alice" beats "Connected: true". "Generating PDF…" beats "Please wait."
>
> The acceptance criterion *"matches the Modern Indica visual identity"* is a human-judged criterion enforced by the maintainer at PR review, in addition to the automated harness checks. A task that passes every `pnpm vitest` assertion but reads as generic does not satisfy this directive and will be sent back.

---

### T-160: Alembic Migrations — Workspace V1.3 Fields and Templates Table

**Description:**
Two ordered migrations land the v1.3 schema. `0009_workspace_v1_3_fields.py` adds four new columns to `workspaces` (`template_slug`, `clarification_qa`, `public_share_slug`, `public_share_enabled`) plus a partial unique index on `public_share_slug`. `0010_templates.py` creates the system-owned `templates` table. Both are independently revertible. Nothing else in Phase 14 can begin until these tables/columns exist.

**Inputs:**
- `backend/migrations/versions/` (existing migration chain ends at `0008_stage_gap_patch_used.py`)
- `backend/models/workspace.py` (current shape)
- Plan §18.3 (T-USE-01 DDL)
- Harness: `harness/tests/backend/test_phase14_v13_usefulness_contract.py` — `test_phase14_workspace_v1_3_*`, `test_phase14_templates_migration_*`

**Outputs:**
- `backend/migrations/versions/0009_workspace_v1_3_fields.py`
- `backend/migrations/versions/0010_templates.py`

**Steps:**
1. Create `0009_workspace_v1_3_fields.py` with `revision = "0009"`, `down_revision = "0008"`.
2. In `upgrade()`:
   - `op.add_column("workspaces", sa.Column("template_slug", sa.Text(), nullable=True))`
   - `op.add_column("workspaces", sa.Column("clarification_qa", postgresql.JSONB, nullable=True))`
   - `op.add_column("workspaces", sa.Column("public_share_slug", sa.Text(), nullable=True))`
   - `op.add_column("workspaces", sa.Column("public_share_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))`
   - `op.create_unique_constraint("uq_workspaces_public_share_slug", "workspaces", ["public_share_slug"])`
   - Create a partial B-tree index for the hot lookup: `op.create_index("ix_workspaces_public_share_slug_enabled", "workspaces", ["public_share_slug"], postgresql_where=sa.text("public_share_enabled = true"))`
3. In `downgrade()`, drop the index, drop the unique constraint, drop the four columns in reverse order.
4. Create `0010_templates.py` with `revision = "0010"`, `down_revision = "0009"`.
5. In `upgrade()` create the `templates` table with all columns per the harness: `id` UUID PK, `slug` TEXT NOT NULL UNIQUE, `name` TEXT NOT NULL, `description` TEXT NOT NULL, `category` TEXT NOT NULL, `problem_statement` TEXT NOT NULL, `suggested_provider` TEXT, `suggested_model` TEXT, `sort_order` INTEGER NOT NULL DEFAULT 0, `active` BOOLEAN NOT NULL DEFAULT true, `created_at` TIMESTAMPTZ NOT NULL.
6. Create index `ix_templates_active_sort` on `(active, sort_order)`.
7. In `downgrade()`, drop the index then the table.
8. `uv run alembic upgrade head` — both apply cleanly.
9. `uv run alembic downgrade -2` — rolls back both cleanly.
10. `uv run alembic upgrade head` again to leave the schema in the upgraded state.

**Acceptance Criteria:**
- `uv run alembic upgrade head` exits 0; `\d+ workspaces` in psql shows the four new columns and the partial index.
- `\d+ templates` shows the table with all columns, the unique constraint on slug, and the `ix_templates_active_sort` index.
- `uv run alembic downgrade -2` cleanly removes everything Phase 14 added.
- `uv run pytest ../harness/tests/backend/test_phase14_v13_usefulness_contract.py::test_phase14_workspace_v1_3_fields_migration_exists ../harness/tests/backend/test_phase14_v13_usefulness_contract.py::test_phase14_workspace_v1_3_migration_adds_all_four_columns ../harness/tests/backend/test_phase14_v13_usefulness_contract.py::test_phase14_workspace_v1_3_migration_creates_unique_constraint_on_share_slug ../harness/tests/backend/test_phase14_v13_usefulness_contract.py::test_phase14_templates_migration_exists ../harness/tests/backend/test_phase14_v13_usefulness_contract.py::test_phase14_templates_migration_creates_templates_table` all pass.

**Dependencies:** T-159

---

### T-161: ORM Models and Pydantic Schemas for V1.3

**Description:**
Add the four new fields to the `Workspace` ORM model, create the `Template` model, and extend the workspace request/response schemas. The `Workspace` API response gains `coverage_summary` (derived on the fly — no DB column), `template_slug`, `public_share_slug`, and `public_share_enabled`. `CreateWorkspaceRequest` accepts an optional `template_slug` for provenance. `Template` is system-owned: no `user_id` FK.

**Inputs:**
- `backend/models/workspace.py` (extend)
- `backend/schemas/workspace.py` (extend)
- `backend/models/__init__.py` (re-exports)
- Migration `0009`, `0010` (T-160)
- Plan §10, §18.3
- Harness: `test_phase14_workspace_model_has_v1_3_fields`, `test_phase14_template_model_*`, `test_phase14_workspace_schema_exposes_v1_3_fields`

**Outputs:**
- `backend/models/template.py` (new)
- Updated `backend/models/workspace.py`
- Updated `backend/models/__init__.py`
- Updated `backend/schemas/workspace.py`

**Steps:**
1. In `backend/models/workspace.py` add four `Mapped` fields mirroring `0009`:
   - `template_slug: Mapped[str | None] = mapped_column(Text, nullable=True)`
   - `clarification_qa: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)`
   - `public_share_slug: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)`
   - `public_share_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))`
2. Create `backend/models/template.py`. The model must NOT reference `users.id` — Templates are system-owned in V1 (user-authored templates are V2). Fields exactly per the harness assertions; `__tablename__ = "templates"`.
3. Re-export `Template` from `backend/models/__init__.py` alongside the existing exports so Alembic autogenerate sees it on future revisions.
4. Extend `backend/schemas/workspace.py`:
   - `CoverageSummary` (Pydantic): `tests`, `covered`, `total`, `percent`, all `int`, all `Field(ge=0)`; `percent` `Field(ge=0, le=100)`.
   - `ClarificationQA` (Pydantic): `question: str`, `answer: str`, both max 1000.
   - `WorkspaceResponse` adds `template_slug: str | None`, `public_share_slug: str | None`, `public_share_enabled: bool = False`, `coverage_summary: CoverageSummary | None = None`.
   - `CreateWorkspaceRequest` adds `template_slug: str | None = None` validated against `^[a-z0-9][a-z0-9-]*$` and max 100 chars.
5. Run `uv run python -c "from models import Workspace, Template; from schemas.workspace import WorkspaceResponse, CreateWorkspaceRequest, CoverageSummary; print('ok')"`.

**Acceptance Criteria:**
- All imports resolve.
- `WorkspaceResponse.model_validate(workspace_orm_instance)` round-trips with the four new fields.
- `CreateWorkspaceRequest(template_slug="../etc/passwd", ...)` raises `ValidationError`.
- `Template.__tablename__ == "templates"` and the class has no `user_id` attribute.
- Harness assertions `test_phase14_workspace_model_has_v1_3_fields`, `test_phase14_template_model_*`, `test_phase14_workspace_schema_exposes_v1_3_fields`, `test_phase14_workspaces_post_accepts_template_slug`, `test_phase14_models_init_exports_template` all pass.

**Dependencies:** T-160

---

### T-162: Spec Clarification Service and Routes

**Description:**
Implement the lightweight Q&A step that runs before the first spec generation. A judge-model (Claude Haiku / GPT-4o Mini / Gemini Flash — the same selector used by `services/evals`) produces 3–5 targeted questions about the workspace's problem statement. The user's answers are persisted on `Workspace.clarification_qa` and injected into the existing spec prompt builder. The call is free (no credit deduction), best-effort (5-second timeout, returns 204 on failure), and uses the existing prompt-injection guard on every persisted answer.

**Inputs:**
- `backend/services/evals/online_eval.py` (reuse the judge-model selector)
- `backend/services/security/prompt_injection_guard.py`, `backend/services/security/sanitizer.py`
- `backend/services/llm/gateway.py`
- Existing prompt builder for the spec stage (find under `backend/prompts/spec*.py`)
- `backend/routers/workspace.py` (extend)
- `backend/middleware/rate_limit.py` (extend)
- Spec §4.4.1, §11; Plan §18.3 (T-USE-03)
- Harness: `test_phase14_spec_clarifier_*`, `test_phase14_clarify_*`, `test_phase14_spec_prompt_accepts_optional_clarification_qa`

**Outputs:**
- `backend/services/pipeline/spec_clarifier.py` (new)
- `backend/prompts/spec_clarification.py` (new — judge-model prompt that yields a strict JSON array of questions)
- Updated spec prompt builder (accept optional `clarification_qa`)
- Updated `backend/routers/workspace.py` (POST + PATCH `/workspaces/{id}/clarify`)
- Updated `backend/middleware/rate_limit.py` (new tier)

**Steps:**
1. Create `backend/prompts/spec_clarification.py`. The system prompt instructs the judge model to produce a strict JSON array `[{"question": "…", "why_it_matters": "…"}]` of 3–5 questions targeted at the problem statement. No prose, no markdown — JSON only. Include a constrained few-shot example.
2. Create `backend/services/pipeline/spec_clarifier.py` with two async functions:
   - `request_clarifying_questions(workspace, db, redis) -> list[dict]`: selects the judge model via the existing eval selector; calls the LLM gateway under `asyncio.timeout(5.0)`; parses the JSON response; on any failure returns `[]`. Caches the returned questions in Redis under `clarify_round:{workspace.id}` with TTL 900s so PATCH can validate that the answers match the questions just asked.
   - `persist_answers(workspace_id, answers, db, redis)`: validates each `answer.question` is in the cached round, runs each `answer.answer` through `prompt_injection_guard` and `sanitize_text`, persists the sanitised pairs to `Workspace.clarification_qa`.
3. Do NOT import `credit_service` or call any deduction API in this module — clarification is free.
4. Extend the spec prompt builder to accept an optional `clarification_qa` argument. When non-empty, render it as a `## Clarifications` markdown block appended to the problem statement.
5. In `backend/routers/workspace.py`:
   - `POST /workspaces/{id}/clarify`: auth + workspace ownership check; calls `request_clarifying_questions`; returns `{"questions": [...]}` or 204 No Content on empty.
   - `PATCH /workspaces/{id}/clarify`: body `{"answers": [{"question": str, "answer": str}]}`; calls `persist_answers`; returns 204.
6. Add to `backend/middleware/rate_limit.py` a new tier: 6 clarify calls per user per hour (`ratelimit:clarify:{user_id}`, 6, 3600s). Match the existing regex-based router used by other tiers.
7. Add unit tests under `backend/tests/test_spec_clarifier.py`: judge-model timeout returns `[]`; injection patterns in answers are stripped; questions unrelated to the cached round are rejected.

**Acceptance Criteria:**
- `POST /workspaces/{id}/clarify` returns a list of 3–5 questions when the judge model is reachable, or 204 when it times out.
- `PATCH /workspaces/{id}/clarify` rejects answers whose `question` is not in the cached Redis round (400).
- An injection string in an answer is sanitised before persistence (verify via DB inspection in the unit test).
- No credit ledger entry is created by either route.
- The spec prompt builder's signature accepts `clarification_qa` and the rendered prompt includes the `## Clarifications` block when supplied.
- All `test_phase14_spec_clarifier_*` and `test_phase14_clarify_*` harness tests pass.

**Dependencies:** T-161

---

### T-163: SpecClarificationModal Frontend Component

**Description:**
A four-state modal (loading → ready → submitting → bypassed) opens on first `Generate` click on the spec stage. The modal must visually match the existing Modern Indica modals (`.create-modal-*`, glassmorphism shell, saffron CTA). Both `Skip` and `Use answers` paths flow into the standard generate. The modal is silently bypassed on 204 from the backend so the user never sees a clarification error.

**Design Brief:**

The moment-of-use feeling: a senior PM has just sat down across the table and is asking three sharp questions before recommending an approach. *Not* a survey. *Not* a wizard. A short, considered conversation.

- The loading state is the surface that sells the feature. A generic spinner kills the mood — use a tasteful pulse on the modal body with a single line of microcopy ("Thinking of the right questions…") in slate so it reads as deliberate, not stalled. Do not show a percentage. Do not show three spinners.
- The question header is the hero — large, Plus Jakarta Sans, saffron-anchored. The `why_it_matters` line below each question (returned by the judge model) sits in slate at a smaller weight; it is the difference between "fill this in" and "here's why this matters." Render it.
- The `Skip` action lives at the LEFT of the footer as a quiet text-link in slate; the `Use answers` saffron CTA lives at the RIGHT. The visual asymmetry must make Skip available but never tempting.
- One delight: when the user types into the first textarea, the corresponding `why_it_matters` line fades to 60% opacity to reduce noise — a small acknowledgement that you've engaged.
- Empty 204 state: invisible. No flash, no toast, no "we tried" message. The user must not know the call happened.

Open the existing post-Phase-13 Settings page and the workspace `Generate` confirmation modal before writing this component. Match their tone exactly.

**Inputs:**
- `frontend/src/services/api.ts` (extend)
- `frontend/src/pages/Workspace.tsx` (mount + open trigger)
- `frontend/src/index.css` (add `.clarify-modal-*` rules in the same section as other modal rules)
- `frontend/src/store/stageStore.ts` (carry `clarificationQA` per workspace if not already present)
- Spec §4.4.1; Plan §18.3 (T-USE-04)
- Harness: `phase14 SpecClarificationModal`, `phase14 api.ts v1.3 exports`, `phase14 index.css design-system classes`

**Outputs:**
- `frontend/src/components/workspace/SpecClarificationModal.tsx` (new)
- Updated `frontend/src/services/api.ts` (new `requestClarification` + `persistClarification`)
- Updated `frontend/src/pages/Workspace.tsx`
- Updated `frontend/src/index.css`
- Updated `frontend/src/types/workspace.ts` (extend with `template_slug`, `clarification_qa`, `public_share_slug`, `public_share_enabled`, `coverage_summary` matching backend)

**Steps:**
1. In `api.ts`:
   - `requestClarification(workspaceId): Promise<{ questions: ClarifyQuestion[] } | null>` — returns `null` on 204.
   - `persistClarification(workspaceId, answers): Promise<void>`.
   - Add the `ClarifyQuestion`, `ClarifyAnswer` types.
2. Create `SpecClarificationModal.tsx`. On open: call `requestClarification`; if it returns `null`, immediately call `props.onProceed(answers=[])` so the parent dispatches the standard generate. Otherwise render the questions as labelled `<textarea>` fields (500-char max each) inside the existing `.create-modal-*` shell with a `.clarify-modal-question` class for the question block.
3. Footer actions: `Skip` (secondary button) calls `onProceed([])` immediately; `Use answers` (primary saffron CTA, disabled until at least one field is non-empty) calls `persistClarification` then `onProceed(answers)`. Both close the modal.
4. In `Workspace.tsx`: open the modal in the `requestGeneration` flow only when `activeStage.type === "spec" && activeStage.current_version === 0 && !workspace.clarification_qa`. Otherwise the existing flow runs unchanged.
5. In `index.css`, add `.clarify-modal`, `.clarify-modal-question`, `.clarify-modal-textarea`, `.clarify-modal-skip` rules. Reuse `--color-primary` for the CTA, `--color-glass-bg` for the shell. Do not introduce a new colour.
6. Extend `frontend/src/types/workspace.ts` to mirror the new `Workspace` response shape.
7. Run `pnpm tsc` and `pnpm test`.

**Acceptance Criteria:**
- Loading state shows a brief shimmer ("Thinking of the right questions…").
- A 204 response is invisible to the user — the modal closes immediately and the standard generate fires.
- `Skip` does not call `persistClarification`.
- The modal opens only on the FIRST spec generation per workspace; subsequent regenerates do not re-prompt.
- `pnpm tsc` exits 0; `pnpm test` passes.
- All `phase14 SpecClarificationModal` and relevant `phase14 api.ts v1.3 exports` harness tests pass.

**Dependencies:** T-162

---

### T-164: Task Priority + Estimate Enforcement

**Description:**
Update the TASKS prompt template so every emitted task carries a `Priority` line (`MUST` / `SHOULD` / `COULD`) and an `Estimate` line (`S` / `M` / `L` / `XL`), and the document starts with a `## Effort Summary` block. Extend the online eval to structurally validate Priority and Estimate per task, emitting `MISSING_PRIORITY` / `MISSING_ESTIMATE` issues into the existing `tasks_without_ref` JSONB field so the existing `TaskValidationPanel` surfaces them with no UI shape change.

**Inputs:**
- `backend/prompts/tasks*.py` (or `.md`) — locate and update
- `backend/services/evals/online_eval.py` (extend `_validate_task_references`)
- Spec §5.4; Plan §18.3 (T-USE-05)
- Harness: `test_phase14_tasks_prompt_mandates_priority_and_estimate_fields`, `test_phase14_tasks_prompt_includes_effort_summary_block`, `test_phase14_online_eval_validates_priority_and_estimate`

**Outputs:**
- Updated `backend/prompts/tasks*.py` (or `.md`)
- Updated `backend/services/evals/online_eval.py`

**Steps:**
1. Locate the tasks prompt template under `backend/prompts/`. Update the system prompt's "Required output shape" section to mandate `Priority:` and `Estimate:` lines per `## Task N — …` block. Constrain the enums explicitly.
2. Update the few-shot example to include Priority and Estimate lines.
3. Mandate a `## Effort Summary` block at the top of the document with: `Estimate range: ~Xw`, `Tasks: N total · X MUST · Y SHOULD · Z COULD`, `Sizes: AxXL · BxL · CxM · DxS`, `Minimum cut: Ship MUST-only → ~Yd`.
4. In `online_eval.py`, add a helper `_validate_task_fields(content) -> list[dict]` that for every `## Task N — …` block: parses out the `Priority:` and `Estimate:` lines (case-insensitive), validates enum membership, returns issues with shape `{ "task_number": int, "task_title": str, "reason": str, "gap_type": "MISSING_PRIORITY" | "MISSING_ESTIMATE" }`.
5. Merge the new issues into the existing `tasks_without_ref` list in `_validate_task_references` so the persisted `EvalResult.tasks_without_ref` carries both flavours of structural issue.
6. Add unit tests `backend/tests/test_online_eval_task_fields.py` covering: clean content (no issues), missing Priority on T-002, invalid enum value, missing Estimate.
7. Re-finalise a tasks stage in dev — verify the existing `TaskValidationPanel` surfaces the new gap types without any UI change.

**Acceptance Criteria:**
- Generating TASKS produces an `## Effort Summary` block at the top.
- Every emitted task carries Priority and Estimate lines with valid enum values.
- An LLM output that omits Priority on a task flags that task in the eval result with `gap_type: "MISSING_PRIORITY"`.
- Existing T-NNN harness-reference checks continue to flag missing references.
- The `tasks_without_ref` panel UI is unchanged.
- All `test_phase14_tasks_prompt_*` and `test_phase14_online_eval_validates_priority_and_estimate` harness tests pass.

**Dependencies:** T-161

---

### T-165: Effort Summary Frontend Chip

**Description:**
Parse the `## Effort Summary` block from finalised TASKS content and render it as a chip in the workspace header. The parser must return `null` on missing/malformed blocks so older content degrades gracefully (chip hidden, no error).

**Design Brief:**

The moment-of-use feeling: glancing at a fitness watch and seeing "8,247 steps." Small surface, high signal, zero ceremony. *Not* a banner. *Not* a billboard. A tiny, confident summary.

- The chip is **at most one line**, tight. The reading order is: estimate → task count → MUST count. `~3 weeks · 15 tasks · 6 MUST` — three glyphs, three middle-dots, nothing else. Resist the urge to add icons or pills inside the chip.
- Colour: lotus `--color-secondary` tint at the chip background (a celebration colour — finishing the pipeline is a win), saffron for the estimate number specifically because that's the headline value the user cares about. Slate for the rest. No borders.
- Position: in the workspace header, after the stage indicator strip, before the export buttons. It belongs in the *summary* zone, not the *action* zone.
- One delight: on hover, the chip tooltip reveals the calibration ("S = 0.5–1d · M = 1–3d · L = 3–7d · XL = 7d+ · informational only") — proactive disclosure that the estimate is not a contract. This is product-level honesty disguised as a tooltip.
- Hidden when null. No skeleton, no "—" placeholder.

Look at the existing stage-status chips and the quality badge before writing this. The chip must read as a *sibling* of those, not a louder cousin.

**Inputs:**
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/utils/` (new helper)
- `frontend/src/index.css`
- Plan §18.3 (T-USE-06)
- Harness: `phase14 effort summary`

**Outputs:**
- `frontend/src/utils/tasksParser.ts` (new)
- Updated `frontend/src/pages/Workspace.tsx`
- Updated `frontend/src/index.css`

**Steps:**
1. Create `frontend/src/utils/tasksParser.ts` with `parseEffortSummary(content: string): EffortSummary | null`. The function looks for `## Effort Summary`, extracts the four bullet lines (estimate range, tasks count, sizes, minimum cut), and returns an `EffortSummary` object. On any parse failure return `null`.
2. Add unit tests `frontend/src/utils/tasksParser.test.ts`: clean content returns the structure; missing block returns `null`; malformed lines return `null` without throwing.
3. In `Workspace.tsx`, when the active stage is TASKS and `parseEffortSummary(stage.content)` is non-null, render the chip in the header strip next to the stage indicators.
4. Add `.effort-summary-chip` rules in `index.css`. Reuse the existing chip styling token set (radius, padding, glass background). Use `--color-secondary` (lotus) tint to differentiate from the saffron primary actions and the slate coverage chip.

**Acceptance Criteria:**
- The chip appears in the workspace header when TASKS content has the block; hides when absent.
- The chip text matches the spec's example layout: `~3 weeks · 15 tasks · 6 MUST`.
- The parser never throws for any input.
- `pnpm test` passes including the new unit tests.
- All `phase14 effort summary` harness tests pass.

**Dependencies:** T-164

---

### T-166: PDF Export Backend (WeasyPrint)

**Description:**
Render finalised SPEC.md, PLAN.md, and TASKS.md into a single branded PDF using WeasyPrint (no headless browser). The renderer is configured with a no-network URL fetcher so a malicious `<img src>` cannot exfiltrate. The harness directory is intentionally excluded — PDFs are for human audiences. New rate-limit tier: 10 exports/user/hour.

**Inputs:**
- `backend/pyproject.toml` (add `weasyprint`)
- `backend/services/pipeline/export_service.py` (reuse stage-content fetch helpers)
- `backend/templates/` (new directory if not present)
- `backend/routers/workspace.py` (extend)
- `backend/middleware/rate_limit.py` (extend)
- Spec §4.8, §12; Plan §18.3 (T-USE-07)
- Harness: `test_phase14_pdf_export_*`

**Outputs:**
- `backend/services/pipeline/pdf_export_service.py` (new)
- `backend/templates/export.html.j2` (new)
- Updated `backend/pyproject.toml`
- Updated `backend/routers/workspace.py`
- Updated `backend/middleware/rate_limit.py`

**Steps:**
1. Add `weasyprint` to `pyproject.toml` and run `uv sync`. The Railway Python base image already includes `cairo` / `pango`; no Dockerfile change needed for production. Document this in the file's import block as a comment so the dependency is visible.
2. Create `backend/templates/export.html.j2` (Jinja2). Layout: cover page (workspace name, provider used, harness coverage figure, generation date), table of contents, one section per stage. Inline all CSS — no `<link>` to external stylesheets. Use Pygments to syntax-highlight fenced code blocks server-side at render time.
3. Create `pdf_export_service.py` with `async def render(workspace_id, db) -> bytes`:
   - Reuse the existing content-fetch helpers from `export_service` to load SPEC, PLAN, TASKS content; do not include the harness directory.
   - Render the Jinja template into HTML.
   - Pass that HTML into `weasyprint.HTML(string=html_text, url_fetcher=NO_NETWORK_FETCHER)` and `.write_pdf()` it to a `BytesIO`.
   - Define `NO_NETWORK_FETCHER` as a module-level function that raises for any non-data-URL fetch — name it explicitly so the harness can find the string `no_network`.
4. Add `POST /workspaces/{id}/export/pdf` in `routers/workspace.py`. Stream the bytes back via `StreamingResponse(media_type="application/pdf")` with `Content-Disposition: attachment; filename="specforge-<slug>.pdf"`. Require all four stages finalised (reuse the existing `ExportNotReadyError` from Phase 13 → 409 mapping).
5. Add to `middleware/rate_limit.py` a new tier: 10 PDF exports/user/hour, key `ratelimit:pdf_export:{user_id}`, window 3600s.
6. Add unit tests `backend/tests/test_pdf_export_service.py`: render produces non-empty bytes starting with `%PDF-`; no-network fetcher raises on `https://` URLs.

**Acceptance Criteria:**
- `curl -X POST .../export/pdf` returns a `%PDF-1.7` (or similar) byte stream of >5 KB.
- The PDF cover page shows the workspace name and the harness coverage figure.
- The harness directory is NOT present in the rendered output.
- A malicious workspace with an `<img src="https://evil/exfil">` injected via spec content does NOT cause an outbound HTTP call (the fetcher raises).
- Rate limit fires on the 11th call within an hour.
- All `test_phase14_pdf_export_*` harness tests pass.

**Dependencies:** T-161

---

### T-167: PDF Export Frontend Button

**Description:**
Add `[📄 Export PDF]` as a third button in the workspace header alongside ZIP and GitHub. Click → call `exportWorkspacePdf` → receive a blob → trigger a browser download. Visually match the existing tertiary buttons; do not introduce a new colour.

**Design Brief:**

The moment-of-use feeling: clicking "Export PDF" in Figma. Quiet competence. No ceremony, no progress bar, just a result.

- The PDF button is **a sibling** of the existing ZIP and GitHub buttons — same height, same radius, same horizontal padding, same slate `--color-tertiary` tint family. Visually they should read as a row of three peers, not "the two real exports and a new one." Order from left to right: ZIP · PDF · GitHub · Share. Source-locally → publish-globally.
- The icon: a single PDF glyph as the leading element, not a saffron primary CTA. Saffron in this row is reserved for finalise / generate.
- In-flight state: replace the label with "Generating PDF…" *in place* (no spinner blob). Disable the button. Keep the layout stable so the row does not jitter. A 1-second render that causes a 1-pixel shift is a regression.
- Success: the download starts. No toast, no modal, no "PDF created" banner. The browser's download UI is sufficient — *layering our own confirmation on top is noise.*
- Failure: a single inline error chip below the row in lotus tint with one line of microcopy ("Couldn't generate PDF. Try again?") and a retry affordance. Never a full-screen error.
- Disabled state (when any stage is unfinalised): tooltip in slate explaining which stage blocks export — "Finalise HARNESS to enable PDF export." Specific, not generic.

Open the existing post-Phase-13 ZIP and GitHub buttons before writing this. The PDF button must read as if the same designer drew all three.

**Inputs:**
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/index.css`
- Plan §18.3 (T-USE-08)
- Harness: `phase14 PDF export button`

**Outputs:**
- `frontend/src/components/workspace/ExportPDFButton.tsx` (new)
- Updated `frontend/src/services/api.ts`
- Updated `frontend/src/pages/Workspace.tsx`
- Updated `frontend/src/index.css`

**Steps:**
1. In `api.ts`, add `exportWorkspacePdf(workspaceId): Promise<Blob>`. Use `axios.post(..., { responseType: "blob" })`.
2. Create `ExportPDFButton.tsx`. On click: call the API, create an object URL from the returned blob, programmatically click a hidden anchor with `download="specforge-<workspaceName>.pdf"`, revoke the URL afterwards.
3. While the request is in flight, swap the label to "Generating PDF…" and disable the button.
4. Mount the button in `Workspace.tsx` between the ZIP button and the GitHub button so the order reads: ZIP · PDF · GitHub · Share.
5. Add `.workspace-pdf-btn` CSS. Reuse the tertiary slate tint set already used by `.workspace-github-btn` — both are secondary outputs vs. the saffron primary actions; visually grouping them is intentional.
6. `pnpm tsc` + `pnpm test`.

**Acceptance Criteria:**
- Clicking the button downloads a file matching `specforge-*.pdf` whose first bytes are `%PDF-`.
- The button is disabled with a tooltip if any of the four stages is not finalised.
- Visual treatment matches the existing tertiary button family — no new colour added.
- All `phase14 PDF export button` harness tests pass.

**Dependencies:** T-166

---

### T-168: Public Share Backend

**Description:**
Implement `enable` / `disable` / `rotate` lifecycle for a per-workspace public slug, plus the unauthenticated `GET /public/{slug}` endpoint. The slug uses `secrets.choice` against a 31-character alphabet that excludes ambiguous characters (`0/o/1/l/i`). The public endpoint builds its response from an explicit allow-list helper — never from a raw `Workspace` model dump — so future ORM fields cannot accidentally leak.

**Inputs:**
- Existing `Workspace` ORM + schema (T-161)
- `backend/routers/` (existing pattern)
- `backend/services/` (new sub-package `sharing/`)
- Spec §4.8, §11, §12; Plan §18.3, §18.4 (T-USE-09)
- Harness: `test_phase14_public_share_*`, `test_phase14_public_router_*`, `test_phase14_share_routes_declared_in_workspace_router`, `test_phase14_public_view_rate_limit_tier_declared`

**Outputs:**
- `backend/services/sharing/__init__.py` (new)
- `backend/services/sharing/public_share_service.py` (new)
- `backend/routers/public.py` (new, unauthenticated)
- Updated `backend/routers/workspace.py` (share lifecycle endpoints)
- Updated `backend/main.py` (register `public` router)
- Updated `backend/middleware/rate_limit.py` (public-view + share-toggle tiers)
- Updated `backend/schemas/workspace.py` (`PublicWorkspaceResponse` model)

**Steps:**
1. Create `services/sharing/public_share_service.py`:
   - `ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"` (31 chars; comment that this excludes `0/o/1/l/i`).
   - `SLUG_LEN = 6`.
   - `_generate_slug() -> str` using `secrets.choice` in a loop; retry up to 3 times on `IntegrityError`.
   - `async def enable(workspace_id, db) -> str`: rejects with `WorkspaceNotFinalisedError` if any of the four stages is not `finalised`. Idempotent: if a slug already exists, only flip `public_share_enabled = True` and return the existing slug.
   - `async def disable(workspace_id, db) -> None`: flips `public_share_enabled = False`; preserves the slug so re-enable reuses the same URL.
   - `async def rotate(workspace_id, db) -> str`: generates a new slug, sets `public_share_enabled = True`. Old slug is invalidated.
   - `async def build_public_view(slug, db) -> PublicWorkspaceResponse | None`: the ONLY function that constructs the public response. Builds the response as an explicit dict with the allow-list fields (`name`, `provider_label`, `stages: [{type, content}, ...]`, `coverage_summary`, `eval_summary`, `shared_at`). Returns `None` if slug unknown or sharing disabled.
2. Define `PublicWorkspaceResponse` Pydantic model in `schemas/workspace.py` matching `harness/schemas/public-workspace.schema.json` exactly (allow-list — `model_config = ConfigDict(extra="forbid")`).
3. Create `backend/routers/public.py`:
   - `GET /public/{slug}`: no auth dependency; calls `build_public_view`; 404 if `None`; sets headers `X-Robots-Tag: noindex, nofollow` and `Cache-Control: public, max-age=60, stale-while-revalidate=600`.
   - Computes an `ETag` from `shared_at`; honours `If-None-Match` with 304.
4. Register the router in `backend/main.py` with prefix `/public` and explicitly mark it as exempt from the auth middleware in the documented exemption list.
5. Add share lifecycle endpoints to `routers/workspace.py`:
   - `POST /workspaces/{id}/share` → `enable`, returns `{slug, url, enabled: true}`.
   - `DELETE /workspaces/{id}/share` → `disable`, returns 204.
   - `POST /workspaces/{id}/share/rotate` → `rotate`, returns `{slug, url, enabled: true}`.
   - Map `WorkspaceNotFinalisedError` → 409 with `{"error": "workspace_not_finalised"}`.
6. Add to `middleware/rate_limit.py` two tiers: `public_view` (per-IP, 120/min) and `share_toggle` (per-user, 20/hour).
7. Unit tests `backend/tests/test_public_share_service.py`: slug alphabet has no ambiguous chars; `_generate_slug` retries on collision; `enable` rejects non-finalised workspaces; `build_public_view` returns `None` for disabled rows; allow-list shape never leaks `user_id`, `email`, `credit balance`, `clarification_qa`.
8. Frontend serving of `/p/:slug` (the React route) is T-169 — backend stops at `/public/{slug}`.

**Acceptance Criteria:**
- `secrets` is used for slug generation; `random` is not imported.
- Enabling sharing on a workspace with any non-finalised stage returns 409.
- The slug returned never contains `0`, `o`, `1`, `l`, or `i`.
- `GET /public/<wrong>` returns 404; `GET /public/<disabled>` returns 404.
- `GET /public/<valid>` response body keys are exactly: `name`, `provider_label`, `stages`, `coverage_summary`, `eval_summary`, `shared_at` — no extras (Pydantic `extra="forbid"`).
- Response carries `X-Robots-Tag: noindex, nofollow`.
- Rate limit fires on the 121st `/public/{slug}` request per IP per minute.
- All `test_phase14_public_share_*`, `test_phase14_public_router_*` harness tests pass.

**Dependencies:** T-161

---

### T-169: Public Share Frontend (Modal + /p/:slug Read-Only View)

**Description:**
Two surfaces: a workspace modal to enable/disable/rotate the link, and a brand-new top-level read-only route at `/p/:slug` that renders the finalised spec in the Modern Indica design without authenticated state. The route must be registered OUTSIDE the auth guard, must inject `<meta name="robots" content="noindex, nofollow" />`, and must not import any authenticated store (no `userStore`, no `creditsBalance`).

**Design Brief:**

This task ships TWO surfaces with very different jobs. Design them separately.

**Surface A — SharePublicLinkModal (workspace-internal).** The moment-of-use feeling: handing someone a printed proof of work. Small ceremony, real pride. *Not* a settings toggle.

- The URL is the hero of the modal. Render it large, in a single line, in monospaced weight (or a clear sans like Plus Jakarta with tabular nums), inside a glass-tinted pill that itself looks click-tappable. Place a saffron `Copy` button immediately to the right of the URL with no gap between them — they read as one component.
- On copy: the button briefly transitions to "Copied ✓" in lotus pink for ~1.2s, then back. This is the one delight in this surface. Do not show a toast.
- The toggle below the URL pill is a quiet horizontal row of two text-radio affordances ("Public" / "Disabled"), not a switch. Reading "Public" should feel descriptive, not aggressive.
- The rotate control is intentionally behind a "More" disclosure (a `<details>` or equivalent) and renders in slate at small weight. Rotating a slug is a "yes I'm sure" gesture; the design must discourage accidental clicks. Include one line of microcopy: "Rotating invalidates the current link. Anyone holding it will see a 404."
- The footer microcopy is the privacy statement quoted exactly from spec §4.8 ("Anyone with the link can view your finalised SPEC.md, PLAN.md, HARNESS coverage, and TASKS.md. They cannot see your credit balance, billing, account email, other workspaces, or any draft / pre-finalisation content."). Sit it in slate at small weight. This is the kind of small honesty that earns trust on a public-share feature.

**Surface B — PublicWorkspaceView at `/p/:slug` (the marketing-grade page).** The moment-of-use feeling: opening a Notion shared doc made by someone who clearly cares. This is **the most-seen surface for non-customers** — the page that decides whether word-of-mouth converts. Treat it accordingly.

- A small but real cover band at the top: workspace name in Plus Jakarta Display weight, "Generated with SpecForge" in slate as a quiet attribution, and the harness coverage chip (from T-172) immediately under it as social proof. No saffron flood — the cover is restrained, the *content below* is where the visitor goes.
- Stage-tab navigation (Spec · Plan · Harness · Tasks) styled as the existing stage indicator strip, not as standard tabs. Continuity with the in-app experience is the point.
- The four stages render in a read-only `StageEditor` (existing component, `readOnly` prop). Code blocks get the same syntax theme as the in-app editor — do not invent a new one. The harness stage shows the coverage detail, not the full directory tree.
- A subtle footer with one CTA: "Made with SpecForge — turn your idea into a spec, plan, harness, and ready-to-ship tasks in 10 minutes →" linking to the marketing site. Lotus accent on the link only. This is the **one** marketing moment on the page and it must land tastefully.
- Loading skeleton uses the existing skeleton component, *not* a new one. A 404 (bad/disabled slug) shows the existing 404 page with one extra line: "This shared spec may have been disabled by its author."
- This page is responsive — it must read on mobile. The in-app workspace is desktop-first; the public view is not. (Out-of-scope items still apply: complex interactions remain desktop-only, but reading flow on phone must work.)
- Performance budget: cover paints in under 800ms on a cold cache. The Vite chunk for this route is lazy-loaded to keep an unauthenticated first paint cheap.

Open three references before writing PublicWorkspaceView: (1) a Notion shared doc, (2) a Linear shared issue, (3) the existing in-app workspace editor. Borrow restraint from the first two, identity from the third.

**Inputs:**
- `frontend/src/App.tsx` (register `/p/:slug` route outside the auth guard)
- `frontend/src/pages/Workspace.tsx` (header button)
- `frontend/src/services/api.ts`
- `frontend/src/index.css`
- `frontend/public/robots.txt` (add Disallow `/p/`)
- Spec §4.8; Plan §18.3, §18.4 (T-USE-10)
- Harness: `phase14 public share frontend`

**Outputs:**
- `frontend/src/components/workspace/SharePublicLinkModal.tsx` (new)
- `frontend/src/pages/PublicWorkspaceView.tsx` (new)
- Updated `frontend/src/App.tsx`
- Updated `frontend/src/services/api.ts`
- Updated `frontend/src/pages/Workspace.tsx`
- Updated `frontend/src/index.css`
- Updated `frontend/public/robots.txt`
- `frontend/src/types/publicShare.ts` (new — `PublicWorkspaceResponse`)

**Steps:**
1. In `api.ts`, add `enablePublicShare(workspaceId)`, `disablePublicShare(workspaceId)`, `rotatePublicShare(workspaceId)`, `getPublicWorkspace(slug)`. `getPublicWorkspace` catches 404 and returns `null`.
2. Define `PublicWorkspaceResponse` TS interface in `frontend/src/types/publicShare.ts` matching the backend Pydantic shape exactly.
3. Create `SharePublicLinkModal.tsx`. Renders three states: `disabled` (Enable CTA), `enabled` (URL + copy button + Disable + Rotate-behind-disclosure), `loading`. Reuse the existing `.create-modal-*` shell. The URL copy uses `navigator.clipboard.writeText`. The rotate control is intentionally behind a disclosure to prevent accidental clicks.
4. Create `PublicWorkspaceView.tsx`. On mount: `getPublicWorkspace(slug)`. While loading: skeleton. On 404: render the 404 page (reuse existing). On success: render the four finalised stages in a read-only `StageEditor` (set `readOnly` prop), the harness coverage chip, and a footer "Made with SpecForge → specforge.app". Inject `<meta name="robots" content="noindex, nofollow" />` via `react-helmet-async` (already in the dependency tree) or via direct `document.head` manipulation in a `useEffect`.
5. Do NOT import `userStore`, `stageStore`, `creditsBalance`, or any other authenticated state. The harness will fail the test if any of these strings appear in the file.
6. In `App.tsx`, register `/p/:slug` as a top-level `<Route>` OUTSIDE the existing `<RequireAuth>` wrapper. Use `React.lazy` for `PublicWorkspaceView` so unauthenticated visitors do not pay the full bundle cost.
7. Add a `Share` button to the workspace header (after the PDF button). Click opens the modal.
8. Update `frontend/public/robots.txt` to add `Disallow: /p/` under `User-agent: *`. If the file does not exist, create it with `User-agent: *\nDisallow: /p/`.
9. Add `.public-view-*` CSS rules: cover, ToC, footer, coverage chip; reuse existing typography and palette.
10. `pnpm tsc`, `pnpm test`, and a manual test: enable share, open the URL in an incognito window, verify the page renders without an auth redirect and view-source shows the noindex meta.

**Acceptance Criteria:**
- `/p/<valid-slug>` in an incognito tab renders the finalised spec without redirecting to `/login`.
- View-source shows `<meta name="robots" content="noindex, nofollow">`.
- The file `frontend/src/pages/PublicWorkspaceView.tsx` does not contain the strings `userStore`, `stageStore`, `creditsBalance`, or `useUserStore`.
- `frontend/public/robots.txt` contains `Disallow: /p/`.
- The copy-link button copies the canonical URL to the clipboard.
- Rotate behind disclosure prevents single-click slug rotation.
- `pnpm tsc` exits 0.
- All `phase14 public share frontend` harness tests pass.

**Dependencies:** T-168

---

### T-170: Starter Templates Backend (Model, Seed, Endpoint)

**Description:**
The `templates` table is already created in T-160 and the model in T-161. This task adds the unauthenticated `GET /templates` endpoint, the idempotent seed script with 6–10 hand-tuned starter templates, and the Docker entrypoint hook that runs the seed after `alembic upgrade head` on every container start.

**Inputs:**
- `backend/models/template.py` (T-161)
- `backend/main.py` (extend)
- `backend/routers/` (new file)
- `backend/scripts/` (new directory if not present)
- `backend/Dockerfile` or entrypoint script
- Spec §4.11, §11; Plan §18.3 (T-USE-11)
- Harness: `test_phase14_templates_router_*`, `test_phase14_templates_seed_script_*`, `test_phase14_templates_endpoint_is_unauthenticated`

**Outputs:**
- `backend/routers/templates.py` (new, unauthenticated)
- `backend/scripts/seed_templates.py` (new, idempotent)
- Updated `backend/main.py`
- Updated `backend/Dockerfile` / entrypoint
- `backend/schemas/template.py` (new — `TemplateRead` matching `harness/schemas/template.schema.json`)

**Steps:**
1. Create `backend/schemas/template.py` with `TemplateRead` Pydantic model mirroring the harness schema. `category` is a `Literal["auth", "payments", "content", "realtime", "agent", "tooling"]`.
2. Create `backend/routers/templates.py`:
   - `GET /templates`: no auth dependency; queries `Template` filtered by `active == True`, ordered by `sort_order`, then `name`. Returns `list[TemplateRead]`.
3. Register the router in `main.py` with prefix `/templates` and add to the auth-exempt list.
4. Create `backend/scripts/seed_templates.py`. It accepts an async session (or constructs one from the app's `DATABASE_URL`) and upserts 6–10 templates via `INSERT ... ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name, description=..., problem_statement=..., suggested_provider=..., suggested_model=..., sort_order=..., active=true`. Required slugs: `stripe-like-checkout`, `linear-like-ticketing`, `slack-bot`, `ai-chat-assistant`, `internal-admin-panel`, `rest-api-server`, `realtime-presence`, `agent-harness`. Each must have a problem_statement of at least 200 chars that produces a high-quality spec on first generation.
5. Mark the script idempotent by ensuring re-runs do not duplicate rows and do not bump `created_at` on already-existing rows.
6. Update the Docker entrypoint to invoke `uv run python scripts/seed_templates.py` AFTER `alembic upgrade head`, BEFORE `uvicorn`. The script must exit 0 even when called against an empty database (the migration runs first so the table exists).
7. Add `backend/tests/test_seed_templates.py`: run the script twice in a transaction → expect the same row count both times.

**Acceptance Criteria:**
- `GET /templates` returns at least 6 templates ordered by `sort_order` ascending.
- An unauthenticated curl to `GET /templates` returns 200 (no 401).
- Running the seed script twice does not duplicate any row.
- `docker compose up --build` brings the API up with the templates already seeded.
- Disabling a template via SQL (`UPDATE templates SET active = false WHERE slug = '…'`) causes it to disappear from the `GET /templates` response but does not break workspaces whose `Workspace.template_slug` references it.
- All `test_phase14_templates_*` harness tests pass.

**Dependencies:** T-161

---

### T-171: Starter Templates Frontend (Strip + Workspace Form Prefill)

**Description:**
Render the template gallery as a horizontal scrolling strip on the Dashboard above the workspace grid AND above the workspace creation form. Clicking a card pre-fills `name`, `problem_statement`, and the suggested provider/model into the form. The chosen `template_slug` is recorded on the workspace for provenance via `POST /workspaces`.

**Design Brief:**

The moment-of-use feeling: a new user just landed on the Dashboard with nothing in it. They've been staring at a blank "what's your idea?" textarea for ten seconds. The templates strip should feel like a friend pulling out a notebook and saying "here, try one of these."

- Cards are **pickable**, not listable. Each card has gentle elevation (existing glass card token), a subtle hover lift (4–6px translate-Y, existing easing token), and the cursor changes to pointer. A row of dead-looking rectangles is the failure state.
- Card content, top to bottom: a small category badge in slate (e.g. *payments*, *tooling*), the template name in Plus Jakarta Display weight, a one-line description in slate, and a quiet "Use this →" affordance pinned to the bottom right. Saffron is reserved for the action affordance, not the card surface.
- Strip layout: horizontal scroll with momentum on iOS. Show ~3.5 cards on a 1280px viewport so the half-card on the right is a visual *invitation to scroll*. Snap scrolling, no scrollbar visible.
- Cold-start dominance: when the user's workspace list is empty, the strip is the **dominant element** on the Dashboard — give it more vertical room, a small section heading ("Start from a template"), and a quiet sub-line ("Hand-tuned starting points — pick one, then edit before generating."). When the user has workspaces, the strip is more modest — still present, still scrollable, but compressed in height.
- Prefill UX: clicking a card scrolls smoothly to the workspace form, fills the fields, and renders a small chip below the form: **"Started from *Stripe-like checkout* · clear"** in lotus tint with the *clear* affordance underlined. The chip is the user's signal that the prefill is editable and removable. Without this chip the prefill feels magical-but-locked; with it the user feels in control.
- One delight: the moment a card is clicked, the card flashes its accent border in lotus for ~400ms before the scroll-to-form animation begins. A small acknowledgement that the click registered. Do not over-animate.
- No empty state for the strip itself — if the API returns zero templates (shouldn't happen post-seed), hide the strip entirely. A "no templates available" message is worse than no strip.

Open the existing dashboard workspace cards before writing this. The template card should read as a *cousin* — same visual family, but with the energy of "ready to use" rather than "previously created."

**Inputs:**
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/components/dashboard/` (existing creation modal or inline form)
- `frontend/src/services/api.ts`
- `frontend/src/index.css`
- Spec §4.2, §4.10, §4.11; Plan §18.3 (T-USE-12)
- Harness: `phase14 starter templates`

**Outputs:**
- `frontend/src/components/templates/TemplatesStrip.tsx` (new)
- `frontend/src/components/templates/TemplateCard.tsx` (new)
- `frontend/src/types/template.ts` (new — `Template` interface)
- Updated `frontend/src/services/api.ts` (`getTemplates`; extend `createWorkspace` body to accept `template_slug`)
- Updated `frontend/src/pages/Dashboard.tsx`
- Updated workspace creation form / modal
- Updated `frontend/src/index.css`

**Steps:**
1. Define `Template` and `TemplateCategory` TS types matching the backend.
2. Add `getTemplates(): Promise<Template[]>` in `api.ts`. Extend `createWorkspace` to accept an optional `template_slug` field.
3. Create `TemplateCard.tsx` and `TemplatesStrip.tsx`. The strip horizontally scrolls (overflow-x: auto with momentum on iOS). Each card shows: name, one-line description, a small category badge, and a subtle "Use →" affordance. Cards use the existing glass card visual token (`--color-glass-bg`, `--color-glass-border`).
4. Cache the fetched template list in a module-level variable for the session so re-renders don't re-fetch.
5. In `Dashboard.tsx`, mount `TemplatesStrip` above the workspace grid. When the user's workspace list is empty, the strip is the dominant element (use stacked layout); when the list has content, the strip is collapsed/optional but still present.
6. In the workspace creation form/modal, mount the strip above the name field. Clicking a card pre-fills name + problem statement + provider + model. Render a small chip below the form showing "Started from <template name> · clear" so the user can opt out.
7. When the user submits, pass the captured `template_slug` to `createWorkspace`.
8. Add CSS rules `.templates-strip`, `.template-card`, `.template-card-badge`, `.template-card-cta`. No new colours.
9. `pnpm tsc` and `pnpm test`.

**Acceptance Criteria:**
- Dashboard with zero workspaces shows the TemplatesStrip prominently.
- Clicking a card pre-fills the workspace form; clearing the chip resets the fields.
- A workspace created from a template has `template_slug` recorded in the DB (verify in psql).
- The strip is horizontally scrollable on narrow viewports.
- Visual treatment matches the existing card family — no new palette entries.
- All `phase14 starter templates` harness tests pass.

**Dependencies:** T-170

---

### T-172: Harness Coverage Surfacing

**Description:**
The harness coverage figure already exists on `EvalResult.coverage_percent` for the harness stage. This task surfaces it as a `coverage_summary` field on the workspace API response (derived on the fly — no DB column) and renders it as a `.harness-coverage-chip` in three places: the workspace header, the dashboard workspace card, and the public share view. Harness is SpecForge's main differentiator — making it visible at a glance is intentional positioning.

**Design Brief:**

The moment-of-use feeling: glancing at a CI badge that says "build passing" — small, trustworthy, glanceable. A *trust signal*, not a metric. This chip carries product-level meaning: "the spec is backed by tests."

- The chip is a single horizontal element with three parts: a tiny progress bar on the left (filling toward 100%), the count in tabular numerals ("18 / 21 reqs"), and a quiet trailing word ("covered"). Use Plus Jakarta Sans tabular nums so the numbers don't jitter when they update post-finalise.
- The progress bar is THE visual hook. ~32px wide, ~4px tall, slate `--color-tertiary` base, saffron `--color-primary` fill. At 100% the fill briefly pulses once (~600ms, existing easing token) to reward completion. Below 80% the fill stays saffron but the chip text colour shifts to a warm warning tone (do not invent a new colour — use a slightly-darker saffron tint already in the token set, or the existing eval-warning treatment). Below 60% there is no special treatment beyond what the eval panel already shows; the chip is informational, not alarmist.
- Identical visual treatment across all three placements (workspace header / dashboard card / public view). The component is one component used three times — never let it diverge per surface. This is the contract that makes the chip read as a *product element* rather than three coincidental UI bits.
- Hidden when null. No "harness not finalised yet" placeholder. The harness coverage chip is a *result* signal, not a *progress* signal.
- Hover tooltip in slate microcopy: "24 tests cover 18 of 21 spec requirements. SpecForge generates the tests; you ship them." That last clause is positioning — it tells the visitor what's actually special. Write it well.
- On the public view specifically (T-169 Surface B), this chip is the **single most important signal** that the shared spec is real work. Place it under the cover band with a touch more breathing room than on the in-app surfaces.

Look at the existing quality badge component before writing this. The coverage chip is a sibling of the quality badge, not a replacement.

**Inputs:**
- `backend/routers/workspace.py` (extend response)
- `backend/schemas/workspace.py` (already extended in T-161)
- `frontend/src/pages/Workspace.tsx`, `Dashboard.tsx`, `PublicWorkspaceView.tsx`
- `frontend/src/components/dashboard/WorkspaceCard.tsx` (if present)
- `frontend/src/index.css`
- Spec §7; Plan §18.3 (T-USE-13)
- Harness: `test_phase14_workspace_response_includes_coverage_summary`, `test_phase14_workspace_endpoint_computes_coverage_summary_from_eval`, `phase14 harness coverage chip`

**Outputs:**
- Updated `backend/routers/workspace.py`
- Updated `backend/services/pipeline/stage_manager.py` (or wherever workspace assembly lives) — derive `coverage_summary`
- Updated `frontend/src/pages/Workspace.tsx`
- Updated `frontend/src/pages/Dashboard.tsx` / `WorkspaceCard.tsx`
- Updated `frontend/src/pages/PublicWorkspaceView.tsx`
- Updated `frontend/src/index.css`

**Steps:**
1. In the workspace response builder, after loading the workspace's stages, find the harness stage and its latest `EvalResult`. Derive `coverage_summary` as `{tests: <count of tests in harness>, covered: <reqs covered>, total: <reqs total>, percent: <coverage_percent>}`. If the harness stage is missing or has no eval, return `None`. Persist nothing — purely computed.
2. Wire the derived value into `WorkspaceResponse.coverage_summary`.
3. Wire the same derivation into the public share endpoint (T-168) so `PublicWorkspaceResponse.coverage_summary` carries the figure.
4. Frontend: add a `<HarnessCoverageChip />` component (or inline JSX) that takes `coverage_summary` and renders the chip. If `null`, render nothing.
5. Mount the chip in:
   - `Workspace.tsx` header, after the stage indicator strip
   - The Dashboard `WorkspaceCard` (replacing or supplementing the current "stages finalised" pip row)
   - `PublicWorkspaceView.tsx` near the workspace title
6. Add `.harness-coverage-chip` and a `.harness-coverage-chip-bar` CSS rule (a tiny progress bar inside the chip showing the percent visually). Use `--color-tertiary` for the chip base; the progress bar fills with `--color-primary` (saffron). No new tokens.
7. Add unit tests for the chip render (`null` hides; 100% renders without warning state; <80% renders with warning state).

**Acceptance Criteria:**
- `GET /workspaces/{id}` returns `coverage_summary: {…}` for workspaces with a finalised, evaluated harness; `null` otherwise.
- No new DB column was added.
- The chip is visible in all three locations.
- Visual treatment is consistent across the three locations — same component, same CSS.
- All `test_phase14_workspace_response_includes_coverage_summary`, `test_phase14_workspace_endpoint_computes_coverage_summary_from_eval`, and `phase14 harness coverage chip` harness tests pass.

**Dependencies:** T-166, T-169 _(PDF service consumes the same derivation; public view renders the chip)_

---

### T-173: CI Update and V1.3 Smoke Test Checklist

**Description:**
Wire the new harness contract groups into CI, ensure WeasyPrint's native deps are present in the Docker image, document the seed step in the README / CLAUDE.md, and add a V1.3 smoke section to the smoke checklist covering the full clarification → priority/estimate → PDF → public share → templates → coverage flow.

**Inputs:**
- `.github/workflows/ci.yml`
- `backend/Dockerfile` / `docker-compose.yml`
- `CLAUDE.md`
- `docs/SMOKE_TEST_CHECKLIST.md` (created in T-159)
- All T-160 through T-172 outputs
- Harness manifest entries: `v1-3-usefulness-contracts`, `v1-3-usefulness-frontend-contracts`

**Outputs:**
- Updated `.github/workflows/ci.yml`
- Verified `backend/Dockerfile` (cairo / pango present)
- Updated `CLAUDE.md`
- Updated `docs/SMOKE_TEST_CHECKLIST.md`

**Steps:**
1. Add to the backend CI job in `.github/workflows/ci.yml`, after the existing Phase 13 step:
   ```yaml
   - name: V1.3 usefulness contracts
     run: cd backend && uv run pytest ../harness/tests/backend/test_phase14_v13_usefulness_contract.py -q
   - name: V1.3 unit tests
     run: cd backend && uv run pytest tests/test_spec_clarifier.py tests/test_pdf_export_service.py tests/test_public_share_service.py tests/test_online_eval_task_fields.py tests/test_seed_templates.py -q
   ```
2. Add to the frontend CI job, after the existing Phase 13 step:
   ```yaml
   - name: V1.3 usefulness frontend contracts
     run: cd frontend && pnpm vitest run ../harness/tests/frontend/phase14-v13-usefulness.contract.test.ts
   ```
3. Verify `backend/Dockerfile` (or the Railway base image) includes `libcairo2`, `libpango-1.0-0`, `libpangoft2-1.0-0`. If using `python:3.12-slim`, add an `apt-get install -y --no-install-recommends libcairo2 libpango-1.0-0 libpangoft2-1.0-0` step. Test locally with `docker compose build --no-cache api && docker compose up -d api && docker compose exec api uv run python -c "import weasyprint; weasyprint.HTML(string='<p>hi</p>').write_pdf()"` — must exit 0.
4. Update `CLAUDE.md`:
   - Mention that `templates` are seeded automatically on container start via `scripts/seed_templates.py`.
   - Mention the new optional env keys if any (none in V1; document for V2 reference).
   - Note that `/p/{slug}` is an unauthenticated public route.
5. Append to `docs/SMOKE_TEST_CHECKLIST.md`:
   ```
   ## V1.3 Usefulness Improvements

   Spec Clarification:
   1. Create a fresh workspace. Click Generate on the spec stage.
   2. Verify the clarification modal opens with 3–5 short-answer fields.
   3. Click Skip. Verify generation begins immediately.
   4. Create another workspace, fill in answers, click "Use answers". Verify generation begins and the spec references the answered context.

   Task Priority + Estimate:
   5. Complete the pipeline to TASKS. Verify every task has Priority and Estimate lines.
   6. Verify the workspace header shows an effort-summary chip.

   PDF Export:
   7. Click "📄 Export PDF" on a finalised workspace. Verify download starts within 2 seconds.
   8. Open the PDF. Verify cover page, ToC, three sections (SPEC/PLAN/TASKS), syntax-highlighted code, SpecForge footer.
   9. Verify the harness directory is NOT included.

   Public Share:
   10. Click "🔗 Share Public Link". Toggle enable. Copy the URL.
   11. Open the URL in an incognito window. Verify the spec renders without a login prompt.
   12. View source — verify the noindex meta tag is present.
   13. Toggle disable. Reload the incognito tab. Verify 404.

   Starter Templates:
   14. Sign out. Sign in as a new user. Verify the Dashboard prominently shows the Templates strip.
   15. Click a template card. Verify the workspace form pre-fills name + problem statement.
   16. Submit. Verify the created workspace's template_slug is recorded.

   Harness Coverage Chip:
   17. Open a workspace with a finalised harness. Verify the coverage chip is visible in the header.
   18. Open the dashboard. Verify the same chip on the workspace card.
   19. Open the public share view. Verify the chip is visible there too.
   ```
6. Run `docker compose down && docker compose up --build -d`. Wait healthy.
7. Run `docker compose exec api uv run pytest ../harness/tests/backend/test_phase14_v13_usefulness_contract.py -q` — all green.
8. Run `docker compose exec frontend pnpm vitest run ../harness/tests/frontend/phase14-v13-usefulness.contract.test.ts` — all green.
9. Run `docker compose exec api uv run pytest tests/ -q --cov=services --cov-fail-under=80` — full backend suite green and coverage maintained.
10. Run `docker compose exec frontend pnpm tsc` — no TypeScript errors.

**Acceptance Criteria:**
- CI references both Phase 14 harness contract files.
- WeasyPrint successfully renders a PDF inside the Docker image.
- `CLAUDE.md` documents the template seed and the public route.
- The smoke checklist covers all six v1.3 features end-to-end.
- All harness tests pass inside Docker.
- `pnpm tsc` exits 0 inside Docker.
- All Phase 1–13 tests continue to pass.

**Dependencies:** T-172

---

## Phase 15 — Enterprise Production Hardening

> Source: `docs/CODE_REVIEW.md` §C-1 through §L-8 (staff-engineer production readiness review dated 2026-05-22). Harness: `harness/tests/backend/test_phase15_enterprise_hardening_contract.py`, `harness/tests/frontend/phase15-enterprise-hardening.contract.test.ts`. Phases 1–14 must be complete and green before starting this phase. Tasks T-174 through T-190 address every critical (C-1–C-4), high (H-1–H-6), medium (M-1–M-7), and low (L-1–L-8) finding from the code review. No finding is skipped; no finding is partially addressed.

---

### T-174: Stage Manager Concurrency Safety

**Description:**
Two race conditions in `backend/services/pipeline/stage_manager.py` allow concurrent requests to corrupt stage state. Finding C-1: `finalise()` calls `_load_stage(stage_id, db)` without `lock=True`; two simultaneous `finalise()` requests both pass the `status != "finalised"` guard and both apply finalise side-effects (credit charges, version snapshots, downstream stage unlocks). Finding C-2: `generate_harness_patch()` accepts `"in_progress"` in its status allowlist and lists `"final"` (a dead status that was renamed to `"finalised"`), allowing a new generation to begin on an already-running stage.

**Severity:** Critical

**Inputs:**
- `backend/services/pipeline/stage_manager.py` — `finalise()` near line 897, `generate_harness_patch()` near line 1126, `_load_stage()` near line 1046
- Harness: `test_phase15_finalise_uses_select_for_update`, `test_phase15_generate_harness_patch_status_allowlist`

**Outputs:**
- `finalise()` passes `lock=True` to `_load_stage`
- `generate_harness_patch()` allowlist is `("draft", "stale", "finalised")`

**Steps:**
1. In `stage_manager.py`, locate `finalise()`. Find the `_load_stage(stage_id, db)` call (no `lock` argument). Change it to `_load_stage(stage_id, db, lock=True)`.
2. In the same file, locate `generate_harness_patch()`. Find the tuple literal containing `"draft"`, `"stale"`, `"final"`, `"in_progress"`. Replace it with `("draft", "stale", "finalised")`. Remove both `"final"` (dead status) and `"in_progress"` (allows mid-generation restart).
3. Run `uv run pytest tests/ -q` to confirm no existing tests break.
4. Verify with `grep -n "lock=True" stage_manager.py` that `finalise()` now appears in the output alongside the two existing `lock=True` call sites.

**Acceptance Criteria:**
- `_load_stage` in `finalise()` is called with `lock=True`.
- `generate_harness_patch()` status allowlist is exactly `("draft", "stale", "finalised")` — neither `"final"` nor `"in_progress"` appears.
- All existing backend tests pass.
- Harness contracts `test_phase15_finalise_uses_select_for_update` and `test_phase15_generate_harness_patch_status_allowlist` pass.

**Dependencies:** None

---

### T-175: OAuth State Atomicity

**Description:**
Finding C-3: `backend/services/auth_service.py` validates the OAuth state parameter using two non-atomic Redis operations — `get(state_key)` followed by `delete(state_key)`. A concurrent second callback with the same state key can read a valid state before the first callback deletes it, passing the CSRF check twice and issuing two valid JWTs from one OAuth flow. Fix: replace both calls with the atomic `getdel(state_key)` command, which reads and deletes in a single round-trip.

**Severity:** Critical

**Inputs:**
- `backend/services/auth_service.py` — lines near 93–95 (`get` + `delete` pattern)
- Harness: `test_phase15_oauth_state_uses_getdel`

**Outputs:**
- `auth_service.py` uses `await redis.getdel(state_key)` — single atomic call, no separate `delete`

**Steps:**
1. Open `backend/services/auth_service.py`. Find the two-line block: `stored = await redis.get(state_key)` followed by `await redis.delete(state_key)`.
2. Replace both lines with: `stored = await redis.getdel(state_key)`. The semantics are identical — returns the value and deletes it atomically; returns `None` if the key does not exist.
3. Confirm `redis.getdel` is supported by the installed `redis-py` version (`pip show redis` — available since 4.1.0).
4. Run `uv run pytest tests/test_auth_service.py -q` to confirm auth tests pass.

**Acceptance Criteria:**
- `auth_service.py` contains exactly one Redis call for state validation — `getdel` — and no separate `delete` call for the state key.
- All auth service tests pass.
- Harness contract `test_phase15_oauth_state_uses_getdel` passes.

**Dependencies:** None

---

### T-176: PDF Export Thread Isolation

**Description:**
Finding C-4: `backend/services/pipeline/pdf_export_service.py` calls `HTML(string=html_text).write_pdf()` (WeasyPrint) synchronously on the async event loop. WeasyPrint is CPU-bound and holds the GIL for the full render duration — typically 0.5–3 seconds per document. During this time the entire FastAPI event loop is blocked: no other request can be handled, no SSE chunks can be flushed, no health checks can respond. Fix: extract the synchronous call into a standalone helper function and dispatch it to the default thread pool via `run_in_executor`.

**Severity:** Critical

**Inputs:**
- `backend/services/pipeline/pdf_export_service.py` — `write_pdf()` call near line 167
- Harness: `test_phase15_pdf_export_uses_run_in_executor`

**Outputs:**
- Module-level `_render_pdf_sync(html_text: str) -> bytes` function
- Async caller uses `await asyncio.get_event_loop().run_in_executor(None, _render_pdf_sync, html_text)`

**Steps:**
1. In `pdf_export_service.py`, extract the WeasyPrint call into a top-level synchronous function:
   ```python
   def _render_pdf_sync(html_text: str) -> bytes:
       return HTML(string=html_text).write_pdf()
   ```
2. Replace the original inline call at line 167 with:
   ```python
   pdf_bytes = await asyncio.get_event_loop().run_in_executor(None, _render_pdf_sync, html_text)
   ```
3. Add `import asyncio` at the top of the file if not already present.
4. Run the PDF export endpoint against a test workspace to confirm the PDF still renders correctly.

**Acceptance Criteria:**
- `pdf_export_service.py` contains no direct synchronous `write_pdf()` call inside an `async def` function.
- `_render_pdf_sync` is a module-level (non-async) function containing the WeasyPrint call.
- `run_in_executor` is used to call it from the async context.
- Harness contract `test_phase15_pdf_export_uses_run_in_executor` passes.

**Dependencies:** T-166

---

### T-177: Unified Redis Connection Pool

**Description:**
Finding H-1: Across routers and services, `Redis.from_url(settings.redis_url)` is called per-request in at least 10 locations. Each call instantiates a new connection object with no pooling. Under sustained load this causes Redis connection exhaustion, `ConnectionError` spikes, and unnecessary TCP handshake overhead. The application already initialises a shared pooled `Redis` client in `app.state.redis` at startup — that shared client must be used everywhere.

**Severity:** High

**Inputs:**
- `backend/database.py` or `backend/main.py` — app startup Redis initialisation
- All router/service files calling `Redis.from_url(...)` directly
- Harness: `test_phase15_no_redis_from_url_in_request_handlers`

**Outputs:**
- FastAPI dependency `get_redis(request: Request) -> Redis` in `backend/dependencies.py` (create if absent)
- All per-request `Redis.from_url()` calls replaced with `Depends(get_redis)`

**Steps:**
1. Confirm `app.state.redis` is set at startup (look in `main.py` lifespan or `startup` event). If not, add it: `app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)` in the startup handler and `await app.state.redis.aclose()` in shutdown.
2. Create (or extend) `backend/dependencies.py`. Add:
   ```python
   from fastapi import Request
   from redis.asyncio import Redis

   def get_redis(request: Request) -> Redis:
       return request.app.state.redis
   ```
3. Search for every `Redis.from_url(` call outside of `main.py` startup. For each call site: inject `redis: Redis = Depends(get_redis)` into the function signature and remove the local `Redis.from_url(...)` call.
4. Run `grep -rn "Redis.from_url" backend/` after the change. The only occurrence must be in `main.py` (or `database.py`) at startup — zero occurrences in routers or services.
5. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `Redis.from_url(` does not appear in any router or service file — only in the application startup path.
- All Redis-dependent tests pass.
- Harness contract `test_phase15_no_redis_from_url_in_request_handlers` passes.

**Dependencies:** None

---

### T-178: N+1 Coverage Query Elimination

**Description:**
Finding H-2: `backend/routers/workspace.py` near line 125 calls `_derive_coverage_summary(workspace.id, db)` inside a loop over all workspaces returned by the list query. For a user with N workspaces, the endpoint issues N+1 database queries. At the default limit of 50 workspaces, this is 51 queries per page load. Fix: rewrite `_derive_coverage_summary` to accept a list of workspace IDs and issue one batched query.

**Severity:** High

**Inputs:**
- `backend/routers/workspace.py` — workspace list endpoint, `_derive_coverage_summary` function
- `backend/services/pipeline/stage_manager.py` or equivalent — coverage query logic
- Harness: `test_phase15_workspace_list_no_n_plus_one`

**Outputs:**
- `_derive_coverage_summary(workspace_ids: list[UUID], db: AsyncSession) -> dict[UUID, CoverageSummary | None]` — batched form
- Workspace list endpoint calls it once with all IDs and distributes results

**Steps:**
1. Locate `_derive_coverage_summary`. Note the SQL it issues (typically a `SELECT` on the `stages` table filtered by workspace ID).
2. Rewrite the signature to accept `workspace_ids: list[UUID]`. Change the WHERE clause from `stage.workspace_id = :id` to `stage.workspace_id = ANY(:ids)` (PostgreSQL) and bind the full list. Return `dict[UUID, CoverageSummary | None]`.
3. In the workspace list endpoint, collect all workspace IDs after the primary query, call `_derive_coverage_summary(workspace_ids, db)` once, then distribute results: `coverage_map.get(workspace.id)` for each workspace in the response.
4. Confirm with `EXPLAIN ANALYZE` or logging that the endpoint now issues exactly 2 queries (one for workspaces, one for coverage) regardless of workspace count.

**Acceptance Criteria:**
- `_derive_coverage_summary` is not called inside a loop in the list endpoint.
- The endpoint issues a fixed number of queries independent of the number of workspaces returned.
- Existing workspace list tests pass.
- Harness contract `test_phase15_workspace_list_no_n_plus_one` passes.

**Dependencies:** T-161

---

### T-179: Recovery Lock TTL Extension

**Description:**
Finding H-3: `backend/services/pipeline/stage_manager.py` sets `_RECOVERY_LOCK_TTL = 60` seconds, which equals `_POLL_INTERVAL_SECONDS = 60`. A recovery run that takes slightly over 60 seconds causes the distributed lock to expire while recovery is still in progress. A second recovery runner then acquires the lock and starts a concurrent recovery of the same workspace, producing duplicate version snapshots, double stage-state writes, and potential credit double-counts. Fix: extend the TTL to 3× the poll interval and add a heartbeat `EXPIRE` inside the recovery loop.

**Severity:** High

**Inputs:**
- `backend/services/pipeline/stage_manager.py` — `_RECOVERY_LOCK_TTL`, `_POLL_INTERVAL_SECONDS`, recovery loop body
- Harness: `test_phase15_recovery_lock_ttl_exceeds_poll_interval`, `test_phase15_recovery_lock_heartbeat_exists`

**Outputs:**
- `_RECOVERY_LOCK_TTL = 180`
- Recovery loop calls `await redis.expire(lock_key, _RECOVERY_LOCK_TTL)` at least once per iteration before the expensive recovery work

**Steps:**
1. Change `_RECOVERY_LOCK_TTL = 60` to `_RECOVERY_LOCK_TTL = 180`.
2. Inside the recovery loop body (the `async for` or `while` block that processes in-flight stages), add a heartbeat at the top of each iteration:
   ```python
   await redis.expire(lock_key, _RECOVERY_LOCK_TTL)
   ```
   This resets the TTL at the start of each iteration, keeping the lock alive for long-running recoveries.
3. Verify `_RECOVERY_LOCK_TTL > _POLL_INTERVAL_SECONDS` with a module-level assertion or test.
4. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `_RECOVERY_LOCK_TTL >= 3 * _POLL_INTERVAL_SECONDS`.
- The recovery loop issues a Redis `EXPIRE` heartbeat call each iteration.
- Harness contracts `test_phase15_recovery_lock_ttl_exceeds_poll_interval` and `test_phase15_recovery_lock_heartbeat_exists` pass.

**Dependencies:** None

---

### T-180: Auth Cache Credit Cross-Invalidation

**Description:**
Finding H-4: `backend/middleware/auth.py` caches `credit_balance` in `_USER_CACHE: OrderedDict[UUID, tuple[float, dict]]` with a 30-second TTL. When `backend/services/credit_service.py` charges or grants credits, it calls `_invalidate(user_id)` to flush internal credit caches — but this does NOT flush `_USER_CACHE`. The user's credit balance displayed in the frontend remains stale for up to 30 seconds after every generation. Fix: export an `invalidate_user_cache(user_id)` function from `auth.py` and call it inside `credit_service._invalidate()`.

**Severity:** High

**Inputs:**
- `backend/middleware/auth.py` — `_USER_CACHE`, cache lookup/write logic
- `backend/services/credit_service.py` — `_invalidate(user_id)` method
- Harness: `test_phase15_credit_invalidation_clears_auth_cache`

**Outputs:**
- `auth.py` exports `def invalidate_user_cache(user_id: UUID) -> None` that removes the entry from `_USER_CACHE`
- `credit_service._invalidate()` imports and calls `invalidate_user_cache(user_id)`

**Steps:**
1. In `backend/middleware/auth.py`, add a public function:
   ```python
   def invalidate_user_cache(user_id: UUID) -> None:
       _USER_CACHE.pop(user_id, None)
   ```
2. In `backend/services/credit_service.py`, at the end of `_invalidate(user_id)`, add:
   ```python
   from middleware.auth import invalidate_user_cache
   invalidate_user_cache(user_id)
   ```
   Place the import at the top of the file to avoid circular-import issues; if a circular import occurs, move to a late import inside the function body.
3. Run `uv run pytest tests/ -q`. Confirm credit and auth tests pass.

**Acceptance Criteria:**
- `auth.py` exposes `invalidate_user_cache`.
- `credit_service._invalidate()` calls `invalidate_user_cache` after updating credit state.
- Harness contract `test_phase15_credit_invalidation_clears_auth_cache` passes.

**Dependencies:** None

---

### T-181: Markdown XSS Remediation

**Description:**
Finding H-5: The frontend `MarkdownRenderer` component uses `react-markdown` without `rehype-sanitize`. A malicious stage document (generated by a compromised LLM response or a SPEC/PLAN/HARNESS/TASKS body containing injected content) can embed `[click me](javascript:void(0))`, `<img src=x onerror=alert(1)>`, or other XSS payloads that execute in the user's browser context — giving an attacker access to JWT tokens stored in-memory, CSRF tokens, and the user's workspace content. Fix: add `rehype-sanitize` as a `rehypePlugin`.

**Severity:** High

**Inputs:**
- `frontend/src/components/` — `MarkdownRenderer.tsx` (or equivalent component using `react-markdown`)
- `frontend/package.json` — add `rehype-sanitize`
- Harness: `test_phase15_markdown_renderer_uses_rehype_sanitize`

**Outputs:**
- `rehype-sanitize` installed and passed as `rehypePlugins={[rehypeSanitize]}` to `<ReactMarkdown>`

**Steps:**
1. Install the package: `pnpm add rehype-sanitize`.
2. In `MarkdownRenderer.tsx`, add the import: `import rehypeSanitize from "rehype-sanitize";`
3. Add `rehypePlugins={[rehypeSanitize]}` to the `<ReactMarkdown>` component props. Use the default sanitization schema — it allows safe HTML elements and strips `script` tags, `on*` event attributes, and `javascript:` hrefs.
4. Run `pnpm test` and `pnpm tsc --noEmit`.
5. Manually verify: create a test markdown string containing `[xss](javascript:alert(1))` and confirm it renders as a plain `<a>` with an empty or safe `href`.

**Acceptance Criteria:**
- `rehype-sanitize` is listed in `frontend/package.json` dependencies.
- `MarkdownRenderer.tsx` imports `rehypeSanitize` and passes it as a `rehypePlugin`.
- `javascript:` hrefs and `onerror` attributes in Markdown input do not appear in the rendered DOM.
- `pnpm tsc` exits 0; `pnpm test` passes.
- Harness contract `test_phase15_markdown_renderer_uses_rehype_sanitize` passes.

**Dependencies:** None

---

### T-182: LLM Adapter HTTP Timeouts

**Description:**
Finding H-6: No `httpx.Timeout` is configured on any LLM provider adapter (Anthropic, OpenAI, Google Gemini). A provider connection that hangs (slow network, provider incident, TCP half-open) holds the event loop connection slot and the credit reservation indefinitely. A credit reservation left unclosed corrupts the credit ledger — users are charged for generations that never completed and never refunded. Fix: add explicit connect and read timeouts to each adapter's `httpx.AsyncClient` and a wall-clock `asyncio.wait_for` wrapper in the gateway.

**Severity:** High

**Inputs:**
- `backend/services/llm/` — provider adapters for Anthropic, OpenAI, Gemini; `gateway.py`
- `backend/services/credit_service.py` — credit reservation/release logic
- Harness: `test_phase15_llm_adapters_have_httpx_timeout`, `test_phase15_gateway_has_wall_clock_timeout`

**Outputs:**
- Each adapter's `httpx.AsyncClient` initialised with `httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)`
- `gateway.py` wraps the streaming call with `asyncio.wait_for(..., timeout=330.0)`
- On timeout, the credit reservation is released via the existing release path

**Steps:**
1. In each provider adapter file, locate the `httpx.AsyncClient(...)` constructor (or equivalent). Add `timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)`. Import `httpx` if not already imported.
2. For providers that use the provider SDK directly (e.g., `anthropic.AsyncAnthropic`), set the `timeout` parameter on the client constructor (Anthropic SDK exposes this directly).
3. In `gateway.py`, wrap the generation coroutine:
   ```python
   try:
       result = await asyncio.wait_for(
           _call_provider(provider, ...),
           timeout=330.0,
       )
   except asyncio.TimeoutError:
       await credit_service.release_reservation(reservation_id)
       raise HTTPException(status_code=504, detail="Generation timed out")
   ```
4. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- Each provider adapter specifies an `httpx.Timeout` (or SDK-level timeout) with connect ≤ 15s and read ≤ 300s.
- `gateway.py` uses `asyncio.wait_for` with a wall-clock timeout.
- On timeout, the credit reservation is released and the caller receives a 504 response.
- Harness contracts `test_phase15_llm_adapters_have_httpx_timeout` and `test_phase15_gateway_has_wall_clock_timeout` pass.

**Dependencies:** None

---

### T-183: PDF Coverage Dead Attribute Fix

**Description:**
Finding M-1: `backend/services/pipeline/pdf_export_service.py` contains `_coverage_label()` which uses `getattr(workspace, "coverage_summary", None)`. The `coverage_summary` attribute does not exist on the `Workspace` ORM model — it is a computed field on the Pydantic response schema and is never stored in the database. The `getattr` always returns `None`, making the coverage section of every exported PDF permanently blank. Fix: pass the already-computed `CoverageSummary` as an explicit parameter to `_coverage_label()`.

**Severity:** Medium

**Inputs:**
- `backend/services/pipeline/pdf_export_service.py` — `_coverage_label()` function, its call sites
- `backend/schemas/workspace.py` — `CoverageSummary` Pydantic model
- Harness: `test_phase15_pdf_coverage_label_receives_explicit_parameter`

**Outputs:**
- `_coverage_label(coverage: CoverageSummary | None) -> str` — accepts the value as a parameter, no `getattr`
- Call sites pass the pre-computed coverage summary

**Steps:**
1. Change `_coverage_label()` signature from `_coverage_label(workspace)` (or similar) to `_coverage_label(coverage: "CoverageSummary | None") -> str`.
2. Replace the `getattr(workspace, "coverage_summary", None)` lookup inside the function with the `coverage` parameter directly.
3. Update all call sites of `_coverage_label` to pass the coverage summary that the PDF export endpoint already derives (or `None` if unavailable).
4. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `_coverage_label` does not call `getattr` on a workspace ORM object.
- `_coverage_label` accepts `coverage: CoverageSummary | None` as an explicit parameter.
- Harness contract `test_phase15_pdf_coverage_label_receives_explicit_parameter` passes.

**Dependencies:** T-166, T-161

---

### T-184: Rate Limit Fallback Bulk Eviction

**Description:**
Finding M-2: `backend/middleware/rate_limit.py`'s in-memory fallback `OrderedDict` evicts exactly one key when the dictionary exceeds 10,000 entries. Under a burst of requests from many distinct IPs (DDoS or testing spike), insertions outpace single-key eviction and the dictionary grows unbounded — eventually causing an OOM condition on the server. Fix: when the cap is reached, evict the oldest 20% of entries (2,000 keys) in a single batch operation.

**Severity:** Medium

**Inputs:**
- `backend/middleware/rate_limit.py` — in-memory fallback `OrderedDict`, eviction logic
- Harness: `test_phase15_rate_limit_fallback_bulk_eviction`

**Outputs:**
- When `len(_fallback_store) >= 10_000`, delete the oldest 2,000 entries using `itertools.islice` before inserting the new key

**Steps:**
1. Locate the eviction block in `rate_limit.py`. It currently calls `_fallback_store.popitem(last=False)` once (or similar single-key removal).
2. Replace with:
   ```python
   import itertools
   if len(_fallback_store) >= 10_000:
       keys_to_delete = list(itertools.islice(_fallback_store, 2_000))
       for k in keys_to_delete:
           del _fallback_store[k]
   ```
3. Confirm the constant 10,000 and the 20% batch size (2,000) are named constants, not magic numbers.
4. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- When the fallback store reaches capacity, 2,000 (20%) of the oldest entries are evicted in one operation.
- The fallback store is bounded above by 10,000 entries under any insertion rate.
- Harness contract `test_phase15_rate_limit_fallback_bulk_eviction` passes.

**Dependencies:** None

---

### T-185: CSRF Token Nonce Rotation

**Description:**
Finding M-3: The CSRF token is structured as `{timestamp}.{hmac(secret, user_id + timestamp)}`. Because it contains no random nonce, the same user_id + timestamp combination produces the same token — tokens are deterministic. Once issued, a token never rotates and remains valid indefinitely (until the session expires). An attacker who extracts a token once can replay it for the life of the session. Fix: inject a 128-bit random nonce into the HMAC input and into the token string; store the nonce in Redis with the session TTL; validate and consume (delete) the nonce on use.

**Severity:** Medium

**Inputs:**
- `backend/services/security/` or `backend/middleware/` — CSRF token generation and validation logic
- Redis — for nonce storage
- Harness: `test_phase15_csrf_token_contains_nonce`, `test_phase15_csrf_nonce_single_use`

**Outputs:**
- Token format: `{timestamp}.{nonce}.{hmac(secret, user_id + timestamp + nonce)}`
- Nonce stored in Redis as `csrf_nonce:{user_id}:{nonce}` with session TTL
- Validation deletes the nonce key atomically (`getdel`) — each token is single-use
- Token regenerated and set in the response on every successful state-changing request

**Steps:**
1. In the CSRF token generation function, generate a 128-bit nonce: `nonce = secrets.token_hex(16)`.
2. Change the HMAC input to include the nonce: `hmac(secret, f"{user_id}{timestamp}{nonce}".encode())`.
3. Change the token format to `f"{timestamp}.{nonce}.{signature}"`.
4. Store the nonce in Redis: `await redis.setex(f"csrf_nonce:{user_id}:{nonce}", session_ttl, "1")`.
5. In the CSRF validation function, parse the three-part token. Extract `nonce`. Call `await redis.getdel(f"csrf_nonce:{user_id}:{nonce}")` — if it returns `None`, the token is replayed or expired; reject with 403.
6. Regenerate and set a new CSRF token in the response header on every successful mutation.
7. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- CSRF tokens contain three dot-separated parts: timestamp, nonce, signature.
- No two tokens issued for the same user share the same nonce.
- A token that has been validated once is rejected on re-use (nonce is consumed).
- `pnpm tsc` exits 0 (no frontend CSRF-header logic changes needed — the header name stays the same).
- Harness contracts `test_phase15_csrf_token_contains_nonce` and `test_phase15_csrf_nonce_single_use` pass.

**Dependencies:** T-177

---

### T-186: SSE Lifecycle Correctness

**Description:**
Two bugs in the frontend SSE cleanup path. Finding M-4: `streamRef.current = null` is set BEFORE `streamRef.current.close()` — the ref is nullified, then `.close()` is called on the nullified ref (which is either a no-op on a stale closure reference or throws `TypeError: Cannot read property 'close' of null`). Finding M-7: a comment reading "keep open for eval event" appears immediately before a `.close()` call — the code and comment directly contradict each other, making the true intent of the SSE lifetime unclear to maintainers.

**Severity:** Medium

**Inputs:**
- `frontend/src/services/sseService.ts` or the component that owns `streamRef` — SSE cleanup code
- Harness: `test_phase15_sse_close_before_null`, `test_phase15_sse_comment_contradiction_resolved`

**Outputs:**
- Cleanup order: call `.close()` first, then set `streamRef.current = null`
- "keep open for eval event" comment removed; replaced with "close after generation complete; eval result arrives via polling, not SSE"

**Steps:**
1. Locate the SSE cleanup block. It currently reads approximately:
   ```js
   streamRef.current = null;
   streamRef.current.close();  // or equivalent reversed order
   ```
2. Swap the order:
   ```js
   streamRef.current.close();
   streamRef.current = null;
   ```
3. Find the "keep open for eval event" comment. Remove it. Add in its place: `// close after generation complete; eval result arrives via polling, not SSE`.
4. Run `pnpm tsc --noEmit` and `pnpm test`.

**Acceptance Criteria:**
- In the SSE cleanup path, `.close()` is called on the non-null ref before the ref is set to `null`.
- The string "keep open for eval event" does not appear in the codebase.
- `pnpm tsc` exits 0; `pnpm test` passes.
- Harness contracts `test_phase15_sse_close_before_null` and `test_phase15_sse_comment_contradiction_resolved` pass.

**Dependencies:** None

---

### T-187: Eval Polling Error Surface

**Description:**
Finding M-5: After 12 consecutive eval polling failures, the frontend silently stops polling and returns `null`. The quality badge shimmer spinner never resolves — the user cannot distinguish "still scoring" from "scoring failed permanently." Fix: track consecutive failure count; on reaching the threshold, set an `evalError` flag and render a deterministic fallback badge with user-visible text.

**Severity:** Medium

**Inputs:**
- `frontend/src/components/workspace/` — eval polling hook or component (whichever owns the retry loop), `QualityBadge.tsx`
- Harness: `test_phase15_eval_polling_surfaces_error_after_max_retries`

**Outputs:**
- `evalError: boolean` state in the polling hook/component
- After 12 consecutive failures, `evalError = true` and polling stops
- When `evalError` is true, `QualityBadge` renders a grey badge with text "Score unavailable"

**Steps:**
1. In the eval polling hook (or component), add a `consecutiveFailures` counter. Increment it on each failed poll. Reset to 0 on success. When `consecutiveFailures >= 12`, set `evalError = true` and clear the polling interval.
2. In `QualityBadge.tsx`, accept an `error?: boolean` prop. When `error` is true, render a grey badge containing "Score unavailable" instead of the shimmer state.
3. Pass `evalError` from the polling hook to `QualityBadge` via props or context.
4. `console.error` the final polling error with the stage ID for debugging.
5. Run `pnpm tsc --noEmit` and `pnpm test`.

**Acceptance Criteria:**
- After 12 consecutive polling failures, the shimmer spinner is replaced with a "Score unavailable" grey badge.
- The polling loop does not continue indefinitely after the threshold is reached.
- `pnpm tsc` exits 0; `pnpm test` passes.
- Harness contract `test_phase15_eval_polling_surfaces_error_after_max_retries` passes.

**Dependencies:** None

---

### T-188: streamingContent Type Narrowing

**Description:**
Finding M-6: The Zustand store declares `streamingContent: Record<string, string> | string`. This union type requires defensive `typeof` guards at every read site (5+ locations in `StageEditor.tsx`, `StreamingOverlay.tsx`, and related components). Missing or incorrect guards cause runtime errors during streaming — `string.split` called on an object, or object property access called on a string. Fix: narrow the type to `Record<string, string>` throughout the store and all consumers.

**Severity:** Medium

**Inputs:**
- `frontend/src/store/` — Zustand store defining `streamingContent`
- `frontend/src/components/workspace/StageEditor.tsx`, `StreamingOverlay.tsx` — read sites
- Harness: `test_phase15_streaming_content_type_is_record`

**Outputs:**
- `streamingContent: Record<string, string>` in store type definition
- Initial value: `{}`
- All `typeof streamingContent === "string"` guards removed
- All callers use `streamingContent[stageId]` (object access, no string branch)

**Steps:**
1. In the Zustand store file, change the type of `streamingContent` from `Record<string, string> | string` to `Record<string, string>`. Update the initial state from any string default to `{}`.
2. In all setter actions, ensure the value being stored is always an object key assignment (`state.streamingContent[stageId] = chunk`).
3. In all read sites (`StageEditor.tsx`, `StreamingOverlay.tsx`, etc.), remove the `typeof` string guards. Update all accesses to use `streamingContent[stageId] ?? ""`.
4. Run `pnpm tsc --noEmit` — it must exit 0 with zero type errors.
5. Run `pnpm test`.

**Acceptance Criteria:**
- `streamingContent` is typed as `Record<string, string>` — no union with `string`.
- `typeof streamingContent === "string"` guards do not appear in the codebase.
- `pnpm tsc` exits 0; `pnpm test` passes.
- Harness contract `test_phase15_streaming_content_type_is_record` passes.

**Dependencies:** None

---

### T-189a: Backend Debt Sweep

**Description:**
Two low-severity backend findings. Finding L-1: `STAGE_DEPENDENCIES` (the dict mapping stage type to its upstream dependency) is defined in two separate backend modules. Both copies must be kept in sync; when they diverge, stage unlock logic and stage ordering logic produce different dependency graphs silently. Finding L-2: the workspace router loads a workspace from the database to validate the request, then passes the workspace ID to a service method that performs a second identical database load — double DB round-trip per request, wasting latency and a connection.

**Severity:** Low

**Inputs:**
- `backend/services/pipeline/stage_manager.py` — `STAGE_DEPENDENCIES` (canonical definition)
- Whichever other module also defines `STAGE_DEPENDENCIES` (find with `grep -rn "STAGE_DEPENDENCIES" backend/`)
- `backend/routers/workspace.py` — double-load request paths
- Harness: `test_phase15_stage_dependencies_single_definition`, `test_phase15_workspace_router_no_double_load`

**Outputs:**
- `STAGE_DEPENDENCIES` defined exactly once; duplicate definition removed and replaced with an import
- The service method accepting a workspace ID is updated to accept the already-loaded ORM object directly (or the router passes the object through)

**Steps:**
1. Run `grep -rn "STAGE_DEPENDENCIES\s*=" backend/` to find every definition site. Keep the one in `stage_manager.py` as canonical. In all other files, remove the local definition and replace with `from services.pipeline.stage_manager import STAGE_DEPENDENCIES`.
2. In `backend/routers/workspace.py`, identify the endpoint(s) that load a workspace then call a service that re-loads the same workspace. Update the service method signature to accept `workspace: Workspace` (ORM object) instead of `workspace_id: UUID`. Pass the already-loaded workspace directly. Remove the second DB call from the service.
3. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `STAGE_DEPENDENCIES =` appears exactly once in the backend codebase.
- The identified workspace service method does not issue a redundant DB query when the router already has the workspace loaded.
- Harness contracts `test_phase15_stage_dependencies_single_definition` and `test_phase15_workspace_router_no_double_load` pass.

**Dependencies:** None

---

### T-189b: Frontend Debt Sweep

**Description:**
Four low-severity frontend findings. Finding L-3: `CreditConfirmModal` accepts both `creditCost` and `cost` as aliases for the same prop, and both `currentBalance` and `balance` as aliases for the same prop — callers across the codebase use different names, both alias pairs must be kept in sync, and TypeScript cannot catch the divergence because both are accepted. Finding L-4: `ExportGitHubModal` shows a progress spinner that runs indefinitely if the export API call hangs or returns a non-error non-success state — there is no client-side timeout, so a stuck export has no recovery path for the user. Finding L-5: `TemplatesStrip` has no error boundary; a network error during template fetch crashes the whole workspace view. Finding L-6: `SharePublicLinkModal` does not trap focus — Tab key exits the modal and reaches background elements, violating WCAG 2.1 SC 2.1.2.

**Severity:** Low

**Inputs:**
- `frontend/src/components/workspace/CreditConfirmModal.tsx`
- `frontend/src/components/workspace/ExportGitHubModal.tsx`
- `frontend/src/components/workspace/TemplatesStrip.tsx`
- `frontend/src/components/workspace/SharePublicLinkModal.tsx`
- Harness: `test_phase15_credit_confirm_modal_no_prop_aliases`, `test_phase15_export_github_modal_has_abort_timeout`, `test_phase15_templates_strip_has_error_boundary`, `test_phase15_share_modal_focus_trap`

**Outputs:**
- `CreditConfirmModal` props: `creditCost` and `currentBalance` as canonical names — `cost` and `balance` aliases removed; all call sites updated
- `ExportGitHubModal` export request uses `AbortController` with a 30-second timeout; spinner resolves to an error state on abort
- `TemplatesStrip` wrapped in a React error boundary rendering "Templates unavailable" on error
- `SharePublicLinkModal` traps focus using `focus-trap-react` or equivalent

**Steps:**
1. In `CreditConfirmModal.tsx`, pick `creditCost` and `currentBalance` as the canonical prop names. Remove the `cost` and `balance` alias definitions from the props interface. Run `pnpm tsc --noEmit` — TypeScript will flag every call site still using the removed aliases. Update each call site to use the canonical names.
2. In `ExportGitHubModal.tsx`, add `AbortController` timeout: create `const controller = new AbortController()` before the export call; pass `signal: controller.signal` to the API client; set `const timeout = setTimeout(() => controller.abort(), 30_000)` and clear it in a `finally` block. On `AbortError`, display "Export timed out — please retry."
3. Create `frontend/src/components/workspace/TemplatesStripErrorBoundary.tsx` (or add an inline class component). Wrap `<TemplatesStrip>` with it everywhere it is rendered. The fallback renders nothing (silent fail) or a one-line "Templates unavailable" note.
4. Install `focus-trap-react` if not already present (`pnpm add focus-trap-react`). In `SharePublicLinkModal.tsx`, wrap the modal content with `<FocusTrap active={isOpen}>`. Set `initialFocus` to the first interactive element.
5. Run `pnpm tsc --noEmit` and `pnpm test`.

**Acceptance Criteria:**
- `CreditConfirmModal` props interface does not contain `cost` or `balance` aliases.
- `ExportGitHubModal` uses `AbortController` and aborts after 30 seconds with a visible error message.
- `TemplatesStrip` is rendered inside an error boundary.
- `SharePublicLinkModal` traps focus when open.
- `pnpm tsc` exits 0; `pnpm test` passes.
- Harness contracts for all four fixes pass.

**Dependencies:** None

---

### T-189c: Infrastructure Debt Sweep

**Description:**
Two low-severity infrastructure findings. Finding L-7: The frontend Vite dev server port `5173:5173` in `docker-compose.yml` is bound to all interfaces without a `127.0.0.1:` prefix. On a developer laptop with the firewall disabled or on a shared network (office Wi-Fi, university LAN), the local Vite dev server — which serves unminified source, source maps, and hot-reload websockets — is accessible to any machine on the same subnet. Finding L-8: `AUTH_LOGIN_BURST_LIMIT: 60` and `AUTH_LOGIN_HOURLY_LIMIT: 240` are set as environment variable overrides in `docker-compose.yml`, dramatically relaxing the production-safe auth rate limits. A developer who copies this Compose configuration to a staging environment without understanding these variables deploys with dangerously permissive rate limits and no warning.

**Severity:** Low

**Inputs:**
- `docker-compose.yml` (repository root) — `ports:` section for the `frontend` service; environment variable overrides for auth rate limits in the `api` service
- `docs/LOCAL_TESTING_HANDBOOK.md` — local dev section
- Harness: `test_phase15_docker_compose_frontend_port_bound_to_localhost`, `test_phase15_docker_compose_auth_rate_limits_documented`

**Outputs:**
- `docker-compose.yml` frontend port binding changed to `"127.0.0.1:5173:5173"`; DB and Redis ports also bound to localhost
- `AUTH_LOGIN_BURST_LIMIT` and `AUTH_LOGIN_HOURLY_LIMIT` annotated with `# Local dev only — do not copy to staging/production`
- `docs/LOCAL_TESTING_HANDBOOK.md` notes the rate limit overrides and their dev-only scope

**Steps:**
1. In `docker-compose.yml`, change the `frontend` service port from `"5173:5173"` to `"127.0.0.1:5173:5173"`. While there, also bind `db` (`5432`) and `redis` (`6379`) to `127.0.0.1` for consistent localhost-only access across all dev services.
2. Locate the `AUTH_LOGIN_BURST_LIMIT` and `AUTH_LOGIN_HOURLY_LIMIT` environment variable overrides in the `api` service definition. Add an inline comment immediately above or beside each:
   ```yaml
   AUTH_LOGIN_BURST_LIMIT: 60      # Local dev only — do not copy to staging/production
   AUTH_LOGIN_HOURLY_LIMIT: 240    # Local dev only — do not copy to staging/production
   ```
3. Consider moving these overrides to a `docker-compose.override.yml` so that a plain `docker compose -f docker-compose.yml` invocation used in CI or staging never picks them up.
4. In `docs/LOCAL_TESTING_HANDBOOK.md`, add a note: "The Compose file sets relaxed auth rate limits for local development (`AUTH_LOGIN_BURST_LIMIT`, `AUTH_LOGIN_HOURLY_LIMIT`). Do not copy these values to staging or production."
5. Run `docker compose config` to validate the compose file syntax after editing.

**Acceptance Criteria:**
- Frontend port `5173` is bound to `127.0.0.1` in `docker-compose.yml`.
- `AUTH_LOGIN_BURST_LIMIT` and `AUTH_LOGIN_HOURLY_LIMIT` overrides have an inline comment marking them as local dev only.
- `docs/LOCAL_TESTING_HANDBOOK.md` documents the rate limit overrides.
- Harness contracts `test_phase15_docker_compose_frontend_port_bound_to_localhost` and `test_phase15_docker_compose_auth_rate_limits_documented` pass.

**Dependencies:** None

---

### T-190: Phase 15 CI Wire-up and Production Hardening Smoke Checklist

**Description:**
Wire the Phase 15 harness contract files into CI and update the production smoke checklist to cover hardening behaviours introduced in T-174 through T-189c. Every new harness test must run in CI on every push. The smoke checklist must verify that hardening controls are active in the staging environment before any production promotion.

**Severity:** High

**Inputs:**
- `.github/workflows/ci.yml` — existing CI definition
- `docs/PRODUCTION_RELEASE_GATE.md` — automated gate and smoke gate sections
- `harness/tests/backend/test_phase15_enterprise_hardening_contract.py` (T-174 → T-189c)
- `harness/tests/frontend/phase15-enterprise-hardening.contract.test.ts` (T-174 → T-189c)

**Outputs:**
- CI runs `test_phase15_enterprise_hardening_contract.py` alongside existing harness contracts
- CI runs `phase15-enterprise-hardening.contract.test.ts` in the frontend vitest harness step
- `docs/PRODUCTION_RELEASE_GATE.md` automated gate section lists Phase 15 harness files
- `docs/PRODUCTION_RELEASE_GATE.md` manual smoke checklist extended with hardening items

**Steps:**
1. In `.github/workflows/ci.yml`, find the `uv run pytest` step that runs harness contracts. Add `../harness/tests/backend/test_phase15_enterprise_hardening_contract.py` to the list of files.
2. Find the frontend vitest harness step. Confirm `phase15-enterprise-hardening.contract.test.ts` is picked up by the existing glob pattern; if not, add it explicitly.
3. In `docs/PRODUCTION_RELEASE_GATE.md`, under the "Automated Gate" code block, add:
   ```
   ../harness/tests/backend/test_phase15_enterprise_hardening_contract.py \
   ```
   to the pytest invocation.
4. In `docs/PRODUCTION_RELEASE_GATE.md`, under "Manual Smoke Gate", add the following items to the minimum release-blocking list:
   - Concurrent finalise requests do not double-charge credits (send two simultaneous finalise API calls and verify exactly one version snapshot and one credit deduction).
   - OAuth sign-in with a replayed state parameter is rejected (verify 403 on duplicate state).
   - PDF export returns within 10 seconds and does not block concurrent API requests during render.
   - Markdown content containing `javascript:` hrefs does not execute in browser (manual XSS smoke).
   - LLM generation request to an unreachable provider returns 504 within 350 seconds, not a hung connection.
   - Credit balance updates immediately after generation completes (no 30-second stale display).
5. Run the full CI locally to confirm all Phase 15 harness tests pass:
   ```bash
   cd backend
   uv run pytest ../harness/tests/backend/test_phase15_enterprise_hardening_contract.py -q
   ```

**Acceptance Criteria:**
- CI references `test_phase15_enterprise_hardening_contract.py`.
- CI references `phase15-enterprise-hardening.contract.test.ts`.
- `docs/PRODUCTION_RELEASE_GATE.md` automated gate lists Phase 15 harness.
- `docs/PRODUCTION_RELEASE_GATE.md` manual smoke gate covers all six hardening behaviours.
- All Phase 1–14 tests continue to pass.
- All Phase 15 harness contract tests pass.

**Dependencies:** T-174, T-175, T-176, T-177, T-178, T-179, T-180, T-181, T-182, T-183, T-184, T-185, T-186, T-187, T-188, T-189a, T-189b, T-189c

---

### T-191: LLM Instance Cache LRU Eviction

**Description:**
The `_INSTANCES` dict in `backend/services/llm/gateway.py` is a module-level plain dict that caches instantiated LLM provider clients keyed by `(provider, api_key_hash)`. It is never evicted. In a long-running worker where many distinct users store custom API keys, the cache accumulates one client instance per unique key. Each instance holds an open `httpx` connection pool. Over hours of operation under diverse user load, memory grows monotonically and the number of open connections grows without bound.

**Severity:** Low

**Inputs:**
- `backend/services/llm/gateway.py` — `_INSTANCES` dict or equivalent client cache
- Harness: `test_phase15_llm_instance_cache_has_bounded_size`

**Outputs:**
- `_INSTANCES` replaced with a bounded structure: `OrderedDict` with LRU eviction at a named `_INSTANCE_CACHE_MAX = 256` constant, or `cachetools.LRUCache(maxsize=256)`

**Steps:**
1. In `gateway.py`, locate the module-level `_INSTANCES: dict[..., ...]`.
2. Replace the plain `dict` with one of:
   - `collections.OrderedDict` with manual LRU: before each insertion, if `len(_INSTANCES) >= _INSTANCE_CACHE_MAX`, call `_INSTANCES.popitem(last=False)` to evict the oldest entry.
   - `cachetools.LRUCache(maxsize=256)`: add `cachetools` to `pyproject.toml`, import `LRUCache`, declare `_INSTANCES: LRUCache = LRUCache(maxsize=256)`.
3. Add `_INSTANCE_CACHE_MAX = 256` at module level as a named constant.
4. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `_INSTANCES` has a defined maximum size (constant ≤ 256 entries).
- When the max is reached, the oldest entry is evicted before a new one is inserted.
- `_INSTANCE_CACHE_MAX` (or equivalent named constant) is defined at module level.
- Harness contract `test_phase15_llm_instance_cache_has_bounded_size` passes.

**Dependencies:** T-177

---

### T-192: CSRF Exempt Path Audit

**Description:**
The Security Audit flagged that `_EXEMPT_PATHS` in the CSRF middleware may inconsistently protect mutation endpoints. Specifically: the coverage of `/auth/logout` is unverified. Logout destroys the session — it is a mutation — and must require a valid CSRF token to prevent cross-site logout attacks (an attacker can silently log out a user by embedding a request to `/auth/logout` on any page the victim visits). Every path listed in `_EXEMPT_PATHS` must have an explicit inline justification documenting why it is safe to exempt.

**Severity:** Medium

**Inputs:**
- `backend/middleware/csrf.py` — `_EXEMPT_PATHS` list
- `backend/routers/auth.py` — logout endpoint definition
- Harness: `test_phase15_csrf_logout_not_exempt`, `test_phase15_csrf_exempt_paths_all_documented`

**Outputs:**
- `/auth/logout` is NOT in `_EXEMPT_PATHS`
- Each path in `_EXEMPT_PATHS` has an inline comment: `# exempt: <reason>`

**Steps:**
1. Open `backend/middleware/csrf.py`. Find `_EXEMPT_PATHS` (list or tuple).
2. Confirm `/auth/logout` is not listed. If it is, remove it — logout requires CSRF.
3. For `/auth/refresh` (expected to be exempt): add comment `# exempt: refresh uses HTTP-only refresh token, not session state; CSRF at this endpoint would require a pre-auth token exchange`.
4. For any other exempt path, add an inline comment with the exemption reason.
5. Run `grep -n "logout" backend/middleware/csrf.py` to confirm logout does not appear in the exempt list.
6. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `/auth/logout` is not present in `_EXEMPT_PATHS`.
- Every path in `_EXEMPT_PATHS` has an inline comment explaining why it is safe to exempt.
- All auth tests pass.
- Harness contracts `test_phase15_csrf_logout_not_exempt` and `test_phase15_csrf_exempt_paths_all_documented` pass.

**Dependencies:** None

---

### T-193: Content Security Policy for Public Share Page

**Description:**
The Security Audit found that the public share page (`/p/:slug`) has no Content Security Policy. The backend sets `X-Robots-Tag: noindex, nofollow` and the frontend renders `<meta name="robots">`, but CSP is absent. The public share page is unauthenticated, reachable by anyone with the link, and renders LLM-generated Markdown. Even with `rehype-sanitize` (T-181), a strict CSP is the last line of defense against residual XSS on this surface. CSP is frontend-controlled via Vercel response headers and must be added there; the backend public endpoint should also set it as defense-in-depth.

**Severity:** Low

**Inputs:**
- `frontend/public/_headers` or `vercel.json` — Vercel response header configuration
- `backend/routers/workspace.py` — public share endpoint (`GET /public/{slug}`)
- Harness: `test_phase15_public_share_csp_configured`

**Outputs:**
- `frontend/public/_headers` (or `vercel.json`) sets `Content-Security-Policy` for `/p/*` routes: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; frame-ancestors 'none'`
- Backend public endpoint sets the same CSP response header

**Steps:**
1. Create or update `frontend/public/_headers`:
   ```
   /p/*
     Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; frame-ancestors 'none'
     X-Frame-Options: DENY
   ```
   Alternatively configure the same header in `vercel.json` under `"headers"` for source `/p/(.*)`.
2. In `backend/routers/workspace.py`, in the `GET /public/{slug}` endpoint, add:
   ```python
   response.headers["Content-Security-Policy"] = (
       "default-src 'self'; script-src 'self'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
       "frame-ancestors 'none'"
   )
   ```
3. Verify the CSP does not break page rendering — if the frontend uses a CDN for fonts or styles, add those domains to the relevant directives.
4. Run `pnpm build` to confirm no build errors.

**Acceptance Criteria:**
- A CSP header is configured for `/p/*` routes in `_headers`, `vercel.json`, or equivalent.
- The backend `GET /public/{slug}` endpoint sets `Content-Security-Policy` in its response headers.
- The CSP includes `frame-ancestors 'none'`.
- `pnpm build` exits 0.
- Harness contract `test_phase15_public_share_csp_configured` passes.

**Dependencies:** T-169, T-181

---

### T-194: Observability Instrumentation

**Description:**
Three observability gaps from the Reliability & Operations report. First: SSE streaming failures are not instrumented — a generation that silently fails mid-stream increments no Prometheus metric, making provider incidents invisible in dashboards. Second: PDF export duration is not measured — without a histogram, the event-loop blocking identified in C-4 would not surface in production monitoring until users complain. Third: eval polling failure rate is not instrumented — the silent drop after 12 retries (M-5) means eval service degradation is completely invisible in metrics.

**Severity:** Medium

**Inputs:**
- Backend SSE streaming path (`stage_manager.py` or equivalent)
- `backend/services/pipeline/pdf_export_service.py`
- Backend eval polling / retry path
- `backend/` — Prometheus metric registry (`prometheus_client` already a dependency per CI)
- Harness: `test_phase15_sse_failure_counter_defined`, `test_phase15_pdf_export_histogram_defined`, `test_phase15_eval_failure_counter_defined`

**Outputs:**
- `Counter("specforge_sse_stream_failures_total", ...)` incremented on SSE streaming failure
- `Histogram("specforge_pdf_export_duration_seconds", ...)` observed on every PDF export
- `Counter("specforge_eval_poll_failures_total", ...)` incremented when polling gives up after max retries

**Steps:**
1. In the backend metrics module (or `main.py`), define three metrics:
   ```python
   from prometheus_client import Counter, Histogram
   sse_failure_counter = Counter(
       "specforge_sse_stream_failures_total",
       "Number of SSE streaming failures",
       ["stage_type"],
   )
   pdf_export_histogram = Histogram(
       "specforge_pdf_export_duration_seconds",
       "PDF export render duration in seconds",
       buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
   )
   eval_failure_counter = Counter(
       "specforge_eval_poll_failures_total",
       "Number of eval polling terminal failures after max retries",
       ["stage_type"],
   )
   ```
2. In the SSE streaming path, increment `sse_failure_counter.labels(stage_type=...).inc()` on any exception that terminates the stream before a completion event.
3. In `pdf_export_service.py`, wrap the `run_in_executor` call with the histogram timer:
   ```python
   with pdf_export_histogram.time():
       pdf_bytes = await asyncio.get_event_loop().run_in_executor(None, _render_pdf_sync, html_text)
   ```
4. In the eval service, when the retry limit is reached and polling gives up, call `eval_failure_counter.labels(stage_type=...).inc()`.
5. Verify all three metrics appear in `GET /metrics` output.
6. Run `uv run pytest tests/ -q`.

**Acceptance Criteria:**
- `specforge_sse_stream_failures_total`, `specforge_pdf_export_duration_seconds`, and `specforge_eval_poll_failures_total` are registered in the application.
- Each is incremented or observed at the correct call site.
- All existing backend tests pass.
- Harness contracts `test_phase15_sse_failure_counter_defined`, `test_phase15_pdf_export_histogram_defined`, and `test_phase15_eval_failure_counter_defined` pass.

**Dependencies:** T-176, T-187

---

### T-195: Missing Concurrency and Integration Tests

**Description:**
The Testing Assessment identified five missing test categories that leave the most dangerous bugs without regression coverage. (1) No concurrency test for `finalise()` — the C-1 race condition (T-174) has no automated regression guard after the fix. (2) No test asserting `generate_harness_patch()` rejects `in_progress` stages with 409 — the C-2 fix (T-174) has no regression guard. (3) No OAuth state replay test — the C-3 TOCTOU fix (T-175) has no regression guard. (4) No SSE streaming lifecycle test — disconnect handling is untested at any level. (5) No credit balance staleness test — the auth cache cross-invalidation fix (T-180) has no regression guard.

**Severity:** High

**Inputs:**
- `backend/tests/` — existing test suite
- `backend/services/pipeline/stage_manager.py` — `finalise`, `generate_harness_patch`
- `backend/services/auth_service.py` — OAuth state handling
- `backend/services/credit_service.py` and `backend/middleware/auth.py` — credit and cache invalidation
- Harness: `test_phase15_concurrency_tests_exist`

**Outputs:**
- `backend/tests/test_concurrency.py` (new file) containing all five test cases
- Tests use `pytest-asyncio` with async fixtures and existing in-memory fakes

**Steps:**
1. Create `backend/tests/test_concurrency.py`. Ensure `pytest-asyncio` is in dev dependencies.
2. **Test 1 — finalise() race:** Use `asyncio.gather` to fire two concurrent `finalise(same_stage_id)` calls. Assert that exactly one succeeds (status becomes `"finalised"`) and the other receives a guard error (409 or equivalent). The row-level lock from T-174 serialises the two calls.
3. **Test 2 — harness patch on in_progress:** Set a test stage's status to `"in_progress"`. Call `generate_harness_patch()`. Assert it raises `HTTPException` with `status_code=409` (or equivalent).
4. **Test 3 — OAuth state replay:** Call the OAuth callback handler twice with identical state and code parameters. Assert the first call succeeds and the second fails with 400/403 (state key consumed by `getdel` in T-175).
5. **Test 4 — SSE lifecycle on disconnect:** Simulate a client disconnect during streaming. Assert `_cleanup_done` is set and the generator stops yielding on the next iteration.
6. **Test 5 — credit balance invalidation:** Deduct credits for a test user. Call `invalidate_user_cache(user_id)`. Assert that the next `_USER_CACHE` lookup for that user misses (returns `None` or reflects the updated balance), not the pre-deduction value.
7. Run `uv run pytest tests/test_concurrency.py -v` to confirm all five pass.

**Acceptance Criteria:**
- `backend/tests/test_concurrency.py` exists with all five test functions.
- Test 2 asserts a 409-equivalent error on `in_progress` patch — not a silent success.
- Test 3 asserts the second OAuth callback fails — not that both succeed.
- All five new tests pass with `uv run pytest tests/test_concurrency.py -q`.
- All pre-existing backend tests continue to pass.
- Harness contract `test_phase15_concurrency_tests_exist` passes.

**Dependencies:** T-174, T-175, T-180

---

---

## Phase 16 — Final Remediation & Enterprise Hardening

**Source:** `docs/CODE_REVIEW_PASS_2.md` — Second-Pass Enterprise Code Review
**Scope:** 21 targeted remediation tasks (T-196 through T-216) addressing every finding from the second-pass review. Quality bar: FAANG-grade production hardening. No shallow tasks, no vague TODOs.
**Second-pass scores (pre-remediation):** Enterprise 5.5/10, Production 6.0/10, Security 7.5/10, Scalability 5.0/10, Reliability 6.5/10, Operational 7.0/10
**Harness contract:** `harness/tests/backend/test_phase16_final_remediation_contract.py`

---

### T-196 — Wire `SELECT FOR UPDATE` in `finalise()` + Real PostgreSQL Integration Test

**Category:** Concurrency / Data Integrity
**Severity:** Critical
**Priority:** P0
**Source finding:** CF-1 (unresolved from Phase 15 despite T-174)

**Business impact:** Two concurrent HTTP requests to finalise the same workspace stage can both pass the `status == 'draft'` guard, both advance the stage, and both charge credits. Users can be double-billed; the stage ends in an inconsistent state where downstream pipeline stages start with corrupted parent state.

**Technical impact:** `stage_manager.py:finalise()` calls `_load_stage(stage_id, db)` without `lock=True`. The `_load_stage` helper accepts `lock: bool = False` and correctly applies `.with_for_update()` when `True`, but the call site in `finalise()` omits the parameter. PostgreSQL never issues `SELECT FOR UPDATE` — two transactions can both read `status='draft'` in their snapshot window and both proceed.

**Root cause:** The T-174/Phase-15 fix added the `lock` parameter to `_load_stage` and verified the mechanism exists but did not wire `lock=True` at the `finalise()` call site. This is a one-character omission that the Phase-15 harness test missed because it checked that `_load_stage` is called with `lock=True` somewhere in the file, not specifically inside `finalise()`.

**Implementation requirements:**
1. In `backend/services/pipeline/stage_manager.py`, find the `finalise()` function body (around line 929). Change `await self._load_stage(stage_id, db)` to `await self._load_stage(stage_id, db, lock=True)`.
2. Verify that `_load_stage` with `lock=True` calls `stmt.with_for_update()` before executing the query (it already does — confirm this).
3. Write `backend/tests/test_finalise_integration.py`: a PostgreSQL integration test using `create_async_engine` + `asyncpg` + real `AsyncSession`. The test spawns two concurrent coroutines that both attempt to finalise the same stage; assert exactly one succeeds and the other receives the guard error (ValueError "cannot be finalised"). This test will FAIL on a PostgreSQL instance if `lock=True` is absent, providing real regression coverage that the mock tests cannot.
4. The integration test must be decorated with a skip marker if `TEST_DATABASE_URL` env var is not set (to allow CI to opt in via env injection).
5. Do NOT weaken the Phase-15 harness test `test_phase15_finalise_uses_select_for_update` — it is now accompanied by T-214 which deletes the misleading mock test.

**Dependencies:** T-214 (delete misleading mock test)

**Risk assessment:** LOW. The fix is one parameter addition. Regression risk: if `_load_stage(lock=True)` is called on a stage that is also loaded elsewhere in the same transaction without FOR UPDATE, PostgreSQL may deadlock. Review all callers of `_load_stage` — only `finalise()` should use `lock=True`.

**Acceptance criteria:**
- `stage_manager.py:finalise()` calls `_load_stage(stage_id, db, lock=True)`.
- `backend/tests/test_finalise_integration.py` exists and passes against a real PostgreSQL instance.
- Harness `test_phase16_finalise_uses_lock_true` passes.
- Harness `test_phase16_finalise_integration_test_file_exists` passes.

**Testing requirements:**
- Unit: existing `test_concurrency.py::test_finalise_race_second_call_raises_when_not_draft` must still pass.
- Integration: `test_finalise_integration.py` must pass against PostgreSQL with `lock=True` in place; must FAIL (demonstrate the bug) when `lock=True` is removed (negative regression test).
- Harness: two new contracts in Phase 16 harness file.

**Rollback considerations:** Reverting `lock=True` to `lock=False` is the only rollback. No schema changes involved. Monitor `pg_stat_activity` for blocking queries after deploy.

**Observability requirements:** None beyond existing stage transition metrics. The SELECT FOR UPDATE adds serialisation overhead — watch `specforge_stage_finalise_duration_seconds` (if defined) for latency increase under concurrent load.

**Documentation updates:** Update inline docstring on `finalise()` to note the pessimistic lock.

**Estimated complexity:** XS (1 line change + integration test file ~80 lines)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/pipeline/stage_manager.py` — 1-line fix
- `backend/tests/test_finalise_integration.py` — new file
- `harness/tests/backend/test_phase16_final_remediation_contract.py` — two new contracts

---

### T-197 — Enforce Circuit Breaker in `gateway.get_llm()` via `can_route()`

**Category:** Reliability / Fault Tolerance
**Severity:** Critical
**Priority:** P0
**Source finding:** CF-2

**Business impact:** When an LLM provider experiences a partial outage (timeout rate > threshold), all requests continue to be routed to it. Users experience cascading timeouts and generation failures. Provider failure detection exists in code but is never consulted — the circuit breaker provides no protection.

**Technical impact:** `provider_status.py` defines `_provider_health()` which correctly returns `"unhealthy"` after 3 consecutive failures and resets on success. `record_provider_failure()` and `record_provider_success()` are called correctly. But `gateway.get_llm()` never calls `_provider_health()` before returning an adapter. The circuit is observability-only.

**Root cause:** The circuit-breaker tracking code was added (likely Phase 12) but the enforcement hook in `gateway.get_llm()` was never wired. The tracking and the routing are two separate code paths that were never connected.

**Implementation requirements:**
1. In `backend/services/llm/provider_status.py`, add a `can_route(provider: str) -> bool` function. It calls `_provider_health(provider)` and returns `True` if the result is `"healthy"`, `False` otherwise. Export it from the module.
2. In `backend/services/llm/gateway.py`, import `can_route` from `provider_status`. In `get_llm()`, after resolving the target provider, call `can_route(provider)`. If it returns `False`, either:
   - Raise `HTTPException(status_code=503, detail=f"LLM provider '{provider}' is temporarily unavailable")`, OR
   - Fall back to the platform default provider (if the user is using a custom provider that is unhealthy). Document which behaviour is chosen in a comment.
3. When `can_route()` returns `False`, increment `specforge_llm_circuit_rejections_total` (defined in T-215 but must be wired here). The counter must be incremented at the rejection site.
4. Add `record_provider_failure()` calls where they are missing — verify all three adapter error paths call this.
5. The `_FAILURES` dict in `provider_status.py` is per-process — document this limitation in a comment (see LF-1 pattern for the auth cache).

**Dependencies:** T-215 (counter definition)

**Risk assessment:** MEDIUM. Adding circuit-breaker enforcement changes routing behaviour — a provider with a transient spike of errors (3 consecutive failures) will be rejected for all users until `record_provider_success()` resets it. Monitor `specforge_llm_circuit_rejections_total` for unexpected activation.

**Acceptance criteria:**
- `provider_status.py` exports `can_route(provider: str) -> bool`.
- `gateway.get_llm()` calls `can_route()` and raises 503 (or falls back) when it returns `False`.
- `specforge_llm_circuit_rejections_total` is incremented at the rejection site.
- Harness `test_phase16_provider_status_has_can_route` passes.
- Harness `test_phase16_gateway_consults_can_route` passes.
- Harness `test_phase16_circuit_breaker_rejection_counter_defined` passes.

**Testing requirements:**
- Unit: test `can_route()` returns `False` after 3 `record_provider_failure()` calls.
- Unit: test `gateway.get_llm()` raises 503 when `can_route()` returns `False`.
- Unit: test counter is incremented on rejection.
- Integration: end-to-end test where a provider is marked unhealthy and a generation request returns 503.

**Rollback considerations:** Remove the `can_route()` call from `gateway.get_llm()` to revert to pass-through routing. The `can_route()` function itself is harmless to leave in place.

**Observability requirements:** `specforge_llm_circuit_rejections_total` Prometheus Counter (defined in T-215). Add `provider` label to distinguish which provider's circuit is open. Log a WARN message when a request is rejected by the circuit.

**Documentation updates:** `docs/RUNBOOK.md` — circuit breaker activation detection, manual reset procedure (T-216).

**Estimated complexity:** S (2 functions + gateway wiring + 1 metric call ~60 lines total)
**Estimated implementation risk:** Medium

**Affected modules/files:**
- `backend/services/llm/provider_status.py` — add `can_route()`
- `backend/services/llm/gateway.py` — wire enforcement + counter increment
- `backend/services/pipeline/stage_manager.py` — verify all adapter error paths call `record_provider_failure()`

---

### T-198 — Batch Coverage Query in Workspace List Endpoint (N+1 Fix Verified)

**Category:** Performance / Scalability
**Severity:** High
**Priority:** P1
**Source finding:** HF-1

**Business impact:** A user with 50 workspaces triggers 51 database queries on the workspace list page (1 for workspaces + 1 per workspace for coverage). At 100 concurrent users, this is 5,100 simultaneous DB queries for one page load. The endpoint will time out under moderate load and exhaust the DB connection pool.

**Technical impact:** `workspace.py` calls `_derive_coverage_summary(workspace_id, db)` per workspace inside a list comprehension. The function accepts a single UUID and issues one `SELECT` per call. The T-178 fix was declared complete but the N+1 pattern may persist.

**Root cause:** `_derive_coverage_summary` was designed for single-workspace views. When the workspace list endpoint was added, it was reused without adapting it for batch operation. The T-178 harness test checked for the absence of a for-loop pattern but may not have caught all call forms.

**Implementation requirements:**
1. Move `_derive_coverage_summary` to a new module `backend/services/coverage_utils.py`. Export it with a batched signature: `derive_coverage_summaries(workspace_ids: list[UUID], db: AsyncSession) -> dict[UUID, CoverageSummary | None]`.
2. The implementation must issue exactly one SQL query using `WHERE stage.workspace_id IN (...)` across all workspace IDs.
3. Update `workspace.py` workspace-list handler to call `derive_coverage_summaries([w.id for w in workspaces], db)` once, then map the results onto the response objects.
4. Update `pdf_export_service.py` and `public_share_service.py` to import from `coverage_utils` (see T-206).
5. The old single-UUID convenience wrapper may be kept for single-workspace use cases (e.g., GET /workspaces/{id}) but must call the batch function internally.

**Dependencies:** T-206 (shared utility module)

**Risk assessment:** LOW. Pure SQL refactor with no schema changes. Risk: if workspace IDs list is very large (> 10,000), the IN clause may be slow on some PostgreSQL versions — add a hard limit (e.g., 500 workspaces per page) if not already present.

**Acceptance criteria:**
- `backend/services/coverage_utils.py` exists with `derive_coverage_summaries()`.
- Workspace list endpoint issues exactly 2 SQL queries (1 for workspaces + 1 batched coverage) regardless of workspace count.
- Harness `test_phase16_derive_coverage_accepts_list` passes.
- Harness `test_phase16_coverage_query_uses_in_clause` passes.

**Testing requirements:**
- Unit: test `derive_coverage_summaries([id1, id2, id3], db)` issues one SQL query (mock DB with query capture).
- Integration: test workspace list with 10 workspaces generates ≤ 3 total DB queries.
- Performance: baseline the list endpoint P99 latency before/after.

**Rollback considerations:** Revert `coverage_utils.py` and restore single-UUID calls. No schema changes.

**Observability requirements:** Add DB query count logging at DEBUG level in the workspace list handler. Track `specforge_workspace_list_db_queries` histogram if instrumentation is needed.

**Documentation updates:** Inline comment in `coverage_utils.py` explaining the batched approach and the IN-clause limit.

**Estimated complexity:** S (new module + refactor 3 callers ~120 lines)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/coverage_utils.py` — new file
- `backend/routers/workspace.py` — batch call
- `backend/services/pipeline/pdf_export_service.py` — import update
- `backend/services/public_share_service.py` — import update

---

### T-199 — Guard Empty `choices[]` in OpenAI Streaming Adapter

**Category:** Reliability / Error Handling
**Severity:** High
**Priority:** P1
**Source finding:** HF-2

**Business impact:** OpenAI streaming responses include "usage-only" chunks with an empty `choices` list (added in the API to report token counts). Any user on an OpenAI provider hits an unhandled `IndexError` mid-stream, which crashes the SSE connection. The generation appears to fail, the user loses their work, and the credit reservation is not released (double credit loss: reserved + not refunded).

**Technical impact:** `openai_adapter.py:39` executes `delta = chunk.choices[0].delta.content` with no guard on `chunk.choices` being empty. `IndexError` propagates up the async generator, raising through the SSE handler's `try/except` block.

**Root cause:** The OpenAI API specification changed to add usage-only chunks after this adapter was written. The streaming protocol was updated server-side without the client being patched.

**Implementation requirements:**
1. In `backend/services/llm/openai_adapter.py`, immediately after the `async for chunk in stream:` line, add: `if not chunk.choices: continue`.
2. Also guard against `chunk.choices[0].delta` being `None` (the API can send `delta=None` on the final chunk): `if chunk.choices[0].delta is None: continue`.
3. Also guard against `chunk.choices[0].delta.content` being `None` (normal on tool-use chunks): `content = chunk.choices[0].delta.content; if content is None: continue`.
4. Add a unit test in `backend/tests/test_openai_adapter.py` that passes a mock stream containing an empty-choices chunk and verifies no exception is raised and the chunk is silently skipped.
5. Review `anthropic_adapter.py` and `gemini_adapter.py` for equivalent patterns — their streaming APIs may have similar edge cases.

**Dependencies:** None

**Risk assessment:** VERY LOW. Defensive guard with no functional change to normal paths. The three guards are purely additive.

**Acceptance criteria:**
- `openai_adapter.py` contains `if not chunk.choices: continue` (or equivalent) before `choices[0]` access.
- Streaming does not crash on OpenAI usage-only chunks.
- Harness `test_phase16_openai_adapter_guards_empty_choices` passes.

**Testing requirements:**
- Unit: mock stream with `[chunk(choices=[]), chunk(choices=[delta(content="hello")])]` → assert output is `"hello"` with no exception.
- Unit: mock stream with `chunk(choices=[delta(content=None)])` → assert no exception, no output for that chunk.
- Manual: test against live OpenAI API with a streaming call — verify usage-only chunks are handled.

**Rollback considerations:** Remove the three guard lines. No state changes, no schema changes.

**Observability requirements:** Log a DEBUG message when an empty-choices chunk is skipped (optional but useful for debugging streaming edge cases).

**Estimated complexity:** XS (~10 lines + unit test ~30 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/llm/openai_adapter.py` — 3 guard lines
- `backend/tests/test_openai_adapter.py` — new or updated unit test

---

### T-200 — Continuous Recovery Lock Heartbeat via `asyncio.create_task`

**Category:** Reliability / Distributed Systems
**Severity:** High
**Priority:** P1
**Source finding:** HF-3

**Business impact:** If a recovery cycle processes many stale stages (e.g., after a mass deployment timeout or database incident), the cycle may run longer than the lock TTL. The second recovery worker acquires the lock and processes the same stages concurrently — double credit charges, corrupted stage states, and duplicate LLM API calls.

**Technical impact:** `stage_manager.py` calls `await refresh_recovery_lock(redis)` once before the cycle begins. A cycle processing 20 stale stages with 30-second LLM calls takes 10+ minutes; the lock TTL expires mid-cycle. The T-179 fix raised the TTL to 3× the poll interval, which helps but does not eliminate the problem for long cycles.

**Root cause:** The heartbeat was designed as a one-shot pre-check rather than a continuous background refresh. True heartbeat semantics require a looping async task.

**Implementation requirements:**
1. Define an async helper `_recovery_heartbeat(redis: Redis, lock_key: str, ttl: int, interval: int) -> None` that loops forever, calling `await redis.expire(lock_key, ttl)` every `interval` seconds (use `ttl // 3` as the interval). The loop must break on `asyncio.CancelledError`.
2. Before the recovery cycle loop starts, create the heartbeat task: `_heartbeat = asyncio.create_task(_recovery_heartbeat(redis, lock_key, _RECOVERY_LOCK_TTL, _RECOVERY_LOCK_TTL // 3))`.
3. Wrap the cycle in `try/finally: _heartbeat.cancel(); await asyncio.gather(_heartbeat, return_exceptions=True)` to ensure the task is cancelled and cleaned up even on exception.
4. Remove the pre-cycle single `refresh_recovery_lock(redis)` call (the heartbeat starts immediately and covers the cycle from t=0).

**Dependencies:** T-179 (existing TTL constants)

**Risk assessment:** LOW. The heartbeat is a pure Redis operation with minimal overhead. Cancellation in `finally` is idiomatic asyncio. Risk: if `_RECOVERY_LOCK_TTL // 3` is very small (e.g., TTL=15s → interval=5s), Redis is called frequently. Minimum TTL should be 60s to keep interval ≥ 20s.

**Acceptance criteria:**
- `stage_manager.py` defines `_recovery_heartbeat()` as an async function.
- The recovery cycle creates `asyncio.create_task(_recovery_heartbeat(...))` before the cycle loop.
- The task is cancelled and awaited in `finally`.
- Harness `test_phase16_recovery_heartbeat_uses_asyncio_task` passes.
- Harness `test_phase16_recovery_heartbeat_is_cancelled_after_cycle` passes.

**Testing requirements:**
- Unit: mock `redis.expire` as AsyncMock. Create the heartbeat task, advance the asyncio event loop by 2× interval, verify `redis.expire` was called at least twice. Cancel the task and verify it exits cleanly.
- Unit: verify the `finally` block cancels `_heartbeat` when an exception is raised mid-cycle.

**Rollback considerations:** Remove `_recovery_heartbeat` and `create_task` call. Restore the single pre-cycle `refresh_recovery_lock(redis)` call.

**Observability requirements:** Log at DEBUG level when each heartbeat refresh is issued (include remaining TTL from Redis response if available).

**Estimated complexity:** S (~50 lines including the helper function)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/pipeline/stage_manager.py` — heartbeat helper + wiring

---

### T-201 — Replace `get_event_loop()` with `get_running_loop()` + Dedicated PDF Executor

**Category:** Reliability / Code Quality
**Severity:** High
**Priority:** P1
**Source finding:** HF-4

**Business impact:** In Python 3.12+, `asyncio.get_event_loop()` in a non-async context emits a DeprecationWarning and may raise `RuntimeError`. A future Python upgrade will break PDF exports silently. Sharing the default executor with Langfuse causes thread pool starvation during concurrent PDF generation.

**Technical impact:** `pdf_export_service.py:263` calls `await asyncio.get_event_loop().run_in_executor(None, _render_pdf_sync, html_text)`. Two problems: (1) `get_event_loop()` is deprecated; use `get_running_loop()`. (2) `None` executor uses the default shared `ThreadPoolExecutor`, which is also used by Langfuse's `get_prompt()` and other deferred calls.

**Root cause:** The PDF export was written before Python 3.10 deprecations and before Langfuse's thread-pool usage was introduced. No one revisited the executor setup when Langfuse was added.

**Implementation requirements:**
1. Define a module-level dedicated executor: `_PDF_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf-export")`.
2. Replace all `asyncio.get_event_loop().run_in_executor(...)` calls with `asyncio.get_running_loop().run_in_executor(_PDF_EXECUTOR, ...)`.
3. Register `_PDF_EXECUTOR.shutdown(wait=False)` in the FastAPI lifespan `on_shutdown` hook (or use a context manager) to avoid resource leaks on process exit.
4. Add a comment explaining why `max_workers=2` — PDF rendering is CPU-bound and WeasyPrint is not thread-safe if two renders share the same HTML document object; each call creates a new Document, so 2 workers provides parallelism without contention.

**Dependencies:** None

**Risk assessment:** VERY LOW. `get_running_loop()` behaves identically to `get_event_loop()` in an async context (which is the only context `run_in_executor` should be called from). The dedicated executor reduces contention.

**Acceptance criteria:**
- `pdf_export_service.py` contains no `get_event_loop()` calls.
- `pdf_export_service.py` defines `_PDF_EXECUTOR = ThreadPoolExecutor(...)`.
- `run_in_executor(_PDF_EXECUTOR, ...)` is used for PDF rendering.
- Harness `test_phase16_pdf_uses_get_running_loop` passes.
- Harness `test_phase16_pdf_uses_dedicated_executor` passes.
- Harness `test_phase16_pdf_dedicated_executor_not_shared` passes (from T-211).

**Testing requirements:**
- Unit: verify `_PDF_EXECUTOR` is a `ThreadPoolExecutor` with `max_workers=2`.
- Unit: verify `get_event_loop` does not appear in the module source.
- Integration: concurrent PDF export test — 3 simultaneous PDF requests should all complete without thread pool exhaustion (mock WeasyPrint with a 1s sleep).

**Rollback considerations:** Restore `get_event_loop().run_in_executor(None, ...)`. No schema changes.

**Observability requirements:** Existing `specforge_pdf_export_duration_seconds` histogram (T-194) already covers PDF export latency. Add `_PDF_EXECUTOR._work_queue.qsize()` to a `/health` detail if thread pool pressure monitoring is needed.

**Estimated complexity:** XS (~20 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/pipeline/pdf_export_service.py` — executor definition + `get_running_loop()` replacement

---

### T-202 — Fix RateLimitMiddleware Redis Injection (Remove `from_url` Fallback)

**Category:** Reliability / Architecture
**Severity:** High
**Priority:** P1
**Source finding:** HF-5

**Business impact:** In production, `RateLimitMiddleware` is instantiated with `redis_client=None` (the default). The constructor creates a new, unpooled Redis connection via `Redis.from_url()`. Under concurrent load, this creates a second Redis connection pool alongside the FastAPI lifespan pool — connection count doubles, Redis max-client limits are hit, and rate limiting fails open (allowing unlimited requests).

**Technical impact:** `middleware/rate_limit.py:134` executes `self._redis = redis_client or Redis.from_url(settings.redis_url, ...)`. `main.py:134` calls `app.add_middleware(RateLimitMiddleware, redis_client=None)` because the shared `redis_client` is not available at middleware registration time (before lifespan runs). The fix requires lazy Redis access.

**Root cause:** FastAPI middleware is registered at startup before the lifespan context manager runs. The shared Redis pool doesn't exist yet when `add_middleware` is called, so `None` is passed. The fallback `from_url` was added as a workaround but creates a second pool.

**Implementation requirements:**
1. Remove the `redis_client` constructor parameter from `RateLimitMiddleware.__init__`. Remove `self._redis` assignment.
2. In `RateLimitMiddleware.__call__(self, request, call_next)`, access Redis lazily: `redis = request.app.state.redis`. Add a guard: `if redis is None: return await call_next(request)` (fail open gracefully if Redis is not yet ready).
3. Replace all `self._redis.xxx` calls inside `__call__` with `redis.xxx`.
4. Update `main.py` to remove the `redis_client=` argument from `add_middleware(RateLimitMiddleware)`.
5. Verify that the middleware does not store the Redis reference beyond the request scope (must not assign `self._redis = redis` — that would cause cross-request state sharing).

**Dependencies:** None

**Risk assessment:** MEDIUM. This changes the middleware architecture. The lazy access must be tested carefully — if `request.app.state.redis` is None during early startup (e.g., health checks before lifespan completes), the middleware must fail open safely. Add a startup readiness probe or order middleware after lifespan is ready.

**Acceptance criteria:**
- `RateLimitMiddleware.__init__` has no `redis_client` parameter.
- `RateLimitMiddleware.__call__` accesses Redis via `request.app.state.redis`.
- `main.py` does not pass `redis_client=` to `add_middleware`.
- No `Redis.from_url()` call in `middleware/rate_limit.py`.
- Harness `test_phase16_rate_limit_no_redis_from_url` passes.
- Harness `test_phase16_rate_limit_uses_app_state_redis` passes.

**Testing requirements:**
- Unit: test `__call__` with `request.app.state.redis = None` → request passes through (fail open).
- Unit: test rate limiting works correctly with a real `_FakeRedis` injected via `request.app.state.redis`.
- Integration: verify no second Redis pool is created under concurrent load (check `INFO clients connected` on Redis before/after).

**Rollback considerations:** Restore `redis_client` constructor parameter and the `from_url` fallback. Re-add `redis_client=None` to `add_middleware` call.

**Observability requirements:** Log a WARNING if `request.app.state.redis is None` (indicates the lifespan hasn't started — a configuration problem). This warning should appear at most once per worker restart.

**Estimated complexity:** S (~40 lines changed across 2 files)
**Estimated implementation risk:** Medium

**Affected modules/files:**
- `backend/middleware/rate_limit.py` — remove constructor param, add lazy access
- `backend/main.py` — remove `redis_client=` from `add_middleware`

---

### T-203 — CSRF Nonce Tracking via Redis SETNX (Close 1-Hour Replay Window)

**Category:** Security
**Severity:** High
**Priority:** P1
**Source finding:** HF-6

**Business impact:** A CSRF token stolen from a user's browser (via XSS, network sniff on HTTP, or log exposure) can be replayed by an attacker for up to 1 hour (the token's timestamp TTL). This enables CSRF attacks on any mutating endpoint during the token's lifetime — workspace deletion, generation triggers, credit purchases.

**Technical impact:** `verify_csrf_token()` validates the HMAC and checks the timestamp is within 1 hour but never records used tokens. A token is usable an unlimited number of times within its TTL. The Phase-15 fix (T-185) added a nonce to the token format but the nonce is never stored — possession of the nonce doesn't prevent replay.

**Root cause:** The nonce was added to the token generation path (T-185) but the verification path was not updated to consume and track the nonce. The fix requires a Redis round-trip on every CSRF verification.

**Implementation requirements:**
1. Update `verify_csrf_token(token: str, ...)` signature to accept `redis: Redis` as a required parameter.
2. After successful HMAC and timestamp validation, extract the nonce from the token (format: `{timestamp}.{nonce}.{signature}`).
3. Compute `nonce_key = f"csrf:nonce:{nonce}"` with expiry = remaining TTL from the timestamp (e.g., `3600 - (now - timestamp)`).
4. Call `stored = await redis.set(nonce_key, "1", nx=True, ex=remaining_ttl)`. If `stored` is `None` (key already existed — SETNX returned 0), raise `HTTPException(status_code=403, detail="CSRF token already used")`.
5. Update all callers of `verify_csrf_token()` in `middleware/csrf.py` to inject the shared Redis client (from `request.app.state.redis`).
6. This is a **breaking internal API change** — update all callers in one atomic commit.
7. Write a unit test that calls `verify_csrf_token` twice with the same token → second call must raise 403.

**Dependencies:** T-202 (ensures `request.app.state.redis` is the canonical Redis access pattern)

**Risk assessment:** HIGH. This adds a Redis round-trip to every mutating HTTP request. Performance impact: ~1ms per request under normal Redis latency. Correctness risk: if Redis is unavailable, CSRF verification fails — either fail open (security risk) or fail closed (availability risk). Recommendation: fail OPEN with a structured log WARNING if Redis is unreachable (CSRF degradation is acceptable; service unavailability is not).

**Acceptance criteria:**
- `verify_csrf_token()` accepts a `redis: Redis` parameter.
- Uses `redis.set(nonce_key, "1", nx=True, ex=remaining_ttl)` to atomically claim the nonce.
- Second call with the same token raises 403.
- Harness `test_phase16_csrf_verify_accepts_redis_param` passes.
- Harness `test_phase16_csrf_verify_uses_setnx_for_nonce` passes.

**Testing requirements:**
- Unit: same-token double-use → second call raises HTTPException(403).
- Unit: expired timestamp → raises 403 before Redis call (no unnecessary Redis round-trip on expired tokens).
- Unit: Redis unavailable (mock raises ConnectionError) → fails open with WARNING log.
- Load test: measure P99 latency impact of the Redis round-trip on a mutating endpoint at 100 RPS.

**Rollback considerations:** Remove the Redis parameter and SETNX call. Revert to HMAC+timestamp-only verification. This re-opens the replay window but restores zero-Redis-dependency verification.

**Observability requirements:** Increment `specforge_csrf_replay_rejections_total` counter when SETNX returns None (existing nonce detected). This metric distinguishes replay attacks from token generation bugs.

**Estimated complexity:** M (~60 lines across csrf.py + middleware updates + unit tests)
**Estimated implementation risk:** High (breaking API change + Redis dependency on hot path)

**Affected modules/files:**
- `backend/services/security/csrf.py` — SETNX in `verify_csrf_token()`
- `backend/middleware/csrf.py` — inject Redis into verify call
- `backend/tests/test_csrf.py` — new/updated unit tests

---

### T-204 — Add Real PostgreSQL and Redis Service Containers to CI

**Category:** Testing / CI Infrastructure
**Severity:** High
**Priority:** P1
**Source finding:** HF-7

**Business impact:** CI passes with all-mock tests while real-DB bugs go undetected. The 0003→0005 migration regression incident proves this — a column type mismatch that would have failed `alembic upgrade head` was not caught by CI because no real database existed. Future migration regressions, SELECT FOR UPDATE issues, and deadlock scenarios are invisible.

**Technical impact:** `.github/workflows/ci.yml` sets `DATABASE_URL` and `REDIS_URL` environment variables but never starts PostgreSQL or Redis service containers. All tests use in-memory mocks. `alembic upgrade head` is never run in CI — migration regressions are undetected.

**Root cause:** The CI pipeline was built for fast mock-only test runs. Real service containers were deferred as a future improvement and never added.

**Implementation requirements:**
1. Add a `services:` block to the backend test job in `ci.yml`:
   ```yaml
   services:
     postgres:
       image: postgres:15-alpine
       env:
         POSTGRES_PASSWORD: postgres
         POSTGRES_DB: specforge_test
       ports:
         - 5432:5432
       options: >-
         --health-cmd pg_isready
         --health-interval 10s
         --health-timeout 5s
         --health-retries 5
     redis:
       image: redis:7-alpine
       ports:
         - 6379:6379
       options: >-
         --health-cmd "redis-cli ping"
         --health-interval 10s
         --health-timeout 5s
         --health-retries 5
   ```
2. Update `DATABASE_URL` env var to `postgresql+asyncpg://postgres:postgres@localhost:5432/specforge_test`.
3. Update `REDIS_URL` to `redis://localhost:6379/0`.
4. Add `uv run alembic upgrade head` step before `uv run pytest`.
5. Add `--skip-integration` pytest marker support for the existing mock tests. Any test that should SKIP on real-DB CI (if any) must use this marker. New integration tests must NOT use this marker.
6. Write `backend/tests/test_credit_cycle_integration.py`: a real DB + Redis integration test that runs the full credit deduct → generation → refund cycle against the test database and verifies: (a) credit balance is updated in DB, (b) Redis cache is invalidated, (c) the ledger entry exists.

**Dependencies:** T-196 (integration test for finalise), T-203 (Redis service needed for CSRF nonce tests)

**Risk assessment:** MEDIUM. CI will be slower (service startup: ~30s). The postgres health-check retries prevent flaky failures. Risk: existing mock tests may fail against a real DB if they have incorrect SQL — this is desirable behaviour, not a bug.

**Acceptance criteria:**
- `ci.yml` has `services: postgres:` and `services: redis:` blocks.
- `alembic upgrade head` runs before pytest in CI.
- `backend/tests/test_credit_cycle_integration.py` exists and passes.
- Harness `test_phase16_ci_has_postgres_service` passes.
- Harness `test_phase16_ci_runs_alembic_upgrade` passes.
- Harness `test_phase16_ci_has_redis_service` passes.

**Testing requirements:**
- CI smoke: verify `alembic upgrade head` completes without errors against the test DB.
- Integration: credit cycle test passes end-to-end with real DB + Redis.
- Regression: all existing mock tests continue to pass.

**Rollback considerations:** Remove `services:` block from CI YAML. Remove `alembic upgrade head` step. No code changes required.

**Observability requirements:** CI workflow step timing visible in GitHub Actions UI. Add `::group::` annotations to differentiate migration and test steps.

**Documentation updates:** `README.md` — note that CI now requires PostgreSQL and Redis service containers.

**Estimated complexity:** M (~80 lines CI YAML + integration test file ~100 lines)
**Estimated implementation risk:** Medium

**Affected modules/files:**
- `.github/workflows/ci.yml` — services block + alembic step
- `backend/tests/test_credit_cycle_integration.py` — new integration test

---

### T-205 — Cancel Orphan Eval Tasks on `asyncio.shield()` Timeout

**Category:** Reliability / Resource Management
**Severity:** Medium
**Priority:** P2
**Source finding:** MF-1

**Business impact:** Under load (20+ concurrent users), 30-second eval timeouts accumulate orphaned coroutines at a rate of 1 per timeout. Each orphan holds an open HTTP connection to the eval backend and a thread pool slot. After 60 minutes of moderate load, the server can have 120+ orphaned eval connections causing connection pool exhaustion and eval service degradation.

**Technical impact:** `stage_manager.py:638-665` wraps the eval task in `asyncio.shield(eval_task)` with a 30-second timeout. When `asyncio.wait_for(asyncio.shield(...))` times out, `asyncio.shield` protects the inner task from cancellation — but no code explicitly cancels it afterward. The task continues running with no reference held.

**Root cause:** `asyncio.shield()` was added to prevent the eval task from being cancelled when the parent coroutine is cancelled (correct intent). But `shield()` semantics mean the task outlives a timeout — it requires explicit cancellation if you want it stopped on timeout.

**Implementation requirements:**
1. Retain the task reference before shielding: `eval_task = asyncio.create_task(self._run_eval(...))`.
2. Wrap the `shield` call in a `try/except asyncio.TimeoutError`:
   ```python
   try:
       await asyncio.wait_for(asyncio.shield(eval_task), timeout=30.0)
   except asyncio.TimeoutError:
       eval_task.cancel()
       # Optionally await cancellation: await asyncio.gather(eval_task, return_exceptions=True)
       logger.warning("eval task timed out and was cancelled", stage_id=str(stage_id))
   ```
3. The cancel + gather ensures the coroutine's `finally` block runs (closing the HTTP client). Without the await, the task is marked for cancellation but may not clean up before the next GC cycle.
4. Add a unit test verifying that after timeout, `eval_task.cancelled()` is True.

**Dependencies:** None

**Risk assessment:** LOW. The change only affects the timeout path. Normal (sub-30s) eval completion is unaffected. The `eval_task.cancel()` call is idempotent if the task has already completed.

**Acceptance criteria:**
- `eval_task.cancel()` is called in the `TimeoutError` handler.
- `asyncio.gather(eval_task, return_exceptions=True)` is awaited after cancel.
- Harness `test_phase16_eval_orphan_tasks_are_cancelled` passes.

**Testing requirements:**
- Unit: mock eval task that runs indefinitely. Verify that after a 30-second (fast-forward) timeout, `eval_task.cancelled()` is True.
- Unit: verify the timeout path logs a WARNING with `stage_id`.

**Rollback considerations:** Remove the `cancel()` and `gather()` calls. The orphan issue returns but is not a correctness regression (evals are best-effort).

**Observability requirements:** Log WARNING on timeout (already required above). Optionally add `specforge_eval_task_orphan_total` counter but the T-194 `specforge_eval_poll_failures_total` already covers eval failures.

**Estimated complexity:** XS (~15 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/pipeline/stage_manager.py` — eval task cancel on timeout

---

### T-206 — Move `_derive_coverage_summary` to Shared `coverage_utils.py` Module

**Category:** Code Quality / Architecture
**Severity:** Medium
**Priority:** P2
**Source finding:** MF-2

**Business impact:** The cross-module private import creates a hidden dependency between PDF export and the public share service. Any rename or refactor of `_derive_coverage_summary` in `public_share_service.py` silently breaks PDF export — the import error is only discovered at runtime when a user attempts a PDF export.

**Technical impact:** `pdf_export_service.py` imports `_derive_coverage_summary` from `public_share_service.py` using a private-function import (`from ... import _derive_coverage_summary`). Python allows this but it violates the convention that `_`-prefixed names are module-private.

**Root cause:** The coverage summary logic was first written in `public_share_service.py` and later copy-used by PDF export without refactoring it to a shared location. Both services have the same need but neither "owns" it.

**Implementation requirements:**
1. Create `backend/services/coverage_utils.py` (also required by T-198 for the batch function).
2. Move `_derive_coverage_summary` into `coverage_utils.py` and rename it to `derive_coverage_summary` (remove the private prefix since it is now a public utility).
3. Update `public_share_service.py` to import `derive_coverage_summary` from `coverage_utils`.
4. Update `pdf_export_service.py` to import `derive_coverage_summary` from `coverage_utils`.
5. Export `derive_coverage_summary` from `services/__init__.py` if one exists.
6. This task is a prerequisite for T-198 (batched coverage query).

**Dependencies:** None (but T-198 builds on this)

**Risk assessment:** VERY LOW. Pure refactor — rename + move. No logic changes. Verify import paths with `uv run ruff check .` and `pnpm tsc`.

**Acceptance criteria:**
- `backend/services/coverage_utils.py` exists and defines `derive_coverage_summary`.
- `pdf_export_service.py` does not import from `public_share_service`.
- Harness `test_phase16_coverage_utils_module_exists` passes.
- Harness `test_phase16_pdf_does_not_import_from_public_share` passes.

**Testing requirements:**
- Smoke: `python -c "from services.coverage_utils import derive_coverage_summary"` succeeds.
- Regression: all existing unit tests for PDF export and public share continue to pass.

**Rollback considerations:** Move the function back and restore the cross-module import. No schema or API changes.

**Observability requirements:** None.

**Estimated complexity:** XS (~30 lines across 3 files)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/coverage_utils.py` — new file
- `backend/services/pipeline/pdf_export_service.py` — import update
- `backend/services/public_share_service.py` — import update

---

### T-207 — Use Savepoint (`begin_nested`) in `refund()` to Isolate `IntegrityError`

**Category:** Data Integrity / Reliability
**Severity:** Medium
**Priority:** P2
**Source finding:** MF-3

**Business impact:** When `refund()` fails with an `IntegrityError` (duplicate ledger entry, constraint violation), it calls `await db.rollback()`. This rolls back the **entire outer transaction** — including the stage status update that marked the stage as complete, any content saved to the stage, and any telemetry writes that shared the session. The user's work is silently lost while the UI shows success.

**Technical impact:** `credit_service.py:171-172` catches `IntegrityError` and calls `db.rollback()`. The outer transaction (from the FastAPI route handler session scope) is rolled back. SQLAlchemy's `begin_nested()` creates a SAVEPOINT that can be rolled back independently.

**Root cause:** The `IntegrityError` handler was written without considering that `refund()` is called within a larger transaction context managed by the route handler's `db: AsyncSession` dependency.

**Implementation requirements:**
1. In `credit_service.py`, locate the `refund()` function.
2. Wrap the ledger insert and flush in a savepoint:
   ```python
   async with db.begin_nested():
       db.add(ledger_entry)
       await db.flush()
   ```
3. On `IntegrityError` from the savepoint context, the savepoint is automatically rolled back; the outer transaction continues. Re-raise as `InsufficientCreditsError` or return the existing balance if the entry is a duplicate (idempotent refund).
4. Remove the `except IntegrityError: await db.rollback()` pattern.
5. Write a unit test simulating `IntegrityError` inside `refund()` — assert the outer session is still usable (can perform a subsequent commit).

**Dependencies:** None

**Risk assessment:** LOW. SQLAlchemy's `begin_nested()` is well-tested. The only risk is that the savepoint semantics differ between `NullPool` (test) and `AsyncAdaptedQueuePool` (production) — test both.

**Acceptance criteria:**
- `credit_service.py:refund()` uses `async with db.begin_nested()` for the ledger insert.
- No `await db.rollback()` in the `refund()` function body.
- Unit test demonstrates outer transaction survives a refund `IntegrityError`.
- Harness `test_phase16_refund_uses_savepoint_not_rollback` passes.

**Testing requirements:**
- Unit: mock `db.flush()` to raise `IntegrityError`. Verify outer session is still active (can run another `db.execute()`).
- Unit: verify `InsufficientCreditsError` (or equivalent) is raised after the failed refund (not a naked `IntegrityError`).

**Rollback considerations:** Restore `except IntegrityError: await db.rollback()`. The outer-transaction corruption returns.

**Estimated complexity:** XS (~20 lines)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/credit_service.py` — `begin_nested()` in `refund()`

---

### T-208 — Wrap `TemplatesStrip` in Reusable Error Boundary (Frontend)

**Category:** Frontend / Reliability
**Severity:** Medium
**Priority:** P2
**Source finding:** MF-4

**Business impact:** A malformed API response for the templates endpoint (unexpected JSON shape, network error during render) causes an unhandled React exception that crashes the entire Dashboard page. The user is shown a blank page with no recovery path and must hard-reload, losing their current workspace selection.

**Technical impact:** `Dashboard.tsx` renders `<TemplatesStrip>` in two locations without an error boundary wrapper. React's error propagation means any throw inside the component tree crashes the nearest error boundary — which is the top-level app error boundary, causing a full-page crash.

**Root cause:** Error boundaries were added to `MarkdownRenderer` (T-181 / Phase 15) but `TemplatesStrip` was not wrapped. There is no reusable `ErrorBoundary` component in the component library.

**Implementation requirements:**
1. Create `frontend/src/components/ErrorBoundary.tsx` — a reusable class-based React error boundary. Props: `fallback?: ReactNode` (default: a generic "Something went wrong" inline message) and `onError?: (error: Error, info: ErrorInfo) => void` (optional reporting hook for Sentry). Follow the pattern from `RendererErrorBoundary` in `MarkdownRenderer.tsx` but generalize it.
2. In `Dashboard.tsx`, wrap both `<TemplatesStrip>` usages:
   ```tsx
   <ErrorBoundary fallback={<TemplatesErrorFallback />}>
     <TemplatesStrip ... />
   </ErrorBoundary>
   ```
3. Define `TemplatesErrorFallback` inline in `Dashboard.tsx` — a simple styled message: "Templates unavailable — reload to retry." with a reload button.
4. The `ErrorBoundary` component must NOT be a wrapper that silences errors; it must call `onError` (if provided) and log to console.error for debugging.
5. Export `ErrorBoundary` from `components/index.ts` (or equivalent barrel export).

**Dependencies:** None

**Risk assessment:** VERY LOW. Error boundaries are a standard React pattern. The only risk is mistyping the class component lifecycle hooks (test in Vitest).

**Acceptance criteria:**
- `frontend/src/components/ErrorBoundary.tsx` exists with `getDerivedStateFromError` and `componentDidCatch`.
- Both `<TemplatesStrip>` usages in `Dashboard.tsx` are wrapped.
- Harness `test_phase16_templates_strip_has_error_boundary` passes.
- Frontend Vitest test: `ErrorBoundary` renders fallback when child throws.

**Testing requirements:**
- Vitest: `<ErrorBoundary fallback={<div>Error</div>}><ThrowingComponent /></ErrorBoundary>` renders fallback.
- Vitest: `onError` callback is called with the error and componentStack.
- E2E (optional): simulate a 500 response from `/api/templates` — verify Dashboard remains usable.

**Rollback considerations:** Remove `ErrorBoundary` wrapper from both `TemplatesStrip` usages. No backend changes.

**Estimated complexity:** S (~80 lines: new component + Dashboard changes + tests)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `frontend/src/components/ErrorBoundary.tsx` — new file
- `frontend/src/pages/Dashboard.tsx` — wrap both TemplatesStrip usages

---

### T-209 — Pin Langfuse Docker Image to Specific Version

**Category:** Operational / Supply Chain
**Severity:** Medium
**Priority:** P2
**Source finding:** MF-5

**Business impact:** `langfuse/langfuse:latest` is pulled on every `docker compose pull`. A breaking Langfuse release can silently disable prompt management and telemetry in production without any code change in this repository. An operator running `docker compose up --pull always` after a Langfuse major release will get a broken deployment.

**Technical impact:** `docker-compose.yml:80` uses `image: langfuse/langfuse:latest`. The floating tag bypasses the version contract expected from Docker image pinning.

**Root cause:** The Langfuse service was added with `:latest` as a convenience during development and was never pinned for production safety.

**Implementation requirements:**
1. Check the current stable Langfuse release at `https://github.com/langfuse/langfuse/releases`. As of 2026-05-23, pin to the latest stable semver tag (e.g., `langfuse/langfuse:2.84.0` or the current latest).
2. Alternatively, pin to a SHA digest: `langfuse/langfuse@sha256:<digest>` for maximum immutability.
3. Update `docker-compose.yml` line 80: change `image: langfuse/langfuse:latest` to `image: langfuse/langfuse:<version>`.
4. Add a comment above the image line: `# Pin to a specific version — update deliberately. Check releases: https://github.com/langfuse/langfuse/releases`
5. Document the upgrade procedure in `docs/RUNBOOK.md` (or a separate `docs/DEPENDENCIES.md`): how to check for Langfuse updates, how to test the upgrade in a dev environment, and what breaking changes to look for.

**Dependencies:** None

**Risk assessment:** VERY LOW. This is a string change in a YAML file. Risk: if the pinned version has a known vulnerability, it will persist until manually updated. Mitigation: add Langfuse to a Dependabot or Renovate configuration.

**Acceptance criteria:**
- `docker-compose.yml` does not contain `langfuse/langfuse:latest`.
- The image tag is a specific semver (e.g., `2.84.0`) or SHA digest.
- Harness `test_phase16_langfuse_image_not_latest` passes.

**Testing requirements:**
- Smoke: `docker compose config` validates without errors.
- Manual: `docker compose pull` with the pinned tag succeeds.

**Rollback considerations:** Restore `langfuse/langfuse:latest`. This is a zero-risk rollback (the old floating tag).

**Observability requirements:** None.

**Documentation updates:** Add Langfuse upgrade procedure to `docs/RUNBOOK.md` or `docs/DEPENDENCIES.md`.

**Estimated complexity:** XS (~5 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `docker-compose.yml` — pin Langfuse image tag

---

### T-210 — Document Auth Cache Multi-Worker Limitation + Redis-Backed Cache Option

**Category:** Architecture / Documentation
**Severity:** Low
**Priority:** P3
**Source finding:** LF-1

**Business impact:** In a multi-worker deployment (Railway horizontal scaling, uvicorn `--workers=4`), `invalidate_user_cache(user_id)` only clears the cache in the worker that handled the credit deduction. Other workers continue serving stale `credit_balance` values for up to 30 seconds. A user who just purchased credits will see the old balance on their next request if it hits a different worker.

**Technical impact:** `_USER_CACHE` in `middleware/auth.py` is an in-process Python dict. `invalidate_user_cache()` calls `_USER_CACHE.pop(user_id, None)` — a local operation that has no effect on sibling processes.

**Root cause:** The auth cache was designed for single-worker deployment. Multi-worker scaling was added later without revisiting the cache invalidation strategy.

**Implementation requirements:**
1. Add a prominent comment to `middleware/auth.py` above `_USER_CACHE`:
   ```python
   # NOTE: _USER_CACHE is per-process. In multi-worker deployments (--workers > 1
   # or horizontal scaling), invalidate_user_cache() only clears the cache in the
   # worker that receives the invalidation call. Other workers may serve stale
   # credit_balance values for up to AUTH_CACHE_TTL_SECONDS (default: 30s).
   # To resolve this in multi-worker deployments, replace _USER_CACHE with a
   # Redis-backed cache keyed by user_id with a short TTL.
   ```
2. Add a `TODO(LF-1): migrate to Redis-backed user cache for multi-worker deployments` comment in the same location.
3. Create `docs/RUNBOOK.md` (if it doesn't exist; required by T-216) with a section: **Auth Cache Multi-Worker Incoherence** — explaining the limitation, symptoms (user sees stale credits after purchase), detection (check `specforge_auth_cache_hit_total` by worker label), and workaround (restart affected workers or wait 30s).
4. Optionally (P4 stretch goal): implement a Redis-backed user cache as `_RedisUserCache` with the same interface as `_USER_CACHE` and swap it in when `settings.redis_url` is set. This is **not** required for T-210 acceptance; it may be a separate task.

**Dependencies:** T-216 (RUNBOOK.md creation)

**Risk assessment:** VERY LOW. Documentation-only change + inline comment. No code behaviour changes.

**Acceptance criteria:**
- `middleware/auth.py` has a multi-worker limitation comment above `_USER_CACHE`.
- `docs/RUNBOOK.md` has a section documenting the limitation.
- Harness `test_phase16_auth_cache_limitation_documented` passes.
- Harness `test_phase16_auth_cache_runbook_entry_exists` passes.

**Estimated complexity:** XS (~10 lines comment + RUNBOOK section)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/middleware/auth.py` — inline comment
- `docs/RUNBOOK.md` — new section

---

### T-211 — Dedicate `ThreadPoolExecutor` for PDF Exports (Decouple from Langfuse)

**Category:** Performance / Reliability
**Severity:** Low
**Priority:** P3
**Source finding:** LF-2

**Business impact:** Under concurrent PDF export load (e.g., 5 users exporting simultaneously), all thread pool slots are consumed by WeasyPrint renders. Langfuse's `get_prompt()` calls — which are also dispatched to `run_in_executor(None, ...)` — are queued behind the PDF jobs. Prompt fetches time out, falling back to hardcoded prompts and degrading generation quality silently.

**Technical impact:** Both `pdf_export_service.py` and Langfuse's synchronous `get_prompt()` use `run_in_executor(None, ...)` which routes to the default asyncio `ThreadPoolExecutor`. This executor has `min(32, os.cpu_count() + 4)` threads (e.g., 36 on an 8-core machine). PDF renders are CPU-bound and slow (2-5s each), while Langfuse calls are I/O-bound and fast (100ms). Mixed workloads starve the fast I/O-bound calls.

**Root cause:** Neither PDF export nor Langfuse integration specified a dedicated executor when they were implemented. This is the "sharing the default executor" antipattern.

**Note:** T-201 also creates the dedicated PDF executor (`_PDF_EXECUTOR`). T-211 is specifically about verifying the Langfuse `run_in_executor(None)` pattern is distinct and that the separation is documented. If T-201 is implemented first, T-211 becomes a verification + documentation task.

**Implementation requirements:**
1. Verify T-201 is implemented first (`_PDF_EXECUTOR` exists in `pdf_export_service.py`).
2. Locate all `run_in_executor(None, ...)` calls in the codebase. For each:
   - If it is a Langfuse `get_prompt()` call, leave it on the default executor (it's I/O-bound and short).
   - If it is a PDF render or other CPU-bound operation, replace `None` with `_PDF_EXECUTOR`.
3. Add a comment in `pdf_export_service.py` at the executor definition: `# Dedicated executor isolates CPU-bound WeasyPrint rendering from Langfuse I/O calls.`
4. Add a comment wherever the default executor is used for Langfuse: `# Default executor: Langfuse get_prompt() is I/O-bound (fast), not CPU-bound.`

**Dependencies:** T-201 (defines `_PDF_EXECUTOR`)

**Risk assessment:** VERY LOW. Documentation + confirmation task. The actual executor change is in T-201.

**Acceptance criteria:**
- No `run_in_executor(None, ...)` calls in `pdf_export_service.py`.
- The dedicated `_PDF_EXECUTOR` is used for all PDF rendering.
- Harness `test_phase16_pdf_dedicated_executor_not_shared` passes.

**Estimated complexity:** XS (~5 lines verification + comments)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/pipeline/pdf_export_service.py` — verify dedicated executor, add comment

---

### T-212 — Delete `test_finalise_concurrent_tasks_only_one_advances` (False Confidence)

**Category:** Testing / Code Quality
**Severity:** Low (impact of keeping: High)
**Priority:** P1 (must ship with T-196)
**Source finding:** LF-3

**Business impact:** The test creates false confidence that the CF-1 race condition is handled. It has been blocking proper acknowledgment of the SELECT FOR UPDATE gap for the duration of Phase 15. Any engineer running the test suite sees green and concludes the concurrency bug is fixed, even though it is not.

**Technical impact:** `test_concurrency.py::test_finalise_concurrent_tasks_only_one_advances` uses a `_RacingDB` whose `execute()` method manually mutates `stage.status = "finalised"` on the second call. This simulates the outcome of a race without exercising any locking mechanism. The test passes whether or not `lock=True` is in `finalise()`. It is a tautological test.

**Root cause:** The test was written with good intent (simulate the race scenario) but the mock approach cannot validate pessimistic locking. Only a real PostgreSQL transaction can validate that SELECT FOR UPDATE serialises concurrent reads.

**Implementation requirements:**
1. Delete `test_finalise_concurrent_tasks_only_one_advances` from `backend/tests/test_concurrency.py`.
2. Keep `test_finalise_race_second_call_raises_when_not_draft` — this test is valid: it verifies that `finalise()` raises when the stage is already finalised. It tests the guard logic independently of locking.
3. The replacement is `test_finalise_integration.py` from T-196.
4. Add a comment in `test_concurrency.py` where the deleted test was: `# NOTE: The concurrent finalise race is tested in test_finalise_integration.py using a real PostgreSQL transaction with SELECT FOR UPDATE.`

**Dependencies:** T-196 (integration test must exist before this is deleted)

**Risk assessment:** VERY LOW. Deleting a false-positive test. The race is tested more accurately in T-196's integration test.

**Acceptance criteria:**
- `test_finalise_concurrent_tasks_only_one_advances` does not exist in `test_concurrency.py`.
- `test_finalise_race_second_call_raises_when_not_draft` still exists and passes.
- Harness `test_phase16_misleading_mock_finalise_test_is_gone` passes.

**Estimated complexity:** XS (delete 45 lines + add comment)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/tests/test_concurrency.py` — delete one test function, add replacement comment

---

### T-213 — Add Composite Index Migration for `eval_results(stage_version_id, created_at DESC)`

**Category:** Performance / Database
**Severity:** Low
**Priority:** P3
**Source finding:** LF-4

**Business impact:** The eval polling query runs on every stage generation (4 times per workspace pipeline — once per stage type). It filters by `stage_version_id` and orders by `created_at DESC` to find the most recent eval. Without a composite index, PostgreSQL performs a sequential scan. At 10,000 eval rows (a few hundred active workspaces), this query takes 50ms+. At 1M rows (moderate scale), it exceeds 500ms, making the polling loop timeout before evals are returned.

**Technical impact:** No migration adds a composite index on `eval_results(stage_version_id, created_at DESC)`. The latest migration is `0011_workspace_public_shared_at.py`. A new migration must be added.

**Root cause:** The eval results table index was not planned during the initial schema design. The table was treated as an append-only log without considering the polling query access pattern.

**Implementation requirements:**
1. Create `backend/migrations/versions/0012_eval_results_composite_index.py` using the Alembic migration template.
2. The `upgrade()` function must execute:
   ```python
   op.create_index(
       "ix_eval_results_stage_version_created_at",
       "eval_results",
       ["stage_version_id", sa.text("created_at DESC")],
       postgresql_using="btree",
   )
   ```
3. The `downgrade()` function must drop the index: `op.drop_index("ix_eval_results_stage_version_created_at", "eval_results")`.
4. The migration must be idempotent on a database that already has the index (use `if_exists=True` on the drop).
5. Generate the migration with `uv run alembic revision --autogenerate -m "eval_results_composite_index"` and then manually adjust to add the DESC direction (autogenerate may not capture this).
6. Run `uv run alembic upgrade head` locally to verify the migration applies without error.

**Dependencies:** None

**Risk assessment:** LOW. Adding an index is non-blocking on PostgreSQL (CREATE INDEX CONCURRENTLY is preferred for production — note this in the migration comment). However, Alembic's `op.create_index` does not support CONCURRENTLY by default; use `postgresql_concurrently=True` parameter or note in the RUNBOOK that this migration requires a maintenance window on large tables.

**Acceptance criteria:**
- `backend/migrations/versions/0012_eval_results_composite_index.py` exists.
- The migration creates `ix_eval_results_stage_version_created_at` on `eval_results`.
- `alembic upgrade head` and `alembic downgrade -1` both succeed without error.
- Harness `test_phase16_eval_results_composite_index_migration_exists` passes.

**Testing requirements:**
- Apply migration to the test database (from T-204 CI). Verify index exists via `\d eval_results` in psql.
- Run `alembic downgrade -1` — verify index is dropped. Run `alembic upgrade head` again — verify index re-created.
- Query plan: `EXPLAIN ANALYZE SELECT * FROM eval_results WHERE stage_version_id = $1 ORDER BY created_at DESC LIMIT 1` must show `Index Scan` not `Seq Scan`.

**Rollback considerations:** `alembic downgrade -1` drops the index. The downgrade target is listed in the migration's `down_revision`.

**Observability requirements:** None — the index improvement will be visible in PostgreSQL's `pg_stat_user_indexes` (index scans vs sequential scans ratio).

**Estimated complexity:** XS (~30 lines migration file)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/migrations/versions/0012_eval_results_composite_index.py` — new migration

---

### T-214 — Delete False-Confidence Mock Concurrency Test (Harness Enforcement)

**Category:** Testing / Code Quality
**Severity:** Low
**Priority:** P1 (ships with T-196)
**Source finding:** LF-3 (same finding as T-212 but at harness-contract level)

**Note:** T-212 is the implementation task (delete the test). T-214 is the harness-contract enforcement task — the harness test `test_phase16_misleading_mock_finalise_test_is_gone` ensures the deletion cannot be accidentally reverted.

**Implementation requirements:**
1. T-212 must be completed first.
2. The Phase 16 harness contract already includes `test_phase16_misleading_mock_finalise_test_is_gone` which permanently enforces the deletion.
3. No additional implementation required for T-214 beyond T-212 — this task exists to ensure the harness contract is explicitly tracked as a deliverable.

**Acceptance criteria:**
- Harness `test_phase16_misleading_mock_finalise_test_is_gone` passes (green = test is gone from codebase).
- `test_finalise_race_second_call_raises_when_not_draft` still passes (valid test preserved).

**Dependencies:** T-212

**Estimated complexity:** XS (harness test already written in Phase 16 contract file)

---

### T-215 — Add `specforge_llm_circuit_rejections_total` Prometheus Counter

**Category:** Observability
**Severity:** Low
**Priority:** P2
**Source finding:** CF-2 (observability gap)

**Business impact:** Without the circuit rejection counter, operators cannot tell whether the circuit breaker has ever activated in production. An open circuit is invisible in dashboards. When a provider has an outage, operators cannot distinguish "users are seeing errors because the circuit is open and protecting them" from "the circuit never activated and the provider is still being hit."

**Technical impact:** `provider_status.py` and `gateway.py` have no Prometheus instrumentation for circuit breaker activations. The counter must be defined and incremented at the `can_route() == False` site.

**Implementation requirements:**
1. In `backend/services/llm/provider_status.py` (or `backend/metrics.py` if a centralized metrics module exists), define:
   ```python
   CIRCUIT_REJECTIONS = Counter(
       "specforge_llm_circuit_rejections_total",
       "Number of LLM requests rejected because the circuit breaker is open",
       ["provider"],
   )
   ```
2. In the code path where `can_route()` returns `False` (either inside `can_route()` itself or in `gateway.get_llm()`), call `CIRCUIT_REJECTIONS.labels(provider=provider).inc()`.
3. Add the counter to `docs/RUNBOOK.md` alerting section: "Alert if `specforge_llm_circuit_rejections_total > 0` — a circuit breaker has activated. Check provider health."
4. Add a Grafana dashboard query (or just document the PromQL): `rate(specforge_llm_circuit_rejections_total[5m])` grouped by `provider`.

**Dependencies:** T-197 (can_route() must exist to have a rejection site)

**Risk assessment:** VERY LOW. Prometheus counter definition and increment. Zero risk.

**Acceptance criteria:**
- `specforge_llm_circuit_rejections_total` Counter is defined with a `provider` label.
- The counter is incremented when `can_route()` returns `False`.
- Harness `test_phase16_circuit_breaker_rejection_counter_defined` passes.
- Harness `test_phase16_circuit_rejection_counter_incremented_on_rejection` passes.

**Estimated complexity:** XS (~15 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/llm/provider_status.py` or `backend/metrics.py` — counter definition
- `backend/services/llm/gateway.py` or `provider_status.py` — counter increment

---

### T-216 — Create `docs/RUNBOOK.md` with CF-1, CF-2, LF-1 Operational Procedures

**Category:** Operational / Documentation
**Severity:** Low
**Priority:** P2
**Source finding:** Cross-cutting (all Critical and High findings)

**Business impact:** When the SELECT FOR UPDATE deadlocks, the circuit breaker activates, or a multi-worker cache incoherence incident occurs, on-call engineers need documented incident response procedures. Without a runbook, incident resolution is ad-hoc and slow. A 15-minute production incident becomes a 2-hour outage because no one knows the rollback or reset procedure.

**Technical impact:** No `docs/RUNBOOK.md` exists in the repository. The document must be created as a living reference for Phase 16 operational changes.

**Implementation requirements:**
Create `docs/RUNBOOK.md` with the following sections (minimum):

1. **Circuit Breaker (CF-2):**
   - Detection: `specforge_llm_circuit_rejections_total` > 0 in Prometheus
   - Symptoms: users receive 503 "LLM provider temporarily unavailable" for affected provider
   - Reset procedure: call `reset_provider_failures(provider)` via admin endpoint or Redis CLI (`DEL specforge:llm:failures:<provider>`)
   - SLA impact: users on custom `<provider>` keys receive 503; users on platform default key receive 200 (platform key uses a different provider)
   - Escalation: if all providers are unhealthy, escalate to LLM provider engineering contact

2. **Finalise Race (CF-1):**
   - Detection: two `CreditLedger` entries for the same `workspace_id` + `stage_type` within 1 second in the DB
   - Symptoms: user reports unexpected credit deduction; stage shows conflicting generation results
   - Recovery: identify duplicate ledger entries via SQL; refund the second charge via admin credit endpoint; reset stage to `draft` status
   - Prevention: confirm `_load_stage(lock=True)` is in place post-deploy

3. **Auth Cache Multi-Worker Incoherence (LF-1):**
   - Detection: user sees stale credit balance after purchase (check `credit_balance` in `/api/me` vs DB)
   - Symptoms: user purchased credits but UI shows old balance for up to 30 seconds
   - Workaround: advise user to wait 30 seconds or hard-reload; the cache TTL will expire
   - Long-term fix: see T-210 — migrate to Redis-backed user cache

4. **Credits Refund Procedure:**
   - How to issue manual credit refund via admin endpoint
   - How to verify the ledger entry was created correctly
   - Escalation threshold (> 10 affected users → incident P1)

5. **Migration Runbook:**
   - How to run `alembic upgrade head` safely in production (Railway deploy process)
   - How to roll back a migration with `alembic downgrade -1`
   - Note on the eval_results composite index (T-213): may require maintenance window on large tables

**Dependencies:** T-210 (requires RUNBOOK.md for LF-1 documentation), T-197 (circuit breaker must exist before documenting it)

**Risk assessment:** VERY LOW. Documentation-only. No code changes.

**Acceptance criteria:**
- `docs/RUNBOOK.md` exists with sections for circuit breaker, finalise race, auth cache, credits refund, and migrations.
- Harness `test_phase16_runbook_covers_circuit_breaker_procedure` passes.
- Harness `test_phase16_runbook_covers_finalise_race_procedure` passes.
- Harness `test_phase16_runbook_has_required_sections` passes.
- Harness `test_phase16_auth_cache_runbook_entry_exists` passes.

**Estimated complexity:** S (~200-line markdown document)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `docs/RUNBOOK.md` — new file

---

## Phase 17 — Final Hardening & Enterprise Closure

> Tasks T-217 through T-225. Source: third-pass enterprise code review (2026-05-25).
> Every task maps to a named finding. No finding is left unaddressed.

### Phase 17 Finding-to-Task Coverage Map

| Finding | Severity | Task | Description |
|---------|----------|------|-------------|
| C-1 | Critical | T-217 | generate() stream timeouts do not trip circuit breaker |
| H-1 | High | T-218 | Tasks prompt regression — pre-existing test failure |
| H-2 | Medium | T-219 | Credit `_invalidate()` called before `db.commit()` |
| H-3 | Medium | T-225 | Rate limit bypasses all tiers when Redis is None on startup |
| M-2 | Medium | T-220 | No `specforge_llm_circuit_state` Gauge for current open/closed state |
| M-4 | Medium | T-221 | Langfuse SDK/server compatibility — silent failure on version skew |
| L-1 | Low | T-223 | `_INSTANCES` adapter cache has no TTL — stale connections served indefinitely |
| L-4 | Low | T-222 | `sliding_window_check()` has no `RedisError` fallback in stage_manager |
| Ops | Medium | T-224 | No `ENCRYPTION_MASTER_KEY`/`CSRF_SECRET`/JWT rotation procedure in RUNBOOK |
| L-2 | Low | Accepted design | CSRF fail-open during Redis outage — documented trade-off |
| L-3 | Low | Accepted design | Public endpoint IP-only rate limit — design decision |
| M-1 | Medium | RUNBOOK §7 | Migration lock risk — already covered by T-216 |
| M-3 | Low | RUNBOOK §4 | Per-process user cache — already documented by T-210/T-216 |

---

### T-217 — Fix Circuit Breaker Gap: Stream Timeouts in generate() Do Not Call record_provider_failure

**Category:** Reliability / Circuit Breaker
**Severity:** Critical
**Priority:** P0
**Source finding:** C-1 (third-pass review)

**Business impact:** The circuit breaker is the primary reliability defense against provider outages. When a provider starts hanging (most common failure mode), `generate()` timeouts should accumulate into `_FAILURES` and trip the circuit after 3 consecutive failures. Without this fix, the circuit never trips on stream timeouts. Every request to a hung provider burns user credits and waits for the 360-second wall-clock timeout before returning an error. Users experience sustained outages instead of the intended fail-fast 503 behavior.

**Technical impact:** `asyncio.timeout(stream_timeout)` fires by injecting `CancelledError` (a `BaseException`) into the running generator. `InstrumentedAdapter.stream()` catches only `Exception` — `CancelledError` bypasses this guard entirely. The outer `except (ProviderError, TimeoutError)` block in `generate()` (lines 635–651) handles the resulting `TimeoutError` but does not call `record_provider_failure()`. Contrast: `refine()` and `generate_harness_patch()` both explicitly call `record_provider_failure()` in their equivalent except blocks (lines 1324–1328).

**Root cause:** The `generate()` except block was written before the circuit breaker was introduced (T-197). When T-197 wired `record_provider_failure()` into `refine()` and `generate_harness_patch()`, the `generate()` path was missed.

**Verified by:** Python 3.12 simulation — `asyncio.timeout(0.1)` + adapter sleeping 10s → `CancelledError` propagates, bypasses `except Exception`, `record_provider_failure` never called (confirmed in review session).

**Implementation requirements:**
1. Open `backend/services/pipeline/stage_manager.py`.
2. Locate the inner `except (ProviderError, TimeoutError) as exc:` block inside `generate()` (approximately line 635). This block currently: increments `SSE_STREAM_FAILURES`, refunds credits, resets stage status, and raises `ProviderTimeoutError`.
3. Add two lines at the **start** of this except block, before the existing `SSE_STREAM_FAILURES.inc()` call:
   ```python
   from services.llm.provider_status import record_provider_failure  # noqa: PLC0415
   record_provider_failure(route.provider, exc)
   ```
4. Add a one-line comment referencing the finding: `# Record failure so the circuit breaker trips after 3 consecutive errors. C-1 — T-217.`
5. No other changes to `generate()`. Do not modify `refine()` or `generate_harness_patch()` — they are already correct.
6. Run: `cd backend && uv run pytest tests/test_circuit_breaker.py -v` — all CB-* tests must continue passing.
7. Write one new test in `tests/test_circuit_breaker.py` named `test_generate_stream_timeout_records_provider_failure` that: mocks `record_provider_failure`, simulates a `TimeoutError` in the `generate()` except block, and asserts `record_provider_failure` was called with the correct provider. (Unit-level mock is sufficient; no real AsyncSession needed.)

**Dependencies:** T-197 (circuit breaker must exist)

**Risk assessment:** VERY LOW. One import + one function call. Exactly mirrors the pattern already present in two other methods. The `record_provider_failure()` function is side-effect-only (increments a counter in a dict); it cannot raise. No credit logic, no DB, no async operations touched.

**Acceptance criteria:**
1. `cd backend && uv run pytest tests/test_circuit_breaker.py -v` — all tests green including new `test_generate_stream_timeout_records_provider_failure`.
2. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_generate_except_block_calls_record_provider_failure -v` passes.
3. Manual smoke: configure Anthropic with an invalid API key, trigger a generate → confirm `specforge_llm_circuit_rejections_total{provider="anthropic"}` increments after 3 failures.
4. `cd backend && uv run ruff check services/pipeline/stage_manager.py` — no lint violations.

**Testing requirements:**
- Unit test using `unittest.mock.patch` for `record_provider_failure` — verify call count and arguments.
- Existing `test_circuit_breaker.py` CB-1 through CB-8 tests must remain green (regression guard).
- Harness contract test scans the `generate()` body for `record_provider_failure` call.

**Observability requirements:** No new metrics. The existing `specforge_llm_circuit_rejections_total` and `specforge_sse_stream_failures_total` counters now cover the timeout path.

**Rollback considerations:** A one-line revert of the two added lines is sufficient. No DB, no config, no migration.

**Estimated complexity:** XS (~5 lines + 30-line test)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/pipeline/stage_manager.py` — add `record_provider_failure()` call in `generate()` except block
- `backend/tests/test_circuit_breaker.py` — add `test_generate_stream_timeout_records_provider_failure`

---

### T-218 — Fix Tasks Stage User Prompt Regression (Pre-existing Test Failure)

**Category:** Testing / Prompt Quality
**Severity:** High
**Priority:** P0
**Source finding:** H-1 (third-pass review)

**Business impact:** `test_tasks_prompt_is_ordered_traceable_and_agent_executable` has failed since a Phase 14 tasks prompt rewrite. This failure means CI's `--cov-fail-under=80` may be failing, and a quality guard for the tasks stage LLM prompt has been silently absent. The missing instruction — "For each plan section or contract, [trace to tasks]" — was a coverage axis ensuring the LLM traces plan-level architectural contracts (not just spec requirements) to generated tasks. Without it, generated TASKS.md documents risk missing plan-level implementation details.

**Technical impact:** `tasks.build_user_prompt()` no longer contains the phrase `"For each plan section or contract"`. The test at `test_prompt_builder.py:249` asserts this phrase is present. The phrase was in an earlier version of the user prompt's coverage-map step and was lost during the Phase 14 system prompt expansion.

**Root cause:** Phase 14 added a detailed Spec/Plan/Harness coverage mandate to `SYSTEM_PROMPT` but did not carry the "For each plan section or contract" coverage axis into the `build_user_prompt()` user message. The test was not updated to match, and the change was not caught in CI.

**Implementation requirements:**
1. Open `backend/prompts/tasks.py`.
2. Locate `build_user_prompt()`, specifically step 0 of the numbered instructions. Step 0 currently reads:
   ```
   0. Before writing any task, build your full coverage map internally:
      - Every FR/NFR/SEC ID → which task addresses it?
      - Every harness test path → which task makes it pass?
      - Every plan contract (endpoint, schema, module boundary) → which task implements it?
   ```
3. Add a fourth bullet at the end of step 0 that contains the exact phrase `"For each plan section or contract"`:
   ```
      - For each plan section or contract (architecture decision, module boundary, API endpoint, schema, migration), confirm at least one task addresses it — no plan artifact may be orphaned from the task list.
   ```
4. The phrase `"For each plan section or contract"` must appear in the returned string of `build_user_prompt()` — it will be part of step 0's bullet, which is inside the `f"""..."""` template.
5. Run: `cd backend && uv run pytest tests/test_prompt_builder.py -v` — all 12 tests must pass (was 11 pass + 1 fail before this fix).
6. Run: `cd backend && uv run pytest tests/ -q` — confirm total pass count increases from 496 to 497.

**Dependencies:** None

**Risk assessment:** VERY LOW. String addition to a prompt template. No DB, no runtime logic, no security impact. The prompt change adds a quality instruction; it does not remove or weaken any existing instruction.

**Acceptance criteria:**
1. `cd backend && uv run pytest tests/test_prompt_builder.py::test_tasks_prompt_is_ordered_traceable_and_agent_executable -v` passes.
2. `cd backend && uv run pytest tests/ -q` — exactly 0 failures (previously 1).
3. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_tasks_build_user_prompt_contains_plan_section_instruction -v` passes.

**Testing requirements:**
- The existing test at `test_prompt_builder.py:249` is the primary acceptance test — it must pass green.
- No new tests required (the existing test is the full coverage for this fix).

**Observability requirements:** None.

**Rollback considerations:** Revert the one bullet addition. The test will fail again (same as before) — this is acceptable if reverting a prompt change for unrelated reasons.

**Estimated complexity:** XS (~3 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/prompts/tasks.py` — `build_user_prompt()`: add one bullet to step 0 coverage map instructions

---

### T-219 — Fix Credit Cache Invalidation Timing: Invalidate After db.commit(), Not Only After db.flush()

**Category:** Data Correctness / Credit Accounting
**Severity:** Medium
**Priority:** P1
**Source finding:** H-2 (third-pass review)

**Business impact:** Between `credit_service.deduct()` calling `_invalidate()` (after flush) and the outer `db.commit()` in stage_manager, a concurrent `get_balance()` call reads the uncommitted (pre-deduction) balance from PostgreSQL (READ COMMITTED isolation), then re-populates Redis with the stale value. For up to 5 minutes after this race, users' displayed balance is incorrectly high. `_assert_visible_credit_balance()` in stage_manager may pass with the stale balance, proceeding to `deduct()` which correctly raises `InsufficientCreditsError` — causing generation to start then fail mid-flight with a confusing "insufficient credits" error.

**Technical impact:** No actual credit loss occurs (`SELECT FOR UPDATE` in `deduct()` is the hard guard). The impact is UX degradation: a user who has just spent their last credits may see a spinner start, then receive a credits error instead of an immediate pre-flight rejection. In multi-worker deployments, the staleness window is also per-process (30s `_USER_CACHE` TTL), compounding the issue.

**Root cause:** `credit_service._invalidate()` is designed to be called after `db.flush()` (within the transaction) to eagerly clear the cache. However, the commit hasn't happened, so any concurrent read re-populates the cache from the uncommitted DB state. The correct pattern for a write-through cache is: invalidate AFTER commit, not after flush.

**Implementation requirements:**
1. In `backend/services/credit_service.py`, add a public method immediately below `_invalidate()`:
   ```python
   async def invalidate(self, user_id: UUID) -> None:
       """Public alias for post-commit cache invalidation.

       Call this immediately after ``db.commit()`` in any code path that
       first called ``deduct()``, ``credit()``, or ``refund()``.  The first
       invalidation (inside those methods, after flush) clears the cache
       eagerly.  This second call ensures any concurrent ``get_balance()``
       that re-populated the cache during the flush→commit window is
       immediately evicted after the true balance is committed.  H-2 — T-219.
       """
       await self._invalidate(user_id)
   ```
2. In `backend/services/pipeline/stage_manager.py`, locate **every** `await db.commit()` that follows a `credit_service.deduct()` or `credit_service.refund()` call. Add `await credit_service.invalidate(user.id)` (or the relevant user_id variable) immediately after each such commit. The sites are:
   - `generate()` line ~585: `await db.commit()` after `deduction = await credit_service.deduct(...)` → add `await credit_service.invalidate(user.id)` on the next line.
   - `generate()` line ~644: `await db.commit()` in the `except (ProviderError, TimeoutError)` handler after `await credit_service.refund(db, deduction.id)` → add `await credit_service.invalidate(user.id)`.
   - `generate()` line ~660: `await db.commit()` after validation failure refund → add `await credit_service.invalidate(user.id)`.
   - `refine()`: locate the same pattern (deduct → commit sites) and add the post-commit invalidation.
   - Any other method in `stage_manager.py` that calls `credit_service.deduct()` or `credit_service.refund()` followed by `db.commit()`.
3. In the cleanup `finally` block of `generate()` that uses `async with AsyncSessionLocal() as cleanup_db:` and calls `await credit_service.refund(cleanup_db, deduction.id)` — this block uses a new session. After the refund, the cleanup_db session commits implicitly when the `async with` exits. Add explicit `await credit_service.invalidate(original.user_id)` after the `async with` block (or move cleanup_db.commit() to be explicit and add invalidation after it).
4. Add a comment at every new `invalidate()` call site: `# Post-commit cache eviction — H-2 — T-219.`
5. Run: `cd backend && uv run pytest tests/ -q` — all tests pass.

**Dependencies:** None (no schema changes, no migration)

**Risk assessment:** LOW. `invalidate()` is a cache eviction (Redis DELETE). It is idempotent and safe to call redundantly. The worst case of calling it twice is one extra Redis round-trip. No DB writes, no business logic changes, no credit flow changes.

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_credit_service_has_public_invalidate_method -v` passes.
2. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_stage_manager_calls_invalidate_after_commit -v` passes.
3. `cd backend && uv run pytest tests/ -q` — all tests pass.
4. Code review: no `await db.commit()` line following a credit_service write in stage_manager.py is unaccompanied by `credit_service.invalidate()`.

**Testing requirements:**
- Harness contract tests (string scans): `public_invalidate_method` exists in credit_service.py; `credit_service.invalidate` appears near `db.commit()` in stage_manager.py.
- No new unit test required beyond the harness contract. The existing `test_credit_service.py` tests should continue passing.

**Observability requirements:** None — the existing `credit.cache_invalidation_failed` log entry covers failures.

**Rollback considerations:** Remove the new `invalidate()` method and the post-commit calls. No DB impact.

**Estimated complexity:** S (~20 lines across 2 files)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/credit_service.py` — add public `invalidate(user_id)` method
- `backend/services/pipeline/stage_manager.py` — add `credit_service.invalidate()` after every `db.commit()` following a credit write

---

### T-220 — Add specforge_llm_circuit_state Gauge for Real-Time Circuit Open/Closed Status

**Category:** Observability
**Severity:** Medium
**Priority:** P2
**Source finding:** M-2 / Observability gap (third-pass review)

**Business impact:** The existing `specforge_llm_circuit_rejections_total` counter (T-215) only shows that rejections occurred — it cannot tell an operator whether a provider's circuit is currently open. When an on-call engineer receives a "users can't generate specs" alert, they need to know instantly whether the circuit is open (provider down, expected behavior) or closed (circuit not protecting users, something else is wrong). A Gauge resolves this in seconds.

**Technical impact:** `provider_status.py` has no Gauge for circuit state. `_FAILURES` is the authoritative state but has no Prometheus representation of its current open/closed status. The Gauge should be updated synchronously inside `record_provider_failure()` and `record_provider_success()` — both are synchronous functions and already update `_FAILURES`.

**Root cause:** T-215 added the rejection Counter but did not add a complementary Gauge for observability of the current state. These are two different observability instruments: Counter answers "how many rejections happened?" and Gauge answers "is the circuit open right now?"

**Implementation requirements:**
1. In `backend/services/llm/provider_status.py`, immediately below the `CIRCUIT_REJECTIONS` Counter definition (approximately line 49), define:
   ```python
   # Gauge for current circuit breaker state per provider.  0 = closed (healthy),
   # 1 = open (rejecting requests).  Updated synchronously in record_provider_failure()
   # and record_provider_success().  Per-process; under multi-worker deployment,
   # use max(specforge_llm_circuit_state) by provider in Grafana.  T-220.
   CIRCUIT_STATE = Gauge(
       "specforge_llm_circuit_state",
       "Current circuit breaker state per LLM provider (0=closed, 1=open)",
       ["provider"],
   )
   ```
2. Add `Gauge` to the `from prometheus_client import Counter` import at the top of the file: `from prometheus_client import Counter, Gauge`.
3. In `record_provider_failure(provider, exc)`: after updating `_FAILURES`, add:
   ```python
   CIRCUIT_STATE.labels(provider=provider).set(1 if _circuit_open(provider) else 0)
   ```
4. In `record_provider_success(provider)`: after `_FAILURES.pop(provider, None)`, add:
   ```python
   CIRCUIT_STATE.labels(provider=provider).set(0)
   ```
5. In `docs/RUNBOOK.md` §1 (Circuit Breaker), add the following PromQL beneath the existing `rate(specforge_llm_circuit_rejections_total[5m])` entry:
   ```
   # Current open/closed state per provider (0=closed, 1=open):
   specforge_llm_circuit_state

   # Alert when any provider circuit is open:
   max by (provider) (specforge_llm_circuit_state) == 1
   ```
6. Run: `cd backend && uv run pytest tests/test_circuit_breaker.py -v` — all CB-* tests pass.

**Dependencies:** T-215 (CIRCUIT_REJECTIONS must exist; Gauge import already has Counter so structure is established)

**Risk assessment:** VERY LOW. Pure observability addition. Gauge `set()` is side-effect-only, cannot raise, cannot affect business logic.

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_circuit_state_gauge_defined -v` passes.
2. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_circuit_state_updated_on_failure_and_success -v` passes.
3. `cd backend && uv run pytest tests/test_circuit_breaker.py -v` — all existing CB-* tests green.
4. RUNBOOK.md §1 contains `specforge_llm_circuit_state` PromQL.

**Testing requirements:**
- Harness contract: `CIRCUIT_STATE` Gauge definition present in provider_status.py.
- Harness contract: `CIRCUIT_STATE.labels` called inside `record_provider_failure` and `record_provider_success`.
- Harness contract: RUNBOOK.md §1 contains `specforge_llm_circuit_state`.

**Observability requirements:** This task IS the observability addition. No additional instrumentation beyond the Gauge itself.

**Rollback considerations:** Remove the Gauge definition and the two `.set()` calls. No DB, no config.

**Estimated complexity:** XS (~15 lines + RUNBOOK edit)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/llm/provider_status.py` — add `CIRCUIT_STATE` Gauge, update `record_provider_failure()` and `record_provider_success()`
- `docs/RUNBOOK.md` — add PromQL for circuit_state to §1

---

### T-221 — Add Langfuse Startup Health Check to Detect SDK/Server Version Skew

**Category:** Reliability / Observability
**Severity:** Medium
**Priority:** P2
**Source finding:** M-4 (third-pass review)

**Business impact:** The Langfuse SDK is pinned at `langfuse>=2.60,<3` while the server is at `langfuse/langfuse:3.175.0`. The SDK's exception-swallowing design means any protocol-level incompatibility is silently logged as `langfuse.create_trace.failed` and never surfaces to operators. Without a startup check, a breaking change in the server API (e.g., deprecation of v2 ingestion endpoints) would cause 100% trace loss for weeks before anyone notices. The startup check converts this from "silent failure" to "loud warning on deploy."

**Technical impact:** `LangfuseClient` has no health-check method. The Langfuse v2 SDK has `langfuse.auth_check()` which verifies connectivity and key validity with a single lightweight HTTP call. This is the correct hook for a startup health check.

**Root cause:** The exception-swallowing design of `LangfuseClient` (intentional — Assumption 7 in the docstring) means individual call failures are invisible. The startup check is the designated place to surface structural connectivity failures without changing the exception-swallowing contract for individual calls.

**Implementation requirements:**
1. In `backend/services/langfuse_service.py`, add a new async method to `LangfuseClient` immediately after `flush()`:
   ```python
   async def startup_check(self) -> bool:
       """Verify Langfuse connectivity on process startup.

       Calls the SDK's auth_check() in a worker thread (blocking I/O).
       Returns True on success, False on failure.  Never raises — a Langfuse
       outage must not prevent the application from starting.  Logs a
       structured WARNING on failure so operators can detect version skew or
       connectivity issues immediately on deploy.  M-4 — T-221.
       """
       client = self._ensure_client()
       if client is None:
           return True  # disabled — not an error
       try:
           result = await asyncio.wait_for(
               asyncio.to_thread(client.auth_check),
               timeout=10.0,
           )
           if result and getattr(result, "status", None) == "success":
               logger.info("langfuse.startup_check.ok")
               return True
           logger.warning(
               "langfuse.startup_check.failed",
               result=str(result)[:200],
           )
           return False
       except asyncio.TimeoutError:
           logger.warning(
               "langfuse.startup_check.timeout",
               timeout_seconds=10.0,
           )
           return False
       except Exception:
           logger.warning("langfuse.startup_check.error", exc_info=True)
           return False
   ```
2. In `backend/main.py` (or wherever the FastAPI lifespan is defined), inside the lifespan startup block, after Redis is initialized, add:
   ```python
   langfuse_client = langfuse_service.get_langfuse_client()
   if langfuse_client.enabled:
       await langfuse_client.startup_check()
       # Result is logged; never fatal.
   ```
3. The `startup_check()` call must NEVER raise and NEVER prevent app startup. It is fire-and-observe only.
4. Run: `cd backend && uv run pytest tests/ -q` — all tests pass.

**Dependencies:** None (LangfuseClient already exists from T-208)

**Risk assessment:** LOW. `startup_check()` is purely additive. `auth_check()` is a read-only SDK call. The 10-second timeout ensures the lifespan startup is never blocked for more than 10 seconds. Langfuse being down during startup is gracefully handled (returns False, logs warning, app starts normally).

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_langfuse_client_has_startup_check_method -v` passes.
2. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_langfuse_startup_check_never_raises -v` passes.
3. `cd backend && uv run pytest tests/ -q` — all tests pass.
4. When `LANGFUSE_SECRET_KEY` is empty, `startup_check()` returns True immediately without calling `auth_check()`.

**Testing requirements:**
- Harness contract: `startup_check` method exists in `LangfuseClient`.
- Harness contract: `startup_check` uses `asyncio.wait_for` with a timeout.
- Unit test in existing `test_langfuse_service.py` (or new file): mock `client.auth_check()` to raise an exception → verify `startup_check()` returns False without re-raising.

**Observability requirements:** Log events `langfuse.startup_check.ok`, `langfuse.startup_check.failed`, `langfuse.startup_check.timeout`, `langfuse.startup_check.error` at structured WARNING/INFO level.

**Rollback considerations:** Remove the `startup_check()` method and the lifespan call. No DB, no config.

**Estimated complexity:** S (~40 lines)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/langfuse_service.py` — add `startup_check()` method to `LangfuseClient`
- `backend/main.py` — call `startup_check()` in lifespan startup after Redis init

---

### T-222 — Add RedisError Fallback for sliding_window_check in stage_manager.py

**Category:** Reliability
**Severity:** Low
**Priority:** P2
**Source finding:** L-4 (third-pass review)

**Business impact:** `sliding_window_check()` is called directly in `stage_manager.generate()` and `stage_manager.refine()` for the per-user LLM rate limiter (10 req/min, 200 req/day). If Redis raises `RedisError` (connectivity blip, Redis restart), the exception propagates unhandled through the async generator, surfaces as an SSE `{"error": "internal_error"}` event, and loses all context. Users see a cryptic internal error when they expected either a successful generation or a "rate limit exceeded" message. The `RateLimitMiddleware` already handles this gracefully via `_local_fallback_check`; the stage_manager should match that behavior.

**Technical impact:** `redis.eval()` inside `sliding_window_check()` can raise `redis.exceptions.RedisError` on connection failure. In the stage_manager's use of this function, no `try/except RedisError` wrapper exists.

**Root cause:** `sliding_window_check()` was written as a utility that expects callers to handle Redis errors. `RateLimitMiddleware` does handle it (falls back to in-process). The stage_manager callers (lines 530–533 in `generate()`) do not.

**Implementation requirements:**
1. In `backend/services/pipeline/stage_manager.py`, locate the two `sliding_window_check()` call sites in `generate()` (lines ~530–533):
   ```python
   if not await sliding_window_check(redis, f"llm:{user.id}", 10, 60):
       raise RateLimitError(retry_after=60)
   if not await sliding_window_check(redis, f"llm_daily:{user.id}", 200, 86400):
       raise RateLimitError(retry_after=86400)
   ```
2. Wrap both calls in a `try/except RedisError` that fails open (allow the request, log a warning):
   ```python
   from redis.exceptions import RedisError  # (already imported elsewhere in the file)

   try:
       if not await sliding_window_check(redis, f"llm:{user.id}", 10, 60):
           raise RateLimitError(retry_after=60)
       if not await sliding_window_check(redis, f"llm_daily:{user.id}", 200, 86400):
           raise RateLimitError(retry_after=86400)
   except RedisError:
       # Redis unavailable — fail open, matching RateLimitMiddleware behavior.
       # Log at WARNING so operators are alerted to the degraded state.
       # L-4 — T-222.
       logger.warning(
           "stage_manager.llm_rate_limit.redis_unavailable "
           "stage_id=%s user_id=%s — rate limiting bypassed",
           stage_id,
           user.id,
       )
   ```
3. Apply the same pattern to the equivalent call sites in `refine()` if they exist.
4. Run: `cd backend && uv run pytest tests/ -q` — all tests pass.

**Dependencies:** None

**Risk assessment:** VERY LOW. Fail-open is the deliberate choice — identical to `RateLimitMiddleware` behavior. Under Redis failure, rate limiting degrades gracefully rather than breaking generation. A `WARNING` log ensures the degraded state is visible.

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_stage_manager_sliding_window_redis_error_fallback -v` passes.
2. `cd backend && uv run pytest tests/ -q` — all tests pass.
3. Code review: no bare `await sliding_window_check(...)` call in stage_manager.py lacks a `RedisError` handler.

**Testing requirements:**
- Harness contract: `except RedisError` present near `sliding_window_check` in stage_manager.py.
- Unit test (existing `test_stage_manager.py` or new): mock `sliding_window_check` to raise `RedisError` → verify generation proceeds (no exception raised to caller).

**Observability requirements:** Log `stage_manager.llm_rate_limit.redis_unavailable` at WARNING level with stage_id and user_id context.

**Rollback considerations:** Remove the try/except wrapper. No DB, no config.

**Estimated complexity:** XS (~15 lines)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `backend/services/pipeline/stage_manager.py` — wrap `sliding_window_check()` calls in `generate()` and `refine()` with `RedisError` handler

---

### T-223 — Add TTL-Based Eviction to the LLM Adapter Instance Cache

**Category:** Reliability
**Severity:** Low
**Priority:** P3
**Source finding:** L-1 (third-pass review)

**Business impact:** The `_INSTANCES` cache in `gateway.py` stores adapter objects with no time-based expiry — only LRU eviction at 256 entries. A cached adapter whose provider SDK has accumulated dead connections (e.g., after a provider-side TCP reset with no FIN, which many HTTP/1.1 keep-alive connections experience after ~1 hour of inactivity) will be returned indefinitely. Most provider SDKs handle reconnection transparently via httpx connection pool retry, but this is implementation-dependent. A TTL ensures adapters are periodically rebuilt, clearing any stale connection state.

**Technical impact:** `_INSTANCES` maps `(provider, model, key_fingerprint)` → `BaseLLMAdapter`. No creation timestamp is stored. Adding TTL requires storing `(adapter, created_at)` tuples instead of plain adapter values.

**Root cause:** `_INSTANCES` was designed as a simple performance cache (avoid repeated constructor calls for the same provider/model/key). Connection lifetime was not considered in the original design.

**Implementation requirements:**
1. In `backend/services/llm/gateway.py`, add a module-level constant below `_INSTANCE_CACHE_MAX`:
   ```python
   # Adapters older than this are evicted on cache hit and rebuilt fresh.
   # Ensures stale httpx connection pools are recycled periodically.  L-1 — T-223.
   _INSTANCE_CACHE_TTL_SECONDS: float = 3600.0
   ```
2. Change the type annotation of `_INSTANCES` to store tuples:
   ```python
   import time as _time
   _INSTANCES: OrderedDict[tuple[str, str, str], tuple["BaseLLMAdapter", float]] = OrderedDict()
   ```
3. Update `get_llm()` to store `(adapter, created_at)` and check TTL on cache hit:
   ```python
   if key in _INSTANCES:
       adapter, created_at = _INSTANCES[key]
       if _time.monotonic() - created_at < _INSTANCE_CACHE_TTL_SECONDS:
           _INSTANCES.move_to_end(key)
           return adapter
       # TTL expired — evict and rebuild below.
       del _INSTANCES[key]
   if len(_INSTANCES) >= _INSTANCE_CACHE_MAX:
       _INSTANCES.popitem(last=False)
   new_adapter = _REGISTRY[provider](model, api_key=api_key)
   _INSTANCES[key] = (new_adapter, _time.monotonic())
   return new_adapter
   ```
4. Update `clear_llm_cache()` to remain functional:
   ```python
   def clear_llm_cache() -> None:
       _INSTANCES.clear()
   ```
   (No change needed — `_INSTANCES.clear()` still works on a dict of tuples.)
5. Run: `cd backend && uv run pytest tests/ -q` — all tests pass. Pay special attention to any test that uses `get_llm()` or checks `_INSTANCES` contents directly.

**Dependencies:** None

**Risk assessment:** LOW. The behavioral change is limited to evicting adapters after 1 hour. The first request after TTL expiry pays a small constructor overhead (negligible). Any test that inspects `_INSTANCES[key]` directly must be updated to unpack the tuple.

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_gateway_adapter_cache_has_ttl_constant -v` passes.
2. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_gateway_instances_stores_tuples_with_timestamp -v` passes.
3. `cd backend && uv run pytest tests/ -q` — all tests pass.

**Testing requirements:**
- Harness contract: `_INSTANCE_CACHE_TTL_SECONDS` defined in gateway.py.
- Harness contract: `_INSTANCES` stores tuples (float timestamp present in values).
- Unit test: set `_INSTANCE_CACHE_TTL_SECONDS = 0.01` in test scope, call `get_llm()` twice with 0.02s sleep → second call gets a new instance (not cached). Restore TTL after test.

**Observability requirements:** None — connection recycling is silent. If needed in future, a Counter `specforge_llm_adapter_cache_evictions_total` can be added.

**Rollback considerations:** Revert the tuple storage change to plain adapter values. No DB, no config.

**Estimated complexity:** S (~25 lines in gateway.py)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/services/llm/gateway.py` — `_INSTANCES` type, `get_llm()` cache logic, `_INSTANCE_CACHE_TTL_SECONDS` constant

---

### T-224 — Add Secret Rotation Procedures to RUNBOOK.md (§8)

**Category:** Operational / Security
**Severity:** Medium
**Priority:** P2
**Source finding:** Operational gap (third-pass review)

**Business impact:** `ENCRYPTION_MASTER_KEY` (Fernet) encrypts all stored user API keys. If this key is compromised or rotated without a procedure, all stored API keys become either inaccessible (wrong key) or unrotated (still encrypted under the compromised key). `CSRF_SECRET` invalidates all outstanding CSRF tokens when rotated — without a procedure, an operator might rotate it during a high-traffic period without understanding the session impact. JWT key rotation forces all users to re-authenticate. None of these have documented procedures.

**Technical impact:** Three secrets require distinct rotation procedures:
1. `ENCRYPTION_MASTER_KEY` (Fernet) — requires re-encrypting all rows in `user_api_keys` table (or equivalent stored key columns) under the new Fernet key.
2. `CSRF_SECRET` — rotation immediately invalidates all outstanding CSRF tokens; users experience a "403 Forbidden — CSRF token invalid" on their next mutating request. No re-encryption needed.
3. `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` — rotation invalidates all existing access tokens and refresh tokens (since signature verification fails). Users are forced to re-authenticate.

**Root cause:** The secrets were added as configuration with no rotation lifecycle defined. The RUNBOOK §1–§7 cover operational incidents but not planned security maintenance procedures.

**Implementation requirements:**
Add **§8 — Secret Rotation Procedures** to `docs/RUNBOOK.md` with the following sub-sections:

**§8.1 — ENCRYPTION_MASTER_KEY Rotation**
- Pre-rotation: verify all currently encrypted values are readable (`SELECT COUNT(*) FROM user_api_keys WHERE encrypted_key IS NOT NULL`)
- Rotation steps:
  1. Generate new Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  2. Set `NEW_ENCRYPTION_MASTER_KEY=<new>` alongside existing `ENCRYPTION_MASTER_KEY=<old>` in Railway env
  3. Run migration script `backend/scripts/rotate_encryption_key.py --old-key $ENCRYPTION_MASTER_KEY --new-key $NEW_ENCRYPTION_MASTER_KEY` — this script reads each encrypted value, decrypts with old key, re-encrypts with new key, and updates the row. Script must be idempotent (test decrypt with new key first; skip if already re-encrypted)
  4. Verify: `python -m pytest tests/test_key_vault.py -v` passes with NEW_ENCRYPTION_MASTER_KEY
  5. Remove old key, rename NEW_ENCRYPTION_MASTER_KEY to ENCRYPTION_MASTER_KEY in Railway
- Rollback: keep old key in env as `OLD_ENCRYPTION_MASTER_KEY` until rotation is verified; re-run script in reverse if needed

**§8.2 — CSRF_SECRET Rotation**
- Impact: all outstanding CSRF tokens are immediately invalidated. Users see 403 on next mutating request and must refresh to get a new token.
- Best practice: rotate during a low-traffic window (e.g., off-peak hours)
- Steps:
  1. Generate new secret: `python -c "import secrets; print(secrets.token_hex(32))"`
  2. Update `CSRF_SECRET` in Railway environment
  3. Deploy — the new secret takes effect immediately on next process start
  4. Monitor `csrf.verify.failed` log events; they should return to baseline within 5 minutes as tokens are refreshed
- No Redis cleanup required (existing nonce keys expire naturally on their existing TTL)

**§8.3 — JWT Key Rotation**
- Impact: all existing access tokens and refresh tokens become invalid. All users must re-authenticate.
- Best practice: rotate only when key compromise is confirmed or on annual schedule; announce to users in advance if possible
- Steps:
  1. Generate new RS256 key pair: `openssl genrsa 4096 | tee jwt_private.pem; openssl rsa -in jwt_private.pem -pubout > jwt_public.pem`
  2. Update `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY` in Railway
  3. Purge all refresh token entries from Redis: `redis-cli KEYS "refresh:*" | xargs redis-cli DEL`
  4. Deploy
  5. Monitor authentication error rates; they should spike briefly (re-auth) then return to baseline
- Rollback: restore old keys in Railway; existing tokens become valid again

**§8.4 — Redis Password Rotation (if applicable)**
- Update `REDIS_URL` in Railway with new password
- Restart the service container

After writing §8, update the RUNBOOK Table of Contents (if present) to include §8.

**Dependencies:** T-216 (RUNBOOK.md must exist)

**Risk assessment:** VERY LOW. Documentation-only. No code changes.

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_runbook_has_secret_rotation_section -v` passes.
2. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_runbook_secret_rotation_covers_all_keys -v` passes.
3. RUNBOOK.md contains `§8` or `## 8` heading with sub-sections for ENCRYPTION_MASTER_KEY, CSRF_SECRET, and JWT rotation.

**Testing requirements:**
- Harness contract: string scan for key rotation headings and procedure terms in RUNBOOK.md.

**Observability requirements:** None.

**Rollback considerations:** Not applicable (documentation).

**Estimated complexity:** S (~120-line RUNBOOK section)
**Estimated implementation risk:** Very Low

**Affected modules/files:**
- `docs/RUNBOOK.md` — add §8 Secret Rotation Procedures

---

### T-225 — Fix Rate Limit Startup Window: Fall Back to In-Process Limits Instead of Bypassing All Tiers

**Category:** Security / Rate Limiting
**Severity:** Medium
**Priority:** P1
**Source finding:** H-3 (third-pass review)

**Business impact:** During the application startup window (between process start and the FastAPI lifespan completing Redis initialization, typically 1–5 seconds), ALL rate limiting is bypassed. This means the IP-global 1000 req/min cap, the per-user 100 req/min cap, and all domain-specific tiers (LLM, PDF, GitHub export, clarify) are inactive. An attacker who times a burst at startup (e.g., during a rolling Railway deploy where workers restart briefly) can bypass rate limiting entirely. The `RateLimitMiddleware` already has `_local_fallback_check` (in-process sliding window) for Redis failures — the startup window should use the same fallback.

**Technical impact:** `RateLimitMiddleware.dispatch()` at lines 157–165 checks `redis is None` and calls `return await call_next(request)` — completely bypassing `_enforce_limits()`. The `RedisError` path (lines 177–184) correctly calls `_enforce_limits(..., self._local_fallback_check)`. The startup path should mirror this.

**Root cause:** The startup fail-open was introduced in T-202 to prevent early requests from being rejected before Redis is available. The intent was correct (don't break requests), but the implementation went too far (bypass all tiers instead of using the in-process fallback).

**Implementation requirements:**
1. In `backend/middleware/rate_limit.py`, locate the `redis is None` branch in `dispatch()` (approximately lines 156–165):
   ```python
   redis = getattr(request.app.state, "redis", None)
   if redis is None:
       if not self._logged_redis_not_ready:
           logger.warning(
               "rate_limit.redis_not_ready "
               "app.state.redis is not set — rate limiting bypassed until "
               "Redis is registered by the lifespan"
           )
           self._logged_redis_not_ready = True
       return await call_next(request)  # ← THE BUG
   ```
2. Replace `return await call_next(request)` with a fallback to the in-process check:
   ```python
   redis = getattr(request.app.state, "redis", None)
   if redis is None:
       if not self._logged_redis_not_ready:
           logger.warning(
               "rate_limit.redis_not_ready "
               "app.state.redis is not set — falling back to in-process "
               "rate limiting until Redis is registered by the lifespan"
           )
           self._logged_redis_not_ready = True
       # Use in-process fallback so rate limiting remains active during startup.
       # Same behavior as the RedisError fallback path.  H-3 — T-225.
       limited_response = await self._enforce_limits(
           request, ip, path, self._local_fallback_check
       )
       if limited_response is not None:
           return limited_response
       return await call_next(request)
   ```
3. In the `else` branch (where `redis is not None`), reset `_logged_redis_not_ready = False` so the startup warning fires again after a Redis restart:
   ```python
   else:
       self._logged_redis_not_ready = False
   ```
4. Update the warning log message to say "falling back to in-process rate limiting" (not "bypassed") — this is a semantic correction, not just a cosmetic change. A monitoring alert on this log message should not indicate "no rate limiting" anymore.
5. Run: `cd backend && uv run pytest tests/ -q` — all tests pass. Check existing rate limit tests.

**Dependencies:** T-202 (lazy Redis injection in RateLimitMiddleware must exist)

**Risk assessment:** LOW. The change replaces one code path (`return call_next`) with another (`_enforce_limits` using the same in-process fallback already used for RedisError). Under startup conditions, this is strictly more protective than the current behavior. The `_logged_redis_not_ready` reset ensures operators can detect Redis restart events via log monitoring.

**Acceptance criteria:**
1. `cd harness && pytest tests/backend/test_phase17_final_hardening_contract.py::test_phase17_rate_limit_startup_uses_fallback_not_bypass -v` passes.
2. `cd backend && uv run pytest tests/test_rate_limit.py -v` — all existing rate limit tests pass.
3. `cd backend && uv run pytest tests/ -q` — all tests pass.
4. Code review: no `return await call_next(request)` exists in the `redis is None` branch of `RateLimitMiddleware.dispatch()`.
5. The log message contains "falling back to in-process" (not "bypassed").

**Testing requirements:**
- Harness contract: `return await call_next(request)` NOT present immediately after the `redis is None` check in rate_limit.py (string scan).
- Harness contract: `_local_fallback_check` appears in the `redis is None` handling branch.
- Unit test (existing test_rate_limit.py or new): simulate `app.state.redis = None` → verify rate limit middleware still applies limits (returns 429 when limit is exceeded).

**Observability requirements:** Updated log message `rate_limit.redis_not_ready ... falling back to in-process rate limiting` — operators should update any alert rules that match the old `"rate limiting bypassed"` string.

**Rollback considerations:** Revert the `return await call_next(request)` change. No DB, no config, no migration.

**Estimated complexity:** S (~15 lines)
**Estimated implementation risk:** Low

**Affected modules/files:**
- `backend/middleware/rate_limit.py` — replace bypass with in-process fallback in `redis is None` branch of `dispatch()`

---

_tasks.md · SpecForge V1 · Version 2.5.0 · 2026-05-25 — Phase 17 Final Hardening & Enterprise Closure T-217 through T-225 (9 remediation tasks addressing all findings from third-pass enterprise review 2026-05-25: 1 critical circuit breaker gap, 1 high prompt regression, 4 medium findings covering credit cache timing / rate limit startup / Langfuse health / secret rotation, 2 low findings covering sliding window fallback / adapter TTL, plus circuit_state Gauge observability addition)_

_tasks.md · SpecForge V1 · Version 2.4.0 · 2026-05-23 — Phase 16 Final Remediation & Enterprise Hardening T-196 through T-216 (21 remediation tasks addressing every finding from docs/CODE_REVIEW_PASS_2.md second-pass enterprise review: 2 critical unresolved findings, 5 high severity regressions, 5 medium severity issues, 4 low severity issues, plus 2 observability/documentation tasks mapping to systemic risks)_

_tasks.md · SpecForge V1 · Version 2.3.1 · 2026-05-22 — Phase 15 addendum: corrected L-3/L-4/L-7/L-8 task descriptions; added T-191 through T-195 (LLM cache eviction, CSRF exempt path audit, CSP for public share, observability instrumentation, missing concurrency tests) covering non-labeled report-body findings from docs/CODE_REVIEW.md_

_tasks.md · SpecForge V1 · Version 2.3.0 · 2026-05-22 — Phase 15 Enterprise Production Hardening T-174 through T-190 (19 remediation tasks addressing all C-1–C-4 critical, H-1–H-6 high, M-1–M-7 medium, and L-1–L-8 low findings from the staff-engineer production readiness code review)_

_tasks.md · SpecForge V1 · Version 2.2.1 · 2026-05-20 — Phase 14 design language: added Design Directive preamble (observe → design → introspect → build → microcopy) and per-task Design Brief subsections to all six frontend tasks (T-163, T-165, T-167, T-169, T-171, T-172) naming the moment-of-use feeling for each component. No acceptance criteria removed; the directive is enforced at PR review as a human-judged criterion in addition to the automated harness checks._

_tasks.md · SpecForge V1 · Version 2.2.0 · 2026-05-20 — Phase 14 V1.3 usefulness improvements T-160 through T-173 (Spec Clarification, per-task Priority + Estimate, PDF export, Public Share, Starter Templates, harness coverage surfacing)_

_tasks.md · SpecForge V1 · Version 2.1.0 · 2026-05-19 — Phase 13 GitHub export integration T-147 through T-159_
