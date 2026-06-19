// @ts-check
import { defineConfig } from "astro/config"
import tailwind from "@astrojs/tailwind"
import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"

// Canonical/OG/sitemap base. `PUBLIC_SITE_URL` is the single source of truth for
// the marketing origin; default keeps local builds working without env wiring.
const site = process.env.PUBLIC_SITE_URL ?? "http://localhost:4321"

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
    // Sitemap integration is wired here in Phase 1; route *filtering* (exclude
    // /p/*, /sb/*, app routes) is finalised in Phase 2.
    sitemap(),
  ],
})
