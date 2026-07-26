// AC: plan docs/SEO_INDEXING_REMEDIATION_PLAN.md §9 T-6.3 — each of the five
// content hubs must be "a real landing page (300+ words of orientation, a
// curated list, cross-links)", not a 100-word stub. This guards the floor
// mechanically so a future edit can't silently shrink a hub back to a stub.
import { describe, it, expect } from "vitest"
import { CONTENT_HUBS } from "../src/consts"
import { readDist, parseDoc } from "./helpers"

const HUB_FILES: Record<string, string> = {
  "/use-cases": "use-cases/index.html",
  "/guides": "guides/index.html",
  "/templates": "templates/index.html",
  "/compare": "compare/index.html",
  "/demos": "demos/index.html",
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length
}

describe("content hubs are real landing pages (T-6.3)", () => {
  for (const [hubPath, file] of Object.entries(HUB_FILES)) {
    describe(hubPath, () => {
      const doc = parseDoc(readDist(file))

      it("carries at least 300 words of orientation copy", () => {
        const section = doc.querySelector(".hub-orientation")
        expect(section, `${hubPath} is missing .hub-orientation`).toBeTruthy()
        expect(wordCount(section!.textContent || "")).toBeGreaterThanOrEqual(300)
      })

      it("cross-links to every sibling hub, and not to itself", () => {
        const links = Array.from(doc.querySelectorAll(".hub-crosslinks a")).map((a) =>
          a.getAttribute("href"),
        )
        const siblingPaths = CONTENT_HUBS.map((h) => h.path).filter((p) => p !== hubPath)
        expect(links.sort()).toEqual(siblingPaths.sort())
        expect(links).not.toContain(hubPath)
      })
    })
  }
})
