// @ts-check
import { defineConfig } from "astro/config"
import tailwind from "@astrojs/tailwind"
import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"

// Canonical/OG/sitemap base. `PUBLIC_SITE_URL` is the single source of truth for
// the marketing origin; default keeps local builds working without env wiring.
// Vercel sets VERCEL_ENV=production for production builds only (preview
// deploys get "preview") — a production build with the var unset or pointed
// at localhost would silently ship localhost canonicals/OG tags/sitemap
// entries (issue #18 defect 2), so fail loudly instead (T-2.2).
const rawSiteUrl = process.env.PUBLIC_SITE_URL
if (
  process.env.VERCEL_ENV === "production" &&
  (!rawSiteUrl || /localhost|127\.0\.0\.1/.test(rawSiteUrl))
) {
  throw new Error(
    `PUBLIC_SITE_URL must be an absolute production origin; got ${rawSiteUrl ?? "<unset>"}. ` +
      "Canonicals, OG tags, and the sitemap would ship localhost URLs.",
  )
}
const site = rawSiteUrl ?? "http://localhost:4321"

// SPA-owned + public-artifact route prefixes that must NEVER appear in the
// marketing sitemap (issue #18, Phase 2). These aren't Astro pages, so they
// can't reach the sitemap anyway — this filter makes the boundary explicit and
// testable, so a future stray Astro route can never leak /p/* or /sb/* (which
// stay noindex to protect user data) or an app route into the indexable set.
const SITEMAP_EXCLUDED_PREFIXES = [
  "/p", // public shared specs (noindex)
  "/sb", // public storyboards (noindex)
  "/dashboard",
  "/workspace",
  "/settings",
  "/billing",
  "/auth",
  "/assets",
]

/** @param {string} pathname */
function isSitemapExcluded(pathname) {
  return SITEMAP_EXCLUDED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  )
}

// https://astro.build/config
export default defineConfig({
  site,
  // Static output: every indexable route ships real, crawlable HTML — the whole
  // point of the marketing zone (issue #18, Phase 1).
  output: "static",
  // Both URL forms resolve; the canonical signal is what aligns surfaces. Every
  // `<link rel="canonical">`/`og:url`/internal link derives from
  // `absoluteUrl(path)`: no trailing slash on content routes, a single "/" on the
  // root. The sitemap must agree (a canonical-vs-sitemap slash mismatch is a
  // self-inflicted duplicate signal), so the serializer below normalizes <loc>
  // to exactly that shape. We DON'T use `trailingSlash: "never"` because the
  // sitemap integration re-applies it *after* serialize, stripping even the
  // root's slash and breaking the home canonical match (issue #18, Phase 4).
  trailingSlash: "ignore",
  integrations: [
    // Reuses the frontend Tailwind config (Modern Indica tokens) — see
    // tailwind.config.mjs. applyBaseStyles:false because the ported landing CSS
    // (src/styles/global.css) owns the base reset already.
    tailwind({ applyBaseStyles: false }),
    react(),
    // Indexable-only sitemap (issue #18, Phase 2). `filter` drops the SPA-owned
    // and noindex artifact routes. `serialize` sets `lastmod` (the one field
    // crawlers actually act on — Google ignores changefreq/priority as ranking
    // signals) and a light homepage priority. `lastmod` is passthrough-first so
    // Phase 3/4 can supply per-page Sanity `_updatedAt` dates, falling back to
    // build time only when a page carries none.
    sitemap({
      filter: (page) => !isSitemapExcluded(new URL(page).pathname),
      serialize: (item) => {
        const isHome = new URL(item.url).pathname === "/"
        // Match <loc> to the canonical exactly: the site root keeps its single
        // trailing slash (canonical is `absoluteUrl("/")` → ".../"), every other
        // route has none. `trailingSlash: "never"` strips even the root, so add
        // it back for home; strip any trailing slash elsewhere.
        const url = isHome
          ? item.url.replace(/\/?$/, "/")
          : item.url.replace(/\/$/, "")
        return {
          ...item,
          url,
          priority: isHome ? 1.0 : 0.7,
          lastmod: item.lastmod ?? new Date().toISOString(),
        }
      },
    }),
  ],
})
