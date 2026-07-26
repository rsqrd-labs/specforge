// AC: sitemap per-page lastmod (T-7.5, issue #18 Phase 7) — the pure
// row-to-path mapping and map-building logic used by astro.config.mjs to give
// each route its real Sanity `_updatedAt` instead of a shared build timestamp.
// The network-fetching half (`fetchLastmodMap`) is exercised for the
// unconfigured (CI) branch only — a live Sanity fetch isn't something this
// suite can or should depend on.
import { describe, it, expect } from "vitest"
import {
  pathForLastmodRow,
  buildLastmodMap,
  fetchLastmodMap,
  type LastmodRow,
} from "../src/lib/sitemap-lastmod"

describe("pathForLastmodRow", () => {
  it("maps guide, templatePage, and demoPage rows to their fixed routes", () => {
    expect(pathForLastmodRow({ _type: "guide", slug: "spec-for-agents", lastmod: null })).toBe(
      "/guides/spec-for-agents",
    )
    expect(pathForLastmodRow({ _type: "templatePage", slug: "saas-prd", lastmod: null })).toBe(
      "/templates/saas-prd",
    )
    expect(pathForLastmodRow({ _type: "demoPage", slug: "waitlist", lastmod: null })).toBe(
      "/demos/waitlist",
    )
  })

  it("routes seoPage rows by section", () => {
    expect(
      pathForLastmodRow({ _type: "seoPage", section: "use-case", slug: "saas-idea", lastmod: null }),
    ).toBe("/use-cases/saas-idea")
    expect(
      pathForLastmodRow({ _type: "seoPage", section: "comparison", slug: "vs-spec-kit", lastmod: null }),
    ).toBe("/compare/vs-spec-kit")
  })

  it("returns null for a landing seoPage (ambiguous top-level slug) and for a missing slug", () => {
    expect(
      pathForLastmodRow({ _type: "seoPage", section: "landing", slug: "pricing", lastmod: null }),
    ).toBeNull()
    expect(pathForLastmodRow({ _type: "guide", slug: null, lastmod: null })).toBeNull()
  })
})

describe("buildLastmodMap", () => {
  it("builds a path -> ISO lastmod map, skipping rows with no lastmod or no path", () => {
    const rows: LastmodRow[] = [
      { _type: "guide", slug: "a", lastmod: "2026-07-01T00:00:00.000Z" },
      { _type: "templatePage", slug: "b", lastmod: "2026-07-02T00:00:00.000Z" },
      { _type: "guide", slug: "c", lastmod: null },
      { _type: "seoPage", section: "landing", slug: "d", lastmod: "2026-07-03T00:00:00.000Z" },
    ]
    const map = buildLastmodMap(rows)
    expect(map.get("/guides/a")).toBe("2026-07-01T00:00:00.000Z")
    expect(map.get("/templates/b")).toBe("2026-07-02T00:00:00.000Z")
    expect(map.has("/guides/c")).toBe(false)
    expect(map.size).toBe(2)
  })

  it("returns an empty map for an empty input", () => {
    expect(buildLastmodMap([]).size).toBe(0)
  })
})

describe("fetchLastmodMap", () => {
  it("returns an empty map when Sanity is unconfigured, without throwing", async () => {
    const prevProjectId = process.env.PUBLIC_SANITY_PROJECT_ID
    delete process.env.PUBLIC_SANITY_PROJECT_ID
    try {
      const map = await fetchLastmodMap()
      expect(map.size).toBe(0)
    } finally {
      if (prevProjectId !== undefined) process.env.PUBLIC_SANITY_PROJECT_ID = prevProjectId
    }
  })
})
