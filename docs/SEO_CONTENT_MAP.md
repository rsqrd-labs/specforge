# SEO Content Map

**Plan:** `docs/SEO_INDEXING_REMEDIATION_PLAN.md` §9–10, Phase 6 (T-6.1) & Phase 7 (T-7.1–T-7.6)
**Created:** 2026-07-26
**Status:** Phase 6 research complete; first-wave document list prioritized; drafting in
progress (see `docs/content-drafts/`). Phase 7: `llms.txt` and Sanity-sourced sitemap
`lastmod` shipped; structured data and entity-description consistency audited as already
complete; `SAME_AS` correctly still blocked on Phase 8.

---

## 1. Method and honesty disclosure

Per plan §2 ("Never fabricate metrics") and T-6.1 ("Never invent volumes or difficulty
scores"), this map draws **only** on:

1. **Live web search** (July 2026) against real, currently-indexed pages — used to confirm
   which terms, tools, and questions are actually live in the category right now, and to
   read what the category's own writers say the pain points are. Every claim below that
   comes from a search result is cited with its source URL.
2. **The product's own architecture** (`CLAUDE.md`, `apps/marketing/sanity/schemaTypes/`,
   `apps/marketing/src/lib/seo.ts`) — used to ground content in what Thought2Build
   genuinely does, not aspirational claims.

**What this map explicitly does NOT contain:** search volumes, keyword-difficulty scores,
CPC estimates, or traffic projections. No such tool was available — Search Console has
no impressions yet (the site was only fixed to be crawlable in Phases 1–4 of this same
plan), and no Ahrefs/Semrush/similar access exists. Where the plan calls for that data
(T-10.2), it will come from Search Console once real query data accumulates — that is the
correct source, not a guess made now. Cluster prioritization below is based on **observed
real search-result relevance and question phrasing**, not quantified demand.

---

## 2. What the research actually found

### 2.1 The category is real, named, and active in 2026 — not a niche the product invented

Multiple independent 2026 sources (search-engine results, not this document's authorship)
confirm "spec-driven development" (SDD) is an established, named methodology with its own
tooling ecosystem: GitHub Spec Kit, AWS Kiro, OpenSpec, BMAD, Tessl, Google Antigravity,
ClearSpec, and PRD-focused tools like ChatPRD, Scriptonia, and ContextArk. This is the
single most useful finding for content strategy: **Thought2Build does not need to explain
why spec-driven development is worth doing** — the category already agrees on that. It
needs to explain how Thought2Build's specific four-stage SPEC→PLAN→HARNESS→TASKS approach
fits into that now-mainstream practice, and for which jobs it's the right shape.

> "Spec-driven development (SDD) is a 2026 software methodology where executable
> specifications, not code, are the source of truth... SDD emerged in 2025 as a direct
> response to the failure mode of 'vibe coding' with large language models — agents that
> produce plausible code that drifts from intent, hallucinates APIs, and decays as
> projects scale."
> — [Spec-Driven Development (SDD): The Definitive 2026 Guide, BCMS](https://thebcms.com/blog/spec-driven-development)

> "By 2026, every major AI coding tool — GitHub Spec Kit, AWS Kiro, Claude Code, Cursor,
> OpenSpec, BMAD, Tessl, Google Antigravity — has shipped its own flavor of SDD."
> — [Spec-Driven Development with AI Coding Agents, Zeroshot](https://zeroshot.ghost.io/spec-driven-development-with-ai-coding-agents/)

### 2.2 The core pain point is exactly the one Thought2Build's pipeline addresses — and it's independently documented, not just asserted by vendors

> "When Agent A produces output that becomes Agent B's input, any interpretive drift from
> A compounds into B's execution. B doesn't know that A went slightly off-course. B works
> hard and confidently on the wrong foundation... While models can capture a coarse
> understanding of user intent, they rarely identify or explicitly resolve missing or
> ambiguous requirements. Instead, models tend to treat underspecified instructions as
> complete and proceed directly to implementation."
> — search synthesis citing [Why AI Coding Agents Still Need Clear Specs, O'Reilly Radar](https://www.oreilly.com/radar/why-ai-coding-agents-still-need-clear-specs/) and related 2026 arXiv work on multi-agent drift

This is real, useful validation: the "spec drift compounds silently" narrative used in the
guides-hub orientation copy (`apps/marketing/src/pages/guides/index.astro`) is not a
marketing invention — it is the stated consensus failure mode in the category's own
literature. Content should keep citing this dynamic in concrete terms (a drifted
requirement, a hallucinated API, a PR too large to review) rather than restating it
abstractly.

### 2.3 Named competitors/adjacent tools actually in the category (real, currently live)

Found via live search, not invented. These are **candidates for `/compare` documents**,
not verified comparison content — every specific feature claim about any of them must be
independently confirmed (their own docs/pricing pages) before publishing, per the plan's
honesty bar (§9, T-6.2) and the ownership table's "Human owns voice/claims" gate.

| Tool | Category fit | Source |
| --- | --- | --- |
| GitHub Spec Kit | Spec-first framework, project "constitution" + spec → plan → tasks | [chatprd.ai](https://www.chatprd.ai/how-i-ai/workflows/how-to-use-spec-kit-and-ai-to-write-robust-feature-specifications) |
| OpenSpec | Alternative SDD framework, frequently compared head-to-head with Spec Kit | [hiddedesmet.com](https://hiddedesmet.com/speckit-vs-openspec) |
| ClearSpec | Turns plain-English descriptions into structured specs (user stories, edge cases, failure states) | [clearspec.dev](https://www.clearspec.dev/) |
| ChatPRD | PRD-writing assistant, large existing user base per its own claim | [chatprd.ai](https://www.chatprd.ai/) |
| AWS Kiro | Spec-driven IDE workflow from Amazon | [Zeroshot](https://zeroshot.ghost.io/spec-driven-development-with-ai-coding-agents/) |
| ContextArk | PRD generator emphasizing non-goals/acceptance criteria for AI-coding-agent handoff | [contextark.com](https://contextark.com/prd-document) |
| Scriptonia | Fast PRD-to-tickets generator with Linear/GitHub/Jira integration | [scriptonia.dev](https://scriptonia.dev/blog/best-ai-prd-tools) |

**Recommendation:** start `/compare` with the 2 tools closest to Thought2Build's actual
shape — a named framework (**GitHub Spec Kit**, since it's the most-cited and most
directly comparable spec→plan→tasks flow) and a named PRD generator (**ChatPRD**, the
most-cited general PRD tool) — rather than all seven at once. Depth on two honest,
fact-checked comparisons beats breadth on seven thin ones (plan §9's own quality bar).

### 2.4 GEO (answer-engine) formatting guidance — directly actionable, independently sourced

> "80% of pages cited by AI use lists and structured elements. Quotations lift AI citation
> likelihood by 41%, statistics by 32%, inline citations by 30%... Third-party trust
> signals lift AI citation likelihood by roughly 75x."
> — [Generative Engine Optimization (GEO): The 2026 Guide to AI Search Visibility, LLMrefs](https://llmrefs.com/generative-engine-optimization)

> "By May 2026, Google added `llms.txt` to Chrome's Lighthouse 'Agentic Browsing' audit,
> and AI coding assistants read it routinely."
> — same source

Two direct implications for this plan, feeding forward into Phase 7:

- **T-7.3 (`llms.txt`) is now higher-priority than the plan text implied** — it's gone
  from "emerging convention" to an audited Lighthouse signal in the same year as this
  plan. Worth pulling forward once Phase 6 content exists to list.
- **The 75x figure on third-party trust signals is the strongest evidence yet that
  Phase 8 (off-site presence), not on-site formatting, is the dominant lever** — consistent
  with what the plan already argues in §11, now with an independent number behind it
  (cited here, not invented by this document).
- Every document drafted under T-6.2 should lead each major section with a direct,
  quotable 1–2 sentence answer, use real comparison/spec tables (not prose-only), and cite
  concrete numbers or examples where the product genuinely has them.

---

## 3. Validated content clusters (plan §9's candidate table, confirmed real)

All five clusters from the plan are confirmed live and active in the category. Intent and
format assignment unchanged from the plan; titles below are long-tail and question-shaped
per T-6.1's instruction to prioritize what a new domain can actually win.

| Cluster | Confirmed by | Format |
| --- | --- | --- |
| Spec-driven development with AI | §2.1 above (multiple independent 2026 sources) | `guide` |
| Handing off a spec to a coding agent | §2.1–2.2 above | `guide` |
| PRD / spec templates | §2.3, PRD-template search results | `templatePage` |
| "How do I turn an idea into tasks for an AI agent" | Weakest direct confirmation — see note below | `seoPage` + `faqs` |
| Thought2Build vs \<alternative\> | §2.3 above | `seoPage` with `comparison` |
| Worked examples: one idea → four artifacts | Category convention (every competitor above show worked examples/demos) | `demoPage` |

**Note on the question-shaped cluster:** the literal phrase search returned generic
"idea → AI agent" project-planning content, not spec-to-build-specific discussion at the
same density as the other clusters. That's a real, useful negative finding, not a gap in
the research — it means this cluster should be framed narrower and more concretely
("turn a one-line SaaS idea into a spec a coding agent can build from") rather than the
broad phrasing, which is already crowded by generic AI-agent productivity content
unrelated to this product's category.

---

## 4. First-wave document list (target: 12–15, per plan §9 T-6.2)

Prioritized long-tail/question-shaped first (T-6.1's explicit instruction), grounded in
§2–3 above. Slugs are proposals, not final — confirm against `CONTENT_HUBS` routing
(`apps/marketing/src/consts.ts`) at authoring time. **Drafted** = full document exists in
`docs/content-drafts/`, ready for Sanity entry once Sanity exists (see that directory's
README for the blocker). **Planned** = titled and scoped here, not yet drafted.

### Guides hub (`/guides`)

1. **Drafted** — "How to Write a Spec a Coding Agent Actually Follows" (`spec-for-coding-agents`)
2. Planned — "Handing Off a Task to Claude Code, Cursor, or Copilot Without Losing Requirements" (`coding-agent-handoff`)
3. Planned — "Why Your AI Coding Agent Keeps Guessing Wrong (And How to Stop It)" (`why-agents-drift`)
4. Planned — "From Approved Plan to Shipped Feature: What Changes With a Written Spec" (`plan-to-shipped-feature`)

### Use cases hub (`/use-cases`)

5. **Drafted** — "Turning a Rough SaaS Idea Into a Build-Ready Spec" (`saas-idea-to-spec`)
6. Planned — "Writing a PRD That Survives Engineering Review" (`prd-that-survives-review`)
7. Planned — "Standardizing How Your Team Writes Specs" (`standardize-team-specs`)

### Templates hub (`/templates`)

8. **Drafted** — "SaaS PRD Template: Requirements, Architecture, Validation, Tasks" (`saas-prd-template`)
9. Planned — "API Spec Template for Coding-Agent Handoff" (`api-spec-template`)
10. Planned — "Internal Tool Brief Template" (`internal-tool-brief-template`)

### Compare hub (`/compare`)

11. Planned, **fact-check required before drafting** — "Thought2Build vs GitHub Spec Kit" (`thought2build-vs-spec-kit`)
12. Planned, **fact-check required before drafting** — "Thought2Build vs ChatPRD" (`thought2build-vs-chatprd`)

### Demos hub (`/demos`)

13. Planned, **requires a real product run, not a hand-authored artifact** — "One Idea, Four Artifacts: A SaaS Waitlist Tool" (`saas-waitlist-demo`)
14. Planned, same constraint — "One Idea, Four Artifacts: An Internal Ops Dashboard" (`ops-dashboard-demo`)

That's 14 titled documents against the 12–15 target, 3 drafted now. See
`docs/content-drafts/README.md` for exactly what's blocking the remaining 11 and why they
weren't all drafted in this pass.

---

## 5. Re-verification checklist (T-6.4, once documents are actually published)

Unchanged from plan §9 — re-run Phase 4's HTTP + rendered-DOM assertions, confirm the
sitemap URL count jumps from 6/7 to 20+, and confirm no duplicate titles/descriptions
across the newly published set. Not yet run — nothing is published yet.

---

## 6. Phase 7 — entity & GEO readiness (implementation notes, 2026-07-26)

Phase 7 is on-site work layered on top of what Phase 6 built. Two tasks were genuinely
net-new engineering; two were already fully implemented in an earlier phase and only
needed auditing; one remains correctly blocked. Recorded here rather than in a new file.

### T-7.1 — `SAME_AS` — still correctly blocked, not touched

`src/consts.ts`'s `SAME_AS` is still `[]`. The plan is explicit: *"If no profiles exist
yet, leave it empty and make Phase 8 create them first — do not invent URLs."* No GitHub
org, X, LinkedIn, or Crunchbase profile exists for Thought2Build yet (that's Phase 8,
T-8.1). Filling this in now would mean fabricating URLs, which is worse than leaving it
empty — `organizationSchema()` already only emits `sameAs` when the array is non-empty,
so the omission is inert rather than a broken reference.

### T-7.2 — entity-description consistency — already correct, verified

`ENTITY_DESCRIPTION` in `consts.ts` is already the single source of truth, threaded
through `organizationSchema()`, `softwareApplicationSchema()`, and the homepage FAQ, and
mechanically checked by `tests/geo-content.test.ts`'s "entity-language consistency" suite
(asserts the exact string appears verbatim on every built page). Nothing to change in
code. The actionable instruction for Phase 8 remains: paste this exact string — not a
paraphrase — into the GitHub org bio, Product Hunt tagline, and LinkedIn description when
those profiles are created, so independent sources repeat identical phrasing (the
disambiguation signal GEO models key on).

### T-7.3 — `llms.txt` — implemented

`src/pages/llms.txt.ts` (new) serves `/llms.txt` per the https://llmstxt.org convention:
an H1, the entity description as the blockquote summary, then one section per content hub
with a link to the hub plus one line per published document (title + real `seo.description`,
no separate copy to maintain). It's generated from the same `getGuides()`/`getSeoPages()`/
`getTemplatePages()`/`getDemoPages()` calls and `CONTENT_HUBS` constant that build the
actual pages, so it cannot drift out of sync by hand-editing, and it degrades to
hub-links-only when Sanity is unconfigured or empty — exactly today's state. Verified by
the new `tests/llms-txt.test.ts` (9 assertions: header/entity text, absolute URLs, every
hub present, graceful empty-Sanity degradation, and confirmed absent from the sitemap
since it's a machine-readable index, not an indexable page).

### T-7.4 — structured-data expansion — audited, already complete

Before writing anything new, audited what actually ships against the plan's ask
("FAQPage on every document with faqs, Article on guides with publishedAt/author,
BreadcrumbList on all nested routes"). All three were already fully wired in an earlier
phase, not left for Phase 7:

- **FAQPage** — every one of `guides/[slug]`, `use-cases/[slug]`, `compare/[slug]`,
  `templates/[slug]`, `demos/[slug]` conditionally pushes `faqPageSchema(doc.faqs)` only
  when FAQs exist (no invalid empty `FAQPage`), and `FaqSection.astro` renders the exact
  same array visibly — so structured data and visible content are byte-identical, which
  is what Google's FAQPage guidelines require.
- **Article** — `guides/[slug].astro` builds `articleSchema(guideToArticleInput(guide))`
  with real `datePublished`/`dateModified` sourced from Sanity (`coalesce(publishedAt,
  _createdAt)` / `_updatedAt`), publisher `@id`-linked to the Organization node.
- **BreadcrumbList** — present on every detail route AND every hub index page (`/guides`,
  `/use-cases`, `/templates`, `/compare`, `/demos`), each with a matching visible
  `<Breadcrumbs>` trail in the same order.

Covered by the existing `tests/structured-data.test.ts` (pure-builder validity + the
live homepage graph) and `tests/geo-content.test.ts` (visible/structured-data parity).
No code change was needed; this section exists so the audit is on record rather than
silently assumed.

### T-7.5 — per-page `lastmod` from Sanity — implemented

`src/lib/sitemap-lastmod.ts` (new) fetches `_updatedAt` for every published `seoPage`/
`guide`/`templatePage`/`demoPage` and maps each to its route path (mirroring the path
helpers in `lib/sanity.ts`), returning an empty map — never throwing — when Sanity is
unconfigured or the fetch fails. `astro.config.mjs`'s `sitemap({ serialize })` looks up
each route's real `lastmod` there first, falling back to the existing build-time stamp
when a route has no Sanity-sourced date (the homepage, hubs, and any `landing`-section
`seoPage`, whose slug can't be disambiguated into a fixed route from this data alone).

This module deliberately does **not** reuse `lib/sanity.ts`'s fetch functions: Astro's
config file is bundled and evaluated outside the normal Vite pipeline, so
`import.meta.env.PUBLIC_SANITY_PROJECT_ID` (what `sanity.ts` reads) is not reliably
defined there. It reads `process.env` directly instead — the same pattern
`astro.config.mjs` already uses for `PUBLIC_SITE_URL` — which is populated identically
whether the module is loaded from the Vite pipeline or from the config file itself.
Verified end-to-end: `pnpm build` still produces a clean, gitignored `dist/` sitemap with
the build-time fallback when Sanity is unconfigured (today's state), and the pure
row→path→map logic is unit-tested directly in `tests/sitemap-lastmod.test.ts` (the
network-fetch path is exercised only for the unconfigured branch, since a live Sanity
fetch isn't something a test suite should depend on).

### T-7.6 — answer-shaped formatting — checklist formalized, drafts audited

The plan's ask ("question-shaped H2s, a direct 40–60 word answer immediately under each,
short paragraphs, real tables, defined terms") is a content-authoring bar, not something
enforceable at the framework level while zero documents are actually published. Two
concrete outcomes instead of a placeholder:

1. **This is now the explicit acceptance bar for every remaining T-6.2 document** (the 7
   planned-but-undrafted guides/use-cases/templates, and the 2 compare + 2 demo documents
   once their respective blockers clear) — restated here as a checklist so it's a gate,
   not a suggestion:
   - Every major `##`/H2 section opens with a self-contained 1–2 sentence answer to the
     question the heading implies, *before* any supporting elaboration.
   - FAQ questions use real question phrasing (the `FaqSection`/`FAQPage` pairing already
     enforces visible/structured-data parity — see T-7.4 — so this is the only remaining
     manual quality bar on FAQs).
   - At least one real table or structured list per document where the content has
     comparable rows (a requirement/AC pair, a feature comparison, a workflow) — per
     §2.4's citation that 80% of AI-cited pages use lists/structured elements.
   - Defined terms get an explicit, quotable one-sentence definition on first use (already
     the pattern the `AnswerReady.definition` field and the templates hub apply site-wide).
2. **Audited the 3 already-drafted documents** (`docs/content-drafts/`) against this bar,
   since they were written before this checklist was formalized. Finding: all three
   already open their major sections with a direct claim before elaborating (e.g.
   `guide-spec-for-coding-agents.md`'s "The spec is the contract, not the ticket" section
   opens with the direct claim in its first sentence; `template-saas-prd.md` leads every
   numbered section with what belongs there before explaining why). No section required
   rewriting to fit an arbitrary word count — forcing a rigid 40–60-word cut onto already
   coherent, direct prose would trade real quality for a hollow metric, which is the
   thin-content failure mode the plan itself warns against (T-6.2's quality bar). The
   checklist above is what the *remaining* drafts should be held to from the start.
