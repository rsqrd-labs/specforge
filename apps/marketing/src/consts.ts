// Shared marketing-zone constants. Single source of truth for site identity,
// canonical base, the OAuth entry point, and the standardized Thought2Build entity
// description used across SEO/GEO surfaces (issue #18).

// Defense-in-depth mirror of the astro.config.mjs production guard (T-2.2).
// In today's build order, Astro always loads and evaluates astro.config.mjs
// before any page module reaches consts.ts, so that guard's identical check
// throws first in practice — verified in origin.test.ts, whose two failing
// cases both stack-trace back to astro.config.mjs, never here. This copy
// exists so SITE_URL can never silently compute to a localhost value if the
// config-level guard is ever weakened, removed, or bypassed by a future
// Astro/Vite build-order change — not because it is independently reachable
// today. Reading `process.env` directly is safe only because this module has
// no client-side consumers (no React island imports consts.ts) — it is
// evaluated exclusively during Astro's server-side static build.
const rawSiteUrl = import.meta.env.PUBLIC_SITE_URL
if (
  process.env.VERCEL_ENV === "production" &&
  (!rawSiteUrl || /localhost|127\.0\.0\.1/.test(rawSiteUrl))
) {
  throw new Error(
    `PUBLIC_SITE_URL must be an absolute production origin; got ${rawSiteUrl ?? "<unset>"}. ` +
      "Canonicals, OG tags, and the sitemap would ship localhost URLs.",
  )
}

/** Canonical origin for the marketing zone. No trailing slash. */
export const SITE_URL = (rawSiteUrl ?? "http://localhost:4321").replace(/\/+$/, "")

/**
 * Backend origin that owns the OAuth start endpoint. The "Sign in with Google"
 * CTA links to `${API_URL}/auth/google`, mirroring the SPA Landing button
 * (frontend Landing.tsx → `${VITE_API_URL}/auth/google`).
 */
export const API_URL = (
  import.meta.env.PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "")

/** Where the Google sign-in CTA points. */
export const SIGN_IN_URL = `${API_URL}/auth/google`

export const SITE_NAME = "Thought2Build"

/**
 * Standardized entity language (issue #18, Phase 4). Use this one snippet
 * everywhere the product is defined so answer engines see consistent framing.
 */
export const ENTITY_DESCRIPTION =
  "Thought2Build is an AI spec-to-build workspace that turns rough product ideas into structured SPEC, PLAN, HARNESS, and TASKS artifacts."

/**
 * Public profiles that verify the Thought2Build entity (schema.org `sameAs` on the
 * Organization node — issue #18, GEO). Answer engines use these to disambiguate
 * "Thought2Build" from other uses of the name and to ground the entity, so every URL
 * MUST be a real, live profile the org controls — a dead or wrong link is worse
 * than none. Left empty, no `sameAs` is emitted (see organizationSchema()).
 *
 * TODO(launch): add the real profiles before go-live, e.g.
 *   "https://github.com/<org>", "https://x.com/<handle>",
 *   "https://www.linkedin.com/company/<slug>", "https://www.crunchbase.com/organization/<slug>".
 */
export const SAME_AS: readonly string[] = []

/** Absolute-URL helper for canonical/OG/sitemap concerns. */
export function absoluteUrl(path = "/"): string {
  return new URL(path, `${SITE_URL}/`).href
}

/**
 * The marketing content hubs (issue #18, Phase 4). Single source of truth for
 * the header/footer navigation, so every hub is reachable from every page —
 * the Phase-6 "no orphaned routes" guard. Order is intentional (use-cases and
 * guides lead the keyword clusters: spec-to-build, coding-agent handoff).
 */
export const CONTENT_HUBS: ReadonlyArray<{
  label: string
  path: string
  blurb: string
}> = [
  {
    label: "Use cases",
    path: "/use-cases",
    blurb: "Turn a rough idea into specs, tests, and tasks for a given workflow.",
  },
  {
    label: "Guides",
    path: "/guides",
    blurb: "How to write specs, hand off to coding agents, and ship from a plan.",
  },
  {
    label: "Templates",
    path: "/templates",
    blurb: "Starter PRD, spec, and plan templates you can generate and adapt.",
  },
  {
    label: "Comparisons",
    path: "/compare",
    blurb: "How Thought2Build compares to other spec, PRD, and planning tools.",
  },
  {
    label: "Demos",
    path: "/demos",
    blurb: "Real first-party examples: one idea expanded into four build artifacts.",
  },
]
