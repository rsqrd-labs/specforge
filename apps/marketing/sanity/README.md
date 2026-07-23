# Thought2Build Marketing Studio

Sanity Studio for the marketing zone (issue #18, Phase 3). This is a **standalone
studio** — it is *not* embedded in the Astro site. That is deliberate: embedding
an editor surface on the public marketing origin would add a `/studio` route to
noindex and exclude from the sitemap, and noindex integrity is a hard requirement
for issue #18. The studio deploys to its own `*.sanity.studio` host; the Astro
site only **reads** this content at build time via
[`../src/lib/sanity.ts`](../src/lib/sanity.ts).

## Content model

Five document types, each carrying an embedded `seo` block (title / description /
canonical override / OG image) plus GEO answer-readiness fields:

| Type           | Route namespace                          | Purpose                                            |
| -------------- | ---------------------------------------- | -------------------------------------------------- |
| `seoPage`      | `/use-cases/*`, `/compare/*`, top-level  | Answer-ready pages, split by a `section` field     |
| `guide`        | `/guides/*`                              | Long-form articles (→ Article JSON-LD)             |
| `templatePage` | `/templates/*`                           | Starter-template landing pages                     |
| `demoPage`     | `/demos/*`                               | **Curated, first-party** four-artifact demos       |
| `redirect`     | —                                        | Editor-managed 308/307 redirects                   |

Shared objects: `seo`, `faqItem`, `workflowStep`, `comparison`(+`comparisonRow`),
`example`, `blockContent`. The Astro fetch layer projects these field names
directly, so **keep the schema field names and the GROQ projections in sync**.

> **Demo sanitization rule:** `demoPage` artifacts are authored by hand. There is
> no import-from-workspace path. Demos must never contain user data, secrets,
> private links, or unsafe generated artifacts (enforced by the Phase-6 gate).

## Local development

This studio is its own package with its own dependency tree (`sanity`,
`@sanity/vision`, …), intentionally kept out of the Astro app's install.

```bash
cd apps/marketing/sanity
cp .env.example .env        # set SANITY_STUDIO_PROJECT_ID + SANITY_STUDIO_DATASET
pnpm install
pnpm dev                    # local studio on http://localhost:3333
pnpm deploy                 # publish to <project>.sanity.studio
```

`SANITY_STUDIO_PROJECT_ID` / `SANITY_STUDIO_DATASET` are **public** values. No
secrets live here — editors authenticate with their own Sanity login.

## How the Astro site consumes it

The marketing build reads `PUBLIC_SANITY_PROJECT_ID` / `PUBLIC_SANITY_DATASET` /
`PUBLIC_SANITY_API_VERSION` (same project, public values). When the project id is
blank, the fetch layer degrades to empty results so `astro build` stays green
without credentials (CI builds this way). A published edit triggers a rebuild via
the Sanity → Vercel deploy hook wired in Phase 7.
