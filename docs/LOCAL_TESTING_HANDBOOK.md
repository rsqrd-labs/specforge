# Local Testing Handbook

This guide walks you through running the complete SpecForge stack on your
laptop — frontend, backend, database, and cache — so you can test everything
end-to-end before deploying to Vercel and Railway.

No prior experience with Docker or Python server tools is assumed.

---

## What you will have running locally

```text
Your browser  (http://localhost:5173)
  |
  v
Frontend — React app       http://localhost:5173
  |
  v
Backend — FastAPI server   http://localhost:8000
  |
  +-- PostgreSQL            localhost:5432  (inside Docker)
  +-- Redis                 localhost:6379  (inside Docker)
```

Everything runs in Docker containers on your machine. You do not install
PostgreSQL or Redis directly — Docker manages them for you.

---

## Part 1 — Install the required tools

You need four things installed before you start.

### 1. Docker Desktop

Docker is what runs the database, cache, and (optionally) the backend in
isolated containers on your machine.

- Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
- Install and open it. You should see the Docker whale icon in your menu bar.
- Verify it works:

```bash
docker --version
```

Expected output: something like `Docker version 27.x.x`

### 2. Python 3.12

The backend requires Python 3.12 exactly (not 3.11 or 3.13).

- Check what you have:

```bash
python3 --version
```

- If you need 3.12, download it from [python.org/downloads](https://www.python.org/downloads/)
  or install it with your system package manager.

### 3. uv (Python package manager)

`uv` installs and manages Python dependencies for the backend. It is much
faster than `pip`.

```bash
pip install uv
```

Verify:

```bash
uv --version
```

### 4. Node.js 22 and pnpm

Node.js runs the frontend build tools. pnpm is the package manager the
frontend uses.

- Download Node.js 22 from [nodejs.org](https://nodejs.org/) (choose the LTS
  version labelled 22.x).
- Once Node is installed, enable pnpm through Corepack (which ships with
  Node):

```bash
corepack enable
```

Verify both:

```bash
node --version   # should show v22.x.x
pnpm --version   # should show 9.x.x
```

---

## Part 2 — Get your API keys

The app needs a way for users to sign in (Google OAuth) and at least one LLM
provider key to generate stages. Gather these before setting up the config
files.

### Google OAuth credentials (required)

This powers the "Sign in with Google" button. Follow these steps:

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and
   sign in with any Google account.
2. Click the project selector at the top → **New Project**. Name it anything
   (e.g. `specforge-local`). Click **Create**.
3. In the left sidebar: **APIs & Services** → **OAuth consent screen**.
   - User type: **External**. Click **Create**.
   - Fill in **App name** (e.g. `SpecForge`) and your email for both support
     and developer contact fields.
   - Click **Save and Continue** through the remaining steps (Scopes and Test
     users can be left at defaults for now).
4. In the left sidebar: **APIs & Services** → **Credentials** →
   **Create Credentials** → **OAuth client ID**.
   - Application type: **Web application**.
   - Under **Authorized JavaScript origins**, click **Add URI** and enter:
     `http://localhost:5173`
   - Under **Authorized redirect URIs**, click **Add URI** and enter:
     `http://localhost:5173/auth/callback`
   - Click **Create**.
5. A popup shows your **Client ID** and **Client Secret**. Copy both
   somewhere safe — you'll need them in Part 3.

> **Why the redirect URI matters:** when a user signs in, Google redirects
> them back to `http://localhost:5173/auth/callback`. If this URI is not
> listed exactly in Google Console, the sign-in will fail with a
> `redirect_uri_mismatch` error.

### LLM provider key (at least one required)

You need at least one of these to generate stages. Pick whichever you already
have access to:

**Anthropic (Claude):**
1. Go to [console.anthropic.com](https://console.anthropic.com/) and sign up.
2. Add a payment method (required even for low usage).
3. Go to **API Keys** → **Create Key**. Copy the key — it starts with
   `sk-ant-`.

**OpenAI:**
1. Go to [platform.openai.com](https://platform.openai.com/) and sign up.
2. Add a payment method under **Billing**.
3. Go to **API Keys** → **Create new secret key**. Copy it — starts with
   `sk-`.

**Google Gemini:**
1. Go to [aistudio.google.com](https://aistudio.google.com/) and sign in.
2. Click **Get API key** → **Create API key**. Copy it.

You only need one. Leave the others blank in the config file — the app will
only show providers with valid keys.

### Stripe billing keys (optional)

Leave Stripe blank for normal local development. The billing page still loads
and `GET /billing/package` still returns the configured package, but checkout
creation returns a safe 503 until Stripe is configured.

To test paid credit packs locally:

1. Create a Stripe test account or use an existing Stripe test mode project.
2. Copy a test secret key (`sk_test_...`) into `STRIPE_SECRET_KEY`.
3. Install the Stripe CLI and run:

   ```bash
   stripe listen --forward-to localhost:8000/billing/webhook
   ```

4. Copy the printed webhook signing secret (`whsec_...`) into
   `STRIPE_WEBHOOK_SECRET`.
5. Use `http://localhost:5173/billing` for both success and cancel URLs.

---

## Part 3 — Configure environment files

### 3a. Copy the example files

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

This creates your local config files from the templates. These files are not
committed to Git — they stay on your machine only.

### 3b. Generate the secrets

The backend needs several cryptographic secrets. Run each command below and
keep the output — you'll paste these into `backend/.env` in the next step.

**JWT key pair** — used to sign and verify login tokens:

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

Now convert them to single-line strings for the `.env` file:

```bash
python3 - <<'PY'
from pathlib import Path
for name, file in [("JWT_PRIVATE_KEY", "jwt_private.pem"), ("JWT_PUBLIC_KEY", "jwt_public.pem")]:
    value = Path(file).read_text().replace("\n", "\\n")
    print(f'{name}="{value}"')
PY
```

This prints two lines like:

```
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIB...\n-----END PUBLIC KEY-----\n"
```

Copy both lines — you need the full value including the quotes.

**Encryption key** — used to encrypt any LLM provider keys users store in
the app:

```bash
cd backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Outputs something like: `xK3mN8vQ2pL7rT1wJ5sY9uA6bC4eF0gH2iD3oP8qR=`

**CSRF secret** — protects against cross-site request forgery attacks:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Outputs a random string like: `Xt7kQ2mNvP9wL4rB8sJ1uY5aZ3cE6fH0iD`

> Run the CSRF command once and save the output. You do not need a
> `METRICS_TOKEN` for local development — leave it blank.

### 3c. Fill in `backend/.env`

Open `backend/.env` in a text editor and replace the placeholder values:

```env
# Database — Docker Compose sets these automatically, leave as-is
DATABASE_URL=postgresql+asyncpg://specforge:specforge@localhost:5432/specforge
REDIS_URL=redis://localhost:6379/0

# Auth — paste the output from the JWT commands above
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"

# Google OAuth — from Part 2
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
FRONTEND_URL=http://localhost:5173

# GitHub OAuth App — leave blank to disable GitHub export integration
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=

# Stripe billing — leave blank to disable local checkout
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_CENTS=900
STRIPE_CREDITS_PER_PURCHASE=200
STRIPE_CREDIT_VALIDITY_DAYS=30
STRIPE_SUCCESS_URL=http://localhost:5173/billing
STRIPE_CANCEL_URL=http://localhost:5173/billing

# LLM providers — fill in whichever you have, leave others as placeholder
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Security — paste the values generated above
ENCRYPTION_MASTER_KEY=your-fernet-key-from-above
CSRF_SECRET=your-random-string-from-above

# Leave these blank for local development
METRICS_TOKEN=
SENTRY_DSN=
GRAFANA_OTLP_ENDPOINT=
GRAFANA_OTLP_TOKEN=
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PROMPT_CACHE_TTL=300
LANGFUSE_CONTENT_CAPTURE_ACK=false

ENVIRONMENT=development
MAX_ACTIVE_WORKSPACES_PER_USER=50
```

> **Important:** `DATABASE_URL` and `REDIS_URL` must stay exactly as shown
> above. Docker Compose starts PostgreSQL and Redis with those credentials
> and the backend connects to them using these URLs.

### 3d. Check `frontend/.env`

The frontend example is already correct for local development:

```env
VITE_API_URL=http://localhost:8000
VITE_SENTRY_DSN=
```

No changes needed.

---

## Part 4 — Start the stack

With Docker Desktop running, start everything from the repository root:

```bash
docker compose up --build
```

The first run takes a few minutes — Docker downloads the base images and
installs dependencies. Subsequent starts are much faster.

You will see interleaved log output from all four services. Wait until you
see both of these lines:

```
api    | Application startup complete.
frontend | VITE v6.x.x  ready in ... ms
```

The stack is ready when both appear.

**Services now running:**

| Service | URL | What it is |
| --- | --- | --- |
| Frontend | http://localhost:5173 | The React app — open this in your browser |
| Backend API | http://localhost:8000 | The FastAPI server |
| Backend docs | http://localhost:8000/docs | Auto-generated API explorer |
| Health check | http://localhost:8000/health | Quick status check |
| PostgreSQL | localhost:5432 | Database (no need to open this) |
| Redis | localhost:6379 | Cache (no need to open this) |

---

## Part 5 — Verify everything is working

### Check the backend is healthy

Open a new terminal tab and run:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","version":"1.0.0","db":"ok","redis":"ok"}
```

If you see `"db":"error"` or `"redis":"error"`, the database or cache did not
start correctly. See the [Troubleshooting](#troubleshooting) section.

### Check the LLM providers loaded

```bash
curl http://localhost:8000/providers
```

Expected: a JSON response with a `providers` array. You should see an entry
for each provider whose API key you filled in.

### Check the billing package

```bash
curl http://localhost:8000/billing/package
```

Expected: JSON with the current price, credits per purchase, and validity
window. If Stripe keys are blank, checkout creation is disabled but the package
endpoint remains available.

### Sign in and run the full flow

1. Open [http://localhost:5173](http://localhost:5173) in your browser.
2. Click **Sign in with Google** and complete the sign-in. You should land on
   `/dashboard`.
3. Check the credit balance shown — it should read **50 credits**.
4. Click **New Workspace**. Enter a name and a problem statement of at least
   50 characters. Choose a provider and model.
5. Open the **SPEC** stage and click **Generate**.
6. You should see text streaming into the editor token by token.
7. When it finishes, a quality score badge appears and your credit balance
   drops by 10.
8. Click **Finalise**. The **PLAN** stage should unlock.

If all of the above works, your local setup is complete and functioning
end-to-end.

### Optional billing checkout walkthrough

With Stripe test mode and `stripe listen` running:

1. Open [http://localhost:5173/billing](http://localhost:5173/billing).
2. Confirm the credit pack price and current purchase history load.
3. Click the buy-credits control and confirm the browser redirects to Stripe
   Checkout.
4. Complete checkout with a Stripe test card.
5. Return to `/billing?session_id=...`; the page should poll
   `GET /billing/status` until the webhook grants credits.
6. Confirm the credit balance and purchase history update once. Replaying the
   webhook should not grant credits a second time.

---

## Part 6 — Run the test suite

### Backend tests

```bash
cd backend
uv run pytest tests/ -q
```

Expected: all tests pass. The backend test suite runs without a live database
— it uses in-memory fakes.

With coverage report:

```bash
uv run pytest tests/ --cov=services --cov-fail-under=80 -q
```

Lint and formatting checks:

```bash
uv run ruff check .
uv run black --check .
```

Security scan:

```bash
uv run bandit -r config.py database.py main.py middleware models prompts routers schemas services
```

### Frontend tests

```bash
cd frontend
pnpm test
```

Type checking:

```bash
pnpm tsc --noEmit
```

### Contract / harness tests

These tests verify structural and security contracts across the whole
codebase:

```bash
cd backend
uv run pytest ../harness/tests/backend/ -q
```

### Prompt eval suite

Run this whenever you change `backend/prompts/**`, the critic template, or
prompt section contracts:

```bash
cd harness
uv run python -m prompt_eval.run \
  --version "$(grep -oE 'asdd-v[0-9.]+' ../backend/prompts/base.py)" \
  --baseline asdd-v1.7.1 \
  --report /tmp/prompt_eval_report.md
```

Also run the anonymization guard before changing golden workspaces:

```bash
cd backend
uv run pytest ../harness/tests/backend/test_prompt_eval_anonymization.py -q
```

---

## Part 7 — Stopping and resetting

**Stop the stack** (keeps your data):

```bash
docker compose down
```

**Restart it later:**

```bash
docker compose up
```

(No `--build` needed unless you changed code.)

**Reset the database** (wipes all data and starts fresh):

```bash
docker compose down -v
docker compose up --build
```

The `-v` flag deletes the Docker volumes where PostgreSQL and Redis store
their data. Use this if you want a clean slate or if the database gets into a
bad state.

---

## Auth rate limit overrides in Docker Compose

The `docker-compose.yml` file sets two environment variables on the `api` service
that override the production-safe defaults:

```yaml
AUTH_LOGIN_BURST_LIMIT: 60    # Local dev only — do not copy to staging/production
AUTH_LOGIN_HOURLY_LIMIT: 240  # Local dev only — do not copy to staging/production
```

These relaxed rate limit values let you run tests and exercise the auth flow
without hitting login throttling on your laptop. **Do not copy them to staging
or production** — the defaults enforced by `config.py` are much stricter.

If you need to test the rate limit behaviour itself (e.g. you are working on
the authentication flow), temporarily lower the values or remove the overrides
so the production defaults apply.

---

## Troubleshooting

### `docker compose up` fails immediately

- Make sure Docker Desktop is open and running (look for the whale icon).
- Try `docker compose down -v` then `docker compose up --build` to start clean.

### Health check shows `"db":"error"` or `"redis":"error"`

The database or Redis container may still be starting up. Wait 10–15 seconds
and try `curl http://localhost:8000/health` again. If it stays in error:

```bash
docker compose logs db      # PostgreSQL logs
docker compose logs redis   # Redis logs
```

Look for startup errors. The most common cause is another process already
using port 5432 or 6379 on your machine. Stop that process or change the port
in `docker-compose.yml`.

### Sign-in fails with `redirect_uri_mismatch`

The redirect URI in Google Cloud Console does not match. Go back to Google
Cloud Console → **Credentials** → your OAuth client → verify that
`http://localhost:5173/auth/callback` is listed exactly under Authorized
redirect URIs. No trailing slash, no `https`.

### Sign-in fails with "OAuth state error"

Redis is not reachable. Check `curl http://localhost:8000/health` for Redis
status and look at `docker compose logs redis`.

### Generation fails or streams nothing

- Check that at least one LLM provider key in `backend/.env` is valid.
- Verify the key is for the provider you selected in the workspace.
- Check the backend logs: `docker compose logs api`. Look for a line
  containing `ProviderError`.
- Make sure billing is enabled on your LLM provider account — most providers
  reject requests from accounts without a payment method even if they have a
  free tier.

### Billing checkout returns 503

This is expected when local billing is intentionally disabled. To enable it,
set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_SUCCESS_URL`, and
`STRIPE_CANCEL_URL` in `backend/.env`, then restart the backend.

### Billing checkout succeeds but credits do not appear

- Confirm `stripe listen --forward-to localhost:8000/billing/webhook` is still
  running.
- Confirm `STRIPE_WEBHOOK_SECRET` matches the current Stripe CLI listener.
- Check backend logs for `billing.webhook_invalid_signature`,
  `billing.webhook_livemode_mismatch`, or `billing.webhook_handle_failed`.
- Confirm you completed the Checkout Session created by SpecForge, not a
  standalone test event without SpecForge metadata.

### Backend starts but immediately crashes

Run the config check:

```bash
cd backend
uv run python -c "from config import settings; print(settings.environment)"
```

If this errors, a required variable is missing or malformed in `backend/.env`.
Read the error message — it names the specific variable.

### Frontend shows a blank page or cannot connect to the API

- Check `frontend/.env` has `VITE_API_URL=http://localhost:8000`.
- Open browser DevTools → **Console** tab for errors.
- Open **Network** tab and look for failed requests — a CORS error means
  `FRONTEND_URL` in `backend/.env` does not match `http://localhost:5173`.

### Port already in use

If you see an error like `bind: address already in use` for port 5173, 8000,
5432, or 6379, something else on your machine is using that port. Find and
stop it:

```bash
lsof -i :8000    # shows what is using port 8000
```

Or stop all Docker containers:

```bash
docker compose down
```

### Changes to `backend/.env` are not taking effect

Stop and restart the stack:

```bash
docker compose down
docker compose up --build
```

Environment variable changes require a restart.

---

## Quick reference

| Task | Command |
| --- | --- |
| Start everything | `docker compose up --build` |
| Stop everything | `docker compose down` |
| Wipe data and restart fresh | `docker compose down -v && docker compose up --build` |
| View backend logs | `docker compose logs api` |
| View all logs | `docker compose logs` |
| Run backend tests | `cd backend && uv run pytest tests/ -q` |
| Run frontend tests | `cd frontend && pnpm test` |
| Run harness tests | `cd backend && uv run pytest ../harness/tests/backend/ -q` |
| Run prompt eval | `cd harness && uv run python -m prompt_eval.run --version "$(grep -oE 'asdd-v[0-9.]+' ../backend/prompts/base.py)" --baseline asdd-v1.7.1 --report /tmp/prompt_eval_report.md` |
| Check backend health | `curl http://localhost:8000/health` |
| Open API explorer | http://localhost:8000/docs |

---

## Storyboard Local Smoke

Use this after SPEC, PLAN, HARNESS, and TASKS are all finalised in a local
workspace.

1. Open the workspace and confirm the Create Storyboard action is enabled.
2. Generate a Storyboard with a mocked provider in tests or a staging-safe
   provider key locally.
3. Open the deck and verify the six acts, presenter view, architecture reveal,
   and source layer.
4. Enable sharing and open the `/sb/` URL in another browser profile.
5. Exercise download actions for PDF, speaker notes, demo script, and appendix.
6. Disable or rotate the public Storyboard link and confirm the old `/sb/` URL
   returns the not-found state.
