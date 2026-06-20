// @ts-check
import { defineConfig } from "astro/config"
import tailwind from "@astrojs/tailwind"
import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"

// Canonical/OG/sitemap base. `PUBLIC_SITE_URL` is the single source of truth for
// the marketing origin; default keeps local builds working without env wiring.
const site = process.env.PUBLIC_SITE_URL ?? "http://localhost:4321"

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
        return {
          ...item,
          priority: isHome ? 1.0 : 0.7,
          lastmod: item.lastmod ?? new Date().toISOString(),
        }
      },
    }),
  ],
})
