// AC: robots.txt — does NOT block / or the content hubs; DOES disallow /p/ and
// /sb/; references the sitemap. Asserted on the built dist robots.txt (the
// authoritative apex policy) and the in-repo source.
import { describe, it, expect } from "vitest"
import { readDist, readMarketing } from "./helpers"

function parseDisallows(robots: string): string[] {
  return robots
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => /^Disallow:/i.test(l))
    .map((l) => l.replace(/^Disallow:\s*/i, "").trim())
}

describe("marketing robots.txt", () => {
  const built = readDist("robots.txt")
  const source = readMarketing("public/robots.txt")

  for (const [label, robots] of [
    ["built dist", built],
    ["repo source", source],
  ] as const) {
    describe(label, () => {
      const disallows = parseDisallows(robots)

      it("disallows /p/ and /sb/ (artifact noindex guard)", () => {
        expect(disallows).toContain("/p/")
        expect(disallows).toContain("/sb/")
      })

      it("does NOT disallow / or the content hubs", () => {
        // A bare `Disallow: /` would block the whole marketing zone.
        expect(disallows).not.toContain("/")
        for (const hub of ["/use-cases", "/guides", "/templates", "/compare", "/demos"]) {
          expect(disallows.some((d) => d === hub || d === `${hub}/`)).toBe(false)
        }
        // Allow directive present for the open crawl policy.
        expect(robots).toMatch(/Allow:\s*\/\s*$/m)
      })

      it("references the sitemap", () => {
        expect(robots).toMatch(/^Sitemap:\s*https?:\/\/\S+sitemap/im)
      })
    })
  }
})
