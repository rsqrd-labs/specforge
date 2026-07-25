// AC (the critical guard): noindex regression. The new OPEN marketing crawl
// policy must never expose the public generated-artifact routes (/p/* shared
// specs, /sb/* storyboards) to indexing. This test protects user data by
// asserting EVERY layer of the noindex stack is intact:
//
//   1. SPA-zone _headers — X-Robots-Tag: noindex, nofollow on /p/* AND /sb/*
//   2. robots.txt (both marketing apex + SPA-zone copy) — Disallow /p/ + /sb/
//   3. vercel.json — /p/* and /sb/* rewrite to the SPA zone (so the SPA-zone
//      _headers + backend header actually apply; they are NOT Astro pages)
//   4. backend X-Robots-Tag still set on the public artifact responses
//      (belt-and-suspenders; behavior is covered by the backend contract suite,
//      here we assert the source guard didn't get deleted)
//   5. SPA JS-injected <meta robots noindex> on the public views still present
//
// If any layer regresses, this fails — by design.
import { describe, it, expect } from "vitest"
import { readRepo, readDist } from "./helpers"

function blockFor(headers: string, route: string): string {
  // _headers blocks: a path line in column 0, followed by indented directives
  // until the next column-0 line.
  const lines = headers.split("\n")
  const start = lines.findIndex((l) => l.trimEnd() === route)
  expect(start, `missing _headers block for ${route}`).toBeGreaterThanOrEqual(0)
  const body: string[] = []
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].length && !/^\s/.test(lines[i])) break
    body.push(lines[i])
  }
  return body.join("\n")
}

describe("noindex regression — public artifact routes stay non-indexable", () => {
  describe("frontend/public/_headers", () => {
    const headers = readRepo("frontend/public/_headers")

    for (const route of ["/p/*", "/sb/*"]) {
      it(`${route} carries X-Robots-Tag: noindex, nofollow`, () => {
        const block = blockFor(headers, route)
        expect(block).toMatch(/X-Robots-Tag:\s*noindex,\s*nofollow/i)
      })
    }
  })

  describe("robots.txt disallows the artifact routes in BOTH zones", () => {
    // Marketing zone: templated (src/pages/robots.txt.ts, T-2.3), not a
    // static file — assert on the built dist output, which is what actually
    // ships. `frontend/public/robots.txt` is still a plain static file.
    const cases: Array<{ label: string; robots: string }> = [
      { label: "apps/marketing/dist/robots.txt (built)", robots: readDist("robots.txt") },
      { label: "frontend/public/robots.txt", robots: readRepo("frontend/public/robots.txt") },
    ]

    for (const { label, robots } of cases) {
      it(`${label} disallows /p/ and /sb/`, () => {
        expect(robots).toMatch(/^Disallow:\s*\/p\/\s*$/im)
        expect(robots).toMatch(/^Disallow:\s*\/sb\/\s*$/im)
      })
    }
  })

  describe("apps/marketing/vercel.json", () => {
    const vercel = JSON.parse(readRepo("apps/marketing/vercel.json"))
    const rewrites: Array<{ source: string; destination: string }> = vercel.rewrites ?? []

    for (const prefix of ["/p/", "/sb/"]) {
      it(`rewrites ${prefix}* to the SPA zone (so its noindex headers apply)`, () => {
        const match = rewrites.find((r) => r.source.startsWith(prefix))
        expect(match, `no ${prefix}* rewrite`).toBeTruthy()
        // Destination is an absolute SPA-zone URL, not served by Astro.
        expect(match!.destination).toMatch(/^https?:\/\//)
      })
    }

    it("does NOT rewrite the marketing content hubs (they are Astro pages)", () => {
      for (const hub of ["/use-cases", "/guides", "/templates", "/compare", "/demos"]) {
        expect(rewrites.some((r) => r.source.startsWith(hub))).toBe(false)
      }
    })
  })

  describe("backend belt-and-suspenders X-Robots-Tag source guard", () => {
    // Behavioral coverage is in harness/tests/backend (phase14/phase23); here
    // we only assert the source header wasn't removed under the new policy.
    for (const file of ["backend/routers/public.py", "backend/routers/storyboards.py"]) {
      it(`${file} still sets X-Robots-Tag noindex`, () => {
        const src = readRepo(file)
        expect(src).toMatch(/X-Robots-Tag/i)
        expect(src).toMatch(/noindex/i)
      })
    }
  })

  describe("SPA JS-injected noindex meta still present", () => {
    for (const file of [
      "frontend/src/pages/PublicWorkspaceView.tsx",
      "frontend/src/pages/StoryboardPublic.tsx",
    ]) {
      it(`${file} injects a noindex robots meta`, () => {
        const src = readRepo(file)
        expect(src).toMatch(/noindex/i)
      })
    }
  })
})
