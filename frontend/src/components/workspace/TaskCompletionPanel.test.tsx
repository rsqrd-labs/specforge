import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { TaskCompletionPanel, type SyncConnection } from "./TaskCompletionPanel"
import type { SyncState, TaskSyncState } from "../../types/github"

function task(overrides: Partial<TaskSyncState> = {}): TaskSyncState {
  return {
    task_ref: "T-001",
    issue_number: 1,
    state: "open",
    done_via: null,
    done_at: null,
    synced_at: null,
    ...overrides,
  }
}

function syncState(overrides: Partial<SyncState> = {}): SyncState {
  const tasks = overrides.tasks ?? [
    task({ task_ref: "T-001", issue_number: 11, state: "done", done_via: "pr_merge" }),
    task({ task_ref: "T-002", issue_number: 12, state: "done", done_via: "manual" }),
    task({ task_ref: "T-003", issue_number: 13, state: "open" }),
  ]
  const shipped = overrides.shipped ?? tasks.filter((t) => t.state === "done").length
  return {
    push_id: "push-1",
    status: "completed",
    out_of_sync: false,
    shipped,
    total: overrides.total ?? tasks.length,
    tasks,
    ...overrides,
  }
}

function renderPanel(
  props: Partial<React.ComponentProps<typeof TaskCompletionPanel>> = {},
) {
  const onResync = vi.fn()
  const merged: React.ComponentProps<typeof TaskCompletionPanel> = {
    data: syncState(),
    repoFullName: "octo/spec",
    repoUrl: "https://github.com/octo/spec",
    connection: "connected" as SyncConnection,
    loading: false,
    resyncing: false,
    onResync,
    ...props,
  }
  return {
    onResync,
    ...render(
      <MemoryRouter>
        <TaskCompletionPanel {...merged} />
      </MemoryRouter>,
    ),
  }
}

describe("TaskCompletionPanel", () => {
  it("renders the shipped/total progress and per-task issue deep links", () => {
    renderPanel()

    expect(screen.getByText(/2 of 3 tasks shipped/i)).toBeInTheDocument()
    const progress = screen.getByRole("progressbar")
    expect(progress).toHaveAttribute("aria-valuenow", "2")
    expect(progress).toHaveAttribute("aria-valuemax", "3")

    const issueLink = screen.getByRole("link", { name: /issue #11/i })
    expect(issueLink).toHaveAttribute(
      "href",
      "https://github.com/octo/spec/issues/11",
    )
  })

  it("marks a merged-PR task with the via-PR (lotus) accent", () => {
    const { container } = renderPanel()
    // T-001 closed via pr_merge → lotus check + 'via PR' label.
    expect(screen.getByText("via PR")).toBeInTheDocument()
    expect(container.querySelector(".ws-sync-check.done.via-pr")).not.toBeNull()
  })

  it("shows the drift banner and triggers resync when out_of_sync", async () => {
    const user = userEvent.setup()
    const { onResync } = renderPanel({ data: syncState({ out_of_sync: true }) })

    expect(screen.getByText(/tasks changed since the last push/i)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /re-sync changed tasks/i }))
    expect(onResync).toHaveBeenCalledOnce()
  })

  it("folds to a sync-paused line when the install is suspended", () => {
    renderPanel({ connection: "suspended" })

    expect(screen.getByText(/sync paused/i)).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /reconnect github/i }),
    ).toHaveAttribute("href", "/settings")
    // The progress hero is not rendered in the disconnected fold.
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument()
  })

  it("renders a two-row skeleton on first load (no spinner)", () => {
    const { container } = renderPanel({ data: null, loading: true })

    expect(container.querySelector(".ws-sync-skeleton")).not.toBeNull()
    expect(container.querySelectorAll(".ws-sync-skeleton-row")).toHaveLength(2)
  })

  it("renders nothing for a workspace that was never pushed", () => {
    const { container } = renderPanel({ data: null, loading: false })
    expect(container.firstChild).toBeNull()
  })

  it("highlights only true open→done transitions, not rows already shipped on mount", () => {
    const { container, rerender } = renderPanel({
      data: syncState({
        tasks: [
          task({ task_ref: "T-001", issue_number: 11, state: "done", done_via: "manual" }),
          task({ task_ref: "T-002", issue_number: 12, state: "open" }),
        ],
      }),
    })
    // Nothing flashes on the first render — the baseline is just established.
    expect(container.querySelector(".ws-sync-task.just-shipped")).toBeNull()

    // T-002 flips to done on the next poll → it (and only it) highlights once.
    rerender(
      <MemoryRouter>
        <TaskCompletionPanel
          data={syncState({
            tasks: [
              task({ task_ref: "T-001", issue_number: 11, state: "done", done_via: "manual" }),
              task({ task_ref: "T-002", issue_number: 12, state: "done", done_via: "manual" }),
            ],
          })}
          repoFullName="octo/spec"
          repoUrl="https://github.com/octo/spec"
          connection="connected"
          loading={false}
          resyncing={false}
          onResync={vi.fn()}
        />
      </MemoryRouter>,
    )
    const flashed = container.querySelectorAll(".ws-sync-task.just-shipped")
    expect(flashed).toHaveLength(1)
    expect(flashed[0].textContent).toContain("T-002")
  })
})
