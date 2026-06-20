// AC: Measurement readiness — analytics + GSC config present; the AI-referral
// channel is defined (the five answer engines, with bing isolated); the
// synthetic-query audit checklist is committed. Plus the load-bearing posture:
// analytics is inert/opt-in so default builds ship no tracking JS, and the
// classifier is pure + drift-free (single source of truth shared with tests).
import { describe, it, expect } from "vitest"
import { existsSync } from "node:fs"
import { resolve } from "node:path"
import { readMarketing, MARKETING_ROOT } from "./helpers"
import {
  classifyReferrer,
  AI_ENGINE_REFERRERS,
  AI_REFERRAL_EVENT,
  analyticsEnabled,
} from "../src/lib/analytics"

describe("AI-referral channel definition (single source of truth)", () => {
  const engines = AI_ENGINE_REFERRERS.map((e) => e.engine)

  it("covers the five required answer engines in the core AI channel", () => {
    for (const required of ["chatgpt", "perplexity", "gemini", "copilot", "claude"]) {
      const entry = AI_ENGINE_REFERRERS.find((e) => e.engine === required)
      expect(entry, `missing engine ${required}`).toBeTruthy()
      expect(entry!.channel).toBe("ai_answer_engine")
    }
    expect(engines.length).toBeGreaterThanOrEqual(5)
  })

  it("isolates bing.com into a separate mixed bucket (keeps the AI metric clean)", () => {
    const bing = AI_ENGINE_REFERRERS.find((e) => e.engine === "bing")
    expect(bing).toBeTruthy()
    expect(bing!.channel).toBe("mixed_search_ai")
  })

  it("names a custom event for classified referrals", () => {
    expect(AI_REFERRAL_EVENT).toBeTruthy()
  })
})

describe("classifyReferrer (pure, host-suffix based)", () => {
  it("maps answer-engine hosts to their core channel", () => {
    expect(classifyReferrer("https://chatgpt.com/")?.engine).toBe("chatgpt")
    expect(classifyReferrer("https://www.perplexity.ai/search")?.engine).toBe("perplexity")
    expect(classifyReferrer("https://gemini.google.com/app")?.engine).toBe("gemini")
    expect(classifyReferrer("https://claude.ai/chat")?.channel).toBe("ai_answer_engine")
  })

  it("classifies bing.com into the mixed bucket, including subdomains", () => {
    expect(classifyReferrer("https://www.bing.com/search")?.channel).toBe("mixed_search_ai")
    expect(classifyReferrer("https://cn.bing.com/")?.engine).toBe("bing")
  })

  it("returns null for classic search and non-engine / invalid referrers", () => {
    expect(classifyReferrer("https://www.google.com/search?q=x")).toBeNull()
    expect(classifyReferrer("https://news.ycombinator.com/")).toBeNull()
    expect(classifyReferrer("")).toBeNull()
    expect(classifyReferrer(null)).toBeNull()
    expect(classifyReferrer("not a url")).toBeNull()
  })
})

describe("analytics posture (opt-in, inert by default)", () => {
  it("ships disabled by default (no PUBLIC_ANALYTICS_ENABLED in CI)", () => {
    // The gate is `=== "true"`; absent/blank env ⇒ false ⇒ zero tracking JS.
    expect(analyticsEnabled).toBe(false)
  })

  it("the analytics module gates the island + GSC meta explicitly", () => {
    const src = readMarketing("src/lib/analytics.ts")
    expect(src).toMatch(/PUBLIC_ANALYTICS_ENABLED/)
    expect(src).toMatch(/PUBLIC_GSC_VERIFICATION|gscVerification/)
  })

  it("the Analytics island is gated on analyticsEnabled", () => {
    const island = readMarketing("src/components/Analytics.astro")
    expect(island).toMatch(/analyticsEnabled/)
  })

  it("BaseLayout wires the Analytics island and the gated GSC meta", () => {
    const layout = readMarketing("src/layouts/BaseLayout.astro")
    expect(layout).toMatch(/<Analytics\s*\/>/)
    expect(layout).toMatch(/google-site-verification/)
  })
})

describe("synthetic-query audit artifact is committed", () => {
  const queries = JSON.parse(readMarketing("measurement/synthetic-queries.json"))

  it("has docs + a runnable audit script + a runs dir", () => {
    for (const f of [
      "measurement/README.md",
      "measurement/SYNTHETIC_QUERY_AUDIT.md",
      "measurement/audit.mjs",
    ]) {
      expect(existsSync(resolve(MARKETING_ROOT, f)), `missing ${f}`).toBe(true)
    }
    expect(existsSync(resolve(MARKETING_ROOT, "measurement/runs"))).toBe(true)
  })

  it("defines clusters mapped to content hubs with target queries", () => {
    const clusters = Object.values(queries.clusters) as Array<Record<string, any>>
    expect(clusters.length).toBeGreaterThan(0)
    for (const c of clusters) {
      expect(c.hub).toMatch(/^\/(use-cases|guides|templates|compare|demos)$/)
      expect(Array.isArray(c.queries)).toBe(true)
      expect(c.queries.length).toBeGreaterThan(0)
    }
  })

  it("targets the answer engines, including those in the referral channel", () => {
    const engineKeys: string[] = queries.engines.map((e: any) => e.key)
    for (const required of ["chatgpt", "perplexity", "gemini", "copilot", "claude"]) {
      expect(engineKeys).toContain(required)
    }
  })
})
