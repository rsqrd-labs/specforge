import { defineType, defineField, defineArrayMember } from "sanity"

// Long-form guide / article (route: /guides/*). Maps to Article JSON-LD: the
// fetch layer's guideToArticleInput() composes seo + dates + author into the
// Phase-2 articleSchema() builder. `publishedAt` is the author-set date; when
// blank the fetch layer falls back to _createdAt, and dateModified is always
// _updatedAt (which also feeds the sitemap lastmod).
export const guide = defineType({
  name: "guide",
  title: "Guide",
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
      name: "excerpt",
      title: "Excerpt",
      type: "text",
      rows: 3,
      group: "content",
      description: "Short standfirst shown under the H1 and in listings.",
    }),
    defineField({
      name: "author",
      title: "Author name",
      type: "string",
      group: "content",
      description:
        "Named human author. Blank ⇒ the article is attributed to the SpecForge organization.",
    }),
    defineField({
      name: "heroImage",
      title: "Hero image",
      type: "image",
      options: { hotspot: true },
      group: "content",
    }),
    defineField({
      name: "publishedAt",
      title: "Published at",
      type: "datetime",
      group: "content",
      description: "Author-set publish date. Blank ⇒ document creation date.",
    }),
    defineField({
      name: "body",
      title: "Body",
      type: "blockContent",
      group: "content",
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
    select: { title: "heading", subtitle: "author", media: "heroImage" },
  },
})
