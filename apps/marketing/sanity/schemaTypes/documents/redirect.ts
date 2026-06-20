import { defineType, defineField } from "sanity"

// An editor-managed redirect. The fetch layer reads these (getRedirects) so the
// marketing build / Vercel config can emit 308/307 redirects without a code
// change — e.g. when a guide slug changes. Source is a site-relative path;
// destination is a path or absolute URL.
export const redirect = defineType({
  name: "redirect",
  title: "Redirect",
  type: "document",
  fields: [
    defineField({
      name: "source",
      title: "Source path",
      type: "string",
      description: "Site-relative path to redirect FROM, e.g. /old-guide.",
      validation: (rule) =>
        rule
          .required()
          .regex(/^\/[^\s]*$/, {
            name: "site-relative path",
          }),
    }),
    defineField({
      name: "destination",
      title: "Destination",
      type: "string",
      description: "Path (/new-guide) or absolute URL to redirect TO.",
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: "permanent",
      title: "Permanent (308)",
      type: "boolean",
      description: "On ⇒ 308 permanent. Off ⇒ 307 temporary.",
      initialValue: true,
    }),
  ],
  preview: {
    select: { title: "source", subtitle: "destination" },
  },
})
