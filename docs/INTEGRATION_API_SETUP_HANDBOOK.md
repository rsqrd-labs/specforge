# Integration & API Setup Handbook

This handbook walks you through everything needed to run SpecForge — both
locally and live on the internet. No prior deployment experience is assumed.

---

## How SpecForge is structured

SpecForge has two application pieces plus two data stores:

```text
User's browser
  |
  | (opens the app, signs in, generates stages)
  v
Frontend — React app, static files
  Hosted on Vercel  (e.g. https://specforge.vercel.app)
  |
  | API calls
  v
Backend — FastAPI Python server
  Hosted on Railway  (e.g. https://specforge-api.up.railway.app)
  |
  +-- PostgreSQL  database, hosted on Railway
  +-- Redis       cache/sessions, hosted on Railway
```

**Locally** everything runs in Docker on your machine at `localhost` URLs.

**In production** the backend and databases live on Railway (a cloud hosting
platform), and the frontend lives on Vercel (a static-site hosting platform).
Both are free to start and require no server management on your part.

---

## Deployment concepts for first-timers

**What is Railway?**
Railway is a platform that runs your backend server and databases in the cloud.
You give it your code and some configuration, and it gives you a public URL
like `https://specforge-api.up.railway.app`. You do not manage any servers —
Railway handles that. It also provides managed PostgreSQL and Redis databases,
meaning you get a database URL without having to install or maintain the
database software yourself.

**What is Vercel?**
Vercel is a platform that hosts frontend web apps. You run `pnpm build` to
turn your React code into plain HTML, CSS, and JavaScript files, and Vercel
serves those files from a global CDN. You get a public URL like
`https://specforge.vercel.app`. No servers to manage.

**What are environment variables?**
Environment variables are configuration values that your app reads at runtime.
Locally they live in `.env` files (`backend/.env`, `frontend/.env`). In
production, Railway and Vercel have a settings UI where you type them in — no
`.env` file is deployed. This is how you safely pass API keys, database URLs,
and secrets to a running service.

**What are GitHub Secrets?**
GitHub Secrets are a secure way to store credentials inside your GitHub
repository without putting them in code. GitHub Actions (the automated
build-and-deploy pipeline in `.github/workflows/ci.yml`) reads these secrets
to push deployments to Railway and Vercel. You add them once in your repo's
Settings page and they never appear in your code.

**What is the deployment flow?**
When you push code to the `main` branch on GitHub:

1. GitHub Actions runs tests automatically.
2. If tests pass, it deploys the backend to Railway.
3. It also deploys the frontend to Vercel.

This is called continuous deployment — the app updates automatically whenever
you merge to `main`.

---

## 1. Overview of Required Services

| Service | Required? | Purpose |
| --- | --- | --- |
| PostgreSQL | Yes | Stores users, workspaces, stages, credits, and evals |
| Redis | Yes | Stores login sessions, rate-limit counters, and stage cache |
| Google OAuth | Yes | User sign-in ("Sign in with Google") |
| Anthropic / OpenAI / Google Gemini | At least one | LLM generation — you need a key for whichever provider(s) you want to offer |
| Railway | Production | Hosts the backend server, PostgreSQL, and Redis in the cloud |
| Vercel | Production | Hosts the frontend website |
| GitHub Actions secrets | Production | Lets the automated pipeline deploy to Railway and Vercel |
| Sentry | Optional | Error reporting if something breaks in production |
| Grafana OTLP | Optional | Distributed tracing (advanced observability) |
| Langfuse | Optional | LLM call logging and prompt management |
| Prometheus metrics | Built in | `/metrics` endpoint — no setup needed |

Dependencies installed but not yet wired to credentials (safe to ignore):
`stripe`, `resend`, `supabase` — these packages exist but SpecForge does not
read any corresponding environment variables for them.

---

## 2. Service Setup

### PostgreSQL

**What it is:** the primary relational database. Every user account, workspace,
stage, credit transaction, and eval result is stored here.

**Locally:** Docker Compose starts a PostgreSQL container automatically. No
setup needed.

**In production on Railway:**

1. Go to [railway.app](https://railway.app) and sign up or log in.
2. Click **New Project**.
3. Click **Add a service** → **Database** → **Add PostgreSQL**.
4. Railway creates a PostgreSQL instance and shows you its connection details.
5. Click the PostgreSQL service, go to the **Connect** tab.
6. Copy the **Private URL** — it looks like:
   `postgresql://postgres:PASSWORD@HOST.railway.internal:5432/railway`
7. You will need to prefix this with `+asyncpg` for SpecForge. Change
   `postgresql://` to `postgresql+asyncpg://`. The final value goes into the
   backend service's `DATABASE_URL` variable (covered in the Railway section
   below).

Required variable:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB_NAME
```

**Local Docker value** (set automatically by `docker-compose.yml`):

```env
DATABASE_URL=postgresql+asyncpg://specforge:specforge@db:5432/specforge
```

Common errors:

- `No module named asyncpg`: run `uv sync` in `backend/`.
- Connection refused: wrong host/port or the database is not running.
- `password authentication failed`: wrong password in the URL.
- Migration failure: make sure you run `alembic upgrade head` from `backend/`.

---

### Redis

**What it is:** an in-memory data store used for login session state, OAuth
handshake state, rate-limit counters, and temporary stage data. If Redis is
unavailable, sign-in and rate limiting degrade gracefully but some features
may behave oddly.

**Locally:** Docker Compose starts Redis automatically. No setup needed.

**In production on Railway:**

1. In your Railway project, click **Add a service** → **Database** → **Add Redis**.
2. Click the Redis service, go to the **Connect** tab.
3. Copy the **Private URL** — it looks like `redis://default:PASSWORD@HOST.railway.internal:6379`.
4. This value goes into the backend service's `REDIS_URL` variable.

> If your Railway Redis requires TLS, use `rediss://` instead of `redis://`
> at the start of the URL. Railway's internal network typically does not
> require TLS, so `redis://` is usually correct.

Required variable:

```env
REDIS_URL=redis://HOST:PORT/0
```

**Local Docker value:**

```env
REDIS_URL=redis://redis:6379/0
```

Common errors:

- `/health` returns `degraded`: Redis is unreachable or the URL is wrong.
- Sign-in fails with "OAuth state error": Redis is down — the login handshake
  stores short-lived state there.
- Rate limits behave strangely: check backend logs for
  `rate_limit.redis_unavailable_fallback`.

---

### Google OAuth

**What it is:** the "Sign in with Google" button. Google handles the password
check and tells SpecForge who the user is. SpecForge never sees or stores
passwords.

**How the flow works:**

1. User clicks "Sign in with Google" on the frontend.
2. They are redirected to Google's consent page.
3. After approving, Google redirects back to `{FRONTEND_URL}/auth/callback`
   with a one-time code.
4. The frontend sends that code to the SpecForge backend, which exchanges it
   with Google for the user's identity.
5. SpecForge issues its own login tokens and sets a session cookie.

**How to set up credentials:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and sign in
   with your Google account.
2. Click the project selector at the top → **New Project**. Give it any name
   (e.g. `specforge`).
3. In the left sidebar, go to **APIs & Services** → **OAuth consent screen**.
   - Choose **External** as the user type.
   - Fill in the app name (e.g. `SpecForge`) and your email for the support
     and developer contact fields.
   - Click through the remaining steps and save.
4. Go to **APIs & Services** → **Credentials** → **Create Credentials** →
   **OAuth client ID**.
5. Application type: **Web application**.
6. Under **Authorized JavaScript origins** add:
   - `http://localhost:5173` (for local development)
   - `https://your-vercel-url.vercel.app` (your production frontend URL — add
     this once you know it from Vercel)
7. Under **Authorized redirect URIs** add:
   - `http://localhost:5173/auth/callback` (for local development)
   - `https://your-vercel-url.vercel.app/auth/callback` (production — add
     after Vercel is set up)
8. Click **Create**. Google shows you a **Client ID** and **Client Secret**.
   Copy both — you will not be able to see the secret again without
   regenerating it.
9. Put these into `backend/.env` for local development, and into Railway
   backend variables for production.

> The redirect URI must be the **frontend** URL (`/auth/callback` on Vercel),
> not the backend URL. Google sends the user back to the frontend, which then
> calls the backend. This is a common source of confusion.

Required variables:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
FRONTEND_URL=http://localhost:5173   # change to your Vercel URL in production
```

Common errors:

- `redirect_uri_mismatch`: the URI you registered in Google Console does not
  exactly match `FRONTEND_URL + /auth/callback`. Check for trailing slashes
  and `http` vs `https`.
- "Google sign-in failed": check backend logs, verify `GOOGLE_CLIENT_SECRET`,
  and verify `FRONTEND_URL` matches the browser origin.
- "OAuth state error": Redis is down.

---

### LLM Providers

SpecForge needs at least one LLM provider key to generate stages. You can
enable one or all three; users pick their provider in the UI.

#### Anthropic (Claude)

1. Go to [console.anthropic.com](https://console.anthropic.com/) and sign up.
2. Add billing details under **Plans & Billing**. Anthropic requires a payment
   method before issuing production keys (there is a free tier for testing).
3. Go to **API Keys** → **Create Key**. Copy the key (starts with `sk-ant-`).
4. Store it in `ANTHROPIC_API_KEY`.

```env
ANTHROPIC_API_KEY=sk-ant-...
```

#### OpenAI

1. Go to [platform.openai.com](https://platform.openai.com/) and sign up.
2. Add a payment method under **Billing**.
3. Go to **API Keys** → **Create new secret key**. Copy the key (starts with
   `sk-`).
4. Store it in `OPENAI_API_KEY`.

```env
OPENAI_API_KEY=sk-...
```

#### Google Gemini

1. Go to [aistudio.google.com](https://aistudio.google.com/) and sign in.
2. Click **Get API key** → **Create API key**.
3. Copy the key and store it in `GOOGLE_API_KEY`.

```env
GOOGLE_API_KEY=...
```

Common errors for all providers:

- Provider error during generation: check the key is valid and the account has
  billing enabled.
- Model not found: the allowed models per provider are listed in
  `backend/services/llm/provider_config.py`.

---

### Sentry (optional — skip for first deploy)

Sentry catches and reports errors from the running app. Useful once you have
real users. Skip it on your first deployment — SpecForge works without it.

If you want to set it up later:

1. Go to [sentry.io](https://sentry.io) and create an account.
2. Create a project for **Python/FastAPI** (for the backend) and another for
   **React** (for the frontend).
3. Each project gives you a **DSN** (a URL starting with `https://`).
4. Set `SENTRY_DSN` in the backend and `VITE_SENTRY_DSN` in the frontend build
   environment.

```env
SENTRY_DSN=https://...       # backend variable
VITE_SENTRY_DSN=https://...  # frontend build variable (set in Vercel)
```

Leave both blank to disable Sentry. No errors or warnings will appear.

---

### Grafana OTLP / OpenTelemetry (optional — skip for first deploy)

Advanced distributed tracing. Skip this entirely unless you specifically need
to trace requests across services.

```env
GRAFANA_OTLP_ENDPOINT=https://...
GRAFANA_OTLP_TOKEN=...
```

Leave both blank. The backend starts normally without them.

---

### Langfuse (optional — skip for first deploy)

Langfuse records every LLM call so you can inspect what prompts and outputs
were produced. Useful for debugging generation quality. Not required for the
app to work.

```env
LANGFUSE_SECRET_KEY=     # leave blank to disable entirely
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

When `LANGFUSE_SECRET_KEY` is blank, the SDK is never loaded and zero network
traffic goes to Langfuse. Leave it blank on your first deploy.

If you enable Langfuse in production later, also set:

```env
LANGFUSE_CONTENT_CAPTURE_ACK=true
```

This is an explicit acknowledgement that prompts and model outputs will be
sent to Langfuse after redaction. The backend refuses to start in production
with Langfuse enabled unless this is set.

---

### Prometheus Metrics

The `/metrics` endpoint is built in — no setup needed. In production, requests
to it require a bearer token to prevent public access to internal metrics data.
Generate a token and set it:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

```env
METRICS_TOKEN=the-random-value-you-generated
```

Leave `METRICS_TOKEN` empty in local development. The backend only requires it
when `ENVIRONMENT=production`.

---

## 3. Production Deployment

This section walks you through putting SpecForge live on the internet for the
first time. Work through these steps in order.

### What you need before starting

- A GitHub account with this repository pushed to it.
- A Railway account ([railway.app](https://railway.app)) — free to sign up.
- A Vercel account ([vercel.com](https://vercel.com)) — free to sign up.
- Your Google OAuth credentials (from section 2 above).
- At least one LLM provider API key.

### Step 1 — Set up Railway (backend + databases)

Railway will host the FastAPI server, PostgreSQL, and Redis.

**Create a project:**

1. Log into [railway.app](https://railway.app).
2. Click **New Project** → **Empty Project**. Name it `specforge`.

**Add PostgreSQL:**

3. Click **Add a service** → **Database** → **Add PostgreSQL**.
4. Railway creates the database. Click the PostgreSQL service tile to see its
   details.
5. Go to the **Connect** tab → copy the **Private URL**.

**Add Redis:**

6. Click **Add a service** → **Database** → **Add Redis**.
7. Click the Redis tile → **Connect** tab → copy the **Private URL**.

**Add the backend service:**

8. Click **Add a service** → **GitHub Repo**.
9. Connect Railway to your GitHub account if prompted, then select this
   repository.
10. Railway detects the `Dockerfile` inside `backend/`. Set the **Root
    directory** to `backend`.
11. Railway may start a first build automatically — that is fine.

**Set environment variables on the backend service:**

12. Click your backend service tile → go to the **Variables** tab.
13. Add each variable listed below. Click **Add Variable** for each one.

    | Variable | Value |
    | --- | --- |
    | `ENVIRONMENT` | `production` |
    | `DATABASE_URL` | The PostgreSQL Private URL from step 5, with `postgresql://` changed to `postgresql+asyncpg://` |
    | `REDIS_URL` | The Redis Private URL from step 7 |
    | `FRONTEND_URL` | Your Vercel URL — come back and fill this in after step 2. For now leave it blank or use a placeholder. |
    | `JWT_PRIVATE_KEY` | Generated below |
    | `JWT_PUBLIC_KEY` | Generated below |
    | `GOOGLE_CLIENT_ID` | From Google Cloud Console |
    | `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
    | `ANTHROPIC_API_KEY` | Your Anthropic key (or leave blank if not using Anthropic) |
    | `OPENAI_API_KEY` | Your OpenAI key (or leave blank if not using OpenAI) |
    | `GOOGLE_API_KEY` | Your Gemini key (or leave blank if not using Gemini) |
    | `ENCRYPTION_MASTER_KEY` | Generated below |
    | `CSRF_SECRET` | Generated below |
    | `METRICS_TOKEN` | Generated below |

**Generate the JWT key pair** (run this on your local machine):

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

Then convert the PEM files to single-line strings for pasting into Railway:

```bash
python3 - <<'PY'
from pathlib import Path
for name, file in [("JWT_PRIVATE_KEY", "jwt_private.pem"), ("JWT_PUBLIC_KEY", "jwt_public.pem")]:
    value = Path(file).read_text().replace("\n", "\\n")
    print(f'{name}="{value}"')
PY
```

Copy the output for each variable into Railway. The value will look like a
long string with `\n` characters inside it — that is correct.

**Generate the remaining secrets** (run each command and copy the output):

```bash
# ENCRYPTION_MASTER_KEY
cd backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# CSRF_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# METRICS_TOKEN
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

14. Once all variables are set, go to the backend service → **Settings** →
    **Networking** → **Generate Domain**. Railway gives you a public URL like
    `https://specforge-backend-production.up.railway.app`. Copy it — you need
    it for Vercel.

15. Check the **Deployments** tab and confirm the backend started successfully.
    Visit `https://your-railway-url/health` — you should see
    `{"status":"ok","version":"1.0.0"}`.

> **If the deployment fails:** go to the **Deployments** tab, click the failed
> deploy, and read the build/runtime logs. The most common issues are a missing
> environment variable or a wrong `DATABASE_URL` format.

---

### Step 2 — Set up Vercel (frontend)

Vercel will build and host the React frontend.

1. Go to [vercel.com](https://vercel.com) and sign up (you can use your GitHub
   account to sign in).
2. Click **Add New Project**.
3. Import your GitHub repository. If it does not appear, click **Adjust GitHub
   App Permissions** to grant Vercel access.
4. Vercel will detect the frontend. Set:
   - **Root Directory**: `frontend`
   - **Framework Preset**: Vite (Vercel usually detects this automatically)
5. Under **Environment Variables**, add:

   | Variable | Value |
   | --- | --- |
   | `VITE_API_URL` | Your Railway backend URL from step 1 (e.g. `https://specforge-backend-production.up.railway.app`) |
   | `VITE_SENTRY_DSN` | Leave blank unless you set up Sentry |

6. Click **Deploy**. Vercel builds the frontend and gives you a URL like
   `https://specforge-abc123.vercel.app`.

7. Copy your Vercel URL. Go back to Railway and set `FRONTEND_URL` on the
   backend service to this URL (it must start with `https://`).

8. Go back to Google Cloud Console and add your Vercel URL to **Authorized
   JavaScript origins** and `https://your-vercel-url.vercel.app/auth/callback`
   to **Authorized redirect URIs**.

9. Redeploy the Railway backend so it picks up the updated `FRONTEND_URL` (in
   Railway → your backend service → **Deployments** → **Deploy**).

10. Visit your Vercel URL and try signing in.

---

### Step 3 — Set up GitHub Secrets (automated deployment)

Right now, deployments only happen when you manually trigger them in Railway or
Vercel. To make deploys automatic on every push to `main`, configure GitHub
Actions.

**What you need:**

- A Railway token
- Three Vercel identifiers (token, org ID, project ID)

**Get a Railway token:**

1. In Railway, click your avatar (top right) → **Account Settings** →
   **Tokens** → **New Token**. Name it `github-actions`. Copy the token.

**Get Vercel credentials:**

2. In Vercel, go to **Account Settings** → **Tokens** → **Create Token**. Name
   it `github-actions`. Copy the token.
3. Your **Vercel Org ID** is shown in **Account Settings** under your profile.
   It looks like `team_xxxxxxx` or just a string of characters.
4. Your **Vercel Project ID** is shown in the project's **Settings** →
   **General** at the top of the page.

**Add the secrets to GitHub:**

5. Go to your GitHub repository → **Settings** → **Secrets and variables** →
   **Actions** → **New repository secret**. Add one at a time:

   | Secret name | Value |
   | --- | --- |
   | `RAILWAY_TOKEN` | The Railway token |
   | `VERCEL_TOKEN` | The Vercel token |
   | `VERCEL_ORG_ID` | Your Vercel org/account ID |
   | `VERCEL_PROJECT_ID` | Your Vercel project ID |

6. Push any small change to `main`. Watch the **Actions** tab in GitHub — you
   should see a workflow run that ends with a deploy step pushing to both
   Railway and Vercel.

---

### Step 4 — Verify the live deployment

1. Visit your Vercel URL. The landing page should load.
2. Click **Sign in with Google** and complete the flow. You should land on
   `/dashboard` with 50 credits.
3. Create a workspace and run a SPEC generation. Tokens should stream in.
4. Check the Railway backend logs (Deployments → the running deploy →
   **View Logs**) for any errors.

If something is wrong, the [Troubleshooting Guide](#5-troubleshooting-guide)
at the bottom of this document covers the most common issues.

---

### Step 5 — Set up the production smoke test (optional but recommended)

After each deploy you can run an automated check that hits the live app:

```bash
SPECFORGE_API_URL=https://your-railway-url \
SPECFORGE_ACCESS_TOKEN=<your access token — see below> \
SPECFORGE_METRICS_TOKEN=<your METRICS_TOKEN value> \
SPECFORGE_RUN_LLM_SMOKE=1 \
python3 scripts/production_smoke.py
```

To get a temporary access token for the smoke test:

1. Open your Vercel URL in a browser and sign in.
2. Open browser DevTools → **Network** tab.
3. Look for the request to `/auth/callback` on the backend.
4. In the response JSON, copy the `access_token` value.
5. Use it as `SPECFORGE_ACCESS_TOKEN` above. The token expires quickly so run
   the smoke test immediately after copying it.

You can also run this from GitHub Actions via the **Production Smoke** workflow
(`.github/workflows/production-smoke.yml`). Add `SPECFORGE_SMOKE_ACCESS_TOKEN`
and `SPECFORGE_METRICS_TOKEN` as GitHub Secrets to enable it.

---

## 4. Environment Configuration

### Local development

Copy the example files:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Minimum `backend/.env` for local development:

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
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PROMPT_CACHE_TTL=300
LANGFUSE_CONTENT_CAPTURE_ACK=false

ENVIRONMENT=development
MAX_ACTIVE_WORKSPACES_PER_USER=50
```

Frontend `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
VITE_SENTRY_DSN=
```

### Generating secrets locally

JWT key pair:

```bash
openssl genrsa -out jwt_private.pem 2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem

python3 - <<'PY'
from pathlib import Path
for name, file in [("JWT_PRIVATE_KEY", "jwt_private.pem"), ("JWT_PUBLIC_KEY", "jwt_public.pem")]:
    value = Path(file).read_text().replace("\n", "\\n")
    print(f'{name}="{value}"')
PY
```

Fernet encryption key:

```bash
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

CSRF secret and metrics token:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run the command twice — once for `CSRF_SECRET`, once for `METRICS_TOKEN`.

### Production-only requirements

The backend enforces these rules at startup when `ENVIRONMENT=production`:

- `METRICS_TOKEN` must be non-empty.
- `FRONTEND_URL` must start with `https://`.
- `JWT_PRIVATE_KEY` must be a real PEM key (not the CI placeholder).
- `ENCRYPTION_MASTER_KEY` must not be the CI placeholder value.
- If `LANGFUSE_SECRET_KEY` is set, `LANGFUSE_PUBLIC_KEY` must also be set,
  `LANGFUSE_HOST` must use `https://`, and `LANGFUSE_CONTENT_CAPTURE_ACK`
  must be `true`.

If any of these fail, the backend refuses to start and prints an error
message describing what is wrong.

---

## 5. Local Validation

### Start everything with Docker

```bash
docker compose up --build
```

This starts PostgreSQL, Redis, the FastAPI backend, and the Vite frontend
together. Wait until you see `Uvicorn running on http://0.0.0.0:8000`.

### Check backend health

```bash
curl http://localhost:8000/health
```

Expected in development:

```json
{"status":"ok","version":"1.0.0","db":"ok","redis":"ok"}
```

### Check provider list

```bash
curl http://localhost:8000/providers
```

Expected: a JSON object with a `providers` array containing `anthropic`,
`openai`, and `google`.

### Browser walkthrough

1. Open `http://localhost:5173`.
2. Click **Sign in with Google** and complete the sign-in.
3. You should land on `/dashboard` with 50 starter credits.
4. Create a workspace with a name and a problem statement of at least 50
   characters. Choose a provider with a valid key.
5. Open the **SPEC** stage and click **Generate**.
6. Tokens should stream into the editor. When it finishes, a quality badge
   appears and your credit balance decreases by 10.
7. Click **Finalise** on SPEC. The **PLAN** stage should unlock.

---

## 6. Troubleshooting Guide

### Backend does not start

Run this to print which config value is missing or wrong:

```bash
cd backend
uv run python -c "from config import settings; print(settings.environment)"
```

Common causes:

- A required environment variable is missing from `.env`.
- `JWT_PRIVATE_KEY` has formatting errors (missing `\n` escapes).
- `ENVIRONMENT=production` is set but `FRONTEND_URL` is not `https://`, or
  `METRICS_TOKEN` is empty, or `ENCRYPTION_MASTER_KEY` is the CI placeholder.

### Google sign-in does not work

Check:

- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are correct.
- The redirect URI in Google Console exactly matches
  `{FRONTEND_URL}/auth/callback` — no trailing slash, correct `http` vs
  `https`.
- `FRONTEND_URL` matches the URL you are opening in the browser.
- Redis is running (the login flow stores short-lived state there).

### Frontend cannot reach the backend

Check:

- `VITE_API_URL` in `frontend/.env` points to the correct backend URL.
- The backend is running: `curl http://localhost:8000/health`.
- Look in the browser DevTools console and Network tab for CORS errors or 401
  responses.

### LLM generation fails or streams nothing

Check:

- The provider API key is valid and the account has billing enabled.
- The model name is in the allowed list in
  `backend/services/llm/provider_config.py`.
- Redis and PostgreSQL are reachable (`/health` shows both as `ok`).
- Backend logs for a line containing `ProviderError`.

### CSRF failures (requests return 403)

Check:

- The frontend successfully obtained an access token after sign-in.
- The frontend can call `GET /auth/csrf-token` (check the Network tab).
- `CSRF_SECRET` is the same across backend restarts.

### Railway deploy fails

- Open the failed deployment in the Railway dashboard and read the build logs.
- Verify all required environment variables are set in Railway (the backend
  prints which ones are missing on startup).
- Verify `DATABASE_URL` starts with `postgresql+asyncpg://` not `postgresql://`.
- Verify `FRONTEND_URL` starts with `https://`.

### Vercel deploy fails

- Check the build logs in the Vercel dashboard.
- Verify `VITE_API_URL` is set in Vercel's environment variable settings.
- After changing any Vercel environment variable, redeploy (the value is baked
  in at build time — changes only take effect on the next build).

### Something worked locally but fails in production

The most common cause is a missing or wrong environment variable in Railway.
Compare every variable in `backend/.env` (working locally) against the
variables set in Railway. The backend's startup log will print an error if a
production-required variable fails validation.

### Keep secrets out of Git

Never commit:

- `backend/.env` or `frontend/.env`
- The `jwt_private.pem` / `jwt_public.pem` files you generated
- Any API keys or tokens

The CI pipeline runs TruffleHog on every push to detect accidentally committed
secrets. It is safest to add `*.pem` and `.env` to `.gitignore` immediately
after creating them.
