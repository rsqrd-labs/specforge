import { defineType, defineField } from "sanity"

// One Question/Answer pair. Arrays of these become FAQPage JSON-LD (GEO
// answer-readiness) and an on-page FAQ block. Keep answers self-contained and
// directly quotable — answer engines lift them as-is.
export const faqItem = defineType({
  name: "faqItem",
  title: "FAQ item",
  type: "object",
  fields: [
    defineField({
      name: "question",
      title: "Question",
      type: "string",
      validation: (rule) => rule.required().min(8),
    }),
    defineField({
      name: "answer",
      title: "Answer",
      type: "text",
      rows: 4,
      description:
        "A complete, self-contained answer. ~40–80 words. No 'see above' references.",
      validation: (rule) => rule.required().min(40),
    }),
  ],
  preview: {
    select: { title: "question" },
  },
})
