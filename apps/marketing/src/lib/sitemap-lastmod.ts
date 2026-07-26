// Per-page sitemap `<lastmod>` sourced from Sanity `_updatedAt` (T-7.5, issue #18
// Phase 7). Before this, every route shared the build timestamp — a weak
// freshness signal that never changes when a document is actually edited.
//
// This deliberately does NOT reuse `getSeoPages`/`getGuides`/etc. from
// `./sanity.ts`. Astro's config file is bundled and evaluated outside the
// normal Vite pipeline, so `import.meta.env.PUBLIC_*` (populated by Vite's
// `define` transform, which is what `sanity.ts` reads) is not reliably defined
// there. This module reads `process.env` directly instead — the same guard
// `astro.config.mjs` already uses for `PUBLIC_SITE_URL` — which works
// identically whether it's imported from the Astro/Vite pipeline or from
// `astro.config.mjs` itself.
import { createClient } from "@sanity/client"

const LASTMOD_DOC_TYPES = ["seoPage", "guide", "templatePage", "demoPage"] as const
type LastmodDocType = (typeof LASTMOD_DOC_TYPES)[number]

export interface LastmodRow {
  _type: LastmodDocType
  /** Only present on `seoPage` rows. */
  section?: "use-case" | "comparison" | "landing" | null
  slug: string | null
  lastmod: string | null
}

/**
 * The route path a lastmod row corresponds to, mirroring the path helpers in
 * `lib/sanity.ts` (`guidePath`, `templatePath`, `demoPath`, `seoPagePath`).
 * Returns `null` when the row can't be mapped to a fixed indexable route —
 * that document's route keeps the build-time `lastmod` fallback instead.
 */
export function pathForLastmodRow(row: LastmodRow): string | null {
  if (!row.slug) return null
  switch (row._type) {
    case "guide":
      return `/guides/${row.slug}`
    case "templatePage":
      return `/templates/${row.slug}`
    case "demoPage":
      return `/demos/${row.slug}`
    case "seoPage":
      if (row.section === "comparison") return `/compare/${row.slug}`
      if (row.section === "use-case") return `/use-cases/${row.slug}`
      // "landing" seoPages resolve to an arbitrary top-level slug
      // (`seoPagePath("landing", slug)` => `/${slug}`) that this row alone
      // can't be told apart from a non-content route — skip rather than guess.
      return null
    default:
      return null
  }
}

/** Pure: rows -> path -> ISO lastmod. Slugs are unique per document type, so
 * there's no meaningful collision to resolve. */
export function buildLastmodMap(rows: LastmodRow[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const row of rows) {
    const path = pathForLastmodRow(row)
    if (path && row.lastmod) map.set(path, row.lastmod)
  }
  return map
}

function isSanityConfiguredForBuild(): boolean {
  return (process.env.PUBLIC_SANITY_PROJECT_ID ?? "").trim().length > 0
}

/**
 * Fetches `_updatedAt` for every published, routable document. Returns an
 * empty map when Sanity is unconfigured (CI, local builds without creds) or on
 * any fetch error — the sitemap always has the build-time fallback to drop
 * back to, so a transient Sanity outage during a production build degrades a
 * freshness signal rather than failing the whole marketing deploy.
 */
export async function fetchLastmodMap(): Promise<Map<string, string>> {
  if (!isSanityConfiguredForBuild()) return new Map()
  try {
    const client = createClient({
      projectId: process.env.PUBLIC_SANITY_PROJECT_ID as string,
      dataset: process.env.PUBLIC_SANITY_DATASET ?? "production",
      apiVersion: process.env.PUBLIC_SANITY_API_VERSION ?? "2024-10-01",
      useCdn: false,
    })
    const rows = await client.fetch<LastmodRow[]>(
      `*[_type in $types && defined(slug.current)] {
        _type, section, "slug": slug.current, "lastmod": _updatedAt
      }`,
      { types: LASTMOD_DOC_TYPES },
    )
    return buildLastmodMap(rows)
  } catch (err) {
    console.warn(
      "[sitemap-lastmod] Sanity fetch failed; sitemap will fall back to build-time lastmod.",
      err,
    )
    return new Map()
  }
}
