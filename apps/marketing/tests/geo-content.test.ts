// AC: GEO content QA — answer-ready structure present (definition / workflow /
// FAQ / comparison / examples), entity language consistent, and demo
// sanitization (curated demos contain no unsafe generated artifacts).
//
// Why component-level + unit, not full pages: detail routes only build with
// Sanity content (absent in CI), so we (a) render the answer-ready components
// directly via the Astro Container API with fixtures, (b) unit-test the demo
// Markdown sanitization boundary, and (c) assert entity-language consistency on
// the built dist. This is more faithful than a page snapshot — it checks the
// exact contracts answer engines reward.
import { describe, it, expect, beforeAll } from "vitest"
import { experimental_AstroContainer as AstroContainer } from "astro/container"
import AnswerReady from "../src/components/content/AnswerReady.astro"
import FaqSection from "../src/components/content/FaqSection.astro"
import { renderMarkdown } from "../src/lib/markdown"
import { faqPageSchema } from "../src/lib/seo"
import { ENTITY_DESCRIPTION } from "../src/consts"
import { readDist } from "./helpers"

let container: Awaited<ReturnType<typeof AstroContainer.create>>
beforeAll(async () => {
  container = await AstroContainer.create()
})

const FIXTURE = {
  definition:
    "SpecForge is an AI spec-to-build workspace that turns a rough idea into SPEC, PLAN, HARNESS, and TASKS.",
  workflowSteps: [
    { name: "Describe the idea", description: "Paste a rough product idea." },
    { name: "Generate the spec", description: "SpecForge drafts structured requirements." },
    { name: "Hand off to build", description: "Export tasks for engineers or coding agents." },
  ],
  comparison: {
    alternativeName: "A blank doc",
    rows: [
      { feature: "Structured artifacts", specforge: "Yes", alternative: "No" },
      { feature: "Coding-agent handoff", specforge: "Yes", alternative: "Manual" },
    ],
  },
  examples: [
    { title: "SaaS CRUD app", input: "A task tracker", output: "Full SPEC + PLAN + TASKS" },
  ],
}

const FAQS = [
  { question: "What is SpecForge?", answer: "An AI spec-to-build workspace." },
  { question: "Is there a free tier?", answer: "Yes — 50 starter credits to begin." },
]

describe("GEO answer-ready structure renders in answer-engine order", () => {
  it("renders definition → workflow → comparison → examples, in order", async () => {
    const html = await container.renderToString(AnswerReady, { props: FIXTURE })

    // All four answer-ready blocks present.
    expect(html).toContain("answer-definition")
    expect(html).toMatch(/How it works/)
    expect(html).toMatch(/SpecForge vs\./)
    expect(html).toMatch(/Examples/)

    // Order matters for answer engines: direct answer first, then how, then
    // comparison, then examples.
    const iDef = html.indexOf("answer-definition")
    const iWorkflow = html.indexOf("How it works")
    const iComparison = html.indexOf("SpecForge vs.")
    const iExamples = html.indexOf(">Examples<")
    expect(iDef).toBeGreaterThanOrEqual(0)
    expect(iWorkflow).toBeGreaterThan(iDef)
    expect(iComparison).toBeGreaterThan(iWorkflow)
    expect(iExamples).toBeGreaterThan(iComparison)
  })

  it("renders the definition as a direct first-paragraph answer", async () => {
    const html = await container.renderToString(AnswerReady, { props: FIXTURE })
    expect(html).toContain(FIXTURE.definition)
  })

  it("renders the workflow as an ordered list and the comparison as a table", async () => {
    const html = await container.renderToString(AnswerReady, { props: FIXTURE })
    expect(html).toMatch(/<ol[^>]*workflow-list/)
    expect(html).toMatch(/<table[^>]*comparison-table/)
    for (const step of FIXTURE.workflowSteps) expect(html).toContain(step.name)
    for (const row of FIXTURE.comparison.rows) expect(html).toContain(row.feature)
  })

  it("omits absent blocks (no empty scaffolding)", async () => {
    const html = await container.renderToString(AnswerReady, {
      props: { definition: "Just a definition." },
    })
    expect(html).toContain("Just a definition.")
    expect(html).not.toMatch(/How it works/)
    expect(html).not.toMatch(/comparison-table/)
    expect(html).not.toMatch(/example-grid/)
  })
})

describe("FAQ — visible answer byte-matches FAQPage JSON-LD", () => {
  it("renders every visible Q&A with no JavaScript (details/summary)", async () => {
    const html = await container.renderToString(FaqSection, { props: { faqs: FAQS } })
    expect(html).toMatch(/<details/)
    for (const faq of FAQS) {
      expect(html).toContain(faq.question)
      expect(html).toContain(faq.answer)
    }
    expect(html).not.toMatch(/<script/i)
  })

  it("visible answers are identical to the FAQPage structured-data answers", async () => {
    // Google requires the FAQPage markup to match visible content; answer
    // engines extract from the rendered Q&A. Same `faqs` array feeds both.
    const html = await container.renderToString(FaqSection, { props: { faqs: FAQS } })
    const schema = faqPageSchema(FAQS)
    for (const q of schema.mainEntity as Array<Record<string, any>>) {
      expect(html).toContain(q.name)
      expect(html).toContain(q.acceptedAnswer.text)
    }
  })

  it("renders nothing for an empty FAQ list (no invalid empty FAQPage)", async () => {
    const html = await container.renderToString(FaqSection, { props: { faqs: [] } })
    expect(html).not.toMatch(/faq-section/)
  })
})

// Note: this guards the unsafe-HTML boundary (raw tags/handlers/embeds), not
// markdown-syntax links — `[text](url)` survives by design. That's acceptable
// because demos are curated, first-party, and unauthored yet; the renderMarkdown
// boundary is the correct testable sanitization contract for this phase.
describe("demo sanitization — curated artifacts produce no unsafe HTML", () => {
  it("renders real crawlable HTML from Markdown (headings, lists, code)", () => {
    const out = renderMarkdown("## Spec\n\nA requirement.\n\n- one\n- two\n\n`code`")
    expect(out).toMatch(/<h2>/)
    expect(out).toMatch(/<li>/)
    expect(out).toMatch(/<code>/)
  })

  it("drops embedded <script> and inline event-handler HTML", () => {
    const out = renderMarkdown(
      "Intro.\n\n<script>alert('xss')</script>\n\nInline <img src=x onerror=alert(1)> and <b onclick=\"x()\">b</b>.",
    )
    expect(out).not.toMatch(/<script/i)
    expect(out).not.toMatch(/onerror=/i)
    expect(out).not.toMatch(/onclick=/i)
  })

  it("drops raw <iframe>/<object> embeds (no private-link/exfil surface)", () => {
    const out = renderMarkdown(
      "See <iframe src=\"https://evil.example/secret\"></iframe> and <object data=x></object>.",
    )
    expect(out).not.toMatch(/<iframe/i)
    expect(out).not.toMatch(/<object/i)
  })

  it("returns empty string for empty/blank input", () => {
    expect(renderMarkdown("")).toBe("")
    expect(renderMarkdown("   \n  ")).toBe("")
    expect(renderMarkdown(null)).toBe("")
    expect(renderMarkdown(undefined)).toBe("")
  })
})

describe("entity-language consistency", () => {
  it("the standardized entity snippet appears verbatim on every built page", () => {
    for (const file of [
      "index.html",
      "use-cases/index.html",
      "guides/index.html",
      "templates/index.html",
      "compare/index.html",
      "demos/index.html",
    ]) {
      expect(readDist(file)).toContain(ENTITY_DESCRIPTION)
    }
  })
})
