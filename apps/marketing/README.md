# SpecForge marketing zone (Astro)

Statically-generated marketing + content layer for SpecForge (issue #18). Ships
real, crawlable HTML with complete SEO metadata and structured data, served on
the **same origin** as the SPA via Vercel multi-zone rewrites. The SPA
(`frontend/`) is untouched and keeps owning all app + public-artifact routes.

## Why a separate Astro app

The SPA is on Vite 8 + rolldown, where in-app prerender plugins are out. This
zone exists purely to emit static HTML for indexable routes; it reuses the
"Modern Indica" design tokens (`src/styles/global.css`, mirrored in
`tailwind.config.mjs`) so it stays visually identical to the SPA.

## Develop

```bash
pnpm install
pnpm dev        # astro dev
pnpm build      # astro build -> dist/ (static)
pnpm preview    # serve dist/
pnpm check      # astro check (types)
```

Copy `.env.example` → `.env` and set `PUBLIC_SITE_URL` / `PUBLIC_API_URL`.

## Routing (Vercel multi-zone)

`vercel.json` rewrites SPA-owned paths (`/dashboard`, `/workspace/*`,
`/settings`, `/billing`, `/auth/*`, `/p/*`, `/sb/*`, `/assets/*`) to the SPA
deployment. **The SPA deployment host in `vercel.json` is a placeholder
(`specforge-app.vercel.app`)** — set it to the real SPA zone URL when the
marketing project is added to Vercel (Phase 7).

## Crawler policy / noindex integrity

- `public/robots.txt` is **authoritative** at the apex: allows marketing,
  disallows `/p/` and `/sb/`. The SPA's `frontend/public/robots.txt` is shadowed
  at the apex and kept consistent only for direct SPA-URL hits.
- Public generated artifacts (`/p/*`, `/sb/*`) stay noindex via the backend
  `X-Robots-Tag`, the SPA `_headers` blocks, and the JS-injected meta — never
  un-noindexed by this zone.

## Phase status

Phase 1 (rendering foundation + crawlability + noindex integrity) is complete:
static homepage, `<Seo>`/`<JsonLd>`/`BaseLayout`, routing boundary, robots +
`/sb/*` noindex. Metadata/sitemap/structured-data hardening (Phase 2), Sanity
models (Phase 3), launch content (Phase 4), GEO + measurement (Phase 5),
validation tests (Phase 6), and CI/deploy (Phase 7) follow. `@sanity/*`,
`@astrojs/react`, and `@astrojs/sitemap` are scaffolded but only lightly wired
until their phases.
