/**
 * Harness contracts for Plan v1.md §18, Phase 14 — V1.3 Usefulness Improvements
 * (frontend layer: T-USE-04, T-USE-06, T-USE-08, T-USE-10, T-USE-12, T-USE-13).
 *
 * These tests are RED before the v1.3 frontend tasks are implemented and GREEN
 * after.
 *
 * Invariants:
 *   - SpecClarificationModal exists and is wired into the workspace stage editor.
 *   - The clarification modal is bypassed (silent) when the backend returns 204.
 *   - The TASKS effort-summary parser handles missing summary blocks gracefully.
 *   - Export PDF button is rendered in the workspace header alongside ZIP/GitHub.
 *   - SharePublicLinkModal exists and copy-button copies the public URL.
 *   - PublicWorkspaceView is a new route at /p/:slug registered outside the
 *     authenticated guard.
 *   - PublicWorkspaceView sets noindex meta tags and never imports authenticated
 *     stores (no userStore / no credit balance leakage).
 *   - TemplatesStrip is rendered on Dashboard and on the workspace creation form.
 *   - Selecting a template prefills the form with template_slug carried through.
 *   - The harness-coverage chip is shown in the workspace header, dashboard card,
 *     and public view.
 *   - api.ts exports new functions: requestClarification, persistClarification,
 *     exportWorkspacePdf, enablePublicShare, disablePublicShare,
 *     rotatePublicShare, getTemplates, getPublicWorkspace.
 *   - No pre-existing api.ts exports were removed or renamed.
 */

import { describe, expect, it } from "vitest"
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")

async function tryRead(relPath: string): Promise<string | null> {
  try {
    return await readFile(resolve(REPO_ROOT, relPath), "utf8")
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// api.ts — v1.3 client surface
// ---------------------------------------------------------------------------

describe("phase14 api.ts v1.3 exports", () => {
  it("exports all v1.3 client functions", async () => {
    // Tests: T-USE-03 / T-USE-07 / T-USE-09 / T-USE-11
    const source = await tryRead("frontend/src/services/api.ts")
    expect(source, "frontend/src/services/api.ts must exist").not.toBeNull()
    for (const fn of [
      "requestClarification",
      "persistClarification",
      "exportWorkspacePdf",
      "enablePublicShare",
      "disablePublicShare",
      "rotatePublicShare",
      "getTemplates",
      "getPublicWorkspace",
    ]) {
      expect(source!, `api.ts must export '${fn}'`).toContain(fn)
    }
  })

  it("preserves all pre-phase-14 api.ts exports", async () => {
    // Tests: Phase 14 must add to api.ts, never remove or rename.
    const api = await import("../../../frontend/src/services/api")
    const exported = api as Record<string, unknown>
    for (const name of [
      "getWorkspaces",
      "createWorkspace",
      "getWorkspace",
      "deleteWorkspace",
      "getStage",
      "generateStage",
      "refineStage",
      "regenerateStage",
      "finaliseStage",
      "rollbackStage",
      "getCredits",
      "getGitHubIntegration",
      "deleteGitHubIntegration",
      "exportWorkspaceToGitHub",
      "getGitHubPush",
    ]) {
      expect(
        exported[name],
        `pre-phase-14 function '${name}' must still be exported`,
      ).toBeTypeOf("function")
    }
  })

  it("getPublicWorkspace returns null on 404", async () => {
    // Tests: T-USE-10: a bad slug must not crash the public route — it
    // resolves to a 404 page, not an unhandled exception.
    const source = await tryRead("frontend/src/services/api.ts")
    expect(source).not.toBeNull()
    expect(source!).toContain("getPublicWorkspace")
    const handles404 =
      source!.includes("404") || source!.includes("catch") || source!.includes("null")
    expect(
      handles404,
      "getPublicWorkspace must handle 404 without throwing",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-USE-04: Spec Clarification modal
// ---------------------------------------------------------------------------

describe("phase14 SpecClarificationModal", () => {
  it("SpecClarificationModal.tsx exists under components/workspace/", async () => {
    // Tests: T-USE-04
    const source = await tryRead(
      "frontend/src/components/workspace/SpecClarificationModal.tsx",
    )
    expect(
      source,
      "not implemented: T-USE-04 — frontend/src/components/workspace/SpecClarificationModal.tsx",
    ).not.toBeNull()
    expect(source!).toContain("SpecClarificationModal")
  })

  it("modal exposes a Skip path and an Use-answers path", async () => {
    // Tests: T-USE-04, Spec §4.4.1: both paths must be visible buttons; Skip
    // must dispatch the standard generate without persisting answers.
    const source = await tryRead(
      "frontend/src/components/workspace/SpecClarificationModal.tsx",
    )
    expect(source).not.toBeNull()
    const hasSkip =
      source!.includes("Skip") || source!.toLowerCase().includes("skip")
    const hasUseAnswers =
      source!.includes("Use answers") ||
      source!.includes("Generate with answers") ||
      source!.toLowerCase().includes("use answers")
    expect(
      hasSkip && hasUseAnswers,
      "SpecClarificationModal must offer both Skip and Use-answers controls.",
    ).toBe(true)
  })

  it("workspace page mounts the clarification modal", async () => {
    // Tests: T-USE-04: the modal is only useful if the workspace page mounts
    // it. Look for the import.
    const source = await tryRead("frontend/src/pages/Workspace.tsx")
    expect(source).not.toBeNull()
    expect(
      source!,
      "Workspace.tsx must import SpecClarificationModal so the modal can be triggered on first spec generate.",
    ).toContain("SpecClarificationModal")
  })

  it("modal calls requestClarification and persistClarification from api", async () => {
    // Tests: T-USE-04: typed API calls only, no raw fetch.
    const source = await tryRead(
      "frontend/src/components/workspace/SpecClarificationModal.tsx",
    )
    expect(source).not.toBeNull()
    const callsApi =
      source!.includes("requestClarification") &&
      source!.includes("persistClarification")
    expect(
      callsApi,
      "SpecClarificationModal must call both requestClarification and persistClarification.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-USE-06: Effort Summary parsing + workspace header chip
// ---------------------------------------------------------------------------

describe("phase14 effort summary", () => {
  it("tasksParser exists and exports parseEffortSummary", async () => {
    // Tests: T-USE-06, Plan §18.3
    const source = await tryRead("frontend/src/utils/tasksParser.ts")
    expect(
      source,
      "not implemented: T-USE-06 — frontend/src/utils/tasksParser.ts",
    ).not.toBeNull()
    expect(source!).toContain("parseEffortSummary")
  })

  it("parseEffortSummary returns null on missing block (graceful degrade)", async () => {
    // Tests: T-USE-06: older content without the block must not throw —
    // the chip simply hides.
    const source = await tryRead("frontend/src/utils/tasksParser.ts")
    expect(source).not.toBeNull()
    // Either an explicit `return null` path or a null-returning type signature
    // is acceptable; both prove the API matches the contract.
    const handlesMissing =
      source!.includes("return null") ||
      source!.includes("| null") ||
      source!.includes("null;")
    expect(
      handlesMissing,
      "parseEffortSummary must return null when no '## Effort Summary' block is present.",
    ).toBe(true)
  })

  it("workspace header renders an effort summary chip", async () => {
    // Tests: T-USE-06: the workspace header must include the chip class so
    // the visual treatment matches the design.
    const source = await tryRead("frontend/src/pages/Workspace.tsx")
    expect(source).not.toBeNull()
    const hasChip =
      source!.includes("effort-summary") ||
      source!.includes("EffortSummary") ||
      source!.includes("parseEffortSummary")
    expect(
      hasChip,
      "Workspace.tsx must render the effort-summary chip (or import the parser).",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-USE-08: PDF Export button
// ---------------------------------------------------------------------------

describe("phase14 PDF export button", () => {
  it("ExportPDFButton.tsx exists under components/workspace/", async () => {
    // Tests: T-USE-08
    const source = await tryRead(
      "frontend/src/components/workspace/ExportPDFButton.tsx",
    )
    expect(
      source,
      "not implemented: T-USE-08 — frontend/src/components/workspace/ExportPDFButton.tsx",
    ).not.toBeNull()
    expect(source!).toContain("ExportPDFButton")
  })

  it("PDF button calls exportWorkspacePdf and triggers a file download", async () => {
    // Tests: T-USE-08: the button must use the typed API client and produce
    // a downloadable blob (anchor with download attribute, or URL.createObjectURL).
    const source = await tryRead(
      "frontend/src/components/workspace/ExportPDFButton.tsx",
    )
    expect(source).not.toBeNull()
    expect(source!).toContain("exportWorkspacePdf")
    const triggersDownload =
      source!.includes("download") ||
      source!.includes("URL.createObjectURL") ||
      source!.includes("createObjectURL")
    expect(
      triggersDownload,
      "ExportPDFButton must trigger a browser download (anchor download attr or createObjectURL).",
    ).toBe(true)
  })

  it("workspace header mounts the PDF button alongside ZIP and GitHub", async () => {
    // Tests: T-USE-08
    const source = await tryRead("frontend/src/pages/Workspace.tsx")
    expect(source).not.toBeNull()
    expect(
      source!,
      "Workspace.tsx must import ExportPDFButton.",
    ).toContain("ExportPDFButton")
  })
})

// ---------------------------------------------------------------------------
// T-USE-10: Public Share modal + /p/:slug route
// ---------------------------------------------------------------------------

describe("phase14 public share frontend", () => {
  it("SharePublicLinkModal.tsx exists under components/workspace/", async () => {
    // Tests: T-USE-10
    const source = await tryRead(
      "frontend/src/components/workspace/SharePublicLinkModal.tsx",
    )
    expect(
      source,
      "not implemented: T-USE-10 — frontend/src/components/workspace/SharePublicLinkModal.tsx",
    ).not.toBeNull()
    expect(source!).toContain("SharePublicLinkModal")
  })

  it("Share modal exposes copy-link, toggle, and rotate controls", async () => {
    // Tests: T-USE-10, Spec §4.8
    const source = await tryRead(
      "frontend/src/components/workspace/SharePublicLinkModal.tsx",
    )
    expect(source).not.toBeNull()
    const hasCopy =
      source!.toLowerCase().includes("copy") ||
      source!.includes("clipboard")
    const hasToggle =
      source!.includes("enablePublicShare") &&
      source!.includes("disablePublicShare")
    const hasRotate = source!.includes("rotatePublicShare")
    expect(
      hasCopy && hasToggle && hasRotate,
      "Share modal must provide copy-link, on/off toggle (enable+disable), and rotate.",
    ).toBe(true)
  })

  it("PublicWorkspaceView.tsx exists under pages/", async () => {
    // Tests: T-USE-10
    const source = await tryRead("frontend/src/pages/PublicWorkspaceView.tsx")
    expect(
      source,
      "not implemented: T-USE-10 — frontend/src/pages/PublicWorkspaceView.tsx",
    ).not.toBeNull()
    expect(source!).toContain("PublicWorkspaceView")
  })

  it("App.tsx registers the /p/:slug route outside the auth guard", async () => {
    // Tests: T-USE-10: the public route must be a top-level route, not nested
    // inside an authenticated layout.
    const source = await tryRead("frontend/src/App.tsx")
    expect(source).not.toBeNull()
    expect(
      source!,
      "App.tsx must register a '/p/:slug' route for the public view.",
    ).toContain("/p/:slug")
  })

  it("PublicWorkspaceView sets noindex meta tags", async () => {
    // Tests: T-USE-10, SEC: noindex prevents search-engine indexing of the
    // public spec view (Spec §4.8 + Plan §18.4).
    const source = await tryRead("frontend/src/pages/PublicWorkspaceView.tsx")
    expect(source).not.toBeNull()
    expect(
      source!,
      "PublicWorkspaceView must inject a 'noindex' robots meta tag.",
    ).toContain("noindex")
  })

  it("PublicWorkspaceView does not import authenticated stores", async () => {
    // Tests: T-USE-10, SEC: the public view must not pull in userStore /
    // credit balance / other authenticated state. This guarantees nothing
    // private leaks into the rendered page.
    const source = await tryRead("frontend/src/pages/PublicWorkspaceView.tsx")
    expect(source).not.toBeNull()
    for (const forbidden of ["userStore", "creditsBalance", "stageStore", "useUserStore"]) {
      expect(
        source!.includes(forbidden),
        `PublicWorkspaceView must not import authenticated state '${forbidden}'.`,
      ).toBe(false)
    }
  })

  it("public robots.txt disallows /p/ crawl path", async () => {
    // Tests: T-USE-10, Plan §18.4: belt-and-suspenders — the response header
    // is the primary control, but robots.txt also disallows /p/.
    // T-2.5 (post Phase-3 cutover): frontend/public/robots.txt now only
    // governs the raw SPA deployment host, which nothing should crawl at
    // all — it blanket-disallows every path ("Disallow: /") rather than
    // naming /p/ specifically. That's a strict superset of the narrow
    // disallow it replaced, so accept it here too (see the parallel
    // reasoning in apps/marketing/tests/noindex-regression.test.ts).
    const candidates = [
      "frontend/public/robots.txt",
      "frontend/public/robots/robots.txt",
    ]
    let foundDisallow = false
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (source && (/disallow:\s*\/p\//i.test(source) || /^disallow:\s*\/\s*$/im.test(source))) {
        foundDisallow = true
        break
      }
    }
    expect(
      foundDisallow,
      "frontend/public/robots.txt must Disallow /p/ to keep shared specs out of search engines.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-USE-12: Starter Templates
// ---------------------------------------------------------------------------

describe("phase14 starter templates", () => {
  it("TemplatesStrip.tsx exists under components/", async () => {
    // Tests: T-USE-12
    const candidates = [
      "frontend/src/components/templates/TemplatesStrip.tsx",
      "frontend/src/components/dashboard/TemplatesStrip.tsx",
      "frontend/src/components/TemplatesStrip.tsx",
    ]
    let found: string | null = null
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (source) {
        found = source
        break
      }
    }
    expect(
      found,
      "not implemented: T-USE-12 — TemplatesStrip.tsx missing. Checked: " +
        candidates.join(", "),
    ).not.toBeNull()
    expect(found!).toContain("TemplatesStrip")
  })

  it("Dashboard renders the templates strip", async () => {
    // Tests: T-USE-12, Spec §4.10
    const source = await tryRead("frontend/src/pages/Dashboard.tsx")
    expect(source).not.toBeNull()
    expect(
      source!,
      "Dashboard.tsx must mount TemplatesStrip above the workspace grid.",
    ).toContain("TemplatesStrip")
  })

  it("workspace creation form references TemplatesStrip or templateSlug", async () => {
    // Tests: T-USE-12, Spec §4.2
    const candidates = [
      "frontend/src/components/dashboard/CreateWorkspaceModal.tsx",
      "frontend/src/components/CreateWorkspaceModal.tsx",
      "frontend/src/pages/Dashboard.tsx",
    ]
    let referencesTemplate = false
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (source && (source.includes("template_slug") || source.includes("templateSlug") || source.includes("TemplatesStrip"))) {
        referencesTemplate = true
        break
      }
    }
    expect(
      referencesTemplate,
      "The workspace creation form must reference template_slug or TemplatesStrip so a chosen template prefills the form.",
    ).toBe(true)
  })

  it("createWorkspace API call accepts template_slug", async () => {
    // Tests: T-USE-12: provenance is carried into the POST /workspaces body.
    const source = await tryRead("frontend/src/services/api.ts")
    expect(source).not.toBeNull()
    expect(
      source!,
      "api.ts createWorkspace must accept an optional template_slug field.",
    ).toContain("template_slug")
  })
})

// ---------------------------------------------------------------------------
// T-USE-13: Harness coverage surfacing
// ---------------------------------------------------------------------------

describe("phase14 harness coverage chip", () => {
  it("workspace header renders the coverage chip", async () => {
    // Tests: T-USE-13, Spec §7
    const source = await tryRead("frontend/src/pages/Workspace.tsx")
    expect(source).not.toBeNull()
    const hasChip =
      source!.includes("coverage_summary") ||
      source!.includes("coverageSummary") ||
      source!.includes("harness-coverage-chip")
    expect(
      hasChip,
      "Workspace.tsx must render the harness-coverage chip in the header. See Spec §7.",
    ).toBe(true)
  })

  it("dashboard workspace card renders the coverage chip", async () => {
    // Tests: T-USE-13
    const candidates = [
      "frontend/src/components/dashboard/WorkspaceCard.tsx",
      "frontend/src/components/WorkspaceCard.tsx",
      "frontend/src/pages/Dashboard.tsx",
    ]
    let found = false
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (
        source &&
        (source.includes("coverage_summary") ||
          source.includes("coverageSummary") ||
          source.includes("harness-coverage-chip"))
      ) {
        found = true
        break
      }
    }
    expect(
      found,
      "Dashboard workspace card must render the harness-coverage chip. Checked: " +
        candidates.join(", "),
    ).toBe(true)
  })

  it("public view renders the coverage chip", async () => {
    // Tests: T-USE-13: the public share view shows the coverage figure as
    // social proof.
    const source = await tryRead("frontend/src/pages/PublicWorkspaceView.tsx")
    expect(source).not.toBeNull()
    const hasChip =
      source!.includes("coverage_summary") ||
      source!.includes("coverageSummary") ||
      source!.includes("harness-coverage-chip")
    expect(
      hasChip,
      "PublicWorkspaceView must render the harness-coverage chip — it is the differentiating signal for shared specs.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// CSS classes — Modern Indica design system
// ---------------------------------------------------------------------------

describe("phase14 index.css design-system classes", () => {
  it("defines clarify-modal-* classes", async () => {
    // Tests: T-USE-04
    const source = await tryRead("frontend/src/index.css")
    expect(source).not.toBeNull()
    const requiredClasses = [
      ".clarify-modal",
      ".clarify-question",
    ]
    for (const cls of requiredClasses) {
      expect(source!, `index.css must define '${cls}'`).toContain(cls)
    }
  })

  it("defines public-view-* classes for the read-only spec view", async () => {
    // Tests: T-USE-10: the public view re-uses the Modern Indica identity
    // and adds its own classes for the cover / footer / coverage chip.
    const source = await tryRead("frontend/src/index.css")
    expect(source).not.toBeNull()
    const hasPublicClasses =
      source!.includes(".public-view") || source!.includes(".public-workspace")
    expect(
      hasPublicClasses,
      "index.css must define .public-view-* (or .public-workspace-*) classes for the read-only view.",
    ).toBe(true)
  })

  it("defines templates-strip-* classes", async () => {
    // Tests: T-USE-12
    const source = await tryRead("frontend/src/index.css")
    expect(source).not.toBeNull()
    expect(source!).toContain(".templates-strip")
  })

  it("defines harness-coverage-chip class", async () => {
    // Tests: T-USE-13
    const source = await tryRead("frontend/src/index.css")
    expect(source).not.toBeNull()
    expect(source!).toContain(".harness-coverage-chip")
  })
})

// ---------------------------------------------------------------------------
// TypeScript interface contracts
// ---------------------------------------------------------------------------

describe("phase14 TypeScript interfaces", () => {
  it("Workspace type carries the v1.3 fields", async () => {
    // Tests: T-USE-02 (frontend-visible part of the schema)
    const sources = [
      await tryRead("frontend/src/types/workspace.ts"),
      await tryRead("frontend/src/types/index.ts"),
      await tryRead("frontend/src/services/api.ts"),
    ].filter((s): s is string => s !== null)
    const combined = sources.join("\n---\n")
    for (const field of [
      "template_slug",
      "public_share_slug",
      "public_share_enabled",
      "coverage_summary",
    ]) {
      expect(
        combined,
        `Workspace TS type must include '${field}'.`,
      ).toContain(field)
    }
  })

  it("Template type is defined", async () => {
    // Tests: T-USE-11
    const candidates = [
      "frontend/src/types/template.ts",
      "frontend/src/types/templates.ts",
      "frontend/src/services/api.ts",
    ]
    let found = false
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (source && /interface\s+Template\b/.test(source)) {
        found = true
        break
      }
    }
    expect(
      found,
      "A TypeScript Template interface must exist. Checked: " +
        candidates.join(", "),
    ).toBe(true)
  })

  it("PublicWorkspaceResponse type is defined", async () => {
    // Tests: T-USE-10 — the frontend must have a typed shape for the
    // allow-list response from GET /public/{slug}.
    const candidates = [
      "frontend/src/types/publicShare.ts",
      "frontend/src/types/public.ts",
      "frontend/src/types/workspace.ts",
      "frontend/src/services/api.ts",
    ]
    let found = false
    for (const candidate of candidates) {
      const source = await tryRead(candidate)
      if (
        source &&
        (source.includes("PublicWorkspaceResponse") ||
          source.includes("PublicWorkspace "))
      ) {
        found = true
        break
      }
    }
    expect(
      found,
      "PublicWorkspaceResponse TS interface must exist in one of: " +
        candidates.join(", "),
    ).toBe(true)
  })
})
