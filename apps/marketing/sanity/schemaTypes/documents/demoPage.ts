import { defineType, defineField, defineArrayMember } from "sanity"

// Curated, FIRST-PARTY demo page (route: /demos/*). Walks a rough idea through
// the four SpecForge artifacts as authored content.
//
// HARD RULE (issue #18, Phase 4 + Phase-6 demo-sanitization gate): demos are
// authored here, never sourced from live user workspaces or storyboards. They
// must contain NO user data, secrets, private links, or unsafe generated
// artifacts. The artifact fields below are plain markdown the editor writes —
// there is deliberately no import-from-workspace path.
export const demoPage = defineType({
  name: "demoPage",
  title: "Demo page (curated)",
  type: "document",
  groups: [
    { name: "seo", title: "SEO", default: true },
    { name: "content", title: "Content" },
    { name: "artifacts", title: "Artifacts" },
    { name: "geo", title: "Answer-readiness (GEO)" },
  ],
  fields: [
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
      title: "Heading (H1)",
      type: "string",
      group: "content",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "summary",
      title: "Summary",
      type: "text",
      rows: 3,
      group: "content",
      validation: (rule) => rule.required().min(40),
    }),
    defineField({
      name: "idea",
      title: "Starting idea (rough input)",
      type: "text",
      rows: 3,
      group: "content",
      description: "The one-line product idea this demo begins from.",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "specMarkdown",
      title: "SPEC.md",
      type: "text",
      rows: 10,
      group: "artifacts",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "planMarkdown",
      title: "PLAN.md",
      type: "text",
      rows: 10,
      group: "artifacts",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "harnessMarkdown",
      title: "HARNESS",
      type: "text",
      rows: 10,
      group: "artifacts",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "tasksMarkdown",
      title: "TASKS",
      type: "text",
      rows: 10,
      group: "artifacts",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "faqs",
      title: "FAQs",
      type: "array",
      group: "geo",
      of: [defineArrayMember({ type: "faqItem" })],
    }),
  ],
  preview: {
    select: { title: "heading", subtitle: "idea" },
  },
})
