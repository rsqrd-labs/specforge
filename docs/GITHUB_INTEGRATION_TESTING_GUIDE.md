# GitHub Integration Testing Guide

This guide walks you through setting up **both** of Thought2Build's GitHub
integrations on your local machine so you can actually click through and test
them. It assumes no prior experience with GitHub Apps, OAuth Apps, or
webhooks — every concept is explained before you're asked to use it.

This guide is about **local testing only**. For production deployment, see
`docs/INTEGRATION_API_SETUP_HANDBOOK.md`.

---

## 1. The two integrations, in plain language

Thought2Build actually has **two separate** GitHub features, built in different
phases. They don't replace each other — both can be on at the same time.

| | Phase 13 — "GitHub Export" | Phase 21 — "GitHub Living System of Record" |
|---|---|---|
| What it does | One-shot: pushes your Spec/Plan/Tasks/Harness as files to a **new** GitHub repo, and creates one GitHub Issue per task. | Keeps Thought2Build and GitHub **in sync over time**: closing an issue on GitHub marks the task done in Thought2Build, PRs merge and close tasks, a Projects board tracks progress, increments add new issues later, etc. |
| How the user connects | Classic "Connect GitHub" **OAuth App** login (like "Sign in with GitHub") | **Install** a GitHub App on specific repos (like installing a bot) |
| Talks to GitHub | Directly from the request, using the user's OAuth token | Through a background **worker** process, using a per-installation token, and GitHub calls **back** into Thought2Build via a **webhook** |
| Env vars | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`(`_PREV`), `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET` |
| Status in this repo | Already configured in your `backend/.env` | Blank — this is the one you need to set up |

Two new concepts show up only in Phase 21, so a quick primer:

- **Webhook** — a URL that GitHub sends an HTTP request to every time
  something happens on your repo (an issue closes, a PR merges, etc.). Your
  laptop doesn't have a public URL, so step 3 below uses a free relay
  (smee.io) to forward GitHub's requests to `localhost`.
- **Installation** — when someone installs a GitHub App on their account/org
  and picks which repos it can see. This is different from an OAuth login;
  it's closer to installing a Slack app.

---

## 2. Prerequisites

- The local stack is running: `docker compose up --build` (see the root
  `CLAUDE.md` / `docs/LOCAL_TESTING_HANDBOOK.md` if it isn't up yet).
- A personal GitHub account. **Use a scratch/test repo you own** — this guide
  will create real repos, issues, and PRs on GitHub.
- Node.js available for `npx` (only needed for the webhook relay in Part B).
- You can edit `backend/.env` in this repo (it's already git-ignored, so
  pasted secrets never get committed).

---

## Part A — Phase 13: GitHub OAuth Export

Skip this part if you already have `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`
filled in and just want Phase 21 — check `backend/.env` first, since this repo
may already have it configured.

### A.1 — Create the OAuth App

1. Go to [github.com/settings/developers](https://github.com/settings/developers)
   and sign in.
2. Click **New OAuth App**.
3. Fill in:
   - **Application name**: `Thought2Build Local` (anything works)
   - **Homepage URL**: `http://localhost:5173`
   - **Authorization callback URL**: `http://localhost:5173/auth/github/callback`
     — this must match exactly, including the path.
4. Click **Register application**.
5. Copy the **Client ID** shown on the app page.
6. Click **Generate a new client secret** and copy it immediately — GitHub
   only shows it once.

### A.2 — Add the keys to `backend/.env`

```env
GITHUB_CLIENT_ID=your-github-oauth-app-client-id
GITHUB_CLIENT_SECRET=your-github-oauth-app-client-secret
```

### A.3 — Restart and test

```bash
docker compose up -d --force-recreate api
```

Then work through **"Phase 13 — GitHub Export Integration"** in
`docs/SMOKE_TEST_CHECKLIST.md` (rows P13-1 through P13-15) — it walks through
connecting, exporting a workspace as a repo + issues, re-exporting without
duplicating, disconnecting, and the rate limit.

**Common errors:**
- "Connect GitHub" button missing in Settings → `GITHUB_CLIENT_ID` is blank.
- Callback fails after approving on GitHub → the callback URL on the GitHub
  OAuth App doesn't exactly match `http://localhost:5173/auth/github/callback`.

---

## Part B — Phase 21: GitHub App Living Integration

This is the bigger integration: a real GitHub App, a webhook, and a
background worker. Follow these steps in order — each one only works once the
previous one is done.

### B.1 — Start a webhook relay (smee.io)

GitHub needs a URL it can reach over the internet to deliver webhooks to.
Your laptop's `localhost:8000` isn't reachable from GitHub, so we use
[smee.io](https://smee.io), a free relay, to bridge the gap.

1. Open [https://smee.io/new](https://smee.io/new) in your browser. It
   creates a unique channel URL, something like
   `https://smee.io/AbCdEfGhIjKlMnOp`. Keep this tab open — it will show every
   webhook delivery live, which is handy for debugging.
2. In a terminal, start the relay, forwarding everything to your local
   backend's webhook endpoint:

   ```bash
   npx smee-client -u https://smee.io/AbCdEfGhIjKlMnOp -t http://localhost:8000/integrations/github/webhook
   ```

   Leave this running in its own terminal window for the rest of this guide
   (and every time you test afterward).

### B.2 — Create a dev GitHub App

A "GitHub App" is a different thing from the "OAuth App" in Part A — it's
registered at a different URL and has its own permissions/webhook config.
**Create a brand-new one just for this testing** (don't reuse a
production App if you have one).

1. Go to
   [github.com/settings/apps/new](https://github.com/settings/apps/new) and
   sign in.
2. Fill in the top fields:
   - **GitHub App name**: something unique, e.g. `thought2build-dev-yourname`
     (this becomes the App's public **slug** — note it, you'll need it later)
   - **Homepage URL**: `http://localhost:5173`
3. **Callback URL**: `http://localhost:8000/integrations/github/setup`
   This is different from Part A's callback — it's the backend endpoint that
   finishes the App installation, not a login callback.
4. Check the box **"Request user authorization (OAuth) during
   installation"**. This makes GitHub also hand back an OAuth code when
   someone installs the App, which Thought2Build uses to verify the installer
   actually has access to that installation (a security check — without it,
   the install step is rejected).
5. **Webhook** section:
   - Check **Active**.
   - **Webhook URL**: paste your smee.io URL from step B.1 (e.g.
     `https://smee.io/AbCdEfGhIjKlMnOp`).
   - **Webhook secret**: generate a random one now and save it somewhere —
     you'll paste it into `backend/.env` in a minute:
     ```bash
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
6. **Permissions** — scroll to "Repository permissions" and "Organization
   permissions" and set exactly these (anything not listed can stay "No
   access"):

   | Section | Permission | Access |
   |---|---|---|
   | Repository | Contents | Read and write |
   | Repository | Issues | Read and write |
   | Repository | Pull requests | Read and write |
   | Repository | Checks | Read and write |
   | Repository | Commit statuses | Read and write |
   | Repository | Metadata | Read-only (mandatory, GitHub sets this for you) |
   | Repository | Administration | Read and write |
   | Organization/Account | Projects | Read and write |

7. **Subscribe to events** — check exactly these:
   - `Issues`
   - `Pull request`
   - `Check suite`
   - `Installation`
   - `Installation repositories`
   - `Projects v2 item`
8. **Where can this GitHub App be installed?** → "Only on this account" is
   fine for solo local testing.
9. Click **Create GitHub App**.

### B.3 — Collect the App's credentials

On the App's settings page (you're redirected there after creating it):

1. Near the top, note the **App ID** (a number) and the **App slug** (in the
   URL, e.g. `github.com/settings/apps/thought2build-dev-yourname` → slug is
   `thought2build-dev-yourname`).
2. Scroll to **"Client secrets"** → click **Generate a new client secret**.
   Copy it immediately. Also copy the **Client ID** shown just above it.
3. Scroll to **"Private keys"** → click **Generate a private key**. Your
   browser downloads a `.pem` file — this is the App's private key, used to
   prove the App's identity to GitHub. Open it in a text editor; you'll paste
   its exact contents (including the `BEGIN`/`END` lines) into `.env` next.

You should now have five values in hand: **App ID**, **slug**, **client ID**,
**client secret**, and the downloaded **private key**, plus the **webhook
secret** you generated in step B.2.

### B.4 — Add everything to `backend/.env`

Open `backend/.env` and fill in (or add) these lines. The private key is
multi-line — paste it exactly as downloaded, inside double quotes, the same
way `JWT_PRIVATE_KEY` is already formatted a few lines above in this same
file:

```env
GITHUB_APP_ID=123456
GITHUB_APP_SLUG=thought2build-dev-yourname
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
MIIEow...(the rest of your downloaded .pem, unchanged)...
-----END RSA PRIVATE KEY-----"
GITHUB_APP_WEBHOOK_SECRET=the-secret-you-generated-in-B.2
GITHUB_APP_WEBHOOK_SECRET_PREV=
GITHUB_APP_CLIENT_ID=your-app-client-id
GITHUB_APP_CLIENT_SECRET=your-app-client-secret
GITHUB_WEBHOOK_PROXY_URL=https://smee.io/your-channel
```

Leave `GITHUB_APP_WEBHOOK_SECRET_PREV` blank — it's only used later when
*rotating* a secret (see `docs/RUNBOOK.md` §12.2), not for first-time setup.
Set `GITHUB_WEBHOOK_PROXY_URL` to the same Smee URL configured on this separate
development GitHub App. The default Compose stack supervises the forwarder and
delivers the original signed request to `/integrations/github/webhook`; no
separate terminal command is required. Leave this variable blank outside local
development and configure the App with the deployed API's public HTTPS webhook
URL instead.

### B.5 — Restart the backend and worker

The App only takes effect once the containers pick up the new environment
variables. This is a config change, not a code change, so a full rebuild
isn't necessary — just recreate the containers so they re-read `.env`:

```bash
docker compose up -d --force-recreate api worker worker-fast
```

Watch the logs for a moment to make sure nothing errors on startup:

```bash
docker compose logs -f api worker
```

### B.6 — Install the App from inside Thought2Build

1. Open `http://localhost:5173`, log in, and go to **Settings**.
2. Click **Install GitHub App**. You're sent to GitHub's install screen.
3. Choose your scratch/test repos (or "All repositories" if you don't mind).
4. Approve. You should land back on
   `http://localhost:5173/settings?github_installed=true`, and Settings
   should now show **"Installed on @your-account · N repositories"**.

### B.7 — Verify the wiring actually works

- Your smee.io browser tab (from B.1) should show a delivery for the
  `installation` event the moment you approved in B.6.
- `docker compose logs api` should show the webhook being verified (no
  signature errors).
- In Settings, the installed/repo count should be non-zero.

If any of this doesn't line up, see **Troubleshooting** below before moving
on — the rest of the test script assumes this wiring is solid.

---

## 3. Running the actual test script

Once Part A and/or Part B are wired up, the step-by-step things to click
through and verify are already written down in
**`docs/SMOKE_TEST_CHECKLIST.md`**:

- **"Phase 13 — GitHub Export Integration"** (rows P13-1 to P13-15): connect,
  export as repo+issues, re-export without duplicating, revoke/reconnect,
  disconnect, rate limiting, validation.
- **"Phase 21 — GitHub Living System of Record"** (rows P21-1 to P21-17),
  grouped into sub-phases:
  - **A** — install, export (files mode), installation-token usage, signed
    webhook security (invalid/replayed/out-of-order deliveries rejected).
  - **B** — closing an issue on GitHub flips the task to done in Thought2Build,
    confused-deputy isolation between two installs, worker-kill mid-job
    recovers with no duplicates, backfill recovers missed events.
  - **C** — export in "PR with tests" mode, merging the PR flips tasks done,
    re-finalizing Tasks shows drift + resync updates only changed issues.
  - **C′** — increments only create new issues/milestones on top of existing
    ones, GitHub issues labelled `idea`/`enhancement` flow into the idea
    backlog.
  - **D** — Projects v2 board reflects live state, PR gets a Thought2Build check
    (the fail-open PR evaluator).
  - Plus: suspend/uninstall shows "sync paused" (not an error), and the
    dead-letter + manual-replay path.

Work through the rows in order and mark each 🔲 as you go — later rows
(re-sync, increments, Projects, dead-letter) build on state from earlier ones
(an exported workspace, an installed App).

---

## 4. Troubleshooting

- **Backend fails to start after adding the App env vars** — almost always a
  malformed private key. Make sure the `.pem` content is pasted verbatim,
  including the `-----BEGIN...-----`/`-----END...-----` lines, inside double
  quotes, with real line breaks (not `\n` text).
- **No webhook deliveries showing up in the smee.io tab** — confirm the
  `smee-client` process from B.1 is still running, and that the Webhook URL
  configured on the GitHub App settings page matches your smee.io channel
  URL exactly.
- **Webhook delivers but backend logs a signature/verification failure** —
  `GITHUB_APP_WEBHOOK_SECRET` in `.env` doesn't match the "Webhook secret"
  configured on the GitHub App page. Fix one to match the other and restart
  the `api` container.
- **Install callback fails / redirects with an error** — the App's Callback
  URL must be exactly `http://localhost:8000/integrations/github/setup`, and
  "Request user authorization (OAuth) during installation" must be checked
  (the callback verifies the installer via GitHub's OAuth, and needs both the
  checkbox and `GITHUB_APP_CLIENT_ID`/`_SECRET` to do that).
- **Issue closes on GitHub but the task never flips to done** — check that
  the `worker` container is actually running (`docker compose ps worker`);
  webhooks are received by `api` but processed by the `worker` off a queue.
  Also confirm the `Issues` event is checked in the App's webhook
  subscriptions (B.2 step 7).
- **A GitHub API call returns 403 "resource not accessible"** — a permission
  is missing on the App (re-check the table in B.2 step 6). Permission
  changes to an existing App require re-approving the installation once
  (GitHub will prompt for this automatically on the next install attempt).
- **"Sync paused — reconnect GitHub" banner appears** — this is the circuit
  breaker for a GitHub outage or a revoked/suspended installation, not a bug.
  See `docs/RUNBOOK.md` §12.5.

---

## 5. Cleaning up when you're done testing

- On GitHub: go to the App's settings page →
  **Advanced** → **Delete GitHub App** (or just **Uninstall** if you want to
  keep the App registration for later testing).
- Delete any scratch repos/issues/PRs the tests created.
- Stop the `smee-client` process (Ctrl+C in its terminal).
- Optionally blank the `GITHUB_APP_*` variables back out in `backend/.env`
  and `docker compose up -d --force-recreate api worker worker-fast` to
  return to the App-disabled state — the Phase 13 OAuth path (Part A) keeps
  working independently either way.
