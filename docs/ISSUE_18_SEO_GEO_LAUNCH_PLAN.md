# Issue #18 — Production SEO + GEO Launch Plan

> Status: **Approved, not yet started.** Execute phase by phase; check off items as they land.

## Context

SpecForge today is a **client-rendered Vite 8 + rolldown React SPA**. The only crawlable
HTML is the empty `index.html` shell (`<div id="root">`); every route is resolved in the
browser by React Router, and Vercel's catch-all rewrite
(`frontend/vercel.json`: `/((?!api/).*) -> /index.html`) funnels *everything* into that
shell. The lone marketing surface is `Landing` (`frontend/src/pages/Landing.tsx`). Public
generated artifacts (`/p/:slug`, `/sb/:slug`) are intentionally `noindex` (JS-injected meta +
backend `X-Robots-Tag` + `_headers`; `robots.txt` disallows `/p/` only).

Issue #18 wants organic + answer-engine (GEO) acquisition before launch: a **crawlable,
statically-generated marketing/content layer** backed by **Sanity**, with full technical-SEO
hygiene, answer-ready content, curated first-party demos, and measurement — **without**
exposing any user data and **without** un-noindexing `/p/*` or `/sb/*`.

Because the SPA is on Vite 8 + rolldown, in-app prerender plugins are out (`vite-react-ssg`
peers only to Vite 7; latest is a beta). **Decision (confirmed with user): build the marketing
layer as a separate Astro static site** that reuses the "Modern Indica" Tailwind tokens, pulls
content from Sanity at build time, and is routed onto the same origin as the SPA via Vercel
multi-zone rewrites. The existing SPA is left untouched and keeps owning all app +
public-artifact routes.

**Outcome:** every indexable marketing/content/demo route ships real static HTML with
complete, unique metadata + validated structured data; `/p/*`, `/sb/*`, app routes, and
generated artifacts stay noindex; and AC-mapped tests guard all of it.

---

## Architecture

**Same origin, two zones (Vercel multi-zone).** Apex domain → **marketing (Astro) project**
(primary zone). Its `vercel.json` *rewrites* the SPA-owned paths to the existing frontend
deployment:

```
Astro zone serves (static HTML):  /  /guides/*  /templates/*  /use-cases/*  /compare/*  /demos/*
                                  /sitemap.xml  /robots.txt  /_astro/*
Rewrite → SPA zone:               /dashboard  /workspace/*  /settings  /billing
                                  /auth/callback  /p/*  /sb/*  /assets/*  (+ SPA fallbacks)
```

Single origin keeps OAuth redirect URIs, the HTTP-only refresh cookie, CSRF, and CORS
**unchanged** (no app-subdomain split). Asset namespaces don't collide (`/_astro/*` vs
`/assets/*`). The SPA's own `vercel.json` catch-all stays valid *inside* the SPA zone.

**New top-level dir:** `apps/marketing/` (Astro). The repo becomes a light monorepo;
`frontend/` is unchanged except its `vercel.json` rewrite is tightened so it no longer claims
marketing paths (those never reach it, but we make the boundary explicit + tested).

**Content freshness:** Sanity content is fetched at **build time**, so edits require a
redeploy. Wire a **Sanity webhook → Vercel deploy hook** on the marketing project only. (If
editors later need instant publish without rebuilds, that's the upgrade path to ISR; out of
scope for launch.)

**Config:** add `SITE_URL` (backend, for any server-emitted canonical/sitemap concerns) and
`PUBLIC_SITE_URL` (Astro, exposed as `import.meta.env.PUBLIC_SITE_URL`) for canonical URLs, OG
absolute URLs, and sitemap base. Backend `config.py` already has `frontend_url`; add
`site_url` alongside it and require HTTPS in prod via `validate_production_settings()`.

---

## Phased plan (foundation-first, per the issue)

### Phase 1 — Rendering foundation + crawlability + noindex integrity
*Goal: real static HTML exists, routing boundary is correct, and noindex protections are airtight before any content is published.*

1. Scaffold `apps/marketing/` Astro project: `astro`, `@astrojs/tailwind` (reuse the frontend
   Tailwind config / Modern Indica tokens — import the existing token source rather than
   forking it), `@astrojs/react` (for islands), `@astrojs/sitemap`, `@sanity/astro` +
   `@sanity/client`. Output mode `static`.
2. Port the homepage from `frontend/src/pages/Landing.tsx` to `src/pages/index.astro`
   (static), reproducing the "Sign in with Google" CTA as a link to
   `${PUBLIC_API_URL}/auth/google`. Keep the SPA `Landing` as the in-app fallback but it is no
   longer the indexable `/`.
3. Add a reusable `<Seo>` Astro component (title, meta description, canonical, OG, Twitter
   card, robots) + a `<JsonLd>` component. One layout (`BaseLayout.astro`) wires them.
4. `apps/marketing/vercel.json`: rewrites mapping SPA-owned paths to the SPA zone (see
   Architecture). Tighten `frontend/vercel.json` so its catch-all is clearly the
   SPA-zone-internal fallback.
5. **Crawler policy:** production-safe `robots.txt` (Astro `public/`) — allow marketing, keep
   `Disallow: /p/`, **add `Disallow: /sb/`**, reference `Sitemap:` URL. Update
   `frontend/public/_headers`: add a `/sb/*` block with `X-Robots-Tag: noindex, nofollow` to
   match `/p/*` (closes the non-JS-crawler gap the audit flagged).

### Phase 2 — Metadata, sitemap, structured data
1. Drive per-route `<Seo>` from page data so **every** indexable route has unique title /
   description / canonical / OG / Twitter. Defaults + per-page overrides; fail the content QA
   check (Phase 6) on duplicates or missing fields.
2. `/sitemap.xml` via `@astrojs/sitemap`, **filtered to indexable routes only** — explicitly
   excludes `/p/*`, `/sb/*`, and app routes (those aren't Astro pages, so they're naturally
   absent, but assert it in tests).
3. JSON-LD via `<JsonLd>`: `Organization` + `SoftwareApplication` (site-wide), `FAQPage`
   (answer-ready pages), `BreadcrumbList` (nested content), `Article` (guides). Validate
   shapes in tests.

### Phase 3 — Sanity content models
Add Sanity schema (in `apps/marketing/sanity/` or a `sanity/` studio) for: `seoPage`, `guide`,
`templatePage`, `demoPage` (curated, first-party), and `redirect`. Each content type carries
explicit SEO fields (title/description/canonical override/OG image) and GEO fields (direct
definition, workflow steps, comparison table, FAQ list, examples). `redirect` powers
Vercel/Astro redirects. Add a typed Sanity fetch layer (GROQ queries) used by the dynamic
`[slug].astro` routes.

### Phase 4 — Launch content (focused)
Per the issue's keyword coverage (spec-to-build, coding-agent handoff, PRD/templates):
homepage SEO refresh, use-case pages, template pages, comparison pages, guide pages, and
**curated first-party demo pages**. Demos are authored content (first-party only) — **no live
user workspaces/storyboards**. Entity language is standardized: "SpecForge — an AI
spec-to-build workspace that turns rough product ideas into SPEC, PLAN, HARNESS, and TASKS
artifacts" (single shared snippet).

### Phase 5 — GEO answer-readiness + measurement
1. Answer-ready page template: direct definition up top, workflow steps, comparison table, FAQ
   (→ `FAQPage` JSON-LD), concrete examples, consistent entity language.
2. **AI-referral measurement:** analytics + GSC wiring. Track referrers for `chatgpt.com`,
   `perplexity.ai`, `gemini.google.com`, `copilot.microsoft.com`/`bing.com`, and `claude.ai`
   as a named "AI answer engines" channel. (Privacy-light analytics; GSC verification meta/DNS
   for Search Console.)
3. **Synthetic query audit:** a small repeatable script/checklist of target queries run
   against the answer engines (where APIs/manual allow) to track citation/visibility over
   time — defined as a launch-monitoring artifact, not automated gating.
4. `/llms.txt` explicitly **deferred** (issue says it's not a launch dependency).

### Phase 6 — Validation (maps 1:1 to acceptance criteria)
Wire into the existing `harness/` contract suite + marketing project CI. Tests:
- **Static-HTML render**: build `apps/marketing`, assert indexable routes emit non-empty
  `<h1>`, title, and body content in the static output (not an empty root div).
- **Metadata completeness**: every indexable route has unique title/description/canonical/OG/
  Twitter; no duplicate titles; H1 present; CTA present; no placeholder copy; no orphaned
  routes (every page reachable + in sitemap).
- **Sitemap**: includes only indexable routes; **excludes** `/p/*`, `/sb/*`, app routes.
- **robots.txt**: does NOT block `/` or content hub; DOES disallow `/p/` and `/sb/`.
- **noindex regression** (the critical guard): assert `/p/*` and `/sb/*` carry
  `noindex, nofollow` via BOTH `_headers` and `robots.txt` (and the existing backend
  `X-Robots-Tag` / JS meta remain). This is the test that protects user data from the new open
  crawler policy.
- **Structured data**: JSON-LD validates for each supported type.
- **GEO content QA**: answer-ready structure present (definition/workflow/FAQ/comparison/
  examples), entity language consistent, and **demo sanitization** — curated demos contain no
  user data, secrets, private links, or unsafe generated artifacts.
- **Measurement readiness**: analytics + GSC config present; AI-referral channel defined;
  synthetic-query audit checklist committed.

### Phase 7 — CI + deploy
Extend `.github/workflows/ci.yml` with a marketing job: install, `astro build`, run the
metadata/sitemap/robots/noindex/structured-data/GEO QA tests, `astro check`. Add the marketing
project to Vercel; configure the Sanity→deploy webhook. Backend
`validate_production_settings()` enforces HTTPS `SITE_URL` in prod.

---

## Critical files

**New** — `apps/marketing/` (Astro): `astro.config.mjs`, `vercel.json`,
`src/pages/index.astro`,
`src/pages/{guides,templates,use-cases,compare,demos}/[slug].astro`,
`src/layouts/BaseLayout.astro`, `src/components/{Seo,JsonLd}.astro`, `src/lib/sanity.ts`
(GROQ), `sanity/schema/*`, `public/robots.txt`, GEO/measurement scripts, tests.

**Modified** — `frontend/vercel.json` (tighten catch-all to SPA-zone-internal),
`frontend/public/_headers` (add `/sb/*` noindex block), `frontend/public/robots.txt`
(superseded by the marketing zone's robots, or kept consistent), `backend/config.py`
(`site_url` + prod validation), `.github/workflows/ci.yml` (marketing job + deploy).

**Reused** — Tailwind config / Modern Indica tokens (from `frontend/`, shared not forked),
existing noindex patterns in `routers/public.py` / `routers/storyboards.py` (kept as the
backend belt-and-suspenders layer), `frontend/src/pages/Landing.tsx` (source for the ported
homepage).

---

## Verification (end-to-end)

1. `cd apps/marketing && pnpm build` → inspect `dist/`: `index.html`, `guides/<slug>/index.html`
   etc. contain real `<h1>`/content + full `<head>` meta (curl/grep the built files).
2. `pnpm preview` (or `vercel dev`): load `/`, a guide, a template, a demo — view-source shows
   metadata, canonical, OG, Twitter, JSON-LD. Validate JSON-LD in Google's Rich Results test.
3. Confirm `/p/<slug>` and `/sb/<slug>` still return `noindex` (rewrite resolves to SPA zone;
   `_headers` + backend header present) — this is the must-not-regress check.
4. Fetch `/sitemap.xml` and `/robots.txt`: sitemap lists only indexable routes; robots allows
   `/`, disallows `/p/` and `/sb/`, points to the sitemap.
5. Run the harness/marketing test suite (metadata, sitemap, robots, noindex regression,
   structured data, GEO QA, demo sanitization) — all green; wired into CI.
6. Trigger a Sanity content edit → confirm the deploy hook rebuilds and the new content
   appears statically.

## Open / explicitly deferred

- `/llms.txt` — deferred (issue: not a launch dependency).
- ISR/instant-publish — deferred; build-time + deploy-hook is the launch posture.
- Exact analytics vendor + GSC ownership — to confirm during Phase 5 (default to a
  privacy-light analytics tool already compatible with the CSP).

---

## Progress log

- [x] Phase 1 — Rendering foundation + crawlability + noindex integrity
  - Scaffolded `apps/marketing/` (Astro 5, `output: "static"`): `astro.config.mjs`,
    `tailwind.config.mjs` (reuses Modern Indica tokens), `tsconfig.json`,
    `package.json`. `@astrojs/react` / `@astrojs/sitemap` / `@sanity/*` present
    but only lightly wired (their phases finalise them).
  - Ported the homepage to `src/pages/index.astro` (static HTML, zero JS shipped),
    CTA → `${PUBLIC_API_URL}/auth/google`. Landing CSS lifted verbatim into
    `src/styles/global.css`. SPA `Landing` kept as in-app fallback.
  - `<Seo>` + `<JsonLd>` components and `BaseLayout.astro`; homepage carries
    Organization + SoftwareApplication JSON-LD and full OG/Twitter/canonical.
  - `apps/marketing/vercel.json` rewrites SPA-owned paths to the SPA zone
    (**SPA host is a placeholder — set during Phase 7 Vercel setup**).
    `frontend/vercel.json` catch-all tightened to exclude marketing namespaces.
  - Crawler policy: authoritative `apps/marketing/public/robots.txt`
    (allow marketing, `Disallow: /p/` + `/sb/`); `frontend/public/_headers` gains
    a `/sb/*` `noindex` block (JS-safe — no scriptless CSP, since `/sb/` is an
    SPA route); `frontend/public/robots.txt` adds `Disallow: /sb/`.
  - Verified: `pnpm build` + `astro check` clean; `dist/index.html` emits real
    `<h1>`/body/title/description/canonical/robots/OG/Twitter/JSON-LD + bundled
    CSS, no external script tags.
- [x] Phase 2 — Metadata, sitemap, structured data
  - Per-route metadata: `<Seo>` is driven entirely by page data with
    defaults only on the *safe* fields (OG image, `og:locale`, Twitter card,
    robots). `title` and `description` stay **required with no fallback** —
    a silent description default would let every un-overridden page pass the
    Phase 6 duplicate/missing QA with identical copy, defeating the gate.
    Added `og:locale`, `og:image:alt`/`twitter:image:alt`, optional
    `article:published_time`/`modified_time` (for guide pages), and an optional
    `twitter:site`/`creator` handle. `BaseLayout` forwards all of them.
  - Centralised SEO + structured-data library `src/lib/seo.ts`: site-wide
    defaults plus pure, typed JSON-LD builders for the five plan types —
    `organizationSchema`, `softwareApplicationSchema`, `faqPageSchema`,
    `breadcrumbListSchema`, `articleSchema`. Entities share stable `@id`
    anchors (`/#organization`, `/#software`) so they resolve to one connected
    graph; SoftwareApplication carries the free-tier `Offer` and references the
    Organization as publisher. `siteJsonLd` is the site-wide bundle; `index.astro`
    now consumes it instead of inlining the schema.
  - Sitemap (`astro.config.mjs`): explicit `filter` excludes `/p`, `/sb`, and
    the SPA app routes (`/dashboard`, `/workspace`, `/settings`, `/billing`,
    `/auth`, `/assets`) — a defence-in-depth boundary (those aren't Astro pages,
    so they can't appear anyway) that's now testable. `serialize` sets `lastmod`
    (passthrough-first → Phase 3/4 supplies Sanity `_updatedAt`) and a homepage
    `priority`; `changefreq`/`priority` are deliberately minimal since Google
    ignores them as ranking signals. Robots `Sitemap:` stays `sitemap-index.xml`
    (matches the `@astrojs/sitemap` output and Phase 1); comment finalised.
  - Verified: `pnpm check` + `pnpm build` clean. `dist/index.html` emits unique
    title/description/canonical/robots + full OG (incl. locale + image:alt) +
    Twitter, and the `@id`-anchored Organization + SoftwareApplication JSON-LD;
    homepage still ships zero executable JS (only the ld+json block).
    `dist/sitemap-0.xml` carries `<lastmod>` + homepage `<priority>1.0</priority>`;
    `dist/robots.txt` allows `/`, disallows `/p/` + `/sb/`, points at the sitemap.
- [x] Phase 3 — Sanity content models
  - Standalone Sanity studio in `apps/marketing/sanity/` (own package +
    `sanity.config.ts`/`sanity.cli.ts`/`tsconfig.json`), **deliberately not
    embedded** via `@sanity/astro`: an embedded `/studio` would put an editor
    surface on the public marketing origin to noindex + sitemap-exclude, which
    fights the issue's noindex-integrity requirement. Deploys separately
    (`sanity deploy`); the Astro site only *reads* it at build time. Excluded
    from the Astro `tsconfig.json` so `astro check` never types studio files
    against deps the marketing app doesn't install.
  - Five document types — `seoPage` (one type powering `/use-cases/*`,
    `/compare/*`, and top-level landings via a `section` field), `guide`
    (→ Article), `templatePage`, `demoPage` (**curated, first-party only** — no
    import-from-workspace path; the Phase-6 demo-sanitization gate's data model),
    and `redirect` — over shared objects (`seo` + the GEO answer-readiness blocks
    `faqItem`/`workflowStep`/`comparison`/`example`/`blockContent`). Every doc
    carries an explicit `seo` block (title/description/canonical override/OG
    image) and the GEO fields (direct definition, workflow steps, comparison
    table, FAQ list, examples).
  - Typed GROQ fetch layer `src/lib/sanity.ts` with **explicit named projections**
    (never `*[_type==…]` splats — the type↔query alignment is the only thing
    Phase 3 can verify, since no routes exercise it yet) and result types shaped
    **backward from the Phase-2 consumers**: `SanityFaq` is a literal alias of
    `seo.ts`'s `FaqItem`, and `guideToArticleInput()` composes a `guide` straight
    into `articleSchema`'s `ArticleSchemaInput` — so the projection drifting from
    what the builders need stops the build. `_updatedAt` → sitemap `lastmod` /
    Article `dateModified`; `coalesce(publishedAt, _createdAt)` → `datePublished`.
  - **Graceful degradation** (the load-bearing contract): the client is created
    *lazily* and only when `isSanityConfigured` (a top-level
    `createClient({projectId:""})` throws at construction); every fetch
    short-circuits to `[]`/`null` when unconfigured, so CI builds with no creds
    stay green and the first Phase-4 route can't brick. `projectId`/`dataset` are
    `PUBLIC_`-exposed (public values); a read token is neither used nor
    `PUBLIC_`-prefixed. `useCdn:false` + pinned `apiVersion`.
  - Verified: `pnpm check` + `pnpm build` clean (0 errors). Runtime degradation
    confirmed by *executing* the layer through a throwaway scratch page during a
    real build (not just type-checking): unconfigured ⇒
    `isSanityConfigured:false`, every fetch `[]`/`null`, no throw. **Not
    runtime-verified against live Sanity** — that's correct for the phase
    boundary: the page templates that consume these queries are Phase 4.
- [x] Phase 4 — Launch content
  - **Content boundary (stated up front):** Phase 4 ships the *templates +
    hubs + in-repo copy* that consume the Phase-3 fetch layer. The actual
    guide/use-case/comparison/template/demo *documents* are authored in the
    Sanity studio later (creds land in Phase 7). With Sanity unconfigured every
    `getStaticPaths` yields zero detail pages, so a green build alone proves
    nothing here — each template was verified against **fixture data** instead
    (see Verified).
  - Five dynamic detail routes consuming `src/lib/sanity.ts`:
    `/guides/[slug]` (Article), `/use-cases/[slug]` + `/compare/[slug]` (both
    `seoPage`, sharing one `SeoPageArticle` body — workflow-led vs table-led),
    `/templates/[slug]`, `/demos/[slug]`. Each emits `BreadcrumbList` always and
    `FAQPage` only when FAQs exist (an empty FAQPage is an invalid/penalized
    shape); guides add `Article` via the Phase-3 `guideToArticleInput` adapter.
    The top-level `landing`-section `seoPage` route (`/[slug]`) is **deliberately
    deferred** — a catch-all top-level dynamic route risks shadowing future
    static pages; the hubs filter to `use-case`/`comparison` so a `landing` doc
    is never listed pointing at a route that doesn't exist.
  - Five **hub/index pages** (`/guides`, `/templates`, `/use-cases`, `/compare`,
    `/demos`) — themselves indexable SEO surfaces carrying the keyword-cluster
    copy in-repo (spec-to-build, coding-agent handoff, PRD/spec/plan templates,
    "X vs Y"). Hubs are linked from a shared `SiteHeader`/`SiteFooter` and an
    on-homepage "explore" grid (single source: `CONTENT_HUBS` in `consts.ts`),
    so every hub is reachable from every page — the Phase-6 "no orphaned routes"
    guard. Detail pages link back via visible breadcrumbs that mirror the
    `BreadcrumbList` JSON-LD.
  - GEO answer-ready rendering (the structure is inherent to the content types;
    Phase 5 adds *measurement*, not this): a shared `AnswerReady` block set
    renders, in answer-engine order, the direct-answer **definition** up top →
    **workflow** steps → **comparison** table → **examples**; `FaqSection`
    renders a no-JS `<details>` FAQ whose visible Q&A is byte-identical to the
    `FAQPage` markup (Google requires the match). Rich `body` is Portable Text
    via `@portabletext/to-html` (`PortableText.astro`).
  - **Demos are curated, first-party only** — no import-from-workspace path. The
    four artifacts (spec/plan/harness/tasks Markdown) render to real crawlable
    HTML via `marked` (`src/lib/markdown.ts`), which **drops raw/inline HTML**
    (`renderer.html → ""`) as defense-in-depth beneath the Phase-6 content gate.
  - **Entity-language discipline (the load-bearing SEO rule):** meta
    `title`/`description` come **only** from each doc's authored `seo.*` (unique,
    min/max-validated in the studio); `ENTITY_DESCRIPTION` lives **only** in
    in-body framing + JSON-LD, **never** as a meta fallback — wiring it as a
    description default would let un-overridden pages pass the Phase-6
    duplicate/missing QA with identical copy, defeating the gate. Homepage
    "refreshed" by standardizing on that snippet in body/footer copy and adding
    the hub-discovery links; its required title/description stay bespoke.
  - Two build-time deps added (`marked`, `@portabletext/to-html`); both run only
    at SSG time, ship zero client JS. `PortableTextBlock` tightened to
    `{ _type: string; … }` (strictly more correct — every PT block has `_type`;
    also satisfies `to-html`'s `TypedObject`). One latent note carried in
    `PortableText.astro`: the bare `body` projection has no asset deref, so
    in-body `image` blocks need a projection+serializer when that content lands.
  - **Verified:** `pnpm check` 0/0/0 and `pnpm build` clean (6 pages: `/` +
    5 hubs; detail routes correctly build 0 pages with no Sanity content). Each
    template was then exercised through **throwaway fixture pages** fed sample
    `GuideDoc`/`SeoPageDoc`/`DemoPageDoc` (the Phase-3 scratch-page technique):
    confirmed real `<h1>`, valid `Article`+`BreadcrumbList`+`FAQPage` JSON-LD,
    Portable-Text body, all answer-ready blocks (definition/workflow/comparison/
    examples), and that an embedded `<script>alert('xss')</script>` in demo
    Markdown was dropped (0 occurrences) — then deleted the fixtures and rebuilt
    clean. Confirmed the 5 hubs carry unique authored meta descriptions, that
    `ENTITY_DESCRIPTION` never appears in a `<meta name="description">`, and that
    the sitemap lists `/` + the 5 hubs only (no app/`/p`/`/sb`/scratch routes).
  - **Conscious deferral (Phase-2 handoff):** sitemap `lastmod` per detail page
    from Sanity `_updatedAt` is **not** wired — `@astrojs/sitemap`'s `serialize`
    runs at config time without per-page Sanity data, and no detail pages exist
    until content is authored. Revisit when detail routes have content (Phase 7
    deploy/webhook), alongside the analytics/GSC/AI-referral measurement that is
    Phase 5's actual new work.
- [x] Phase 5 — GEO answer-readiness + measurement
  - **Answer-ready template (5.1) was finalized in Phase 4** and verified again
    here: the `AnswerReady` set renders, in answer-engine order, direct-answer
    **definition** → **workflow** → **comparison table** → **examples**, and
    `FaqSection` renders a no-JS `<details>` FAQ whose visible Q&A byte-matches
    the `FAQPage` JSON-LD, with consistent `ENTITY_DESCRIPTION` framing. Phase 5
    adds **measurement**, not new template structure.
  - **Vendor: Vercel Web Analytics** (user decision). Chosen because the zone
    deploys on Vercel — its script is served **first-party from
    `/_vercel/insights/*`** (same-origin → CSP-clean, no third-party host to
    allowlist later), cookieless/privacy-light (no consent banner), and it
    captures the referrer breakdown natively. Wired via `@vercel/analytics/astro`
    (`<Analytics/>` island, default export — API verified empirically against the
    installed package, not memory).
  - **Gated + inert by default (the load-bearing posture):** `src/lib/analytics.ts`
    exposes `analyticsEnabled` (`PUBLIC_ANALYTICS_ENABLED === "true"`, **off by
    default**). `BaseLayout` renders the analytics island only when enabled — a
    default/CI/preview build ships **zero executable JS** (verified: no
    `<script src>`/`type=module`, no `vercel`/`_astro/*.js`, no GSC meta in the
    built HTML). Enabled build verified to emit the Vercel island + the bundled
    classifier + the GSC meta. Real creds switch on in Phase 7.
  - **AI-referral channel (5.2):** `AI_ENGINE_REFERRERS` in `analytics.ts` is the
    single source of truth (consumed by both the client classifier and the
    Phase-6 tests, so it can't drift). A pure, side-effect-free `classifyReferrer()`
    maps a `document.referrer` to `{engine,label,channel}`; the classifier is a
    **bundled** module script (`Analytics.astro`, not `define:vars`-inline — keeps
    it an external `/_astro/*` asset, CSP-clean for Phase 7) that fires
    `track('AI Referral', { engine, channel })`. **`bing.com` is deliberately a
    separate `mixed_search_ai` bucket**, not in the core `ai_answer_engine`
    channel — `bing.com` referrals are mostly classic Bing organic, so folding
    them in would inflate the exact metric this phase isolates; we keep the host
    (some Copilot-in-Bing answers refer as `bing.com`) without polluting the AI
    channel. `copilot.microsoft.com` is the high-confidence Copilot host. Logic
    smoke-tested against sample referrers (Bing split, www/cn-subdomain suffix
    match, classic-Google → null, empty/invalid → null — all pass).
  - **Honest caveats committed this phase (not deferred surprises):** the README
    states (a) Vercel **custom events need Pro+** — on Hobby they drop, so the
    **native referrer breakdown is the guaranteed baseline** and the custom event
    is an enhancement; (b) referrer attribution is **best-effort** (policy
    stripping / origin-only referrers) — a **sampler, not a census**.
  - **Search Console (5.2):** gated `<meta name="google-site-verification">` in
    `<head>` driven by `PUBLIC_GSC_VERIFICATION`, **independent** of analytics
    (renders even with tracking off; blank ⇒ omitted, e.g. DNS verification).
  - **Synthetic-query audit (5.3):** `apps/marketing/measurement/` —
    `synthetic-queries.json` (cluster-keyed target queries: spec-to-build /
    coding-agent-handoff / templates / comparisons, mapped to hubs + the six
    engines), a dependency-free `audit.mjs` that renders a dated fill-in results
    log (16 queries × 6 engines = 96 checks), `SYNTHETIC_QUERY_AUDIT.md`
    (methodology, cadence, limitations) and `README.md` (the full measurement
    overview + AI-channel definition). Defined as a **launch-monitoring artifact,
    not an automated gate** (engine answers are non-deterministic / mostly
    API-less). `measurement/runs/` holds dated runs.
  - **`/llms.txt` (5.4): deferred** per the issue (not a launch dependency).
  - Two build-time-only deps unaffected; added `@vercel/analytics` (client island,
    only shipped when enabled). `pnpm check` 0/0/0; disabled + enabled builds both
    verified.
- [x] Phase 6 — Validation tests
  - **Test runner:** added `vitest` (+ `linkedom` for zero-DOM HTML parsing) to
    `apps/marketing` with `vitest.config.ts` built on Astro's `getViteConfig`,
    so the suite imports the site's own `.astro` components and TS libs with the
    **same resolution the build uses** (no forked module graph) and
    `import.meta.env` is defined. `pnpm test` → `vitest run`. CI wiring is
    **deliberately left to Phase 7** (which owns the marketing job).
  - **Always-fresh dist (kills the stale-pass class):** `tests/setup/global-setup.ts`
    runs `astro build` **unconditionally** before the suite (~1.6s), so the
    dist-parsing tests can never pass against stale output. A credential-free
    build emits the homepage + 5 hubs — exactly the "always-indexable" surface
    the dist assertions gate; Sanity detail routes are covered by
    component/unit tests instead (they don't build without content in CI).
  - **8 test files / 137 assertions, mapped 1:1 to the ACs:**
    `static-html` (every indexable route emits one non-empty `<h1>`, a `<title>`,
    a `<main>`, and >200 chars of real body — not an empty `#root` div);
    `metadata` (per-route unique title/description/canonical/OG/Twitter +
    indexable robots + sign-in CTA + no placeholder copy + the load-bearing
    "`ENTITY_DESCRIPTION` is never reused as a `<meta description>`" check, plus
    cross-route title/description/canonical **uniqueness**); `sitemap` (lists
    only the indexable routes, no orphans, **excludes** `/p`,`/sb`, app routes);
    `robots` (both zones disallow `/p/`+`/sb/`, never block `/` or the hubs,
    reference the sitemap); `noindex-regression` (**the critical guard** —
    `_headers` `X-Robots-Tag` on `/p/*`+`/sb/*`, both robots.txt disallows,
    `vercel.json` rewrites `/p/`+`/sb/` to the SPA zone but **not** the hubs,
    and the backend `X-Robots-Tag` + SPA JS-meta source guards still present —
    backend *behavior* stays owned by `harness/tests/backend` phase14/23, not
    duplicated); `structured-data` (homepage Organization+SoftwareApplication
    `@id`-connected graph as actually emitted, plus the FAQPage/BreadcrumbList/
    Article pure builders); `geo-content` (answer-ready blocks rendered via the
    **Astro Container API** assert definition→workflow→comparison→examples
    **order**, FAQ visible Q&A byte-matches the FAQPage JSON-LD, empty FAQ emits
    nothing, and demo-sanitization exercises `renderMarkdown` dropping
    `<script>`/inline handlers/`<iframe>`/`<object>`; entity language verbatim
    on every page); `measurement` (AI-referral channel = the 5 engines with
    `bing` isolated to `mixed_search_ai`, `classifyReferrer` host-suffix +
    null-path behavior, analytics opt-in/inert by default, GSC meta gated, and
    the synthetic-query audit artifacts committed + hub-mapped).
  - **Container API kept non-load-bearing** (advisor steer): component-level
    only (`AnswerReady`/`FaqSection` import types, no island → no renderer
    registration); full-page rendering avoided (the `@vercel/analytics` island
    would need React wired into the container). Every other AC is covered by
    dist-parsing or pure-unit tests, so the suite never hinges on the
    experimental API.
  - **Verified non-vacuous:** mutation-tested the critical guard — deleting the
    `/sb/*` `X-Robots-Tag` from `_headers` turns `noindex-regression` RED;
    reverted, all 137 green. `pnpm check` 0/0/0; `pnpm test` 8 files / 137 pass.
- [ ] Phase 7 — CI + deploy
