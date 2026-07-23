// Schema registry for the Thought2Build marketing studio (issue #18, Phase 3).
// Five document types (seoPage, guide, templatePage, demoPage, redirect) over a
// set of shared objects (seo + the GEO answer-readiness blocks). The Astro
// fetch layer (apps/marketing/src/lib/sanity.ts) projects these field names
// directly — keep them in sync.
import type { SchemaTypeDefinition } from "sanity"

import { seo } from "./objects/seo"
import { faqItem } from "./objects/faqItem"
import { workflowStep } from "./objects/workflowStep"
import { comparison, comparisonRow } from "./objects/comparison"
import { example } from "./objects/example"
import { blockContent } from "./objects/blockContent"

import { seoPage } from "./documents/seoPage"
import { guide } from "./documents/guide"
import { templatePage } from "./documents/templatePage"
import { demoPage } from "./documents/demoPage"
import { redirect } from "./documents/redirect"

export const schemaTypes: SchemaTypeDefinition[] = [
  // documents
  seoPage,
  guide,
  templatePage,
  demoPage,
  redirect,
  // objects
  seo,
  faqItem,
  workflowStep,
  comparison,
  comparisonRow,
  example,
  blockContent,
]
