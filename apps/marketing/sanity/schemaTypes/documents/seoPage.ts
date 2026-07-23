import { defineType, defineField, defineArrayMember } from "sanity"

// Generic answer-ready page. One type powers three route namespaces, chosen by
// `section`: use-cases (/use-cases/*), comparisons (/compare/*), and standalone
// landing pages (top-level). The fetch layer filters by section
// (getSeoPages(section)); the route maps section→path (seoPagePath).
//
// Carries the full GEO answer-readiness kit (Phase 5): a direct definition up
// top, ordered workflow steps, an optional comparison table, FAQs, and concrete
// examples — so the static HTML answers the query without the visitor scrolling.
export const seoPage = defineType({
  name: "seoPage",
  title: "SEO / answer page",
  type: "document",
  groups: [
    { name: "seo", title: "SEO", default: true },
    { name: "content", title: "Content" },
    { name: "geo", title: "Answer-readiness (GEO)" },
  ],
  fields: [
    defineField({
      name: "section",
      title: "Section",
      type: "string",
      group: "seo",
      description: "Which route namespace this page lives under.",
      options: {
        list: [
          { title: "Use case (/use-cases/…)", value: "use-case" },
          { title: "Comparison (/compare/…)", value: "comparison" },
          { title: "Landing (top-level)", value: "landing" },
        ],
        layout: "radio",
      },
      initialValue: "use-case",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "slug",
      title: "Slug",
      type: "slug",
      group: "seo",
      options: { source: "heading", maxLength: 96 },
      validation: (rule) => rule.required(),
    }),
    defineField({ name: "seo", title: "SEO", type: "seo", group: "seo" }),
    defineField({
      name: "heading",
      title: "Page heading (H1)",
      type: "string",
      group: "content",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "definition",
      title: "Direct definition",
      type: "text",
      rows: 3,
      group: "geo",
      description:
        "The up-top, quotable answer. Lead with the standardized Thought2Build entity language for consistent framing across answer engines.",
      validation: (rule) => rule.required().min(40),
    }),
    defineField({
      name: "workflowSteps",
      title: "Workflow steps",
      type: "array",
      group: "geo",
      of: [defineArrayMember({ type: "workflowStep" })],
    }),
    defineField({
      name: "comparison",
      title: "Comparison table",
      type: "comparison",
      group: "geo",
      description: "Recommended for the comparison section; optional elsewhere.",
    }),
    defineField({
      name: "faqs",
      title: "FAQs",
      type: "array",
      group: "geo",
      of: [defineArrayMember({ type: "faqItem" })],
    }),
    defineField({
      name: "examples",
      title: "Examples",
      type: "array",
      group: "geo",
      of: [defineArrayMember({ type: "example" })],
    }),
    defineField({
      name: "body",
      title: "Body",
      type: "blockContent",
      group: "content",
    }),
  ],
  preview: {
    select: { title: "heading", subtitle: "section" },
  },
})
