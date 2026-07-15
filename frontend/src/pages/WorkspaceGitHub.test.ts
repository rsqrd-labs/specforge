import { describe, expect, it } from "vitest"

import { exportTone } from "../components/github/ExportStatusBadge"
import { taskSyncPresentation } from "./WorkspaceGitHub"

describe("WorkspaceGitHub task sync presentation", () => {
  it("describes version alignment without claiming issue-content equality", () => {
    expect(taskSyncPresentation("completed", "up_to_date", false)).toEqual({
      value: "Up to date",
      detail: "Current Tasks version is on GitHub",
    })
  })

  it("keeps task changes separate from a paused GitHub connection", () => {
    expect(taskSyncPresentation("stale", "changes_pending", true)).toEqual({
      value: "Sync paused",
      detail: "Reconnect GitHub to resume",
    })
    expect(exportTone("stale", false, true)).toBe("paused")
  })

  it("makes changed and legacy-unknown states explicit", () => {
    expect(taskSyncPresentation("completed", "changes_pending", false).value).toBe(
      "Changes pending",
    )
    expect(taskSyncPresentation("completed", "unknown", false).value).toBe(
      "Not verified",
    )
    expect(exportTone("completed", false, false, "unknown")).toBe("exported")
  })
})
