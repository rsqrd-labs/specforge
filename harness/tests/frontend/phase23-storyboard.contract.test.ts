/**
 * Harness contracts for Plan v1.md §23, Phase 23 - Storyboard Product Keynote
 * Generation (frontend layer: T-257 through T-260 plus public/share/download
 * client contracts from T-251/T-256).
 *
 * These tests are RED before Storyboard is implemented and GREEN after.
 *
 * Invariants:
 *   - api.ts exposes typed Storyboard functions for owner and public flows.
 *   - types/storyboard.ts models Storyboard status, six fixed acts, payload,
 *     diagrams, notes, source map, public permissions, and download kinds.
 *   - /storyboards/:id is an authenticated owner route.
 *   - /sb/:slug is an unauthenticated public route and never imports auth/user
 *     stores or credit UI.
 *   - Workspace shows Create Storyboard only when the four stages are finalised,
 *     then Open Storyboard / stale / regenerate states after generation.
 *   - CreateStoryboardModal shows the 25-credit cost, included artifacts,
 *     post-action balance, insufficient-balance billing path, and finalised-stage
 *     preconditions.
 *   - StoryboardDeck is full-screen, keyboard navigable, presenter/source aware,
 *     and does not persist source content in localStorage.
 *   - ArchitectureReveal renders the required architecture layers with an
 *     accessible non-canvas fallback.
 *   - PresenterMode keeps notes private unless public notes permission is
 *     enabled.
 *   - SourceLayer uses bounded source excerpts from SPEC/PLAN/HARNESS/TASKS and
 *     respects allow_source_layer.
 *   - Share modal and download menu expose owner permissions without leaking
 *     notes/source/appendix by default.
 */

import { describe, expect, it } from "vitest"
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")

const REQUIRED_ACTS = [
  "Opening Thesis",
  "Product Vision",
  "Product Walkthrough",
  "Technical Architecture",
  "Trust, Security, Reliability",
  "Launch Close",
]

const REQUIRED_LAYERS = [
  "client",
  "frontend",
  "api",
  "data",
  "llm",
  "integrations",
  "trust",
  "recovery",
]

async function tryRead(relPath: string): Promise<string | null> {
  try {
    return await readFile(resolve(REPO_ROOT, relPath), "utf8")
  } catch {
    return null
  }
}

function expectContainsAll(source: string, required: string[], context: string) {
  const missing = required.filter((term) => !source.includes(term))
  expect(missing, `${context} missing required terms: ${missing.join(", ")}`).toEqual([])
}

function expectContainsAny(source: string, options: string[], context: string) {
  expect(
    options.some((option) => source.includes(option)),
    `${context} must include one of: ${options.join(", ")}`,
  ).toBe(true)
}

// ---------------------------------------------------------------------------
// API client and type contracts
// ---------------------------------------------------------------------------

describe("phase23 Storyboard API client", () => {
  it("api.ts exports all owner and public Storyboard functions", async () => {
    const source = await tryRead("frontend/src/services/api.ts")
    expect(source, "frontend/src/services/api.ts must exist").not.toBeNull()
    for (const fn of [
      "listStoryboards",
      "getLatestStoryboard",
      "generateStoryboard",
      "getStoryboard",
      "regenerateStoryboard",
      "regenerateStoryboardSection",
      "getStoryboardPresenter",
      "downloadStoryboard",
      "shareStoryboard",
      "disableStoryboardShare",
      "rotateStoryboardShare",
      "getPublicStoryboard",
      "downloadPublicStoryboard",
    ]) {
      expect(source!, `api.ts must export '${fn}'`).toContain(fn)
    }
  })

  it("api.ts calls the exact owner and public Storyboard endpoint paths", async () => {
    const source = await tryRead("frontend/src/services/api.ts")
    expect(source).not.toBeNull()
    for (const path of [
      "/storyboards",
      "/storyboards/latest",
      "/storyboards/",
      "/regenerate",
      "/sections/",
      "/presenter",
      "/download/html",
      "/download/pdf",
      "/download/notes",
      "/download/demo-script",
      "/download/appendix",
      "/share",
      "/share/rotate",
      "/storyboards/public/",
    ]) {
      expect(source!, `api.ts must call Storyboard path fragment '${path}'`).toContain(path)
    }
  })

  it("api.ts handles public Storyboard 404s without throwing an unhandled exception", async () => {
    const source = await tryRead("frontend/src/services/api.ts")
    expect(source).not.toBeNull()
    const publicFnStart = source!.indexOf("getPublicStoryboard")
    const publicSlice = publicFnStart >= 0 ? source!.slice(publicFnStart, publicFnStart + 1600) : source!
    expect(
      publicSlice.includes("404") || publicSlice.includes("null") || publicSlice.includes("catch"),
      "getPublicStoryboard must map unknown/disabled slugs to a safe not-found state.",
    ).toBe(true)
  })
})

describe("phase23 Storyboard TypeScript types", () => {
  it("types/storyboard.ts exists and defines the core Storyboard contracts", async () => {
    const source = await tryRead("frontend/src/types/storyboard.ts")
    expect(
      source,
      "not implemented: T-257/T-260 - frontend/src/types/storyboard.ts",
    ).not.toBeNull()
    for (const typeName of [
      "StoryboardStatus",
      "StoryboardSummary",
      "StoryboardDetail",
      "StoryboardPayload",
      "StoryboardSection",
      "StoryboardSlide",
      "StoryboardDiagram",
      "SpeakerNote",
      "SourceRef",
      "StoryboardPublicResponse",
      "StoryboardShareRequest",
      "StoryboardDownloadKind",
    ]) {
      expect(source!, `types/storyboard.ts must define ${typeName}`).toContain(typeName)
    }
  })

  it("types/storyboard.ts encodes statuses, six acts, sources, permissions, and downloads", async () => {
    const source = await tryRead("frontend/src/types/storyboard.ts")
    expect(source).not.toBeNull()
    expectContainsAll(source!, ["generating", "ready", "failed", "stale"], "StoryboardStatus")
    expectContainsAll(source!, REQUIRED_ACTS, "Storyboard section titles")
    expectContainsAll(source!, ["SPEC", "PLAN", "HARNESS", "TASKS"], "SourceRef source enum")
    expectContainsAll(
      source!,
      ["allow_pdf_download", "allow_notes_download", "allow_appendix_download", "allow_source_layer"],
      "Storyboard public permissions",
    )
    expectContainsAll(source!, ["html", "pdf", "notes", "demo-script", "appendix"], "Download kinds")
  })

  it("types/storyboard.ts carries immutable source versions and generated artifacts", async () => {
    const source = await tryRead("frontend/src/types/storyboard.ts")
    expect(source).not.toBeNull()
    expectContainsAll(
      source!,
      [
        "source_stage_version_ids",
        "source_map",
        "speaker_notes_md",
        "demo_script_md",
        "technical_appendix_md",
        "diagrams",
        "theme",
      ],
      "Storyboard detail type",
    )
  })
})

// ---------------------------------------------------------------------------
// Routes and workspace owner flow
// ---------------------------------------------------------------------------

describe("phase23 routes and workspace owner flow", () => {
  it("App.tsx registers authenticated owner and unauthenticated public Storyboard routes", async () => {
    const source = await tryRead("frontend/src/App.tsx")
    expect(source, "frontend/src/App.tsx must exist").not.toBeNull()
    expect(source!).toContain("/storyboards/:id")
    expect(source!).toContain("/sb/:slug")
    expect(source!).toContain("Storyboard")
    expect(source!).toContain("StoryboardPublic")
  })

  it("StoryboardPublic page is public-only and does not import auth, user, or credit state", async () => {
    const source = await tryRead("frontend/src/pages/StoryboardPublic.tsx")
    expect(
      source,
      "not implemented: T-256/T-257 - frontend/src/pages/StoryboardPublic.tsx",
    ).not.toBeNull()
    for (const forbidden of ["ProtectedRoute", "userStore", "useUserStore", "CreditMeter", "credit_balance"]) {
      expect(source!, `StoryboardPublic.tsx must not import/render ${forbidden}`).not.toContain(forbidden)
    }
    expectContainsAny(source!, ["getPublicStoryboard", "downloadPublicStoryboard"], "StoryboardPublic public API usage")
    expectContainsAny(source!, ["noindex", "X-Robots-Tag", "robots"], "StoryboardPublic noindex handling")
  })

  it("Workspace.tsx wires the Create/Open Storyboard flow into the workspace header", async () => {
    const source = await tryRead("frontend/src/pages/Workspace.tsx")
    expect(source).not.toBeNull()
    expectContainsAll(source!, ["CreateStoryboardModal", "StoryboardToolbar"], "Workspace Storyboard owner flow")
    expectContainsAny(source!, ["Create Storyboard", "create storyboard"], "Workspace create Storyboard CTA")
    expectContainsAny(source!, ["Open Storyboard", "open storyboard"], "Workspace open Storyboard CTA")
    expectContainsAny(source!, ["stale", "is_stale"], "Workspace stale Storyboard state")
  })

  it("Workspace gates Create Storyboard on all four finalised stages", async () => {
    const source = await tryRead("frontend/src/pages/Workspace.tsx")
    expect(source).not.toBeNull()
    for (const stage of ["spec", "plan", "harness", "tasks"]) {
      expect(source!.toLowerCase(), `Workspace Storyboard gating must inspect ${stage}`).toContain(stage)
    }
    expect(source!.toLowerCase()).toContain("finalised")
  })
})

// ---------------------------------------------------------------------------
// Create modal and toolbar
// ---------------------------------------------------------------------------

describe("phase23 CreateStoryboardModal and toolbar", () => {
  it("CreateStoryboardModal shows price, artifacts, balance, and billing fallback", async () => {
    const source = await tryRead("frontend/src/components/workspace/CreateStoryboardModal.tsx")
    expect(
      source,
      "not implemented: T-257 - frontend/src/components/workspace/CreateStoryboardModal.tsx",
    ).not.toBeNull()
    expect(source!).toContain("25")
    expectContainsAll(
      source!,
      ["architecture", "speaker", "demo", "appendix", "share", "PDF", "HTML"],
      "CreateStoryboardModal artifact list",
    )
    expectContainsAny(source!, ["remaining", "post", "balance"], "CreateStoryboardModal balance preview")
    expectContainsAny(source!, ["/billing", "Billing"], "CreateStoryboardModal insufficient balance fallback")
  })

  it("CreateStoryboardModal blocks insufficient balance and non-finalised prerequisites", async () => {
    const source = await tryRead("frontend/src/components/workspace/CreateStoryboardModal.tsx")
    expect(source).not.toBeNull()
    expectContainsAny(source!, ["credit", "balance"], "CreateStoryboardModal credit check")
    expectContainsAny(source!, ["< 25", "balance < 25", "insufficient"], "CreateStoryboardModal insufficient balance check")
    expectContainsAny(source!.toLowerCase(), ["finalised", "not finalised", "all four"], "CreateStoryboardModal finalised stage check")
    expectContainsAny(source!.toLowerCase(), ["stale", "prerequisite"], "CreateStoryboardModal stale prerequisite check")
  })

  it("CreateStoryboardModal starts generation and surfaces refund-aware failure language", async () => {
    const source = await tryRead("frontend/src/components/workspace/CreateStoryboardModal.tsx")
    expect(source).not.toBeNull()
    expect(source!).toContain("generateStoryboard")
    expectContainsAny(source!, ["poll", "getLatestStoryboard", "status"], "CreateStoryboardModal generation polling")
    expectContainsAny(source!.toLowerCase(), ["refund", "refunded"], "CreateStoryboardModal failure refund language")
  })

  it("StoryboardToolbar exposes present, share, download, regenerate, and notes actions", async () => {
    const source = await tryRead("frontend/src/components/workspace/StoryboardToolbar.tsx")
    expect(
      source,
      "not implemented: T-257 - frontend/src/components/workspace/StoryboardToolbar.tsx",
    ).not.toBeNull()
    for (const action of ["Present", "Share", "Download", "Regenerate", "Notes"]) {
      expect(source!, `StoryboardToolbar must expose ${action}`).toContain(action)
    }
  })
})

// ---------------------------------------------------------------------------
// Deck, architecture reveal, presenter mode, source layer
// ---------------------------------------------------------------------------

describe("phase23 StoryboardDeck", () => {
  it("StoryboardDeck exists and renders the six-act payload", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardDeck.tsx")
    expect(
      source,
      "not implemented: T-258 - frontend/src/components/storyboard/StoryboardDeck.tsx",
    ).not.toBeNull()
    expect(source!).toContain("StoryboardPayload")
    for (const act of REQUIRED_ACTS) {
      expect(source!, `StoryboardDeck should recognise/render ${act}`).toContain(act)
    }
  })

  it("StoryboardDeck supports required keyboard shortcuts", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardDeck.tsx")
    expect(source).not.toBeNull()
    for (const key of ["ArrowRight", "ArrowLeft", "Space", "Escape"]) {
      expect(source!, `StoryboardDeck must handle ${key}`).toContain(key)
    }
    for (const key of ["f", "p", "s"]) {
      expect(source!.toLowerCase(), `StoryboardDeck must handle ${key.toUpperCase()} shortcut`).toContain(key)
    }
    expectContainsAny(source!, ["requestFullscreen", "fullscreen"], "StoryboardDeck fullscreen support")
  })

  it("StoryboardDeck does not persist source content in localStorage", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardDeck.tsx")
    expect(source).not.toBeNull()
    const sourceLayerSlice = source!.toLowerCase().includes("source")
      ? source!.slice(source!.toLowerCase().indexOf("source"))
      : source!
    expect(sourceLayerSlice).not.toContain("localStorage")
    expect(sourceLayerSlice).not.toContain("sessionStorage")
  })
})

describe("phase23 ArchitectureReveal", () => {
  it("ArchitectureReveal renders all required architecture layers in deterministic order", async () => {
    const source = await tryRead("frontend/src/components/storyboard/ArchitectureReveal.tsx")
    expect(
      source,
      "not implemented: T-258 - frontend/src/components/storyboard/ArchitectureReveal.tsx",
    ).not.toBeNull()
    for (const layer of REQUIRED_LAYERS) {
      expect(source!.toLowerCase(), `ArchitectureReveal missing layer ${layer}`).toContain(layer)
    }
    expectContainsAny(source!, ["step", "currentStep", "sequence", "ordered"], "ArchitectureReveal deterministic reveal")
  })

  it("ArchitectureReveal has accessible non-canvas fallback for PDF and screen readers", async () => {
    const source = await tryRead("frontend/src/components/storyboard/ArchitectureReveal.tsx")
    expect(source).not.toBeNull()
    expectContainsAny(source!, ["aria-label", "sr-only", "role=", "screen reader"], "ArchitectureReveal accessibility")
    expectContainsAny(source!, ["fallback", "ordered", "<ol", "summary"], "ArchitectureReveal textual fallback")
    const usesCanvasOnly = source!.includes("<canvas") && !source!.includes("<svg") && !source!.includes("<ol")
    expect(usesCanvasOnly, "ArchitectureReveal must not require canvas for core meaning").toBe(false)
  })
})

describe("phase23 PresenterMode and SourceLayer", () => {
  it("PresenterMode shows notes, next slide, timer, transitions, demo cues, and backup points", async () => {
    const source = await tryRead("frontend/src/components/storyboard/PresenterMode.tsx")
    expect(
      source,
      "not implemented: T-259 - frontend/src/components/storyboard/PresenterMode.tsx",
    ).not.toBeNull()
    expectContainsAll(
      source!,
      ["current", "next", "timer", "speaker", "transition", "pause", "demo", "backup"],
      "PresenterMode",
    )
  })

  it("PresenterMode keeps notes private unless public notes permission is enabled", async () => {
    const source = await tryRead("frontend/src/components/storyboard/PresenterMode.tsx")
    expect(source).not.toBeNull()
    expectContainsAny(source!, ["allow_notes_download", "canViewNotes", "isOwner"], "PresenterMode notes permission")
    expectContainsAny(source!.toLowerCase(), ["public", "owner"], "PresenterMode owner/public distinction")
  })

  it("SourceLayer maps claims to bounded SPEC/PLAN/HARNESS/TASKS excerpts", async () => {
    const source = await tryRead("frontend/src/components/storyboard/SourceLayer.tsx")
    expect(
      source,
      "not implemented: T-260 - frontend/src/components/storyboard/SourceLayer.tsx",
    ).not.toBeNull()
    expect(source!).toContain("source_map")
    expectContainsAll(source!, ["SPEC", "PLAN", "HARNESS", "TASKS"], "SourceLayer badges")
    expectContainsAny(source!, ["slice", "substring", "maxLength", "1200"], "SourceLayer bounded excerpt")
  })

  it("SourceLayer respects public allow_source_layer permission", async () => {
    const source = await tryRead("frontend/src/components/storyboard/SourceLayer.tsx")
    expect(source).not.toBeNull()
    expect(source!).toContain("allow_source_layer")
    expectContainsAny(source!.toLowerCase(), ["public", "owner", "permission"], "SourceLayer public permission")
  })
})

// ---------------------------------------------------------------------------
// Sharing, downloads, launch page, and public safety
// ---------------------------------------------------------------------------

describe("phase23 sharing and downloads", () => {
  it("StoryboardShareModal toggles PDF, notes, appendix, source, disable, and rotate", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardShareModal.tsx")
    expect(
      source,
      "not implemented: T-256/T-257 - frontend/src/components/storyboard/StoryboardShareModal.tsx",
    ).not.toBeNull()
    expectContainsAll(
      source!,
      [
        "allow_pdf_download",
        "allow_notes_download",
        "allow_appendix_download",
        "allow_source_layer",
        "disableStoryboardShare",
        "rotateStoryboardShare",
      ],
      "StoryboardShareModal permissions",
    )
  })

  it("StoryboardShareModal defaults private materials to disabled", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardShareModal.tsx")
    expect(source).not.toBeNull()
    for (const permission of ["allow_notes_download", "allow_appendix_download", "allow_source_layer"]) {
      const index = source!.indexOf(permission)
      const slice = index >= 0 ? source!.slice(index, index + 300) : ""
      expect(
        slice.includes("false") || source!.includes(`default${permission}`),
        `${permission} must default to false in public sharing UI.`,
      ).toBe(true)
    }
  })

  it("StoryboardDownloadMenu exposes all owner downloads and public permission filtering", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardDownloadMenu.tsx")
    expect(
      source,
      "not implemented: T-255/T-257 - frontend/src/components/storyboard/StoryboardDownloadMenu.tsx",
    ).not.toBeNull()
    for (const kind of ["html", "pdf", "notes", "demo-script", "appendix"]) {
      expect(source!, `StoryboardDownloadMenu missing ${kind}`).toContain(kind)
    }
    expectContainsAny(source!, ["allow_pdf_download", "allow_notes_download", "allow_appendix_download"], "Download permission filtering")
  })

  it("StoryboardLaunchPage renders first-screen launch content and actions", async () => {
    const source = await tryRead("frontend/src/components/storyboard/StoryboardLaunchPage.tsx")
    expect(
      source,
      "not implemented: T-256/T-258 - frontend/src/components/storyboard/StoryboardLaunchPage.tsx",
    ).not.toBeNull()
    expectContainsAny(source!, ["Present", "Start", "Open"], "Launch page present action")
    expectContainsAny(source!, ["Download", "PDF"], "Launch page download action")
    expectContainsAny(source!, ["Notes", "Speaker"], "Launch page notes action")
    expectContainsAny(source!, ["ArchitectureReveal", "architecture"], "Launch page architecture preview")
  })

  it("Public Storyboard page never exposes private owner fields", async () => {
    const source = await tryRead("frontend/src/pages/StoryboardPublic.tsx")
    expect(source).not.toBeNull()
    for (const forbidden of [
      "user_id",
      "workspace_id",
      "credit_ledger_id",
      "source_stage_version_ids",
      "credit_balance",
      "billing",
      "previous_versions",
    ]) {
      expect(source!, `StoryboardPublic must not render ${forbidden}`).not.toContain(forbidden)
    }
  })
})

// ---------------------------------------------------------------------------
// Frontend tests expected from the implementation phase
// ---------------------------------------------------------------------------

describe("phase23 implementation test coverage", () => {
  it("frontend Storyboard implementation includes focused unit tests", async () => {
    const possibleTests = [
      "frontend/src/components/storyboard/StoryboardDeck.test.tsx",
      "frontend/src/components/storyboard/ArchitectureReveal.test.tsx",
      "frontend/src/components/storyboard/PresenterMode.test.tsx",
      "frontend/src/components/storyboard/SourceLayer.test.tsx",
      "frontend/src/components/storyboard/StoryboardShareModal.test.tsx",
      "frontend/src/components/workspace/CreateStoryboardModal.test.tsx",
    ]
    const found: string[] = []
    for (const relPath of possibleTests) {
      const source = await tryRead(relPath)
      if (source) found.push(relPath)
    }
    expect(
      found.length,
      `Expected focused Storyboard component tests to exist. Looked for: ${possibleTests.join(", ")}`,
    ).toBeGreaterThanOrEqual(4)
  })
})
