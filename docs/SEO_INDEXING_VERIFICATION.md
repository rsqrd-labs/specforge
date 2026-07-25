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

## Post-fix

_Not yet run — populate after Phase 4 verification, once Phase 3's Vercel
cutover has shipped._
