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
