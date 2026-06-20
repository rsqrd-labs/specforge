import { defineType, defineField } from "sanity"

// One step in an ordered "how it works" sequence (GEO answer-readiness — the
// workflow-steps block). The array order in the parent document is the step
// order; no explicit index field so editors can reorder by drag.
export const workflowStep = defineType({
  name: "workflowStep",
  title: "Workflow step",
  type: "object",
  fields: [
    defineField({
      name: "name",
      title: "Step name",
      type: "string",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "description",
      title: "Description",
      type: "text",
      rows: 3,
      validation: (rule) => rule.required().min(20),
    }),
  ],
  preview: {
    select: { title: "name", subtitle: "description" },
  },
})
