# Content drafts (Phase 6, T-6.2)

**Status as of 2026-07-26: blocked on a prerequisite that has nothing to do with content
quality — Sanity has not been set up yet.**

## The actual blocker

`docs/INTEGRATION_API_SETUP_HANDBOOK.md` §"Step A — Set up Sanity" requires a human to go
to sanity.io, create an account and a project, and deploy the standalone studio
(`apps/marketing/sanity/`). Nothing in this repo has a configured `SANITY_STUDIO_PROJECT_ID`
or `PUBLIC_SANITY_PROJECT_ID` — not a placeholder, not a real one — which means the CMS
these documents would be authored into **does not exist yet**, independent of who's
logged into what. This is a different, earlier blocker than the plan's usual credential
boundary (§2: "the agent has no Vercel, Google, or Sanity credentials, drive it through
Playwright against a session the human is already logged into") — there is no session to
drive because there is nothing to log into.

Once Sanity exists (Step A, above — a ~10-minute human task), the path is unblocked and
either works:

- **Manual**: paste each draft below into the Studio by hand, field by field.
- **Agent-driven**: once the human is logged into the deployed `*.sanity.studio` URL,
  I can drive data entry through Playwright MCP against that session, per the plan's
  standard credential-boundary pattern.

## Why only 3 of the 14 planned documents (`docs/SEO_CONTENT_MAP.md` §4) are drafted here

This isn't a shortcut — it's the plan's own rules applied honestly:

- **`saas-idea-to-spec` (use case), `spec-for-coding-agents` (guide), and
  `saas-prd-template` (template)** make no claims about anyone but Thought2Build itself.
  They're fully drafted, full-length, and ready to publish once Sanity exists.
- **The two `/compare` documents are deliberately NOT drafted.** Plan §9's honesty bar
  ("comparison pages must be accurate about competitors... overstated claims are a legal
  and reputational risk") and the ownership table's "Human owns voice/claims" line both
  mean a comparison page needs specific, checkable claims about GitHub Spec Kit and
  ChatPRD verified against their actual current docs/pricing — not written from search
  snippets, which are third-party summaries and occasionally wrong. Drafting a
  comparison table now would mean either fabricating specifics or copying unverified
  third-party claims, both of which the plan explicitly forbids. `SEO_CONTENT_MAP.md`
  §2.3 lists the two candidates and the sources that identified them; turning that into
  a real comparison page is a follow-up task, not a content-quality shortcut.
- **The two `/demos` documents are deliberately NOT drafted.** The `demoPage` schema's
  own source comment is explicit: demos must be "curated, FIRST-PARTY only" and there is
  "deliberately no import-from-workspace path" — meaning a real demo's SPEC/PLAN/HARNESS/
  TASKS markdown is supposed to be the actual output of a real Thought2Build generation
  run, reviewed and cleaned of any incidental artifacts, not hand-written prose made to
  *look* like generator output. I have no way to run the live product's generation
  pipeline from here (no credits, no authenticated workspace, and doing so would consume
  real production credits per `CLAUDE.md`'s credit-ledger accounting for a demo, which is
  a product-cost decision, not mine to make unilaterally). The correct next step is for a
  human (or a follow-up session with product access) to actually run two idea→artifact
  generations and hand the real output back for cleanup into a `demoPage` document.

## Remaining 6 planned-but-undrafted documents

`coding-agent-handoff`, `why-agents-drift`, `plan-to-shipped-feature`,
`prd-that-survives-review`, `standardize-team-specs`, `api-spec-template`,
`internal-tool-brief-template` (7, not 6 — `SEO_CONTENT_MAP.md` §4 has the full list) are
titled and scoped but not drafted in this pass, purely for effort/scope reasons — three
complete, full-quality documents plus the research and hub-page rewrite was the right
size for one implementation pass. They don't have the compare/demo blocker; drafting them
is straightforward continuation work.

## Field mapping

Each `.md` file in this directory is structured to map 1:1 onto its Sanity document type's
fields (`apps/marketing/sanity/schemaTypes/documents/*.ts`) — a top frontmatter-style block
for the scalar/object fields, then the `body` as markdown (paste into the Studio's rich-text
field; Sanity's Portable Text editor accepts pasted Markdown and converts it). `publishedAt`
is deliberately left as `<set at actual publish time>` rather than a fabricated date.
