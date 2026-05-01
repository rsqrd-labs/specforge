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

_tasks.md · SpecForge V1 · Version 1.2.0 · Updated 2026-05-01 with gap-closure tasks T-050 through T-066_
