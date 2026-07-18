import { describe, expect, it } from "vitest"

import type { ExportSummary } from "../types/github"
import {
  exportNeedsAttention,
  safeGitHubUrl,
  selectGitHubExports,
  summarizeGitHubExports,
} from "./githubHub"

function summary(
  overrides: Partial<ExportSummary> & Pick<ExportSummary, "workspace_name">,
): ExportSummary {
  const { workspace_name, ...rest } = overrides
  return {
    workspace_id: crypto.randomUUID(),
    workspace_name,
    push_id: crypto.randomUUID(),
    status: "completed",
    export_mode: "files_to_default",
    repo_full_name: null,
    repo_url: null,
    pr_number: null,
    task_sync_status: "up_to_date",
    sync_paused: false,
    out_of_sync: false,
    shipped: 0,
    total: 0,
    pushed_at: null,
    last_inbound_sync_at: null,
    ...rest,
  }
}

describe("GitHub hub view model", () => {
  const rows = [
    summary({
      workspace_name: "Atlas",
      repo_full_name: "acme/atlas",
      shipped: 2,
      total: 4,
      pushed_at: "2026-07-10T10:00:00Z",
    }),
    summary({
      workspace_name: "Beacon",
      repo_full_name: "acme/beacon",
      shipped: 8,
      total: 8,
      out_of_sync: true,
      task_sync_status: "changes_pending",
      last_inbound_sync_at: "2026-07-12T10:00:00Z",
    }),
    summary({
      workspace_name: "Cedar",
      status: "pending",
      pushed_at: "2026-07-11T10:00:00Z",
    }),
  ]

  it("summarises repositories and every actionable state", () => {
    expect(summarizeGitHubExports(rows)).toEqual({
      repositories: 3,
      shipped: 10,
      total: 12,
      attention: 1,
    })
    expect(exportNeedsAttention(rows[1])).toBe(true)
    expect(exportNeedsAttention(summary({ workspace_name: "Paused", sync_paused: true }))).toBe(true)
    expect(exportNeedsAttention(summary({ workspace_name: "Failed", status: "failed" }))).toBe(true)
  })

  it("searches both workspace and repository names and applies status filters", () => {
    expect(selectGitHubExports(rows, "ACME/ATLAS", "all", "recent")).toHaveLength(1)
    expect(selectGitHubExports(rows, "", "attention", "recent").map((row) => row.workspace_name)).toEqual(["Beacon"])
    expect(selectGitHubExports(rows, "", "syncing", "recent").map((row) => row.workspace_name)).toEqual(["Cedar"])
  })

  it("sorts deterministically by activity, name, and completion", () => {
    expect(selectGitHubExports(rows, "", "all", "recent").map((row) => row.workspace_name)).toEqual(["Cedar", "Beacon", "Atlas"])
    expect(selectGitHubExports(rows, "", "all", "name").map((row) => row.workspace_name)).toEqual(["Atlas", "Beacon", "Cedar"])
    expect(selectGitHubExports(rows, "", "all", "progress").map((row) => row.workspace_name)).toEqual(["Beacon", "Atlas", "Cedar"])
  })

  it("allows only secure external repository URLs", () => {
    expect(safeGitHubUrl("https://github.com/acme/atlas")).toBe("https://github.com/acme/atlas")
    expect(safeGitHubUrl("javascript:alert(1)")).toBeNull()
    expect(safeGitHubUrl("http://github.com/acme/atlas")).toBeNull()
    expect(safeGitHubUrl("https://example.com/acme/atlas")).toBeNull()
    expect(safeGitHubUrl("not a url")).toBeNull()
  })
})
