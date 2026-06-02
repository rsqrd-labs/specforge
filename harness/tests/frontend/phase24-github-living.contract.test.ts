/**
 * Harness contracts for Plan v1.md §24, Phase 24 — GitHub Living System of
 * Record (frontend layer: T-275 plus the api/type contracts for the install
 * flow, export modes, sync state, and increments).
 *
 * These tests are RED before the frontend work lands and GREEN after. They are
 * the verifiability layer for the coding agent on the client side.
 *
 * Invariants:
 *   - api.ts exposes typed functions for the App install flow, mode-aware
 *     export, sync/resync/backfill, and increments/ideas — and calls the exact
 *     backend paths from spec §11.
 *   - getGitHubSync / getGitHubPush never throw on 404 — they return a safe
 *     not-found/empty state (a stale or never-pushed workspace is normal).
 *   - types/github.ts models the install status, export_mode union, per-task
 *     sync state (open|done, done_via pr_merge|manual), drift (out_of_sync),
 *     and the increment timeline.
 *   - TaskCompletionPanel renders shipped/total with deep links to issue + PR
 *     and is a sibling of CoveragePanel / TaskValidationPanel.
 *   - A drift banner appears when out_of_sync and calls the resync endpoint.
 *   - A disconnected state appears when the installation is suspended/removed.
 *   - Settings shows "Install GitHub App" for a non-installed user and the
 *     installed account + repo count when installed (App model, not OAuth token).
 *   - The export modal exposes the files_to_default | pr_with_tests choice.
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

/** Read the first frontend file that exists from a list of candidates. */
async function tryReadAny(relPaths: string[]): Promise<{ path: string; src: string } | null> {
  for (const p of relPaths) {
    const src = await tryRead(p)
    if (src !== null) return { path: p, src }
  }
  return null
}

function expectContainsAll(source: string, required: string[], context: string) {
  const missing = required.filter((term) => !source.includes(term))
  expect(missing, `${context} missing required terms: ${missing.join(", ")}`).toEqual([])
}

function expectContainsAny(source: string, options: string[], context: string) {
  expect(
    options.some((o) => source.includes(o)),
    `${context} must include one of: ${options.join(", ")}`,
  ).toBe(true)
}

// ---------------------------------------------------------------------------
// T-266 / T-275 — API client surface
// ---------------------------------------------------------------------------

describe("phase24 api.ts GitHub living-integration surface", () => {
  it("exports typed functions for install, mode-aware export, sync, and increments", async () => {
    const src = await tryRead("frontend/src/services/api.ts")
    expect(src, "frontend/src/services/api.ts must exist").not.toBeNull()
    // install flow (App, not OAuth)
    expectContainsAny(
      src!,
      ["getGitHubInstallUrl", "installGitHubApp", "getGitHubInstall"],
      "api.ts must expose a GitHub App install starter",
    )
    // mode-aware export still present (extends Phase 13)
    expect(src!, "api.ts must keep exportWorkspaceToGitHub").toContain("exportWorkspaceToGitHub")
    // sync + increments
    expectContainsAny(src!, ["getGitHubSync", "getWorkspaceSync"], "api.ts must expose sync state fetch")
    expectContainsAny(src!, ["resyncWorkspace", "resyncGitHub"], "api.ts must expose resync")
    expectContainsAny(src!, ["listIncrements", "getIncrements"], "api.ts must expose increments list")
    expectContainsAny(src!, ["createIncrement"], "api.ts must expose increment creation")
  })

  it("calls the exact backend path fragments from spec §11", async () => {
    const src = await tryRead("frontend/src/services/api.ts")
    expect(src).not.toBeNull()
    for (const frag of [
      "/integrations/github",
      "/export/github",
      "/sync",
      "/sync/resync",
      "/increments",
      "/ideas",
    ]) {
      expect(src!, `api.ts must call path fragment '${frag}'`).toContain(frag)
    }
  })

  it("export request carries the export_mode union", async () => {
    const src = await tryRead("frontend/src/services/api.ts")
    expect(src).not.toBeNull()
    expectContainsAll(src!, ["files_to_default", "pr_with_tests"], "api.ts export request")
  })

  it("sync/push fetchers tolerate 404 without throwing (stale or never-pushed is normal)", async () => {
    const src = await tryRead("frontend/src/services/api.ts")
    expect(src).not.toBeNull()
    // anchor on the NEW sync fetcher specifically — getGitHubPush already exists
    // from Phase 13 and is covered by its own contract.
    const anchor = ["getGitHubSync", "getWorkspaceSync"].find((n) => src!.includes(n))
    expect(anchor, "api.ts must define a GitHub sync-state fetcher").toBeTruthy()
    const start = src!.indexOf(anchor!)
    const slice = src!.slice(start, start + 1800)
    expect(
      slice.includes("404") || slice.includes("null") || slice.includes("catch"),
      "Sync/push fetchers must map unknown/disabled/never-pushed to a safe state, not throw.",
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

describe("phase24 types/github.ts", () => {
  it("models install status, export mode, per-task sync state, drift, and increments", async () => {
    const found = await tryReadAny([
      "frontend/src/types/github.ts",
      "frontend/src/types/integration.ts",
    ])
    expect(found, "frontend/src/types/github.ts must exist").not.toBeNull()
    const { src } = found!
    expectContainsAll(src, ["files_to_default", "pr_with_tests"], "github types export_mode union")
    expectContainsAll(src, ["open", "done"], "github types task state union")
    expectContainsAll(src, ["pr_merge", "manual"], "github types done_via union")
    expectContainsAny(src, ["out_of_sync", "outOfSync"], "github types must model drift")
    expectContainsAny(src, ["Increment", "increment"], "github types must model the increment timeline")
    expectContainsAny(
      src,
      ["repository_selection", "account_login", "installation"],
      "github types must model the App installation, not just an OAuth token",
    )
  })
})

// ---------------------------------------------------------------------------
// T-275 — Task-completion panel, drift banner, disconnected state
// ---------------------------------------------------------------------------

describe("phase24 TaskCompletionPanel (sibling of CoveragePanel)", () => {
  it("exists and renders shipped/total with issue + PR deep links", async () => {
    const src = await tryRead("frontend/src/components/workspace/TaskCompletionPanel.tsx")
    expect(src, "TaskCompletionPanel.tsx must exist under components/workspace").not.toBeNull()
    expectContainsAny(src!, ["shipped", "done", "/", "completed"], "panel must show shipped/total")
    expectContainsAny(src!, ["issue", "html_url", "issueUrl", "pull", "pr"], "panel must deep-link issue/PR")
  })

  it("shows a drift banner that triggers resync when out_of_sync", async () => {
    const candidates = [
      "frontend/src/components/workspace/TaskCompletionPanel.tsx",
      "frontend/src/components/workspace/SyncStatusBanner.tsx",
      "frontend/src/pages/Workspace.tsx",
    ]
    const found = await tryReadAny(candidates)
    expect(found, "A drift/sync banner must exist").not.toBeNull()
    const { src } = found!
    expectContainsAny(src, ["out_of_sync", "outOfSync", "drift", "out of sync"], "drift banner condition")
    expectContainsAny(src, ["resync", "re-sync", "Re-sync"], "drift banner must offer resync")
  })

  it("renders a disconnected/sync-paused state when the install is removed", async () => {
    const found = await tryReadAny([
      "frontend/src/components/workspace/TaskCompletionPanel.tsx",
      "frontend/src/pages/Workspace.tsx",
      "frontend/src/pages/Settings.tsx",
    ])
    expect(found).not.toBeNull()
    expectContainsAny(
      found!.src,
      ["disconnected", "sync paused", "Sync paused", "reconnect", "suspended"],
      "UI must surface a disconnected / sync-paused state",
    )
  })
})

// ---------------------------------------------------------------------------
// Settings — GitHub App install (not OAuth token)
// ---------------------------------------------------------------------------

describe("phase24 Settings GitHub App install", () => {
  it("offers App installation and shows the installed account + repo count", async () => {
    const found = await tryReadAny([
      "frontend/src/pages/Settings.tsx",
      "frontend/src/components/settings/GitHubConnection.tsx",
    ])
    expect(found, "A Settings GitHub panel must exist").not.toBeNull()
    const { src } = found!
    expectContainsAny(src, ["Install", "Install GitHub App", "installation"], "Settings must offer App install")
    expectContainsAny(
      src,
      ["repositor", "repos", "account", "@"],
      "Settings must show the installed account / repository selection",
    )
  })
})

// ---------------------------------------------------------------------------
// Export modal — mode choice
// ---------------------------------------------------------------------------

describe("phase24 export modal mode choice", () => {
  it("exposes the files_to_default vs pr_with_tests choice", async () => {
    const found = await tryReadAny([
      "frontend/src/components/workspace/ExportGitHubModal.tsx",
      "frontend/src/pages/Workspace.tsx",
    ])
    expect(found, "The GitHub export modal must exist").not.toBeNull()
    const { src } = found!
    expectContainsAny(
      src,
      ["pr_with_tests", "PR with tests", "Pull request", "files_to_default", "export_mode"],
      "Export modal must let the user choose the export mode",
    )
  })
})
