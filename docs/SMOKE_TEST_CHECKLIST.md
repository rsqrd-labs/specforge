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
| Credits Edge Cases | 3 | | | |
| Rate Limiting | 1 | | | |
| Stale State | 3 | | | |
| Infrastructure | 4 | | | |
| Sign-out | 2 | | | |
| **Total** | **45** | | | |

Optional/additional checks:

| Category | Total | Pass | Fail | Notes |
|----------|-------|------|------|-------|
| Langfuse configured mode | 7 | | | |
| Langfuse disabled mode | 3 | | | |

**Sign-off:** ________________  **Date:** ________________

> All items must pass before production deploy. Any ❌ must be filed as a bug and resolved first.
