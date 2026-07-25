// AC (T-2.4, issue #18): production origin correctness. This is the
// regression test for defect 2 (PUBLIC_SITE_URL silently falling back to
// localhost in a production build) and defect 4 (a hardcoded Sitemap: origin
// drifting from the real canonical) ever becoming possible again.
//
// Runs its OWN isolated `astro build` with an explicit production
// PUBLIC_SITE_URL — the shared dist/ built by tests/setup/global-setup.ts
// deliberately stays on the localhost default so the rest of the suite is
// credential/env-independent, so it cannot be reused here. The input origin
// carries a trailing slash on purpose: it must be stripped everywhere
// (consts.ts's `.replace(/\/+$/, "")`), so this also proves the "no trailing
// slash" contract, not just the "not localhost" one.
import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { execFileSync } from "node:child_process"
import { mkdtempSync, rmSync, readFileSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { parseHTML } from "linkedom"
import { MARKETING_ROOT, INDEXABLE_ROUTES } from "./helpers"

const INPUT_SITE_URL = "https://thought2build.com/"
const PRODUCTION_ORIGIN = "https://thought2build.com"

let outDir: string

function readOut(relPath: string): string {
  return readFileSync(join(outDir, relPath), "utf8")
}

beforeAll(() => {
  outDir = mkdtempSync(join(tmpdir(), "t2b-marketing-origin-"))
  // Mirror global-setup.ts: strip Sanity creds so this build stays pinned to
  // the credential-free contract (homepage + 5 hubs + the legal page).
  const env: NodeJS.ProcessEnv = { ...process.env, PUBLIC_SITE_URL: INPUT_SITE_URL }
  delete env.PUBLIC_SANITY_PROJECT_ID
  delete env.PUBLIC_SANITY_DATASET
  execFileSync("pnpm", ["exec", "astro", "build", "--outDir", outDir], {
    cwd: MARKETING_ROOT,
    stdio: "inherit",
    env,
  })
}, 60_000)

afterAll(() => {
  if (outDir && existsSync(outDir)) {
    rmSync(outDir, { recursive: true, force: true })
  }
})

describe("production origin correctness (T-2.4)", () => {
  it("PRODUCTION_ORIGIN fixture is https with no trailing slash (sanity check on the test itself)", () => {
    expect(PRODUCTION_ORIGIN).toMatch(/^https:\/\//)
    expect(PRODUCTION_ORIGIN.endsWith("/")).toBe(false)
  })

  it("every <loc> in the sitemap starts with the production origin, no doubled slash", () => {
    const xml = readOut("sitemap-0.xml")
    const locs = Array.from(xml.matchAll(/<loc>([^<]+)<\/loc>/g)).map((m) => m[1])
    expect(locs.length).toBeGreaterThan(0)
    for (const loc of locs) {
      expect(loc.startsWith(PRODUCTION_ORIGIN)).toBe(true)
      expect(loc).not.toContain("localhost")
      // Doubled slash from a stray trailing slash in the input, excluding the
      // "https://" scheme separator itself.
      expect(loc.replace(/^https?:\/\//, "")).not.toMatch(/\/\//)
    }
  })

  it("robots.txt Sitemap: origin matches the production origin (defect 4)", () => {
    const robots = readOut("robots.txt")
    const match = robots.match(/^Sitemap:\s*(\S+)/im)
    expect(match, "no Sitemap: line found in robots.txt").toBeTruthy()
    expect(match![1].startsWith(PRODUCTION_ORIGIN)).toBe(true)
    expect(match![1]).not.toContain("localhost")
  })

  it("no emitted HTML has localhost in canonical, og:url, or og:image", () => {
    for (const file of Object.values(INDEXABLE_ROUTES)) {
      const html = readOut(file)
      const { document } = parseHTML(html)
      const canonical = document.querySelector('link[rel="canonical"]')?.getAttribute("href") ?? ""
      const ogUrl = document.querySelector('meta[property="og:url"]')?.getAttribute("content") ?? ""
      const ogImage = document.querySelector('meta[property="og:image"]')?.getAttribute("content") ?? ""

      expect(canonical, `${file} canonical`).toBeTruthy()
      expect(canonical, `${file} canonical`).not.toContain("localhost")
      expect(canonical.startsWith(PRODUCTION_ORIGIN), `${file} canonical origin`).toBe(true)

      expect(ogUrl, `${file} og:url`).not.toContain("localhost")
      expect(ogImage, `${file} og:image`).not.toContain("localhost")
      if (ogUrl) expect(ogUrl.startsWith(PRODUCTION_ORIGIN), `${file} og:url origin`).toBe(true)
      if (ogImage) expect(ogImage.startsWith(PRODUCTION_ORIGIN), `${file} og:image origin`).toBe(true)
    }
  })
})

// AC (T-2.2, issue #18): the production build guard itself. The two tests
// above prove the OUTPUT is correct given a good PUBLIC_SITE_URL; until now
// the "a bad production build throws instead of shipping localhost" behavior
// (astro.config.mjs / consts.ts) had only been checked by hand in a terminal
// (see docs/SEO_INDEXING_VERIFICATION.md's Phase 2 section) — no automated
// test would have caught a future regression that silently dropped the
// guard. Each case gets its own throwaway --outDir so a build that (correctly)
// fails before emitting anything never collides with another run.
function attemptProductionBuild(publicSiteUrl: string | undefined): { status: number | null; stderr: string } {
  const dir = mkdtempSync(join(tmpdir(), "t2b-marketing-guard-"))
  try {
    const env: NodeJS.ProcessEnv = { ...process.env, VERCEL_ENV: "production" }
    if (publicSiteUrl === undefined) {
      delete env.PUBLIC_SITE_URL
    } else {
      env.PUBLIC_SITE_URL = publicSiteUrl
    }
    delete env.PUBLIC_SANITY_PROJECT_ID
    delete env.PUBLIC_SANITY_DATASET
    try {
      execFileSync("pnpm", ["exec", "astro", "build", "--outDir", dir], {
        cwd: MARKETING_ROOT,
        encoding: "utf8",
        env,
      })
      return { status: 0, stderr: "" }
    } catch (err) {
      const e = err as { status: number | null; stderr: string }
      return { status: e.status, stderr: e.stderr }
    }
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe("production build guard (T-2.2)", () => {
  it("VERCEL_ENV=production with PUBLIC_SITE_URL unset fails the build", () => {
    const result = attemptProductionBuild(undefined)
    expect(result.status).not.toBe(0)
    expect(result.stderr).toContain("PUBLIC_SITE_URL must be an absolute production origin")
  }, 30_000)

  it("VERCEL_ENV=production with PUBLIC_SITE_URL=localhost fails the build", () => {
    const result = attemptProductionBuild("http://localhost:4321")
    expect(result.status).not.toBe(0)
    expect(result.stderr).toContain("PUBLIC_SITE_URL must be an absolute production origin")
  }, 30_000)

  it("VERCEL_ENV=production with a real PUBLIC_SITE_URL succeeds", () => {
    const result = attemptProductionBuild(INPUT_SITE_URL)
    expect(result.status).toBe(0)
  }, 30_000)
})
