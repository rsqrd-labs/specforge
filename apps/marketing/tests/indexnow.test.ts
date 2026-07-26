// AC: plan §8 T-5.3 — the IndexNow submission script's sitemap-parsing logic
// must correctly flatten a real `@astrojs/sitemap` `sitemapindex` → `urlset`
// chain, and must not choke on an already-flat `urlset`. Pure unit tests, no
// network and no dependency on the built `dist/` — the fixtures below are
// deliberately shaped like real Astro sitemap output.
import { describe, it, expect } from "vitest"
import { extractLocs, isSitemapIndex, collectSitemapUrls } from "../scripts/submit-indexnow.mjs"

const SITEMAP_INDEX_XML = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://thought2build.com/sitemap-0.xml</loc></sitemap>
</sitemapindex>`

const URLSET_XML = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://thought2build.com/</loc></url>
<url><loc>https://thought2build.com/guides</loc></url>
<url><loc>https://thought2build.com/compare</loc></url>
</urlset>`

describe("extractLocs", () => {
  it("extracts <loc> values from a urlset", () => {
    expect(extractLocs(URLSET_XML)).toEqual([
      "https://thought2build.com/",
      "https://thought2build.com/guides",
      "https://thought2build.com/compare",
    ])
  })

  it("extracts <loc> values from a sitemapindex", () => {
    expect(extractLocs(SITEMAP_INDEX_XML)).toEqual(["https://thought2build.com/sitemap-0.xml"])
  })

  it("returns an empty list for a urlset with no entries", () => {
    expect(extractLocs('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>')).toEqual([])
  })
})

describe("isSitemapIndex", () => {
  it("detects a sitemapindex document", () => {
    expect(isSitemapIndex(SITEMAP_INDEX_XML)).toBe(true)
  })

  it("does not mistake a urlset for a sitemapindex", () => {
    expect(isSitemapIndex(URLSET_XML)).toBe(false)
  })
})

describe("collectSitemapUrls", () => {
  it("follows a sitemapindex one level down and flattens to page URLs", async () => {
    const fakeFetch = async (url: string) => {
      if (url === "https://thought2build.com/sitemap-index.xml") {
        return { ok: true, text: async () => SITEMAP_INDEX_XML } as Response
      }
      if (url === "https://thought2build.com/sitemap-0.xml") {
        return { ok: true, text: async () => URLSET_XML } as Response
      }
      throw new Error(`unexpected fetch: ${url}`)
    }

    const urls = await collectSitemapUrls("https://thought2build.com/sitemap-index.xml", fakeFetch)
    expect(urls).toEqual([
      "https://thought2build.com/",
      "https://thought2build.com/guides",
      "https://thought2build.com/compare",
    ])
  })

  it("returns the urlset's own URLs when the entry point is not an index", async () => {
    const fakeFetch = async () => ({ ok: true, text: async () => URLSET_XML }) as unknown as Response
    const urls = await collectSitemapUrls("https://thought2build.com/sitemap-0.xml", fakeFetch)
    expect(urls).toHaveLength(3)
  })

  it("throws if the sitemap index itself is unreachable", async () => {
    const fakeFetch = async () => ({ ok: false, status: 404, text: async () => "" }) as unknown as Response
    await expect(collectSitemapUrls("https://thought2build.com/sitemap-index.xml", fakeFetch)).rejects.toThrow(
      "404",
    )
  })

  it("throws if a child sitemap referenced by the index is unreachable", async () => {
    const fakeFetch = async (url: string) => {
      if (url === "https://thought2build.com/sitemap-index.xml") {
        return { ok: true, text: async () => SITEMAP_INDEX_XML } as Response
      }
      return { ok: false, status: 500, text: async () => "" } as Response
    }
    await expect(collectSitemapUrls("https://thought2build.com/sitemap-index.xml", fakeFetch)).rejects.toThrow(
      "500",
    )
  })
})
