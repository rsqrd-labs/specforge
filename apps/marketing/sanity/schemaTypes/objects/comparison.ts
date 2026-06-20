import { defineType, defineField, defineArrayMember } from "sanity"

// A structured comparison table (GEO answer-readiness — answer engines quote
// "X vs Y" tables directly). One row per feature, with the SpecForge cell and
// the alternative's cell. The alternative is named once at the table level.
export const comparisonRow = defineType({
  name: "comparisonRow",
  title: "Comparison row",
  type: "object",
  fields: [
    defineField({
      name: "feature",
      title: "Feature / dimension",
      type: "string",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "specforge",
      title: "SpecForge",
      type: "string",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "alternative",
      title: "Alternative",
      type: "string",
      validation: (rule) => rule.required(),
    }),
  ],
  preview: {
    select: { title: "feature", subtitle: "specforge" },
  },
})

export const comparison = defineType({
  name: "comparison",
  title: "Comparison table",
  type: "object",
  fields: [
    defineField({
      name: "alternativeName",
      title: "Alternative name",
      type: "string",
      description: "The thing SpecForge is compared against (column header).",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "rows",
      title: "Rows",
      type: "array",
      of: [defineArrayMember({ type: "comparisonRow" })],
      validation: (rule) => rule.min(2),
    }),
  ],
})
