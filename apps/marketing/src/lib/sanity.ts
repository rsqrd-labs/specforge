// Typed Sanity fetch layer for the marketing zone (issue #18, Phase 3).
//
// This is the *data layer* only — the content models live in the standalone
// studio (`apps/marketing/sanity/`) and the page templates that consume these
// queries are Phase 4. Three contracts make Phase 3 correct rather than merely
// plausible:
//
//   1. Graceful degradation. CI (and any local build without Sanity creds)
//      runs `astro build` with no project configured. The client is created
//      *lazily* and only when `isSanityConfigured` — `createClient({projectId:""})`
//      throws at construction, so a top-level client would brick the first
//      Phase-4 route. Every fetch short-circuits to `[]`/`null` when unconfigured,
//      so `getStaticPaths` yields zero pages and the build stays green.
//
//   2. Output types compose into the existing Phase-2 consumers. The GROQ
//      projections are shaped so a `guide` drops straight into `articleSchema`
//      (`ArticleSchemaInput`) and any `faqs` array into `faqPageSchema`
//      (`FaqItem[]`) — no parallel types, no Phase-4 rework. `SanityFaq` is a
//      literal alias of `FaqItem` so assignability is guaranteed by the compiler.
//
//   3. Explicit named projections, never `*[_type=="guide"]{...}` splats. The
//      type↔query alignment is the only thing verifiable in Phase 3 (no routes
//      exercise it at runtime yet), so the projections name every field.
import { createClient, type SanityClient } from "@sanity/client"
import type { ArticleSchemaInput, FaqItem } from "./seo"

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
// projectId + dataset are public values (they appear in every browser request
// to the Sanity API), so PUBLIC_ exposure is correct. A read token is NOT set
// here and must NEVER be PUBLIC_-prefixed: published content on a public dataset
// needs no token at build time.
const PROJECT_ID = import.meta.env.PUBLIC_SANITY_PROJECT_ID ?? ""
const DATASET = import.meta.env.PUBLIC_SANITY_DATASET ?? "production"
// Pinned API date — Sanity's content-lake API is versioned by date; never float.
const API_VERSION = import.meta.env.PUBLIC_SANITY_API_VERSION ?? "2024-10-01"

/** True only when a real project is wired. Gates client creation + every fetch. */
export const isSanityConfigured = PROJECT_ID.trim().length > 0

let _client: SanityClient | null = null

/**
 * Lazily construct the client. Returns null when unconfigured — callers must
 * treat that as "no content" rather than an error so the build degrades cleanly.
 * `useCdn: false` so a build always reads the freshest published content (the
 * Sanity→deploy webhook in Phase 7 is what triggers rebuilds on publish).
 */
function getClient(): SanityClient | null {
  if (!isSanityConfigured) return null
  if (!_client) {
    _client = createClient({
      projectId: PROJECT_ID,
      dataset: DATASET,
      apiVersion: API_VERSION,
      useCdn: false,
    })
  }
  return _client
}

/** Run a GROQ query, or return `fallback` when Sanity is not configured. */
async function query<T>(
  groq: string,
  params: Record<string, unknown>,
  fallback: T,
): Promise<T> {
  const client = getClient()
  if (!client) return fallback
  return client.fetch<T>(groq, params)
}

// ---------------------------------------------------------------------------
// Result types — shaped to compose with the Phase-2 JSON-LD builders (seo.ts).
// ---------------------------------------------------------------------------

/** Shared SEO block. `ogImage`/`canonicalUrl` are resolved/absolute already. */
export interface SanitySeo {
  title: string
  description: string
  /** Author-set canonical override; absent ⇒ derive from the route path. */
  canonicalUrl?: string
  /** Resolved CDN URL of the OG image asset, if one is set. */
  ogImage?: string
}

/** Alias, not a parallel type: a `faqs` array drops straight into faqPageSchema. */
export type SanityFaq = FaqItem

export interface SanityWorkflowStep {
  name: string
  description: string
}

export interface SanityComparisonRow {
  feature: string
  specforge: string
  alternative: string
}

export interface SanityComparison {
  alternativeName: string
  rows: SanityComparisonRow[]
}

export interface SanityExample {
  title: string
  input: string
  output: string
}

/** Portable Text blocks. Rendered to HTML in Phase 4; kept opaque here. */
export type PortableTextBlock = Record<string, unknown>

interface SanityDocMeta {
  _id: string
  _createdAt: string
  _updatedAt: string
  slug: string
}

/** `seoPage` powers /use-cases/*, /compare/*, and standalone landing pages. */
export type SeoPageSection = "use-case" | "comparison" | "landing"

export interface SeoPageDoc extends SanityDocMeta {
  section: SeoPageSection
  seo: SanitySeo
  heading: string
  /** GEO direct-answer definition rendered up top (Phase 5 answer-readiness). */
  definition: string
  workflowSteps: SanityWorkflowStep[]
  comparison?: SanityComparison
  faqs: SanityFaq[]
  examples: SanityExample[]
  body?: PortableTextBlock[]
}

export interface GuideDoc extends SanityDocMeta {
  seo: SanitySeo
  heading: string
  excerpt?: string
  authorName?: string
  heroImage?: string
  /** ISO 8601. Author-set publish date, else the document's creation date. */
  datePublished: string
  /** ISO 8601. Last content edit. Feeds Article dateModified + sitemap lastmod. */
  dateModified: string
  body?: PortableTextBlock[]
  faqs: SanityFaq[]
}

export interface TemplatePageDoc extends SanityDocMeta {
  seo: SanitySeo
  heading: string
  templateName: string
  definition: string
  workflowSteps: SanityWorkflowStep[]
  examples: SanityExample[]
  faqs: SanityFaq[]
  body?: PortableTextBlock[]
}

export interface DemoPageDoc extends SanityDocMeta {
  seo: SanitySeo
  heading: string
  summary: string
  /** The rough product idea this curated, first-party demo starts from. */
  idea: string
  specMarkdown: string
  planMarkdown: string
  harnessMarkdown: string
  tasksMarkdown: string
  faqs: SanityFaq[]
}

export interface RedirectDoc {
  _id: string
  /** Site-relative source path, e.g. "/old-guide". */
  source: string
  /** Destination path or absolute URL. */
  destination: string
  /** 308 (permanent) vs 307 (temporary). */
  permanent: boolean
}

// ---------------------------------------------------------------------------
// Projections — named field-by-field so the result shape is the contract.
// ---------------------------------------------------------------------------
const SEO_PROJECTION = `
  seo {
    title,
    description,
    canonicalUrl,
    "ogImage": ogImage.asset->url
  }`

const FAQ_PROJECTION = `faqs[]{ question, answer }`
const WORKFLOW_PROJECTION = `workflowSteps[]{ name, description }`
const EXAMPLE_PROJECTION = `examples[]{ title, input, output }`
const COMPARISON_PROJECTION = `comparison{ alternativeName, rows[]{ feature, specforge, alternative } }`
const META = `_id, _createdAt, _updatedAt, "slug": slug.current`

const SEO_PAGE_FIELDS = `
  ${META},
  section,
  ${SEO_PROJECTION},
  heading,
  definition,
  ${WORKFLOW_PROJECTION},
  ${COMPARISON_PROJECTION},
  ${FAQ_PROJECTION},
  ${EXAMPLE_PROJECTION},
  body`

const GUIDE_FIELDS = `
  ${META},
  ${SEO_PROJECTION},
  heading,
  excerpt,
  "authorName": author,
  "heroImage": heroImage.asset->url,
  "datePublished": coalesce(publishedAt, _createdAt),
  "dateModified": _updatedAt,
  body,
  ${FAQ_PROJECTION}`

const TEMPLATE_FIELDS = `
  ${META},
  ${SEO_PROJECTION},
  heading,
  templateName,
  definition,
  ${WORKFLOW_PROJECTION},
  ${EXAMPLE_PROJECTION},
  ${FAQ_PROJECTION},
  body`

const DEMO_FIELDS = `
  ${META},
  ${SEO_PROJECTION},
  heading,
  summary,
  idea,
  specMarkdown,
  planMarkdown,
  harnessMarkdown,
  tasksMarkdown,
  ${FAQ_PROJECTION}`

// Only publishable docs: a slug must exist or the route can't be built.
const PUBLISHED = `defined(slug.current)`

// ---------------------------------------------------------------------------
// Fetch functions — every one returns empty/null when Sanity is unconfigured.
// ---------------------------------------------------------------------------

export function getSeoPages(section?: SeoPageSection): Promise<SeoPageDoc[]> {
  const filter = section
    ? `_type == "seoPage" && ${PUBLISHED} && section == $section`
    : `_type == "seoPage" && ${PUBLISHED}`
  return query<SeoPageDoc[]>(
    `*[${filter}] | order(_updatedAt desc) { ${SEO_PAGE_FIELDS} }`,
    { section: section ?? null },
    [],
  )
}

export function getSeoPage(slug: string): Promise<SeoPageDoc | null> {
  return query<SeoPageDoc | null>(
    `*[_type == "seoPage" && slug.current == $slug][0] { ${SEO_PAGE_FIELDS} }`,
    { slug },
    null,
  )
}

export function getGuides(): Promise<GuideDoc[]> {
  return query<GuideDoc[]>(
    `*[_type == "guide" && ${PUBLISHED}] | order(coalesce(publishedAt, _createdAt) desc) { ${GUIDE_FIELDS} }`,
    {},
    [],
  )
}

export function getGuide(slug: string): Promise<GuideDoc | null> {
  return query<GuideDoc | null>(
    `*[_type == "guide" && slug.current == $slug][0] { ${GUIDE_FIELDS} }`,
    { slug },
    null,
  )
}

export function getTemplatePages(): Promise<TemplatePageDoc[]> {
  return query<TemplatePageDoc[]>(
    `*[_type == "templatePage" && ${PUBLISHED}] | order(_updatedAt desc) { ${TEMPLATE_FIELDS} }`,
    {},
    [],
  )
}

export function getTemplatePage(slug: string): Promise<TemplatePageDoc | null> {
  return query<TemplatePageDoc | null>(
    `*[_type == "templatePage" && slug.current == $slug][0] { ${TEMPLATE_FIELDS} }`,
    { slug },
    null,
  )
}

export function getDemoPages(): Promise<DemoPageDoc[]> {
  return query<DemoPageDoc[]>(
    `*[_type == "demoPage" && ${PUBLISHED}] | order(_updatedAt desc) { ${DEMO_FIELDS} }`,
    {},
    [],
  )
}

export function getDemoPage(slug: string): Promise<DemoPageDoc | null> {
  return query<DemoPageDoc | null>(
    `*[_type == "demoPage" && slug.current == $slug][0] { ${DEMO_FIELDS} }`,
    { slug },
    null,
  )
}

export function getRedirects(): Promise<RedirectDoc[]> {
  return query<RedirectDoc[]>(
    `*[_type == "redirect" && defined(source) && defined(destination)] {
      _id, source, destination, "permanent": coalesce(permanent, true)
    }`,
    {},
    [],
  )
}

// ---------------------------------------------------------------------------
// Route paths + Phase-2 adapters. These make the content-routing contract
// explicit and prove the result types compose into the existing builders.
// ---------------------------------------------------------------------------

export const guidePath = (slug: string) => `/guides/${slug}`
export const templatePath = (slug: string) => `/templates/${slug}`
export const demoPath = (slug: string) => `/demos/${slug}`

/** Each `seoPage` section owns a route namespace; `landing` is top-level. */
export function seoPagePath(section: SeoPageSection, slug: string): string {
  switch (section) {
    case "use-case":
      return `/use-cases/${slug}`
    case "comparison":
      return `/compare/${slug}`
    case "landing":
      return `/${slug}`
  }
}

/**
 * Adapt a guide into the Phase-2 `articleSchema` input. Lives here (not in the
 * route) so the type alignment is compiler-checked in the data layer: if the
 * GROQ projection drifts from what `articleSchema` needs, this stops building.
 */
export function guideToArticleInput(guide: GuideDoc): ArticleSchemaInput {
  return {
    title: guide.seo.title,
    description: guide.seo.description,
    path: guidePath(guide.slug),
    image: guide.seo.ogImage,
    datePublished: guide.datePublished,
    dateModified: guide.dateModified,
    authorName: guide.authorName,
  }
}
