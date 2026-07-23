import { defineType, defineField } from "sanity"

// A concrete input→output example (GEO answer-readiness — examples ground the
// abstract claim in something specific). For Thought2Build: a rough idea in, a
// shaped artifact out.
export const example = defineType({
  name: "example",
  title: "Example",
  type: "object",
  fields: [
    defineField({
      name: "title",
      title: "Title",
      type: "string",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "input",
      title: "Input (rough idea)",
      type: "text",
      rows: 3,
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "output",
      title: "Output (shaped artifact)",
      type: "text",
      rows: 4,
      validation: (rule) => rule.required(),
    }),
  ],
  preview: {
    select: { title: "title", subtitle: "input" },
  },
})
