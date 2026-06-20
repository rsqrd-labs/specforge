// AC: Metadata completeness — every indexable route has unique
// title/description/canonical/OG/Twitter; no duplicate titles or descriptions;
// H1 present; CTA present; no placeholder copy. (No-orphan / sitemap coverage
// lives in sitemap.test.ts.)
//
// SEO rationale: duplicate titles/descriptions cannot rank distinct pages and
// signal thin/templated content; a missing or non-absolute canonical risks
// duplicate-URL dilution; the entity description must never leak in as a meta
// default (that would make un-overridden pages pass with identical copy and
// quietly defeat this very gate — see seo.ts / consts.ts).
import { describe, it, expect } from "vitest"
import { allIndexableDocs, metaContent } from "./helpers"
import { ENTITY_DESCRIPTION, SITE_URL } from "../src/consts"

const PLACEHOLDER_PATTERNS = [
  /lorem ipsum/i,
  /\bTODO\b/,
  /\bFIXME\b/,
  /\bplaceholder\b/i,
  /\bYOUR[_ ]?(TITLE|DESCRIPTION|TEXT)\b/i,
  /\bxxx+\b/i,
]

const MIN_TITLE_LENGTH = 15
const MAX_TITLE_LENGTH = 70
const MIN_DESCRIPTION_LENGTH = 50
const MAX_DESCRIPTION_LENGTH = 220

const docs = allIndexableDocs()

describe("metadata completeness (per route)", () => {
  for (const { route, doc } of docs) {
    describe(`route ${route}`, () => {
      const title = doc.querySelector("title")?.textContent?.trim() ?? ""
      const description = metaContent(doc, 'meta[name="description"]') ?? ""
      const canonical = doc.querySelector('link[rel="canonical"]')?.getAttribute("href") ?? ""

      it("has a substantive title", () => {
        expect(title.length).toBeGreaterThanOrEqual(MIN_TITLE_LENGTH)
        expect(title.length).toBeLessThanOrEqual(MAX_TITLE_LENGTH)
      })

      it("has a substantive meta description", () => {
        // Lower bound guards against thin/empty descriptions; the upper bound
        // is a generous runaway-content guard (Google truncates SERP display
        // near ~160, but over-long authored copy is a soft issue, not a gate).
        expect(description.length).toBeGreaterThanOrEqual(MIN_DESCRIPTION_LENGTH)
        expect(description.length).toBeLessThanOrEqual(MAX_DESCRIPTION_LENGTH)
      })

      it("has an absolute canonical on the production origin matching its route", () => {
        expect(canonical.startsWith(SITE_URL)).toBe(true)
        const path = new URL(canonical).pathname.replace(/\/$/, "") || "/"
        expect(path).toBe(route)
      })

      it("carries complete Open Graph tags", () => {
        expect(metaContent(doc, 'meta[property="og:title"]')).toBeTruthy()
        expect(metaContent(doc, 'meta[property="og:description"]')).toBeTruthy()
        expect(metaContent(doc, 'meta[property="og:type"]')).toBeTruthy()
        expect(metaContent(doc, 'meta[property="og:url"]')).toBeTruthy()
        const ogImage = metaContent(doc, 'meta[property="og:image"]') ?? ""
        expect(ogImage.startsWith("http")).toBe(true)
      })

      it("carries complete Twitter card tags", () => {
        expect(metaContent(doc, 'meta[name="twitter:card"]')).toBeTruthy()
        expect(metaContent(doc, 'meta[name="twitter:title"]')).toBeTruthy()
        expect(metaContent(doc, 'meta[name="twitter:description"]')).toBeTruthy()
        const twImage = metaContent(doc, 'meta[name="twitter:image"]') ?? ""
        expect(twImage.startsWith("http")).toBe(true)
      })

      it("has an indexable robots directive", () => {
        const robots = metaContent(doc, 'meta[name="robots"]') ?? ""
        expect(robots).toMatch(/index/)
        expect(robots).not.toMatch(/noindex/)
      })

      it("has a sign-in CTA", () => {
        const hasCta = Array.from(doc.querySelectorAll("a")).some((a) =>
          (a.getAttribute("href") ?? "").includes("/auth/google"),
        )
        expect(hasCta).toBe(true)
      })

      it("contains no placeholder copy in title or description", () => {
        for (const pat of PLACEHOLDER_PATTERNS) {
          expect(title).not.toMatch(pat)
          expect(description).not.toMatch(pat)
        }
      })

      it("does not reuse the shared ENTITY_DESCRIPTION as its meta description", () => {
        // The entity snippet belongs in body/JSON-LD only — never as the meta
        // description (would defeat the uniqueness gate). See consts.ts.
        expect(description).not.toBe(ENTITY_DESCRIPTION)
      })
    })
  }
})

describe("no orphaned routes — every page is reachable via internal links", () => {
  // The sitemap covers "in sitemap"; this covers the other half of the AC
  // ("every page reachable"). A page only in the sitemap is weakly discoverable
  // and earns no internal relevance signal — orphaned in the link graph is the
  // property that actually matters for SEO. Hub nav (SiteHeader/SiteFooter) must
  // link every hub from every page, and every page must link home.
  const HUBS = ["/use-cases", "/guides", "/templates", "/compare", "/demos"]

  for (const { route, doc } of docs) {
    it(`${route} links to home and every content hub`, () => {
      const hrefs = Array.from(doc.querySelectorAll("a")).map(
        (a) => a.getAttribute("href") ?? "",
      )
      expect(hrefs.some((h) => h === "/" || h === ""), `${route} missing home link`).toBe(true)
      for (const hub of HUBS) {
        expect(
          hrefs.some((h) => h === hub || h === `${hub}/`),
          `${route} missing nav link to ${hub}`,
        ).toBe(true)
      }
    })
  }
})

describe("metadata uniqueness (across routes)", () => {
  it("has no duplicate titles", () => {
    const titles = docs.map(({ doc }) => doc.querySelector("title")?.textContent?.trim() ?? "")
    expect(new Set(titles).size).toBe(titles.length)
  })

  it("has no duplicate meta descriptions", () => {
    const descs = docs.map(({ doc }) => metaContent(doc, 'meta[name="description"]') ?? "")
    expect(new Set(descs).size).toBe(descs.length)
  })

  it("has no duplicate canonical URLs", () => {
    const canon = docs.map(
      ({ doc }) => doc.querySelector('link[rel="canonical"]')?.getAttribute("href") ?? "",
    )
    expect(new Set(canon).size).toBe(canon.length)
  })
})
