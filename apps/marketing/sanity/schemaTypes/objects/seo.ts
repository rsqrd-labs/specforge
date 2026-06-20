import { defineType, defineField } from "sanity"

// Per-document SEO block. Every content type embeds exactly one of these so the
// title/description that drive <Seo> and the JSON-LD builders are authored
// explicitly per route (issue #18 forbids silent metadata fallbacks — duplicate
// or missing title/description fail the Phase-6 content QA). `canonicalUrl` and
// `ogImage` are overrides; absent ⇒ the route derives them.
export const seo = defineType({
  name: "seo",
  title: "SEO",
  type: "object",
  options: { collapsible: true, collapsed: false },
  fields: [
    defineField({
      name: "title",
      title: "Title tag",
      type: "string",
      description:
        "Unique <title> + og:title. ~50–60 chars. Must be distinct across pages.",
      validation: (rule) => rule.required().min(15).max(70),
    }),
    defineField({
      name: "description",
      title: "Meta description",
      type: "text",
      rows: 3,
      description:
        "Unique meta description + og:description. ~150–160 chars. Must be distinct across pages.",
      validation: (rule) => rule.required().min(50).max(180),
    }),
    defineField({
      name: "canonicalUrl",
      title: "Canonical URL override",
      type: "url",
      description:
        "Only set to point this page's canonical elsewhere (e.g. consolidating duplicates). Leave blank to use the page's own route.",
    }),
    defineField({
      name: "ogImage",
      title: "Social share image (OG)",
      type: "image",
      options: { hotspot: true },
      description: "1200×630 recommended. Falls back to the brand mark if unset.",
    }),
  ],
})
