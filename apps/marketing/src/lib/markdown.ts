// Build-time Markdown → HTML for the curated, first-party demo artifacts
// (issue #18, Phase 4). The four demo fields (spec/plan/harness/tasks Markdown)
// are authored by us in the studio and rendered to real, crawlable HTML so the
// demo pages ship actual headings/lists/code for SEO + answer engines rather
// than opaque <pre> blobs.
//
// Defense-in-depth: raw HTML embedded in the Markdown is dropped (the renderer's
// `html` hook returns ""). Curated artifacts contain no raw HTML, but the issue's
// demo-sanitization requirement ("no unsafe generated artifacts") points here, so
// we neutralize it at the boundary rather than trusting the content gate alone.
import { marked, Renderer } from "marked"

const renderer = new Renderer()
// Drop raw/inline HTML blocks. Arg is ignored so this is robust across marked
// versions (string-arg vs token-arg signatures both resolve to "").
renderer.html = () => ""

/** Render trusted, first-party Markdown to sanitized HTML. Synchronous. */
export function renderMarkdown(md: string | undefined | null): string {
  if (!md || !md.trim()) return ""
  return marked.parse(md, { renderer, async: false }) as string
}
