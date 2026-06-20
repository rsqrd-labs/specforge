// AC: Static-HTML render — build apps/marketing, assert indexable routes emit
// non-empty <h1>, <title>, and real body content in the static output (NOT an
// empty root div). This is the foundational crawlability guarantee: an answer
// engine or Googlebot that does not execute JS must still see the page.
import { describe, it, expect } from "vitest"
import { allIndexableDocs, INDEXABLE_ROUTES } from "./helpers"

describe("static-HTML render", () => {
  const docs = allIndexableDocs()

  it("emits an HTML file for every indexable route", () => {
    expect(docs.length).toBe(Object.keys(INDEXABLE_ROUTES).length)
  })

  for (const { route, doc, html } of allIndexableDocs()) {
    describe(`route ${route}`, () => {
      it("has exactly one non-empty <h1>", () => {
        const h1s = doc.querySelectorAll("h1")
        expect(h1s.length).toBe(1)
        expect((h1s[0].textContent || "").trim().length).toBeGreaterThan(0)
      })

      it("has a non-empty <title>", () => {
        const title = doc.querySelector("title")?.textContent?.trim() ?? ""
        expect(title.length).toBeGreaterThan(0)
      })

      it("renders real body content, not an empty SPA root div", () => {
        // The SPA shell is `<div id="root"></div>`; static marketing HTML must
        // carry substantive prerendered text instead.
        expect(html).not.toMatch(/<div id="root">\s*<\/div>/)
        const bodyText = (doc.querySelector("main")?.textContent ?? doc.body?.textContent ?? "")
          .replace(/\s+/g, " ")
          .trim()
        expect(bodyText.length).toBeGreaterThan(200)
      })

      it("has a <main> landmark", () => {
        expect(doc.querySelector("main")).not.toBeNull()
      })
    })
  }
})
