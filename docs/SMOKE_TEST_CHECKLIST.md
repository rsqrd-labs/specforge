# SpecForge V1 — Smoke Test Checklist

Execute against the staging environment before each production deploy.
Tester: ________________  Date: ________________  Environment URL: ________________

Legend: ✅ Pass  ❌ Fail  ⚠️ Pass with notes  🔲 Not tested

Automated gate:

```bash
SPECFORGE_API_URL=https://api.example.com \
SPECFORGE_ACCESS_TOKEN=<short-lived smoke-user access token> \
SPECFORGE_METRICS_TOKEN=<metrics token> \
SPECFORGE_RUN_LLM_SMOKE=1 \
python3 scripts/production_smoke.py
```

Public-only smoke, useful before a smoke access token is available:

```bash
SPECFORGE_API_URL=https://api.example.com \
SPECFORGE_METRICS_TOKEN=<metrics token> \
SPECFORGE_PUBLIC_ONLY_SMOKE=1 \
python3 scripts/production_smoke.py
```

The same automated smoke can also be launched from GitHub Actions through the
`Production Smoke` workflow in `.github/workflows/production-smoke.yml`.

The automated smoke must pass against staging before production deploy. It checks
health, provider catalog, metrics, authenticated user lookup, credits,
workspace create/read/update/archive, and live SPEC streaming when
`SPECFORGE_RUN_LLM_SMOKE=1`. Keep the manual checklist below for browser-only
OAuth and UI interaction coverage.

For prompt changes, also run the Phase 19 prompt eval before deploy:

```bash
cd harness
uv run python -m prompt_eval.run \
  --version "$(grep -oE 'asdd-v[0-9.]+' ../backend/prompts/base.py)" \
  --baseline asdd-v1.7.1 \
  --report ../prompt_eval_report.md
```

Use this checklist with `docs/PRODUCTION_RELEASE_GATE.md`. For observability
troubleshooting during smoke, use `docs/OBSERVABILITY_RUNBOOK.md`.

---

## Authentication

| # | Test | Result | Notes |
|---|------|--------|-------|
| 1 | New user signs in with Google OAuth and is redirected to Dashboard | 🔲 | |
| 2 | New user receives 50 credits on first sign-in (shown in credit banner) | 🔲 | |
| 3 | Returning user signs in and retains existing credit balance | 🔲 | |
| 4 | `GET /auth/me` returns 200 with correct user email | 🔲 | |

---

## Workspace Creation

| # | Test | Result | Notes |
|---|------|--------|-------|
| 5 | Create workspace with valid name and problem statement (≥50 chars) → workspace page opens with all 4 stages visible | 🔲 | |
| 6 | Create workspace with problem statement under 50 chars → validation error shown, form not submitted | 🔲 | |
| 7 | Create workspace with empty name → validation error shown | 🔲 | |
| 8 | Workspace card appears on Dashboard with correct name | 🔲 | |

---

## SPEC Stage — Generation

| # | Test | Result | Notes |
|---|------|--------|-------|
| 9 | Click Generate on SPEC → spinner shown, tokens stream into editor in real time | 🔲 | |
| 10 | Quality badge (score/flags) appears within ~10s after generation completes | 🔲 | |
| 11 | Credit balance decreases by 10 after SPEC generation | 🔲 | |
| 12 | SPEC stage transitions to `draft` status (not yet finalised) | 🔲 | |

---

## Phase 12 — Provider-Agnostic Cost Smoke

Run first with only the OpenAI key configured in staging. Repeat with Anthropic
and Google keys when those providers are enabled for the environment.

| # | Test | Result | Notes |
|---|------|--------|-------|
| P12-1 | OpenAI-only: generate SPEC, PLAN, HARNESS, and TASKS successfully | 🔲 | |
| P12-2 | Logs contain `llm.cost_recorded` for each provider call | 🔲 | |
| P12-3 | Cost log fields include provider, model_tier, operation, stage_type, prompt_version, input/output tokens, estimated_cost_usd, cache_hit, batch, and cross_provider_fallback | 🔲 | |
| P12-4 | Prometheus `/metrics` includes `llm_request_total`, `llm_estimated_cost_usd_total`, token totals, latency buckets, and cross-provider fallback counter | 🔲 | |
| P12-5 | Cross-provider fallback remains `false` during OpenAI-only smoke unless an explicit fallback test is being run | 🔲 | |
| P12-6 | Repeat SPEC/PLAN/HARNESS/TASKS generation with Anthropic key configured | 🔲 | |
| P12-7 | Repeat SPEC/PLAN/HARNESS/TASKS generation with Google key configured | 🔲 | |
| P12-8 | Run dry route eval: `cd backend && uv run python ../scripts/run_llm_route_eval.py --operation all --provider openai --format markdown` | 🔲 | |

---

## SPEC Stage — Refine Flow

| # | Test | Result | Notes |
|---|------|--------|-------|
| 13 | Select a section of SPEC, click Refine → credit confirmation modal appears | 🔲 | |
| 14 | Confirm refine → diff viewer appears showing proposed changes | 🔲 | |
| 15 | Accept diff → editor content updates, credit balance decreases by 3 | 🔲 | |
| 16 | Reject diff → editor content unchanged, credits are refunded | 🔲 | |
| 17 | Select >80% of document for refine → large-selection warning shown offering Regenerate alternative | 🔲 | |

---

## SPEC Stage — Finalise & Downstream Effects

| # | Test | Result | Notes |
|---|------|--------|-------|
| 18 | Click Finalise on SPEC → SPEC status changes to `finalised`, PLAN unlocks in navigator | 🔲 | |
| 19 | Edit finalised SPEC content → PLAN, HARNESS, TASKS all show stale warning (`⚠` in navigator) | 🔲 | |
| 20 | Rollback SPEC to previous version → stage reverts to prior content, version counter decreases | 🔲 | |

---

## PLAN Stage — Human Review Gate

| # | Test | Result | Notes |
|---|------|--------|-------|
| 21 | Click Generate on PLAN (first time) → Human Review Gate dialog appears before generation starts | 🔲 | |
| 22 | Cancel review gate → generation does not start | 🔲 | |
| 23 | Acknowledge review gate → generation starts, spinner shown, tokens stream | 🔲 | |
| 24 | Review gate is NOT shown again for the same stage after acknowledgement | 🔲 | |
| 25 | PLAN quality badge appears after generation | 🔲 | |
| 26 | Credit balance decreases by 10 after PLAN generation | 🔲 | |

---

## HARNESS and TASKS Stages

| # | Test | Result | Notes |
|---|------|--------|-------|
| 27 | HARNESS generates only after SPEC and PLAN are both `finalised` | 🔲 | |
| 28 | Attempt to generate HARNESS before PLAN is finalised → error message shown | 🔲 | |
| 29 | TASKS generates only after SPEC, PLAN, and HARNESS are all `finalised` | 🔲 | |
| 30 | Complete full pipeline (SPEC → PLAN → HARNESS → TASKS all finalised) | 🔲 | |

---

## Export

| # | Test | Result | Notes |
|---|------|--------|-------|
| 31 | Export zip downloads successfully once all stages are finalised | 🔲 | |
| 32 | Zip contains `SPEC.md`, `PLAN.md`, `TASKS.md`, and harness directory with stub files | 🔲 | |

---

## Phase 13 — GitHub Export Integration

**Prerequisites:** `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` configured in
the backend environment. The OAuth App's callback URL must be
`{FRONTEND_URL}/auth/github/callback`. Skip this section when GitHub
integration is intentionally disabled for the environment.

| # | Test | Result | Notes |
|---|------|--------|-------|
| P13-1 | Navigate to `/settings`. GitHub card shows **not connected**. | 🔲 | |
| P13-2 | Click **Connect GitHub** → GitHub OAuth consent screen. Approve → return to `/settings?github_connected=true`. | 🔲 | |
| P13-3 | Settings shows **Connected as @{username}** with green status dot; query param cleaned from URL after mount. | 🔲 | |
| P13-4 | Open a fully-finalised workspace. Both **↓ ZIP** and **↑ GitHub** buttons visible in header. | 🔲 | |
| P13-5 | Click **↓ ZIP**. Download contains `SPEC.md`, `PLAN.md`, `TASKS.md`, `harness/...` files (unchanged from pre-Phase-13). | 🔲 | |
| P13-6 | Click **↑ GitHub**. Modal opens in *configure* phase: pre-filled repo name (slugified workspace name), Public/Private pills, issue count pill matching task count. | 🔲 | |
| P13-7 | Submit with Private visibility. Modal switches to *progress* phase with 3 animated dots cycling labels: "Creating repo…" → "Pushing files…" → "Creating issues…". | 🔲 | |
| P13-8 | *Success* phase shows green check, repo URL link, **Open on GitHub ↗** button. Repo on GitHub contains all 4 files at root + harness/ + N Issues (one per task). | 🔲 | |
| P13-9 | Close and re-export to the same repo. Modal succeeds without GitHubRepoExistsError. Issues are **updated, not duplicated** — total issue count unchanged. | 🔲 | |
| P13-10 | Revoke OAuth token in GitHub Settings → retry export. Returns 403 with "GitHub connection expired. Reconnect from Settings." UserIntegration row deleted. | 🔲 | |
| P13-11 | `/settings` → Disconnect → **Yes, disconnect**. Card returns to **not connected**. | 🔲 | |
| P13-12 | Workspace header **↑ GitHub** button is disabled with tooltip "Connect GitHub in Settings to export". **↓ ZIP** still works. | 🔲 | |
| P13-13 | Rate limit: 4 export POSTs within an hour. 4th returns 429 with detail `"GitHub export rate limit reached. Maximum 3 exports per hour."`. ZIP downloads in parallel are unaffected. | 🔲 | |
| P13-14 | Repo name validation: try `../etc/passwd` in configure phase. Inline error appears on blur; submit disabled. | 🔲 | |
| P13-15 | Workspace not finalised → modal Export submit returns 409 with "stage not finalised" detail. | 🔲 | |

---

## Phase 21 — GitHub Living System of Record

**Prerequisites:** the GitHub **App** is enabled (`GITHUB_APP_ID` +
`GITHUB_APP_SLUG`, plus `GITHUB_APP_PRIVATE_KEY` and
`GITHUB_APP_WEBHOOK_SECRET`). Webhooks need public ingress — forward
`smee.io` / `gh webhook forward` → `{BACKEND_URL}/integrations/github/webhook`
(register a **separate dev App** with its own id/key/secret). The **worker**
process must be running (`docker compose ps worker`, or `arq worker.WorkerSettings`).
This is the §24.11 manual end-to-end flow and the **final Phase 21 checkpoint —
re-run it after T-287–T-289**. Skip when the App is intentionally disabled (the
Phase-13 OAuth path covers that environment).

This flow ships A→D — verify each phase before enabling the next surface in prod.

| # | Phase | Test | Result | Notes |
|---|---|------|--------|-------|
| P21-1 | A | From `/settings`, **Install GitHub App** → GitHub install screen → choose repos → return with `?github_installed=true`. Settings shows **Installed on @account · N repositories**. The install row persists in `github_installations`. | 🔲 | T-287 surface |
| P21-2 | A | Export a finalised workspace with **Files** mode. POST `/workspaces/{id}/export/github` returns **202** with a `push_id` (no inline block). The worker creates the repo, pushes `SPEC/PLAN/HARNESS/TASKS` + `harness/`, and opens one Issue per task. | 🔲 | |
| P21-3 | A | Every GitHub call uses a **cached installation token** (no static user token in the write path); webhook **ack p99 < 300 ms** under the signed-fixture load. | 🔲 | |
| P21-4 | A | Signed-fixture security smoke: send **invalid**, **replayed** (duplicate `X-GitHub-Delivery`), and **out-of-order** signed deliveries. Each is rejected/deduped **before** any DB/queue write (O(1)); no task state mutates. | 🔲 | |
| P21-5 | B | **Close an issue** on GitHub → its task flips to **done** in SpecForge within SLO; `GET /workspaces/{id}/sync` shows shipped count rise and `done_via='manual'`. | 🔲 | |
| P21-6 | B | **Confused-deputy**: a delivery for install A cannot mutate a workspace exported under install B (proven by the authz contract; spot-check with two installs if available). | 🔲 | |
| P21-7 | B | **Kill the worker mid-reconcile/export**, restart → the job resumes from the ledger with **no duplicate** repo/issues/PR. | 🔲 | |
| P21-8 | B | **Backfill** recovers missed-while-down events: stop the worker, close an issue, restart, run `POST /workspaces/{id}/sync/backfill` (202) → the task flips done; a webhook-set `pr_merge` is never downgraded to `manual`. | 🔲 | |
| P21-9 | C | Export **PR with tests** mode → exactly **one PR** opens on a `specforge/...` branch with a **red** harness CI run (`.github/workflows/specforge.yml` + failing per-stack tests). Re-export updates the same branch/PR **in place** (no duplicate). | 🔲 | T-288 surface |
| P21-10 | C | Merge that PR → its linked tasks flip **done** via `done_via='pr_merge'`. A `Workflows: write` 403 surfaces a distinct actionable error; a content 409 refetches SHA and retries. | 🔲 | |
| P21-11 | B/C′ | **Re-finalise Tasks** → the push shows **out-of-sync** (drift banner). **Re-sync** (`POST /sync/resync`, 202) updates **only changed** issues. | 🔲 | |
| P21-12 | C′ | Create an **increment** ("add two features") → only **new issues** appear under a **new milestone** on top of shipped v1 work; unchanged tasks are not re-created (stable `task_ref`). | 🔲 | T-289 surface |
| P21-13 | C′ | A GitHub issue labelled `idea`/`enhancement` flows into the **idea backlog** with `source='github'`. | 🔲 | T-289 surface |
| P21-14 | D | Tasks appear on a **Projects v2 board** reflecting live state; merged/closed items move; milestones reflect the increment. | 🔲 | |
| P21-15 | D | A PR carries a **SpecForge check** (the fail-open PR-diff evaluator, distinct from the critic). A judge error posts a **neutral** check (never blocks); the LLM-check cost is **capped per tenant/day**. | 🔲 | |
| P21-16 | A/B | **Suspend / uninstall** the App → the UI surfaces **"sync paused — reconnect GitHub"** (not an error); no push is marked failed. Re-install → backfill recovers and sync resumes. | 🔲 | |
| P21-17 | X | Dead-letter path: force a job past its retry budget → `specforge_github_job_deadlettered_total` increments and the alert fires; manual replay (RUNBOOK §12.4) of the idempotent job recovers with no duplicates. | 🔲 | |

---

## Phase 22 — Lemon Squeezy Billing

**Prerequisites:** Lemon Squeezy is enabled in staging with test-store
credentials (`LEMONSQUEEZY_API_KEY` / `_STORE_ID` / `_VARIANT_ID` set,
`LEMONSQUEEZY_TEST_MODE=true`), and the webhook endpoint is
`{BACKEND_URL}/billing/webhook` subscribed to `order_created` / `order_refunded`.
If billing is intentionally disabled for the environment, run P22-8 and mark
P22-1 through P22-7 as not applicable with release-owner approval.

| # | Test | Result | Notes |
|---|------|--------|-------|
| P22-1 | Open `/billing` → package price, credit amount, current balance, and purchase history load (no Stripe copy is visible). | 🔲 | |
| P22-2 | Click buy credits → browser redirects to the Lemon Squeezy hosted checkout for the configured variant. | 🔲 | |
| P22-3 | Complete test checkout → return to `/billing?checkout_ref=...`; `GET /billing/status?checkout_ref=...` polling grants credits once. | 🔲 | |
| P22-4 | Purchase history shows the completed pack, credit amount, and expiry date. | 🔲 | |
| P22-5 | Replay the same Lemon event → the durable inbox dedupes on the event id; credits are not granted twice. | 🔲 | |
| P22-6 | Send a webhook with an invalid `X-Signature` → API returns 400 and no credits are granted. | 🔲 | |
| P22-7 | Trigger an `order_refunded` (or test dispute) → the pack is revoked, balance drops, and any over-spend becomes recoverable billing debt (shown as a calm slate note, never summed into the usable balance). | 🔲 | |
| P22-8 | With Lemon intentionally disabled, buy credits shows a safe disabled state and `POST /billing/checkout` returns 503 (no checkout is created). | 🔲 | |

---

## Phase 19 — Prompt Pipeline Quality Gate

| # | Test | Result | Notes |
|---|------|--------|-------|
| P19-1 | `ASDD_PROMPT_VERSION` in `backend/prompts/base.py` is at or above the release target and was bumped for any prompt change. | 🔲 | |
| P19-2 | `harness/prompt_eval` passes against the selected baseline and `prompt_eval_report.md` has no unapproved per-grader regression. | 🔲 | |
| P19-3 | Generate PLAN and confirm required architecture/security/reliability sections are present, including ADRs, capacity, STRIDE, SLOs, and FMEA where applicable. | 🔲 | |
| P19-4 | Generate HARNESS and TASKS; mandatory section validation passes before critic repair. | 🔲 | |
| P19-5 | `/metrics` shows no new `pipeline_validator_failures_total` increase during the smoke run. | 🔲 | |
| P19-6 | Any `pipeline_upstream_section_skipped_total` or `specforge_billing_credits_critic_regen_total` increase is understood and accepted by release owner. | 🔲 | |

---

## Credit System Edge Cases

| # | Test | Result | Notes |
|---|------|--------|-------|
| 33 | Credit balance reaches 0 → credit exhaustion state shown (banner + waitlist link) | 🔲 | |
| 34 | Attempt to generate with 0 credits → blocked with an error, no generation starts | 🔲 | |
| 35 | Credit banner turns red when balance ≤ 5 | 🔲 | |

---

## Rate Limiting

| # | Test | Result | Notes |
|---|------|--------|-------|
| 36 | Trigger >10 LLM calls within 1 minute → rate limit error returned (429), `retry_after` shown | 🔲 | |

---

## Stale State Warning

| # | Test | Result | Notes |
|---|------|--------|-------|
| 37 | Navigate to stale PLAN stage → yellow staleness banner shown with "Regenerate" and "Keep as-is" options | 🔲 | |
| 38 | Click "Keep as-is" on staleness warning → warning dismissed, stage stays unchanged | 🔲 | |
| 39 | Click "Regenerate" on staleness warning → credit confirmation → generation starts | 🔲 | |

---

## Infrastructure

| # | Test | Result | Notes |
|---|------|--------|-------|
| 40 | `GET /health` returns `{"status": "ok"}` with HTTP 200 | 🔲 | |
| 41 | `GET /metrics` returns Prometheus metrics text with HTTP 200 | 🔲 | |
| 42 | Frontend loads without console errors on initial page visit | 🔲 | |
| 43 | Auth redirect loop does not occur after login (no infinite refresh cycle) | 🔲 | |

---

## Sign-out

| # | Test | Result | Notes |
|---|------|--------|-------|
| 44 | Sign out → session cleared, redirect to Landing page | 🔲 | |
| 45 | Accessing `/dashboard` after sign-out redirects to `/` | 🔲 | |

---

## Langfuse Integration (optional)

With Langfuse configured (`docker compose --profile langfuse up` and the
required `LANGFUSE_*` env vars set in `backend/.env`):

```env
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_SECRET_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_PROMPT_CACHE_TTL=300
LANGFUSE_CONTENT_CAPTURE_ACK=true
```

`LANGFUSE_CONTENT_CAPTURE_ACK=true` is required for production enablement when
`LANGFUSE_SECRET_KEY` is set. It acknowledges prompt/output telemetry export
after secret-shaped redaction.

- [ ] Sign in and create a workspace.
- [ ] Generate a SPEC stage. Confirm streaming works normally.
- [ ] Open Langfuse UI at `http://localhost:3000`.
- [ ] Confirm a trace appears with the `workspace_id` and `user_id` metadata.
- [ ] Confirm one generation is recorded inside the trace with provider,
      model, full system prompt, full user prompt, and accumulated output.
- [ ] Wait for the eval to complete. Confirm the overall score is attached
      to the same generation in the Langfuse UI.
- [ ] Trigger a generation that scores `>=85` or `<60`. Confirm a dataset item
      appears in the corresponding Langfuse dataset.

With Langfuse unconfigured (`LANGFUSE_SECRET_KEY` blank):

- [ ] Sign in, create a workspace, generate a SPEC stage.
- [ ] Confirm the application behaves identically: same streaming, same eval
      scoring, same credit accounting, and no user-visible dependency on
      Langfuse availability.
- [ ] Confirm zero requests to any Langfuse host appear in `tcpdump` or proxy
      logs during the generation.

---

## Results Summary

| Category | Total | Pass | Fail | Notes |
|----------|-------|------|------|-------|
| Authentication | 4 | | | |
| Workspace Creation | 4 | | | |
| SPEC Generation | 4 | | | |
| SPEC Refine | 5 | | | |
| SPEC Finalise | 3 | | | |
| PLAN / Review Gate | 6 | | | |
| HARNESS + TASKS | 4 | | | |
| Export | 2 | | | |
| Phase 13 — GitHub | 15 | | | |
| Phase 21 — GitHub Living (App enabled) | 17 | | | |
| Phase 22 — Billing (Lemon Squeezy) | 8 | | | |
| Phase 19 — Prompt Quality | 6 | | | |
| Credits Edge Cases | 3 | | | |
| Rate Limiting | 1 | | | |
| Stale State | 3 | | | |
| Infrastructure | 4 | | | |
| Sign-out | 2 | | | |
| **Total** | **91** | | | |

Optional/additional checks:

| Category | Total | Pass | Fail | Notes |
|----------|-------|------|------|-------|
| Langfuse configured mode | 7 | | | |
| Langfuse disabled mode | 3 | | | |

**Sign-off:** ________________  **Date:** ________________

> All items must pass before production deploy. Any ❌ must be filed as a bug and resolved first.

## V1.3 Usefulness Improvements

Phase 14 added six end-to-end flows. Walk all of them on a fresh smoke
account before each release. Each row should land at ✅ or be filed as
a bug.

### Spec Clarification

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| 1 | Create a fresh workspace; click Generate on the spec stage. | Clarification modal opens with 3–5 short-answer fields. A 204 from the judge silently bypasses the modal. | |
| 2 | Click **Skip**. | Generation begins immediately; no clarification persisted. | |
| 3 | Create another workspace; fill answers; click **Use answers**. | Generation begins; regenerated spec references the answered context. | |

### Task Priority + Estimate

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| 4 | Complete the pipeline to TASKS. | Every task carries `**Priority:**` and `**Estimate:**` lines. | |
| 5 | View the workspace header. | Effort-summary chip shows `~Xw · N tasks · M MUST`. | |

### PDF Export

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| 6 | Click **📄 PDF** on a finalised workspace. | Download starts within 2 seconds. | |
| 7 | Open the PDF. | Cover page, ToC, three sections (SPEC/PLAN/TASKS), syntax-highlighted code, page footer. | |
| 8 | Inspect the PDF contents. | The harness directory is NOT included. | |
| 9 | (Defence-in-depth) Inject an `<img src="https://evil/exfil">` into spec content via the workspace and re-export. | No outbound HTTP fired during render (check egress logs); PDF still renders. | |

### Public Share

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| 10 | Click **🔗 Share**. Toggle **Public**. Click **Copy**. | Copy button briefly transitions to "Copied ✓"; the clipboard holds the URL. | |
| 11 | Open the URL in an incognito window. | The spec renders without a login prompt; stage tabs work. | |
| 12 | View source on the public page. | `<meta name="robots" content="noindex, nofollow">` is present. | |
| 13 | `curl -i $URL` and check headers. | `X-Robots-Tag: noindex, nofollow` and ETag are present. | |
| 14 | Toggle **Disabled**; reload the incognito tab. | 404 page renders. | |
| 15 | Rotate (behind the "More" disclosure); paste the OLD URL. | 404 page; the new URL works. | |

### Starter Templates

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| 16 | Sign in as a brand-new user with zero workspaces. | Dashboard prominently shows the templates strip with a header. | |
| 17 | Scroll the strip on a 1280px viewport. | ~3.5 cards visible; a half-card on the right invites further scroll. | |
| 18 | Click a card. | Create-workspace modal opens; name + problem statement + provider are pre-filled; lotus chip reads "Started from … · clear". | |
| 19 | Click **clear** on the chip. | Fields reset; chip disappears. | |
| 20 | Submit a template-prefilled workspace. | Workspace is created. `SELECT template_slug FROM workspaces WHERE id = '…'` returns the chosen slug. | |
| 21 | Re-deploy the API container. | `SELECT COUNT(*) FROM templates` returns the same count as before. The seed is idempotent. | |

### Harness Coverage Chip

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| 22 | Open the **Harness** stage of a workspace whose harness eval shows 100% coverage. | Green "✓ Full coverage" badge visible in the pane header. | |
| 23 | Hover the badge. | Tooltip reads "N tests cover all N spec requirements." | |
| 24 | Switch to the **Plan** and **Tasks** stages of the same workspace. | Coverage badge is absent — it only appears on the Harness stage. | |
| 25 | Open the dashboard. | The "✓ Full coverage" badge is visible on the workspace card when harness coverage is 100%. | |
| 26 | Open the public share view. | The "✓ Full coverage" badge is visible under the cover band when applicable. | |
| 27 | Find a workspace whose harness eval is below 100% (or has no eval yet). | The badge is absent — no count, no bar, no placeholder. | |

**V1.3 Sign-off:** ________________  **Date:** ________________

---

## Storyboard Smoke

| Step | What to do | Expected | Result |
| ---- | ---------- | -------- | ------ |
| S1 | Create or open a staging workspace and finalise SPEC, PLAN, HARNESS, and TASKS. | Create Storyboard is enabled only after all four source stages are finalised. | |
| S2 | Click Generate Storyboard and confirm the paid modal. | Generation starts, exactly 25 credits are reserved once, and duplicate clicks do not create another debit. | |
| S3 | Open the generated `/storyboards/<id>` owner page. | Deck renders exactly six main acts: Opening Thesis, Product Vision, Product Walkthrough, Technical Architecture, Trust/Security/Reliability, and Launch Close. | |
| S4 | Inspect act tabs and slide titles. | There is no top-level Validation act and no top-level Execution Plan act. | |
| S5 | Present deck from the owner page. | Presenter mode opens; speaker notes are visible to the owner. | |
| S6 | Open the architecture reveal. | Layered client/frontend/API/data/LLM/integrations/trust/recovery architecture appears and is sourced. | |
| S7 | Download HTML, PDF, speaker notes, demo script, and appendix from owner view. | Each download returns an attachment with the expected file type; PDF opens locally. | |
| S8 | Enable public sharing with default permissions and copy the `/sb/<slug>` link. | Public sharing creates a Storyboard `/sb/` URL, not a workspace `/p/` URL. | |
| S9 | Open `/sb/<slug>` in an incognito/private window. | Public deck loads without sign-in, has no account/credit UI, and has noindex posture. | |
| S10 | With default public permissions, inspect deck, source layer, presenter/notes UI, appendix, and public downloads. | Speaker notes, technical appendix, and source excerpts are hidden; public HTML download is not available. | |
| S11 | Enable source layer, notes, and appendix, then reload the incognito page. | Bounded source excerpts, speaker notes, and appendix become available only after their owner permissions are enabled. | |
| S12 | Re-finalise PLAN in the same workspace. | Existing ready Storyboard is marked stale but remains presentable; owner is prompted to regenerate. | |
| S13 | In staging with a fake provider failure, trigger full regeneration or section regeneration. | Failed replacement refunds exactly once, and the previous ready/stale Storyboard remains presentable and unmodified. | |
| S14 | Disable then rotate the public slug. | Old incognito link returns not-found; the new link works only after sharing is enabled. | |

Storyboard sign-off: ________________  Date: ________________
