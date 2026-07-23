// AC: Structured data — JSON-LD validates for each supported type. Two layers:
//   1. The site-wide graph as actually emitted in the built homepage HTML
//      (Organization + SoftwareApplication, @id-connected).
//   2. The pure builders for the content-type schemas that only appear on
//      Sanity-backed detail pages (FAQPage, BreadcrumbList, Article) — validated
//      directly since those pages don't build without content in CI.
import { describe, it, expect } from "vitest"
import { readDist, parseDoc, extractJsonLd } from "./helpers"
import { SITE_URL } from "../src/consts"
import {
  organizationSchema,
  softwareApplicationSchema,
  faqPageSchema,
  breadcrumbListSchema,
  articleSchema,
  ORGANIZATION_ID,
  SOFTWARE_ID,
} from "../src/lib/seo"

function isSchemaOrg(node: Record<string, unknown>): boolean {
  return node["@context"] === "https://schema.org" && typeof node["@type"] === "string"
}

describe("structured data — emitted in built homepage", () => {
  const doc = parseDoc(readDist("index.html"))
  const nodes = extractJsonLd(doc)
  const byType = (t: string) => nodes.find((n) => n["@type"] === t)

  it("emits valid JSON-LD (parses, all schema.org)", () => {
    expect(nodes.length).toBeGreaterThan(0)
    for (const n of nodes) expect(isSchemaOrg(n)).toBe(true)
  })

  it("includes an Organization entity with a stable @id", () => {
    const org = byType("Organization")
    expect(org).toBeTruthy()
    expect(org!["@id"]).toBe(ORGANIZATION_ID)
    expect(org!.name).toBeTruthy()
    expect(String(org!.url)).toMatch(/^https?:\/\//)
  })

  it("includes a SoftwareApplication entity linked to the Organization", () => {
    const app = byType("SoftwareApplication")
    expect(app).toBeTruthy()
    expect(app!["@id"]).toBe(SOFTWARE_ID)
    expect(app!.applicationCategory).toBeTruthy()
    // Connected graph: publisher references the Organization @id.
    expect((app!.publisher as Record<string, unknown>)["@id"]).toBe(ORGANIZATION_ID)
  })

  it("uses the production canonical origin in entity URLs", () => {
    const org = byType("Organization")!
    expect(String(org.url).startsWith(SITE_URL)).toBe(true)
  })
})

describe("structured data — pure builders (detail-page schemas)", () => {
  it("organizationSchema / softwareApplicationSchema are valid + connected", () => {
    expect(isSchemaOrg(organizationSchema())).toBe(true)
    const app = softwareApplicationSchema()
    expect(isSchemaOrg(app)).toBe(true)
    expect((app.publisher as Record<string, unknown>)["@id"]).toBe(ORGANIZATION_ID)
    expect((app.offers as Record<string, unknown>)["@type"]).toBe("Offer")
  })

  it("faqPageSchema builds a valid FAQPage with Question/Answer pairs", () => {
    const schema = faqPageSchema([
      { question: "What is Thought2Build?", answer: "An AI spec-to-build workspace." },
      { question: "Is there a free tier?", answer: "Yes, 50 starter credits." },
    ])
    expect(schema["@type"]).toBe("FAQPage")
    const main = schema.mainEntity as Record<string, unknown>[]
    expect(main).toHaveLength(2)
    for (const q of main) {
      expect(q["@type"]).toBe("Question")
      expect(q.name).toBeTruthy()
      const ans = q.acceptedAnswer as Record<string, unknown>
      expect(ans["@type"]).toBe("Answer")
      expect(ans.text).toBeTruthy()
    }
  })

  it("breadcrumbListSchema builds positioned ListItems with absolute URLs", () => {
    const schema = breadcrumbListSchema([
      { name: "Home", path: "/" },
      { name: "Guides", path: "/guides" },
      { name: "Spec-to-build", path: "/guides/spec-to-build" },
    ])
    expect(schema["@type"]).toBe("BreadcrumbList")
    const items = schema.itemListElement as Record<string, unknown>[]
    expect(items).toHaveLength(3)
    items.forEach((item, i) => {
      expect(item["@type"]).toBe("ListItem")
      expect(item.position).toBe(i + 1)
      expect(String(item.item)).toMatch(/^https?:\/\//)
    })
  })

  it("articleSchema builds a valid Article linked to the Organization publisher", () => {
    const schema = articleSchema({
      title: "How to hand off a spec to a coding agent",
      description: "A workflow for clean spec-to-agent handoffs.",
      path: "/guides/coding-agent-handoff",
      datePublished: "2026-06-01T00:00:00.000Z",
      dateModified: "2026-06-10T00:00:00.000Z",
    })
    expect(schema["@type"]).toBe("Article")
    expect(schema.headline).toBeTruthy()
    expect(schema.description).toBeTruthy()
    expect(String(schema.url)).toMatch(/^https?:\/\//)
    expect((schema.publisher as Record<string, unknown>)["@id"]).toBe(ORGANIZATION_ID)
    expect(schema.datePublished).toBeTruthy()
    expect(schema.dateModified).toBeTruthy()
  })
})
