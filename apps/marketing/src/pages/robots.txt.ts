// Thought2Build — authoritative robots policy (served at the apex by the
// marketing zone). The SPA zone's own robots.txt is shadowed at the apex and
// kept only for direct hits on the SPA deployment URL.
//
// Templated (not a static file) so the `Sitemap:` line always matches the
// canonical origin instead of a hardcoded literal that can silently drift
// from a real host change (issue #18 defect 4, T-2.3).
import type { APIRoute } from "astro"
import { absoluteUrl } from "../consts"

export const GET: APIRoute = () =>
  new Response(
    [
      // Marketing/content routes are open to crawlers. Public generated
      // artifacts are intentionally noindex; this Disallow is the PRIMARY
      // document-level guard for compliant crawlers (the SPA-zone _headers
      // X-Robots-Tag and JS-injected meta are the secondary layers):
      //   /p/  — public shared specs        /sb/ — public storyboards
      "User-agent: *",
      "Allow: /",
      "Disallow: /p/",
      "Disallow: /sb/",
      "",
      // @astrojs/sitemap emits a sitemap index (sitemap-index.xml →
      // sitemap-0.xml), filtered to indexable routes only (the /p/* and /sb/*
      // artifact routes and the SPA app routes are excluded in
      // astro.config.mjs).
      `Sitemap: ${absoluteUrl("/sitemap-index.xml")}`,
      "",
    ].join("\n"),
    { headers: { "Content-Type": "text/plain; charset=utf-8" } },
  )
