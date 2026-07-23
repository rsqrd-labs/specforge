// Central SEO + structured-data library for the marketing zone (issue #18,
// Phase 2). Two responsibilities:
//
//   1. Site-wide metadata defaults (OG image, locale, Twitter card) — the *safe*
//      fields that may default. `title` and `description` deliberately have NO
//      default: they must be unique per route, and the Phase 6 content QA fails
//      on duplicate/missing values. A silent description fallback would make
//      every un-overridden page pass with identical copy, defeating that gate.
//
//   2. Pure, typed JSON-LD builders for the five schema.org types the plan
//      calls for: Organization + SoftwareApplication (site-wide), FAQPage and
//      BreadcrumbList (answer-ready / nested content), and Article (guides).
//      Builders are side-effect free so Phase 6 can validate their shapes
//      directly, and they share stable `@id` anchors so the entities resolve to
//      one connected graph instead of disconnected nodes — answer engines key on
//      a single, consistent Thought2Build entity.
import {
  SITE_NAME,
  SITE_URL,
  ENTITY_DESCRIPTION,
  SAME_AS,
  absoluteUrl,
} from "../consts"

/** Stable `@id` anchors for cross-referencing entities across pages. */
export const ORGANIZATION_ID = `${SITE_URL}/#organization`
export const SOFTWARE_ID = `${SITE_URL}/#software`

/**
 * Default social-share image. Site-relative; resolved to absolute by <Seo>. A
 * purpose-built 1200×630 card (the 1.91:1 ratio OG/Twitter `summary_large_image`
 * expects) — not the square brand mark, which social + answer-engine previews
 * would letterbox/crop. Regenerate with `node scripts/generate-og-card.mjs`.
 */
export const DEFAULT_OG_IMAGE = "/brand/og-card.png"
/** Dimensions of DEFAULT_OG_IMAGE, emitted as og:image:width/height by <Seo>. */
export const OG_IMAGE_WIDTH = 1200
export const OG_IMAGE_HEIGHT = 630
/**
 * The square brand mark — used for schema.org `Organization.logo`, which wants a
 * logo-shaped image, NOT the wide 1.91:1 social card (DEFAULT_OG_IMAGE).
 */
export const BRAND_LOGO = "/brand/squirrel-mark.png"
/** Marketing copy is English; keep OG locale consistent across routes. */
export const OG_LOCALE = "en_US"
/** Large image card so OG previews render the brand mark prominently. */
export const TWITTER_CARD = "summary_large_image"

/** A single JSON-LD node. Loose by design — schema.org shapes vary by type. */
export type JsonLdSchema = Record<string, unknown>

/**
 * Publisher/brand entity. Referenced by `@id` from SoftwareApplication and
 * Article so the graph stays connected.
 */
export function organizationSchema(): JsonLdSchema {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": ORGANIZATION_ID,
    name: SITE_NAME,
    url: absoluteUrl("/"),
    logo: absoluteUrl(BRAND_LOGO),
    description: ENTITY_DESCRIPTION,
    // Only emit `sameAs` when real profiles are configured — an empty array (or a
    // dead/placeholder link) weakens entity grounding rather than helping it.
    ...(SAME_AS.length ? { sameAs: [...SAME_AS] } : {}),
  }
}

/**
 * The product entity. Carries the free-tier offer (starter credits) and points
 * its publisher at the Organization `@id`.
 */
export function softwareApplicationSchema(): JsonLdSchema {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "@id": SOFTWARE_ID,
    name: SITE_NAME,
    applicationCategory: "DeveloperApplication",
    operatingSystem: "Web",
    url: absoluteUrl("/"),
    description: ENTITY_DESCRIPTION,
    publisher: { "@id": ORGANIZATION_ID },
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
      description: "Start free with 50 starter credits.",
    },
  }
}

export interface FaqItem {
  question: string
  answer: string
}

/** Answer-ready FAQ block (GEO). Each item becomes a Question/Answer pair. */
export function faqPageSchema(faqs: FaqItem[]): JsonLdSchema {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((faq) => ({
      "@type": "Question",
      name: faq.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: faq.answer,
      },
    })),
  }
}

export interface BreadcrumbItem {
  name: string
  /** Site-relative path; resolved to an absolute URL. */
  path: string
}

/** Breadcrumb trail for nested content (e.g. /guides/<slug>). */
export function breadcrumbListSchema(items: BreadcrumbItem[]): JsonLdSchema {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    })),
  }
}

export interface ArticleSchemaInput {
  title: string
  description: string
  /** Site-relative path of the article. */
  path: string
  /** Site-relative or absolute hero image. Defaults to the brand mark. */
  image?: string
  /** ISO 8601. In Phase 3/4 these come from Sanity `_createdAt`/`_updatedAt`. */
  datePublished?: string
  dateModified?: string
  /** Named human author; falls back to the Organization entity. */
  authorName?: string
}

/** Article entity for guide pages. */
export function articleSchema(input: ArticleSchemaInput): JsonLdSchema {
  const url = absoluteUrl(input.path)
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: input.title,
    description: input.description,
    url,
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    image: absoluteUrl(input.image ?? DEFAULT_OG_IMAGE),
    author: input.authorName
      ? { "@type": "Person", name: input.authorName }
      : { "@id": ORGANIZATION_ID },
    publisher: { "@id": ORGANIZATION_ID },
    ...(input.datePublished ? { datePublished: input.datePublished } : {}),
    ...(input.dateModified ? { dateModified: input.dateModified } : {}),
  }
}

/**
 * Site-wide structured data: the Organization + product entities every page
 * should carry so answer engines resolve the Thought2Build entity consistently.
 */
export const siteJsonLd: JsonLdSchema[] = [
  organizationSchema(),
  softwareApplicationSchema(),
]
