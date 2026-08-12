# Integration & API Setup Handbook

This handbook walks you through everything needed to run Thought2Build — both
locally and live on the internet. No prior deployment experience is assumed.

---

## How Thought2Build is structured

Thought2Build has three application pieces plus two data stores. The third piece —
the **marketing zone** — is the SEO/GEO content site (issue #18); it is optional
for running the product but required for organic and answer-engine acquisition.

```text
User's browser
  |
  | (lands on a marketing/content page, or opens the app, signs in, generates stages)
  v
Marketing zone — Astro static site (SEO + GEO content)   [optional]
  Hosted on Vercel, on the APEX domain  (e.g. https://thought2build.com)
  Source: apps/marketing/.  Content authored in Sanity (a hosted CMS).
  |
  | Vercel multi-zone "rewrites" forward app/artifact paths to the SPA below.
  | (/dashboard, /workspace/*, /settings, /billing, /auth/*, /p/*, /sb/*, /assets/*)
  v
Frontend — React app, static files (the SPA)
  Hosted on Vercel, on its OWN project/subdomain  (e.g. https://thought2build-app.vercel.app)
  |
  | API calls
  v
Backend — FastAPI Python server
  Hosted on Railway  (e.g. https://thought2build-api.up.railway.app)
  |
  +-- PostgreSQL  database, hosted on Railway
  +-- Redis       cache/sessions, hosted on Railway
```

**Locally** the frontend, backend, and data stores run in Docker on your machine
at `localhost` URLs. The marketing zone is a separate Astro project under
`apps/marketing/` with its own dev/build commands (`pnpm dev` / `pnpm build`); it
is not part of `docker compose` and is not needed to run the product locally.

**In production** the backend and databases live on Railway (a cloud hosting
platform), and the SPA frontend lives on Vercel (a static-site hosting platform).
Both are free to start and require no server management on your part. The
marketing zone, when you launch it, is a **second, separate Vercel project**
rooted at `apps/marketing` that owns the apex domain and rewrites the
app/artifact paths to the SPA project — so the whole product stays on one origin
(OAuth redirect URIs, the refresh cookie, CSRF, and CORS are all unchanged). See
[section 7](#7-marketing-zone-seo--geo-content-site) for the full marketing-zone
setup, and `docs/ISSUE_18_SEO_GEO_LAUNCH_PLAN.md` for its architecture and build
log.

---

## Deployment concepts for first-timers

**What is Railway?**
Railway is a platform that runs your backend server and databases in the cloud.
You give it your code and some configuration, and it gives you a public URL
like `https://thought2build-api.up.railway.app`. You do not manage any servers —
Railway handles that. It also provides managed PostgreSQL and Redis databases,
meaning you get a database URL without having to install or maintain the
database software yourself.

**What is Vercel?**
Vercel is a platform that hosts frontend web apps. You run `pnpm build` to
turn your React code into plain HTML, CSS, and JavaScript files, and Vercel
serves those files from a global CDN. You get a public URL like
`https://thought2build.vercel.app`. No servers to manage.

**What are environment variables?**
Environment variables are configuration values that your app reads at runtime.
Locally they live in `.env` files (`backend/.env`, `frontend/.env`). In
production, Railway and Vercel have a settings UI where you type them in — no
`.env` file is deployed. This is how you safely pass API keys, database URLs,
and secrets to a running service.

**What is GitHub Actions?**
GitHub Actions is an automation system built into GitHub. You define workflows
as YAML files in `.github/workflows/` and GitHub runs them automatically in
response to events — for example, every time you push code. Thought2Build's
workflow (`.github/workflows/ci.yml`) runs the test suite, lints the code, and
then deploys the backend to Railway and the frontend to Vercel, all without
you doing anything manually. You can watch it run in real time under the
**Actions** tab of your GitHub repository.

**What are GitHub Secrets?**
GitHub Secrets are a secure way to store credentials inside your GitHub
repository without putting them in code. GitHub Actions reads these secrets
to push deployments to Railway and Vercel. You add them once in your repo's
Settings page and they never appear in your code or in the workflow logs.

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
| Railway | Production | Hosts the backend `backend` web service **plus the `worker` and `worker-fast` arq worker services**, PostgreSQL, and Redis in the cloud — see [Step 1](#step-1--set-up-railway-backend--databases), all three services are required, not just `backend` |
| Vercel | Production | Hosts the frontend website (the SPA) — and, separately, the marketing zone |
| GitHub Actions secrets | Production | Lets the automated pipeline deploy to Railway and Vercel |
| Marketing Vercel project | Optional | Second Vercel project rooted at `apps/marketing` — the SEO/GEO content site on the apex domain (issue #18). Skip until you launch organic/answer-engine acquisition. |
| Sanity | Optional | Hosted CMS that holds the marketing content (guides, use-cases, comparisons, templates, demos). Fetched at build time. Required only if you run the marketing zone with real content. |
| GitHub OAuth App | Optional | Legacy (Phase 13) GitHub export integration — lets users push spec/plan/tasks to a GitHub repo as files + issues, one-shot. Leave blank to disable. |
| GitHub App | Optional | Phase 21 bidirectional "living system of record" — issues sync back to task status, PRs, webhooks, Projects board. Supersedes the OAuth App above when configured; requires the `worker`/`worker-fast` services. Leave blank to disable. |
| Payments (Lemon Squeezy or Razorpay) | Optional | Paid credit packs, gated by the `PAYMENTS_ENABLED` master switch + `PAYMENT_PROVIDER` selector (issue #44). Leave `PAYMENTS_ENABLED=false` to launch with checkout off. |
| Sentry | Optional | Error reporting if something breaks in production |
| Grafana OTLP | Optional | Distributed tracing (advanced observability) |
| Langfuse | Optional | LLM call logging and prompt management |
| Prometheus metrics | Built in | `/metrics` endpoint — no setup needed |

Dependencies installed but not currently required for runtime setup:
`resend` and `supabase`. Lemon Squeezy and Razorpay are the two supported runtime
billing providers (Phase 22 / issue #44), selected by `PAYMENT_PROVIDER` and gated
by `PAYMENTS_ENABLED` — both documented below. The Stripe runtime was fully
decommissioned (T-308) — there is no Stripe SDK, config, or webhook path anymore;
only the read-only Stripe audit tables remain (see "Stripe (decommissioned)" below).

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
7. You will need to prefix this with `+asyncpg` for Thought2Build. Change
   `postgresql://` to `postgresql+asyncpg://`. The final value goes into the
   backend service's `DATABASE_URL` variable (covered in the Railway section
   below).

Required variable:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB_NAME
```

**Local Docker value** (set automatically by `docker-compose.yml`):

```env
DATABASE_URL=postgresql+asyncpg://thought2build:thought2build@db:5432/thought2build
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
check and tells Thought2Build who the user is. Thought2Build never sees or stores
passwords.

**How the flow works:**

1. User clicks "Sign in with Google" on the frontend.
2. They are redirected to Google's consent page.
3. After approving, Google redirects back to `{FRONTEND_URL}/auth/callback`
   with a one-time code.
4. The frontend sends that code to the Thought2Build backend, which exchanges it
   with Google for the user's identity.
5. Thought2Build issues its own login tokens and sets a session cookie.

**How to set up credentials:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and sign in
   with your Google account.
2. Click the project selector at the top → **New Project**. Give it any name
   (e.g. `thought2build`).
3. In the left sidebar, go to **APIs & Services** → **OAuth consent screen**.
   - Choose **External** as the user type.
   - Fill in the app name (e.g. `Thought2Build`) and your email for the support
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

Thought2Build needs at least one LLM provider key to generate stages. You can
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

#### OpenRouter (optional — open-weight models, issue #152)

A fourth, optional provider reached through a single OpenAI-compatible
endpoint fronting open-weight models (DeepSeek, GLM, Qwen, and others).
Skip this section unless you specifically want an open-weight fallback tier —
it is not part of the minimal go-live path and defaults to unset.

1. Go to [openrouter.ai](https://openrouter.ai/) and sign up.
2. Add credits under **Credits**.
3. Go to **Keys** → **Create Key**. Copy the key (starts with `sk-or-`).
4. Store it in `OPENROUTER_API_KEY`.

```env
OPENROUTER_API_KEY=sk-or-...
```

Setting the key alone does nothing — routing only considers a provider that
also appears in `LLM_PROVIDER_PRIORITY` (see `docs/RUNBOOK.md` §8.5 before
adding `"openrouter"` there in production; the flip also moves the judge/
critic model, not just generation).

Common errors for all providers:

- Provider error during generation: check the key is valid and the account has
  billing enabled.
- Model not found: the allowed models per provider are listed in
  `backend/services/llm/provider_config.py`.

---

### GitHub OAuth App (optional — skip if you don't need GitHub export)

The GitHub export integration lets users push their spec, plan, tasks, and
harness to a new GitHub repository and create issues for each task. Leave
both variables blank to disable it — the backend returns a 503 on GitHub
auth endpoints and the frontend hides the export button.

**How to set up the OAuth App:**

1. Go to [github.com/settings/developers](https://github.com/settings/developers)
   and sign in.
2. Click **New OAuth App**.
3. Fill in:
   - **Application name**: `Thought2Build` (or any name)
   - **Homepage URL**: your Vercel URL (or `http://localhost:5173` for local)
   - **Authorization callback URL**: `{FRONTEND_URL}/auth/github/callback`
     — for local use `http://localhost:5173/auth/github/callback`
4. Click **Register application**.
5. Copy the **Client ID** shown on the app page.
6. Click **Generate a new client secret**. Copy the secret immediately — it
   is only shown once.

```env
GITHUB_CLIENT_ID=your-github-oauth-app-client-id
GITHUB_CLIENT_SECRET=your-github-oauth-app-client-secret
```

Leave both blank to disable GitHub export:

```env
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
```

Common errors:

- `Connect GitHub` button is missing in Settings: `GITHUB_CLIENT_ID` is blank
  — the backend disables the integration entirely when both vars are unset.
- Callback fails after GitHub approval: the Authorization callback URL in the
  GitHub OAuth App settings does not match `{FRONTEND_URL}/auth/github/callback`.
- 503 on `/auth/github`: `GITHUB_CLIENT_ID` is not set in the backend environment.

---

### GitHub App (Phase 21 — optional, the bidirectional "living system of record")

This supersedes the OAuth App above: instead of a one-shot export, closing a
task's GitHub issue (or merging its PR) flips that task to **done** inside
Thought2Build, and pushes/reconciliation/backfill all run as durable background
jobs. It requires the `worker` and `worker-fast` Railway services from
[Step 1](#step-1--set-up-railway-backend--databases) — nothing processes GitHub
webhooks or PR checks without them.

**How to set up the GitHub App:**

1. Go to [github.com/settings/apps](https://github.com/settings/apps) and click
   **New GitHub App**.
2. Fill in:
   - **GitHub App name**: `Thought2Build` (or any unique name — this becomes the
     app's public slug)
   - **Homepage URL**: your frontend URL
   - **Callback URL**: `{BACKEND_URL}/integrations/github/setup` — this **must**
     be the backend, not the frontend (unlike the OAuth App above)
   - **Webhook URL**: `{BACKEND_URL}/integrations/github/webhook`
   - **Webhook secret**: generate one (`python3 -c "import secrets;
     print(secrets.token_urlsafe(32))"`) and copy it into
     `GITHUB_APP_WEBHOOK_SECRET`
   - Under **Identifying and authorizing users**, check **Request user
     authorization (OAuth) during installation** — this makes the install
     callback a single hop and is what lets the backend verify the installer
     actually administers the installation (it's a required security check, not
     just a convenience: without it the setup callback has no way to prove the
     caller controls the installation they're binding).
   - Under **Permissions**, grant repository **Contents** (read/write),
     **Issues** (read/write), **Pull requests** (read/write), and organization
     **Members** (read) if you want the identity-verification access check to
     work for org installations.
   - Subscribe to webhook events: **Push**, **Issues**, **Pull request**.
3. Click **Create GitHub App**. On the app's page, note the numeric **App ID**
   (top of the page) and generate a **private key** (scroll to **Private
   keys** → **Generate a private key** — downloads a `.pem` file).
4. Still on the app's page, note the **Client ID** and generate a **Client
   secret** (this is the identity OAuth pair, separate from the webhook
   secret).
5. Convert the private key to a single-line string the same way as the JWT key
   in [Step 1](#step-1--set-up-railway-backend--databases):
   ```bash
   python3 -c "print(open('/path/to/downloaded-key.pem').read().replace(chr(10), '\\\\n'))"
   ```

```env
GITHUB_APP_ID=123456
GITHUB_APP_SLUG=thought2build
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
GITHUB_APP_WEBHOOK_SECRET=
GITHUB_APP_WEBHOOK_SECRET_PREV=          # set during a secret-rotation window only
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=
```

Leave all six blank to keep the App off (the Phase-13 OAuth path above remains
available on its own).

Production guardrails (`validate_production_settings()`): the App is
"enabled" once `GITHUB_APP_ID` + `GITHUB_APP_SLUG` are both set. Once enabled
in production, the backend refuses to start unless `GITHUB_APP_PRIVATE_KEY`,
`GITHUB_APP_WEBHOOK_SECRET`, and **both** `GITHUB_APP_CLIENT_ID` /
`GITHUB_APP_CLIENT_SECRET` are also set — the identity OAuth pair is what closes
a cross-tenant IDOR in the install callback, so it's mandatory, not optional,
whenever the App itself is on.

Common errors:

- Install callback rejects with `github.install.rejected`: the caller doesn't
  administer the installation being bound — this is the intended security
  behavior, not a bug; the person completing setup must be an admin of the
  GitHub org/account that installed the app.
- Webhooks never arrive / `worker-fast` looks idle: confirm the Callback and
  Webhook URLs point at the **backend** domain, not the frontend, and that
  both `worker` and `worker-fast` services are deployed and green in Railway.
- Backend refuses to start in production: one of `GITHUB_APP_PRIVATE_KEY`,
  `GITHUB_APP_WEBHOOK_SECRET`, `GITHUB_APP_CLIENT_ID`, or
  `GITHUB_APP_CLIENT_SECRET` is blank while `GITHUB_APP_ID`/`GITHUB_APP_SLUG`
  are set.

See `docs/RUNBOOK.md` §12 for ongoing ops: webhook-secret rotation,
installation-token re-mint, dead-letter replay, backfill, and increment-push.

---

### Payments — two providers behind one flag (issue #44)

Paid credit packs are gated by a master switch plus a provider selector, kept
deliberately separate from "is a provider configured":

```env
PAYMENTS_ENABLED=false          # master kill switch — default off
PAYMENT_PROVIDER=lemonsqueezy   # "lemonsqueezy" | "razorpay" — must be set even while disabled
```

Checkout is only reachable when **both** are true: `PAYMENTS_ENABLED=true` AND
the active `PAYMENT_PROVIDER` is fully configured (its required variables all
set). `GET /billing/package` surfaces this as `enabled` / `provider` fields that
gate the frontend's Buy button. `PAYMENT_PROVIDER` must always be a valid value
— the backend refuses to start in production if it's blank or misspelled, even
with payments off.

Pick one provider per deployment:

- **Lemon Squeezy** — the default, and the Merchant of Record (it absorbs sales
  tax, chargebacks, and disputes for you). Documented in full below.
- **Razorpay** — an INR-focused alternative via hosted Payment Links.
  **Not** a Merchant of Record — tax and dispute liability sit with your
  account, and lost disputes settle manually via admin-correction. Documented
  in full below.

Both providers' webhooks are always processed regardless of which one is
currently active, so switching `PAYMENT_PROVIDER` and redeploying never breaks
settlement of a still-open order/refund on the provider you just switched away
from.

#### Lemon Squeezy Billing (Phase 22)

Lemon Squeezy powers the `/billing` page, hosted checkout, and the signed
webhook that grants purchased credits. Lemon is the **Merchant of Record**, so
it absorbs sales tax, chargebacks, and disputes.
Leave `LEMONSQUEEZY_API_KEY` / `LEMONSQUEEZY_STORE_ID` / `LEMONSQUEEZY_VARIANT_ID`
blank to leave this provider unconfigured (fine if `PAYMENT_PROVIDER=razorpay`
instead): `GET /billing/package` still returns the configured package, but
`POST /billing/checkout` returns a safe `503` and the frontend surfaces a calm
disabled state.

Checkout is **attempt-first**: Thought2Build commits a `billing_checkout_attempts`
row (snapshotting credits/price/currency/validity) *before* calling Lemon, then
returns a `checkout_ref` the frontend polls. The webhook proves the order back
with a one-time `checkout_nonce` (only its `sha256` is ever stored).

**How to set up Lemon Squeezy:**

1. Create a Lemon Squeezy store. Use **test mode** for local/staging and a live
   store for production.
2. Create a single-charge product variant for the credit pack and copy its
   numeric id into `LEMONSQUEEZY_VARIANT_ID`; copy the store id into
   `LEMONSQUEEZY_STORE_ID`.
3. Create an API key (Settings → API) and copy it into `LEMONSQUEEZY_API_KEY`.
4. Create a webhook (Settings → Webhooks) pointing at `{BACKEND_URL}/billing/webhook`.
   Subscribe it to:
   - `order_created`
   - `order_refunded`
   (Chargebacks/disputes surface to Thought2Build through `order_refunded`/fraud
   revocation inputs because Lemon is the Merchant of Record — confirm against
   Lemon's **current** webhook catalog before go-live and record the list in the
   release gate. Reconcile lane 2 backstops anything the catalog adds.)
5. Copy the webhook signing secret into `LEMONSQUEEZY_WEBHOOK_SECRET`. The
   handler verifies the `X-Signature` HMAC against
   `[LEMONSQUEEZY_WEBHOOK_SECRET, LEMONSQUEEZY_WEBHOOK_SECRET_PREV]` so secret
   rotation has a two-secret window (see `RUNBOOK.md` §9).
6. Set the success return URL to the billing page. There is intentionally **no**
   cancel URL — `LEMONSQUEEZY_SUCCESS_URL={FRONTEND_URL}/billing`.
7. Configure the package:
   - `LEMONSQUEEZY_PRICE_CENTS=900`
   - `LEMONSQUEEZY_CURRENCY=USD`
   - `LEMONSQUEEZY_CREDITS_PER_PURCHASE=200`
   - `LEMONSQUEEZY_CREDIT_VALIDITY_DAYS=30`
8. Set `LEMONSQUEEZY_TEST_MODE=true` for local/staging; it **must be `false`** in
   production (enforced at startup).

```env
LEMONSQUEEZY_API_KEY=
LEMONSQUEEZY_WEBHOOK_SECRET=
LEMONSQUEEZY_WEBHOOK_SECRET_PREV=        # set during a secret-rotation window only
LEMONSQUEEZY_STORE_ID=
LEMONSQUEEZY_VARIANT_ID=
LEMONSQUEEZY_PRICE_CENTS=900
LEMONSQUEEZY_CURRENCY=USD
LEMONSQUEEZY_CREDITS_PER_PURCHASE=200
LEMONSQUEEZY_CREDIT_VALIDITY_DAYS=30
LEMONSQUEEZY_SUCCESS_URL=http://localhost:5173/billing
LEMONSQUEEZY_TEST_MODE=true               # MUST be false in production
LEMONSQUEEZY_CHECKOUT_TTL_MINUTES=30
LEMONSQUEEZY_API_BASE=https://api.lemonsqueezy.com
LEMONSQUEEZY_RECONCILE_MAX_CALLS_PER_RUN=200

# Billing admin allowlist (comma-separated emails) authorised to issue manual
# billing corrections via POST /billing/admin/correction. Empty = nobody.
ADMIN_USER_EMAILS=
```

Production guardrails (`validate_production_settings()`):

- Lemon is "enabled" only when `LEMONSQUEEZY_API_KEY` + `LEMONSQUEEZY_STORE_ID` +
  `LEMONSQUEEZY_VARIANT_ID` are all set; a half-configured Lemon is treated as
  disabled.
- When enabled in production, the backend refuses to start unless
  `LEMONSQUEEZY_WEBHOOK_SECRET` is set, `LEMONSQUEEZY_SUCCESS_URL` is HTTPS,
  price/credits/validity are positive, currency is non-empty, and
  `LEMONSQUEEZY_TEST_MODE=false`.
- The webhook handler verifies `X-Signature` (two-secret HMAC, fail-closed),
  commits each event to the durable `billing_webhook_events` inbox keyed by the
  Lemon event id (replay is idempotent), then enqueues a worker job. Credit
  grants are idempotent on `(provider, provider_order_id)` and the
  `billing_purchase:lemonsqueezy:{order}` ledger reason.

Common errors:

- Checkout returns 503: Lemon billing is not configured (one of API key / store
  id / variant id is blank).
- Checkout returns 502: Lemon could not create the checkout, or the post-Lemon
  commit failed (the URL is never exposed; reconcile settles the order later).
- Credits do not appear after payment: verify webhook delivery in the Lemon
  dashboard, confirm the signing secret, and check logs for
  `billing.webhook.*` and the `billing_webhook_events` inbox row. The 60s
  pending-sweep and the 15-minute reconcile recover a missed enqueue.

#### Razorpay Billing (issue #44 — INR alternative)

Razorpay is a hosted **Payment Links** integration — no SDK, no CSP change.
Unlike Lemon Squeezy, Razorpay is **not** a Merchant of Record: sales tax (GST)
and dispute/chargeback liability sit with your account, not Razorpay's, and a
Razorpay chargeback cannot be auto-detected by reconcile — settle it manually
via `POST /billing/admin/correction`.

**How to set up Razorpay:**

1. Create a Razorpay account and complete KYC (required before you can generate
   **live** keys — test keys work immediately for staging).
2. Go to **Settings → API Keys** and generate a key pair. Copy the **Key ID**
   and **Key Secret** into `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`.
3. Go to **Settings → Webhooks** and add a webhook pointing at
   `{BACKEND_URL}/billing/webhook/razorpay` — note this is a **different path**
   from Lemon Squeezy's `{BACKEND_URL}/billing/webhook`. Subscribe to
   `payment_link.paid` and `refund.processed`.
4. Copy the webhook secret into `RAZORPAY_WEBHOOK_SECRET`. As with Lemon, a
   `_PREV` variable exists for a rotation window.
5. Set the success URL and pack economics to match what you want to sell:

```env
RAZORPAY_KEY_ID=rzp_test_...        # MUST be rzp_live_... in production
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_WEBHOOK_SECRET_PREV=        # set during a secret-rotation window only
RAZORPAY_PRICE_CENTS=154900          # minor units — this is paise for INR (₹1549.00)
RAZORPAY_CURRENCY=INR
RAZORPAY_CREDITS_PER_PURCHASE=200
RAZORPAY_CREDIT_VALIDITY_DAYS=30
RAZORPAY_SUCCESS_URL=http://localhost:5173/billing   # MUST be https:// in production
RAZORPAY_CHECKOUT_TTL_MINUTES=30     # must be >= 16, Razorpay rejects shorter link expiries
RAZORPAY_API_BASE=https://api.razorpay.com
RAZORPAY_RECONCILE_MAX_CALLS_PER_RUN=200
```

> `RAZORPAY_PRICE_CENTS=154900` (₹1549) is not a currency conversion of the
> Lemon $15 price — since Razorpay isn't a Merchant of Record, ~18% GST comes
> off this gross on your side, netting roughly ₹1313 ≈ $14.9. Re-derive the
> INR gross if you change the USD-equivalent price you're targeting.

6. Send a **test webhook delivery** from Razorpay's dashboard and confirm it
   returns `200` before flipping `PAYMENTS_ENABLED=true` for real users.

Production guardrails (`validate_production_settings()`): when
`PAYMENT_PROVIDER=razorpay` and `PAYMENTS_ENABLED=true`, the backend refuses to
start unless `RAZORPAY_WEBHOOK_SECRET` is set, `RAZORPAY_SUCCESS_URL` is HTTPS,
price/credits/validity are positive, currency is non-empty,
`RAZORPAY_KEY_ID` starts with `rzp_live_` (not `rzp_test_`), and
`RAZORPAY_CHECKOUT_TTL_MINUTES >= 16`.

Common errors:

- Backend refuses to start in production: `RAZORPAY_KEY_ID` still has the
  `rzp_test_` prefix — Razorpay has no separate test-mode flag like Lemon
  Squeezy, the key prefix *is* the environment.
- Checkout returns 503: `PAYMENTS_ENABLED` is false, or `PAYMENT_PROVIDER` is
  not `razorpay`, or a required Razorpay variable is blank.
- Credits do not appear after payment: verify the webhook delivery in the
  Razorpay dashboard, confirm `RAZORPAY_WEBHOOK_SECRET`, and check logs for
  `billing.webhook.*`. Chargebacks/disputes are not auto-reconciled for
  Razorpay — settle via `POST /billing/admin/correction`.

See `docs/RAZORPAY_INTEGRATION_PLAN.md` and `docs/RUNBOOK.md` §9.9 for deeper
Razorpay ops.

#### Stripe (decommissioned — T-308)

Stripe was the Phase-18 provider; it has been **fully decommissioned** (T-308).
There is no Stripe SDK, no `STRIPE_*` settings, and no Stripe webhook processing:
`POST /billing/webhook` answers any Stripe-shaped request (one carrying a
`Stripe-Signature` header) with `{"status":"ignored_provider_disabled"}` before
any body read, signature claim, or DB write. The bounded late-webhook grace
adapter that briefly bridged the cutover has been removed. The only Stripe
artifacts left are the **read-only audit tables** `stripe_credit_packs` /
`stripe_webhook_events` and their backfilled `provider='stripe'` rows (the
historical financial record); no runtime path reads or writes them. There is
nothing to configure — do not set any `STRIPE_*` variables.

---

### Sentry (optional — skip for first deploy)

Sentry catches and reports errors from the running app. Useful once you have
real users. Skip it on your first deployment — Thought2Build works without it.

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

This section walks you through putting Thought2Build live on the internet for the
first time. Work through these steps in order.

### What you need before starting

- A GitHub account with this repository pushed to it.
- A Railway account ([railway.app](https://railway.app)) — free to sign up.
- A Vercel account ([vercel.com](https://vercel.com)) — free to sign up.
- Your Google OAuth credentials (from section 2 above).
- At least one LLM provider API key.
- Lemon Squeezy or Razorpay credentials only if you plan to enable paid credit
  packs at launch — otherwise leave `PAYMENTS_ENABLED=false` and add a provider
  later with zero downtime.

### Step 1 — Set up Railway (backend + databases)

Railway will host the FastAPI server, **two arq worker processes**, PostgreSQL,
and Redis. All three application services (`backend`, `worker`, `worker-fast`)
are required — not just `backend` — or GitHub jobs and billing webhooks never
process even though the app otherwise looks fine.

**Create a project:**

1. Log into [railway.app](https://railway.app).
2. Click **New Project** → **Empty Project**. Name it `thought2build`.

**Add PostgreSQL:**

3. Click **Add a service** → **Database** → **Add PostgreSQL**.
4. Railway creates the database. Click the PostgreSQL service tile to see its
   details.
5. Go to the **Connect** tab → copy the **Private URL**.

**Add Redis:**

6. Click **Add a service** → **Database** → **Add Redis**.
7. Click the Redis tile → **Connect** tab → copy the **Private URL**.

**Add the three backend services (`backend`, `worker`, `worker-fast`):**

8. Click **Add a service** → **GitHub Repo**, connect Railway to your GitHub
   account if prompted, then select this repository. Name this service
   `backend`.
9. Repeat step 8 **two more times** — once for `worker`, once for
   `worker-fast` — each pointing at the same GitHub repository.
10. On **all three** services, set **Settings → Config-as-code → Config File
    Path** explicitly (this is what tells Railway which process each service
    runs — the `startCommand` differs per service):

    | Service name | Config File Path |
    | --- | --- |
    | `backend` | `/backend/railway.json` |
    | `worker` | `/backend/railway.worker.json` |
    | `worker-fast` | `/backend/railway.worker-fast.json` |

    (You do **not** need to set a Root Directory separately — each config file
    already points at `backend/`.)
11. Railway may start a first build on each automatically — that is fine.

**Set environment variables on the backend service:**

12. Click the `backend` service tile → go to the **Variables** tab.
13. Add each variable listed below. Click **Add Variable** for each one.

    | Variable | Value |
    | --- | --- |
    | `ENVIRONMENT` | `production` |
    | `DATABASE_URL` | The PostgreSQL Private URL from step 5, with `postgresql://` changed to `postgresql+asyncpg://` |
    | `REDIS_URL` | The Redis Private URL from step 7 |
    | `FRONTEND_URL` | Your Vercel URL — come back and fill this in after step 2. For now leave it blank or use a placeholder. |
    | `ALLOWED_HOSTS` | Comma-separated allowed `Host` headers, e.g. `api.thought2build.com,*.up.railway.app`. **Required in production** — the backend refuses to start without it. Keep the `*.up.railway.app` entry even after attaching a custom domain (Railway's own healthcheck uses it). |
    | `JWT_PRIVATE_KEY` | Generated below |
    | `JWT_PUBLIC_KEY` | Generated below |
    | `GOOGLE_CLIENT_ID` | From Google Cloud Console |
    | `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
    | `ANTHROPIC_API_KEY` | Your Anthropic key (or leave blank if not using Anthropic) |
    | `OPENAI_API_KEY` | Your OpenAI key (or leave blank if not using OpenAI) |
    | `GOOGLE_API_KEY` | Your Gemini key (or leave blank if not using Gemini) |
    | `OPENROUTER_API_KEY` | Optional (issue #152) — your OpenRouter key for the open-weight fallback tier, or leave blank. Not part of the minimal go-live path. |
    | `GITHUB_CLIENT_ID` | Your GitHub OAuth App client ID (legacy Phase-13 export, or leave blank) |
    | `GITHUB_CLIENT_SECRET` | Your GitHub OAuth App client secret (or leave blank) |
    | `GITHUB_APP_ID` / `GITHUB_APP_SLUG` / `GITHUB_APP_PRIVATE_KEY` / `GITHUB_APP_WEBHOOK_SECRET` / `GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET` | Phase-21 GitHub App (optional) — see the [GitHub App section](#github-app-phase-21--optional-the-bidirectional-living-system-of-record) above. Leave all blank to skip. |
    | `PAYMENTS_ENABLED` | `false` to launch with checkout off (recommended for a first launch); `true` once a provider below is fully configured and tested |
    | `PAYMENT_PROVIDER` | `lemonsqueezy` or `razorpay` — **must be a valid value even while `PAYMENTS_ENABLED=false`**, production refuses to boot on a blank/misspelled value |
    | `LEMONSQUEEZY_API_KEY` | Blank to leave this provider unconfigured; the Lemon Squeezy API key for production billing |
    | `LEMONSQUEEZY_STORE_ID` | Lemon store id (required to enable checkout) |
    | `LEMONSQUEEZY_VARIANT_ID` | Lemon product-variant id for the credit pack |
    | `LEMONSQUEEZY_WEBHOOK_SECRET` | Lemon webhook signing secret when billing is enabled |
    | `LEMONSQUEEZY_WEBHOOK_SECRET_PREV` | Previous secret, set only during a rotation window |
    | `LEMONSQUEEZY_PRICE_CENTS` | Credit pack price in cents, e.g. `900` |
    | `LEMONSQUEEZY_CURRENCY` | ISO 4217 currency, e.g. `USD` |
    | `LEMONSQUEEZY_CREDITS_PER_PURCHASE` | Credits granted per purchase, e.g. `200` |
    | `LEMONSQUEEZY_CREDIT_VALIDITY_DAYS` | Credit expiry window, e.g. `30` |
    | `LEMONSQUEEZY_SUCCESS_URL` | Your frontend billing URL, e.g. `https://your-vercel-url.vercel.app/billing` |
    | `LEMONSQUEEZY_TEST_MODE` | `true` for staging; **must be `false`** in production |
    | `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` / `RAZORPAY_PRICE_CENTS` / `RAZORPAY_CURRENCY` / `RAZORPAY_CREDITS_PER_PURCHASE` / `RAZORPAY_CREDIT_VALIDITY_DAYS` / `RAZORPAY_SUCCESS_URL` / `RAZORPAY_CHECKOUT_TTL_MINUTES` | Only if `PAYMENT_PROVIDER=razorpay` — see the [Razorpay Billing section](#razorpay-billing-issue-44--inr-alternative) above |
    | `ADMIN_USER_EMAILS` | Comma-separated emails allowed to issue billing admin corrections (empty = nobody) |
    | `ENCRYPTION_MASTER_KEY` | Generated below |
    | `CSRF_SECRET` | Generated below |
    | `METRICS_TOKEN` | Generated below |
    | `WEB_CONCURRENCY` | Optional cost lever — `1` keeps `backend` to a single async worker (roughly halves its memory bill) at pre-launch traffic; bump to `2` once real traffic arrives. Workers ignore this variable. |

14. Copy the **same environment variables** onto the `worker` and
    `worker-fast` services (Railway's "Variable References" / "Shared
    Variables" feature can do this in one place — use it if offered instead of
    keeping three copies in sync by hand). Only `backend` needs
    `WEB_CONCURRENCY`; the other two ignore it either way.

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

15. Once all variables are set, go to the `backend` service → **Settings** →
    **Networking** → **Generate Domain**. Railway gives you a public URL like
    `https://thought2build-backend-production.up.railway.app`. Copy it — you need
    it for Vercel. `worker` and `worker-fast` don't serve HTTP traffic, so skip
    this for them.

16. Check the **Deployments** tab and confirm **all three services** —
    `backend`, `worker`, and `worker-fast` — started successfully, not just
    `backend`. Visit `https://your-railway-url/health` — you should see
    `{"status":"ok","version":"1.0.0"}`.

> **If the deployment fails:** go to the **Deployments** tab, click the failed
> deploy, and read the build/runtime logs. The most common issues are a missing
> environment variable or a wrong `DATABASE_URL` format. A `worker`/`worker-fast`
> deploy failing on the `Config File Path` step usually means step 10 above
> wasn't set correctly for that service.

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
   | `VITE_API_URL` | Your Railway backend URL from step 1 (e.g. `https://thought2build-backend-production.up.railway.app`) |
   | `VITE_SENTRY_DSN` | Leave blank unless you set up Sentry |

6. Click **Deploy**. Vercel builds the frontend and gives you a URL like
   `https://thought2build-abc123.vercel.app`.

7. Copy your Vercel URL. Go back to Railway and set `FRONTEND_URL` on the
   `backend` service to this URL (it must start with `https://`). If you used
   Railway's Variable References/Shared Variables in Step 1, this also updates
   `worker` and `worker-fast` automatically — otherwise update it on those two
   services by hand as well.

8. Go back to Google Cloud Console and add your Vercel URL to **Authorized
   JavaScript origins** and `https://your-vercel-url.vercel.app/auth/callback`
   to **Authorized redirect URIs**.

9. Redeploy the `backend` service so it picks up the updated `FRONTEND_URL` (in
   Railway → the `backend` service → **Deployments** → **Deploy**).

10. Visit your Vercel URL and try signing in.

---

### Step 3 — Set up GitHub Secrets (automated deployment)

Right now, deployments only happen when you manually trigger them in Railway or
Vercel. To make deploys automatic on every push to `main`, configure GitHub
Actions.

**What you need:**

- Three Vercel identifiers (token, org ID, project ID)

**Railway needs no token — it deploys itself.** The `backend`, `worker`, and
`worker-fast` services are each connected to this repo's `main` branch with
**Auto deploys when pushed to GitHub** *and* **Wait for CI** enabled (service →
**Settings** → **Source**), so Railway builds them once this workflow goes green.
CI therefore contains **no** `railway up` step and no `RAILWAY_TOKEN`.

> Do not re-add a `railway up` step. Each service resolves its root directory
> (`/backend`) and its config file (`/backend/railway.json`,
> `railway.worker.json`, `railway.worker-fast.json`) *relative to the repo root*,
> so `railway up ./backend --path-as-root` — which makes the backend folder the
> snapshot root — fails initialization with
> `service config at '/backend/railway.json' not found`. It would also
> double-build every push alongside the GitHub trigger.

**Get Vercel credentials:**

1. In Vercel, go to **Account Settings** → **Tokens** → **Create Token**. Name
   it `github-actions`. Copy the token.
2. Your **Vercel Org ID** is shown in **Account Settings** under your profile.
   It looks like `team_xxxxxxx` or just a string of characters.
3. Your **Vercel Project ID** is shown in the project's **Settings** →
   **General** at the top of the page.

**Add the secrets to GitHub:**

4. Go to your GitHub repository → **Settings** → **Secrets and variables** →
   **Actions** → **New repository secret**. Add one at a time:

   | Secret name | Value |
   | --- | --- |
   | `VERCEL_TOKEN` | The Vercel token |
   | `VERCEL_ORG_ID` | Your Vercel org/account ID |
   | `VERCEL_PROJECT_ID` | Your Vercel project ID (the SPA project) |

   Optional — only if you launch the marketing zone (section 7):

   | Secret name | Value |
   | --- | --- |
   | `VERCEL_MARKETING_PROJECT_ID` | The project ID of the **marketing** Vercel project (rooted at `apps/marketing`). Until this is set, the marketing deploy step in CI is **skipped, not failed** — so adding the marketing zone later never breaks the existing backend/SPA deploy. |

   Optional but recommended for prompt-eval and provider smoke workflows:

   | Secret name | Value |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | Anthropic key for prompt/provider eval jobs |
   | `OPENAI_API_KEY` | OpenAI key for prompt/provider eval jobs |
   | `GOOGLE_API_KEY` | Gemini key for prompt/provider eval jobs |

5. Push any small change to `main`. Watch the **Actions** tab in GitHub — the run
   should end with the `Deploy` job pushing the SPA (and marketing) to Vercel.
   Railway's three services pick the same commit up on their own once the run is
   green; watch them in the Railway dashboard's **Deployments** tab.

---

### Step 4 — Verify the live deployment

1. Visit your Vercel URL. The landing page should load.
2. Click **Sign in with Google** and complete the flow. You should land on
   `/dashboard` with 50 credits.
3. Create a workspace and run a SPEC generation. Tokens should stream in.
4. If Lemon Squeezy billing is enabled, open `/billing`, create a test checkout
   in staging, and confirm the `order_created` webhook grants credits once.
5. Check the Railway backend logs (Deployments → the running deploy →
   **View Logs**) for any errors.

If something is wrong, the [Troubleshooting Guide](#5-troubleshooting-guide)
at the bottom of this document covers the most common issues.

---

### Step 5 — Set up the production smoke test (optional but recommended)

After each deploy you can run an automated check that hits the live app:

```bash
THOUGHT2BUILD_API_URL=https://your-railway-url \
THOUGHT2BUILD_ACCESS_TOKEN=<your access token — see below> \
THOUGHT2BUILD_METRICS_TOKEN=<your METRICS_TOKEN value> \
THOUGHT2BUILD_RUN_LLM_SMOKE=1 \
python3 scripts/production_smoke.py
```

To get a temporary access token for the smoke test:

1. Open your Vercel URL in a browser and sign in.
2. Open browser DevTools → **Network** tab.
3. Look for the request to `/auth/callback` on the backend.
4. In the response JSON, copy the `access_token` value.
5. Use it as `THOUGHT2BUILD_ACCESS_TOKEN` above. The token expires quickly so run
   the smoke test immediately after copying it.

You can also run this from GitHub Actions via the **Production Smoke** workflow
(`.github/workflows/production-smoke.yml`). Add `THOUGHT2BUILD_SMOKE_ACCESS_TOKEN`
and `THOUGHT2BUILD_METRICS_TOKEN` as GitHub Secrets to enable it.

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
DATABASE_URL=postgresql+asyncpg://thought2build:thought2build@localhost:5432/thought2build
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

GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=

GITHUB_APP_ID=
GITHUB_APP_SLUG=
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_WEBHOOK_SECRET=
GITHUB_APP_WEBHOOK_SECRET_PREV=
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=

PAYMENTS_ENABLED=false
PAYMENT_PROVIDER=lemonsqueezy

LEMONSQUEEZY_API_KEY=
LEMONSQUEEZY_WEBHOOK_SECRET=
LEMONSQUEEZY_WEBHOOK_SECRET_PREV=
LEMONSQUEEZY_STORE_ID=
LEMONSQUEEZY_VARIANT_ID=
LEMONSQUEEZY_PRICE_CENTS=900
LEMONSQUEEZY_CURRENCY=USD
LEMONSQUEEZY_CREDITS_PER_PURCHASE=200
LEMONSQUEEZY_CREDIT_VALIDITY_DAYS=30
LEMONSQUEEZY_SUCCESS_URL=http://localhost:5173/billing
LEMONSQUEEZY_TEST_MODE=true

RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_WEBHOOK_SECRET_PREV=
RAZORPAY_PRICE_CENTS=154900
RAZORPAY_CURRENCY=INR
RAZORPAY_CREDITS_PER_PURCHASE=200
RAZORPAY_CREDIT_VALIDITY_DAYS=30
RAZORPAY_SUCCESS_URL=http://localhost:5173/billing
RAZORPAY_CHECKOUT_TTL_MINUTES=30

ADMIN_USER_EMAILS=

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
# ALLOWED_HOSTS is deliberately left unset here — it's production-only (the
# Host-header middleware isn't added when blank, so local/compose flows on
# any host work). Never set it locally.
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
- `ALLOWED_HOSTS` must be non-empty (comma-separated `Host` header allowlist).
- `JWT_PRIVATE_KEY` must be a real PEM key (not the CI placeholder).
- `ENCRYPTION_MASTER_KEY` must not be the CI placeholder value.
- `PAYMENT_PROVIDER` must be exactly `lemonsqueezy` or `razorpay` — required
  even when `PAYMENTS_ENABLED=false`.
- `SITE_URL` is optional, but **if set it must start with `https://`** (it is the
  backend mirror of the marketing canonical origin used for canonical/OG/sitemap
  concerns; an `http://` value fails startup). Leave it blank if you are not
  running the marketing zone — no backend code reads it yet.
- If Lemon billing is enabled in production (`PAYMENTS_ENABLED=true`,
  `PAYMENT_PROVIDER=lemonsqueezy`, and `LEMONSQUEEZY_API_KEY` +
  `LEMONSQUEEZY_STORE_ID` + `LEMONSQUEEZY_VARIANT_ID` all set),
  `LEMONSQUEEZY_WEBHOOK_SECRET` must be set, `LEMONSQUEEZY_SUCCESS_URL` must use
  `https://`, and `LEMONSQUEEZY_TEST_MODE` must be `false`. Leave the three core
  keys blank to intentionally disable billing checkout.
- If Razorpay billing is enabled in production (`PAYMENTS_ENABLED=true`,
  `PAYMENT_PROVIDER=razorpay`), `RAZORPAY_WEBHOOK_SECRET` must be set,
  `RAZORPAY_SUCCESS_URL` must use `https://`, price/credits/validity must be
  positive, `RAZORPAY_KEY_ID` must start with `rzp_live_`, and
  `RAZORPAY_CHECKOUT_TTL_MINUTES` must be at least `16`.
- If the GitHub App is enabled (`GITHUB_APP_ID` + `GITHUB_APP_SLUG` both set),
  `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`, and both
  `GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET` must all be set.
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

This starts PostgreSQL, Redis, the FastAPI backend, the Vite frontend, and the
two arq worker containers (`worker` and `worker-fast`, which drain GitHub jobs
and billing webhooks respectively). Wait until you see
`Uvicorn running on http://0.0.0.0:8000`.

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

### Check billing package

```bash
curl http://localhost:8000/billing/package
```

Expected: JSON with price, credits, and validity window. Blank Lemon Squeezy
keys are valid for local development and mean checkout creation is disabled
(`POST /billing/checkout` returns 503).

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

### Billing checkout does not work

Check first, regardless of provider:

- `PAYMENTS_ENABLED=true` — checkout is inert with it `false`, by design.
- `PAYMENT_PROVIDER` matches the provider you actually configured
  (`lemonsqueezy` or `razorpay`) — a mismatch means `GET /billing/package`
  reports the wrong/unconfigured provider as active.

If `PAYMENT_PROVIDER=lemonsqueezy`:

- `LEMONSQUEEZY_API_KEY`, `LEMONSQUEEZY_STORE_ID`, and `LEMONSQUEEZY_VARIANT_ID`
  are all set.
- In production, `LEMONSQUEEZY_TEST_MODE` is `false` and
  `LEMONSQUEEZY_SUCCESS_URL` uses `https://`; otherwise startup validation fails.
- `LEMONSQUEEZY_SUCCESS_URL` points to `{FRONTEND_URL}/billing` (there is no
  cancel URL).
- The Lemon webhook endpoint is `{BACKEND_URL}/billing/webhook`, uses the
  `LEMONSQUEEZY_WEBHOOK_SECRET` signing secret, and is subscribed to
  `order_created` / `order_refunded`.
- Backend logs for `billing.webhook.*` failures and the `billing_webhook_events`
  inbox row for the order.

If `PAYMENT_PROVIDER=razorpay`:

- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` are
  all set, and in production `RAZORPAY_KEY_ID` starts with `rzp_live_` (not
  `rzp_test_`) — Razorpay's key prefix is the environment, there's no separate
  test-mode flag.
- The Razorpay webhook endpoint is `{BACKEND_URL}/billing/webhook/razorpay`
  (a **different path** from Lemon's) and is subscribed to
  `payment_link.paid` / `refund.processed`.
- `RAZORPAY_CHECKOUT_TTL_MINUTES` is at least `16`.
- Backend logs for `billing.webhook.*` failures. Razorpay chargebacks aren't
  auto-reconciled — settle via `POST /billing/admin/correction`.

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

---

## 7. Marketing Zone (SEO + GEO content site)

This section is **optional**. The product runs fine without it — skip everything
here until you want organic (search) and answer-engine (GEO — ChatGPT,
Perplexity, Gemini, Copilot, Claude) acquisition. It was built under issue #18;
the full architecture and phase-by-phase build log live in
`docs/ISSUE_18_SEO_GEO_LAUNCH_PLAN.md`.

### What it is and why it is separate

The SPA (`frontend/`) is a client-rendered Vite + React app: the only HTML a
crawler sees is an empty `<div id="root">` shell, so it is effectively invisible
to search engines and answer engines. The marketing zone solves that without
touching the SPA: it is a **separate Astro static site** under `apps/marketing/`
that emits real, crawlable HTML with complete metadata and validated structured
data, and pulls its content from **Sanity** at build time.

In production it runs as a **second Vercel project** that owns the apex domain
and uses Vercel multi-zone **rewrites** (`apps/marketing/vercel.json`) to forward
all app/artifact paths to the SPA project. Everything stays on one origin, so
OAuth redirect URIs, the refresh cookie, CSRF, and CORS are unchanged.

What ships where:

- **Marketing zone serves (real static HTML):** `/` (homepage), the five content
  hubs and their detail pages — `/use-cases/*`, `/guides/*`, `/templates/*`,
  `/compare/*`, `/demos/*` — plus `/sitemap.xml` and `/robots.txt`.
- **Rewritten to the SPA project:** `/dashboard`, `/workspace/*`, `/settings`,
  `/billing`, `/auth/*`, `/p/*`, `/sb/*`, `/assets/*`.
- **Still `noindex` (must not regress):** the public artifact pages `/p/*` and
  `/sb/*` stay `noindex, nofollow` via `frontend/public/_headers`, both
  `robots.txt` files, the backend `X-Robots-Tag`, and JS-injected meta. The
  marketing zone opens crawling for content **only** — never for user data.

### Important: content lives in Sanity, not in the repo

The repo ships the page **templates, the five hub pages, and the in-repo framing
copy** — but the actual guide / use-case / comparison / template / demo
**documents are authored in the Sanity studio** (`apps/marketing/sanity/`) and
fetched at build time. With Sanity unconfigured, a build produces only the
homepage and the five hub index pages; every detail route yields zero pages. So
launching the zone with real content has two parts: **(1)** stand up Sanity and
author content, **(2)** deploy the marketing Vercel project. You can deploy the
zone with no Sanity creds first (homepage + hubs only) — the fetch layer degrades
gracefully to empty content and the build stays green.

### Step A — Set up Sanity (the content CMS)

1. Go to [sanity.io](https://www.sanity.io/) and create an account and a project.
   Note the **Project ID** (a short string) and the **dataset** name (use
   `production`). These are **public** values — they appear in every browser
   request to the Sanity API, so they are fine to expose (`PUBLIC_`-prefixed
   below). **Do not** create or expose a read token: published content on a
   public dataset is read tokenlessly at build time, and a token must never be
   `PUBLIC_`-prefixed.
2. Deploy the studio. The studio is a **standalone** package in
   `apps/marketing/sanity/` (deliberately not embedded in the public site, so no
   editor surface is ever served on the marketing origin):

   ```bash
   cd apps/marketing/sanity
   pnpm install
   npx sanity deploy      # publishes the editing studio (e.g. https://<project>.sanity.studio)
   ```
3. In the studio, author content for the document types you want live: `guide`,
   `seoPage` (powers `/use-cases/*` and `/compare/*`), `templatePage`, and
   `demoPage`. Demos are **curated, first-party only** — there is no
   import-from-a-user-workspace path, by design.

### Step B — Create the marketing Vercel project

This is a **second** Vercel project, separate from the SPA project you created in
[section 3, Step 2](#step-2--set-up-vercel-frontend).

1. In Vercel, **Add New Project** → import this same GitHub repository again.
2. Set the **Root Directory** to `apps/marketing`. Framework preset: **Astro**.
3. Add the environment variables below (Vercel → the marketing project →
   **Settings** → **Environment Variables**). Astro bakes `PUBLIC_*` values in at
   build time, so a change only takes effect on the next deploy.

   | Variable | Value |
   | --- | --- |
   | `PUBLIC_SITE_URL` | The HTTPS **apex** origin this project serves, e.g. `https://thought2build.com`. Drives canonical URLs, OG absolute URLs, and the sitemap base. |
   | `PUBLIC_API_URL` | Your Railway backend URL. The "Sign in with Google" CTA links to `${PUBLIC_API_URL}/auth/google`, mirroring the SPA. |
   | `PUBLIC_SANITY_PROJECT_ID` | Your Sanity Project ID. Leave blank to build homepage + hubs only (no detail pages). |
   | `PUBLIC_SANITY_DATASET` | `production` (or your dataset name). |
   | `PUBLIC_SANITY_API_VERSION` | Pinned API date, e.g. `2024-10-01`. |
   | `PUBLIC_ANALYTICS_ENABLED` | `false` by default — the zone ships **zero** analytics JS unless this is exactly `true`. Set `true` to enable the first-party Vercel Web Analytics island (also enable the integration on the Vercel project). |
   | `PUBLIC_GSC_VERIFICATION` | Optional Google Search Console verification token (the `content` of the `<meta name="google-site-verification">` tag). Leave blank if verifying by DNS. |

4. Assign the **apex domain** to this marketing project, and keep the SPA on its
   own project/subdomain (the one whose URL you set as `VITE_API_URL` / the
   backend `FRONTEND_URL`).

### Step C — Point the rewrites at the real SPA host

`apps/marketing/vercel.json` rewrites every `/dashboard`, `/workspace/*`,
`/settings`, `/billing`, `/auth/*`, `/p/*`, `/sb/*`, `/assets/*` destination to
the SPA project's stable Vercel URL — for thought2build.com this is
`https://thought2build.vercel.app` (the SPA project's own default domain; not a
`-app` suffixed variant, which does not exist). If the SPA project's default
domain is ever renamed, `vercel.json` must be updated in the same change, or
`/dashboard`, `/p/*`, etc. on the apex domain will 404.

### Step D — Set the backend `SITE_URL`

On the Railway backend, set `SITE_URL` to the same HTTPS apex origin as
`PUBLIC_SITE_URL`. It is the backend mirror of the canonical origin; it is
optional, but if set it **must be HTTPS** or the backend refuses to start
(see [Production-only requirements](#production-only-requirements)).

### Step E — Enable automatic deploys (GitHub secret)

Add the `VERCEL_MARKETING_PROJECT_ID` GitHub secret (the marketing project's ID),
as described in [section 3, Step 3](#step-3--set-up-github-secrets-automated-deployment).
The CI `marketing` job builds and tests the zone on every push; the deploy step
is skipped until this secret exists, so adding the zone never breaks the existing
backend/SPA deploy.

### Step F — Wire content refresh (Sanity → Vercel deploy hook)

Because Sanity content is fetched at **build time**, an editor's change only goes
live on a rebuild. Connect them:

1. In the marketing Vercel project → **Settings** → **Git** → **Deploy Hooks**,
   create a hook and copy its URL.
2. In Sanity → **API** → **Webhooks**, add a webhook that POSTs to that deploy
   hook URL on document publish.

Now publishing content in Sanity triggers a marketing-zone rebuild automatically.
(Instant publish without a rebuild — ISR — is a deliberate future upgrade, out of
scope for launch.)

### Marketing zone `.env` (local builds)

For building the zone locally, copy `apps/marketing/.env.example` to
`apps/marketing/.env`:

```env
PUBLIC_SITE_URL=https://thought2build.com
PUBLIC_API_URL=https://api.thought2build.com

PUBLIC_SANITY_PROJECT_ID=your_project_id   # blank ⇒ homepage + hubs only
PUBLIC_SANITY_DATASET=production
PUBLIC_SANITY_API_VERSION=2024-10-01

PUBLIC_ANALYTICS_ENABLED=false             # exactly "true" to ship analytics JS
PUBLIC_GSC_VERIFICATION=                   # GSC meta token, or blank for DNS
```

### Verify the marketing zone

```bash
cd apps/marketing
pnpm install
pnpm check     # astro check / type gate
pnpm build     # static build → dist/
pnpm test      # the issue-#18 SEO/GEO contract suite (metadata, sitemap,
               # robots, noindex regression, structured data, GEO content QA)
pnpm preview   # serve dist/ locally to view-source the HTML
```

Then confirm against the built output / preview:

1. `dist/index.html` and each hub emit a real `<h1>`, a unique `<title>` and meta
   description, canonical, OG, Twitter, and JSON-LD (not an empty root div).
2. `dist/sitemap-index.xml` lists only indexable routes — **not** `/p/*`, `/sb/*`,
   or app routes.
3. `dist/robots.txt` allows `/` and the hubs and disallows `/p/` and `/sb/`.
4. Validate the JSON-LD in Google's Rich Results test.
5. **Must-not-regress:** on the live apex domain, `/p/<slug>` and `/sb/<slug>`
   still return `noindex` (the rewrite resolves to the SPA zone; `_headers` and
   the backend `X-Robots-Tag` are present).

### Marketing zone troubleshooting

- **App paths 404 on the apex domain** (`/dashboard`, `/p/...`): the placeholder
  SPA host in `apps/marketing/vercel.json` was not replaced with the real SPA
  host (Step C).
- **Detail pages are missing, only homepage + 5 hubs build:** Sanity is
  unconfigured (`PUBLIC_SANITY_PROJECT_ID` blank) or has no published content.
  This is the expected graceful-degradation state, not an error.
- **Backend refuses to start after setting `SITE_URL`:** the value is not HTTPS.
- **Marketing deploy never runs in CI:** `VERCEL_MARKETING_PROJECT_ID` is not set
  — the step is intentionally skipped, not failed.
- **Content edits do not appear:** the Sanity → Vercel deploy hook (Step F) is
  missing; content is build-time, so a rebuild is required.
- **Analytics not recording:** `PUBLIC_ANALYTICS_ENABLED` is not exactly `true`,
  or the `@vercel/analytics` integration is not enabled on the Vercel project.
  (Note: Vercel custom events need a Pro plan; on Hobby the native referrer
  breakdown is the guaranteed baseline.)
