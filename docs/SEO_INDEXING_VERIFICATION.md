# SEO Indexing Verification Log

Companion evidence log for [`docs/SEO_INDEXING_REMEDIATION_PLAN.md`](SEO_INDEXING_REMEDIATION_PLAN.md).
Every probe run against production is recorded here, before and after, so the
outage and its fix are provable rather than asserted.

---

## Phase 1 — Canonical host decision

**Decided:** 2026-07-25, by the user (human), per plan §4 (hard gate — not assumed).

**Decision: apex, `https://thought2build.com`.** `www.thought2build.com` will
308-redirect to it. This reverses today's live Vercel redirect direction
(currently apex → `www`; T-3.3 flips it to `www` → apex).

**Rationale:** repo evidence showed the codebase and docs already assume the
apex almost everywhere — the only thing actually pointing the other way is
Vercel's own domain config. Choosing apex is a single-surface change; choosing
`www` would have required updating four independent systems (Railway env,
Google Cloud Console, and two source files), any one of which left stale
breaks login.

### Blast-radius table (plan §4)

| Surface | Where | Status with apex chosen |
| --- | --- | --- |
| `FRONTEND_URL` | `backend/config.py:13`, Railway env (prod) | ✅ Already correct — [`docs/GO_LIVE_RUNBOOK.md`](GO_LIVE_RUNBOOK.md) instructs `FRONTEND_URL=https://thought2build.com` (apex, no `www`). The agent has no Railway credentials, so the *live* env value isn't directly verifiable — confirm it matches during T-3.6. |
| `ALLOWED_HOSTS` | `backend/config.py:83`, Railway env (prod) | ✅ Not affected — scoped to the backend API's own host (`api.thought2build.com,*.up.railway.app` per the runbook), independent of the frontend apex/`www` choice. |
| Google OAuth redirect URIs | Google Cloud Console | ✅ Already correct — the runbook instructs authorized origin `https://thought2build.com` and redirect URI `https://thought2build.com/auth/callback` (apex). Not directly verifiable without Console access — confirm during T-3.6. |
| Auth cookie domain / `__Host-` prefix | `backend/routers/auth.py` (refresh + OAuth-state cookies) | ✅ Not affected — the `__Host-` prefix forbids a `Domain` attribute entirely; these cookies are issued host-less by the backend/API host, not the frontend apex/`www` choice. |
| `LEMONSQUEEZY_SUCCESS_URL` | Vercel/Railway env (human-owned) | ⚠️ Needs human confirmation regardless of which host was chosen — `config.py`'s own comment example uses a third subdomain (`app.thought2build.com`), not apex or `www`; the live value isn't visible without credentials. Action item for T-3.6. |
| GitHub App callback URL | GitHub App settings → `/integrations/github/setup` | ✅ Not affected — points at the backend API host, independent of the frontend apex/`www` choice. |
| `PUBLIC_SITE_URL`, `PUBLIC_API_URL` | Vercel marketing project env | 🆕 New config, not yet set — the marketing Vercel project has no domain attached yet. Set to `https://thought2build.com` (apex) in T-3.2. |

### Additional repo-level references found (beyond the plan's table)

| Reference | Status with apex chosen |
| --- | --- |
| `frontend/src/pages/PublicWorkspaceView.tsx:76,109` — hardcoded `https://thought2build.com` links | ✅ Already correct, no change needed |
| `apps/marketing/public/robots.txt:19` — hardcoded `Sitemap: https://thought2build.com/...` | ✅ Origin already correct (this file itself is still replaced by T-2.3's dynamic template, for the unrelated reason that a hardcoded literal drifts) |

**Net effect:** every "needs change" row is a decision-independent human action
item (confirm `LEMONSQUEEZY_SUCCESS_URL`, set the new marketing env vars) —
none is a rename forced by picking apex over `www`. Phase 2 (repo hardening)
and Phase 3 (Vercel cutover) can now proceed against a fixed target.

---

## Phase 2 — Repo hardening

**Landed:** 2026-07-25, agent-only (no production surface touched — safe to
land ahead of the Phase 3 cutover per plan §5).

| Task | Change | Verified |
| --- | --- | --- |
| T-2.1 | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) `deploy` job: new "Assert marketing deploy is configured" preflight step hard-fails (`::error::` + `exit 1`) when `VERCEL_MARKETING_PROJECT_ID` is unset, unless the repo variable `MARKETING_DEPLOY_OPTIONAL=true` is explicitly set. Previously the deploy step's own `if:` silently skipped — CI stayed green while the marketing zone never shipped. | Read-through of the new step logic; the pre-existing `if:` on the deploy step itself is now unreachable-without-a-visible-opt-out, not a silent skip. |
| T-2.2 | [`astro.config.mjs`](../apps/marketing/astro.config.mjs) and [`src/consts.ts`](../apps/marketing/src/consts.ts) (independent guards — see T-2.2's own code comment for why both are needed): throw when `VERCEL_ENV=production` and `PUBLIC_SITE_URL` is unset or matches `localhost`/`127.0.0.1`. Dev/CI builds keep the localhost fallback. | Live-ran all three cases locally: `VERCEL_ENV=production pnpm build` (unset) → throws; `VERCEL_ENV=production PUBLIC_SITE_URL=http://localhost:4321 pnpm build` → throws; `VERCEL_ENV=production PUBLIC_SITE_URL=https://thought2build.com pnpm build` → succeeds. Plain `pnpm build` (no `VERCEL_ENV`) unaffected. |
| T-2.3 | Deleted the static [`public/robots.txt`](../apps/marketing/public/robots.txt) (hardcoded `Sitemap: https://thought2build.com/...`, defect 4); added [`src/pages/robots.txt.ts`](../apps/marketing/src/pages/robots.txt.ts), an Astro endpoint that derives the `Sitemap:` line from `absoluteUrl()` — the same origin source of truth as every canonical/OG tag — so it can never drift from a future host change again. Explanatory comments preserved from the original file. | `pnpm build` → `dist/robots.txt` present with the derived origin; `robots.test.ts` updated to assert on the built dist **and** the live endpoint's `Response` body (not raw-parsing TS source). |
| T-2.4 | New [`tests/origin.test.ts`](../apps/marketing/tests/origin.test.ts): runs its own isolated `astro build` (own `--outDir` under the OS tmp dir, so it never races the shared suite's dist) with an explicit production origin fed **with** a trailing slash (`https://thought2build.com/`), then asserts every `sitemap-0.xml` `<loc>`, the `robots.txt` `Sitemap:` line, and every indexable page's canonical/`og:url`/`og:image` (a) start with the normalized origin (no trailing slash, no doubled `//`) and (b) never contain `localhost`. | 4 new tests, all passing. Regression-proven, not just written: temporarily hardcoded a wrong `Sitemap:` host back into `robots.txt.ts` and reran — `origin.test.ts` failed exactly as expected (`expected false to be true` on the origin-match assertion); reverted, full suite green again. |
| T-2.5 | **Deliberately not applied.** Plan §5 T-2.5 (lock `frontend/public/robots.txt` to `Disallow: /`) is explicitly gated to run only *after* Phase 3 is verified — applying it now would deepen the current outage, since the SPA build is still what's live at the apex. |
| T-2.6 | **Not resolvable without Vercel credentials the agent doesn't have.** Deferred to T-3.1 (inspect the marketing project's last production build log for whether `PUBLIC_SITE_URL` was set) and T-4.1 (`grep -c localhost` on the live sitemap settles it definitively either way). |

### Exit check

```
cd apps/marketing && pnpm check && pnpm build && pnpm test   # 0 errors; 7 pages built; 161/161 tests pass (157 pre-existing + 4 new)
cd frontend && pnpm tsc                                       # clean (frontend untouched this phase; sanity-checked only)
```

`noindex-regression.test.ts` (guards the `/p/` `/sb/` noindex stack) and
`robots.test.ts` were both updated to read the new templated endpoint/built
dist instead of the deleted static file — neither test's *assertions*
changed, only what they read.

**Net effect:** the marketing deploy can no longer silently fail to ship: an
unconfigured secret now hard-fails CI, a production build with a bad origin
now hard-fails the build, and the `Sitemap:` line can no longer drift from a
hardcoded literal. Phase 3 (Vercel cutover) can now proceed knowing the repo
side will fail loudly rather than silently regressing again.

---

## Phase 3 — Vercel cutover

**Landed:** 2026-07-25/26. Ends the outage: `thought2build.com` now serves the
marketing zone's static Astro build instead of the SPA shell.

### Pre-flight fixes found before touching any domain

Two real bugs were found and fixed before T-3.3, both via live verification
rather than trusting existing docs/config:

1. **CI ordering (`.github/workflows/ci.yml`):** the T-2.1 "assert marketing
   deploy configured" preflight ran *before* "Deploy frontend to Vercel" — a
   hard-fail there aborted the whole step sequence and would have taken the
   unrelated frontend/SPA deploy down with it. Confirmed live-broken on `main`
   (run `30168097349`). Fixed by moving the assert to run only before the
   marketing-only deploy step.
2. **`apps/marketing/vercel.json` rewrote every app/artifact path
   (`/dashboard`, `/workspace`, `/settings`, `/billing`, `/auth`, `/p/`,
   `/sb/`, `/assets`) to `thought2build-app.vercel.app`, which does not exist**
   (`curl` → 404). The SPA's real default domain is `thought2build.vercel.app`
   (confirmed live, 200). Undetected, this would have 404'd the entire
   logged-in app and every public share link on the first cutover. Fixed and
   verified end-to-end (rewritten HTML, proxied JS bundle, `/p/*`) against the
   marketing project's own preview URL before moving any domain.

A separate, unrelated CI failure (`test_automatic_backfill_coalesces_requests_by_time_window`,
a timing-bucket race in an existing GitHub-sync test) was hit and cleared by
re-running the job — confirmed pre-existing and untouched by this diff.

### T-3.1 / T-3.2 — Marketing Vercel project

Created `thought2build-marketing` (team `rsqr`), Root Directory
`apps/marketing`, framework Astro (auto-detected), Node 22. Production env
vars: `PUBLIC_SITE_URL=https://thought2build.com`,
`PUBLIC_API_URL=https://api.thought2build.com` (confirmed live via
`api.thought2build.com/health` before use). Sanity vars left unset — matches
Phase 2's credential-free degrade path; Sanity content is Phase 6.

### T-3.5 — CI secret

`VERCEL_MARKETING_PROJECT_ID` added as a GitHub secret from the new project's
ID. A stray `MARKETING_DEPLOY_OPTIONAL=true` repo variable (a troubleshooting
leftover, not set by this session) was found and removed afterward so T-2.1's
hard-fail guard is genuinely active again.

### T-3.3 — Domain move

Per the Phase 1 decision: removed `thought2build.com` + `www.thought2build.com`
from the `thought2build` (SPA) project (Vercel's own confirmation dialog
correctly identified both as one unit, since apex was redirecting to www) and
added them to `thought2build-marketing`: apex → Production, `www` → 308
redirect → apex. Deliberately unchecked Vercel's "Redirect apex domains to
www (recommended)" default, which would have silently recreated the reversed
(pre-fix) redirect direction.

### T-3.4 — First real deploy

Happened automatically via the CI `Deploy` job's `vercel --prod` step once
T-3.1/3.2/3.5 were in place (commits `4e2cd2f`, `02058ef`, `cd2591c`) — no
separate manual trigger needed.

### T-3.6 — Host-dependent config reconciliation

Checked live Railway values rather than trusting the Phase 1 table's
predictions:

| Variable | Predicted (Phase 1) | Actual live value found | Action |
| --- | --- | --- | --- |
| `FRONTEND_URL` | "Already correct" (apex) | `https://www.thought2build.com` (www — **contradicted the prediction**) | Updated to `https://thought2build.com` (apex). Verified safe first: the pre-cutover apex→www redirect preserved OAuth query params (`curl` test with `?code=&state=`), so the change was safe to make ahead of T-3.3. Deployed via Railway (bundled with the user's own already-staged, unrelated "Wait for CI" setting change for backend/worker/worker-fast, which matches `CLAUDE.md`'s documented intended config). |
| `ALLOWED_HOSTS` | "Not affected" | `*.up.railway.app,*.railway.internal,healthcheck.railway.app,api.thought2build.com` | Matches prediction — no change needed. |

Google OAuth Console and GitHub App callback settings were not touched
(outside agent credential access) — the blast-radius table already marked
GitHub App callback unaffected, and the live OAuth redirect now correctly
requests `redirect_uri=https://thought2build.com/auth/callback` (apex),
confirmed via `curl` against `api.thought2build.com/auth/google`.

---

## Phase 4 — Verification (post-cutover)

Captured 2026-07-26 against live production, immediately after T-3.3.

### T-4.1 HTTP-layer assertions — all pass

| Assertion | Result |
| --- | --- |
| Canonical host serves static HTML | `thought2build.com/` → 200, 17,637 bytes (was 1,113), real `<meta description>`/canonical/OG/JSON-LD |
| Non-canonical host redirects | `www.thought2build.com` → 308 → `thought2build.com`, 1 redirect, same final content |
| `robots.txt` is the marketing policy | `Allow: /`, `Disallow: /p/`, `Disallow: /sb/`, `Sitemap: https://thought2build.com/sitemap-index.xml` |
| `sitemap-index.xml` | 200 (was 404) |
| `sitemap-0.xml` | 200; 7 URLs, all on `https://thought2build.com`, zero `localhost` |
| Each hub is distinct static HTML | `/compare` 4945B, `/guides` 4894B, `/templates` 4957B, `/use-cases` 4897B, `/demos` 4858B — all distinct, none 1,113 |
| Artifact routes reachable | `/p/<slug>` → 200, `/sb/<slug>` → 200 |
| App routes still proxy | `/dashboard` → 200 |

**Finding (pre-existing, not introduced by this session): `X-Robots-Tag` is
absent on `/p/*` and `/sb/*`.** `frontend/public/_headers` (Netlify-style)
is never honored by Vercel — confirmed by testing `thought2build.vercel.app`
(the SPA's own domain) directly, with identical results, before any cutover
touched it. The only header source actually live is the single catch-all
block in `frontend/vercel.json`, which does not special-case `/p/*`/`/sb/*`.
Practical exposure is low: the JS-injected `<meta name="robots" content="noindex, nofollow">`
layer *is* present and confirmed working (checked via rendered DOM), and
`robots.txt` already blocks crawling of both prefixes, so a compliant crawler
never reaches the point of needing the HTTP header. Independent of noindex,
though, **the stricter `script-src 'none'` CSP that `_headers` intended for
`/p/*`** (hardening against injection in LLM-rendered public markdown, issue
T-193 per that file's own comment) **is also not live** — `/p/*` currently
gets the general SPA CSP (`script-src 'self'`) instead. This is a real gap,
independent of the outage this plan fixes, and is flagged to the user as a
separate follow-up rather than patched inline, since it touches frontend
security headers outside Phase 3's scope and deserves its own careful change.

### T-4.2 Rendered-DOM assertions — pass

Homepage: `title` non-empty, `description` non-empty, `canonical` =
`https://thought2build.com/` (absolute, correct host, no localhost), `robots`
= `index, follow`, `ogTitle` present, 1 JSON-LD block (`Organization` +
`SoftwareApplication` + `FAQPage`, correctly cross-linked via `@id`), 1 `h1`,
`textLength` = 3,991 (⋙ 500). Titles/descriptions differ across hubs (verified
distinct byte sizes above imply distinct content — the Phase 2 test suite
enforces the uniqueness contract at build time).

### T-4.3 No-JavaScript crawl check — pass

`/guides` returns real `<h1>` content and 4,894 bytes (⋙ 1,113) with zero
client-side rendering required; homepage carries `application/ld+json` in the
initial HTML payload, not injected post-hydration.

### T-4.4 Auth/billing regression check — pass (stopped before real login, per plan)

`api.thought2build.com/auth/google` → 307 → Google's consent screen with
`redirect_uri=https://thought2build.com/auth/callback` (apex, matches the
Phase 1 decision and the corrected `FRONTEND_URL`). Did not complete an actual
Google sign-in, per the plan's explicit instruction not to authenticate with
the user's credentials during this check.

### T-4.5 Structured-data validation — schema verified, not run through Google's tool

`Organization`, `SoftwareApplication`, and `FAQPage` JSON-LD all present and
well-formed on the homepage, cross-linked via `@id` anchors as designed. Did
not separately run Google's Rich Results Test (would require a Playwright
round-trip to an external tool); the schema shape matches `src/lib/seo.ts`'s
builders exactly.

**Net effect:** Part I (Phases 0–5) is now functionally complete except T-5
(index registration, which needs GSC/Bing account access) and the flagged
`/p/*` CSP follow-up above.

---

## Baseline (pre-fix)

**Captured:** 2026-07-25, against production (`thought2build.com` / `www.thought2build.com`).

### HTTP-layer probes (`curl`)

Command run (T-0.2):

```bash
for u in https://thought2build.com/ https://www.thought2build.com/ \
         https://www.thought2build.com/robots.txt \
         https://www.thought2build.com/sitemap-index.xml \
         https://www.thought2build.com/compare \
         https://www.thought2build.com/guides \
         https://www.thought2build.com/templates \
         https://www.thought2build.com/use-cases \
         https://www.thought2build.com/demos; do
  echo "=== $u ==="
  curl -sS -o /dev/null -w "status=%{http_code} size=%{size_download} redirects=%{num_redirects} final=%{url_effective}\n" -L --max-time 25 "$u"
done
```

Result:

| URL | Status | Size (bytes) | Redirects | Final URL |
| --- | --- | --- | --- | --- |
| `https://thought2build.com/` | 200 | 1113 | 1 | `https://www.thought2build.com/` (308 apex→www) |
| `https://www.thought2build.com/` | 200 | 1113 | 0 | same |
| `https://www.thought2build.com/robots.txt` | 200 | 509 | 0 | same |
| `https://www.thought2build.com/sitemap-index.xml` | **404** | 79 | 0 | same |
| `https://www.thought2build.com/compare` | 200 | 1113 | 0 | same |
| `https://www.thought2build.com/guides` | 200 | 1113 | 0 | same |
| `https://www.thought2build.com/templates` | 200 | 1113 | 0 | same |
| `https://www.thought2build.com/use-cases` | 200 | 1113 | 0 | same |
| `https://www.thought2build.com/demos` | 200 | 1113 | 0 | same |

Every route — the homepage and all five content hubs — returns the **identical
1113-byte SPA shell**. Confirms defect described in plan §1.1 exactly.

**Apex redirect headers** (`curl -sS -D - -o /dev/null https://thought2build.com/`):

```
HTTP/2 308
location: https://www.thought2build.com/
refresh: 0;url=https://www.thought2build.com/
server: Vercel
```

**`www` response headers** (`curl -sS -D - -o /dev/null https://www.thought2build.com/`):

```
HTTP/2 200
content-type: text/html; charset=utf-8
content-security-policy: default-src 'self'; base-uri 'self'; object-src 'none'; ...
x-vercel-cache: HIT
content-length: 1113
```

No `X-Robots-Tag` header present (neither an indexing block nor a signal either
way — the page is simply empty).

**`robots.txt` body served at the apex** (this is the SPA-zone copy, per plan
defect list — its own header comment says as much):

```
# NOTE: At the apex domain this file is shadowed by the marketing zone's
# robots.txt (apps/marketing/public/robots.txt is authoritative). This copy is
# kept consistent for direct hits on the SPA deployment URL.
User-agent: *
# T-USE-10 / issue #18: public shared specs (/p/) and storyboards (/sb/) are
# intentionally noindex. This Disallow is the primary document-level guard for
# compliant crawlers; the _headers X-Robots-Tag and JS-injected meta are the
# secondary layers.
Disallow: /p/
Disallow: /sb/
```

No `Sitemap:` directive at all — confirming the marketing zone's `robots.txt`
(with its `Sitemap:` line) is not what's live in production.

**`sitemap-index.xml` body:**

```
The page could not be found

NOT_FOUND
```

404, plain-text Vercel not-found page, not XML.

**Homepage raw HTML** (`curl -sS https://www.thought2build.com/`):

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap" rel="stylesheet" />
    <link rel="icon" type="image/png" href="/favicon.png" />
    <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
    <meta name="theme-color" content="#8f4e00" />
    <title>Thought2Build</title>
    <script type="module" crossorigin src="/assets/index-COq31ppI.js"></script>
    <link rel="modulepreload" crossorigin href="/assets/rolldown-runtime-QTnfLwEv.js">
    <link rel="modulepreload" crossorigin href="/assets/react-BMRwKF_T.js">
    <link rel="modulepreload" crossorigin href="/assets/vendor-BczrMNe5.js">
    <link rel="stylesheet" crossorigin href="/assets/index-CZtF-SC9.css">
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
```

No `<meta name="description">`, no `<link rel="canonical">`, no Open Graph
tags, no `application/ld+json`. This is the raw `frontend/` (Vite SPA) build
output — confirms the marketing zone (`apps/marketing/`) is not attached to
either host.

### Rendered-DOM probe (Playwright MCP, T-0.3)

Navigated to `https://www.thought2build.com/` with a browser profile that
already held a valid auth session for this account — the SPA's client-side
router redirected to `/dashboard` after hydration (expected SPA behavior, not
a bug). Noted for transparency: the captured `h1`/`textLength` below reflect
the authenticated dashboard view, not a logged-out landing view. This has no
bearing on the metadata fields, which are set once in the static `<head>` and
are identical across every client-side route (there is no per-route head
management in the SPA at all):

```js
{
  title: "Thought2Build",
  description: null,
  canonical: null,
  robots: null,
  ogTitle: null,
  jsonLd: 0,
  h1: ["Welcome back,Arvind."],
  textLength: 2091
}
```

Matches the plan's predicted baseline exactly: `description: null`,
`canonical: null`, `jsonLd: 0`.

Screenshot: [`docs/seo-baseline/baseline-homepage-2026-07-25.png`](seo-baseline/baseline-homepage-2026-07-25.png)
(shows the authenticated dashboard the client router landed on, per the note
above — not a logged-out marketing view, because production currently has no
separate marketing zone to land on).

### Baseline summary

| Fact | Status |
| --- | --- |
| Marketing zone attached to production domain | ❌ No — both hosts serve the `frontend/` SPA build |
| `robots.txt` is the marketing policy | ❌ No — SPA-zone copy, no `Sitemap:` line |
| `sitemap-index.xml` reachable | ❌ No — 404 |
| Content hubs (`/compare`, `/guides`, `/templates`, `/use-cases`, `/demos`) distinct from homepage | ❌ No — byte-identical 1113-byte shell |
| Homepage has description / canonical / OG / JSON-LD | ❌ No — none present |
| Apex → `www` redirect | ✅ Yes, 308 |

This confirms every claim in plan §1.1 against live production as of
2026-07-25. Part I (Phases 1–5) has not yet been executed — Phase 1 requires
an explicit host decision from the user before any further change lands.

---

## Phase 2 — T-2.5 closeout (deferred item, now unblocked)

**Landed:** 2026-07-26. Plan §5 T-2.5 was deliberately deferred at Phase-2
time ("apply only AFTER Phase 3 is verified") because at that point the SPA
build was still what was live at the apex — locking the SPA's `robots.txt`
would have deepened the outage. Phase 4 confirmed the cutover is live and
correct, so this is now safe to close.

[`frontend/public/robots.txt`](../frontend/public/robots.txt) changed from
`Disallow: /p/` + `Disallow: /sb/` to a blanket `Disallow: /`. Rationale: the
apex and `www` no longer serve this file at all — the marketing zone's own
`src/pages/robots.txt.ts` (T-2.3) answers `/robots.txt` on those hosts
directly, and `/robots.txt` is not one of the proxied paths in
`apps/marketing/vercel.json`. This file now only governs direct hits on the
SPA's raw deployment host (`thought2build.vercel.app`), which has no reason
to be crawled or indexed at all — a blanket disallow is simpler and stricter
than continuing to special-case `/p/`/`/sb/` on a host nothing should reach
via search in the first place. No test asserts on this file's content
(`StoryboardPublic.test.tsx`'s `robots` reference is the unrelated
JS-injected `<meta name="robots">` tag), so there is no coupling to update.

**AC verification:** deferred to the next live check of
`thought2build.vercel.app/robots.txt` (plan §5 T-2.5's own AC) — not
re-probed in this session since it requires a fresh Vercel deploy of the
`frontend` project to pick up the change.

---

## Phase 5 — Index registration (in progress)

**Started:** 2026-07-26. Per plan §8 ownership table this phase is
agent-driven-via-Playwright but human-gated on DNS/account access — both
gates were hit immediately, which is the expected shape of this phase, not a
blocker in the code sense.

### T-5.1 Google Search Console — domain property created, verification pending on the user

Using the already-authenticated Google session (`arvindsathyan@gmail.com`)
in the Playwright browser profile, confirmed via `search.google.com/search-console`
redirecting to the welcome screen that **no property existed yet** on this
account. Started a **Domain property** for `thought2build.com` (not URL-prefix
— per plan §8 T-5.1.1, a domain property covers apex/`www`/http/https in one
verification instead of four). Google issued a DNS TXT verification record
and the property is now saved in a pending/unverified state (confirmed by
reopening it via "Already started? Finish verification").

**Action required (human — DNS registrar access, per plan §2 credential
boundary):**

| Field | Value |
| --- | --- |
| Record type | `TXT` |
| Host/name | `@` (root of `thought2build.com` — exact field name depends on registrar) |
| Value | `google-site-verification=XPfo13CWlMu1j-lYn7sHesf3zMe1i-h-kptWTyCqXy4` |

After adding the record (allow up to ~24h for DNS propagation per Google's
own note in the dialog), either the agent can click "Verify" on a future run,
or the user can do it directly at
`search.google.com/search-console/welcome` → "Already started? Finish
verification" → `thought2build.com` → Verify.

**Not yet done, blocked on verification above:** submitting
`https://thought2build.com/sitemap-index.xml` (T-5.1.2), URL Inspection on
the homepage (T-5.1.3), Request Indexing on homepage + 5 hubs (T-5.1.4), and
the Crawl Stats check for pre-cutover crawl failures (T-5.1.5). Google's own
UI gates all of these behind a verified property — there is no way to submit
a sitemap to an unverified domain property. Revisit immediately once DNS is
live.

### T-5.2 Bing Webmaster Tools — blocked, no authenticated session

`bing.com/webmasters/home` redirected to the logged-out marketing page — no
Microsoft/Bing account is signed in in this browser profile (unlike Google,
where an existing session was already present). Per plan §2's credential
boundary, the agent does not have and must not request Microsoft credentials.

**Action required (human):** sign in to Bing Webmaster Tools with whichever
Microsoft account should own this property, then either import the property
directly from Search Console (available once T-5.1 is verified — it pulls
verification status from GSC, avoiding a second DNS record) or verify
`thought2build.com` independently. Once a session exists, the agent can
resume driving it via Playwright per plan §2.

### T-5.3 IndexNow — implemented

**Landed:** 2026-07-26. Credential-free per plan §8, so unlike T-5.1/T-5.2 this
required no human gate and was implemented in full:

- [`apps/marketing/public/ef7228a2eede034338007049a8149ac2.txt`](../apps/marketing/public/ef7228a2eede034338007049a8149ac2.txt) —
  the IndexNow key, published as a plain-text file at the site root (IndexNow's
  own ownership proof; not a secret — the protocol requires it to be public).
- [`apps/marketing/scripts/submit-indexnow.mjs`](../apps/marketing/scripts/submit-indexnow.mjs) —
  fetches `sitemap-index.xml`, follows the `<sitemapindex>` → `<urlset>` chain
  (so it stays correct once content growth splits the sitemap, plan §9 T-6.4),
  and POSTs the flattened URL list to `https://api.indexnow.org/indexnow` in a
  single call. Retries transient failures (3 attempts, 3s backoff — covers a
  brief post-deploy CDN-propagation gap) and is deliberately best-effort: it
  always exits 0 and reports failures as a `::warning::` annotation, never a
  job failure, since an indexing nicety must not be able to fail a deploy that
  otherwise shipped correctly.
- Wired into `.github/workflows/ci.yml`'s `deploy` job as "Notify IndexNow of
  updated marketing URLs", immediately after "Deploy marketing to Vercel",
  gated on the same condition (marketing changed + the Vercel project id is
  set) with no `always()` — if the deploy step itself fails, this step is
  correctly skipped too (submitting URLs for a deploy that didn't ship would
  be actively wrong).
- New pure-unit tests in [`apps/marketing/tests/indexnow.test.ts`](../apps/marketing/tests/indexnow.test.ts)
  (9 tests, network-free — fixtures shaped like real Astro sitemap output)
  cover the sitemap-index-flattening logic, including both unreachable-index
  and unreachable-child-sitemap failure paths.

**Live-verified end to end** (ran the script locally against real production,
not just the unit tests):

```
$ INDEXNOW_SITE_URL=https://thought2build.com INDEXNOW_KEY=ef7228a2ee...49ac2 \
  node apps/marketing/scripts/submit-indexnow.mjs
submit-indexnow: submitted 7 URL(s) to IndexNow (status 202).
```

`202` is IndexNow's expected response for a key that is not yet reachable at
its `keyLocation` — confirmed via `curl` that the key file 404s in production
right now (`ef7228a2eede034338007049a8149ac2.txt` isn't deployed until this
commit ships). IndexNow queues the submission and verifies the key
asynchronously; once this change deploys, the key file goes live and both the
already-queued submission and every future CI-triggered one verify cleanly.
No action needed from the user — this self-resolves on deploy.

### Fixed in this pass: a real test/code drift, not just new work

While re-verifying Phase 2's T-2.5 closeout, `apps/marketing/tests/noindex-regression.test.ts`
turned out to assert the **old** narrow `frontend/public/robots.txt` policy
(`Disallow: /p/` + `Disallow: /sb/` as literal lines) — the prior session's
claim that "no test asserts on this file's content" was wrong; this one does,
by design (it's the noindex regression guard). T-2.5's blanket `Disallow: /`
is a strict superset of the old policy (it already blocks `/p/` and `/sb/`
along with everything else), so the test was updated to assert the stronger,
now-correct guarantee directly (`User-agent: *` + `Disallow: /`) instead of
pattern-matching for path segments that no longer appear verbatim. Confirmed
this was a genuine gap, not a false alarm, by running the full suite before
touching it: `apps/marketing/tests/noindex-regression.test.ts` failed with
exactly this mismatch. All 173 marketing tests pass after the fix
(`pnpm check`, `pnpm build`, `pnpm test` all green).

**Net effect:** Phase 5 is now agent-complete on every surface that doesn't
require a credential the agent doesn't hold. What remains — GSC domain
verification and Bing sign-in — cannot be crossed without the user adding one
DNS TXT record and signing into a Microsoft account (plan §2 hard boundary).
Everything on the agent's side of that boundary (starting both properties,
extracting the exact values needed, and now IndexNow end to end) is done.

---

## Post-fix

See the "Phase 4 — Verification (post-cutover)" section above — Phase 3
shipped and Phase 4 ran against live production on 2026-07-26.

---

## Phase 10 — T-10.1 regression monitor

**Landed:** 2026-07-26. New scheduled workflow
[`.github/workflows/marketing-monitor.yml`](../.github/workflows/marketing-monitor.yml)
— runs every 30 minutes plus `workflow_dispatch`, no secrets/credentials
required (pure public `curl` against `thought2build.com`). Three checks, each
a direct regression guard against the exact failure modes this plan fixed:

| Check | Fails if |
| --- | --- |
| `sitemap-index.xml` → 200 | The marketing zone detaches from the apex again (was a 404 in the baseline) |
| Homepage body > 5,000 bytes and contains `rel="canonical"` | The apex reverts to serving the 1,113-byte SPA shell with no metadata |
| `www` → 308 | The apex/`www` redirect direction reverts or breaks |

Live-verified: ran all three checks by hand against production immediately
before adding the workflow (`sitemap-index.xml` → 200; homepage → 17,601
bytes with `rel="canonical"` present; `www` → `HTTP/2 308`) — the workflow
would pass on its first scheduled run. Deliberately a separate file from
`production-smoke.yml` (that workflow is manual-dispatch-only, authenticated,
and checks the backend API — a different surface and trigger model than an
unauthenticated, scheduled, public-HTML check).
