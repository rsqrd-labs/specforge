// AC: /llms.txt (T-7.3, issue #18 Phase 7) — a curated map for LLM crawlers per
// https://llmstxt.org, generated from the same content/consts that build the
// marketing pages so it can never hand-drift out of sync.
import { describe, it, expect } from "vitest"
import { readDist } from "./helpers"
import { SITE_NAME, ENTITY_DESCRIPTION, CONTENT_HUBS, absoluteUrl } from "../src/consts"

describe("/llms.txt", () => {
  const body = readDist("llms.txt")

  it("is served as plain text with an H1 naming the site and the entity description", () => {
    expect(body).toMatch(new RegExp(`^# ${SITE_NAME}`))
    expect(body).toContain(ENTITY_DESCRIPTION)
  })

  it("links the homepage with an absolute production URL", () => {
    expect(body).toContain(`(${absoluteUrl("/")})`)
  })

  it("links every content hub (no orphaned hub, no invented one)", () => {
    for (const hub of CONTENT_HUBS) {
      expect(body).toContain(`(${absoluteUrl(hub.path)})`)
      expect(body).toContain(hub.blurb)
    }
  })

  it("degrades to hub-only listings when Sanity has no published documents", () => {
    // The CI/local build in globalSetup runs with no Sanity project id, so no
    // per-document rows should appear — only the five "<Hub> hub" link lines.
    const docLines = body.split("\n").filter((line) => line.startsWith("- ["))
    expect(docLines).toHaveLength(1 + CONTENT_HUBS.length) // Home + one row per hub
    for (const line of docLines.slice(1)) {
      expect(line).toMatch(/^- \[.+ hub\]/)
    }
  })

  it("is not present in the sitemap (it is a machine-readable index, not an indexable page)", () => {
    const sitemap = readDist("sitemap-0.xml")
    expect(sitemap).not.toContain("llms.txt")
  })
})
