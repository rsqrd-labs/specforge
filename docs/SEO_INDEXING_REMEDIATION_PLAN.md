# Search & Answer-Engine Acquisition Plan

**Status:** Not started
**Created:** 2026-07-25
**Goal:** Acquire users from Google **and** from LLM/answer-engine recommendations.
**Owner:** Claude Code (implementation) + human (credentials, content decisions, distribution)
**Tooling:** Claude Code + Playwright MCP + `curl`

---

## 0. Read this first

This plan has two halves that must not be confused.

**Phases 0–5 fix an outage.** The marketing zone was never attached to the
production domain, so `thought2build.com` has been serving an empty JavaScript
shell since go-live. Nothing is indexable. This is a hard blocker and nothing
else in the plan works until it is fixed.

**Phases 6–10 are the actual acquisition work.** Fixing the outage makes the
site *eligible* to be found. It does not make it found. A brand-new domain with
one real page and no third-party presence will not rank for competitive queries
and will not be recommended by any model, no matter how clean its metadata is.

Anyone reading only the first half will ship a technically perfect site that
nobody visits. Anyone reading only the second half will invest in content that
Google cannot crawl. Both halves are required.

### Honest timeline

| Milestone | Realistic timing after Phase 3 ships |
| --- | --- |
| Indexed; findable by brand name (`thought2build`) | 3 days – 3 weeks |
| Ranking for long-tail, low-competition queries | 2 – 4 months, **and only with Phase 6** |
| Ranking for category queries ("AI spec generator") | 6 – 12 months, with sustained content + links |
| Cited/recommended by LLMs | 3 – 9 months, driven almost entirely by **Phase 8**, not by on-site work |

Do not report a green Phase 4 to stakeholders as "we now rank". It means "we are
now crawlable".

---

## 1. Problem statement and evidence

### 1.1 The outage

Verified 2026-07-25 against production:

| Probe | Observed | Expected |
| --- | --- | --- |
| `GET https://thought2build.com/` | `308` → `https://www.thought2build.com/` | (decision — Phase 1) |
| `GET https://www.thought2build.com/` | 1113 bytes; `<div id="root"></div>`; `<title>Thought2Build</title>`; **no** description / canonical / OG / JSON-LD | Full static Astro HTML from [`index.astro`](../apps/marketing/src/pages/index.astro) |
| `GET /robots.txt` | The **SPA-zone copy** ([`frontend/public/robots.txt`](../frontend/public/robots.txt)) — the file whose own comment says it is "shadowed at the apex by the marketing zone" | [`apps/marketing/public/robots.txt`](../apps/marketing/public/robots.txt) |
| `GET /sitemap-index.xml` | **404** | `200`, XML index → `sitemap-0.xml` |
| `/compare` `/guides` `/templates` `/use-cases` `/demos` | All `200`, all **1113 bytes** — the identical SPA shell | Distinct static HTML per hub |

Every production URL returns an empty JS shell with no metadata. For Googlebot
there is nothing to index. For GEO/answer-engine crawlers — most of which do not
execute JavaScript at all — the site is a blank page.

### 1.2 The content gap

Measured from a local `pnpm build`:

| Page | Words |
| --- | --- |
| `/` | 989 |
| `/compare` | 106 |
| `/guides` | 108 |
| `/templates` | 110 |
| `/use-cases` | 105 |
| `/demos` | 100 |

The five hubs are **empty shells**. They are Sanity-driven — `guides/[slug].astro`,
`compare/[slug].astro`, `use-cases/[slug].astro`, `templates/[slug].astro`,
`demos/[slug].astro` all render from CMS documents. With nothing published, each hub
renders a header and a blurb listing zero items. CI builds credential-free, so the
"6 indexable routes" in the sitemap are **one real page plus five stubs**.

The infrastructure is excellent and the content is absent. That is the single most
important fact in this document.

### 1.3 Contributing defects

1. **`VERCEL_MARKETING_PROJECT_ID` gate fails open.**
   [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — `Deploy marketing to Vercel`
   is `if: ${{ env.VERCEL_MARKETING_PROJECT_ID != '' }}`. Unset ⇒ **skipped, not failed**.
   Every deploy reported success while shipping only the SPA.

2. **`PUBLIC_SITE_URL` silently falls back to localhost.**
   [`astro.config.mjs`](../apps/marketing/astro.config.mjs) and
   [`src/consts.ts`](../apps/marketing/src/consts.ts) both default to `http://localhost:4321`
   with no production guard. A local build demonstrates the failure mode: every `<loc>`
   in `dist/sitemap-0.xml` reads `http://localhost:4321/...`.
   *This is latent, not confirmed in production* — `dist/` is gitignored, so the local
   artifact says nothing about what Vercel built. Confirm in T-3.1; settle in T-4.1.

3. **The test suite cannot catch defect 2.** The Phase-6 vitest suite asserts via
   `absoluteUrl()`, which reads the same env var — localhost-vs-production is
   self-consistent and always green. Origin correctness is untested.

4. **Host mismatch.** The apex 308-redirects to `www`, but
   `apps/marketing/public/robots.txt` hardcodes `Sitemap: https://thought2build.com/...`
   (non-www). A hardcoded literal in a static file will drift again.

5. **`SAME_AS` is empty.** [`src/consts.ts`](../apps/marketing/src/consts.ts) carries a
   `TODO(launch)`. The schema.org `Organization` node emits no `sameAs`, so answer
   engines have no way to ground "Thought2Build" as an entity.

6. **No off-site presence.** The repo is private; there is no public GitHub artifact,
   no Product Hunt listing, no HN/Reddit discussion. This is the binding constraint on
   LLM recommendation and no amount of on-site work substitutes for it.

---

## 2. Execution rules for the implementing agent

- **Work phases in order.** Phase 3 ends the outage; Phase 2 ensures it cannot
  silently recur; Phases 6–8 are what actually produce users.
- **Two tool classes, two jobs:**
  - `curl` (Bash) is authoritative for **HTTP-level** facts — status codes, redirect
    chains, headers, `robots.txt`, `sitemap*.xml`, raw HTML bytes. A browser will
    happily render a page while hiding the 308 and the `X-Robots-Tag` that actually
    determine indexing.
  - **Playwright MCP** is for what `curl` cannot see — rendered DOM, whether metadata
    survives hydration, visual confirmation, and driving the Vercel / Search Console /
    Bing dashboards.
- **Credential boundary.** The agent has no Vercel, Google, or Sanity credentials.
  Every such task is either driven through Playwright MCP against a session the human
  has already logged into, or handed to the human explicitly. **Never** ask the user to
  paste a token, password, or OAuth code into the conversation.
- **Phase 3 mutates production DNS/domain routing.** Confirm with the user before each
  domain-level change. Do not batch them.
- **Never fabricate metrics.** Do not invent search volumes, difficulty scores, or
  traffic estimates. Where the plan calls for keyword data, it must come from a real
  tool or be marked as an assumption to validate.
- **Log every probe** to `docs/SEO_INDEXING_VERIFICATION.md` (created in Phase 0) so
  before/after is provable rather than asserted.
- **Do not `git push`** unless the user asks.

### Ownership at a glance

| Phase | Agent | Human |
| --- | --- | --- |
| 0 Baseline | ✅ all | — |
| 1 Host decision | proposes | ✅ decides |
| 2 Repo hardening | ✅ all | review |
| 3 Vercel cutover | drives via Playwright | ✅ authorizes, holds credentials |
| 4 Verification | ✅ all | — |
| 5 Index registration | drives via Playwright | ✅ DNS TXT, account access |
| 6 Content | ✅ drafts, ✅ publishes via Studio | ✅ approves, owns voice/claims |
| 7 Entity/GEO | ✅ all | ✅ supplies real profile URLs |
| 8 Off-site | drafts copy | ✅ posts, engages — **must be a real human** |
| 9 Conversion | ✅ all | review |
| 10 Measurement | ✅ all | ✅ reviews monthly |

---

# PART I — UNBLOCK (Phases 0–5)

## 3. Phase 0 — Baseline capture

**Goal:** freeze the broken state as evidence before touching anything.

### T-0.1 Create the verification log
Create `docs/SEO_INDEXING_VERIFICATION.md` with a `## Baseline (pre-fix)` section.

### T-0.2 Capture HTTP baseline

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

### T-0.3 Capture rendered-DOM baseline (Playwright MCP)

`browser_navigate` to `https://www.thought2build.com/`, then `browser_evaluate`:

```js
() => ({
  title: document.title,
  description: document.querySelector('meta[name="description"]')?.content ?? null,
  canonical: document.querySelector('link[rel="canonical"]')?.href ?? null,
  robots: document.querySelector('meta[name="robots"]')?.content ?? null,
  ogTitle: document.querySelector('meta[property="og:title"]')?.content ?? null,
  jsonLd: [...document.querySelectorAll('script[type="application/ld+json"]')].length,
  h1: [...document.querySelectorAll('h1')].map(h => h.textContent.trim()),
  textLength: document.body.innerText.trim().length,
})
```

Then `browser_take_screenshot`. Expected baseline (documenting the bug):
`description: null`, `canonical: null`, `jsonLd: 0`.

**Exit:** baseline section committed with all three captures.

---

## 4. Phase 1 — Canonical host decision ⚠️ GATE

**Blocks Phases 2 and 3. Ask the user; do not assume.**

Nothing is indexed, so there is no ranking equity to preserve — the choice is free,
but must be made once and applied everywhere.

**Recommendation: apex (`https://thought2build.com`), `www` 308-redirecting to it.**
Every in-repo comment, the `robots.txt` `Sitemap:` line, and the marketing zone's
documentation already assume the apex — smallest diff, fewest places left to drift.
Requires flipping the current Vercel redirect direction (today apex → www).

**Alternative: keep `www`.** No redirect change, but every in-repo apex reference
must be updated.

### Blast radius — this is not SEO-only

| Surface | Where | Risk if missed |
| --- | --- | --- |
| `FRONTEND_URL` | `backend/config.py:13` (HTTPS-validated in prod, `config.py:940`) | OAuth callback redirects to wrong host |
| `ALLOWED_HOSTS` | `backend/config.py:83` (required in prod, `config.py:942`) | Backend rejects requests with 400 Host error |
| Google OAuth redirect URIs | Google Cloud Console | Sign-in dies with `redirect_uri_mismatch` |
| Auth cookie domain / `__Host-` prefix | Refresh + OAuth-state cookies | Silent logout loop |
| `LEMONSQUEEZY_SUCCESS_URL` | Vercel/Railway env | Post-purchase redirect 404s |
| GitHub App callback URL | GitHub App settings → `/integrations/github/setup` | Install rejects, audits `github.install.rejected` |
| `PUBLIC_SITE_URL`, `PUBLIC_API_URL` | Vercel marketing project env | Wrong canonicals; broken sign-in CTA |

**Exit:** host chosen; every row marked "already correct" or "needs change"; decision
recorded at the top of the verification log.

---

## 5. Phase 2 — Repo hardening (agent-only)

Lands and is testable **before** the Phase 3 cutover.

### T-2.1 Make the marketing deploy fail loudly

**File:** [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

Add a preflight step to the `deploy` job that hard-fails when the secret is unset,
and drop the fail-open `if:` from the deploy step:

```yaml
- name: Assert marketing deploy is configured
  run: |
    if [ -z "${VERCEL_MARKETING_PROJECT_ID}" ]; then
      echo "::error::VERCEL_MARKETING_PROJECT_ID is unset — the marketing zone (apex, all SEO surfaces) would not deploy." >&2
      exit 1
    fi
```

Keep a documented escape hatch (`vars.MARKETING_DEPLOY_OPTIONAL == 'true'`) so a
deliberate opt-out is *visible*. The current behaviour is an invisible opt-out.

**AC:** a `deploy` run without the secret fails with a readable error naming the consequence.

### T-2.2 Fail production builds without `PUBLIC_SITE_URL`

**Files:** [`astro.config.mjs`](../apps/marketing/astro.config.mjs), [`src/consts.ts`](../apps/marketing/src/consts.ts)

Keep the localhost fallback for dev; throw when `VERCEL_ENV=production` and the var is
absent or localhost:

```js
const rawSite = process.env.PUBLIC_SITE_URL
if (process.env.VERCEL_ENV === "production" &&
    (!rawSite || /localhost|127\.0\.0\.1/.test(rawSite))) {
  throw new Error(
    `PUBLIC_SITE_URL must be an absolute production origin; got ${rawSite ?? "<unset>"}. ` +
    "Canonicals and the sitemap would ship localhost URLs.",
  )
}
const site = rawSite ?? "http://localhost:4321"
```

Mirror in `consts.ts` — it reads `import.meta.env.PUBLIC_SITE_URL` independently, so
both paths need the guard.

**AC:** `VERCEL_ENV=production pnpm build` without the var fails; plain `pnpm build` still works.

### T-2.3 Template `robots.txt` from the canonical origin

**Files:** delete `apps/marketing/public/robots.txt`; add `apps/marketing/src/pages/robots.txt.ts`

The hardcoded `Sitemap:` literal is defect 4's root cause. Derive it instead:

```ts
import type { APIRoute } from "astro"
import { absoluteUrl } from "../consts"

export const GET: APIRoute = () =>
  new Response(
    [
      "# Thought2Build — authoritative robots policy (marketing zone owns the apex).",
      "# /p/ (public shared specs) and /sb/ (public storyboards) are intentionally noindex.",
      "User-agent: *",
      "Allow: /",
      "Disallow: /p/",
      "Disallow: /sb/",
      "",
      `Sitemap: ${absoluteUrl("/sitemap-index.xml")}`,
      "",
    ].join("\n"),
    { headers: { "Content-Type": "text/plain; charset=utf-8" } },
  )
```

Preserve the existing explanatory comments. `robots.test.ts` asserts on both dist **and**
`readMarketing("public/robots.txt")` — update it to read the endpoint source.

**AC:** built `dist/robots.txt` carries the production origin; `pnpm test` green.

### T-2.4 Add origin-correctness tests

**File:** new `apps/marketing/tests/origin.test.ts`

Build with an explicit production `PUBLIC_SITE_URL` and assert:

- every `<loc>` in `dist/sitemap-0.xml` starts with that origin;
- no emitted HTML has `localhost` in `canonical`, `og:url`, or `og:image`;
- `robots.txt`'s `Sitemap:` origin **matches the canonical origin** (defect 4 exactly);
- the origin is `https://`, no trailing slash.

**AC:** fails against a localhost build, passes after T-2.2/T-2.3.

### T-2.5 Stop the SPA zone competing for the same queries

**File:** [`frontend/public/robots.txt`](../frontend/public/robots.txt)

⚠️ **Apply only AFTER Phase 3 is verified.** Until then this file *is* the apex policy
and disallowing everything would deepen the outage.

Post-cutover the SPA is reachable only at its `*.vercel.app` host (the apex proxies
`/dashboard`, `/workspace`, `/p/*`, `/sb/*` via
[`apps/marketing/vercel.json`](../apps/marketing/vercel.json) rewrites, which do not
expose the SPA's own `robots.txt`). Then set:

```
User-agent: *
Disallow: /
```

with a comment noting it applies only to the raw deployment host.

**AC:** `thought2build-app.vercel.app/robots.txt` → `Disallow: /`, while the canonical
host still serves the marketing policy.

### T-2.6 Confirm what production actually built

`dist/` is gitignored, so the local localhost artifact is not evidence about production.
In T-3.1 open the marketing project's last production build log and check whether
`PUBLIC_SITE_URL` was present; T-4.1's `grep -c localhost` settles it definitively.
Record the finding — if production had it set all along, T-2.2 is still worth landing
as a guard, but note it was not a contributing cause.

### Phase 2 exit
`cd apps/marketing && pnpm check && pnpm build && pnpm test` green;
`cd frontend && pnpm tsc && pnpm test` green; new tests demonstrably fail without the fixes.

---

## 6. Phase 3 — Vercel cutover ⚠️ PRODUCTION CHANGE

**This is the change that ends the outage.** Confirm before each mutation.

### T-3.1 Confirm the marketing Vercel project exists
Inspect the Vercel project list. If absent, create it — Root Directory `apps/marketing`,
framework Astro, build `pnpm build`, output `dist`, Node 22, pnpm 9.15.9 (match
[ci.yml](../.github/workflows/ci.yml)). If present, record its project ID and inspect
its most recent production deployment (stale? ever succeeded? was `PUBLIC_SITE_URL` set?).
Project IDs are not secrets; **do not** record tokens.

### T-3.2 Set marketing project env vars (Production scope)

| Variable | Value |
| --- | --- |
| `PUBLIC_SITE_URL` | Phase-1 canonical origin, no trailing slash |
| `PUBLIC_API_URL` | Railway backend origin (drives the sign-in CTA in `consts.ts`) |
| Sanity project/dataset/token | Required for the content hubs to render anything (Phase 6) |

CI builds credential-free (homepage + 5 hubs). A production build **with** Sanity
credentials emits additional routes — re-run the sitemap assertions after the first
real production build.

### T-3.3 Move the domains ⚠️ HIGHEST-RISK STEP

1. Remove `thought2build.com` and `www.thought2build.com` from the **SPA** project.
2. Add both to the **marketing** project.
3. Set the Phase-1 canonical as primary; the other as a **308 redirect** to it.
4. Confirm the SPA project keeps a stable deployment URL matching the rewrite targets in
   [`apps/marketing/vercel.json`](../apps/marketing/vercel.json)
   (`https://thought2build-app.vercel.app`). **If that hostname changes, the apex
   rewrites break and the entire logged-in app 404s** — update `vercel.json` in the
   same change.

Expect a brief window where the domain resolves to neither project. Do this alone.

### T-3.4 Trigger the first real marketing production deploy
Watch the build log for the T-2.2 guard — a failure here is the guard working.

### T-3.5 Add the CI secret
`VERCEL_MARKETING_PROJECT_ID` → GitHub repo secrets, so future `main` pushes deploy
the marketing zone automatically.

### T-3.6 Reconcile host-dependent config
Apply every "needs change" row from the Phase 1 table (Railway `FRONTEND_URL` /
`ALLOWED_HOSTS`, Google OAuth redirect URIs, GitHub App callback, `LEMONSQUEEZY_SUCCESS_URL`).
Restart affected Railway services.

**Exit:** Phase 4 passes end to end.

---

## 7. Phase 4 — Verification

Nothing is "done" until every assertion passes. Log under `## Post-fix`.

### T-4.1 HTTP-layer assertions (`curl`)

| Assertion | Expected |
| --- | --- |
| Canonical host serves static HTML | ≫ 1113 bytes; contains `<meta name="description"`, `<link rel="canonical"`, `application/ld+json` |
| Non-canonical host redirects | `308` → canonical |
| `robots.txt` is the marketing policy | `Allow: /`, `Disallow: /p/`, `Disallow: /sb/`, `Sitemap:` on the **canonical** origin |
| `sitemap-index.xml` | `200`, XML, references `sitemap-0.xml` |
| `sitemap-0.xml` | `200`; **zero** `localhost`; every `<loc>` on canonical origin |
| Each hub is distinct static HTML | `200`, **different** byte sizes, none equal to 1113 |
| Artifact routes reachable but noindex | `/p/<slug>` → `200` **and** `X-Robots-Tag: noindex` |
| App routes still proxy | `/dashboard` → `200` |

```bash
curl -sS -L https://<host>/sitemap-0.xml | grep -c localhost   # must be 0
```

### T-4.2 Rendered-DOM assertions (Playwright MCP)

For each of `/`, `/compare`, `/guides`, `/templates`, `/use-cases`, `/demos` — reuse the
T-0.3 snippet and assert:

- `title` non-empty and **unique across all six**
- `description` non-empty and **unique across all six**
- `canonical` absolute, canonical host, matches path, no `localhost`
- `robots` = `index, follow` (the [`Seo.astro`](../apps/marketing/src/components/Seo.astro) default)
- `ogTitle` present; `jsonLd >= 1`; exactly one `h1`; `textLength > 500`

Duplicate titles/descriptions are a real ranking problem — compare **across** pages,
not per page.

### T-4.3 No-JavaScript crawl check (GEO-critical)

Most answer-engine crawlers do not run JS. Confirm content is in the initial payload:

```bash
curl -sS -L https://<host>/guides | grep -c "<h1"                      # >= 1
curl -sS -L https://<host>/guides | wc -c                              # >> 1113
curl -sS -L https://<host>/ | grep -o 'application/ld+json' | wc -l    # >= 1
```

### T-4.4 Auth/billing regression check (Playwright MCP)
Navigate to the canonical host, click "Sign in with Google", confirm it reaches Google's
consent screen with **no** `redirect_uri_mismatch`. **Stop there** — do not authenticate
with the user's credentials. `browser_network_requests` → no CORS failures, no
`400 Invalid host header`.

### T-4.5 Structured-data validation
Run the homepage through Google's Rich Results Test via Playwright MCP; confirm the
`Organization` / `SoftwareApplication` nodes parse cleanly.

---

## 8. Phase 5 — Index registration

Only after Phase 4 is fully green. Submitting a broken site wastes crawl budget.

### T-5.1 Google Search Console
1. Verify a **Domain property** (DNS TXT) — covers apex, `www`, `http`, `https` in one,
   eliminating "verified the wrong variant" confusion. Human adds the registrar record.
2. Submit `https://<canonical>/sitemap-index.xml`; confirm **Success** with a
   discovered-URL count matching the sitemap.
3. **URL Inspection** on the homepage. Record the verdict verbatim — "URL is not on
   Google" plus a *successful live test* is the expected fresh-site state, and is very
   different from "Blocked by robots.txt" or "Crawled – currently not indexed".
4. **Request Indexing** for the homepage and five hubs. Rate-limited; do not loop.
5. **Settings → Crawl stats** — check for failures accumulated while the SPA shell was
   live. Google may have classified those URLs as thin content, which slows recovery.

### T-5.2 Bing Webmaster Tools
Same drill; supports importing the GSC property directly. Bing feeds several answer
engines, so it matters more for GEO than its search share suggests.

### T-5.3 IndexNow (optional)
Instant URL submission for Bing/Yandex. Worth wiring as a post-deploy step; skip if the
user prefers fewer moving parts.

---

# PART II — ACQUIRE (Phases 6–10)

> Everything above makes the site *eligible*. Everything below is what actually
> produces users. Phase 6 drives Google; Phase 8 drives LLM recommendation.

## 9. Phase 6 — Content: the ranking engine

**This is the highest-leverage work in the entire plan and it is pure content, not
engineering.** The architecture is already built; the CMS is empty.

### 9.1 What the schema already supports

[`apps/marketing/sanity/schemaTypes/`](../apps/marketing/sanity/schemaTypes/) defines five
document types — `seoPage`, `guide`, `templatePage`, `demoPage`, `redirect` — over
answer-engine-ready objects. `seoPage` alone carries:

| Field | Why it matters for GEO |
| --- | --- |
| `definition` | Direct extractable answer to "what is X" |
| `workflowSteps` | Feeds HowTo-style structured data |
| `comparison` | Feeds comparison tables models quote verbatim |
| `faqs` | Feeds `FAQPage` JSON-LD — the single most-cited format |
| `examples` | Concrete grounding |
| `body` (blockContent) | Long-form depth |

`guide` adds `heading`, `excerpt`, `author`, `publishedAt`, `body`, `faqs`.
[`src/lib/seo.ts`](../apps/marketing/src/lib/seo.ts) already ships JSON-LD builders for
Organization, SoftwareApplication, FAQPage, BreadcrumbList, and Article, with shared
`@id` anchors so entities resolve into one connected graph.

Whoever designed this understood GEO. It has simply never been fed.

### T-6.1 Keyword and question research ⚠️ NO FABRICATION

Produce `docs/SEO_CONTENT_MAP.md` with real data from a real tool (Search Console once
it has impressions, Ahrefs/Semrush, Google autocomplete, "People Also Ask", relevant
subreddit and HN threads). **Never invent volumes or difficulty scores.** Mark anything
unvalidated as an assumption.

Anchor on what the product genuinely is — a spec-to-build workspace producing SPEC →
PLAN → HARNESS → TASKS for handoff to coding agents. Candidate clusters to *validate*:

| Cluster | Intent | Format |
| --- | --- | --- |
| Spec-driven development with AI | Informational | `guide` |
| Handing off a spec to a coding agent (Claude Code, Cursor, Copilot) | Informational, high intent | `guide` |
| PRD / spec templates | Transactional | `templatePage` |
| "How do I turn an idea into tasks for an AI agent" | Question | `seoPage` with `faqs` |
| Thought2Build vs \<alternative\> | Commercial | `seoPage` with `comparison` |
| Worked examples: one idea → four artifacts | Proof | `demoPage` |

Prioritize **long-tail, question-shaped queries**. A new domain cannot win head terms,
but question-shaped content is also exactly what answer engines extract — the same work
serves Phase 8.

### T-6.2 Publish the first content wave

Target **12–15 documents** across the five hubs. Minimum bar per document:

- 1,200–2,000 words of genuinely useful content — not padding
- unique `title` and `description` (the Phase-4 uniqueness check enforces this)
- a filled `definition` where the type supports it
- **3–6 `faqs`** using real question phrasing → `FAQPage` JSON-LD
- at least one concrete `example`
- 3+ internal links to sibling content and one to the sign-up CTA
- a genuine comparison table on `compare/*` documents

**Quality bar — non-negotiable.** Thin AI-generated filler is actively harmful: it
triggers Google's spam classifiers, and models will not cite content that says nothing.
Every document must contain at least one thing a reader cannot get from a competitor —
a real worked example, a real artifact, a real opinion. The product's own output is the
best source: generate real SPEC/PLAN/HARNESS/TASKS artifacts and publish them as demos.

**Honesty bar.** Comparison pages must be accurate about competitors. Overstated claims
are a legal and reputational risk, and models increasingly cross-check them.

### T-6.3 Internal linking and hub depth

Rewrite the five hub `index.astro` pages so that with content published each hub is a
real landing page (300+ words of orientation, a curated list, cross-links), not a 105-word
stub. Ensure every document is reachable within two clicks of the homepage — the
`CONTENT_HUBS` array in [`consts.ts`](../apps/marketing/src/consts.ts) already single-sources
nav; use it.

### T-6.4 Re-verify after publishing
Re-run Phase 4 assertions. Word counts should now clear 1,000+ on hubs and documents.
Re-submit the sitemap; the URL count should jump from 6 to 20+.

**Exit:** 12–15 published documents; every hub > 300 words; sitemap reflects all of it;
no duplicate titles/descriptions.

---

## 10. Phase 7 — Entity and answer-engine readiness

On-site GEO. Necessary but **not sufficient** — it helps a model that already found you
describe you correctly; it does not make a model find you.

### T-7.1 Fill `SAME_AS` (unblocks entity grounding)
[`src/consts.ts`](../apps/marketing/src/consts.ts). Ask the user for real profiles the org
controls — GitHub org, X, LinkedIn company page, Product Hunt, Crunchbase. Verify each
returns `200` before adding (`curl -sS -o /dev/null -w '%{http_code}'`). The file's own
comment is right: a dead link is worse than none. **If no profiles exist yet, leave it
empty and make Phase 8 create them first — do not invent URLs.**

### T-7.2 Entity-description consistency
`ENTITY_DESCRIPTION` in `consts.ts` is the canonical one-liner. Use the *same* phrasing
on every off-site profile created in Phase 8 (GitHub bio, Product Hunt tagline, LinkedIn).
Models disambiguate entities by consistent repetition across independent sources; drifting
descriptions fragment the signal.

### T-7.3 Add `llms.txt`
Publish `/llms.txt` at the canonical root (an Astro endpoint, same pattern as T-2.3) — an
emerging convention giving LLM crawlers a curated map of the site. Cheap, additive, no risk.

### T-7.4 Expand structured data as content lands
The builders exist; wire them per type — `FAQPage` on every document with `faqs`,
`Article` on guides with `publishedAt`/`author`, `BreadcrumbList` on all nested routes.
Validate via Rich Results Test (T-4.5).

### T-7.5 Per-page `lastmod` from Sanity
[`astro.config.mjs`](../apps/marketing/astro.config.mjs)'s sitemap `serialize` already
supports passthrough `lastmod`; currently everything shares build time, a weak freshness
signal. Wire Sanity `_updatedAt` through.

### T-7.6 Answer-shaped formatting
Structure content so extraction is trivial: question-shaped H2s, a direct 40–60 word
answer immediately under each, short paragraphs, real tables, defined terms. This is the
formatting models quote.

---

## 11. Phase 8 — Off-site presence ⚠️ THE ACTUAL LLM LEVER

**Read this section carefully; it is the one most likely to be skipped and it is the one
that determines whether models ever recommend the product.**

Models recommend tools based on their **training corpus** and, when browsing, on
**retrieved third-party sources**. Almost none of that is your own marketing site.
Your JSON-LD helps a browsing model confirm facts about you *once it already knows you
exist*. It does essentially nothing to make it know you exist.

What actually drives it, roughly in order:

1. **Reddit and Hacker News discussions** — heavily weighted in training data and the
   single biggest lever for "what tool should I use for X"
2. **Comparison articles and roundups by other people** — the "best AI PRD tools" posts
   models synthesize from
3. **Public GitHub presence** — heavily crawled and cited; the repo is currently private,
   so there is no public artifact to reference
4. **Product directories** — Product Hunt, AlternativeTo, G2, Slant
5. **Newsletters, YouTube, conference talks**

### T-8.1 Create the entity footprint (unblocks T-7.1)
GitHub org profile, X, LinkedIn company page, Product Hunt. Use `ENTITY_DESCRIPTION`
verbatim on each. Feed the live URLs back into `SAME_AS`.

### T-8.2 Publish something public on GitHub
The strongest single GEO action available. Options, cheapest first:
- an open spec-format specification (the SPEC/PLAN/HARNESS/TASKS structure as a documented, reusable format)
- a small CLI or GitHub Action that consumes exported artifacts
- a public examples repo of real generated artifacts
- awesome-list-style curation of spec-driven-development resources

A public repo with a real README is crawled, cited, and starred — all signals models weigh.

### T-8.3 Launch posts — genuine participation only
Product Hunt launch; a Show HN; posts in relevant communities (r/ChatGPTCoding,
r/ClaudeAI, r/ExperiencedDevs, r/SaaS and similar).

**Rules, non-negotiable:**
- A **real human** posts and engages. The agent may draft copy; it must not operate
  accounts or impersonate users.
- **No astroturfing** — no fake accounts, sockpuppets, planted reviews, or undisclosed
  affiliation. It violates every platform's rules, and communities like HN and Reddit
  detect and punish it in ways that are far worse than obscurity.
- Disclose affiliation plainly. "I built this" outperforms pretending you didn't.
- Lead with the problem and a real artifact, not a pitch. Show actual generated output.

### T-8.4 Earn third-party comparison coverage
Submit to AlternativeTo, Slant, and relevant "AI dev tools" directories. Reach out to
newsletter and blog authors who cover AI coding tooling with a genuine, specific pitch.
One roundup inclusion is worth more for LLM recommendation than every meta tag in the repo.

### T-8.5 Publish real artifacts as public shares
The product already has public share routes (`/p/`, `/sb/`). Those are `noindex` by
design and must stay that way — but the *same* artifacts republished as `demoPage`
documents on the marketing zone (T-6.2) are indexable proof of capability. This is
first-party evidence no competitor can copy.

**Exit:** a public GitHub artifact exists; Product Hunt live; at least one substantive
HN/Reddit thread; `SAME_AS` populated with live URLs; at least one third-party listing.

---

## 12. Phase 9 — Traffic → users

Ranking without conversion is vanity. The ask is *users*, not sessions.

- **T-9.1** — every marketing document ends with a contextual CTA to sign-in
  (`SIGN_IN_URL` in [`consts.ts`](../apps/marketing/src/consts.ts)), not a generic footer link.
- **T-9.2** — the homepage must answer "what is this and what do I get" above the fold;
  verify with Playwright MCP at mobile and desktop widths.
- **T-9.3** — confirm the free-credit path is obvious. A visitor arriving from a guide
  should reach a generated artifact without hitting a paywall or a confusing empty state.
- **T-9.4** — attribute signups to landing page. [`src/lib/analytics.ts`](../apps/marketing/src/lib/analytics.ts)
  exists; confirm it distinguishes organic entry points so Phase 10 can tell which
  content converts.
- **T-9.5** — Core Web Vitals: the zone is `output: "static"` with no runtime JS, so it
  should score well by construction. Verify rather than assume.

---

## 13. Phase 10 — Measurement and monitoring

### T-10.1 Regression monitor (would have caught this outage on day one)
A synthetic check asserting `GET /sitemap-index.xml` → `200` and the homepage byte size
> 5,000. This outage was invisible for the entire period since go-live. A one-line check
prevents a recurrence.

### T-10.2 Search Console review cadence
Monthly: impressions, clicks, average position, coverage errors, and which queries
actually surface. Real query data replaces T-6.1's assumptions — feed it back into the
content map.

### T-10.3 LLM-citation tracking
Periodically ask major assistants category questions ("what tools turn a product idea
into a spec for a coding agent?") and record whether Thought2Build appears and how it is
described. This is the only direct read on GEO progress. Track the *description* too —
a wrong description is an entity-consistency bug (T-7.2).

### T-10.4 Content cadence
2–4 quality documents per month, sustained. SEO compounds; a single burst decays. If the
cadence cannot be sustained, prefer fewer, better documents over more, thinner ones.

---

## 14. Rollback

| Phase | Rollback |
| --- | --- |
| 2 | `git revert` — no production surface touched |
| 3 T-3.3 | Re-add domains to the SPA project. **The app keeps working throughout either way** — the SPA is reachable via its `*.vercel.app` host and via the apex rewrites |
| 3 T-3.6 | Revert env values, restart Railway services |
| 5 | Sitemaps can be removed from GSC; indexing requests cannot be withdrawn (harmless) |
| 6–8 | Content and posts are additive; unpublish via Sanity if needed |

Genuine risk is concentrated in **T-3.3** (domain move) and **T-3.6** (host-dependent
config). Everything else is additive or revertible with a commit.

---

## 15. Definition of done

### Part I — unblocked (technical)
- [ ] Canonical host serves static Astro HTML with unique title, description, canonical, OG, and JSON-LD on every indexable route
- [ ] `robots.txt` is the marketing policy; its `Sitemap:` origin matches the canonical origin
- [ ] `sitemap-index.xml` / `sitemap-0.xml` → `200`, zero `localhost`
- [ ] Non-canonical host 308-redirects to canonical
- [ ] `/p/*` and `/sb/*` reachable and `noindex`; `/dashboard` and auth still work
- [ ] CI fails loudly if the marketing deploy is unconfigured
- [ ] Production build fails loudly if `PUBLIC_SITE_URL` is unset
- [ ] New origin tests fail without the fixes, pass with them
- [ ] GSC domain property verified; sitemap submitted with Success
- [ ] `docs/SEO_INDEXING_VERIFICATION.md` holds before/after evidence for every probe

### Part II — acquiring (outcome)
- [ ] 12–15 substantive documents published; every hub > 300 words
- [ ] `SAME_AS` populated with live, verified profile URLs
- [ ] `llms.txt` published; FAQPage/Article/Breadcrumb JSON-LD live on applicable routes
- [ ] A public GitHub artifact exists and is linked from the site
- [ ] Product Hunt live; at least one substantive HN/Reddit thread; ≥1 third-party listing
- [ ] Synthetic monitor alerting on sitemap/homepage regression
- [ ] Search Console showing non-zero impressions for non-brand queries
- [ ] At least one assistant naming Thought2Build for a category question (T-10.3)

**The last two are the only items on this list that mean "we are getting users."
Everything above them is a prerequisite.**
