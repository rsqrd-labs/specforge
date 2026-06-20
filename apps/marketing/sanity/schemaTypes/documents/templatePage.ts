import { defineType, defineField, defineArrayMember } from "sanity"

// Starter-template landing page (route: /templates/*). Targets the
// PRD/template keyword cluster (issue #18, Phase 4). Answer-ready: a direct
// definition of what the template produces, the workflow it follows, concrete
// examples, and FAQs.
export const templatePage = defineType({
  name: "templatePage",
  title: "Template page",
  type: "document",
  groups: [
    { name: "seo", title: "SEO", default: true },
    { name: "content", title: "Content" },
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
      name: "templateName",
      title: "Template name",
      type: "string",
      group: "content",
      description: "The named starter this page documents (e.g. 'SaaS PRD').",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "definition",
      title: "Direct definition",
      type: "text",
      rows: 3,
      group: "geo",
      description: "Quotable, up-top answer to 'what does this template do?'.",
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
      name: "examples",
      title: "Examples",
      type: "array",
      group: "geo",
      of: [defineArrayMember({ type: "example" })],
    }),
    defineField({
      name: "faqs",
      title: "FAQs",
      type: "array",
      group: "geo",
      of: [defineArrayMember({ type: "faqItem" })],
    }),
    defineField({
      name: "body",
      title: "Body",
      type: "blockContent",
      group: "content",
    }),
  ],
  preview: {
    select: { title: "heading", subtitle: "templateName" },
  },
})
