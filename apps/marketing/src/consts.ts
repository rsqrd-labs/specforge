// Shared marketing-zone constants. Single source of truth for site identity,
// canonical base, the OAuth entry point, and the standardized SpecForge entity
// description used across SEO/GEO surfaces (issue #18).

/** Canonical origin for the marketing zone. No trailing slash. */
export const SITE_URL = (
  import.meta.env.PUBLIC_SITE_URL ?? "http://localhost:4321"
).replace(/\/+$/, "")

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

export const SITE_NAME = "SpecForge"

/**
 * Standardized entity language (issue #18, Phase 4). Use this one snippet
 * everywhere the product is defined so answer engines see consistent framing.
 */
export const ENTITY_DESCRIPTION =
  "SpecForge is an AI spec-to-build workspace that turns rough product ideas into structured SPEC, PLAN, HARNESS, and TASKS artifacts."

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
    blurb: "How SpecForge compares to other spec, PRD, and planning tools.",
  },
  {
    label: "Demos",
    path: "/demos",
    blurb: "Real first-party examples: one idea expanded into four build artifacts.",
  },
]
