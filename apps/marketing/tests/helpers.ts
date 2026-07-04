// Shared helpers for the Phase-6 validation suite (issue #18).
//
// The dist-parsing tests target the routes a bare build (no Sanity creds)
// actually emits: the homepage + the five content hubs. These are the
// "always-indexable" marketing surfaces — they exist in-repo and don't depend
// on authored content, so they're the right contract to gate in CI. Sanity
// detail pages (/guides/<slug> etc.) are covered by component/unit tests.
import { readFileSync, existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"
import { parseHTML } from "linkedom"

const here = dirname(fileURLToPath(import.meta.url))
export const MARKETING_ROOT = resolve(here, "..")
export const REPO_ROOT = resolve(MARKETING_ROOT, "..", "..")
export const DIST = resolve(MARKETING_ROOT, "dist")

/**
 * Indexable routes a credential-free build emits, keyed by route path → the
 * built HTML file. Every entry here must be in the sitemap and carry complete,
 * unique metadata; the detail (Sanity-backed) routes are intentionally absent
 * because they have no content to build in CI.
 */
export const INDEXABLE_ROUTES: Record<string, string> = {
  "/": "index.html",
  "/use-cases": "use-cases/index.html",
  "/guides": "guides/index.html",
  "/templates": "templates/index.html",
  "/compare": "compare/index.html",
  "/demos": "demos/index.html",
  "/legal/retention": "legal/retention/index.html",
}

/** Route paths that MUST NOT appear in the sitemap or be Astro-built pages. */
export const FORBIDDEN_SITEMAP_PREFIXES = [
  "/p/",
  "/p",
  "/sb/",
  "/sb",
  "/dashboard",
  "/workspace",
  "/settings",
  "/billing",
  "/auth",
  "/assets",
]

export function readDist(relPath: string): string {
  const full = resolve(DIST, relPath)
  if (!existsSync(full)) {
    throw new Error(
      `Expected built file missing: dist/${relPath}. Did 'astro build' run? (globalSetup)`,
    )
  }
  return readFileSync(full, "utf8")
}

export function readRepo(relPath: string): string {
  return readFileSync(resolve(REPO_ROOT, relPath), "utf8")
}

export function readMarketing(relPath: string): string {
  return readFileSync(resolve(MARKETING_ROOT, relPath), "utf8")
}

/** Parse a built HTML file into a queryable document. */
export function parseDoc(html: string): Document {
  const { document } = parseHTML(html)
  return document as unknown as Document
}

/** All built indexable HTML docs, keyed by route path. */
export function allIndexableDocs(): Array<{ route: string; doc: Document; html: string }> {
  return Object.entries(INDEXABLE_ROUTES).map(([route, file]) => {
    const html = readDist(file)
    return { route, doc: parseDoc(html), html }
  })
}

/** Extract every JSON-LD payload from a parsed doc (flattening @graph if used). */
export function extractJsonLd(doc: Document): Record<string, unknown>[] {
  const blocks = Array.from(
    doc.querySelectorAll('script[type="application/ld+json"]'),
  )
  const out: Record<string, unknown>[] = []
  for (const block of blocks) {
    const parsed = JSON.parse(block.textContent || "{}")
    const nodes = Array.isArray(parsed) ? parsed : [parsed]
    for (const node of nodes) {
      if (node && typeof node === "object" && Array.isArray((node as any)["@graph"])) {
        out.push(...(node as any)["@graph"])
      } else {
        out.push(node)
      }
    }
  }
  return out
}

export function metaContent(doc: Document, selector: string): string | null {
  const el = doc.querySelector(selector)
  return el ? el.getAttribute("content") : null
}
