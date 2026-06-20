// SpecForge marketing studio (issue #18, Phase 3).
//
// Standalone studio — intentionally NOT embedded via @sanity/astro. This keeps
// the editor surface off the public marketing origin entirely, so there is no
// /studio route to noindex or exclude from the sitemap (noindex integrity is a
// hard requirement for issue #18). Deploy with `sanity deploy` to its own
// *.sanity.studio host. The Astro site only *reads* this content at build time
// via apps/marketing/src/lib/sanity.ts.
//
// projectId/dataset come from SANITY_STUDIO_* env (see .env.example). They are
// public values; no secrets live here.
import { defineConfig } from "sanity"
import { structureTool } from "sanity/structure"
import { visionTool } from "@sanity/vision"
import { schemaTypes } from "./schemaTypes"

export default defineConfig({
  name: "specforge-marketing",
  title: "SpecForge Marketing",
  projectId: process.env.SANITY_STUDIO_PROJECT_ID ?? "",
  dataset: process.env.SANITY_STUDIO_DATASET ?? "production",
  plugins: [structureTool(), visionTool()],
  schema: { types: schemaTypes },
})
