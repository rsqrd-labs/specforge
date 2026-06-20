// AC: Sitemap — includes only indexable routes; EXCLUDES /p/*, /sb/*, and app
// routes. Also the "no orphaned routes" guard: every built indexable page is
// present in the sitemap (reachable + discoverable).
import { describe, it, expect } from "vitest"
import { readDist, INDEXABLE_ROUTES, FORBIDDEN_SITEMAP_PREFIXES } from "./helpers"
import { absoluteUrl } from "../src/consts"

function sitemapLocs(): string[] {
  // @astrojs/sitemap emits an index → sitemap-0.xml. Read the leaf.
  const xml = readDist("sitemap-0.xml")
  return Array.from(xml.matchAll(/<loc>([^<]+)<\/loc>/g)).map((m) => m[1])
}

describe("sitemap", () => {
  const locs = sitemapLocs()
  const paths = locs.map((u) => new URL(u).pathname.replace(/\/$/, "") || "/")

  it("emits a sitemap index pointing at the leaf sitemap", () => {
    const index = readDist("sitemap-index.xml")
    expect(index).toMatch(/sitemap-0\.xml/)
  })

  it("lists every built indexable route (no orphans)", () => {
    for (const route of Object.keys(INDEXABLE_ROUTES)) {
      expect(paths).toContain(route)
    }
  })

  it("lists ONLY indexable routes — no extras", () => {
    const expected = new Set(Object.keys(INDEXABLE_ROUTES))
    for (const p of paths) {
      expect(expected.has(p)).toBe(true)
    }
  })

  it("excludes /p/*, /sb/*, and all SPA app routes", () => {
    for (const loc of locs) {
      const path = new URL(loc).pathname
      for (const forbidden of FORBIDDEN_SITEMAP_PREFIXES) {
        expect(path.startsWith(forbidden)).toBe(false)
      }
    }
  })

  it("uses absolute production URLs on the canonical origin", () => {
    expect(locs).toContain(absoluteUrl("/"))
    for (const loc of locs) {
      expect(() => new URL(loc)).not.toThrow()
      expect(loc.startsWith("http")).toBe(true)
    }
  })
})
