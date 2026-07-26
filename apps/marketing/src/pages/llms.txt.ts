// /llms.txt — a curated, plain-text map of the site for LLM crawlers and
// coding-agent browsing tools (T-7.3, issue #18 Phase 7). Convention:
// https://llmstxt.org. As of May 2026, Chrome Lighthouse's "Agentic Browsing"
// audit checks for this file, and AI coding assistants read it routinely
// (docs/SEO_CONTENT_MAP.md §2.4) — cheap, additive, no risk.
//
// Generated from the same Sanity content that builds the marketing pages
// (never hand-maintained), so it can't drift out of sync with what's actually
// published. With Sanity unconfigured (CI, or before Phase 6 content lands)
// every content list is empty and the file still degrades gracefully to just
// the hub links — the same pattern the hub `index.astro` pages use.
import type { APIRoute } from "astro"
import { SITE_NAME, ENTITY_DESCRIPTION, CONTENT_HUBS, absoluteUrl } from "../consts"
import {
  getGuides,
  getSeoPages,
  getTemplatePages,
  getDemoPages,
  guidePath,
  seoPagePath,
  templatePath,
  demoPath,
} from "../lib/sanity"

interface ListedDoc {
  title: string
  path: string
  description: string
}

function hubBlurb(hubPath: string): string {
  return CONTENT_HUBS.find((hub) => hub.path === hubPath)?.blurb ?? ""
}

function renderSection(heading: string, hubPath: string, docs: ListedDoc[]): string {
  const lines = [`## ${heading}`, "", `- [${heading} hub](${absoluteUrl(hubPath)}): ${hubBlurb(hubPath)}`]
  for (const doc of docs) {
    lines.push(`- [${doc.title}](${absoluteUrl(doc.path)}): ${doc.description}`)
  }
  return lines.join("\n")
}

export const GET: APIRoute = async () => {
  const [guides, useCases, comparisons, templates, demos] = await Promise.all([
    getGuides(),
    getSeoPages("use-case"),
    getSeoPages("comparison"),
    getTemplatePages(),
    getDemoPages(),
  ])

  const sections = [
    renderSection(
      "Guides",
      "/guides",
      guides.map((g) => ({ title: g.heading, path: guidePath(g.slug), description: g.seo.description })),
    ),
    renderSection(
      "Use cases",
      "/use-cases",
      useCases.map((d) => ({
        title: d.heading,
        path: seoPagePath("use-case", d.slug),
        description: d.seo.description,
      })),
    ),
    renderSection(
      "Templates",
      "/templates",
      templates.map((t) => ({ title: t.heading, path: templatePath(t.slug), description: t.seo.description })),
    ),
    renderSection(
      "Comparisons",
      "/compare",
      comparisons.map((d) => ({
        title: d.heading,
        path: seoPagePath("comparison", d.slug),
        description: d.seo.description,
      })),
    ),
    renderSection(
      "Demos",
      "/demos",
      demos.map((d) => ({ title: d.heading, path: demoPath(d.slug), description: d.seo.description })),
    ),
  ]

  const body = [
    `# ${SITE_NAME}`,
    "",
    `> ${ENTITY_DESCRIPTION}`,
    "",
    "A four-stage pipeline — SPEC, PLAN, HARNESS, TASKS — turns a one-line product " +
      "idea into a build-ready, human-reviewed artifact set for handoff to an " +
      "engineer or a coding agent.",
    "",
    "## Product",
    "",
    `- [Home](${absoluteUrl("/")}): overview, the four-stage pipeline, and free-credit sign-up.`,
    "",
    sections.join("\n\n"),
    "",
  ].join("\n")

  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } })
}
