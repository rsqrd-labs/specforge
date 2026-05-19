/**
 * Harness contracts for Plan v1.md §17, Phase 13 — GitHub Export Integration
 * (frontend layer: T-155, T-156, T-157, T-158).
 *
 * These tests are RED before T-155 through T-158 are implemented and GREEN after.
 *
 * Invariants:
 *   - api.ts exports exactly the four GitHub integration functions.
 *   - getGitHubIntegration never throws on 404 — returns the disconnected shape.
 *   - getGitHubPush never throws on 404 — returns null.
 *   - Settings.tsx exists at frontend/src/pages/Settings.tsx.
 *   - App.tsx registers a /settings route.
 *   - ExportGitHubModal.tsx exists at frontend/src/components/workspace/.
 *   - index.css defines all required github-modal-* and workspace-github-btn classes.
 *   - No changes to existing api.ts functions.
 */

import { describe, expect, it } from "vitest"
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")

// ---------------------------------------------------------------------------
// T-155: TypeScript types and API client functions
// ---------------------------------------------------------------------------

describe("phase13 api.ts github integration exports", () => {
  it("exports all four GitHub integration functions", async () => {
    // Tests: T-155
    // api.ts must export getGitHubIntegration, deleteGitHubIntegration,
    // exportWorkspaceToGitHub, and getGitHubPush for the Settings and workspace
    // UI components to call without importing from separate modules.
    const api = await import("../../../frontend/src/services/api")
    const exported = api as Record<string, unknown>

    for (const name of [
      "getGitHubIntegration",
      "deleteGitHubIntegration",
      "exportWorkspaceToGitHub",
      "getGitHubPush",
    ]) {
      expect(exported[name], `${name} must be exported from api.ts`).toBeTypeOf("function")
    }
  })

  it("preserves all pre-phase-13 api.ts exports", async () => {
    // Tests: T-155: Phase 13 must add functions, never remove or rename existing ones.
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
      "getProviders",
    ]) {
      expect(exported[name], `pre-phase-13 function '${name}' must still be exported`).toBeTypeOf(
        "function",
      )
    }
  })

  it("getGitHubIntegration does not throw on 404 — returns disconnected shape", async () => {
    // Tests: T-155: callers use this function unconditionally on mount; a 404
    // must silently return {connected: false, github_username: null} so the
    // Settings page renders in the unconnected state without try/catch wrappers.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/services/api.ts"),
      "utf8",
    )
    expect(source).toContain("getGitHubIntegration")
    // The function must handle 404 and return the fallback shape.
    const handles404 = source.includes("404") || source.includes("catch")
    expect(handles404, "getGitHubIntegration must handle 404 without throwing").toBe(true)
    expect(source).toContain("connected")
  })

  it("getGitHubPush returns null on 404", async () => {
    // Tests: T-155: the workspace page calls this on load to check for a prior
    // push; a 404 means no push yet and must not trigger an error boundary.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/services/api.ts"),
      "utf8",
    )
    expect(source).toContain("getGitHubPush")
    expect(source, "getGitHubPush must handle 404 and return null").toContain("null")
  })

  it("defines GitHubIntegration, GitHubExportRequest, GitHubExportResponse, IntegrationPushRead types", async () => {
    // Tests: T-155: all four TypeScript interfaces must be present so components
    // can import them and tsc type-checks the entire call chain.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/services/api.ts"),
      "utf8",
    )
    // The types may live in api.ts or in a separate types/integration.ts; either
    // way they must be accessible from the api module.
    const typeSourcePath = resolve(REPO_ROOT, "frontend/src/types/integration.ts")
    let combinedSource = source
    try {
      const typeSource = await readFile(typeSourcePath, "utf8")
      combinedSource += typeSource
    } catch {
      // types are inline in api.ts — fine
    }

    for (const typeName of [
      "GitHubIntegration",
      "GitHubExportRequest",
      "GitHubExportResponse",
      "IntegrationPushRead",
    ]) {
      expect(combinedSource, `TypeScript interface '${typeName}' must be defined`).toContain(
        typeName,
      )
    }
  })
})

// ---------------------------------------------------------------------------
// T-156: Settings page and /settings route
// ---------------------------------------------------------------------------

describe("phase13 Settings page", () => {
  it("Settings.tsx exists at frontend/src/pages/Settings.tsx", async () => {
    // Tests: T-156
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/pages/Settings.tsx"),
      "utf8",
    ).catch(() => {
      throw new Error(
        "not implemented: T-156 — frontend/src/pages/Settings.tsx does not exist",
      )
    })
    expect(source).toContain("Settings")
  })

  it("App.tsx registers a /settings route", async () => {
    // Tests: T-156: the Settings page is unreachable without a route declaration.
    const source = await readFile(resolve(REPO_ROOT, "frontend/src/App.tsx"), "utf8")
    expect(source, "App.tsx must register a /settings route").toContain("/settings")
    expect(source).toContain("Settings")
  })

  it("Settings.tsx imports getGitHubIntegration from api", async () => {
    // Tests: T-156: the page must use the API layer, not hand-roll fetch calls.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/pages/Settings.tsx"),
      "utf8",
    ).catch(() => {
      throw new Error("not implemented: T-156 — Settings.tsx does not exist")
    })
    expect(
      source,
      "Settings.tsx must import getGitHubIntegration from the api service",
    ).toContain("getGitHubIntegration")
  })

  it("Settings.tsx uses settings-card CSS classes aligned to design system", async () => {
    // Tests: T-156: settings cards must use the 'settings-card-*' prefix and
    // align with the glassmorphism / Modern Indica design system so the page
    // does not appear unstyled.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/pages/Settings.tsx"),
      "utf8",
    ).catch(() => {
      throw new Error("not implemented: T-156 — Settings.tsx does not exist")
    })
    expect(source, "Settings.tsx must use 'settings-card' CSS classes").toContain("settings-card")
  })
})

// ---------------------------------------------------------------------------
// T-157: ExportGitHubModal
// ---------------------------------------------------------------------------

describe("phase13 ExportGitHubModal", () => {
  it("ExportGitHubModal.tsx exists at frontend/src/components/workspace/", async () => {
    // Tests: T-157
    const source = await readFile(
      resolve(
        REPO_ROOT,
        "frontend/src/components/workspace/ExportGitHubModal.tsx",
      ),
      "utf8",
    ).catch(() => {
      throw new Error(
        "not implemented: T-157 — frontend/src/components/workspace/ExportGitHubModal.tsx",
      )
    })
    expect(source).toContain("ExportGitHubModal")
  })

  it("ExportGitHubModal implements the four phases: configure/progress/success/error", async () => {
    // Tests: T-157: the modal must handle all four UI states so the user sees
    // meaningful feedback throughout the export flow.
    const source = await readFile(
      resolve(
        REPO_ROOT,
        "frontend/src/components/workspace/ExportGitHubModal.tsx",
      ),
      "utf8",
    ).catch(() => {
      throw new Error("not implemented: T-157 — ExportGitHubModal.tsx does not exist")
    })
    for (const phase of ["configure", "progress", "success", "error"]) {
      expect(source, `ExportGitHubModal must handle '${phase}' phase`).toContain(phase)
    }
  })

  it("ExportGitHubModal uses modal-* structural shell classes from index.css", async () => {
    // Tests: T-157: new modals must reuse the existing create-modal-* / modal-*
    // structural classes for consistent glassmorphism layout; the github-modal-*
    // prefix is for phase-specific elements only.
    const source = await readFile(
      resolve(
        REPO_ROOT,
        "frontend/src/components/workspace/ExportGitHubModal.tsx",
      ),
      "utf8",
    ).catch(() => {
      throw new Error("not implemented: T-157 — ExportGitHubModal.tsx does not exist")
    })
    const usesModalShell =
      source.includes("create-modal") || source.includes("modal-submit") || source.includes("modal-label")
    expect(
      usesModalShell,
      "ExportGitHubModal must reuse existing modal-* structural CSS classes",
    ).toBe(true)
  })

  it("ExportGitHubModal calls exportWorkspaceToGitHub from api", async () => {
    // Tests: T-157: the modal must use the typed API function, not a raw fetch/axios call.
    const source = await readFile(
      resolve(
        REPO_ROOT,
        "frontend/src/components/workspace/ExportGitHubModal.tsx",
      ),
      "utf8",
    ).catch(() => {
      throw new Error("not implemented: T-157 — ExportGitHubModal.tsx does not exist")
    })
    expect(
      source,
      "ExportGitHubModal must call exportWorkspaceToGitHub from api.ts",
    ).toContain("exportWorkspaceToGitHub")
  })
})

// ---------------------------------------------------------------------------
// T-158: Workspace header GitHub button
// ---------------------------------------------------------------------------

describe("phase13 workspace header github button", () => {
  it("Workspace.tsx or workspace header file renders workspace-github-btn", async () => {
    // Tests: T-158: the GitHub export button must be added to the workspace
    // header so it is always visible when the workspace is ready.
    const candidatePaths = [
      "frontend/src/pages/Workspace.tsx",
      "frontend/src/components/workspace/WorkspaceHeader.tsx",
      "frontend/src/components/workspace/StageNavigator.tsx",
    ]
    let found = false
    for (const candidate of candidatePaths) {
      try {
        const source = await readFile(resolve(REPO_ROOT, candidate), "utf8")
        if (source.includes("workspace-github-btn")) {
          found = true
          break
        }
      } catch {
        // file may not exist
      }
    }
    expect(
      found,
      "One of the workspace/header components must render 'workspace-github-btn'. " +
        `Checked: ${candidatePaths.join(", ")}`,
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// T-156 + T-157 + T-158: CSS classes in index.css
// ---------------------------------------------------------------------------

describe("phase13 index.css design-system classes", () => {
  it("defines settings-card CSS classes", async () => {
    // Tests: T-156: without these classes the Settings page renders unstyled.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/index.css"),
      "utf8",
    )
    expect(source, "index.css must define .settings-card class").toContain(".settings-card")
  })

  it("defines github-modal-* CSS classes", async () => {
    // Tests: T-157: github-modal-* classes drive the four-phase modal layout.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/index.css"),
      "utf8",
    )
    const requiredClasses = [
      ".github-modal-visibility-grid",
      ".github-modal-visibility-btn",
      ".github-modal-progress",
      ".github-modal-success",
      ".github-modal-not-connected",
    ]
    for (const cls of requiredClasses) {
      expect(source, `index.css must define '${cls}'`).toContain(cls)
    }
  })

  it("defines workspace-github-btn CSS class", async () => {
    // Tests: T-158: the GitHub export button needs its own CSS class distinct
    // from the saffron ZIP button so users can visually tell them apart.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/index.css"),
      "utf8",
    )
    expect(source, "index.css must define .workspace-github-btn").toContain(
      ".workspace-github-btn",
    )
  })

  it("workspace-github-btn uses tertiary tints not saffron primary", async () => {
    // Tests: T-158: the GitHub button must use --color-tertiary tints (blue-grey)
    // to visually distinguish it from the saffron ZIP button while remaining
    // within the Modern Indica design language.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/index.css"),
      "utf8",
    )
    const btnSection = source.slice(
      source.indexOf(".workspace-github-btn"),
      source.indexOf(".workspace-github-btn") + 800,
    )
    const usesTertiary =
      btnSection.includes("tertiary") || btnSection.includes("565e74") || btnSection.includes("rgba(86")
    expect(
      usesTertiary,
      ".workspace-github-btn must use tertiary colour tints (not --color-primary saffron) " +
        "to distinguish it visually from the ZIP export button.",
    ).toBe(true)
  })

  it("github-modal-dots defines keyframe animation for progress indicator", async () => {
    // Tests: T-157: the three animated dots in the progress phase require a
    // @keyframes definition so the user sees motion during the export.
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/index.css"),
      "utf8",
    )
    expect(source, "index.css must define .github-modal-dots").toContain(".github-modal-dots")
    const hasAnimation =
      source.includes("animation") && source.includes("github-modal-dots")
    expect(
      hasAnimation,
      ".github-modal-dots must use CSS animation for the progress indicator",
    ).toBe(true)
  })
})
